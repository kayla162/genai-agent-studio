"""品牌、RAG 切塊與商品。"""

import secrets
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import case, delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.brands import LoadedBrand, is_alt
from app.contract import Brand, FilePhoto, Product, ProductCutout, ProductDraft, RagChunk
from app.core.clock import iso, parse_iso
from app.db.models import BrandChunkRow, BrandRow, ProductRow

#: 列出切塊的順序：設定檔、合規替代用語、上傳的手冊、回寫的歷史切塊
_ORIGIN_ORDER = case(
    {'config': 0, 'alt': 1, 'upload': 2, 'history': 3},
    value=BrandChunkRow.origin,
)


async def sync_brands(session: AsyncSession, loaded: Sequence[LoadedBrand], now: datetime) -> None:
    """品牌設定檔 → 資料庫。內容改變時取代設定檔的切塊；補上還沒有的示範商品（刪除過的不再加回）；
    設定檔已移除的品牌不再列出。"""
    rows = {row.id: row for row in (await session.scalars(select(BrandRow))).all()}
    for item in loaded:
        brand = item.brand
        row = rows.get(brand.id)
        if row is None:
            row = BrandRow(id=brand.id, source_hash='')
            session.add(row)
        row.active = True
        if row.source_hash == item.source_hash:
            continue
        config = brand.to_json()
        config['guidelineChunks'] = []
        row.name, row.config, row.source_hash, row.updated_at = brand.name, config, item.source_hash, now
        await session.flush()
        await session.execute(
            delete(BrandChunkRow).where(BrandChunkRow.brand_id == brand.id, BrandChunkRow.origin.in_(('config', 'alt')))
        )
        for i, c in enumerate(brand.guideline_chunks):
            origin = 'alt' if is_alt(c) else 'config'
            session.add(_chunk_row(brand.id, c, origin, i, now))
        for product in item.samples:
            if await session.get(ProductRow, product.id) is None:
                session.add(
                    ProductRow(
                        id=product.id,
                        brand_id=brand.id,
                        data=product.to_json(),
                        sample=True,
                        deleted=False,
                        created_at=parse_iso(product.created_at),
                    )
                )
    active = [b.brand.id for b in loaded]
    await session.execute(update(BrandRow).where(BrandRow.id.not_in(active)).values(active=False))
    await session.commit()


def _chunk_row(brand_id: str, chunk: RagChunk, origin: str, position: int, now: datetime) -> BrandChunkRow:
    return BrandChunkRow(
        id=chunk.id,
        brand_id=brand_id,
        source=chunk.source,
        section=chunk.section,
        tag=chunk.tag,
        text=chunk.text,
        origin=origin,
        position=position,
        created_at=now,
    )


async def list_chunks(session: AsyncSession, brand_id: str) -> list[tuple[RagChunk, str]]:
    """品牌的全部切塊與各自的 origin（config、alt、upload、history），依列出的順序。"""
    rows = await session.scalars(
        select(BrandChunkRow)
        .where(BrandChunkRow.brand_id == brand_id)
        .order_by(_ORIGIN_ORDER, BrandChunkRow.created_at, BrandChunkRow.position)
    )
    return [
        (
            RagChunk.model_validate(
                {'id': r.id, 'source': r.source, 'section': r.section, 'tag': r.tag, 'text': r.text}
            ),
            r.origin,
        )
        for r in rows
    ]


async def _brand(session: AsyncSession, row: BrandRow) -> Brand:
    chunks = [c.to_json() for c, _ in await list_chunks(session, row.id)]
    return Brand.model_validate({**row.config, 'guidelineChunks': chunks})


async def active_brand_ids(session: AsyncSession) -> list[str]:
    """設定檔仍在的品牌（RAG 同步的對象）。"""
    return list(await session.scalars(select(BrandRow.id).where(BrandRow.active).order_by(BrandRow.id)))


async def list_brands(session: AsyncSession) -> list[Brand]:
    rows = await session.scalars(select(BrandRow).where(BrandRow.active).order_by(BrandRow.id))
    return [await _brand(session, row) for row in rows.all()]


async def get_brand(session: AsyncSession, brand_id: str) -> Brand | None:
    row = await session.get(BrandRow, brand_id)
    return await _brand(session, row) if row and row.active else None


