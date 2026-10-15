"""去背的前處理與後處理（純函式）。

與實測時使用的 rembg 2.0.85 相同：縮成 1024×1024、除以像素最大值、以 ImageNet 的平均值與標準差正規化；
輸出經 sigmoid 與 min-max 正規化後縮回原尺寸。另外修正透明度：模型輸出的商品主體約為 98–99.6% 不透明，
接近不透明與接近透明的值直接設為 255 與 0，邊緣保留柔和的過渡。
"""

import io

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageOps, UnidentifiedImageError

INPUT_SIZE = 1024
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)
#: 遮罩值 ≥ 這個值視為完全不透明（95%）
OPAQUE_FROM = 242
#: 遮罩值 ≤ 這個值視為完全透明（5%）
CLEAR_UNTIL = 13


class CutoutError(Exception):
    """去背失敗；訊息為繁體中文，直接顯示在商品卡上。"""


def load_photo(data: bytes) -> Image.Image:
    """讀取照片，依 EXIF 轉正（手機照片常以 EXIF 記錄旋轉方向），轉成 RGB。"""
    try:
        with Image.open(io.BytesIO(data)) as img:
            upright = ImageOps.exif_transpose(img)
            return upright.convert('RGB')
    except Image.DecompressionBombError as error:
        raise CutoutError('照片尺寸過大，請縮小後再試') from error
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, TypeError) as error:
        raise CutoutError('照片無法讀取') from error


def to_input(photo: Image.Image) -> NDArray[np.float32]:
    """照片 → 模型輸入（1, 3, 1024, 1024）。"""
    resized = photo.resize((INPUT_SIZE, INPUT_SIZE), Image.Resampling.LANCZOS)
    pixels = np.asarray(resized, dtype=np.float64)
    pixels = pixels / max(float(pixels.max()), 1e-6)
    normalized = (pixels - np.array(MEAN)) / np.array(STD)
    batch: NDArray[np.float32] = normalized.transpose(2, 0, 1)[np.newaxis].astype(np.float32)
    return batch


def to_mask(output: NDArray[np.float32], size: tuple[int, int]) -> Image.Image:
    """模型輸出（1, 1, 1024, 1024）→ 原尺寸的透明度遮罩（L）。"""
    pred = 1 / (1 + np.exp(-output[0, 0].astype(np.float64)))
    low, high = float(pred.min()), float(pred.max())
    if high - low > 1e-6:
        pred = (pred - low) / (high - low)
    mask = Image.fromarray((pred * 255).astype(np.uint8), mode='L').resize(size, Image.Resampling.LANCZOS)
    return mask.point(lambda v: 255 if v >= OPAQUE_FROM else 0 if v <= CLEAR_UNTIL else v)


def compose(photo: Image.Image, mask: Image.Image) -> bytes:
    """照片的顏色加上遮罩當透明度 → PNG。"""
    cut = photo.convert('RGBA')
    cut.putalpha(mask)
    buf = io.BytesIO()
    cut.save(buf, 'PNG')
    return buf.getvalue()
