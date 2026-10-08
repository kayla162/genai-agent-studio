from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.brands import LoadedBrand, load_brands
from app.contract import FilePhoto, Price, ProductDraft, RagChunk
from app.repo import catalog
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
