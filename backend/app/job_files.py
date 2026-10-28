"""data/jobs/ 的清理：審查用海報與生成的背景每張約 0.3–1 MB，不清理會一直累積。

結束超過 JOB_FILES_RETENTION_DAYS 天的任務，刪掉它資料夾裡的檔案，只留下歷史紀錄（選定的海報）用到的背景圖：
歷史紀錄與品牌案例要用它重畫海報。資料庫裡找不到的任務資料夾不刪（不知道是否有人用到）。
清理之後，舊任務的任務透視看不到審查用海報與候選的背景。
"""

import asyncio
import logging
from collections.abc import Collection, Mapping
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.contract import HistoryEntry, UrlBackground
from app.core.clock import utc_now
from app.db.models import HistoryRow, JobRow
from app.db.session import Database
from app.files import JOB_FILE_ID, PREFIX
from app.settings import Settings

logger = logging.getLogger(__name__)

#: 多久清理一次（秒）
CLEAN_INTERVAL = 24 * 3600


async def clean_job_files(db: Database, settings: Settings, now: datetime) -> int:
    """回傳刪除的檔案數；保留天數為 0 時不清理。"""
    if settings.job_files_retention_days == 0:
        return 0
    cutoff = now - timedelta(days=settings.job_files_retention_days)
    async with db.session() as s:
        job_ids = list(await s.scalars(select(JobRow.id).where(JobRow.finished.is_(True), JobRow.created_at < cutoff)))
        rows = await s.scalars(select(HistoryRow.data).where(HistoryRow.job_id.in_(job_ids)))
        entries = [HistoryEntry.model_validate(data) for data in rows]
    kept: dict[str, set[str]] = {}
    for entry in entries:
        background = entry.render.background
        folder_url = f'{PREFIX}jobs/{entry.job_id}/'
        if isinstance(background, UrlBackground) and background.url.startswith(folder_url):
            kept.setdefault(entry.job_id, set()).add(background.url.removeprefix(folder_url))
    return await asyncio.to_thread(_remove, settings.data_dir / 'jobs', job_ids, kept)


def _remove(root: Path, job_ids: Collection[str], kept: Mapping[str, Collection[str]]) -> int:
    removed = 0
    for job_id in job_ids:
        folder = root / job_id
        if not JOB_FILE_ID.fullmatch(job_id) or not folder.is_dir():
            continue
        keep = kept.get(job_id, ())
        for path in folder.iterdir():
            if path.is_file() and path.name not in keep:
                path.unlink(missing_ok=True)
                removed += 1
        if not keep and not any(folder.iterdir()):
            folder.rmdir()
    return removed


async def clean_job_files_periodically(db: Database, settings: Settings, interval: float = CLEAN_INTERVAL) -> None:
    """worker 啟動時清理一次，之後每天一次。出錯只記錄，下一輪再試。"""
    while True:
        try:
            removed = await clean_job_files(db, settings, utc_now())
            if removed:
                logger.info('清理舊任務的檔案：刪除 %d 個', removed)
        except Exception:
            logger.exception('清理舊任務的檔案失敗')
        await asyncio.sleep(interval)
