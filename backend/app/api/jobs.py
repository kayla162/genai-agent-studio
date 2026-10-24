"""需求拆解、任務（建立、列表、取消、WebSocket 事件串流）、選定海報、歷史紀錄與成效儀表板。"""

import asyncio
import json
import logging
import secrets
from contextlib import aclosing
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, WebSocket
from pydantic import Field
from sqlalchemy.exc import IntegrityError

from app.adapters.gemini import NOT_CONFIGURED, GeminiError
from app.api.catalog import api_options
from app.api.services import ApiServices, Services
from app.contract import (
    Copy,
    DashboardStats,
    HistoryEntry,
    JobAcceptedEvent,
    JobEvent,
    JobFailedEvent,
    JobInput,
    JobSnapshot,
    JobStatusEvent,
    JobSummary,
    LogEvent,
    Model,
    ParsedBrief,
)
from app.core.clock import iso, utc_now
from app.errors import Invalid, NotFound, Unavailable
from app.queues import TaskFailed
from app.repo import catalog, history, jobs
from app.repo import usage as usage_repo
from app.stats import dashboard_stats
from app.usage import UsageScope

logger = logging.getLogger(__name__)

router = APIRouter(tags=['任務'])

#: 回寫歷史切塊最多等待的秒數（逾時時 writtenToRag 為 false，worker 仍會完成）
WRITE_BACK_WAIT = 10
#: WebSocket 關閉代碼：任務不存在（前端不再重新連線）
WS_NOT_FOUND = 4404
#: 需求拆解最多等待的秒數（AGENT_MODE=gemini 時含 Gemini 的重試）
BRIEF_TIMEOUT = 90


class BriefRequest(Model):
    brand_id: str
    text: str
    product_id: str | None


class JobCreated(Model):
    job_id: str


class SelectRequest(Model):
    render_id: str
    copy_: Copy = Field(alias='copy')


class FavoriteRequest(Model):
    favorite: bool


@router.post('/api/briefs/parse')
async def parse_brief(body: BriefRequest, services: Services) -> ParsedBrief:
    async with services.db.session() as s:
        brand = await catalog.get_brand(s, body.brand_id)
        product = await catalog.get_product(s, body.product_id) if body.product_id else None
    if brand is None:
        raise Invalid(f'找不到品牌：{body.brand_id}')
    if body.product_id and product is None:
        raise Invalid(f'找不到商品：{body.product_id}')
    try:
        return await asyncio.wait_for(services.agent.parse_brief(brand, body.text, product), BRIEF_TIMEOUT)
    except TimeoutError as error:
        raise Unavailable(f'Gemini 沒有在 {BRIEF_TIMEOUT} 秒內完成需求拆解，請稍後再試') from error


async def _validate(services: ApiServices, job_input: JobInput) -> None:
    """與 mock 的 createJob 相同的檢查，再加上模型與引擎必須是目前可用的選項。"""
    async with services.db.session() as s:
        brand = await catalog.get_brand(s, job_input.brand_id)
        product = await catalog.get_product(s, job_input.product_id)
    if brand is None:
        raise Invalid(f'找不到品牌：{job_input.brand_id}')
    if product is None:
        raise Invalid(f'找不到商品：{job_input.product_id}')
    if not job_input.template_ids:
        raise Invalid('至少要選一個通路模板')
    if len(set(job_input.template_ids)) != len(job_input.template_ids):
        raise Invalid('通路模板不可重複')
    if not 1 <= job_input.variants_per_template <= 8:
        raise Invalid('每個模板的候選張數需為 1–8')
    if job_input.max_retries < 0:
        raise Invalid('最大重試次數需為 0 以上的整數')
    if product.brand_id != brand.id:
        raise Invalid('商品不屬於所選品牌')
    if job_input.visual_style_id is not None and all(s.id != job_input.visual_style_id for s in brand.visual_styles):
        raise Invalid(f'品牌沒有這個背景風格：{job_input.visual_style_id}')
    options = api_options(services.settings)
    if job_input.llm not in options.llm:
        raise Invalid(f'目前不支援這個 LLM：{job_input.llm}')
    if job_input.vlm not in options.vlm:
        raise Invalid(f'目前不支援這個 VLM：{job_input.vlm}')
    if job_input.engine not in options.engines:
        raise Invalid(f'目前不支援這個生圖引擎：{job_input.engine}')
    await _check_gemini(services, job_input)


