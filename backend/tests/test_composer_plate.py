"""composer 的 /plate：ComfyUI 生成背景用的商品底圖與遮罩（Plan 7 規格 §4.3）。

使用測試啟動的 composer（3902 埠，需要 Node）；不需要資料庫。
"""

import io
from collections.abc import AsyncIterator

import pytest
from PIL import Image

from app.adapters.composer import ComposerClient, PlateResult, PosterImages, ProductImage
from app.contract import Brand, FilePhoto, Product, Render
from tests.fixtures import load_fixture

TIMELINE = load_fixture('timelines/selune-retry.json')
CLEAN = next(
    Render.model_validate(r)
    for item in TIMELINE['events']
    if item['event']['type'] == 'render.completed'
    for r in item['event']['renders']
    if r['round'] == 2 and r['templateId'] == 'ig-post'
)
CATALOG = load_fixture('brands.json')
SELUNE = Brand.model_validate(next(b for b in CATALOG['brands'] if b['id'] == 'selune'))
SERUM = Product.model_validate(next(p for p in CATALOG['products'] if p['id'] == 'prod_selune_serum'))


@pytest.fixture
async def composer(composer_url: str) -> AsyncIterator[ComposerClient]:
    client = ComposerClient(composer_url)
    yield client
    await client.aclose()


def opened(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def png(size: tuple[int, int], color: tuple[int, int, int]) -> bytes:
    out = io.BytesIO()
    Image.new('RGB', size, color).save(out, 'PNG')
    return out.getvalue()


async def test_the_plate_and_mask_match_the_generation_size_and_keep_the_product(composer: ComposerClient) -> None:
    plate = await composer.plate(CLEAN.spec, SERUM, SELUNE, PosterImages())
    assert isinstance(plate, PlateResult)
    # IG 貼文（4:5）的 SDXL 生成尺寸
    assert (plate.width, plate.height) == (896, 1152)
    assert opened(plate.plate).size == opened(plate.mask).size == (896, 1152)
    assert plate.warning is None
    assert plate.product_rect is not None
    r = plate.product_rect
    mask = opened(plate.mask).convert('L')
    assert mask.getpixel((1, 1)) == 255
    assert mask.getpixel((round(r.x + r.w / 2), round(r.y + r.h / 2))) == 0
    # 放大 scale 倍、裁掉 crop 之後是模板尺寸
    assert plate.width * plate.scale >= CLEAN.spec.canvas.width - 1e-6
    assert plate.height * plate.scale >= CLEAN.spec.canvas.height - 1e-6
    assert min(plate.crop_x, plate.crop_y) == pytest.approx(0, abs=1e-6)


async def test_a_photo_that_is_not_cut_out_yet_warns(composer: ComposerClient) -> None:
    upload = SERUM.model_copy(update={'photo': FilePhoto(source='upload', url='/files/uploads/serum.jpg')})
    plate = await composer.plate(
        CLEAN.spec, upload, SELUNE, PosterImages(product=ProductImage(png((300, 400), (0, 255, 0)), 'multiply'))
    )
    assert plate.warning == '商品尚未去背，背景依外框生成'


async def test_a_deleted_product_has_no_rect_and_an_all_white_mask(composer: ComposerClient) -> None:
    plate = await composer.plate(CLEAN.spec, None, SELUNE, PosterImages())
    assert plate.product_rect is None
    assert opened(plate.mask).convert('L').getextrema() == (255, 255)
