"""Redis 客户端封装。键设计见 v2 文档第 10 节。"""
from functools import lru_cache

import redis

from app.config import settings

PREFIX_AUTH_TOKEN = "auth:token:"
PREFIX_AUTH_USER_TOKENS = "auth:user:{user_id}:tokens"
PREFIX_GEN_TASK = "gen:task:{task_id}"
PREFIX_GEN_LOCK = "gen:lock:{user_id}"
PREFIX_INGEST_TASK = "ingest:task:{document_id}"
PREFIX_INGEST_LOCK = "ingest:lock:{document_id}"
PREFIX_CHAT_SESSION = "chat:session:{session_id}"
PREFIX_HYDE = "rag:hyde:{digest}"
PREFIX_CACHE_BANK_DOCS = "cache:bank:{bank_id}:documents"


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)
