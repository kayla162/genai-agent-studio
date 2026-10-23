"""job_usage：外部服務的用量與費用。"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import JobUsageRow


async def add_usage(session: AsyncSession, row: JobUsageRow) -> None:
    session.add(row)
    await session.commit()


async def job_total(session: AsyncSession, job_id: str) -> tuple[Decimal, int]:
    """一個任務的費用合計與呼叫次數；沒有紀錄時為 (0, 0)。"""
    total, count = (
        await session.execute(
            select(func.coalesce(func.sum(JobUsageRow.cost_usd), 0), func.count()).where(JobUsageRow.job_id == job_id)
        )
    ).one()
    return Decimal(total), int(count)


async def range_total(session: AsyncSession, start: datetime, end: datetime) -> Decimal:
    """created_at 在 [start, end) 之間的費用合計（含需求拆解等沒有任務的紀錄）。"""
    total = await session.scalar(
        select(func.coalesce(func.sum(JobUsageRow.cost_usd), 0)).where(
            JobUsageRow.created_at >= start, JobUsageRow.created_at < end
        )
    )
    return Decimal(total or 0)


async def costs_by_job(session: AsyncSession, job_ids: list[str]) -> dict[str, Decimal]:
    """每個任務的費用合計；沒有紀錄的任務不出現。"""
    if not job_ids:
        return {}
    rows = await session.execute(
        select(JobUsageRow.job_id, func.sum(JobUsageRow.cost_usd))
        .where(JobUsageRow.job_id.in_(job_ids))
        .group_by(JobUsageRow.job_id)
    )
    return {job_id: Decimal(total) for job_id, total in rows if job_id is not None}
