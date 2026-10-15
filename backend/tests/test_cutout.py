"""去背：前處理、後處理與兩種實作（模擬版、ONNX Runtime）。不需要資料庫，也不需要真正的模型。"""

import io
import math
from pathlib import Path

import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper
from PIL import Image

from app.cutout.processing import INPUT_SIZE, MEAN, STD, CutoutError, compose, load_photo, to_input, to_mask
from app.cutout.segmenter import OnnxSegmenter, SimSegmenter


def png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


def logit(p: float) -> float:
    return math.log(p / (1 - p))


def test_input_is_a_normalized_1024_square() -> None:
    x = to_input(Image.new('RGB', (40, 20), (255, 255, 255)))
    assert x.shape == (1, 3, INPUT_SIZE, INPUT_SIZE)
    assert x.dtype == np.float32
    for c in range(3):
        assert x[0, c, 0, 0] == pytest.approx((1 - MEAN[c]) / STD[c], rel=1e-5)


def test_photos_are_turned_upright_and_converted_to_rgb() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # 拍攝時轉了 90 度
    buf = io.BytesIO()
    Image.new('RGB', (20, 10), (200, 10, 10)).save(buf, 'JPEG', exif=exif)
    photo = load_photo(buf.getvalue())
    assert (photo.size, photo.mode) == ((10, 20), 'RGB')
    assert load_photo(png(Image.new('RGBA', (3, 3)))).mode == 'RGB'


def test_unreadable_photos_raise_a_readable_error() -> None:
    with pytest.raises(CutoutError, match='照片無法讀取'):
        load_photo(b'not an image')


def test_mask_is_resized_and_snaps_near_opaque_and_near_clear_values() -> None:
    # 五個區塊：幾乎透明、偏透明、一半、偏不透明、幾乎不透明
    bands = [-20.0, logit(0.03), 0.0, logit(0.97), 20.0]
    output = np.zeros((1, 1, INPUT_SIZE, INPUT_SIZE), dtype=np.float32)
    width = INPUT_SIZE // len(bands)
    for i, value in enumerate(bands):
        output[0, 0, :, i * width : (i + 1) * width] = value
    output[0, 0, :, len(bands) * width :] = bands[-1]
    mask = to_mask(output, (500, 100))
    assert (mask.size, mask.mode) == ((500, 100), 'L')
    centers = [int(np.asarray(mask)[50, i * 100 + 50]) for i in range(len(bands))]
    assert centers[0] == 0 and centers[1] == 0
    assert 120 <= centers[2] <= 135
    assert centers[3] == 255 and centers[4] == 255


def test_flat_output_does_not_divide_by_zero() -> None:
    mask = to_mask(np.full((1, 1, INPUT_SIZE, INPUT_SIZE), 20.0, dtype=np.float32), (8, 8))
    assert np.asarray(mask)[4, 4] == 255


def test_compose_keeps_the_photo_colors_and_uses_the_mask_as_alpha() -> None:
    photo = Image.new('RGB', (4, 2), (10, 20, 30))
    mask = Image.new('L', (4, 2), 0)
    mask.putpixel((3, 1), 255)
    out = Image.open(io.BytesIO(compose(photo, mask)))
    assert out.mode == 'RGBA'
    px = np.asarray(out)
    assert px[1, 3].tolist() == [10, 20, 30, 255]
    assert px[0, 0, 3] == 0


def test_sim_segmenter_cuts_a_centered_ellipse() -> None:
    out = Image.open(io.BytesIO(SimSegmenter().cut(png(Image.new('RGB', (60, 80), (90, 60, 120))))))
    assert (out.size, out.mode) == ((60, 80), 'RGBA')
    px = np.asarray(out)
    assert px[0, 0, 3] == 0
    assert px[40, 30].tolist() == [90, 60, 120, 255]


def tiny_model(path: Path) -> Path:
    """與 BiRefNet 相同的輸入輸出：output_image = 三個色版的平均（亮的地方是前景）。"""
    graph = helper.make_graph(
        [helper.make_node('ReduceMean', ['input_image'], ['output_image'], axes=[1], keepdims=1)],
        'tiny',
        [helper.make_tensor_value_info('input_image', TensorProto.FLOAT, [1, 3, INPUT_SIZE, INPUT_SIZE])],
        [helper.make_tensor_value_info('output_image', TensorProto.FLOAT, [1, 1, INPUT_SIZE, INPUT_SIZE])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 13)])
    model.ir_version = 8
    onnx.save(model, path)
    return path


def test_onnx_segmenter_runs_the_model_without_a_memory_arena(tmp_path: Path) -> None:
    segmenter = OnnxSegmenter('tiny', tiny_model(tmp_path / 'tiny.onnx'))
    options = segmenter.session.get_session_options()
    assert not options.enable_cpu_mem_arena
    assert not options.enable_mem_pattern
    photo = Image.new('RGB', (64, 32), (0, 0, 0))
    photo.paste((255, 255, 255), (32, 0, 64, 32))
    out = Image.open(io.BytesIO(segmenter.cut(png(photo))))
    assert (out.size, out.mode) == ((64, 32), 'RGBA')
    px = np.asarray(out)
    assert px[16, 8, 3] == 0
    assert px[16, 56].tolist() == [255, 255, 255, 255]
