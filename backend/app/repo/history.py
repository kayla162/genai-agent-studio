"""歷史紀錄：選定並匯出的海報（新到舊）。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contract import HistoryEntry
from app.core.clock import parse_iso
from app.db.models import HistoryRow


async def add_history(session: AsyncSession, entry: HistoryEntry) -> None:
    session.add(
        HistoryRow(
            id=entry.id,
            job_id=entry.job_id,
            brand_id=entry.brand_id,
            data=entry.to_json(),
            selected_at=parse_iso(entry.selected_at),
        )
    )
    await session.commit()


async def list_history(session: AsyncSession, brand_id: str | None = None) -> list[HistoryEntry]:
    query = select(HistoryRow).order_by(HistoryRow.selected_at.desc(), HistoryRow.id.desc())
    if brand_id is not None:
        query = query.where(HistoryRow.brand_id == brand_id)
    return [HistoryEntry.model_validate(r.data) for r in await session.scalars(query)]


async def get_history(session: AsyncSession, history_id: str) -> HistoryEntry | None:
    row = await session.get(HistoryRow, history_id)
    return HistoryEntry.model_validate(row.data) if row else None


async def mark_written(session: AsyncSession, history_id: str) -> bool:
    """回寫成歷史切塊後標記 writtenToRag。"""
    row = await session.get(HistoryRow, history_id)
    if row is None:
        return False
    row.data = {**row.data, 'writtenToRag': True}
    await session.commit()
    return True


async def set_favorite(session: AsyncSession, history_id: str, favorite: bool) -> HistoryEntry | None:
    row = await session.get(HistoryRow, history_id)
    if row is None:
        return None
    entry = HistoryEntry.model_validate({**row.data, 'favorite': favorite})
    row.data = entry.to_json()
    await session.commit()
    return entry
