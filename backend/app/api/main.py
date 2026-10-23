"""FastAPI 入口：uv run uvicorn app.api.main:app --port 8000

錯誤一律回傳 { error: { code, message } }（message 為繁體中文）。OpenAPI 文件在 /docs。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.adapters.composer import ComposerError
from app.api import catalog, files, jobs
from app.api.services import ApiServices, start_services, stop_services
from app.errors import AppError
from app.pipeline.runner import failure_reason
from app.settings import settings
from app.validation import describe_error

HTTP_CODES = {404: 'not_found', 405: 'method_not_allowed'}


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({'error': {'code': code, 'message': message}}, status_code=status)


def create_app(services: ApiServices | None = None) -> FastAPI:
    """測試傳入已建立的 services；省略時依設定在啟動時建立、結束時關閉。"""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if services is not None:
            app.state.services = services
            yield
            return
        started = await start_services(settings)
        app.state.services = started
        try:
            yield
        finally:
            await stop_services(started)

    app = FastAPI(title='虛實整合 GenAI Agent API', version='0.4.0', lifespan=lifespan)
    app.include_router(catalog.router)
    app.include_router(jobs.router)
    app.include_router(files.router)

    @app.exception_handler(AppError)
    async def app_error(request: Request, error: AppError) -> JSONResponse:
        return error_response(error.status, error.code, error.message)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        errors = error.errors()
        return error_response(400, 'invalid', '請求格式錯誤' + (f'：{describe_error(errors[0])}' if errors else ''))

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        message = '找不到這個網址' if error.status_code == 404 else str(error.detail)
        return error_response(error.status_code, HTTP_CODES.get(error.status_code, 'http_error'), message)

    @app.exception_handler(ComposerError)
    async def composer_error(request: Request, error: ComposerError) -> JSONResponse:
        return error_response(503, 'unavailable', str(error))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception) -> JSONResponse:
        return error_response(500, 'internal', failure_reason(error))

    return app


app = create_app()
