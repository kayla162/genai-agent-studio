"""RAG 模型的狀態：worker 寫入 Redis，api 的系統狀態讀取（api 不必載入 onnxruntime）。"""

from typing import Literal

#: worker 回報模型狀態的 Redis key：{"model": 模式, "state": …, "error": …}（與去背的 cutout:model 相同格式）
STATE_KEY = 'rag:model'

#: RAG_MODE：bge（真正的模型與 Chroma）或 sim（模擬檢索，不下載模型、不連 Chroma）
RagMode = Literal['bge', 'sim']

#: standby：模型檔已下載並核對，第一次向量化或 Rerank 時才載入
RagModelState = Literal['sim', 'downloading', 'standby', 'loading', 'ready', 'failed']