async def replace_document_chunks(
    session: AsyncSession, brand_id: str, source: str, chunks: Sequence[RagChunk], now: datetime
) -> None:
    """上傳的手冊：同名文件重新上傳時取代舊的切塊。"""
    await session.execute(
        delete(BrandChunkRow).where(
            BrandChunkRow.brand_id == brand_id, BrandChunkRow.origin == 'upload', BrandChunkRow.source == source
        )
    )
    for i, c in enumerate(chunks):
        session.add(_chunk_row(brand_id, c, 'upload', i, now))
    await session.commit()


async def delete_document_chunks(session: AsyncSession, brand_id: str, source: str) -> int:
    """刪除一份上傳的手冊（品牌設定檔的規範與歷史回寫不受影響），回傳刪除的切塊數。"""
    result = await session.execute(
        delete(BrandChunkRow).where(
            BrandChunkRow.brand_id == brand_id, BrandChunkRow.origin == 'upload', BrandChunkRow.source == source
        )
    )
    await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def upsert_chunk(session: AsyncSession, brand_id: str, chunk: RagChunk, origin: str, now: datetime) -> None:
    """以 id 新增或取代一個切塊（歷史回寫：重跑不會產生重複的切塊）。已經有時保留第一次寫入的時間，列出的順序不變。"""
    values = {
        'brand_id': brand_id,
        'source': chunk.source,
        'section': chunk.section,
        'tag': chunk.tag,
        'text': chunk.text,
        'origin': origin,
    }
    stmt = insert(BrandChunkRow).values(id=chunk.id, position=0, created_at=now, **values)
    await session.execute(stmt.on_conflict_do_update(index_elements=[BrandChunkRow.id], set_=values))
    await session.commit()


async def list_products(session: AsyncSession, brand_id: str) -> list[Product]:
    rows = await session.scalars(
        select(ProductRow)
        .where(ProductRow.brand_id == brand_id, ProductRow.deleted.is_(False))
        .order_by(ProductRow.sample.desc(), ProductRow.created_at, ProductRow.id)
    )
    return [Product.model_validate(r.data) for r in rows]


async def get_product(session: AsyncSession, product_id: str, *, for_update: bool = False) -> Product | None:
    """for_update：鎖定商品列直到交易結束（先讀再改的呼叫端用，避免與其他寫入交錯）。"""
    row = await session.get(ProductRow, product_id, with_for_update=for_update)
    return Product.model_validate(row.data) if row and not row.deleted else None


async def save_product(session: AsyncSession, draft: ProductDraft, now: datetime) -> Product:
    """沒有 id（或 id 不存在）時新增；有時更新內容並保留建立時間。"""
    row = await session.get(ProductRow, draft.id) if draft.id else None
    if row is None:
        row = ProductRow(
            id=draft.id or f'prod_{secrets.token_hex(5)}', brand_id=draft.brand_id, sample=False, created_at=now
        )
        session.add(row)
    product = Product(
        id=row.id,
        brand_id=draft.brand_id,
        name=draft.name,
        features=draft.features,
        price=draft.price,
        photo=draft.photo,
        cutout=draft.cutout,
        created_at=iso(row.created_at),
    )
    row.brand_id, row.data, row.deleted = draft.brand_id, product.to_json(), False
    await session.commit()
    return product


async def set_cutout(session: AsyncSession, product_id: str, photo_url: str, cutout: ProductCutout) -> Product | None:
    """鎖定商品列，確認商品仍在、照片沒換才寫入去背狀態；否則不寫入並回傳 None。"""
    row = await session.get(ProductRow, product_id, with_for_update=True)
    product = Product.model_validate(row.data) if row and not row.deleted else None
    if row is None or product is None or not isinstance(product.photo, FilePhoto) or product.photo.url != photo_url:
        await session.rollback()
        return None
    updated = product.model_copy(update={'cutout': cutout})
    row.data = updated.to_json()
    await session.commit()
    return updated


async def pending_cutouts(session: AsyncSession) -> list[Product]:
    """還在去背中的商品（worker 啟動時重新排入）。"""
    rows = await session.scalars(
        select(ProductRow).where(ProductRow.deleted.is_(False), ProductRow.data['cutout']['status'].astext == 'pending')
    )
    return [Product.model_validate(r.data) for r in rows]


async def delete_product(session: AsyncSession, product_id: str) -> bool:
    """示範商品只標記刪除；自建商品直接刪除。回傳是否有刪到。"""
    row = await session.get(ProductRow, product_id)
    if row is None or row.deleted:
        return False
    if row.sample:
        row.deleted = True
    else:
        await session.delete(row)
    await session.commit()
    return True
