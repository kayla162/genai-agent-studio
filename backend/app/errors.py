"""領域錯誤：API 轉成 { error: { code, message } }（message 為繁體中文）。"""


class AppError(Exception):
    status = 400
    code = 'invalid'

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(AppError):
    status = 404
    code = 'not_found'


class Invalid(AppError):
    status = 400
    code = 'invalid'


class Conflict(AppError):
    status = 409
    code = 'conflict'


class Unavailable(AppError):
    """依賴的服務（worker、composer）沒有回應或逾時。"""

    status = 503
    code = 'unavailable'
