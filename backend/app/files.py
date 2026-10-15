"""/files/... 網址與檔案的對應（api 提供檔案、worker 讀取商品照共用）：

- /files/uploads/…、/files/products/{id}/…（去背圖）→ data/
- /files/local/{檔名} → 本機資料夾 assets/products/
- /files/brands/… → 品牌設定檔資料夾（Logo 等圖檔）
"""

import re
from pathlib import Path
from urllib.parse import unquote

from app.errors import Invalid, NotFound
from app.settings import Settings

#: 只提供圖片；MIME 固定，不依賴作業系統的對照表
FILE_TYPES = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
    '.svg': 'image/svg+xml',
}
PREFIX = '/files/'
#: 商品 id 要能直接當資料夾名稱：不含路徑分隔字元，也不能是 . 或 ..
PRODUCT_ID = re.compile(r'[A-Za-z0-9_-]{1,64}')


def resolve_file(settings: Settings, path: str) -> Path | None:
    """網址路徑（/files/ 之後的部分）→ 檔案。不允許超出各自的資料夾（.. 與絕對路徑都會被擋下）。"""
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


def photo_path(settings: Settings, url: str) -> Path:
    """商品照的網址（/files/uploads/…、/files/local/…，檔名經過 URL 編碼）→ 檔案。"""
    target = resolve_file(settings, unquote(url.removeprefix(PREFIX))) if url.startswith(PREFIX) else None
    if target is None:
        raise NotFound(f'找不到商品照：{unquote(url)}')
    return target


def product_folder(settings: Settings, product_id: str) -> Path:
    """商品的檔案資料夾（去背圖）：data/products/{id}。商品 id 格式不對時不給路徑，避免寫到 data/products 之外。"""
    if not PRODUCT_ID.fullmatch(product_id):
        raise Invalid(f'商品 id 格式錯誤：{product_id}')
    return settings.data_dir / 'products' / product_id
