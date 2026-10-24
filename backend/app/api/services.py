"""api 使用的服務：資料庫、Redis、事件、佇列、composer、Agent（拆解需求）與 Gemini 的用量。

api 不載入任何模型；生圖、文件上傳、去背與回寫都放進佇列交給 worker。
"""

from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from starlette.requests import HTTPConnection

from app.adapters.comfyui import ComfyClient
from app.adapters.composer import ComposerClient
from app.adapters.gemini import GeminiClient
from app.brands import BrandLoadError, load_brands
from app.core.clock import utc_now
from app.db.session import Database
from app.events import EventStore
from app.pipeline.gemini import GeminiAgent
from app.pipeline.ports import Agent
from app.pipeline.sim import SimAgent
from app.queues import Queues
from app.repo import catalog
from app.settings import Settings
from app.usage import Pricing, UsageLedger


@dataclass
class ApiServices:
    settings: Settings
    db: Database
    redis: Redis
    store: EventStore
    queues: Queues
    composer: ComposerClient
    agent: Agent
    #: 格式錯誤而略過的品牌設定檔（系統狀態顯示原因）
    brand_errors: list[BrandLoadError] = field(default_factory=list)
    #: AGENT_MODE=gemini 時的 Gemini client（需求拆解與系統狀態的 models.get）
    gemini: GeminiClient | None = None
    #: Gemini 的用量、上限與單價表（AGENT_MODE=gemini）
    ledger: UsageLedger | None = None
    #: IMAGE_MODE=comfyui 時的 ComfyUI client（系統狀態檢查連線、節點與模型）
    comfy: ComfyClient | None = None

    async def sync_brands(self) -> None:
        """品牌設定檔 → 資料庫（api 啟動時執行）。"""
        loaded, self.brand_errors = load_brands(self.settings.brands_dir)
        async with self.db.session() as s:
            await catalog.sync_brands(s, loaded, utc_now())


async def start_services(settings: Settings) -> ApiServices:
    """連線、執行 migration、匯入品牌設定檔。worker 等 api 健康後才啟動，所以 migration 只在這裡跑。"""
    db = Database(settings.database_url)
    await db.migrate()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    queues = Queues(settings.redis_url)
    await queues.connect()
    composer = ComposerClient(settings.composer_url)
    agent: Agent
    gemini: GeminiClient | None = None
    ledger: UsageLedger | None = None
    if settings.agent_mode == 'gemini':
        ledger = UsageLedger(
            db,
            Pricing.load_or_unavailable(settings.pricing_file),
            job_budget=settings.gemini_job_budget_usd,
            monthly_budget=settings.gemini_monthly_budget_usd,
        )
        gemini = GeminiClient(settings, ledger)
        agent = GeminiAgent(gemini, composer, settings)
    else:
        agent = SimAgent(
            composer, first_round_fail=settings.sim_first_round_fail, force_all_fail=settings.sim_force_all_fail
        )
    comfy = ComfyClient(settings) if settings.image_mode == 'comfyui' else None
    services = ApiServices(
        settings, db, redis, EventStore(db, redis), queues, composer, agent, gemini=gemini, ledger=ledger, comfy=comfy
    )
    await services.sync_brands()
    return services


async def stop_services(services: ApiServices) -> None:
    await services.queues.disconnect()
    await services.composer.aclose()
    if services.gemini is not None:
        await services.gemini.aclose()
    if services.comfy is not None:
        await services.comfy.aclose()
    await services.redis.aclose()
    await services.db.dispose()


def get_services(connection: HTTPConnection) -> ApiServices:
    services: ApiServices = connection.app.state.services
    return services


#: 路由函式的參數型別：services: Services
Services = Annotated[ApiServices, Depends(get_services)]
