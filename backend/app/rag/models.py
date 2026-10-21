"""RAG 模型的清單：bge-m3（向量化）與 bge-reranker-v2-m3（Rerank），都是 int8 ONNX，共用 bge-m3 的 tokenizer。

網址固定在 Hugging Face 的 commit；位元組數與 SHA-256 是 2026-10-21 實測時下載的檔案。換模型或換版本都要重建索引。
"""

from app.modelfiles import ModelFile

HF = 'https://huggingface.co'
BGE_M3 = f'{HF}/Xenova/bge-m3/resolve/4de13258303883538bd53b696b452bf8099f0858'
RERANKER_REPO = f'{HF}/onnx-community/bge-reranker-v2-m3-ONNX/resolve/6f5ff65298512715a1e669753bc754d2bc8f367b'

#: 輸出已正規化的 1024 維向量（sentence_embedding）；MIT 授權
EMBEDDER = ModelFile(
    'bge-m3',
    f'{BGE_M3}/onnx/sentence_transformers_int8.onnx',
    568599071,
    'e5b42096865cef734247dd8c7a44e35d305b70ba0c3736758065e1cad50f6453',
    filename='bge-m3-int8.onnx',
)
#: 兩個模型的 token id 完全相同，共用一個（省約 285 MB 記憶體）；MIT 授權
TOKENIZER = ModelFile(
    'bge-m3-tokenizer',
    f'{BGE_M3}/tokenizer.json',
    17082821,
    '6710678b12670bc442b99edc952c4d996ae309a7020c1fa0096dd245c2faf790',
    filename='bge-m3-tokenizer.json',
)
#: 輸出 logit，分數取 sigmoid；Apache-2.0（上游 BAAI/bge-reranker-v2-m3）
RERANKER = ModelFile(
    'bge-reranker-v2-m3',
    f'{RERANKER_REPO}/onnx/model_int8.onnx',
    570727094,
    '912fc1215c2dbff6499700534bd8d31253af01573861abbfc43afd1fab6cce5d',
    filename='bge-reranker-v2-m3-int8.onnx',
)

#: 下載的順序：先下載小的 tokenizer，連不上時很快就知道
MODELS = (TOKENIZER, EMBEDDER, RERANKER)
