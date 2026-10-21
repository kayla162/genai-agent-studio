"""資料庫測試需要 docker compose 的 postgres、redis 與 chroma（docker compose up -d postgres redis chroma）。

每次測試開始時重建 genai_test 資料庫並跑 migration；每個測試結束後清空所有資料表。
Chroma 使用另一個 database genai_test；每個測試結束後刪除所有 collection。
"""

import asyncio
import os
import subprocess
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import httpx
import pytest
import uvicorn
from redis.asyncio import Redis
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.composer import ComposerClient
from app.api.main import create_app
from app.api.services import ApiServices
from app.cutout.engine import CutoutEngine
from app.db.session import Database
from app.events import EventStore
from app.pipeline.sim import SimAgent, sim_ports
from app.queues import Queues
from app.rag.store import VectorStore
from app.settings import REPO_ROOT, Settings, settings
from app.worker import Services as WorkerServices
from app.worker import build_workers

TEST_DATABASE = 'genai_test'
#: 測試使用 Redis 的第 15 個資料庫，開始時清空
TEST_REDIS_URL = settings.redis_url.rsplit('/', 1)[0] + '/15'
#: 測試使用 Chroma 的另一個 database（default_tenant 之下）
TEST_CHROMA_DATABASE = 'genai_test'


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


@pytest.fixture(scope='session')
async def chroma_store() -> AsyncIterator[VectorStore]:
    """建立 Chroma 的 genai_test database（已經有時沿用），並刪除上次留下的 collection。"""
    async with httpx.AsyncClient(base_url=settings.chroma_url) as http:
        res = await http.post('/api/v2/tenants/default_tenant/databases', json={'name': TEST_CHROMA_DATABASE})
        # 409：database 已經存在
        if res.status_code != 409:
            res.raise_for_status()
    store = VectorStore(settings.chroma_url, database=TEST_CHROMA_DATABASE)
    for brand_id in await store.brands():
        await store.drop(brand_id)
    yield store


@pytest.fixture
async def chroma(chroma_store: VectorStore) -> AsyncIterator[VectorStore]:
    yield chroma_store
    for brand_id in await chroma_store.brands():
        await chroma_store.drop(brand_id)


@pytest.fixture(scope='session')
def composer_url() -> Iterator[str]:
    """在 3902 埠啟動 composer（需要 web/ 已 npm install）。"""
    port = 3902
    url = f'http://127.0.0.1:{port}'
    proc = subprocess.Popen(
        ['node', '--import', 'tsx', 'composer/server.ts'],
        cwd=REPO_ROOT / 'web',
        env={**os.environ, 'PORT': str(port)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                if httpx.get(f'{url}/health').status_code == 200:
                    break
            except httpx.HTTPError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)
        yield url
    finally:
        proc.terminate()
        proc.wait(10)


@pytest.fixture
async def session(db: Database) -> AsyncIterator[AsyncSession]:
    async with db.session() as s:
        yield s
    await db.truncate_all()


@dataclass
class LiveApi:
    """在測試的 event loop 內以 uvicorn 執行的 api；worker 只在需要的測試中啟動。"""

    http: httpx.AsyncClient
    ws_url: str
    services: ApiServices
    composer_url: str

    @asynccontextmanager
    async def worker(self, speed: float = 0) -> AsyncIterator[None]:
        s = self.services
        composer = ComposerClient(self.composer_url)
        ports = sim_ports(composer, first_round_fail=True, force_all_fail=False)
        cutouts = CutoutEngine('sim', s.settings.data_dir / 'models', s.redis)
        worker_services = WorkerServices(s.db, s.redis, s.store, composer, ports, speed, s.settings, cutouts)
        workers = build_workers(worker_services, s.queues)
        started = [asyncio.create_task(w.start()) for w in workers]
        try:
            yield
        finally:
            for w in workers:
                await w.stop()
            await asyncio.gather(*started, return_exceptions=True)
            await composer.aclose()


@pytest.fixture
async def api(db: Database, redis: Redis, composer_url: str, tmp_path: Path) -> AsyncIterator[LiveApi]:
    """data/ 與本機資料夾指向 tmp_path；品牌設定檔使用 repo 的 brands/。"""
    await redis.flushdb()
    queues = Queues(TEST_REDIS_URL)
    await queues.connect()
    composer = ComposerClient(composer_url)
    agent = SimAgent(composer, first_round_fail=True, force_all_fail=False)
    test_settings = Settings(data_dir=tmp_path / 'data', local_photos_dir=tmp_path / 'local')
    services = ApiServices(test_settings, db, redis, EventStore(db, redis), queues, composer, agent)
    await services.sync_brands()
    server = uvicorn.Server(uvicorn.Config(create_app(services), host='127.0.0.1', port=0, log_level='warning'))
    serving = asyncio.create_task(server.serve())
    while not server.started:
        if serving.done():
            serving.result()
            raise RuntimeError('uvicorn 沒有啟動')
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}', timeout=30) as http:
            yield LiveApi(http, f'ws://127.0.0.1:{port}', services, composer_url)
    finally:
        server.should_exit = True
        await serving
        await queues.disconnect()
        await composer.aclose()
        await db.truncate_all()
