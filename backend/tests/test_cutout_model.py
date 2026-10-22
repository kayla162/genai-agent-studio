"""真正的 BiRefNet：只在本機已有模型檔（models/）且以 CUTOUT_TEST_PHOTO 指定商品照時執行，否則略過。

照片的商品要在畫面中央、四個角是背景，例如：
    CUTOUT_TEST_PHOTO=../data/uploads/xxx.jpg uv run pytest -m model
"""

import io
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.cutout.models import MODELS
from app.cutout.segmenter import OnnxSegmenter
from app.settings import Settings

#: 不讀 .env（測試一律如此）；要測另一個模型時以環境變數指定，例如 CUTOUT_MODEL=birefnet-general-lite
SETTINGS = Settings(_env_file=None)
MODEL = MODELS.get(SETTINGS.cutout_model, MODELS['birefnet-general'])
PATH = SETTINGS.models_dir / MODEL.filename
PHOTO = os.environ.get('CUTOUT_TEST_PHOTO')

pytestmark = [
    pytest.mark.model,
    pytest.mark.skipif(not PATH.is_file() or not PHOTO, reason='需要 models/ 的模型檔與 CUTOUT_TEST_PHOTO'),
]


def test_real_model_keeps_the_product_and_clears_the_corners() -> None:
    assert PHOTO is not None
    cut = OnnxSegmenter(MODEL.name, PATH).cut(Path(PHOTO).read_bytes())
    alpha = np.asarray(Image.open(io.BytesIO(cut)))[:, :, 3]
    h, w = alpha.shape
    assert [alpha[2, 2], alpha[2, w - 3], alpha[h - 3, 2], alpha[h - 3, w - 3]] == [0, 0, 0, 0]
    assert alpha[h // 2, w // 2] == 255
