"""真實版的檢索（Retriever 介面）：BGE-M3 向量化查詢 → Chroma 召回 → bge-reranker-v2-m3 逐筆 Rerank。

檢索前先同步品牌（PostgreSQL → Chroma），所以不必依賴 worker 啟動時的同步是否完成。
模型或 Chroma 無法使用時丟出 RagError（中文訊息），任務以這個原因失敗。
"""

from app.contract import Brand, JobInput, Product, RagHit
from app.db.session import Database
from app.pipeline.ports import RunContext
from app.rag.engine import RagEngine
from app.rag.store import VectorHit, VectorStore, Where
from app.rag.sync import BrandLocks, index_text, sync_brand

#: 第一次檢索的召回筆數（全部 Rerank 後，前 5 筆進入 Prompt，見 runner.PROMPT_REFS）
RECALL_K = 8
#: Query Rewriting 重新檢索的召回筆數
REQUERY_K = 4
#: 第一次檢索不含合規替代用語（只在 Query Rewriting 時使用）
RECALL_WHERE: Where = {'origin': {'$ne': 'alt'}}
#: 重新檢索只找合規替代用語與法規切塊
REQUERY_WHERE: Where = {'$or': [{'origin': 'alt'}, {'tag': 'law'}]}
#: 模型還沒載入時（下載或載入中），任務在 retrieving 階段等候並送出這則 log
PREPARING = 'RAG 模型準備中'


def build_query(brand: Brand, product: Product, job_input: JobInput) -> str:
    """「品牌名｜商品名｜一句話需求｜賣點」，空的部分略過。
    賣點取 parsedBrief.sellingPoints，沒有時改用商品的 features，以「、」連接。"""
    points = job_input.parsed_brief.selling_points or product.features
    parts = [brand.name, product.name, job_input.brief, '、'.join(points)]
    return '｜'.join(p for p in parts if p)


def _hit(hit: VectorHit) -> RagHit:
    meta = hit.metadata
    # 以 model_validate 建立：tag 是 metadata 的字串，由 RagHit 檢查是否為合法的 tag
    return RagHit.model_validate(
        {
            'chunk_id': hit.id,
            'source': meta['source'],
            'section': meta['section'],
            'tag': meta['tag'],
            'text': hit.document,
            'vector_score': hit.score,
        }
    )


class BgeRetriever:
    def __init__(self, db: Database, store: VectorStore, engine: RagEngine, locks: BrandLocks) -> None:
        self.db = db
        self.store = store
        self.engine = engine
        self.locks = locks

    async def retrieve(
        self, brand: Brand, product: Product, job_input: JobInput, run: RunContext
    ) -> tuple[str, list[RagHit]]:
        """同步品牌 → 向量召回 8 筆（不含 alt），依向量分數由高到低。"""
        if not self.engine.loaded:
            await run.log('rag', PREPARING)
        await sync_brand(self.db, self.store, self.engine, self.locks, brand.id)
        query = build_query(brand, product, job_input)
        return query, await self._recall(brand.id, query, RECALL_K, RECALL_WHERE)

    async def rerank(self, query: str, hits: list[RagHit]) -> list[RagHit]:
        """逐筆計算 sigmoid(logit)，由高到低排序；同分時維持原本（向量）的順序。"""
        if not hits:
            return []
        scores = await self.engine.rerank(query, [index_text(h) for h in hits])
        scored = [h.model_copy(update={'rerank_score': s}) for h, s in zip(hits, scores, strict=True)]
        return sorted(scored, key=lambda h: -(h.rerank_score or 0))

    async def requery(self, brand: Brand, query: str) -> list[RagHit]:
        """Query Rewriting：召回 4 筆合規替代用語或法規切塊並 Rerank（同一個任務開頭已同步過品牌）。"""
        return await self.rerank(query, await self._recall(brand.id, query, REQUERY_K, REQUERY_WHERE))

    async def _recall(self, brand_id: str, query: str, k: int, where: Where) -> list[RagHit]:
        embedding = await self.engine.embed(query)
        return [_hit(h) for h in await self.store.query(brand_id, embedding, k, where)]
