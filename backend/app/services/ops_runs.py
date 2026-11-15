"""最小运行记录写入：独立受理与观察，批次完成参与调用方事务。

本模块不接收正文或异常，不调用模型、Redis 或 Phoenix 导出器。
complete_in_transaction 不提交、回滚或关闭调用方 Session；调用方须先 flush 批次及题目。
"""
from collections.abc import Callable
from datetime import datetime, timezone
import re

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Bank, ChatSession, Document, GenerationBatch, OpsRun, Question, User
from app.models.base import new_id, utcnow
from app.models.ops_run import RunEntrypoint, RunErrorCode, RunStatus
from app.services.phoenix_tracing import current_run_id

_IDENTIFIER = re.compile(r"[a-zA-Z0-9_.:-]{1,40}\Z")
_UNKNOWN_CODES = {RunErrorCode.EXECUTION_INTERRUPTED, RunErrorCode.OUTCOME_UNKNOWN}
_FAILURE_CODES = set(RunErrorCode) - _UNKNOWN_CODES - {RunErrorCode.USER_CANCELED}
_TERMINAL = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELED}


class RunConflictError(ValueError):
    """关联不一致、非法转换或并发写冲突；错误信息不包含业务值。"""


def _identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError("运行关联标识必须为 1–40 位安全字符")
    return value


def _at(value: datetime | None) -> datetime:
    value = value if value is not None else utcnow()
    if value.utcoffset() is None:
        raise ValueError("运行时间必须带时区")
    return value.astimezone(timezone.utc)


def _code(value: RunErrorCode) -> RunErrorCode:
    try:
        return RunErrorCode(value)
    except (TypeError, ValueError):
        raise ValueError("错误分类不在安全白名单内") from None


def _load(db: Session, run_id: str) -> OpsRun:
    row = db.get(OpsRun, _identifier(run_id), populate_existing=True)
    if row is None:
        raise RunConflictError("运行记录不存在")
    return row


def _write(
    db: Session, row: OpsRun, status: RunStatus, at: datetime, *,
    started_at: datetime | None = None, finished_at: datetime | None = None,
    batch_id: str | None = None, delivered_count: int | None = None,
    error_code: RunErrorCode | None = None,
) -> None:
    # 比较并交换，防止另一 Session 已确认的状态被旧观察覆盖。
    result = db.execute(
        update(OpsRun).where(
            OpsRun.run_id == row.run_id,
            OpsRun.status == row.status,
            OpsRun.last_observed_at == row.last_observed_at,
        ).values(
            status=status.value, started_at=started_at, finished_at=finished_at,
            batch_id=batch_id, delivered_count=delivered_count,
            error_code=error_code.value if error_code else None, last_observed_at=at,
        ).returning(OpsRun.run_id).execution_options(synchronize_session=False)
    )
    if result.scalar_one_or_none() is None:
        raise RunConflictError("运行观察发生并发冲突，请回滚后重新读取")
    db.expire(row)


