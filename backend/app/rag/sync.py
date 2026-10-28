"""PostgreSQL → Chroma 的同步：brand_chunks 為準，Chroma 只是索引，資料遺失時會自動重建。

比對 Chroma 中每個切塊的 metadata（含向量化模型的指紋）：缺少或不同的重新向量化後 upsert，PostgreSQL 已沒有的刪除。
沒有差異時只查一次資料庫與一次 Chroma，不會載入模型。
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from itertools import batched

from app.contract import RagChunk, RagHit
from app.db.session import Database
from app.rag.engine import RagEngine
from app.rag.models import EMBEDDER
from app.rag.store import VectorRecord, VectorStore
from app.repo import catalog

logger = logging.getLogger(__name__)

#: 每向量化幾個切塊就寫入 Chroma 一次：重建大量切塊時中途失敗，已完成的不必重算
UPSERT_BATCH = 32


def index_text(chunk: RagChunk | RagHit) -> str:
    """向量化（以及 Rerank）的文字：章節名稱也帶有語意，例如「§2.1 色彩系統」。"""
    return f'{chunk.section}：{chunk.text}'


def text_hash(text: str) -> str:
    """向量化文字的 SHA-256 前 16 碼。"""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


#: 向量化模型的指紋（模型檔 SHA-256 的前 12 碼）：換了模型或版本時，舊的向量全部重新計算
EMBEDDER_FINGERPRINT = EMBEDDER.sha256[:12]


def chunk_metadata(brand_id: str, chunk: RagChunk, origin: str) -> dict[str, str]:
    """寫進 Chroma 的 metadata。同步時比對整份 metadata：
    內文、章節、tag、source、向量化模型任何一項改變都會重新寫入。"""
    return {
        'brandId': brand_id,
        'tag': chunk.tag,
        'source': chunk.source,
        'section': chunk.section,
        'origin': origin,
        'textHash': text_hash(index_text(chunk)),
        'embedder': EMBEDDER_FINGERPRINT,
    }


async def vector_record(engine: RagEngine, brand_id: str, chunk: RagChunk, origin: str) -> VectorRecord:
    """向量化一個切塊（上傳手冊、歷史回寫也用這個寫入 Chroma）。"""
    embedding = await engine.embed(index_text(chunk))
    return VectorRecord(chunk.id, embedding, chunk.text, chunk_metadata(brand_id, chunk, origin))


class BrandLocks:
    """worker 行程內每個品牌一把鎖。同步、上傳與回寫寫入 Chroma 前都要取得，避免同步時誤刪剛寫入的切塊。"""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def __call__(self, brand_id: str) -> asyncio.Lock:
        return self._locks.setdefault(brand_id, asyncio.Lock())


@dataclass(frozen=True)
class SyncResult:
    #: 重新向量化並寫入的切塊數（新增或內容改變）
    embedded: int
    #: 從 Chroma 刪除的切塊數
    removed: int


async def sync_brand(
    db: Database, store: VectorStore, engine: RagEngine, locks: BrandLocks, brand_id: str
) -> SyncResult:
    """比對並修正一個品牌（持有品牌鎖）。"""
    async with locks(brand_id):
        async with db.session() as s:
            chunks = await catalog.list_chunks(s, brand_id)
        stored = await store.metadata(brand_id)
        wanted = {c.id for c, _ in chunks}
        removed = [id_ for id_ in stored if id_ not in wanted]
        await store.delete(brand_id, ids=removed)
        changed = [(c, origin) for c, origin in chunks if stored.get(c.id) != chunk_metadata(brand_id, c, origin)]
        for batch in batched(changed, UPSERT_BATCH, strict=False):
            await store.upsert(brand_id, [await vector_record(engine, brand_id, c, origin) for c, origin in batch])
        return SyncResult(embedded=len(changed), removed=len(removed))


async def sync_all(db: Database, store: VectorStore, engine: RagEngine, locks: BrandLocks) -> None:
    """worker 啟動時：依序同步所有啟用中的品牌，並刪除已停用品牌的 collection。"""
    async with db.session() as s:
        active = await catalog.active_brand_ids(s)
    changed = False
    for brand_id in active:
        result = await sync_brand(db, store, engine, locks, brand_id)
        if result.embedded or result.removed:
            changed = True
            logger.info('RAG 同步 %s：向量化 %d 個切塊、刪除 %d 個', brand_id, result.embedded, result.removed)
    for brand_id in await store.brands():
        if brand_id not in active:
            changed = True
            async with locks(brand_id):
                await store.drop(brand_id)
            logger.info('RAG 同步：刪除已停用品牌 %s 的 collection', brand_id)
    if not changed:
        # 沒有差異時也留一行紀錄，重新啟動 worker 後可以確認沒有重新向量化
        logger.info('RAG 同步完成：%d 個品牌的索引都沒有差異', len(active))
