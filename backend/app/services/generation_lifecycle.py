"""实际出题的台账接点：受理、执行观察、批次事务和当前进程退出封口。"""
from collections.abc import Iterator
from contextlib import contextmanager
from _thread import LockType
import logging
from threading import Lock

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models.ops_run import RunEntrypoint, RunErrorCode
from app.schemas.question import GenerateParams
from app.services.ops_runs import RunLedger

logger = logging.getLogger(__name__)
_guard = Lock()
_active: dict[str, RunLedger] = {}
_turns: dict[str, LockType] = {}


def error_code(exc: Exception) -> RunErrorCode:
    """仅按异常类型分类，不解析异常全文或用户回复。"""
    from httpx import HTTPError
    from openai import APIError

    from app.services.rag.embeddings import EmbeddingError
    from app.services.rag.llm import LLMError
    from app.services.rag.question_gen import NeedConfirmError, QuestionOutputError
    from app.services.rag.vectorstore import VectorStoreError

    if isinstance(exc, NeedConfirmError):
        return RunErrorCode.NEED_CONFIRM
    if isinstance(exc, (EmbeddingError, VectorStoreError)):
        return RunErrorCode.RETRIEVAL_ERROR
    if isinstance(exc, (LLMError, APIError, HTTPError)):
        return RunErrorCode.MODEL_ERROR
    if isinstance(exc, SQLAlchemyError):
        return RunErrorCode.PERSISTENCE_ERROR
    if isinstance(exc, (QuestionOutputError, ValueError)):
        return RunErrorCode.GENERATION_ERROR
    return RunErrorCode.EXECUTION_ERROR


def rollback_business(db: Session) -> bool:
    """回滚调用方业务事务；无法确认回滚时只记录安全类别。"""
    try:
        db.rollback()
    except SQLAlchemyError:
        logger.error("Generation transaction rollback unavailable")
        return False
    return True


class GenerationRun:
    """一轮实际出题的结构化事实；不持有提示词、模型正文或凭据。"""

    def __init__(
        self, entrypoint: RunEntrypoint, owner_user_id: str, bank_id: str, document_id: str,
        *, session_id: str | None = None, task_id: str | None = None,
        run_id: str | None = None, ledger: RunLedger | None = None,
    ) -> None:
        self.run_id = run_id
        self._ledger = ledger if ledger is not None else RunLedger()
        self._entrypoint = entrypoint
        self._owner = owner_user_id
        self._bank = bank_id
        self._document = document_id
        self._session = session_id
        self._task = task_id
        self._settled = False

    def accept(self, params: GenerateParams) -> str:
        """独立持久化已校验的实际受理，后台提交在此后进行。"""
        self.run_id = self._ledger.accept(
            entrypoint=self._entrypoint, owner_user_id=self._owner, bank_id=self._bank,
            document_id=self._document, session_id=self._session, task_id=self._task,
            run_id=self.run_id, requested_count=sum(item.count for item in params.types),
        )
        with _guard:
            _active[self.run_id] = self._ledger
        return self.run_id

    def begin(self, params: GenerateParams) -> None:
        """有效参数齐备并决定生成时受理；执行器真正开始时记录 running。"""
        self._ledger.start(self.accept(params))

    def complete_in_transaction(self, db: Session, batch_id: str) -> None:
        """只参加批次事务；调用方仍负责 commit。"""
        if self.run_id is None:
            raise ValueError("批次保存前必须受理实际出题")
        self._ledger.complete_in_transaction(db, self.run_id, batch_id=batch_id)

    def committed(self) -> None:
        """批次事务已确认提交，后续回复或进度错误不改变保存事实。"""
        self._settled = True
        self._forget()

    def fail(self, code: RunErrorCode) -> None:
        """有明确失败证据且未保存批次时调用。"""
        if self.run_id is not None and not self._settled:
            self._ledger.fail(self.run_id, error_code=code)
            self._settled = True
            self._forget()

    def cancel(self) -> None:
        """执行检查点已确认停止；暂停 HTTP 请求本身不调用此方法。"""
        if self.run_id is not None and not self._settled:
            self._ledger.cancel(self.run_id)
            self._settled = True
            self._forget()

    def unknown(self, code: RunErrorCode = RunErrorCode.OUTCOME_UNKNOWN) -> None:
        """提交结果不明或确认发生执行中断；不被外层通用异常改成失败。"""
        if self.run_id is not None and not self._settled:
            self._settled = True
            try:
                self._ledger.unknown(self.run_id, error_code=code)
            finally:
                self._forget()

    @contextmanager
    def observe(self, db: Session | None = None) -> Iterator[None]:
        """集中收尾；吞掉异常的业务分支须显式提供确认或取消事实。"""
        try:
            yield
        except BaseException as exc:
            rolled_back = db is None or rollback_business(db)
            try:
                if not rolled_back:
                    self.unknown()
                elif isinstance(exc, Exception):
                    self.fail(error_code(exc))
                else:
                    self.unknown(RunErrorCode.EXECUTION_INTERRUPTED)
            except (SQLAlchemyError, ValueError):
                logger.error("Generation outcome could not be recorded")
            raise
        else:
            self.fail(RunErrorCode.NO_PERSISTABLE_QUESTIONS)
        finally:
            self._forget()

    def _forget(self) -> None:
        if self.run_id is not None:
            with _guard:
                _active.pop(self.run_id, None)


@contextmanager
def conversation_turn(session_id: str) -> Iterator[None]:
    """单 worker 内同会话互斥；调用方先验证会话归属，避免泄露他人活动。"""
    with _guard:
        lock = _turns.setdefault(session_id, Lock())
        if not lock.acquire(blocking=False):
            raise AppError("CHAT_BUSY", "当前对话正在处理消息，请稍后再试", status_code=409)
    try:
        yield
    finally:
        with _guard:
            lock.release()
            _turns.pop(session_id, None)


def mark_active_unknown() -> None:
    """仅封口当前进程登记的在途运行，不扫描其他进程或历史非终态记录。"""
    with _guard:
        pending = list(_active.items())
        _active.clear()
    for run_id, ledger in pending:
        try:
            ledger.unknown(run_id, error_code=RunErrorCode.EXECUTION_INTERRUPTED)
        except (SQLAlchemyError, ValueError):
            logger.error("Generation shutdown observation unavailable")
