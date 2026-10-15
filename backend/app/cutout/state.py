"""去背模型的狀態：worker 寫入 Redis，api 的系統狀態讀取（api 不必載入 onnxruntime）。"""

from typing import Literal

#: worker 回報模型狀態的 Redis key：{"model": …, "state": …, "error": …}
STATE_KEY = 'cutout:model'

ModelState = Literal['downloading', 'loading', 'ready', 'failed', 'sim']
