"""向量化與 Rerank：同步執行、佔用 CPU；worker 在 RAG 專用的單一執行緒裡呼叫（RagEngine）。"""

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt
import onnxruntime as ort
from tokenizers import Encoding, Tokenizer

from app.rag.models import EMBEDDER, RERANKER, TOKENIZER

#: 輸入的 token 上限（切塊約 180 字，查詢與切塊合計也遠低於這個數字）
MAX_TOKENS = 512


class Encoder(Protocol):
    def embed(self, text: str) -> list[float]:
        """已正規化的向量（cosine 相似度即內積）。"""
        ...

    def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        """每一段與查詢的相關分數（0–1），順序與 passages 相同。"""
        ...


def _session(path: Path) -> ort.InferenceSession:
    # 關閉記憶體池：兩個模型都載入後峰值約 1.93 GB（開啟時約 2.65 GB）
    options = ort.SessionOptions()
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    return ort.InferenceSession(str(path), sess_options=options, providers=['CPUExecutionProvider'])


def _feed(encoding: Encoding) -> dict[str, npt.NDArray[np.int64]]:
    return {
        'input_ids': np.array([encoding.ids], dtype=np.int64),
        'attention_mask': np.array([encoding.attention_mask], dtype=np.int64),
    }


def _sigmoid(x: float) -> float:
    # 分兩邊計算，logit 很大或很小時都不會溢位
    if x >= 0:
        return 1 / (1 + math.exp(-x))
    z = math.exp(x)
    return z / (1 + z)


class OnnxEncoder:
    """bge-m3 與 bge-reranker-v2-m3（int8 ONNX），共用一個 tokenizer。

    一律逐筆計算（批次大小 1）：int8 動態量化的縮放值以整個批次計算，
    同一段文字放進批次裡算，向量的餘弦相似度最低只有 0.971；逐筆計算時結果固定，也快 10–14%，而且不需要補 <pad>。
    """

    def __init__(self, models_dir: Path) -> None:
        self.tokenizer = Tokenizer.from_file(str(models_dir / TOKENIZER.filename))
        # tokenizer.json 沒有設定截斷。預設的 longest_first 在查詢本身就超過上限時也能截斷（only_second 會出錯）
        self.tokenizer.enable_truncation(max_length=MAX_TOKENS)
        self.embedder = _session(models_dir / EMBEDDER.filename)
        self.reranker = _session(models_dir / RERANKER.filename)

    def embed(self, text: str) -> list[float]:
        # sentence_embedding 已做 CLS pooling 與 L2 正規化；只取這個輸出（token_embeddings 用不到）
        (vectors,) = self.embedder.run(['sentence_embedding'], _feed(self.tokenizer.encode(text)))
        return [float(x) for x in vectors[0]]

    def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        """sigmoid(logit)。標題式的查詢分數常低於 0.05：只能比較排名，不能設門檻。"""
        scores: list[float] = []
        for passage in passages:
            # 一對文字編成 <s> 查詢 </s></s> 段落 </s>
            (logits,) = self.reranker.run(['logits'], _feed(self.tokenizer.encode(query, passage)))
            scores.append(_sigmoid(float(logits[0][0])))
        return scores
