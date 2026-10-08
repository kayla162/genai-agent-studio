"""資料庫連線：api 與 worker 各建立一個 Database；測試另外指向測試資料庫。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base
from app.settings import BACKEND_DIR


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True)
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._sessions() as session:
            yield session

    async def migrate(self) -> None:
        """alembic upgrade head（共用目前的連線，可在執行中的 event loop 內呼叫）。"""

        def upgrade(connection: Connection) -> None:
            config = Config(str(BACKEND_DIR / 'alembic.ini'))
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')

        async with self.engine.begin() as connection:
            await connection.run_sync(upgrade)

    async def truncate_all(self) -> None:
        """測試用：清空所有資料表。"""
        tables = ', '.join(t.name for t in Base.metadata.sorted_tables)
        async with self.engine.begin() as connection:
            await connection.execute(text(f'TRUNCATE {tables} CASCADE'))

    async def dispose(self) -> None:
        await self.engine.dispose()
