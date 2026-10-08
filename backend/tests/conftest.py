"""資料庫測試需要 docker compose 的 postgres（docker compose up -d postgres redis）。

每次測試開始時重建 genai_test 資料庫並跑 migration；每個測試結束後清空所有資料表。
"""

from collections.abc import AsyncIterator

import asyncpg
import pytest
from redis.asyncio import Redis
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.settings import settings

TEST_DATABASE = 'genai_test'
#: 測試使用 Redis 的第 15 個資料庫，開始時清空
TEST_REDIS_URL = settings.redis_url.rsplit('/', 1)[0] + '/15'


@pytest.fixture(scope='session')
async def db() -> AsyncIterator[Database]:
    url = make_url(settings.database_url)
    admin = await asyncpg.connect(
        user=url.username, password=url.password, host=url.host, port=url.port, database='postgres'
    )
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS {TEST_DATABASE} WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE {TEST_DATABASE}')
    finally:
        await admin.close()
    database = Database(url.set(database=TEST_DATABASE).render_as_string(hide_password=False))
    await database.migrate()
    yield database
    await database.dispose()


@pytest.fixture(scope='session')
async def redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    await client.flushdb()
    yield client
    await client.aclose()


@pytest.fixture
async def session(db: Database) -> AsyncIterator[AsyncSession]:
    async with db.session() as s:
        yield s
    await db.truncate_all()
