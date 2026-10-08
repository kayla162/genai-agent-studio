"""後端設定：環境變數（或 repo 根目錄的 .env）覆寫預設值。

預設值對應本機開發：docker compose 的 postgres 在 5433；用 127.0.0.1 而不是 localhost
（Windows 會先嘗試 IPv6 的 ::1，連不上要等約 2 秒才改用 IPv4）。
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

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


settings = Settings()
