"""測試用的 Encoder：不需要模型檔，結果固定。"""

import math
from collections.abc import Sequence
from pathlib import Path

from redis.asyncio import Redis

from app.rag.chunking import EMBED_DIMS
from app.rag.engine import RagEngine


class FakeEncoder:
    """依字元產生 1024 維的向量（每個字元的 code point 落在一維），正規化後內積即 cosine：
    共用字元越多的文字越相似。Rerank 的分數也是 cosine。記錄每次呼叫。"""

    def __init__(self) -> None:
        self.embedded: list[str] = []
        self.reranked: list[tuple[str, list[str]]] = []

    @staticmethod
    def vector(text: str) -> list[float]:
        counts = [0.0] * EMBED_DIMS
        for ch in text:
            counts[ord(ch) % EMBED_DIMS] += 1
        norm = math.sqrt(sum(c * c for c in counts))
        if norm == 0:
            # 空字串：固定的單位向量（零向量沒有 cosine）
            return [1.0] + [0.0] * (EMBED_DIMS - 1)
        return [c / norm for c in counts]

    def embed(self, text: str) -> list[float]:
        self.embedded.append(text)
        return self.vector(text)

    def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        self.reranked.append((query, list(passages)))
        q = self.vector(query)
        return [sum(a * b for a, b in zip(q, self.vector(p), strict=True)) for p in passages]


def fake_engine(redis: Redis, encoder: FakeEncoder) -> RagEngine:
    """沒有模型檔要下載、載入時換成 encoder 的 RagEngine（狀態照樣寫到 Redis）。"""
    return RagEngine('bge', Path('models'), redis, models=[], load=lambda _: encoder)
