"""任務事件的保存與推送。

- append：同一個交易內鎖定任務列、取得下一個 seq、寫入 job_events 並更新任務摘要；commit 後發布到 Redis。
- stream：先訂閱 Redis，再從資料庫補送 seq 之後的事件，接著轉送即時事件（依 seq 去除重複、補齊漏掉的）。
- 任務結束的 job.status（done／needs_review／cancelled／failed）一定是最後一則事件，串流看到就結束。
"""

import json
from collections.abc import AsyncIterator
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select

from app.contract import FINISHED_STAGES, JobEvent, JobStage, message_json
from app.core.clock import iso, utc_now
from app.db.models import JobEventRow, JobRow
from app.db.session import Database
from app.errors import NotFound


def channel(job_id: str) -> str:
    return f'job:{job_id}'


def is_final(message: dict[str, Any]) -> bool:
    return message['type'] == 'job.status' and message['stage'] in FINISHED_STAGES


def _apply(row: JobRow, event: JobEvent) -> None:
    """事件 → 任務摘要（任務列表與 Agent 透視的選單使用）。"""
    if event.type == 'job.status':
        row.stage, row.round = event.stage, event.round
        row.finished = event.stage in FINISHED_STAGES
    elif event.type == 'job.completed':
        row.best_render_ids = {str(t): r for t, r in event.best_render_ids.items()}
    elif event.type == 'job.failed':
        row.failure_reason = event.reason


def _message(row: JobEventRow) -> dict[str, Any]:
    return {**row.payload, 'seq': row.seq, 'ts': iso(row.ts)}


class EventStore:
    def __init__(self, db: Database, redis: Redis) -> None:
        self.db = db
        self.redis = redis

    async def append(self, job_id: str, event: JobEvent, *, expect_stage: JobStage | None = None) -> int | None:
        """寫入事件並回傳 seq。expect_stage 與目前階段不同時不寫入、回傳 None（例如排隊中的任務已被取消）。"""
        ts = utc_now()
        async with self.db.session() as s:
            row = await s.get(JobRow, job_id, with_for_update=True)
            if row is None:
                raise NotFound(f'找不到任務：{job_id}')
            if expect_stage is not None and row.stage != expect_stage:
                return None
            row.last_seq += 1
            seq = row.last_seq
            _apply(row, event)
            s.add(JobEventRow(job_id=job_id, seq=seq, ts=ts, type=event.type, payload=event.to_json()))
            await s.commit()
        await self.publish(job_id, message_json(event, seq, iso(ts)))
        return seq

    async def publish(self, job_id: str, message: dict[str, Any]) -> None:
        await self.redis.publish(channel(job_id), json.dumps(message, ensure_ascii=False))

    async def _stored(self, job_id: str, after: int, before: int | None = None) -> list[dict[str, Any]]:
        async with self.db.session() as s:
            query = select(JobEventRow).where(JobEventRow.job_id == job_id, JobEventRow.seq > after)
            if before is not None:
                query = query.where(JobEventRow.seq < before)
            return [_message(r) for r in await s.scalars(query.order_by(JobEventRow.seq))]

    async def stream(self, job_id: str, after: int = 0) -> AsyncIterator[dict[str, Any]]:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(channel(job_id))
        try:
            async with self.db.session() as s:
                job = await s.get(JobRow, job_id)
                if job is None:
                    raise NotFound(f'找不到任務：{job_id}')
                final_seq = job.last_seq if job.finished else None
            last = after
            for message in await self._stored(job_id, after):
                yield message
                last = message['seq']
                if is_final(message):
                    return
            # 任務早已結束，呼叫端也已收到全部事件
            if final_seq is not None and last >= final_seq:
                return
            while True:
                raw = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if raw is None:
                    continue
                message = json.loads(raw['data'])
                if message['seq'] <= last:
                    continue
                # Redis 漏掉的訊息從資料庫補齊
                for missing in await self._stored(job_id, last, before=message['seq']):
                    yield missing
                yield message
                last = message['seq']
                if is_final(message):
                    return
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()  # type: ignore[no-untyped-call]
