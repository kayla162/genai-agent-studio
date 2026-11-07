"""/files/...（唯讀）：網址與資料夾的對應見 app/files.py。"""

import asyncio
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from app.api.services import Services
from app.errors import NotFound
from app.files import FILE_TYPES, jpeg_preview, resolve_file

router = APIRouter(tags=['檔案'])

NOSNIFF = {'X-Content-Type-Options': 'nosniff'}


@router.get('/files/{path:path}', response_model=None)
async def read_file(
    path: str, services: Services, variant: Literal['preview'] | None = None
) -> FileResponse | Response:
    """variant=preview：縮成 JPEG 預覽圖（長邊最多 1600 px、最多 1 MB；n8n 上傳到 R2 給 LINE 的圖片訊息）。"""
    target = resolve_file(services.settings, path)
    if target is None:
        raise NotFound(f'找不到檔案：{path}')
    if variant == 'preview':
        data = await asyncio.to_thread(jpeg_preview, target)
        return Response(data, media_type='image/jpeg', headers=NOSNIFF)
    return FileResponse(target, media_type=FILE_TYPES[target.suffix.lower()], headers=NOSNIFF)
