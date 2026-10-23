"""REVIEW_MODE=composer：composer 繪製審查用海報（存到 data/jobs/，經 /files 讀取）、量主色、規則審查，
worker 送出的圖檔（去背圖或原圖、Logo、url 背景，大圖先縮小），以及 composer 失敗時任務失敗。

使用測試啟動的 composer（3902 埠，需要 npm run fonts 下載的字型）。
"""

import io
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from redis.asyncio import Redis

from app.adapters.composer import ComposerClient, PosterImages, ProductImage, RenderedPoster
from app.brands import load_brands
from app.contract import (
    Brand,
    BrandLogo,
    FilePhoto,
    JobAcceptedEvent,
    JobInput,
    JobStatusEvent,
    Product,
    ProductCutout,
    Render,
    UrlBackground,
)
from app.db.session import Database
from app.errors import AppError
from app.events import EventStore
from app.pipeline.review import MAX_IMAGE_SIDE, ComposerPosters, ComposerReviewer, fit_image
from app.pipeline.runner import run_job
from app.pipeline.sim import sim_ports
from app.repo import catalog, jobs
from app.settings import Settings
from tests.conftest import LiveApi
from tests.fixtures import BRANDS_DIR, load_fixture

NOW = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)
TIMELINE = load_fixture('timelines/selune-retry.json')
JOB_ID: str = TIMELINE['jobId']
RENDERS = {
    r['id']: Render.model_validate(r)
    for item in TIMELINE['events']
    if item['event']['type'] == 'render.completed'
    for r in item['event']['renders']
}
#: 第 1 輪刻意失誤（applyFlaws：主色換成別的顏色、禁用詞…）；第 2 輪修正後的版本
FLAWED = RENDERS[f'{JOB_ID}_r1_ig-post_v0']
CLEAN = RENDERS[f'{JOB_ID}_r2_ig-post_v0']
CATALOG = load_fixture('brands.json')
SELUNE = Brand.model_validate(next(b for b in CATALOG['brands'] if b['id'] == 'selune'))
SERUM = Product.model_validate(next(p for p in CATALOG['products'] if p['id'] == 'prod_selune_serum'))


class RecordingComposer(ComposerClient):
    """照常呼叫 composer，同時記下 worker 送出的圖檔。"""

    def __init__(self, base_url: str) -> None:
        super().__init__(base_url)
        self.sent: list[PosterImages] = []

    async def render(
        self, render: Render, product: Product | None, brand: Brand, images: PosterImages
    ) -> RenderedPoster:
        self.sent.append(images)
        return await super().render(render, product, brand, images)


@pytest.fixture
async def composer(composer_url: str) -> AsyncIterator[RecordingComposer]:
    client = RecordingComposer(composer_url)
    yield client
    await client.aclose()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None, data_dir=tmp_path / 'data', local_photos_dir=tmp_path / 'local', brands_dir=tmp_path / 'brands'
    )


def image_bytes(size: tuple[int, int], mode: str = 'RGB', fmt: str = 'JPEG', **save: Any) -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, (90, 140, 200, 255)[: len(mode)]).save(out, fmt, **save)
    return out.getvalue()


