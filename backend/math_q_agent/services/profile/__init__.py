"""Independent single-tenant profile persistence and safe avatar replacement."""

import os
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

from math_q_agent.runtime.home import get_runtime_data_root
from schemas.profile import UserProfile, UserProfileUpdate

MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_AVATAR_SIDE = 4096


class InvalidAvatar(ValueError):
    """An upload fails the public avatar policy."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class ProfileService:
    """Resolve the runtime home per instance; keep no personal data in process globals."""

    def __init__(self):
        self.directory = get_runtime_data_root() / "user" / "profile"

    def read(self) -> UserProfile:
        record = self.directory / "profile.json"
        try:
            payload = record.read_bytes()
        except FileNotFoundError:
            return UserProfile(avatar_url=self.avatar_url)
        details = UserProfileUpdate.model_validate_json(payload)
        return UserProfile(**details.model_dump(), avatar_url=self.avatar_url)

    def update(self, details: UserProfileUpdate) -> UserProfile:
        profile = UserProfile(**details.model_dump(), avatar_url=self.avatar_url)
        self._replace("profile.json", details.model_dump_json().encode("utf-8"))
        return profile

    def _replace(self, name: str, payload: bytes) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(dir=self.directory, prefix=".pending-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / name)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @property
    def avatar_url(self) -> str | None:
        try:
            return _versioned_avatar_url(self.read_avatar())
        except FileNotFoundError:
            return None

    def read_avatar(self) -> bytes:
        return (self.directory / "avatar.png").read_bytes()

    def save_avatar(self, payload: bytes, filename: str | None, content_type: str | None) -> UserProfile:
        from PIL import Image, UnidentifiedImageError

        if len(payload) > MAX_AVATAR_BYTES:
            raise InvalidAvatar("头像文件不能超过 5 MiB", status_code=413)
        if not filename or any(char in filename for char in "/\\:\x00"):
            raise InvalidAvatar("头像文件名不能包含路径")
        formats = {".png": ("PNG", "image/png"), ".jpg": ("JPEG", "image/jpeg"),
                   ".jpeg": ("JPEG", "image/jpeg"), ".webp": ("WEBP", "image/webp")}
        expected = formats.get(Path(filename).suffix.lower())
        if expected is None or content_type != expected[1]:
            raise InvalidAvatar("仅支持类型与扩展名一致的 PNG、JPEG、WebP 图片")
        profile = self.read()
        output = BytesIO()
        try:
            with Image.open(BytesIO(payload), formats=[expected[0]]) as source:
                width, height = source.size
                if not (0 < width <= MAX_AVATAR_SIDE and 0 < height <= MAX_AVATAR_SIDE):
                    raise InvalidAvatar("头像宽高必须在 1 至 4096 像素之间")
                if getattr(source, "n_frames", 1) != 1:
                    raise InvalidAvatar("头像必须是静态图片")
                source.verify()
            with Image.open(BytesIO(payload), formats=[expected[0]]) as source:
                source.load()
                # A fresh bitmap removes EXIF, arbitrary chunks and trailing executable bytes.
                clean = Image.new("RGBA", source.size)
                clean.paste(source.convert("RGBA"))
                clean.save(output, format="PNG")
        except InvalidAvatar:
            raise
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
            raise InvalidAvatar("图片内容无效或已损坏") from None
        self._replace("avatar.png", output.getvalue())
        return profile.model_copy(update={"avatar_url": _versioned_avatar_url(output.getvalue())})


def _versioned_avatar_url(payload: bytes) -> str:
    return f"/api/user-profile/avatar?v={sha256(payload).hexdigest()}"