async def _check_gemini(services: ApiServices, job_input: JobInput) -> None:
    """AGENT_MODE=gemini：沒有 key、單價表有問題（503），或本月已達費用上限（429）時不建立任務。"""
    settings = services.settings
    if settings.agent_mode != 'gemini':
        return
    if services.gemini is None or not services.gemini.configured:
        raise GeminiError(NOT_CONFIGURED)
    if services.ledger is None:
        return
    scope = UsageScope(job_id=None, brand_id=job_input.brand_id, round=None, target=None)
    services.ledger.pricing.price(settings.gemini_vlm_model, utc_now())
    await services.ledger.check(scope, settings.gemini_llm_model)


@router.post('/api/jobs', status_code=201)
async def create_job(job_input: JobInput, services: Services) -> JobCreated:
    """寫入任務、送出 job.accepted 與 job.status queued，放進 jobs 佇列。"""
    await _validate(services, job_input)
    now = utc_now()
    local = now.astimezone(ZoneInfo(services.settings.timezone))
    for attempt in range(5):
        job_id = jobs.make_job_id(local)
        try:
            async with services.db.session() as s:
                await jobs.create_job(s, job_id, job_input, now)
            break
        except IntegrityError:
            # 同一分鐘內 4 位亂數重複：換一個
            if attempt == 4:
                raise
    await services.store.append(job_id, JobAcceptedEvent(type='job.accepted', job_id=job_id))
    await services.store.append(job_id, JobStatusEvent(type='job.status', stage='queued', round=0))
    try:
        await services.queues.enqueue_job(job_id)
    except Exception as error:  # noqa: BLE001 - 佇列的任何錯誤都要讓任務結束，不能留在排隊中
        logger.exception('任務無法排入佇列：job_id=%s', job_id)
        if not await _fail_unless_taken(services, job_id):
            raise Unavailable('目前無法排入任務（佇列服務沒有回應），請稍後再試') from error
        # 排入其實成功了（只是回應遺失），worker 已經取走任務：照常回傳
    return JobCreated(job_id=job_id)


async def _fail_unless_taken(services: ApiServices, job_id: str) -> bool:
    """任務已寫入資料庫卻排不進佇列：標記失敗，否則它會停在排隊中，等 worker 重新啟動時意外執行。
    任務已不在排隊中（worker 已經取走）時不動它並回傳 True；其餘情況回傳 False，包含失敗事件也寫不進去。"""
    reason = '無法排入佇列：佇列服務沒有回應'
    # 每一則事件都要求任務還在排隊中，worker 取走任務之後就不再寫入
    events: list[JobEvent] = [
        LogEvent(type='log', source='api', level='error', message=reason),
        JobFailedEvent(type='job.failed', job_id=job_id, reason=reason),
        JobStatusEvent(type='job.status', stage='failed', round=0),
    ]
    try:
        for event in events:
            if await services.store.append(job_id, event, expect_stage='queued') is None:
                logger.warning('任務已被 worker 取走，不標記為失敗：job_id=%s', job_id)
                return True
    except Exception:  # noqa: BLE001 - 連失敗事件都寫不進去時，仍要回 503
        logger.exception('無法把任務標記為失敗：job_id=%s', job_id)
    return False


@router.get('/api/jobs')
async def list_jobs(services: Services) -> list[JobSummary]:
    async with services.db.session() as s:
        return await jobs.list_jobs(s)


@router.get('/api/jobs/{job_id}')
async def get_job(job_id: str, services: Services) -> JobSnapshot:
    async with services.db.session() as s:
        snap = await jobs.get_job(s, job_id)
    if snap is None:
        raise NotFound(f'找不到任務：{job_id}')
    return snap


