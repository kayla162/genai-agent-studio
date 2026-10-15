"""去背的實作：照片（bytes）→ 透明 PNG（bytes）。同步執行，worker 以 asyncio.to_thread 呼叫。"""

from pathlib import Path
from typing import Protocol

import onnxruntime as ort
from PIL import Image, ImageDraw

from app.cutout.processing import compose, load_photo, to_input, to_mask


class Segmenter(Protocol):
    #: 寫進 ProductCutout.model 的名稱
    name: str

    def cut(self, photo: bytes) -> bytes: ...


class OnnxSegmenter:
    """BiRefNet（ONNX）。關閉 ONNX Runtime 的記憶體池：推論完立刻歸還記憶體（峰值約 6.5 GB，平常約 1.1 GB）。"""

    def __init__(self, name: str, model_path: Path) -> None:
        self.name = name
        options = ort.SessionOptions()
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        self.session = ort.InferenceSession(str(model_path), sess_options=options, providers=['CPUExecutionProvider'])
        self.input_name: str = self.session.get_inputs()[0].name

    def cut(self, photo: bytes) -> bytes:
        image = load_photo(photo)
        (output, *_) = self.session.run(None, {self.input_name: to_input(image)})
        return compose(image, to_mask(output, image.size))


class SimSegmenter:
    """模擬去背（測試與 live E2E）：中央的橢圓是前景，不需要模型。"""

    name = 'sim'

    def cut(self, photo: bytes) -> bytes:
        image = load_photo(photo)
        width, height = image.size
        mask = Image.new('L', image.size, 0)
        ImageDraw.Draw(mask).ellipse((width * 0.1, height * 0.05, width * 0.9, height * 0.95), fill=255)
        return compose(image, mask)
