"""任務事件的保存與推送。

- append：同一個交易內鎖定任務列、取得下一個 seq、寫入 job_events 並更新任務摘要；commit 後發布到 Redis
  （發布失敗只記錄警告，事件已在資料庫，串流會從資料庫補齊）。
- stream：先訂閱 Redis，再從資料庫補送 seq 之後的事件，接著轉送即時事件（依 seq 去除重複、補齊漏掉的）。
  Redis 停止或訂閱失敗時不中斷，改為每秒從資料庫讀取新事件，直到任務結束。
- 任務結束的 job.status（done／needs_review／cancelled／failed）一定是最後一則事件，串流看到就結束。
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from redis.exceptions import RedisError
from sqlalchemy import select

from app.contract import FINISHED_STAGES, JobEvent, JobStage, message_json
from app.core.clock import iso, utc_now
from app.db.models import JobEventRow, JobRow
from app.db.session import Database
from app.errors import NotFound

logger = logging.getLogger(__name__)

#: 串流從資料庫讀取新事件的間隔（秒）：Redis 閒置時補齊遺失的發布；Redis 停止時每隔這麼久讀一次
POLL_INTERVAL = 1.0
#: 連不上 Redis 時的錯誤（redis-py 的錯誤與底層的 socket 錯誤）
REDIS_DOWN = (RedisError, OSError)


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
        try:
            await self.publish(job_id, message_json(event, seq, iso(ts)))
        except Exception as error:  # noqa: BLE001 - 事件已寫入資料庫；發布失敗不能影響任務，訂閱端會從資料庫補齊
            logger.warning('事件已寫入資料庫，但發布到 Redis 失敗（任務 %s，seq %d）：%r', job_id, seq, error)
        return seq

    async def publish(self, job_id: str, message: dict[str, Any]) -> None:
        await self.redis.publish(channel(job_id), json.dumps(message, ensure_ascii=False))

    async def _stored(self, job_id: str, after: int, before: int | None = None) -> list[dict[str, Any]]:
        async with self.db.session() as s:
            query = select(JobEventRow).where(JobEventRow.job_id == job_id, JobEventRow.seq > after)
            if before is not None:
                query = query.where(JobEventRow.seq < before)
            return [_message(r) for r in await s.scalars(query.order_by(JobEventRow.seq))]

    async def _subscribe(self, job_id: str) -> PubSub | None:
        """訂閱任務的頻道；Redis 停止時回傳 None（串流改為每秒從資料庫讀取）。"""
        pubsub = self.redis.pubsub()
        try:
            await pubsub.subscribe(channel(job_id))
        except REDIS_DOWN as error:
            logger.warning('訂閱任務 %s 的事件失敗，改為每秒從資料庫讀取：%r', job_id, error)
            await _close(pubsub)
            return None
        return pubsub

    async def stream(self, job_id: str, after: int = 0) -> AsyncGenerator[dict[str, Any]]:
        pubsub = await self._subscribe(job_id)
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
                raw = None
                if pubsub is None:
                    await asyncio.sleep(POLL_INTERVAL)
                else:
                    try:
                        raw = await pubsub.get_message(ignore_subscribe_messages=True, timeout=POLL_INTERVAL)
                    except REDIS_DOWN as error:
                        logger.warning('任務 %s 的事件訂閱中斷，改為每秒從資料庫讀取：%r', job_id, error)
                        await _close(pubsub)
                        pubsub = None
                if raw is None:
                    # 閒置（或 Redis 停止）時從資料庫補齊：結束事件的發布可能遺失，之後不會再有訊息
                    for missing in await self._stored(job_id, last):
                        yield missing
                        last = missing['seq']
                        if is_final(missing):
                            return
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
            if pubsub is not None:
                await _close(pubsub)


async def _close(pubsub: PubSub) -> None:
    """關閉訂閱的連線（Redis 會一併取消訂閱）。不另外送 UNSUBSCRIBE：Redis 停止時那會先重試連線，拖慢結束。"""
    try:
        await pubsub.aclose()  # type: ignore[no-untyped-call]
    except REDIS_DOWN as error:
        logger.warning('關閉 Redis 訂閱失敗：%r', error)
