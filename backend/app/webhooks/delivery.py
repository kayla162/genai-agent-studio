"""發送任務結束的通知：worker 每 POLL_INTERVAL 秒取一批到期的 pending（FOR UPDATE SKIP LOCKED，不會重複取得），
簽章後 POST，依結果標記送達、排定重試或放棄（dead）。接收端依 X-Webhook-Id 去重：worker 在送出後、寫入結果前
被結束時，同一則通知會再送一次。"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select

from app.core.clock import utc_now
from app.db.models import WebhookOutboxRow
from app.db.session import Database
from app.settings import Settings
from app.webhooks.signing import encode, headers

logger = logging.getLogger(__name__)

#: 第 n 次失敗後等待的秒數；第 MAX_ATTEMPTS 次仍失敗就放棄
BACKOFF: tuple[int, ...] = (10, 60, 300, 900, 1800, 3600, 7200)
MAX_ATTEMPTS = len(BACKOFF) + 1
#: 取到期通知的間隔（秒）
POLL_INTERVAL = 2.0
#: 每次最多取幾筆
BATCH = 20
#: 連線與讀取的逾時（秒）
TIMEOUT = 10.0
#: 雖然是 4xx 但值得重試的狀態碼
RETRY_STATUSES = frozenset({408, 429})
#: 記錄回應內容的長度上限
ERROR_CHARS = 500


@dataclass(frozen=True)
class Outcome:
    delivered: bool
    #: 失敗時是否值得重試
    retry: bool
    error: str | None


async def send(http: httpx.AsyncClient, settings: Settings, row: WebhookOutboxRow, now: datetime) -> Outcome:
    body = encode(row.payload)
    timestamp = int(now.timestamp())
    secret = settings.job_webhook_secret.get_secret_value()
    try:
        res = await http.post(
            settings.job_webhook_url,
            content=body,
            headers=headers(webhook_id=row.id, event=row.event, secret=secret, timestamp=timestamp, body=body),
        )
    except httpx.HTTPError as error:
        return Outcome(False, True, f'連線失敗：{error!r}')
    if 200 <= res.status_code < 300:
        return Outcome(True, False, None)
    retry = res.status_code >= 500 or res.status_code in RETRY_STATUSES
    return Outcome(False, retry, f'HTTP {res.status_code}：{res.text[:ERROR_CHARS]}')


def apply_outcome(row: WebhookOutboxRow, outcome: Outcome, now: datetime) -> None:
    row.attempts += 1
    if outcome.delivered:
        row.status, row.delivered_at, row.last_error = 'delivered', now, None
    elif not outcome.retry or row.attempts >= MAX_ATTEMPTS:
        row.status, row.last_error = 'dead', outcome.error
    else:
        row.next_attempt_at = now + timedelta(seconds=BACKOFF[row.attempts - 1])
        row.last_error = outcome.error


async def deliver_due(db: Database, settings: Settings, http: httpx.AsyncClient, now: datetime) -> int:
    if not settings.job_webhook_url:
        return 0
    delivered = 0
    async with db.session() as s:
        rows = (
            await s.scalars(
                select(WebhookOutboxRow)
                .where(WebhookOutboxRow.status == 'pending', WebhookOutboxRow.next_attempt_at <= now)
                .order_by(WebhookOutboxRow.next_attempt_at)
                .limit(BATCH)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for row in rows:
            outcome = await send(http, settings, row, now)
            apply_outcome(row, outcome, now)
            if outcome.delivered:
                delivered += 1
            elif row.status == 'dead':
                logger.warning('webhook 放棄發送：%s（任務 %s）：%s', row.id, row.job_id, row.last_error)
        await s.commit()
    return delivered


async def deliver_periodically(db: Database, settings: Settings, interval: float = POLL_INTERVAL) -> None:
    """worker 執行期間一直發送；出錯只記錄，下一輪再試。"""
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as http:
        while True:
            try:
                await deliver_due(db, settings, http, utc_now())
            except Exception:
                logger.exception('發送 webhook 失敗')
            await asyncio.sleep(interval)
