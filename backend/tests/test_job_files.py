"""data/jobs/ 的清理：結束超過保留天數的任務只留下歷史紀錄用到的背景圖。"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contract import UrlBackground
from app.db.models import JobRow
from app.db.session import Database
from app.job_files import clean_job_files
from app.repo import history, jobs
from app.settings import Settings
from tests.fixtures import selected_history

NOW = datetime(2026, 12, 1, 1, 0, tzinfo=UTC)


def settings_for(tmp_path: Path, days: int = 30) -> Settings:
    return Settings(
        _env_file=None, image_mode='sim', agent_mode='sim', data_dir=tmp_path / 'data', job_files_retention_days=days
    )


def job_folder(settings: Settings, job_id: str, *names: str) -> Path:
    folder = settings.data_dir / 'jobs' / job_id
    folder.mkdir(parents=True)
    for name in names:
        (folder / name).write_bytes(b'png')
    return folder


async def add_job(session: AsyncSession, job_id: str, created: datetime, *, finished: bool = True) -> None:
    await jobs.create_job(session, job_id, selected_history().input, created)
    await session.execute(update(JobRow).where(JobRow.id == job_id).values(finished=finished))
    await session.commit()


async def test_old_jobs_keep_only_the_backgrounds_used_by_the_history(
    session: AsyncSession, db: Database, tmp_path: Path
) -> None:
    settings = settings_for(tmp_path)
    old = NOW - timedelta(days=31)
    await add_job(session, 'job_plain', old)
    plain = job_folder(settings, 'job_plain', 'r1.png', 'bg-ig-post-r1-v0.png')
    await add_job(session, 'job_picked', old)
    picked = job_folder(settings, 'job_picked', 'r1.png', 'bg-ig-post-r1-v0.png', 'bg-ig-post-r1-v1.png')
    entry = selected_history()
    background = UrlBackground(kind='url', url='/files/jobs/job_picked/bg-ig-post-r1-v1.png', includes_product=False)
    await history.add_history(
        session,
        entry.model_copy(
            update={'job_id': 'job_picked', 'render': entry.render.model_copy(update={'background': background})}
        ),
    )

    assert await clean_job_files(db, settings, NOW) == 4
    assert not plain.exists()
    assert sorted(f.name for f in picked.iterdir()) == ['bg-ig-post-r1-v1.png']


async def test_recent_and_unfinished_jobs_are_left_alone(session: AsyncSession, db: Database, tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    await add_job(session, 'job_recent', NOW - timedelta(days=29))
    await add_job(session, 'job_running', NOW - timedelta(days=40), finished=False)
    recent = job_folder(settings, 'job_recent', 'r1.png')
    running = job_folder(settings, 'job_running', 'r1.png')
    # 資料庫裡沒有的任務（例如換了資料庫）不知道是否有人用到，也不刪
    unknown = job_folder(settings, 'job_unknown', 'r1.png')
    assert await clean_job_files(db, settings, NOW) == 0
    assert all(f.exists() for f in (recent / 'r1.png', running / 'r1.png', unknown / 'r1.png'))


async def test_a_retention_of_zero_days_keeps_everything(session: AsyncSession, db: Database, tmp_path: Path) -> None:
    settings = settings_for(tmp_path, days=0)
    await add_job(session, 'job_old', NOW - timedelta(days=400))
    folder = job_folder(settings, 'job_old', 'r1.png')
    assert await clean_job_files(db, settings, NOW) == 0
    assert (folder / 'r1.png').exists()


async def test_cleaning_without_a_jobs_folder_does_nothing(session: AsyncSession, db: Database, tmp_path: Path) -> None:
    await add_job(session, 'job_old', NOW - timedelta(days=400))
    assert await clean_job_files(db, settings_for(tmp_path), NOW) == 0
