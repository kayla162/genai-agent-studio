"""向量庫：Chroma 的非同步 HTTP 客戶端（chromadb-client）。每個品牌一個 collection（{brandId}_ci），距離為 cosine。

只有 worker 寫入；資料以 PostgreSQL 為準，Chroma 只是索引（見 sync.py）。Chroma 的錯誤一律轉成 RagError。
"""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import chromadb
import httpx
from chromadb.api import AsyncClientAPI
from chromadb.api.models.AsyncCollection import AsyncCollection
from chromadb.api.types import PyEmbedding
from chromadb.config import DEFAULT_DATABASE
from chromadb.errors import NotFoundError

from app.rag.errors import RagError

#: collection 名稱：{brandId}_ci
SUFFIX = '_ci'
#: 每次呼叫 Chroma 最多等待的秒數（chromadb-client 的 HTTP 連線沒有逾時）
TIMEOUT = 30

#: Chroma 的 metadata 條件，例如 {'origin': {'$ne': 'alt'}}；兩個以上的條件要包在 $and 或 $or 裡
Where = dict[str, Any]


def collection_name(brand_id: str) -> str:
    return f'{brand_id}{SUFFIX}'


@dataclass(frozen=True)
class VectorRecord:
    id: str
    embedding: list[float]
    #: 切塊的內文
    document: str
    metadata: dict[str, str]


@dataclass(frozen=True)
class VectorHit:
    id: str
    document: str
    metadata: dict[str, str]
    #: cosine 相似度（1 - distance）
    score: float


def _strings(metadata: Mapping[str, object] | None) -> dict[str, str]:
    return {key: str(value) for key, value in (metadata or {}).items()}


class VectorStore:
    def __init__(self, url: str, *, database: str = DEFAULT_DATABASE) -> None:
        self.url = url
        self.database = database
        self._client: AsyncClientAPI | None = None
        self._connecting = asyncio.Lock()

    async def upsert(self, brand_id: str, records: Sequence[VectorRecord]) -> None:
        """一次最多 5461 筆（Chroma 的上限）。"""
        if not records:
            return
        embeddings: list[PyEmbedding] = [r.embedding for r in records]
        await self._run(
            brand_id,
            lambda c: c.upsert(
                ids=[r.id for r in records],
                embeddings=embeddings,
                metadatas=[r.metadata for r in records],
                documents=[r.document for r in records],
            ),
        )

    async def delete(self, brand_id: str, *, ids: Sequence[str] | None = None, where: Where | None = None) -> None:
        """依 id 或 metadata 條件刪除；沒有符合的切塊時不做任何事。"""
        if ids is not None and not ids:
            return
        await self._run(brand_id, lambda c: c.delete(ids=list(ids) if ids is not None else None, where=where))

    async def metadata(self, brand_id: str) -> dict[str, dict[str, str]]:
        """每個切塊的 metadata（id → metadata）：同步時與 PostgreSQL 比對，不讀向量。"""

        async def run(c: AsyncCollection) -> dict[str, dict[str, str]]:
            result = await c.get(include=['metadatas'])
            return {id_: _strings(m) for id_, m in zip(result['ids'], result['metadatas'] or [], strict=True)}

        return await self._run(brand_id, run)

    async def query(
        self, brand_id: str, embedding: Sequence[float], k: int, where: Where | None = None
    ) -> list[VectorHit]:
        """與 embedding 最相近的 k 個切塊，依相似度由高到低。"""
        query: list[PyEmbedding] = [list(embedding)]

        # 解讀結果也在 _call 裡：回應的格式不對時同樣轉成 RagError
        async def run(c: AsyncCollection) -> list[VectorHit]:
            result = await c.query(
                query_embeddings=query,
                n_results=k,
                where=where,
                include=['metadatas', 'documents', 'distances'],
            )
            ids, documents = result['ids'][0], (result['documents'] or [[]])[0]
            metadatas, distances = (result['metadatas'] or [[]])[0], (result['distances'] or [[]])[0]
            return [
                VectorHit(id_, doc, _strings(m), 1 - d)
                for id_, doc, m, d in zip(ids, documents, metadatas, distances, strict=True)
            ]

        return await self._run(brand_id, run)

    async def drop(self, brand_id: str) -> None:
        """刪除品牌的 collection；本來就沒有時不做任何事。"""

        async def drop(client: AsyncClientAPI) -> None:
            with contextlib.suppress(NotFoundError):
                await client.delete_collection(collection_name(brand_id))

        await self._call(drop)

    async def brands(self) -> list[str]:
        """有 collection 的品牌 id。"""

        async def names(client: AsyncClientAPI) -> list[str]:
            return [c.name for c in await client.list_collections()]

        return sorted(n.removesuffix(SUFFIX) for n in await self._call(names) if n.endswith(SUFFIX))

    async def aclose(self) -> None:
        """關閉與 Chroma 的 HTTP 連線（worker 結束時）；之後再呼叫會重新連線。"""
        async with self._connecting:
            client, self._client = self._client, None
        # chromadb 的 AsyncClientAPI 沒有公開的關閉方法：由它底下的 AsyncFastAPI 關掉持有的 httpx client
        cleanup = getattr(getattr(client, '_server', None), '_cleanup', None)
        if cleanup is not None:
            await cleanup()

    async def _run[T](self, brand_id: str, call: Callable[[AsyncCollection], Awaitable[T]]) -> T:
        """在品牌的 collection 上執行（沒有時建立）。不保留 collection 物件：collection 被刪除後舊的物件就不能用。"""

        async def run(client: AsyncClientAPI) -> T:
            collection = await client.get_or_create_collection(
                collection_name(brand_id), configuration={'hnsw': {'space': 'cosine'}}, embedding_function=None
            )
            return await call(collection)

        return await self._call(run)

    async def _call[T](self, call: Callable[[AsyncClientAPI], Awaitable[T]]) -> T:
        try:
            async with asyncio.timeout(TIMEOUT):
                return await call(await self._connect())
        except RagError:
            raise
        except TimeoutError as error:
            raise RagError(f'向量庫（Chroma）{TIMEOUT} 秒內沒有回應（{self.url}）') from error
        except httpx.TransportError as error:
            raise self._unreachable(error) from error
        except Exception as error:
            raise RagError(f'向量庫（Chroma）操作失敗：{error}') from error

    async def _connect(self) -> AsyncClientAPI:
        async with self._connecting:
            if self._client is None:
                url = httpx.URL(self.url)
                ssl = url.scheme == 'https'
                try:
                    self._client = await chromadb.AsyncHttpClient(
                        host=url.host, port=url.port or (443 if ssl else 80), ssl=ssl, database=self.database
                    )
                except (httpx.TransportError, ValueError) as error:
                    # 建立客戶端時會先連線確認 tenant 與 database；連不上時 chromadb 可能改丟 ValueError
                    raise self._unreachable(error) from error
            return self._client

    def _unreachable(self, error: Exception) -> RagError:
        return RagError(f'向量庫（Chroma）無法連線（{self.url}）：{error}')
