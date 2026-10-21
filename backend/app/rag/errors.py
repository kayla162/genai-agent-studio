"""RAG 的錯誤：模型準備失敗或向量庫（Chroma）無法使用。訊息為繁體中文，直接顯示為任務失敗的原因或上傳的錯誤。"""

from app.errors import Unavailable


class RagError(Unavailable):
    pass
