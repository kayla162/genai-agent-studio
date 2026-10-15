"""/files/...（唯讀）：網址與資料夾的對應見 app/files.py。"""

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.api.services import Services
from app.errors import NotFound
from app.files import FILE_TYPES, resolve_file

router = APIRouter(tags=['檔案'])


@router.get('/files/{path:path}')
async def read_file(path: str, services: Services) -> FileResponse:
    target = resolve_file(services.settings, path)
    if target is None:
        raise NotFound(f'找不到檔案：{path}')
    return FileResponse(
        target, media_type=FILE_TYPES[target.suffix.lower()], headers={'X-Content-Type-Options': 'nosniff'}
    )
