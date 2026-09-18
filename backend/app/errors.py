"""Domain errors mapped to HTTP responses in app.main."""


class ApiError(Exception):
    status_code = 400

    def __init__(self, message: str, extra: dict | None = None):
        super().__init__(message)
        self.message = message
        self.extra = extra or {}


class NotFoundError(ApiError):
    status_code = 404


class ConflictError(ApiError):
    """可读的冲突拒绝（HTTP 409），如估计与正式抄表双有效。"""

    status_code = 409
