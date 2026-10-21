"""PostgreSQL → Chroma 的同步：示範品牌的切塊、FakeEncoder 與 Chroma 的 genai_test database。"""

import asyncio
import logging
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.brands import load_brands
from app.contract import RagChunk
from app.db.models import BrandChunkRow
from app.db.session import Database
from app.rag.store import VectorRecord, VectorStore
from app.rag.sync import BrandLocks, SyncResult, chunk_metadata, index_text, sync_all, sync_brand, text_hash
from app.repo import catalog
from tests.fake_encoder import FakeEncoder, fake_engine
from tests.fixtures import BRANDS_DIR

NOW = datetime(2026, 10, 21, 1, 0, tzinfo=UTC)
UPLOAD = [
    RagChunk(id='selune#doc-x-1', source='手冊.md', section='§9 包裝', tag='general', text='外盒需印上回收標誌。'),
    RagChunk(id='selune#doc-x-2', source='手冊.md', section='§9 包裝', tag='logo', text='Logo 置於正面左上角。'),
]


@pytest.fixture
async def brands(session: AsyncSession) -> AsyncSession:
    await catalog.sync_brands(session, load_brands(BRANDS_DIR)[0], NOW)
    return session


def test_index_text_and_hash() -> None:
    chunk = RagChunk(id='a#color', source='ci.md', section='§2.1 色彩系統', tag='color', text='主色為品牌紫。')
    assert index_text(chunk) == '§2.1 色彩系統：主色為品牌紫。'
    # 「章節：內文」UTF-8 的 SHA-256 前 16 碼
    assert text_hash(index_text(chunk)) == '86ccbb049fa2565a'
    assert chunk_metadata('a', chunk, 'config') == {
        'brandId': 'a',
        'tag': 'color',
        'source': 'ci.md',
        'section': '§2.1 色彩系統',
        'origin': 'config',
        'textHash': '86ccbb049fa2565a',
    }


async def test_sync_adds_every_chunk_with_its_text_and_metadata(
    brands: AsyncSession, db: Database, redis: Redis, chroma: VectorStore
) -> None:
    encoder = FakeEncoder()
    result = await sync_brand(db, chroma, fake_engine(redis, encoder), BrandLocks(), 'selune')
    chunks = await catalog.list_chunks(brands, 'selune')
    assert result == SyncResult(embedded=len(chunks), removed=0)
    assert encoder.embedded == [index_text(c) for c, _ in chunks]
    assert await chroma.metadata('selune') == {c.id: chunk_metadata('selune', c, origin) for c, origin in chunks}
    assert (await chroma.metadata('selune'))['selune#law-alt']['origin'] == 'alt'
    # 文件是切塊的內文；向量是「章節：內文」的向量
    color = next(c for c, _ in chunks if c.id == 'selune#color')
    (hit,) = await chroma.query('selune', FakeEncoder.vector(index_text(color)), 1)
    assert (hit.id, hit.document) == ('selune#color', color.text)
    assert hit.score == pytest.approx(1, abs=1e-5)
    # 其他品牌不受影響
    assert await chroma.brands() == ['selune']


async def test_sync_without_differences_does_not_embed_or_load_the_model(
    brands: AsyncSession, db: Database, redis: Redis, chroma: VectorStore
) -> None:
    locks = BrandLocks()
    await sync_brand(db, chroma, fake_engine(redis, FakeEncoder()), locks, 'selune')
    encoder = FakeEncoder()
    engine = fake_engine(redis, encoder)
    assert await sync_brand(db, chroma, engine, locks, 'selune') == SyncResult(embedded=0, removed=0)
    assert encoder.embedded == []
    assert not engine.loaded


