"""真實版的排版與審查（REVIEW_MODE=composer）：

- ComposerPosters：worker 以 resolve_file 讀商品圖與 Logo，composer 在伺服器端繪製審查用海報（與瀏覽器相同的
  scene.ts 與 paint.ts）並從像素量出品牌主色，worker 把 PNG 存到 data/jobs/{jobId}/{renderId}.png。
- ComposerReviewer：以量到的主色呼叫 composer 的 /review（7 項規則加 3 項依內容判斷的 VLM 檢查，分數不加抖動）。

composer 沒有回應或回傳錯誤時任務失敗，原因為中文。
"""

import asyncio
import io
import logging
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app.adapters.composer import ComposerClient, ComposerError, PosterImages, ProductImage
from app.contract import Brand, FilePhoto, Product, Render, UrlBackground
from app.errors import AppError
from app.files import poster_file, resolve_url
from app.pipeline.ports import ComposedPoster, ReviewResult, RunContext
from app.settings import Settings

logger = logging.getLogger(__name__)

#: 傳給 composer 的商品圖與 Logo 的長邊上限（像素）：上傳的照片最大 20 MB，base64 後約 26.7 MB，
#: 加上其他欄位可能超過 composer 的請求上限（30 MB）；海報上的商品圖也用不到更大的尺寸
MAX_IMAGE_SIDE = 2048
#: EXIF 的拍攝方向（1 為正向）
EXIF_ORIENTATION = 0x0112

#: 任務失敗的原因開頭：composer 沒有回應或回傳錯誤，以及 worker 讀不到海報要用的圖檔
COMPOSE_FAILED = '排版服務（composer）無法繪製海報：'
REVIEW_FAILED = '排版服務（composer）無法審查海報：'
MISSING_IMAGE = '無法繪製審查用海報：'
#: 審查一定要有排版階段繪製的審查用海報
POSTER_REQUIRED = '審查需要伺服器端繪製的審查用海報（REVIEW_MODE=composer 時由 ComposerPosters 繪製）'


def fit_image(path: Path) -> bytes:
    """讀取商品圖或 Logo，準備傳給 composer。

    長邊超過 MAX_IMAGE_SIDE，或 EXIF 記錄了旋轉方向（手機照片）時，以 Pillow 轉正、縮小後重新編碼：
    有透明度用 PNG，否則用 JPEG。其他情況原樣傳送，與瀏覽器載入的檔案相同。SVG 不經過 Pillow。
    讀不到或無法解碼時丟出 OSError 或 Pillow 的例外，由呼叫端決定如何處理。
    """
    data = path.read_bytes()
    if path.suffix.lower() == '.svg':
        return data
    with Image.open(io.BytesIO(data)) as img:
        rotated = img.getexif().get(EXIF_ORIENTATION, 1) != 1
        if max(img.size) <= MAX_IMAGE_SIDE and not rotated:
            return data
        fitted = ImageOps.exif_transpose(img)
    fitted.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    if fitted.mode in ('RGBA', 'LA', 'PA') or 'transparency' in fitted.info:
        fitted.convert('RGBA').save(out, 'PNG')
    else:
        fitted.convert('RGB').save(out, 'JPEG', quality=90)
    return out.getvalue()


#: 圖檔讀取或解碼失敗時 Pillow 與檔案系統可能丟出的例外
IMAGE_ERRORS = (OSError, UnidentifiedImageError, Image.DecompressionBombError, ValueError, SyntaxError)


class ComposerPosters:
    """真實版的排版：composer 繪製審查用海報並量主色，worker 存檔。"""

    def __init__(self, composer: ComposerClient, settings: Settings) -> None:
        self.composer = composer
        self.settings = settings

    async def compose(self, job_id: str, render: Render, product: Product, brand: Brand) -> ComposedPoster:
        target, url = poster_file(self.settings, job_id, render.id)
        images = await asyncio.to_thread(self._images, render, product, brand)
        try:
            poster = await self.composer.render(render, product, brand, images)
        except ComposerError as error:
            raise AppError(f'{COMPOSE_FAILED}{error}') from error
        await asyncio.to_thread(_write, target, poster.png)
        return ComposedPoster(url=url, measured_primary=poster.measured_primary)

    def _images(self, render: Render, product: Product, brand: Brand) -> PosterImages:
        """在執行緒裡讀圖與縮圖（大張照片解碼約需數百毫秒）。"""
        return PosterImages(
            product=self._product(product),
            logo=self._logo(brand),
            background=self._required(render.background.url, '背景圖')
            if isinstance(render.background, UrlBackground)
            else None,
        )

    def _product(self, product: Product) -> ProductImage | None:
        """與前端 productImage 相同：去背完成用去背圖（normal），否則用原圖並以色彩增值（multiply）合成。
        示範商品由 composer 依 productImage 產生 SVG。"""
        if not isinstance(product.photo, FilePhoto):
            return None
        cut = product.cutout
        if cut is not None and cut.status == 'done' and cut.url:
            return ProductImage(self._required(cut.url, '商品去背圖'), 'normal')
        return ProductImage(self._required(product.photo.url, '商品圖'), 'multiply')

    def _logo(self, brand: Brand) -> bytes | None:
        """與前端相同：Logo 圖檔找不到或無法讀取時改畫向量標誌與字標。"""
        if brand.logo is None:
            return None
        path = resolve_url(self.settings, brand.logo.url)
        if path is None:
            logger.warning('找不到品牌 Logo 圖檔，審查用海報改畫向量標誌：%s', brand.logo.url)
            return None
        try:
            return fit_image(path)
        except IMAGE_ERRORS:
            logger.warning('品牌 Logo 圖檔無法讀取，審查用海報改畫向量標誌：%s', brand.logo.url, exc_info=True)
            return None

    def _required(self, url: str, label: str) -> bytes:
        """審查用海報是紀錄，不像瀏覽器預覽那樣略過讀不到的圖：找不到或無法讀取時任務失敗。"""
        path = resolve_url(self.settings, url)
        if path is None:
            raise AppError(f'{MISSING_IMAGE}找不到{label}（{url}）')
        try:
            return fit_image(path)
        except IMAGE_ERRORS as error:
            raise AppError(f'{MISSING_IMAGE}{label}無法讀取（{url}）：{error}') from error


def _write(target: Path, png: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(png)


class ComposerReviewer:
    """真實版的審查：以審查用海報量到的主色呼叫 /review，分數不加隨機抖動（seed 不使用）。"""

    def __init__(self, composer: ComposerClient) -> None:
        self.composer = composer

    async def review(
        self, brand: Brand, render: Render, seed: int, poster: ComposedPoster | None, run: RunContext
    ) -> ReviewResult:
        if poster is None:
            raise AppError(POSTER_REQUIRED)
        try:
            return await self.composer.review(render.spec, brand, poster.measured_primary)
        except ComposerError as error:
            raise AppError(f'{REVIEW_FAILED}{error}') from error