def save_file(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def opened(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


async def test_the_review_poster_is_written_under_the_job_and_served_through_files(
    api: LiveApi, composer: RecordingComposer
) -> None:
    settings = api.services.settings
    poster = await ComposerPosters(composer, settings).compose(JOB_ID, CLEAN, SERUM, SELUNE)
    assert poster.url == f'/files/jobs/{JOB_ID}/{CLEAN.id}.png'
    path = settings.data_dir / 'jobs' / JOB_ID / f'{CLEAN.id}.png'
    with Image.open(path) as img:
        assert (img.format, img.size) == ('PNG', (CLEAN.spec.canvas.width, CLEAN.spec.canvas.height))
    res = await api.http.get(poster.url)
    assert (res.status_code, res.headers['content-type']) == (200, 'image/png')
    assert res.content == path.read_bytes()
    # 示範商品由 composer 依 productImage 自己產生 SVG；品牌沒有 Logo 圖檔
    assert composer.sent == [PosterImages()]


async def test_a_clean_spec_measures_the_brand_primary_and_passes_color_delta(
    composer: RecordingComposer, settings: Settings
) -> None:
    posters, reviewer = ComposerPosters(composer, settings), ComposerReviewer(composer)
    clean = await posters.compose(JOB_ID, CLEAN, SERUM, SELUNE)
    assert clean.measured_primary == SELUNE.palette.primary.lower()
    result = await reviewer.review(SELUNE, CLEAN, 1, clean)
    assert len(result.checks) == 10
    assert next(c for c in result.checks if c.id == 'color_delta').status == 'pass'
    assert result.passed
    # 分數不加隨機抖動：seed 不同，結果相同
    assert await reviewer.review(SELUNE, CLEAN, 2, clean) == result

    flawed = await posters.compose(JOB_ID, FLAWED, SERUM, SELUNE)
    assert flawed.measured_primary is not None
    color = next(c for c in (await reviewer.review(SELUNE, FLAWED, 1, flawed)).checks if c.id == 'color_delta')
    # 說明文字顯示實際用錯的顏色
    assert color.status == 'fail'
    assert f'偵測主色 {flawed.measured_primary.upper()}' in color.value


async def test_uploaded_products_send_the_cutout_or_the_photo_and_large_photos_are_downscaled(
    composer: RecordingComposer, settings: Settings
) -> None:
    posters = ComposerPosters(composer, settings)
    big = save_file(settings.data_dir / 'uploads' / 'big.jpg', image_bytes((3000, 2000)))
    cut = save_file(settings.data_dir / 'products' / 'prod_up' / 'cutout-1.png', image_bytes((400, 600), 'RGBA', 'PNG'))
    photo = FilePhoto(source='upload', url='/files/uploads/big.jpg')
    done = ProductCutout(model='sim', status='done', url='/files/products/prod_up/cutout-1.png', error=None)
    pending = ProductCutout(model='sim', status='pending', url=None, error=None)

    for cutout in (None, pending, done):
        product = SERUM.model_copy(update={'id': 'prod_up', 'photo': photo, 'cutout': cutout})
        poster = await posters.compose(JOB_ID, CLEAN, product, SELUNE)
        # 商品框不在主色的量測範圍內，換了商品圖仍量得到主色
        assert poster.measured_primary == SELUNE.palette.primary.lower()

    sent = [images.product for images in composer.sent]
    assert all(p is not None for p in sent)
    original, while_pending, cutout_image = (p for p in sent if p is not None)
    # 沒有去背、去背中：原圖以色彩增值合成；20 MB 的照片 base64 後會超過 composer 的上限，先把長邊縮到 2048
    for p in (original, while_pending):
        assert p.blend == 'multiply'
        sent_photo = opened(p.data)
        assert (sent_photo.format, sent_photo.size) == ('JPEG', (MAX_IMAGE_SIDE, round(2000 * MAX_IMAGE_SIDE / 3000)))
    assert opened(big.read_bytes()).size == (3000, 2000)
    # 去背完成：透明 PNG，尺寸夠小時原樣傳送
    assert cutout_image == ProductImage(cut.read_bytes(), 'normal')


async def test_the_logo_and_a_url_background_are_read_for_the_composer(
    composer: RecordingComposer, settings: Settings
) -> None:
    posters = ComposerPosters(composer, settings)
    logo = save_file(settings.brands_dir / 'assets' / 'logo.png', image_bytes((300, 100), 'RGBA', 'PNG'))
    background = save_file(settings.data_dir / 'uploads' / 'bg.jpg', image_bytes((1080, 1080)))
    brand = SELUNE.model_copy(update={'logo': BrandLogo(url='/files/brands/assets/logo.png')})
    render = CLEAN.model_copy(
        update={'background': UrlBackground(kind='url', url='/files/uploads/bg.jpg', includes_product=False)}
    )
    await posters.compose(JOB_ID, render, SERUM, brand)
    assert composer.sent[-1] == PosterImages(logo=logo.read_bytes(), background=background.read_bytes())

    # 與瀏覽器相同：Logo 圖檔不見時改畫向量標誌，海報照樣畫得出來
    logo.unlink()
    await posters.compose(JOB_ID, render, SERUM, brand)
    assert composer.sent[-1].logo is None


async def test_unusable_product_images_fail_with_a_chinese_reason(
    composer: RecordingComposer, settings: Settings
) -> None:
    posters = ComposerPosters(composer, settings)

    def uploaded(name: str) -> Product:
        return SERUM.model_copy(update={'photo': FilePhoto(source='upload', url=f'/files/uploads/{name}')})

    # worker 讀不到或 Pillow 無法解碼：不呼叫 composer
    with pytest.raises(AppError, match=r'^無法繪製審查用海報：找不到商品圖（/files/uploads/gone\.png）$'):
        await posters.compose(JOB_ID, CLEAN, uploaded('gone.png'), SELUNE)
    save_file(settings.data_dir / 'uploads' / 'broken.png', b'not an image')
    with pytest.raises(AppError, match=r'^無法繪製審查用海報：商品圖無法讀取（/files/uploads/broken\.png）：'):
        await posters.compose(JOB_ID, CLEAN, uploaded('broken.png'), SELUNE)
    assert composer.sent == []
    # Pillow 讀得懂、composer 解不開的格式（TIFF）：composer 回 400，原因帶著 composer 的訊息
    save_file(settings.data_dir / 'uploads' / 'scan.png', image_bytes((64, 64), fmt='TIFF'))
    with pytest.raises(AppError, match=r'^排版服務（composer）無法繪製海報：composer /render 失敗：商品圖無法解碼'):
        await posters.compose(JOB_ID, CLEAN, uploaded('scan.png'), SELUNE)
    assert not (settings.data_dir / 'jobs').exists()


def test_fit_image_keeps_small_files_and_downscales_or_rotates_the_rest(tmp_path: Path) -> None:
    small = save_file(tmp_path / 'small.png', image_bytes((800, 600), 'RGBA', 'PNG'))
    assert fit_image(small) == small.read_bytes()
    svg = save_file(tmp_path / 'logo.svg', b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
    assert fit_image(svg) == svg.read_bytes()

    # 透明的大圖縮小後仍是 PNG（保留透明度）；不透明的照片改存 JPEG
    wide = opened(fit_image(save_file(tmp_path / 'wide.png', image_bytes((4096, 1024), 'RGBA', 'PNG'))))
    assert (wide.format, wide.mode, wide.size) == ('PNG', 'RGBA', (2048, 512))
    tall = opened(fit_image(save_file(tmp_path / 'tall.webp', image_bytes((1000, 5000), fmt='WEBP'))))
    assert (tall.format, tall.size) == ('JPEG', (410, 2048))

    # 手機照片的 EXIF 方向（6：順時針轉 90 度）：尺寸不大也要轉正，瀏覽器顯示的就是轉正後的樣子
    exif = Image.Exif()
    exif[0x0112] = 6
    rotated = opened(fit_image(save_file(tmp_path / 'phone.jpg', image_bytes((600, 400), exif=exif))))
    assert rotated.size == (400, 600)
    assert rotated.getexif().get(0x0112, 1) == 1


async def queue_selune_job(db: Database, redis: Redis) -> EventStore:
    async with db.session() as s:
        await catalog.sync_brands(s, load_brands(BRANDS_DIR)[0], NOW)
        await jobs.create_job(s, JOB_ID, JobInput.model_validate(TIMELINE['input']), NOW)
    store = EventStore(db, redis)
    await store.append(JOB_ID, JobAcceptedEvent(type='job.accepted', job_id=JOB_ID))
    await store.append(JOB_ID, JobStatusEvent(type='job.status', stage='queued', round=0))
    return store


async def job_events(db: Database) -> list[dict[str, Any]]:
    async with db.session() as s:
        snap = await jobs.get_job(s, JOB_ID)
    assert snap is not None
    return snap.events


async def test_a_composer_job_fails_the_first_round_on_colour_and_passes_after_rewriting(
    db: Database, redis: Redis, composer_url: str, settings: Settings
) -> None:
    store = await queue_selune_job(db, redis)
    composer = ComposerClient(composer_url)
    try:
        ports = replace(
            sim_ports(composer, first_round_fail=True, force_all_fail=False),
            posters=ComposerPosters(composer, settings),
            reviewer=ComposerReviewer(composer),
        )
        await run_job(JOB_ID, db, store, ports, speed=0)
    finally:
        await composer.aclose()
    events = await job_events(db)
    assert events[-1] == {**events[-1], 'type': 'job.status', 'stage': 'done', 'round': 2}
    completed = [m for m in events if m['type'] == 'review.completed']
    assert [(m['round'], m['passed']) for m in completed] == [(1, False)] * 4 + [(2, True)] * 4
    for m in completed:
        assert m['image'] == f'/files/jobs/{JOB_ID}/{m["renderId"]}.png'
        assert (settings.data_dir / 'jobs' / JOB_ID / f'{m["renderId"]}.png').is_file()
    checks = [m for m in events if m['type'] == 'review.check']
    colour = [(m['round'], m['check']['status']) for m in checks if m['check']['id'] == 'color_delta']
    assert colour == [(1, 'fail')] * 4 + [(2, 'pass')] * 4
    logs = [m['message'] for m in events if m['type'] == 'log' and m['source'] == 'compose']
    assert logs.count('✓ 伺服器端排版 4 張') == 2
    await db.truncate_all()


async def test_the_job_fails_with_a_chinese_reason_when_the_composer_cannot_draw(
    db: Database, redis: Redis, composer_url: str, settings: Settings
) -> None:
    store = await queue_selune_job(db, redis)
    composer, unreachable = ComposerClient(composer_url), ComposerClient('http://127.0.0.1:9')
    try:
        ports = replace(
            sim_ports(composer, first_round_fail=True, force_all_fail=False),
            posters=ComposerPosters(unreachable, settings),
            reviewer=ComposerReviewer(composer),
        )
        await run_job(JOB_ID, db, store, ports, speed=0)
    finally:
        await composer.aclose()
        await unreachable.aclose()
    events = await job_events(db)
    (failed,) = [m for m in events if m['type'] == 'job.failed']
    assert failed['reason'].startswith('排版服務（composer）無法繪製海報：composer 沒有回應（http://127.0.0.1:9）：')
    stages = [m['stage'] for m in events if m['type'] == 'job.status']
    assert stages[-2:] == ['composing', 'failed']
    assert not any(m['type'] == 'review.check' for m in events)
    await db.truncate_all()
