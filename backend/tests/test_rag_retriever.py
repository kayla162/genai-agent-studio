"""BgeRetriever：FakeEncoder 與 Chroma 的 genai_test database（示範品牌的切塊，再加上幾份上傳的切塊）。"""

import asyncio
import threading
from collections.abc import Awaitable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.brands import load_brands
from app.contract import Brand, JobEvent, JobInput, LogLevel, LogSource, ParsedBrief, Product, RagChunk, RagHit
from app.db.session import Database
from app.pipeline.ports import JobCancelled
from app.rag.engine import RagEngine
from app.rag.retriever import PREPARING, RECALL_K, REQUERY_K, BgeRetriever, build_query
from app.rag.store import VectorStore
from app.rag.sync import BrandLocks, index_text
from app.repo import catalog
from tests.fake_encoder import FakeEncoder, fake_engine
from tests.fixtures import BRANDS_DIR, load_fixture

NOW = datetime(2026, 10, 21, 1, 0, tzinfo=UTC)
#: 上傳的手冊：讓品牌的一般切塊多於 8 個、法規切塊多於 4 個
UPLOAD = [
    RagChunk(id='selune#doc-x-1', source='手冊.md', section='§9 包裝', tag='general', text='外盒需印上回收標誌。'),
    RagChunk(id='selune#doc-x-2', source='手冊.md', section='§9 包裝', tag='law', text='保濕不可宣稱根治乾燥。'),
    RagChunk(id='selune#doc-x-3', source='手冊.md', section='§9 包裝', tag='law', text='廣告不得誇大保濕效果。'),
    RagChunk(id='selune#doc-x-4', source='手冊.md', section='§9 包裝', tag='law', text='療效宣稱一律禁用。'),
]
JOB_INPUT = JobInput.model_validate(load_fixture('timelines/selune-retry.json')['input'])


class RecordingRun:
    """記錄 log 的 RunContext。"""

    job_id = 'job_rag'

    def __init__(self) -> None:
        self.logs: list[tuple[LogSource, str]] = []

    async def wait[T](self, awaitable: Awaitable[T], note: str | None = None) -> T:
        return await awaitable

    async def emit(self, event: JobEvent) -> None:
        pass

    async def log(self, source: LogSource, message: str, level: LogLevel = 'info') -> None:
        self.logs.append((source, message))

    async def pace(self, ms: float) -> None:
        pass


@pytest.fixture
async def selune(session: AsyncSession) -> tuple[Brand, Product]:
    await catalog.sync_brands(session, load_brands(BRANDS_DIR)[0], NOW)
    await catalog.replace_document_chunks(session, 'selune', '手冊.md', UPLOAD, NOW)
    brand = await catalog.get_brand(session, 'selune')
    product = await catalog.get_product(session, JOB_INPUT.product_id)
    assert brand is not None and product is not None
    return brand, product


def cosine(a: str, b: str) -> float:
    return sum(x * y for x, y in zip(FakeEncoder.vector(a), FakeEncoder.vector(b), strict=True))


def test_build_query_uses_the_selling_points_or_else_the_product_features() -> None:
    brand = Brand.model_validate(load_fixture('brands.json')['brands'][0])
    product = Product.model_validate(load_fixture('brands.json')['products'][0])
    brief = ParsedBrief.model_validate({**JOB_INPUT.parsed_brief.to_json(), 'sellingPoints': ['長效保濕', '修護']})
    job_input = JOB_INPUT.model_copy(update={'parsed_brief': brief, 'brief': '秋季保濕主打'})
    assert build_query(brand, product, job_input) == f'{brand.name}｜{product.name}｜秋季保濕主打｜長效保濕、修護'
    no_points = job_input.model_copy(update={'parsed_brief': brief.model_copy(update={'selling_points': []})})
    features = '、'.join(product.features)
    assert build_query(brand, product, no_points) == f'{brand.name}｜{product.name}｜秋季保濕主打｜{features}'
    # 兩者都沒有時省略最後一段
    bare = product.model_copy(update={'features': []})
    assert build_query(brand, bare, no_points) == f'{brand.name}｜{product.name}｜秋季保濕主打'


async def test_retrieve_syncs_the_brand_and_recalls_eight_chunks_without_alt(
    selune: tuple[Brand, Product], db: Database, redis: Redis, chroma: VectorStore
) -> None:
    brand, product = selune
    encoder = FakeEncoder()
    retriever = BgeRetriever(db, chroma, fake_engine(redis, encoder), BrandLocks())
    query, hits = await retriever.retrieve(brand, product, JOB_INPUT, RecordingRun())

    assert query == build_query(brand, product, JOB_INPUT)
    # 先同步（每個切塊向量化一次），最後才是查詢
    assert len(await chroma.metadata('selune')) == len(brand.guideline_chunks)
    assert encoder.embedded[-1] == query
    assert len(encoder.embedded) == len(brand.guideline_chunks) + 1
    # 共 13 個切塊，其中 1 個是 alt：召回 8 個，依 cosine 由高到低
    assert len(hits) == RECALL_K
    assert all(not h.chunk_id.endswith('#law-alt') for h in hits)
    chunks = {c.id: c for c in brand.guideline_chunks}
    expected = sorted(
        (c for c in brand.guideline_chunks if not c.id.endswith('#law-alt')),
        key=lambda c: -cosine(query, index_text(c)),
    )
    assert [h.chunk_id for h in hits] == [c.id for c in expected[:RECALL_K]]
    for hit in hits:
        chunk = chunks[hit.chunk_id]
        assert (hit.source, hit.section, hit.tag, hit.text) == (chunk.source, chunk.section, chunk.tag, chunk.text)
        assert hit.vector_score == pytest.approx(cosine(query, index_text(chunk)), abs=1e-5)
        assert hit.rerank_score is None


