"""真正的 bge-m3 與 bge-reranker-v2-m3：只在本機已有三個模型檔（models/）時執行，否則略過。

uv run pytest -m model
"""

import numpy as np
import pytest

from app.rag.chunking import EMBED_DIMS
from app.rag.encoder import OnnxEncoder
from app.rag.models import MODELS
from app.settings import Settings

QUERY = 'SÉLUNE｜玻尿酸修護精華｜秋季保濕主打｜長效保濕'
#: 品牌色彩、保濕合規、咖啡產地（與查詢無關）、秋季主視覺
PASSAGES = [
    '海報主色須使用品牌紫，不可使用螢光色。',
    '保濕類商品不可宣稱『根治乾燥』，可改用『改善乾燥感』。',
    '咖啡豆產地標示需與包裝一致。',
    '秋季檔期主視覺以暖色調與柔和光線呈現。',
]
COFFEE = 2
#: 不讀 .env（測試一律如此）；模型資料夾可用環境變數 MODELS_DIR 指定
SETTINGS = Settings(_env_file=None)

pytestmark = [
    pytest.mark.model,
    pytest.mark.skipif(
        not all((SETTINGS.models_dir / m.filename).is_file() for m in MODELS), reason='需要 models/ 的 RAG 模型檔'
    ),
]


@pytest.fixture(scope='module')
def encoder() -> OnnxEncoder:
    return OnnxEncoder(SETTINGS.models_dir)


def test_embeddings_are_normalized_1024_dims_and_repeatable(encoder: OnnxEncoder) -> None:
    vector = encoder.embed(QUERY)
    assert len(vector) == EMBED_DIMS
    assert np.linalg.norm(vector) == pytest.approx(1, abs=1e-3)
    assert encoder.embed(QUERY) == vector


def test_the_unrelated_passage_ranks_last_in_both_models(encoder: OnnxEncoder) -> None:
    query = np.array(encoder.embed(QUERY))
    cosines = [float(query @ np.array(encoder.embed(p))) for p in PASSAGES]
    scores = encoder.rerank(QUERY, PASSAGES)
    assert all(0 < s < 1 for s in scores)
    assert min(range(len(PASSAGES)), key=cosines.__getitem__) == COFFEE, cosines
    assert min(range(len(PASSAGES)), key=scores.__getitem__) == COFFEE, scores
