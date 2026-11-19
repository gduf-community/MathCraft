"""导入全部模型，供 Alembic autogenerate 与 create_all 使用。"""
from app.models.auth import AuthProof, AuthSession, EmailChange, RefreshUse
from app.models.bank import Bank, BankMember, Document, DocumentChunk
from app.models.chat import ChatMessage, ChatRequest, ChatSession
from app.models.deletion import DeletionOperation
from app.models.favorite import Favorite, FavoriteGroup
from app.models.generation_task import GenerationTask
from app.models.notification import Notification
from app.models.ops_run import OpsRun
from app.models.paper import (
    AttemptAnswer,
    Paper,
    PaperAttempt,
    PaperPublication,
    PaperQuestion,
    PaperUrge,
    UrgeReadState,
)
from app.models.question import GenerationBatch, Question
from app.models.platform_llm import PlatformLlmSetting
from app.models.rag_setting import RagSetting
from app.models.space import SpaceMember, StudySpace
from app.models.user import User, UserModelSetting

__all__ = [
    "AuthProof", "AuthSession", "EmailChange", "RefreshUse",
    "Bank", "BankMember", "Document", "DocumentChunk",
    "ChatMessage", "ChatRequest", "ChatSession",
    "DeletionOperation", "GenerationTask",
    "Favorite", "FavoriteGroup",
    "Notification",
    "OpsRun",
    "Paper", "PaperAttempt", "PaperPublication", "PaperQuestion", "AttemptAnswer",
    "PaperUrge", "UrgeReadState",
    "GenerationBatch", "Question",
    "PlatformLlmSetting",
    "RagSetting",
    "SpaceMember", "StudySpace",
    "User", "UserModelSetting",
]