async def test_rerank_scores_each_hit_and_keeps_the_vector_order_on_ties(
    db: Database, redis: Redis, chroma: VectorStore
) -> None:
    encoder = FakeEncoder()
    retriever = BgeRetriever(db, chroma, fake_engine(redis, encoder), BrandLocks())

    def hit(id_: str, text: str, score: float) -> RagHit:
        return RagHit(chunk_id=id_, source='ci.md', section='§1', tag='general', text=text, vector_score=score)

    hits = [
        hit('b#far', '咖啡產地', 0.9),
        hit('b#tie-1', '保濕', 0.8),
        hit('b#tie-2', '保濕', 0.7),
        hit('b#near', '保濕精華', 0.6),
    ]
    ranked = await retriever.rerank('保濕精華', hits)
    assert [h.chunk_id for h in ranked] == ['b#near', 'b#tie-1', 'b#tie-2', 'b#far']
    # 一次 Rerank 全部的切塊，段落為「章節：內文」；分數是 Encoder 的分數
    assert encoder.reranked == [('保濕精華', [index_text(h) for h in hits])]
    assert [h.rerank_score for h in ranked] == pytest.approx([cosine('保濕精華', index_text(h)) for h in ranked])
    assert [h.vector_score for h in ranked] == [0.6, 0.8, 0.7, 0.9]
    # 沒有切塊時不呼叫模型
    assert await retriever.rerank('保濕精華', []) == []
    assert len(encoder.reranked) == 1


async def test_requery_recalls_four_alt_or_law_chunks_with_rerank_scores(
    selune: tuple[Brand, Product], db: Database, redis: Redis, chroma: VectorStore
) -> None:
    brand, product = selune
    encoder = FakeEncoder()
    retriever = BgeRetriever(db, chroma, fake_engine(redis, encoder), BrandLocks())
    await retriever.retrieve(brand, product, JOB_INPUT, RecordingRun())
    query = '保養品 禁用詞 合規替代用語'
    hits = await retriever.requery(brand, query)
    # 候選：law、law-alt 與 3 個上傳的法規切塊
    assert len(hits) == REQUERY_K
    tags = {c.id: c.tag for c in brand.guideline_chunks}
    assert all(h.chunk_id.endswith('#law-alt') or tags[h.chunk_id] == 'law' for h in hits)
    assert all(h.rerank_score is not None for h in hits)
    assert [h.rerank_score for h in hits] == sorted((h.rerank_score or 0 for h in hits), reverse=True)
    assert encoder.embedded[-1] == query
    assert encoder.reranked[-1] == (query, [index_text(h) for h in sorted(hits, key=lambda h: -h.vector_score)])


async def test_a_brand_without_chunks_gets_no_hits(db: Database, redis: Redis, chroma: VectorStore) -> None:
    brand = Brand.model_validate({**load_fixture('brands.json')['brands'][0], 'id': 'empty', 'guidelineChunks': []})
    product = Product.model_validate(load_fixture('brands.json')['products'][0])
    retriever = BgeRetriever(db, chroma, fake_engine(redis, FakeEncoder()), BrandLocks())
    query, hits = await retriever.retrieve(brand, product, JOB_INPUT, RecordingRun())
    assert query and hits == []
    assert await retriever.rerank(query, hits) == []
    assert await retriever.requery(brand, '禁用詞') == []


async def test_logs_that_the_models_are_being_prepared_until_they_are_loaded(
    selune: tuple[Brand, Product], db: Database, redis: Redis, chroma: VectorStore
) -> None:
    brand, product = selune
    engine = fake_engine(redis, FakeEncoder())
    retriever = BgeRetriever(db, chroma, engine, BrandLocks())
    first, second = RecordingRun(), RecordingRun()
    await retriever.retrieve(brand, product, JOB_INPUT, first)
    assert first.logs == [('rag', PREPARING)]
    assert engine.loaded
    await retriever.retrieve(brand, product, JOB_INPUT, second)
    assert second.logs == []


class CancellingRun(RecordingRun):
    """等待超過 0.2 秒就視為使用者已取消（RunContext.wait 的行為：中斷 awaitable 再丟出 JobCancelled）。"""

    async def wait[T](self, awaitable: Awaitable[T], note: str | None = None) -> T:
        task = asyncio.ensure_future(awaitable)
        done, _ = await asyncio.wait({task}, timeout=0.2)
        if done:
            return task.result()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise JobCancelled


async def test_cancelling_while_the_models_are_prepared_stops_the_job_but_not_the_preparation(
    selune: tuple[Brand, Product], db: Database, redis: Redis, chroma: VectorStore
) -> None:
    brand, product = selune
    release = threading.Event()
    encoder = FakeEncoder()

    def load(_: Path) -> FakeEncoder:
        release.wait(5)
        return encoder

    engine = RagEngine('bge', Path('models'), redis, models=[], load=load)
    retriever = BgeRetriever(db, chroma, engine, BrandLocks())
    try:
        with pytest.raises(JobCancelled):
            await asyncio.wait_for(retriever.retrieve(brand, product, JOB_INPUT, CancellingRun()), 2)
    finally:
        release.set()
    # 準備沒有因為取消而中斷：下一個任務不必重新下載或載入
    assert await asyncio.wait_for(engine.encoder(), 2) is encoder
