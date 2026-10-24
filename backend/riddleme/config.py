"""全局配置，从 backend/.env 读取。密钥只存在于环境变量，绝不进代码与 git。"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # Ollama 向量模型
    ollama_base_url: str = "http://localhost:11434"
    embed_model: str = "qwen3-embedding:0.6b"
    embed_dim: int = 1024

    # 存储
    chroma_dir: str = "data/chroma"
    upload_dir: str = "data/uploads"

    # 检索与切片
    top_k: int = 6
    chunk_size: int = 500
    chunk_overlap: int = 100

    def chroma_path(self) -> Path:
        p = BASE_DIR / self.chroma_dir
        p.mkdir(parents=True, exist_ok=True)
        return p

    def upload_path(self) -> Path:
        p = BASE_DIR / self.upload_dir
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
