"""静态加密存储：平台级模型凭据以 Fernet 对称加密落库。

主密钥管理：首次使用时自动生成并写入 backend/data/secret.key（data 目录不入库），
文件丢失即密文不可解——轮换凭据重新保存即可恢复服务。
设计取向：密钥永远不以明文进入代码仓库或 .env 文件。
"""
import secrets
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_SECRET_FILE = Path(settings.upload_path()).parent / "secret.key"


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    """加载（或首次生成）Fernet 主密钥。"""
    path = Path(_SECRET_FILE)
    if path.exists():
        key = path.read_text(encoding="utf-8").strip()
        if key:
            return Fernet(key.encode("utf-8"))
    key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key.decode("utf-8"), encoding="utf-8")
    try:
        path.chmod(0o600)  # Windows 下尽力而为，失败不影响功能
    except OSError:
        pass
    return Fernet(key)


def encrypt_secret(plain: str) -> str:
    """明文 → 密文（含时间戳，可校验完整性）。"""
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_secret(cipher: str) -> str | None:
    """密文 → 明文；密文损坏或主密钥不匹配返回 None（调用方回退默认凭据）。"""
    if not cipher:
        return None
    try:
        return _fernet().decrypt(cipher.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def mask_secret(plain: str | None) -> str:
    """掩码展示：只露末 4 位。"""
    if not plain:
        return ""
    return "****" + plain[-4:] if len(plain) > 8 else "****"


# 占位值：前端回传该值表示"保持原 key 不变"
MASK_PLACEHOLDER = "__KEEP__"


def random_token(n: int = 32) -> str:
    return secrets.token_hex(n)
