"""VectorStore：連 127.0.0.1:8001 的 Chroma（database genai_test），每個測試結束後刪除建立的 collection。"""

import pytest

from app.rag.errors import RagError
from app.rag.store import VectorRecord, VectorStore, collection_name


def record(id_: str, embedding: list[float], origin: str = 'config', tag: str = 'color') -> VectorRecord:
    return VectorRecord(id_, embedding, f'{id_} 的內文', {'origin': origin, 'tag': tag, 'textHash': id_[-1]})


async def test_query_returns_cosine_scores_in_order_and_applies_where(chroma: VectorStore) -> None:
    await chroma.upsert(
        'acme',
        [
            record('acme#a', [1.0, 0.0, 0.0]),
            record('acme#b', [0.6, 0.8, 0.0]),
            record('acme#law', [0.0, 1.0, 0.0], tag='law'),
            record('acme#law-alt', [1.0, 0.1, 0.0], origin='alt', tag='law'),
        ],
    )
    hits = await chroma.query('acme', [1.0, 0.0, 0.0], 8, where={'origin': {'$ne': 'alt'}})
    assert [h.id for h in hits] == ['acme#a', 'acme#b', 'acme#law']
    assert [h.score for h in hits] == pytest.approx([1.0, 0.6, 0.0], abs=1e-5)
    assert hits[0].document == 'acme#a 的內文'
    assert hits[0].metadata == {'origin': 'config', 'tag': 'color', 'textHash': 'a'}

    rewrite = await chroma.query('acme', [1.0, 0.0, 0.0], 4, where={'$or': [{'origin': 'alt'}, {'tag': 'law'}]})
    assert [h.id for h in rewrite] == ['acme#law-alt', 'acme#law']
    assert [h.id for h in await chroma.query('acme', [0.0, 1.0, 0.0], 1)] == ['acme#law']


async def test_each_brand_has_its_own_collection(chroma: VectorStore) -> None:
    await chroma.upsert('acme', [record('acme#a', [1.0, 0.0])])
    await chroma.upsert('other-brand', [record('other-brand#a', [1.0, 0.0])])
    assert await chroma.brands() == ['acme', 'other-brand']
    assert [h.id for h in await chroma.query('other-brand', [1.0, 0.0], 8)] == ['other-brand#a']
    assert collection_name('other-brand') == 'other-brand_ci'


async def test_metadata_upsert_and_delete(chroma: VectorStore) -> None:
    assert await chroma.metadata('acme') == {}
    await chroma.upsert('acme', [record('acme#a', [1.0, 0.0]), record('acme#b', [0.0, 1.0], origin='upload')])
    await chroma.upsert('acme', [record('acme#a', [0.0, 1.0], tag='logo')])
    assert await chroma.metadata('acme') == {
        'acme#a': {'origin': 'config', 'tag': 'logo', 'textHash': 'a'},
        'acme#b': {'origin': 'upload', 'tag': 'color', 'textHash': 'b'},
    }
    await chroma.delete('acme', where={'origin': 'upload'})
    assert list(await chroma.metadata('acme')) == ['acme#a']
    # 空的清單、不存在的 id 都不做任何事
    await chroma.upsert('acme', [])
    await chroma.delete('acme', ids=[])
    await chroma.delete('acme', ids=['acme#missing'])
    await chroma.delete('acme', ids=['acme#a'])
    assert await chroma.metadata('acme') == {}
    assert await chroma.query('acme', [1.0, 0.0], 8) == []


async def test_drop_removes_the_collection_and_ignores_missing_ones(chroma: VectorStore) -> None:
    await chroma.upsert('acme', [record('acme#a', [1.0, 0.0])])
    await chroma.drop('acme')
    await chroma.drop('acme')
    assert await chroma.brands() == []


async def test_chroma_errors_become_chinese_rag_errors(chroma: VectorStore) -> None:
    await chroma.upsert('acme', [record('acme#a', [1.0, 0.0])])
    with pytest.raises(RagError, match='向量庫（Chroma）操作失敗'):
        await chroma.query('acme', [1.0, 0.0, 0.0], 1)
    with pytest.raises(RagError, match=r'向量庫（Chroma）無法連線（http://127\.0\.0\.1:9）'):
        await VectorStore('http://127.0.0.1:9').brands()
