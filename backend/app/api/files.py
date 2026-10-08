"""/files/...（唯讀）：

- /files/uploads/…、之後的去背圖與生成圖 → data/
- /files/local/{檔名} → 本機資料夾 assets/products/
- /files/brands/… → 品牌設定檔資料夾（Logo 等圖檔）
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.api.services import Services
from app.errors import NotFound
from app.settings import Settings

router = APIRouter(tags=['檔案'])

#: 只提供圖片；MIME 固定，不依賴作業系統的對照表
FILE_TYPES = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
    '.svg': 'image/svg+xml',
}


def resolve_file(settings: Settings, path: str) -> Path | None:
    """網址路徑 → 檔案。不允許超出各自的資料夾（.. 與絕對路徑都會被擋下）。"""
    head, _, rest = path.partition('/')
    if head == 'local':
        root, relative = settings.local_photos_dir, rest
    elif head == 'brands':
        root, relative = settings.brands_dir, rest
    else:
        root, relative = settings.data_dir, path
    base = root.resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base) or target.suffix.lower() not in FILE_TYPES or not target.is_file():
        return None
    return target


@router.get('/files/{path:path}')
async def read_file(path: str, services: Services) -> FileResponse:
    target = resolve_file(services.settings, path)
    if target is None:
        raise NotFound(f'找不到檔案：{path}')
    return FileResponse(
        target, media_type=FILE_TYPES[target.suffix.lower()], headers={'X-Content-Type-Options': 'nosniff'}
    )
