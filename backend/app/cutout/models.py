"""去背模型的清單、下載與核對。

模型取自 rembg 的 GitHub releases（BiRefNet，MIT 授權）；位元組數與 SHA-256 是 2026-10-15 實測時下載的檔案。
"""

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.cutout.processing import CutoutError

RELEASES = 'https://github.com/danielgatis/rembg/releases/download/v0.0.0'
#: 下載時每次讀取的位元組數
CHUNK = 1 << 20


@dataclass(frozen=True)
class ModelFile:
    name: str
    url: str
    size: int
    sha256: str

    @property
    def filename(self) -> str:
        return f'{self.name}.onnx'


MODELS: dict[str, ModelFile] = {
    'birefnet-general': ModelFile(
        'birefnet-general',
        f'{RELEASES}/BiRefNet-general-epoch_244.onnx',
        972666916,
        '58f621f00f5d756097615970a88a791584600dcf7c45b18a0a6267535a1ebd3c',
    ),
    'birefnet-general-lite': ModelFile(
        'birefnet-general-lite',
        f'{RELEASES}/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx',
        224005088,
        '5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333',
    ),
}


def _matches(path: Path, model: ModelFile) -> bool:
    if path.stat().st_size != model.size:
        return False
    digest = hashlib.sha256()
    with path.open('rb') as f:
        while block := f.read(CHUNK):
            digest.update(block)
    return digest.hexdigest() == model.sha256


def has_model(model: ModelFile, models_dir: Path) -> bool:
    """已有大小與 SHA-256 都正確的檔案。"""
    path = models_dir / model.filename
    return path.is_file() and _matches(path, model)


async def ensure_model(model: ModelFile, models_dir: Path, http: httpx.AsyncClient) -> Path:
    """回傳模型檔的路徑；沒有正確的檔案時先下載到 .part，核對大小與 SHA-256 後才改名。"""
    target = models_dir / model.filename
    if await asyncio.to_thread(has_model, model, models_dir):
        return target
    models_dir.mkdir(parents=True, exist_ok=True)
    part = models_dir / f'{model.filename}.part'
    mismatch = f'去背模型下載不完整（{model.name}）：檔案大小或 SHA-256 不符'
    digest = hashlib.sha256()
    size = 0
    try:
        async with http.stream('GET', model.url, follow_redirects=True) as res:
            res.raise_for_status()
            with part.open('wb') as f:
                async for chunk in res.aiter_bytes(CHUNK):
                    f.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                    # 已經比宣告的大：不必讀完（伺服器出錯時可能一直送，會寫滿磁碟）
                    if size > model.size:
                        raise CutoutError(mismatch)
        if size != model.size or digest.hexdigest() != model.sha256:
            raise CutoutError(mismatch)
        part.replace(target)
    except httpx.HTTPError as error:
        raise CutoutError(f'去背模型下載失敗：{error}') from error
    finally:
        part.unlink(missing_ok=True)
    return target
