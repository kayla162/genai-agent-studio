"""RAG 的 OnnxEncoder：以極小的 ONNX 模型與 tokenizer 測試（輸入輸出的名稱與真正的模型相同），不需要真正的模型檔。"""

import math
from pathlib import Path
from typing import Any

import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper
from tokenizers import Tokenizer, models, pre_tokenizers, processors

from app.rag.encoder import MAX_TOKENS, OnnxEncoder
from app.rag.models import EMBEDDER, RERANKER, TOKENIZER

#: 極小的詞彙表：前四個與 XLM-RoBERTa 相同（<pad> 的 id 為 1）
VOCAB = ['<s>', '<pad>', '</s>', '<unk>', 'serum', 'moisture', 'autumn', 'coffee', 'origin']
#: 每個詞的向量（3 維：保養、季節、咖啡）
TABLE = [
    [0.1, 0.1, 0.1],
    [0.0, 0.0, 0.0],
    [0.1, 0.1, 0.1],
    [0.0, 0.0, 0.0],
    [1.0, 0.0, 0.0],
    [1.0, 0.2, 0.0],
    [0.2, 1.0, 0.0],
    [0.0, 0.0, 1.0],
    [0.0, 0.1, 1.0],
]
#: 每個詞對 Rerank logit 的貢獻：保濕相關為正、咖啡為負
WEIGHTS = [0.0, 0.0, 0.0, 0.0, 0.5, 1.0, 0.0, -1.0, -0.5]


def tiny_tokenizer(path: Path) -> Path:
    """以空白斷詞，特殊 token 的排法與 bge-m3 相同：<s> A </s>、<s> A </s></s> B </s>。"""
    tokenizer = Tokenizer(models.WordLevel({w: i for i, w in enumerate(VOCAB)}, unk_token='<unk>'))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.post_processor = processors.TemplateProcessing(
        single='<s> $A </s>', pair='<s> $A </s> </s> $B </s>', special_tokens=[('<s>', 0), ('</s>', 2)]
    )
    tokenizer.save(str(path))
    return path


def _inputs() -> list[onnx.ValueInfoProto]:
    return [
        helper.make_tensor_value_info('input_ids', TensorProto.INT64, ['batch', 'seq']),
        helper.make_tensor_value_info('attention_mask', TensorProto.INT64, ['batch', 'seq']),
    ]


def _masked(table: str) -> list[onnx.NodeProto]:
    """每個 token 查表後乘上 attention_mask：輸出 masked [batch, seq, dims]。"""
    return [
        helper.make_node('Gather', [table, 'input_ids'], ['token_embeddings']),
        helper.make_node('Cast', ['attention_mask'], ['mask'], to=TensorProto.FLOAT),
        helper.make_node('Unsqueeze', ['mask', 'last'], ['mask3']),
        helper.make_node('Mul', ['token_embeddings', 'mask3'], ['masked']),
    ]


def _save(graph: onnx.GraphProto, path: Path) -> Path:
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 13)])
    model.ir_version = 8
    onnx.save(model, path)
    return path


def tiny_embedder(path: Path) -> Path:
    """與 bge-m3 相同的輸入輸出：token_embeddings，以及平均後 L2 正規化的 sentence_embedding。"""
    graph = helper.make_graph(
        [
            *_masked('table'),
            helper.make_node('ReduceSum', ['masked', 'seq_axis'], ['summed'], keepdims=0),
            helper.make_node('LpNormalization', ['summed'], ['sentence_embedding'], axis=1, p=2),
        ],
        'tiny-embedder',
        _inputs(),
        [
            helper.make_tensor_value_info('token_embeddings', TensorProto.FLOAT, ['batch', 'seq', 3]),
            helper.make_tensor_value_info('sentence_embedding', TensorProto.FLOAT, ['batch', 3]),
        ],
        [
            helper.make_tensor('table', TensorProto.FLOAT, [len(VOCAB), 3], [x for row in TABLE for x in row]),
            helper.make_tensor('last', TensorProto.INT64, [1], [2]),
            helper.make_tensor('seq_axis', TensorProto.INT64, [1], [1]),
        ],
    )
    return _save(graph, path)