async def test_sync_embeds_added_and_changed_chunks_and_removes_deleted_ones(
    brands: AsyncSession, db: Database, redis: Redis, chroma: VectorStore
) -> None:
    locks = BrandLocks()
    await sync_brand(db, chroma, fake_engine(redis, FakeEncoder()), locks, 'selune')
    await catalog.replace_document_chunks(brands, 'selune', '手冊.md', UPLOAD, NOW)
    await brands.execute(update(BrandChunkRow).where(BrandChunkRow.id == 'selune#color').values(text='主色改為深紫。'))
    # 只改 tag（向量化的文字不變）也要重新寫入，重新檢索以 tag 篩選
    await brands.execute(update(BrandChunkRow).where(BrandChunkRow.id == 'selune#logo').values(tag='law'))
    await brands.execute(delete(BrandChunkRow).where(BrandChunkRow.id == 'selune#case-1'))
    await brands.commit()

    encoder = FakeEncoder()
    result = await sync_brand(db, chroma, fake_engine(redis, encoder), locks, 'selune')
    chunks = await catalog.list_chunks(brands, 'selune')
    by_id = {c.id: c for c, _ in chunks}
    assert result == SyncResult(embedded=4, removed=1)
    assert sorted(encoder.embedded) == sorted(
        index_text(by_id[i]) for i in ('selune#color', 'selune#logo', 'selune#doc-x-1', 'selune#doc-x-2')
    )
    stored = await chroma.metadata('selune')
    assert stored == {c.id: chunk_metadata('selune', c, origin) for c, origin in chunks}
    assert stored['selune#logo']['tag'] == 'law'
    assert stored['selune#doc-x-1']['origin'] == 'upload'
    assert 'selune#case-1' not in stored


async def test_sync_rebuilds_a_lost_collection(
    brands: AsyncSession, db: Database, redis: Redis, chroma: VectorStore
) -> None:
    locks = BrandLocks()
    first = await sync_brand(db, chroma, fake_engine(redis, FakeEncoder()), locks, 'misty-isle')
    await chroma.drop('misty-isle')
    again = await sync_brand(db, chroma, fake_engine(redis, FakeEncoder()), locks, 'misty-isle')
    assert again == first
    assert len(await chroma.metadata('misty-isle')) == first.embedded


async def test_sync_all_syncs_active_brands_and_drops_inactive_collections(
    brands: AsyncSession, db: Database, redis: Redis, chroma: VectorStore
) -> None:
    locks = BrandLocks()
    engine = fake_engine(redis, FakeEncoder())
    await sync_all(db, chroma, engine, locks)
    assert await chroma.brands() == ['misty-isle', 'selune']

    # misty-isle 的設定檔移除後停用；另一個 collection 的品牌從來不存在
    await catalog.sync_brands(brands, [b for b in load_brands(BRANDS_DIR)[0] if b.brand.id == 'selune'], NOW)
    await chroma.upsert('gone', [VectorRecord('gone#a', [1.0] * 1024, '內文', {'origin': 'config'})])
    encoder = FakeEncoder()
    await sync_all(db, chroma, fake_engine(redis, encoder), locks)
    assert await chroma.brands() == ['selune']
    assert encoder.embedded == []


async def test_sync_all_logs_a_line_when_every_index_is_current(
    brands: AsyncSession, db: Database, redis: Redis, chroma: VectorStore, caplog: pytest.LogCaptureFixture
) -> None:
    locks = BrandLocks()
    await sync_all(db, chroma, fake_engine(redis, FakeEncoder()), locks)
    caplog.set_level(logging.INFO, logger='app.rag.sync')
    await sync_all(db, chroma, fake_engine(redis, FakeEncoder()), locks)
    assert caplog.messages == ['RAG 同步完成：2 個品牌的索引都沒有差異']


async def test_brand_locks_serialise_writes_per_brand(
    brands: AsyncSession, db: Database, redis: Redis, chroma: VectorStore
) -> None:
    locks = BrandLocks()
    assert locks('selune') is locks('selune')
    assert locks('selune') is not locks('misty-isle')
    engine = fake_engine(redis, FakeEncoder())
    async with locks('selune'):
        waiting = asyncio.create_task(sync_brand(db, chroma, engine, locks, 'selune'))
        # 其他品牌不必等
        assert (await sync_brand(db, chroma, engine, locks, 'misty-isle')).embedded > 0
        await asyncio.sleep(0.1)
        assert not waiting.done()
        assert await chroma.metadata('selune') == {}
    assert (await waiting).embedded > 0
