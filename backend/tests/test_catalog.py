import json
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.brands import LoadedBrand, load_brands
from app.contract import FilePhoto, Price, ProductDraft, RagChunk
from app.db.models import BrandChunkRow, ProductRow
from app.db.session import Database
from app.repo import catalog
from app.settings import BACKEND_DIR
from tests.fixtures import BRANDS_DIR, load_fixture

T0 = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 7, 2, 0, tzinfo=UTC)


def demo_brands() -> list[LoadedBrand]:
    loaded, errors = load_brands(BRANDS_DIR)
    assert errors == []
    return loaded


def draft(name: str, product_id: str | None = None) -> ProductDraft:
    return ProductDraft(
        id=product_id,
        brand_id='selune',
        name=name,
        features=['保濕'],
        price=Price(sale=680, original=880),
        photo=FilePhoto(source='upload', url='/files/products/x.png'),
        cutout=None,
    )


async def test_syncs_brands_from_config_files(session: AsyncSession) -> None:
    await catalog.sync_brands(session, demo_brands(), T0)
    fixture = sorted(load_fixture('brands.json')['brands'], key=lambda b: b['id'])
    assert [b.to_json() for b in await catalog.list_brands(session)] == fixture
    assert (await catalog.get_brand(session, 'selune')) is not None
    assert (await catalog.get_brand(session, 'nope')) is None


async def test_case_study_chunks_are_config_chunks(session: AsyncSession) -> None:
    await catalog.sync_brands(session, demo_brands(), T0)
    rows = await session.scalars(select(BrandChunkRow).where(BrandChunkRow.brand_id == 'selune'))
    origins = {r.id: r.origin for r in rows}
    assert (origins['selune#history'], origins['selune#case-1'], origins['selune#case-2']) == ('config',) * 3
    assert origins['selune#law-alt'] == 'alt'


async def test_resyncing_replaces_config_chunks_and_hides_removed_brands(session: AsyncSession) -> None:
    loaded = demo_brands()
    await catalog.sync_brands(session, loaded, T0)
    selune = next(b for b in loaded if b.brand.id == 'selune')
    color = selune.brand.guideline_chunks[0].model_copy(update={'text': '主色改為 #A0566A。'})
    changed = LoadedBrand(
        brand=selune.brand.model_copy(update={'guideline_chunks': [color]}),
        samples=selune.samples,
        logo_path=None,
        style_images=[],
        source_hash='changed',
    )
    await catalog.sync_brands(session, [changed], T1)
    brands = await catalog.list_brands(session)
    assert [b.id for b in brands] == ['selune']
    assert [c.text for c in brands[0].guideline_chunks] == ['主色改為 #A0566A。']


async def test_upserting_an_existing_chunk_replaces_its_text_and_keeps_its_place(session: AsyncSession) -> None:
    """歷史回寫重跑（例如商品改名後補做）：以 id 取代內容，列出的位置維持第一次寫入的順序。"""
    await catalog.sync_brands(session, demo_brands(), T0)

    def history_chunk(id_: str, text: str) -> RagChunk:
        return RagChunk(id=id_, source='history/job_a', section='歷史回寫', tag='history', text=text)

    first, second = 'selune#hist-a', 'selune#hist-b'
    await catalog.upsert_chunk(session, 'selune', history_chunk(first, '舊的內文'), 'history', T0)
    await catalog.upsert_chunk(session, 'selune', history_chunk(second, 'B'), 'history', T1)
    await catalog.upsert_chunk(session, 'selune', history_chunk(first, '新的內文'), 'history', T1.replace(hour=3))
    history = [(c.id, c.text) for c, origin in await catalog.list_chunks(session, 'selune') if origin == 'history']
    assert history == [(first, '新的內文'), (second, 'B')]


async def test_uploaded_chunks_follow_the_config_chunks_and_replace_by_source(session: AsyncSession) -> None:
    await catalog.sync_brands(session, demo_brands(), T0)

    def chunk(n: int) -> RagChunk:
        return RagChunk(
            id=f'selune#doc-abc-{n}', source='ci_update.md', section='色彩更新', tag='color', text=f'第 {n} 塊'
        )

    await catalog.replace_document_chunks(session, 'selune', 'ci_update.md', [chunk(1), chunk(2)], T0)
    await catalog.replace_document_chunks(session, 'selune', 'ci_update.md', [chunk(3)], T1)
    brand = await catalog.get_brand(session, 'selune')
    assert brand is not None
    assert [c.id for c in brand.guideline_chunks][-2:] == ['selune#law-alt', 'selune#doc-abc-3']