def tiny_reranker(path: Path) -> Path:
    """與 bge-reranker-v2-m3 相同的輸入輸出：logits [batch, 1] = 查詢與段落每個 token 的權重總和。"""
    graph = helper.make_graph(
        [*_masked('weights'), helper.make_node('ReduceSum', ['masked', 'seq_axis'], ['logits'], keepdims=0)],
        'tiny-reranker',
        _inputs(),
        [helper.make_tensor_value_info('logits', TensorProto.FLOAT, ['batch', 1])],
        [
            helper.make_tensor('weights', TensorProto.FLOAT, [len(VOCAB), 1], WEIGHTS),
            helper.make_tensor('last', TensorProto.INT64, [1], [2]),
            helper.make_tensor('seq_axis', TensorProto.INT64, [1], [1]),
        ],
    )
    return _save(graph, path)


def tiny_models(models_dir: Path) -> Path:
    """三個檔案放在真正模型的檔名下。"""
    models_dir.mkdir(parents=True, exist_ok=True)
    tiny_tokenizer(models_dir / TOKENIZER.filename)
    tiny_embedder(models_dir / EMBEDDER.filename)
    tiny_reranker(models_dir / RERANKER.filename)
    return models_dir


class Recording:
    """記錄每次 run 的輸入形狀與要求的輸出。"""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.calls: list[tuple[list[str], tuple[int, ...], list[int]]] = []

    def run(self, names: list[str], feed: dict[str, np.ndarray[Any, Any]]) -> Any:
        self.calls.append((names, feed['input_ids'].shape, feed['attention_mask'][0].tolist()))
        return self.session.run(names, feed)


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


@pytest.fixture
def encoder(tmp_path: Path) -> OnnxEncoder:
    return OnnxEncoder(tiny_models(tmp_path))


def test_embeddings_are_normalized_and_related_texts_score_higher(encoder: OnnxEncoder) -> None:
    serum, moisture, coffee = (np.array(encoder.embed(t)) for t in ('serum', 'moisture serum', 'coffee origin'))
    assert len(serum) == 3
    assert np.linalg.norm(serum) == pytest.approx(1, abs=1e-6)
    assert serum @ moisture > serum @ coffee


def test_rerank_scores_each_pair_with_sigmoid(encoder: OnnxEncoder) -> None:
    # 查詢與段落的 token 都算進 logit：moisture（1）+ moisture（1）、moisture（1）+ coffee（-1）
    scores = encoder.rerank('moisture', ['moisture', 'coffee', 'autumn'])
    assert scores == pytest.approx([sigmoid(2), sigmoid(0), sigmoid(1)], abs=1e-6)
    assert encoder.rerank('moisture', []) == []


def test_each_text_and_each_pair_is_its_own_batch_of_one(encoder: OnnxEncoder) -> None:
    embedder, reranker = Recording(encoder.embedder), Recording(encoder.reranker)
    encoder.embedder, encoder.reranker = embedder, reranker
    encoder.embed('serum moisture')
    encoder.rerank('serum', ['moisture', 'coffee origin'])
    # <s> serum moisture </s>；只要求 sentence_embedding
    assert embedder.calls == [(['sentence_embedding'], (1, 4), [1, 1, 1, 1])]
    # <s> serum </s></s> moisture </s>、<s> serum </s></s> coffee origin </s>：每一對各算一次，不補 <pad>
    assert reranker.calls == [(['logits'], (1, 6), [1] * 6), (['logits'], (1, 7), [1] * 7)]


def test_long_texts_and_long_queries_are_truncated_to_512_tokens(encoder: OnnxEncoder) -> None:
    embedder, reranker = Recording(encoder.embedder), Recording(encoder.reranker)
    encoder.embedder, encoder.reranker = embedder, reranker
    long = ' '.join(['serum'] * 2000)
    encoder.embed(long)
    # 查詢本身就超過上限時也能截斷
    encoder.rerank(long, [long, 'coffee'])
    assert [shape for _, shape, _ in embedder.calls + reranker.calls] == [(1, MAX_TOKENS)] * 3


def test_sessions_run_without_a_memory_arena(encoder: OnnxEncoder) -> None:
    for session in (encoder.embedder, encoder.reranker):
        options = session.get_session_options()
        assert not options.enable_cpu_mem_arena
        assert not options.enable_mem_pattern
