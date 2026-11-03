"""全局配置，从 backend/.env 读取。密钥只存在于环境变量与 local_secrets.py，绝不进 git。"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    # 数据库与缓存
    database_url: str = "sqlite:///./data/mathcraft.db"
    redis_url: str = "redis://127.0.0.1:6379/0"
    session_ttl_seconds: int = 604800        # 登录会话 7 天
    generate_task_ttl_seconds: int = 1800    # 出题任务 30 分钟
    chat_session_ttl_seconds: int = 7200     # 对话槽位 2 小时
    ingest_task_ttl_seconds: int = 7200      # 文档入库任务 2 小时

    # DeepSeek（密钥优先取用户配置，环境变量仅作脚本与调试兜底）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_display_name: str = "DeepSeek Flash"

    # 硅基流动（向量与重排，密钥在 app/local_secrets.py，不提供配置入口）
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"

    # 存储
    chroma_dir: str = "data/chroma"
    upload_dir: str = "data/uploads"
    ocr_dir: str = "data/ocr"
    avatar_dir: str = "data/avatars"
    max_upload_mb: int = 200
    max_avatar_mb: int = 5

    # 检索与切片（混合检索参数，详见 v2 文档 6.5）
    top_k: int = 6
    dense_top_k: int = 20
    sparse_top_k: int = 20
    fused_top_k: int = 12
    rerank_top_k: int = 6
    rrf_k: int = 60
    chunk_size: int = 500
    chunk_overlap: int = 100

    # CORS
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    def chroma_path(self) -> Path:
        p = BASE_DIR / self.chroma_dir
        p.mkdir(parents=True, exist_ok=True)
        return p

    def upload_path(self) -> Path:
        p = BASE_DIR / self.upload_dir
        p.mkdir(parents=True, exist_ok=True)
        return p

    def ocr_path(self) -> Path:
        p = BASE_DIR / self.ocr_dir
        p.mkdir(parents=True, exist_ok=True)
        return p

    def avatar_path(self) -> Path:
        p = BASE_DIR / self.avatar_dir
        p.mkdir(parents=True, exist_ok=True)
        return p

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
