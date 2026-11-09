"""全局配置，从 backend/.env 读取。密钥只存在于环境变量与 local_secrets.py，绝不进 git。"""
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import model_validator

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", extra="ignore", hide_input_in_errors=True,
    )

    # 认证部署配置：缺失密钥时认证入口 fail closed，绝不提供默认密钥。
    app_env: str = "production"
    admin_contact: str = "请联系学校或平台管理员获取账号、重置密码或处理账号问题。"
    auth_jwt_secret: str = ""
    auth_jwt_issuer: str = "mathcraft"
    auth_jwt_audience: str = "mathcraft-web"
    auth_access_ttl_seconds: int = 900
    auth_refresh_ttl_seconds: int = 604800
    auth_code_secret: str = ""
    auth_code_ttl_seconds: int = 300
    auth_code_max_attempts: int = 5
    auth_code_retry_seconds: int = 60
    auth_code_email_hour_limit: int = 5
    auth_code_ip_hour_limit: int = 30
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_tls_mode: str = "starttls"
    smtp_timeout_seconds: float = 10
    turnstile_enabled: bool = True
    turnstile_site_key: str = ""
    turnstile_secret_key: str = ""
    turnstile_allowed_hostnames: str = ""
    turnstile_timeout_seconds: float = 10
    dev_accounts_enabled: bool = False
    dev_teacher_email: str = ""
    dev_teacher_user_no: str = ""
    dev_teacher_password: str = ""
    dev_teacher_display_name: str = ""
    dev_student_email: str = ""
    dev_student_user_no: str = ""
    dev_student_password: str = ""
    dev_student_display_name: str = ""

    @model_validator(mode="after")
    def validate_auth_configuration(self) -> "Settings":
        """拒绝危险环境、通配 CORS、无效有效期及生产开发配置。"""
        if self.app_env not in {"development", "test", "production"}:
            raise ValueError("APP_ENV 必须为 development/test/production")
        origins = self.cors_origin_list()
        for origin in origins:
            parsed = urlsplit(origin)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username or parsed.password or parsed.path
                    or parsed.query or parsed.fragment or "*" in origin):
                raise ValueError("CORS_ORIGINS 必须为无路径的精确 HTTP Origin")
        limits = (self.auth_access_ttl_seconds, self.auth_refresh_ttl_seconds,
                  self.auth_code_ttl_seconds, self.auth_code_max_attempts,
                  self.auth_code_retry_seconds, self.auth_code_email_hour_limit,
                  self.auth_code_ip_hour_limit, self.smtp_timeout_seconds,
                  self.turnstile_timeout_seconds, self.max_avatar_mb)
        if any(value <= 0 for value in limits):
            raise ValueError("认证有效期、限额及超时必须为正数")
        if self.smtp_tls_mode not in {"tls", "starttls"}:
            raise ValueError("SMTP_TLS_MODE 必须为 tls/starttls")
        if not 1 <= self.smtp_port <= 65535:
            raise ValueError("SMTP_PORT 无效")
        if self.auth_jwt_secret and len(self.auth_jwt_secret.encode()) < 32:
            raise ValueError("AUTH_JWT_SECRET 至少需要 32 字节")
        if self.auth_code_secret and len(self.auth_code_secret.encode()) < 32:
            raise ValueError("AUTH_CODE_SECRET 至少需要 32 字节")
        if self.auth_jwt_secret and self.auth_jwt_secret == self.auth_code_secret:
            raise ValueError("验证码与 JWT 必须使用独立密钥")
        if self.app_env == "production":
            if not self.turnstile_enabled:
                raise ValueError("生产环境禁止关闭人机验证")
            if any(getattr(self, f"dev_{role}_{field}")
                   for role in ("teacher", "student")
                   for field in ("email", "user_no", "password", "display_name")):
                raise ValueError("生产环境禁止配置开发账号凭据")
            if self.dev_accounts_enabled:
                raise ValueError("生产环境禁止开发账号能力")
            if (self.turnstile_site_key.startswith(("1x", "2x", "3x"))
                    or self.turnstile_secret_key.startswith(("1x", "2x", "3x"))):
                raise ValueError("生产环境禁止 Turnstile 测试密钥")
        return self

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
    # 单次模型调用超时；SDK 内部重试已关闭，避免超时被放大成十几分钟
    llm_timeout_seconds: int = 300

    # 硅基流动（向量与重排，密钥在 app/local_secrets.py，不提供配置入口）
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"

    # 存储
    chroma_dir: str = "data/chroma"
    upload_dir: str = "data/uploads"
    ocr_dir: str = "data/ocr"
    avatar_dir: str = "data/avatars"
    max_upload_mb: int = 200
    max_avatar_mb: int = 5

    # 出题中间件：语义查重阈值、换模板重出轮数、查重语料上限
    review_similarity_threshold: float = 0.92
    review_max_regen_rounds: int = 1
    review_corpus_limit: int = 300

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
