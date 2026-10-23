"""後端設定：環境變數（或 repo 根目錄的 .env）覆寫預設值。

預設值對應本機開發：docker compose 的 postgres 在 5433；用 127.0.0.1 而不是 localhost
（Windows 會先嘗試 IPv6 的 ::1，連不上要等約 2 秒才改用 IPv4）。
"""

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.rag.state import RagMode

#: 審查：composer（伺服器端繪製審查用海報、量主色、規則審查）或 sim（不畫圖，沿用 mock 的審查；測試與作品集 Demo）
ReviewMode = Literal['composer', 'sim']
#: Agent 與 VLM：gemini（Gemini 拆解需求、構建 Prompt、Query Rewriting 與 VLM 審查）或 sim（模擬，測試與作品集 Demo）
AgentMode = Literal['gemini', 'sim']

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / '.env', extra='ignore')

    database_url: str = 'postgresql+asyncpg://genai:genai@127.0.0.1:5433/genai'
    redis_url: str = 'redis://127.0.0.1:6379/0'
    brands_dir: Path = REPO_ROOT / 'brands'
    #: 商品照、去背圖、生成圖、審查用海報
    data_dir: Path = REPO_ROOT / 'data'
    #: 使用者自己的商品照（唯讀）
    local_photos_dir: Path = REPO_ROOT / 'assets' / 'products'
    composer_url: str = 'http://127.0.0.1:3900'
    #: 任務 id 使用的本地時間（與前端 mock 的 makeJobId 一樣顯示使用者所在地的日期時間）
    timezone: str = 'Asia/Taipei'

    #: AGENT_MODE=sim 時前端可選的模型名稱（JobInput.llm、JobInput.vlm）；
    #: gemini 模式改用 gemini_llm_model 與 gemini_vlm_model
    llm_model: str = 'Gemini 3.7 Flash'
    vlm_model: str = 'Gemini 3.7 Vision'

    #: Agent 與 VLM 一起切換：gemini（預設，需要 GEMINI_API_KEY 與 REVIEW_MODE=composer）或 sim
    agent_mode: AgentMode = 'gemini'
    #: Gemini API key（repo 根目錄的 .env，不進 git）；只在建立 SDK client 時取值，系統狀態只顯示末 4 碼
    gemini_api_key: SecretStr = SecretStr('')
    #: 需求拆解、Prompt 構建、Query Rewriting
    gemini_llm_model: str = 'gemini-3.8-flash'
    #: 審查
    gemini_vlm_model: str = 'gemini-3.8-flash'
    #: 每次請求的逾時（秒）
    gemini_timeout_seconds: float = Field(default=60, gt=0)
    #: 429、5xx、逾時的重試次數
    gemini_max_retries: int = Field(default=3, ge=0)
    #: 每個 worker 同時進行的 Gemini 呼叫數
    gemini_concurrency: int = Field(default=4, ge=1)
    #: 單一任務的 Gemini 費用上限（美元），0 為不設上限
    gemini_job_budget_usd: float = Field(default=1, ge=0)
    #: 每月（台北時間）的 Gemini 費用上限（美元），0 為不設上限
    gemini_monthly_budget_usd: float = Field(default=20, ge=0)
    #: Gemini 單價表（Docker 內為 /app/pricing.yaml）
    pricing_file: Path = REPO_ROOT / 'pricing.yaml'

    #: 去背模型：birefnet-general（預設）、birefnet-general-lite，或不需要模型的 sim（測試與 live E2E）
    cutout_model: str = 'birefnet-general'
    #: 去背與 RAG 模型的存放位置（Docker 為 models volume）
    models_dir: Path = REPO_ROOT / 'models'

    #: RAG：bge（BGE-M3＋Reranker＋Chroma，第一次啟動時下載模型約 1.2 GB），
    #: 或不需要模型與 Chroma 的 sim（測試與 live E2E）
    rag_mode: RagMode = 'bge'
    #: 向量庫（Docker 內為 http://chroma:8000）
    chroma_url: str = 'http://127.0.0.1:8001'

    #: 審查：composer（預設；composer 繪製審查用海報存到 data/jobs/，量出主色後審查，分數不加抖動）
    #: 或 sim（不畫圖，審查結果與前端 mock 相同）
    review_mode: ReviewMode = 'composer'

    #: 模擬模式的播放速度（1 為 1× 時間軸，約 15 秒一個任務；0 為不等待）
    sim_speed: float = 1.0
    #: 模擬模式：第一輪刻意失誤（觸發 Query Rewriting）
    sim_first_round_fail: bool = True
    #: 模擬模式：每一輪都失誤（展示「需人工審核」）
    sim_force_all_fail: bool = False

    @model_validator(mode='after')
    def _gemini_needs_the_composer_review(self) -> Self:
        """Gemini 的 VLM 審查要讀伺服器端繪製的審查用海報，所以 AGENT_MODE=gemini 不能搭配 REVIEW_MODE=sim。
        settings 在匯入時建立，所以 api 與 worker 會在啟動時失敗並顯示這個原因。"""
        if self.agent_mode == 'gemini' and self.review_mode == 'sim':
            raise ValueError(
                'AGENT_MODE=gemini 需要 REVIEW_MODE=composer（目前為 sim）：'
                '請改為 REVIEW_MODE=composer，或設定 AGENT_MODE=sim'
            )
        return self


settings = Settings()