@router.post('/api/jobs/{job_id}/cancel', status_code=204)
async def cancel_job(job_id: str, services: Services) -> None:
    """排隊中：直接取消。執行中：設定取消旗標，worker 在步驟之間停止。已結束：不做任何事。"""
    cancelled = JobStatusEvent(type='job.status', stage='cancelled', round=0)
    if await services.store.append(job_id, cancelled, expect_stage='queued') is None:
        async with services.db.session() as s:
            await jobs.request_cancel(s, job_id)


@router.websocket('/ws/jobs/{job_id}')
async def stream_job(websocket: WebSocket, job_id: str, services: Services, after: int = 0) -> None:
    """先補送 seq 大於 after 的事件，再轉送即時事件；任務結束且事件送完後由伺服器關閉連線。"""
    await websocket.accept()
    async with services.db.session() as s:
        if await jobs.get_summary(s, job_id) is None:
            await websocket.close(code=WS_NOT_FOUND, reason='job not found')
            return

    async def forward() -> None:
        async with aclosing(services.store.stream(job_id, after)) as messages:
            async for message in messages:
                await websocket.send_text(json.dumps(message, ensure_ascii=False))

    async def until_disconnect() -> None:
        # 前端不送訊息；收到 disconnect 代表連線已經關閉
        while (await websocket.receive())['type'] != 'websocket.disconnect':
            pass

    sender = asyncio.create_task(forward())
    watcher = asyncio.create_task(until_disconnect())
    done, pending = await asyncio.wait({sender, watcher}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    if sender in done:
        error = sender.exception()
        await websocket.close(code=1011 if error else 1000)
        if error:
            raise error


@router.post('/api/jobs/{job_id}/select', status_code=201)
async def select_render(job_id: str, body: SelectRequest, services: Services) -> HistoryEntry:
    """選定候選圖：寫入歷史紀錄，再由 worker 回寫成歷史切塊（writtenToRag）。

    回寫最多等 WRITE_BACK_WAIT 秒；逾時、失敗或被中止時 writtenToRag 為 false。歷史紀錄已經建立，所以不回錯誤。
    """
    async with services.db.session() as s:
        summary = await jobs.get_summary(s, job_id)
        if summary is None:
            raise NotFound(f'找不到任務：{job_id}')
        render = await jobs.get_render(s, job_id, body.render_id)
        if render is None:
            raise NotFound(f'找不到候選圖：{body.render_id}')
        entry = HistoryEntry(
            id=f'hist_{secrets.token_hex(6)}',
            job_id=job_id,
            brand_id=summary.input.brand_id,
            product_id=summary.input.product_id,
            input=summary.input,
            template_id=render.template_id,
            render=render,
            copy_=body.copy_,
            selected_at=iso(utc_now()),
            favorite=False,
            written_to_rag=False,
        )
        await history.add_history(s, entry)
    try:
        done = await services.queues.run_task('write_back', wait=WRITE_BACK_WAIT, history_id=entry.id)
    except TaskFailed as error:
        logger.warning('歷史回寫失敗：history_id=%s：%s', entry.id, error)
        return entry
    if done.completed and done.result:
        entry = entry.model_copy(update={'written_to_rag': True})
    return entry


@router.get('/api/history')
async def list_history(
    services: Services, brand_id: Annotated[str | None, Query(alias='brandId')] = None
) -> list[HistoryEntry]:
    async with services.db.session() as s:
        return await history.list_history(s, brand_id)


@router.patch('/api/history/{history_id}')
async def set_favorite(history_id: str, body: FavoriteRequest, services: Services) -> HistoryEntry:
    async with services.db.session() as s:
        entry = await history.set_favorite(s, history_id, body.favorite)
    if entry is None:
        raise NotFound(f'找不到歷史紀錄：{history_id}')
    return entry


@router.get('/api/stats')
async def get_stats(
    services: Services, brand_id: Annotated[str | None, Query(alias='brandId')] = None
) -> DashboardStats:
    """每張成本依 job_usage 的實際費用（沒有紀錄的任務，例如模擬模式，為 0）。"""
    async with services.db.session() as s:
        snaps = await jobs.finished_snapshots(s, brand_id)
        costs = await usage_repo.costs_by_job(s, [snap.summary.id for snap in snaps])
    return dashboard_stats(snaps, {job_id: float(cost) for job_id, cost in costs.items()})
