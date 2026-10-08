"""任務：建立、列表、快照、取消要求，以及從事件組回候選圖。"""

import secrets
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contract import JobInput, JobSnapshot, JobSummary, Render, ReviewCheck
from app.core.clock import iso
from app.db.models import JobEventRow, JobRow

#: 任務列表最多列出的筆數（新到舊）
LIST_LIMIT = 100


def make_job_id(local_now: datetime, suffix: int | None = None) -> str:
    """job_20261005_0930_7fff：本地日期時間（與前端 mock 的 makeJobId 相同格式）加上 4 位十六進位亂數。"""
    tail = secrets.randbelow(0xFFFF) if suffix is None else suffix
    return f'job_{local_now:%Y%m%d}_{local_now:%H%M}_{tail:04x}'


def _summary(row: JobRow) -> JobSummary:
    return JobSummary.model_validate(
        {
            'id': row.id,
            'input': row.input,
            'createdAt': iso(row.created_at),
            'stage': row.stage,
            'round': row.round,
            'finished': row.finished,
            'bestRenderIds': row.best_render_ids,
        }
    )


async def create_job(session: AsyncSession, job_id: str, job_input: JobInput, now: datetime) -> None:
    session.add(
        JobRow(id=job_id, brand_id=job_input.brand_id, input=job_input.to_json(), created_at=now, stage='queued')
    )
    await session.commit()


async def list_jobs(session: AsyncSession) -> list[JobSummary]:
    rows = await session.scalars(select(JobRow).order_by(JobRow.created_at.desc(), JobRow.id.desc()).limit(LIST_LIMIT))
    return [_summary(r) for r in rows]


async def get_job(session: AsyncSession, job_id: str) -> JobSnapshot | None:
    row = await session.get(JobRow, job_id)
    if row is None:
        return None
    events = await session.scalars(select(JobEventRow).where(JobEventRow.job_id == job_id).order_by(JobEventRow.seq))
    return JobSnapshot(summary=_summary(row), events=[{**e.payload, 'seq': e.seq, 'ts': iso(e.ts)} for e in events])


async def request_cancel(session: AsyncSession, job_id: str) -> bool:
    """執行中的任務：設定取消旗標（worker 在步驟之間檢查）。已結束或不存在時回傳 False。"""
    result = await session.execute(
        update(JobRow).where(JobRow.id == job_id, JobRow.finished.is_(False)).values(cancel_requested=True)
    )
    await session.commit()
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def cancel_requested(session: AsyncSession, job_id: str) -> bool:
    return bool(await session.scalar(select(JobRow.cancel_requested).where(JobRow.id == job_id)))


async def get_render(session: AsyncSession, job_id: str, render_id: str) -> Render | None:
    """由事件組回候選圖：render.completed 的內容加上 review.check 與 review.completed。"""
    payloads = await session.scalars(
        select(JobEventRow.payload)
        .where(
            JobEventRow.job_id == job_id,
            JobEventRow.type.in_(('render.completed', 'review.check', 'review.completed')),
        )
        .order_by(JobEventRow.seq)
    )
    render: Render | None = None
    for p in payloads:
        if p['type'] == 'render.completed':
            for r in p['renders']:
                if r['id'] == render_id:
                    render = Render.model_validate(r)
        elif render is not None and p.get('renderId') == render_id:
            if p['type'] == 'review.check':
                render.checks.append(ReviewCheck.model_validate(p['check']))
            else:
                render.score, render.passed = p['score'], p['passed']
    return render
