"""Alembic：資料表定義來自 app.db.models，網址來自 app.settings。

Database.migrate() 會把連線放在 config.attributes['connection']，在執行中的 event loop 內直接使用；
命令列（uv run alembic upgrade head）則自行建立連線。
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.models import Base
from app.settings import settings

config = context.config
if config.config_file_name is not None and 'connection' not in config.attributes:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_with_own_engine() -> None:
    engine = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif 'connection' in config.attributes:
    run(config.attributes['connection'])
else:
    asyncio.run(run_with_own_engine())
