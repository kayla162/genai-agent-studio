"""定稿海報：歷史紀錄選定的候選圖，以選定時的文案（Studio 可以改文案）重新繪製的模板原尺寸 PNG。

第一次請求時由 composer 繪製並存到 data/history/{historyId}.png，之後直接讀檔。n8n 收到 history.selected 後下載它，
上傳到 R2 並推送到 LINE（docs/superpowers/specs/2026-11-07-publish-on-select-design.md）。
"""

import asyncio
import os
import secrets
from pathlib import Path

from app.adapters.composer import ComposerClient, ComposerError
from app.contract import HistoryEntry, Render
from app.db.session import Database
from app.errors import AppError, NotFound
from app.files import JOB_FILE_ID
from app.pipeline.review import ComposerPosters
from app.repo import catalog, history
from app.settings import Settings


class RenderFailed(AppError):
    """composer 畫不出定稿（n8n 走錯誤輸出，改送純文字）。"""

    status = 502
    code = 'render_failed'


def final_render(entry: HistoryEntry) -> Render:
    """候選圖換上歷史紀錄的文案（composer 依 render.spec.copy 繪製文字）。"""
    spec = entry.render.spec.model_copy(update={'copy_': entry.copy_})
    return entry.render.model_copy(update={'spec': spec})


def final_poster_path(settings: Settings, history_id: str) -> Path:
    if not JOB_FILE_ID.fullmatch(history_id):
        raise NotFound(f'找不到歷史紀錄：{history_id}')
    return settings.data_dir / 'history' / f'{history_id}.png'


def _write_atomically(target: Path, png: bytes) -> None:
    """先寫暫存檔再改名：同時有兩個請求時，讀到的一定是完整的檔案。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f'.{target.name}.{secrets.token_hex(4)}.tmp')
    temp.write_bytes(png)
    os.replace(temp, target)


async def final_poster(settings: Settings, db: Database, composer: ComposerClient, history_id: str) -> Path:
    target = final_poster_path(settings, history_id)
    if target.is_file():
        return target
    async with db.session() as s:
        entry = await history.get_history(s, history_id)
        if entry is None:
            raise NotFound(f'找不到歷史紀錄：{history_id}')
        brand = await catalog.get_brand(s, entry.brand_id)
        product = await catalog.get_product(s, entry.product_id)
    if brand is None:
        raise NotFound(f'找不到品牌：{entry.brand_id}')
    render = final_render(entry)
    posters = ComposerPosters(composer, settings)
    try:
        images = await asyncio.to_thread(posters._images, render, product, brand)
        poster = await composer.render(render, product, brand, images)
    except (AppError, ComposerError) as error:
        raise RenderFailed(f'定稿繪製失敗：{error}') from error
    await asyncio.to_thread(_write_atomically, target, poster.png)
    return target
