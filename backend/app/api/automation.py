"""n8n 等自動化呼叫端的 API（Authorization: Bearer AUTOMATION_TOKEN）。

內部重用 Studio 的建任務與選圖邏輯；AUTOMATION_TOKEN 為空時整組回 404（像是不存在）。
"""

import hmac
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import Field
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.catalog import api_options
from app.api.jobs import JobCreated, JobMeta, parse_text, record_selection, submit_job
from app.api.services import Services
from app.contract import FINISHED_STAGES, HistoryEntry, JobInput, Model, TemplateId
from app.core.clock import utc_now
from app.db.models import AutomationRequestRow, JobRow
from app.errors import Conflict, Invalid, NotFound, Unauthorized
from app.repo import catalog, jobs
from app.webhooks.payload import best, candidates

#: 與 Studio 的預設相同（web/src/lib/store/studio.ts）
DEFAULT_MAX_RETRIES = 2


async def require_token(services: Services, authorization: Annotated[str | None, Header()] = None) -> None:
    token = services.settings.automation_token.get_secret_value()
    if not token:
        raise NotFound('找不到這個網址')
    scheme, _, given = (authorization or '').partition(' ')
    if scheme.lower() != 'bearer' or not hmac.compare_digest(given.encode(), token.encode()):
        raise Unauthorized('缺少或錯誤的 automation token')


router = APIRouter(prefix='/api/automation', tags=['自動化'], dependencies=[Depends(require_token)])


class AutomationJobRequest(Model):
    brand_id: str
    product_id: str
    brief: str = Field(min_length=1, max_length=500)
    #: 呼叫端的參照（例如 sheet:<id>:row:12）：原樣存起來，在 webhook 帶回
    client_ref: str | None = Field(default=None, max_length=200)
    template_ids: list[TemplateId] | None = None
    variants_per_template: int | None = None
    visual_style_id: str | None = None


@router.post('/jobs', status_code=201)
async def create_job(body: AutomationJobRequest, services: Services) -> JobCreated:
    """在伺服器端拆解需求，其餘欄位以設定與可用選項的預設值補齊，再走與 Studio 相同的建任務流程。"""
    async with services.db.session() as s:
        brand = await catalog.get_brand(s, body.brand_id)
        product = await catalog.get_product(s, body.product_id)
    if brand is None:
        raise Invalid(f'找不到品牌：{body.brand_id}')
    if product is None:
        raise Invalid(f'找不到商品：{body.product_id}')
    parsed = await parse_text(services, brand, body.brief, product)
    settings = services.settings
    options = api_options(settings)
    job_input = JobInput(
        brand_id=body.brand_id,
        product_id=body.product_id,
        brief=body.brief,
        parsed_brief=parsed,
        template_ids=body.template_ids or list(settings.automation_templates),
        variants_per_template=body.variants_per_template or settings.automation_variants,
        llm=options.llm[0],
        engine=options.engines[0],
        vlm=options.vlm[0],
        max_retries=DEFAULT_MAX_RETRIES,
        visual_style_id=body.visual_style_id,
    )
    return JobCreated(job_id=await submit_job(services, job_input, JobMeta(client_ref=body.client_ref)))


#: 一條退回鏈最多幾次
MAX_REVISIONS = 3
#: 冪等鍵保留的天數
IDEMPOTENCY_DAYS = 7

IdempotencyKey = Annotated[str | None, Header(alias='Idempotency-Key', max_length=100)]


async def idempotent[M: Model](
    services: Services, key: str | None, action: str, job_id: str, model: type[M], run: Callable[[], Awaitable[M]]
) -> M:
    """同一個 (key, action) 只執行一次：先佔用鍵，執行成功後存下回應；再次呼叫時回傳存下的回應。
    執行失敗時放掉鍵（呼叫端可以重試）；另一個相同的請求還在處理中時回 409。"""
    if key is None:
        return await run()
    now = utc_now()
    async with services.db.session() as s:
        await s.execute(
            delete(AutomationRequestRow).where(AutomationRequestRow.created_at < now - timedelta(days=IDEMPOTENCY_DAYS))
        )
        claimed = await s.execute(
            pg_insert(AutomationRequestRow)
            .values(key=key, action=action, job_id=job_id, response=None, created_at=now)
            .on_conflict_do_nothing()
            .returning(AutomationRequestRow.key)
        )
        mine = claimed.scalar() is not None
        await s.commit()
        if not mine:
            row = await s.get(AutomationRequestRow, (key, action))
            if row is None or row.response is None:
                raise Conflict('同一個請求正在處理中，請稍後再試')
            return model.model_validate(row.response)
    try:
        result = await run()
    except BaseException:
        async with services.db.session() as s:
            await s.execute(
                delete(AutomationRequestRow).where(
                    AutomationRequestRow.key == key, AutomationRequestRow.action == action
                )
            )
            await s.commit()
        raise
    async with services.db.session() as s:
        row = await s.get(AutomationRequestRow, (key, action))
        assert row is not None
        row.response = result.to_json()
        await s.commit()
    return result


class ApproveRequest(Model):
    #: 不填就用分數最高的候選圖
    render_id: str | None = None


class ReviseRequest(Model):
    feedback: str = Field(min_length=1, max_length=500)


@router.post('/jobs/{job_id}/approve', status_code=201)
async def approve(
    job_id: str, body: ApproveRequest, services: Services, idempotency_key: IdempotencyKey = None
) -> HistoryEntry:
    """以候選圖本身的文案選定它（寫入歷史紀錄並回寫 RAG），與 Studio 的選定相同。"""

    async def run() -> HistoryEntry:
        async with services.db.session() as s:
            snap = await jobs.get_job(s, job_id)
            if snap is None:
                raise NotFound(f'找不到任務：{job_id}')
            if snap.summary.stage not in ('done', 'needs_review'):
                raise Conflict(f'任務還沒有可選的候選圖（目前階段：{snap.summary.stage}）')
            render_id = body.render_id
            if render_id is None:
                top = best(candidates(snap.summary.best_render_ids, snap.events))
                if top is None:
                    raise Conflict('任務沒有審查過的候選圖')
                render_id = top['renderId']
            render = await jobs.get_render(s, job_id, render_id)
        if render is None:
            raise NotFound(f'找不到候選圖：{render_id}')
        return await record_selection(services, job_id, render_id, render.spec.copy_)

    return await idempotent(services, idempotency_key, 'approve', job_id, HistoryEntry, run)


@router.post('/jobs/{job_id}/revise', status_code=201)
async def revise(
    job_id: str, body: ReviseRequest, services: Services, idempotency_key: IdempotencyKey = None
) -> JobCreated:
    """以原任務的輸入另開新任務，附上審核者的修改意見；client_ref 沿用，parent_job_id 指向原任務。"""

    async def run() -> JobCreated:
        async with services.db.session() as s:
            row = await s.get(JobRow, job_id)
            if row is None:
                raise NotFound(f'找不到任務：{job_id}')
            if row.stage not in FINISHED_STAGES:
                raise Conflict('任務還沒結束，不能退回')
            if await jobs.ancestor_count(s, job_id, MAX_REVISIONS) >= MAX_REVISIONS:
                raise Conflict(f'已退回 {MAX_REVISIONS} 次，請到 Studio 手動處理')
            job_input = JobInput.model_validate(row.input)
            meta = JobMeta(client_ref=row.client_ref, parent_job_id=job_id, reviewer_feedback=body.feedback)
        return JobCreated(job_id=await submit_job(services, job_input, meta))

    return await idempotent(services, idempotency_key, 'revise', job_id, JobCreated, run)
