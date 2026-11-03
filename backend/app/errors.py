"""业务异常与统一错误结构：{"detail": {"code": "...", "message": "..."}}。"""


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, **extra):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.extra = extra
        super().__init__(message)

    def to_detail(self) -> dict:
        detail = {"code": self.code, "message": self.message}
        detail.update(self.extra)
        return detail
