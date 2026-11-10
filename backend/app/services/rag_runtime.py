"""为一次检索固定模型与索引版本，避免切换中出现新向量查询旧索引。"""
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from functools import wraps
import json
from typing import ParamSpec, TypeVar

from app.config import settings
from app.db import SessionLocal
from app.models.rag_setting import RagSetting


@dataclass(frozen=True)
class RuntimeConfig:
    """不可变的系统模型配置；凭据不进入 repr 或对外响应。"""

    embedding_model: str = "BAAI/bge-m3"
    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_api_key: str | None = field(default=None, repr=False)
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_base_url: str = "https://api.siliconflow.cn/v1"
    rerank_api_key: str | None = field(default=None, repr=False)

    def serialize(self) -> str:
        """仅供 SQL 持久化使用，不得输出到响应或日志。"""
        return json.dumps(asdict(self), ensure_ascii=False)


@dataclass(frozen=True)
class RuntimeSnapshot:
    """模型及与其兼容的 Chroma collection 后缀。"""

    config: RuntimeConfig
    generation: str = ""


_current: ContextVar[RuntimeSnapshot | None] = ContextVar("rag_runtime", default=None)
P = ParamSpec("P")
R = TypeVar("R")


def decode_config(value: str | None) -> RuntimeConfig:
    """没有平台覆盖时继续使用当前部署地址与既有凭据兜底。"""
    defaults = RuntimeConfig(
        embedding_base_url=settings.siliconflow_base_url,
        rerank_base_url=settings.siliconflow_base_url,
    )
    return RuntimeConfig(**(asdict(defaults) | json.loads(value or "{}")))


def current_snapshot() -> RuntimeSnapshot:
    """返回调用上下文的快照；独立调用从 SQL 读取当前版本。"""
    existing = _current.get()
    if existing is not None:
        return existing
    with SessionLocal() as db:
        row = db.get(RagSetting, 1)
        return RuntimeSnapshot(
            decode_config(row.active_json if row else None), row.generation if row else ""
        )


@contextmanager
def use_snapshot(snapshot: RuntimeSnapshot | None = None) -> Iterator[RuntimeSnapshot]:
    """嵌套调用复用快照；重建显式指定新版本，退出后恢复调用方上下文。"""
    chosen = snapshot or current_snapshot()
    token = _current.set(chosen)
    try:
        yield chosen
    finally:
        _current.reset(token)


def with_snapshot(function: Callable[P, R]) -> Callable[P, R]:
    """同步业务入口固定一次模型与索引读取，保留原函数签名。"""
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        with use_snapshot():
            return function(*args, **kwargs)
    return wrapped