async def test_get_product_can_lock_the_row_until_the_transaction_ends(db: Database, session: AsyncSession) -> None:
    await catalog.sync_brands(session, demo_brands(), T0)
    created = await catalog.save_product(session, draft('晚安面膜'), T0)
    assert await catalog.get_product(session, created.id, for_update=True) is not None
    async with db.session() as other:
        # 不鎖定的讀取不受影響；另一個交易想鎖同一列時（不等待）會被擋下
        assert await catalog.get_product(other, created.id) is not None
        with pytest.raises(DBAPIError):
            await other.execute(select(ProductRow.id).where(ProductRow.id == created.id).with_for_update(nowait=True))
    await session.rollback()


async def test_lists_samples_first_and_keeps_deleted_samples_out(session: AsyncSession) -> None:
    await catalog.sync_brands(session, demo_brands(), T0)
    assert [p.id for p in await catalog.list_products(session, 'selune')] == ['prod_selune_serum']

    created = await catalog.save_product(session, draft('晚安面膜'), T0)
    assert created.id.startswith('prod_')
    assert created.created_at == '2026-10-07T01:00:00.000Z'
    updated = await catalog.save_product(session, draft('晚安面膜 50ml', created.id), T1)
    assert (updated.name, updated.created_at) == ('晚安面膜 50ml', '2026-10-07T01:00:00.000Z')
    names = [p.name for p in await catalog.list_products(session, 'selune')]
    assert names == ['極光玻尿酸修護精華 30ml', '晚安面膜 50ml']

    assert await catalog.delete_product(session, 'prod_selune_serum')
    assert await catalog.delete_product(session, created.id)
    assert not await catalog.delete_product(session, created.id)
    await catalog.sync_brands(session, demo_brands(), T1)
    assert await catalog.list_products(session, 'selune') == []
    assert await catalog.get_product(session, 'prod_selune_serum') is None
    assert [p.id for p in await catalog.list_products(session, 'misty-isle')] == ['prod_misty_coldbrew']


async def alembic(db: Database, action: str, revision: str) -> None:
    """在測試資料庫上執行 alembic upgrade／downgrade。"""

    def run(connection: Connection) -> None:
        config = Config(str(BACKEND_DIR / 'alembic.ini'))
        config.attributes['connection'] = connection
        getattr(command, action)(config, revision)

    async with db.engine.begin() as connection:
        await connection.run_sync(run)


async def cutouts(session: AsyncSession) -> dict[str, object]:
    rows = await session.execute(text("SELECT id, data->'cutout' FROM products ORDER BY id"))
    return {product_id: cutout for product_id, cutout in rows.all()}


async def test_migration_0002_queues_photo_products_for_a_real_cutout(db: Database, session: AsyncSession) -> None:
    await catalog.sync_brands(session, demo_brands(), T0)
    await alembic(db, 'downgrade', '0001')
    try:
        # 0001 時代的商品：模擬去背過的上傳照、還沒去背的本機照片
        for product_id, source, cutout in [
            ('prod_old_upload', 'upload', {'model': 'BiRefNet-general', 'url': None}),
            ('prod_old_local', 'local', None),
        ]:
            data: dict[str, object] = {
                'id': product_id,
                'brandId': 'selune',
                'name': product_id,
                'features': [],
                'price': {'sale': 0, 'original': 0},
                'photo': {'source': source, 'url': f'/files/{product_id}.png'},
                'cutout': cutout,
                'createdAt': '2026-10-07T01:00:00.000Z',
            }
            await session.execute(
                text(
                    'INSERT INTO products (id, brand_id, data, sample, deleted, created_at) '
                    "VALUES (:id, 'selune', CAST(:data AS jsonb), false, false, :now)"
                ),
                {'id': product_id, 'data': json.dumps(data), 'now': T0},
            )
        await session.commit()
    finally:
        await alembic(db, 'upgrade', 'head')

    pending = {'model': 'BiRefNet-general', 'status': 'pending', 'url': None, 'error': None}
    assert await cutouts(session) == {
        'prod_misty_coldbrew': None,
        'prod_old_local': pending,
        'prod_old_upload': pending,
        'prod_selune_serum': None,
    }
    assert (await catalog.get_product(session, 'prod_old_upload')) is not None

    await alembic(db, 'downgrade', '0001')
    try:
        assert (await cutouts(session))['prod_old_upload'] == {'model': 'BiRefNet-general', 'url': None}
    finally:
        await alembic(db, 'upgrade', 'head')