class RunLedger:
    """集中维护运行事实；独立方法使用自己的短事务，完成写入由调用方提交。

调用方在受理前完成鉴权及资源访问校验。本模块校验关联一致性，不替代路由鉴权。
同一 run_id 的重放只认相同受理事实；新的实际受理必须使用新的 ID。
"""

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        self._sessions = session_factory

    def accept(
        self, *, entrypoint: RunEntrypoint, owner_user_id: str, bank_id: str,
        document_id: str, requested_count: int, session_id: str | None = None,
        task_id: str | None = None, run_id: str | None = None,
        observed_at: datetime | None = None,
    ) -> str:
        """独立提交受理，优先使用显式 ID、当前追踪 ID，否则独立生成 ID。"""
        try:
            entrypoint = RunEntrypoint(entrypoint)
        except (TypeError, ValueError):
            raise ValueError("出题入口不在允许范围内") from None
        run_id = _identifier(
            run_id if run_id is not None else (current_run_id() or new_id("run"))
        )
        if type(requested_count) is not int or requested_count <= 0:
            raise ValueError("请求数量必须是正整数")
        fields = {
            "entrypoint": entrypoint.value, "owner_user_id": _identifier(owner_user_id),
            "bank_id": _identifier(bank_id), "document_id": _identifier(document_id),
            "requested_count": requested_count,
            "session_id": _identifier(session_id) if session_id is not None else None,
            "task_id": _identifier(task_id) if task_id is not None else None,
        }
        if ((entrypoint == RunEntrypoint.CONVERSATION
             and (session_id is None or task_id is not None))
                or (entrypoint == RunEntrypoint.PARAMETERIZED and session_id is not None)):
            raise ValueError("入口与会话或任务关联不一致")
        at = _at(observed_at)

        def same(row: OpsRun) -> bool:
            return all(getattr(row, key) == value for key, value in fields.items())

        try:
            with self._sessions() as db, db.begin():
                row = db.get(OpsRun, run_id)
                if row is not None:
                    if not same(row):
                        raise RunConflictError("重复受理与已有运行关联不一致")
                    return run_id
                doc = db.get(Document, document_id)
                if (db.get(User, owner_user_id) is None or db.get(Bank, bank_id) is None
                        or doc is None or doc.bank_id != bank_id):
                    raise RunConflictError("受理账号或资源关联不存在或不一致")
                if session_id is not None:
                    session = db.get(ChatSession, session_id)
                    if (session is None or session.user_id != owner_user_id
                            or session.bank_id != bank_id or session.document_id != document_id):
                        raise RunConflictError("会话与受理账号或资源不一致")
                db.add(OpsRun(
                    run_id=run_id, **fields, status=RunStatus.ACCEPTED.value,
                    accepted_at=at, last_observed_at=at,
                ))
        except IntegrityError:
            # 唯一约束处理并发相同受理；不能将另一个账号或任务的冲突视作重放。
            with self._sessions() as db:
                row = db.get(OpsRun, run_id)
                if row is None or not same(row):
                    raise RunConflictError("运行标识或任务关联冲突") from None
        return run_id

    def start(self, run_id: str, *, observed_at: datetime | None = None) -> None:
        """独立记录执行器已开始；重复开始不是心跳，不刷新观察时间。"""
        at = _at(observed_at)
        with self._sessions() as db, db.begin():
            row = _load(db, run_id)
            if at < row.last_observed_at or row.status in {RunStatus.RUNNING, RunStatus.COMPLETED}:
                return
            if row.status in _TERMINAL:
                raise RunConflictError("已确认停止的运行不能再次开始")
            _write(db, row, RunStatus.RUNNING, at, started_at=row.started_at or at)

    def complete_in_transaction(
        self, db: Session, run_id: str, *, batch_id: str,
        observed_at: datetime | None = None,
    ) -> None:
        """关联已 flush 的批次及题目，与调用方同事务提交；回滚时完成事实一起撤销。

        数量取当前事务内已写入题目数并与批次数量核对。调用返回尚不证明提交成功。
        已完成的相同批次重放保持原快照，即使之后题目或批次已删除。
        """
        at = _at(observed_at)
        _identifier(batch_id)
        if not db.in_transaction():
            raise RunConflictError("批次完成必须参与调用方已有事务")
        with db.no_autoflush:
            if any(isinstance(obj, (GenerationBatch, Question))
                   for obj in (*db.new, *db.dirty, *db.deleted)):
                raise RunConflictError("请先 flush 全部批次和题目变更")
            row = _load(db, run_id)
            if row.status == RunStatus.COMPLETED:
                if row.batch_id != batch_id:
                    raise RunConflictError("运行已关联其他批次")
                return
            if at < row.last_observed_at:
                raise RunConflictError("批次完成时间早于已有观察")
            if row.status not in {RunStatus.RUNNING, RunStatus.UNKNOWN} or row.started_at is None:
                raise RunConflictError("批次完成需要已开始且未确认停止的运行")
            batch = db.get(GenerationBatch, batch_id, populate_existing=True)
            if (batch is None or batch.user_id != row.owner_user_id or batch.bank_id != row.bank_id
                    or batch.document_id != row.document_id or batch.status != "done"):
                raise RunConflictError("批次与运行账号或资源不一致")
            count = db.scalar(select(func.count()).select_from(Question).where(
                Question.batch_id == batch_id
            ))
            if count != batch.question_count or count is None:
                raise RunConflictError("批次数量与已写入题目不一致，请先 flush 全部业务行")
            _write(db, row, RunStatus.COMPLETED, at, started_at=row.started_at,
                   finished_at=at, batch_id=batch_id, delivered_count=count)

    def fail(
        self, run_id: str, *, error_code: RunErrorCode = RunErrorCode.EXECUTION_ERROR,
        observed_at: datetime | None = None,
    ) -> None:
        """调用方已确认失败且没有保存批次；业务事务须先回滚。"""
        code = _code(error_code)
        if code not in _FAILURE_CODES:
            raise ValueError("失败必须使用有限失败分类")
        self._stop(run_id, RunStatus.FAILED, code, _at(observed_at))

    def cancel(self, run_id: str, *, observed_at: datetime | None = None) -> None:
        """执行器已确认停止且未保存批次；暂停请求本身不能调用本方法。"""
        self._stop(run_id, RunStatus.CANCELED, RunErrorCode.USER_CANCELED, _at(observed_at))

    def unknown(
        self, run_id: str, *, error_code: RunErrorCode = RunErrorCode.OUTCOME_UNKNOWN,
        observed_at: datetime | None = None,
    ) -> None:
        """记录提交结果不明或中断观察，不检测中断，不伪造结束时间。"""
        code = _code(error_code)
        if code not in _UNKNOWN_CODES:
            raise ValueError("未知必须使用中断或结果不明分类")
        self._stop(run_id, RunStatus.UNKNOWN, code, _at(observed_at))

    def _stop(self, run_id: str, status: RunStatus, code: RunErrorCode, at: datetime) -> None:
        with self._sessions() as db, db.begin():
            row = _load(db, run_id)
            if at < row.last_observed_at or row.status == RunStatus.COMPLETED:
                return
            if row.status == status and row.error_code == code:
                return
            if row.status in _TERMINAL:
                raise RunConflictError("已确认终态不能被另一停止观察覆盖")
            _write(
                db, row, status, at, started_at=row.started_at,
                finished_at=None if status == RunStatus.UNKNOWN else at,
                delivered_count=None if status == RunStatus.UNKNOWN else 0, error_code=code,
            )
