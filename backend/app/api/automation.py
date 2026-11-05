"""n8n 等自動化呼叫端的 API（Authorization: Bearer AUTOMATION_TOKEN）。

內部重用 Studio 的建任務與選圖邏輯；AUTOMATION_TOKEN 為空時整組回 404（像是不存在）。
"""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import Field

from app.api.catalog import api_options
from app.api.jobs import JobCreated, JobMeta, parse_text, submit_job
from app.api.services import Services
from app.contract import JobInput, Model, TemplateId
from app.errors import Invalid, NotFound, Unauthorized
from app.repo import catalog

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
