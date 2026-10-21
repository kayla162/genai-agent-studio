"""去背模型的清單與下載（下載與核對由 app.modelfiles 處理）。

模型取自 rembg 的 GitHub releases（BiRefNet，MIT 授權）；位元組數與 SHA-256 是 2026-10-15 實測時下載的檔案。
"""

from pathlib import Path

import httpx

from app import modelfiles
from app.cutout.processing import CutoutError
from app.modelfiles import ModelFile, ModelFileError

RELEASES = 'https://github.com/danielgatis/rembg/releases/download/v0.0.0'

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


async def ensure_model(model: ModelFile, models_dir: Path, http: httpx.AsyncClient) -> Path:
    """回傳模型檔的路徑（必要時下載）；下載失敗或檔案不符時丟出 CutoutError。"""
    try:
        return await modelfiles.ensure_model(model, models_dir, http)
    except ModelFileError as error:
        raise CutoutError(f'去背模型{error}') from error
