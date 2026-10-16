"""去背模型：下載與核對、載入、回報狀態到 Redis。下載都由假的 HTTP 回應提供，不連外網。"""

import hashlib
import io
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest
from PIL import Image
from redis.asyncio import Redis

from app.cutout.engine import CutoutEngine
from app.cutout.models import CHUNK, ModelFile, ensure_model
from app.cutout.processing import CutoutError
from app.cutout.segmenter import OnnxSegmenter, SimSegmenter
from app.cutout.state import STATE_KEY
from tests.test_cutout import png, tiny_model

URL = 'https://models.test/tiny.onnx'


def model_file(content: bytes, name: str = 'tiny') -> ModelFile:
    return ModelFile(name=name, url=URL, size=len(content), sha256=hashlib.sha256(content).hexdigest())


def serve(content: bytes, status: int = 200) -> tuple[Callable[[], httpx.AsyncClient], list[str]]:
    """假的模型伺服器：回傳建立 client 的函式，以及收到的請求網址。"""
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(status, content=content)

    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)), requests


async def state(redis: Redis) -> dict[str, object]:
    raw = await redis.get(STATE_KEY)
    assert raw is not None
    loaded: dict[str, object] = json.loads(raw)
    return loaded


async def test_downloads_into_a_part_file_and_renames_after_the_checksum(tmp_path: Path) -> None:
    content = b'model bytes' * 100
    client, requests = serve(content)
    async with client() as http:
        path = await ensure_model(model_file(content), tmp_path / 'models', http)
    assert path == tmp_path / 'models' / 'tiny.onnx'
    assert path.read_bytes() == content
    assert requests == [URL]
    assert list((tmp_path / 'models').iterdir()) == [path]

    # 已有正確的檔案：不再下載
    async with client() as http:
        assert await ensure_model(model_file(content), tmp_path / 'models', http) == path
    assert requests == [URL]


async def test_a_corrupt_download_leaves_nothing_behind(tmp_path: Path) -> None:
    client, _ = serve(b'truncated')
    with pytest.raises(CutoutError, match='SHA-256'):
        async with client() as http:
            await ensure_model(model_file(b'the real model'), tmp_path, http)
    assert list(tmp_path.iterdir()) == []


async def test_a_download_larger_than_declared_stops_early_and_leaves_nothing_behind(tmp_path: Path) -> None:
    sent = 0

    class Endless(httpx.AsyncByteStream):
        """伺服器一直送資料（最多 50 MiB）；超過宣告的大小就應該停止讀取。"""

        async def __aiter__(self) -> AsyncIterator[bytes]:
            nonlocal sent
            while sent < 50:
                sent += 1
                yield bytes(CHUNK)

    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=Endless()))
    with pytest.raises(CutoutError, match='SHA-256'):
        async with httpx.AsyncClient(transport=transport) as http:
            await ensure_model(model_file(b'the real model'), tmp_path, http)
    assert sent < 5
    assert list(tmp_path.iterdir()) == []


async def test_http_errors_are_reported_in_chinese(tmp_path: Path) -> None:
    client, _ = serve(b'', status=503)
    with pytest.raises(CutoutError, match='去背模型下載失敗'):
        async with client() as http:
            await ensure_model(model_file(b'x'), tmp_path, http)


async def test_sim_engine_needs_no_model(redis: Redis, tmp_path: Path) -> None:
    await redis.delete(STATE_KEY)
    engine = CutoutEngine('sim', tmp_path, redis)
    assert isinstance(await engine.segmenter(), SimSegmenter)
    assert await state(redis) == {'model': 'sim', 'state': 'sim', 'error': None}


async def test_downloads_loads_and_reports_each_state(redis: Redis, tmp_path: Path) -> None:
    content = tiny_model(tmp_path / 'source.onnx').read_bytes()
    client, requests = serve(content)
    seen: list[object] = []

    async def record(message: dict[str, object]) -> None:
        seen.append(message['state'])

    models = {'tiny': model_file(content)}
    engine = CutoutEngine('tiny', tmp_path / 'models', redis, models=models, http=client, on_state=record)
    segmenter = await engine.segmenter()
    assert isinstance(segmenter, OnnxSegmenter)
    assert await engine.segmenter() is segmenter
    assert seen == ['downloading', 'loading', 'ready']
    assert await state(redis) == {'model': 'tiny', 'state': 'ready', 'error': None}
    assert len(requests) == 1
    assert Image.open(io.BytesIO(segmenter.cut(png(Image.new('RGB', (8, 8)))))).mode == 'RGBA'

    # 第二個 worker：檔案已在，只載入
    again = CutoutEngine('tiny', tmp_path / 'models', redis, models=models, http=client, on_state=record)
    await again.segmenter()
    assert seen[3:] == ['loading', 'ready']
    assert len(requests) == 1


async def test_a_failed_download_is_reported_and_retried_on_the_next_cutout(redis: Redis, tmp_path: Path) -> None:
    content = tiny_model(tmp_path / 'source.onnx').read_bytes()
    replies = [httpx.Response(503), httpx.Response(200, content=content)]

    def handler(request: httpx.Request) -> httpx.Response:
        return replies.pop(0)

    engine = CutoutEngine(
        'tiny',
        tmp_path / 'models',
        redis,
        models={'tiny': model_file(content)},
        http=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(CutoutError, match='去背模型下載失敗'):
        await engine.segmenter()
    failed = await state(redis)
    assert failed['state'] == 'failed'
    assert '去背模型下載失敗' in str(failed['error'])
    assert isinstance(await engine.segmenter(), OnnxSegmenter)
    assert (await state(redis))['state'] == 'ready'


async def test_unknown_models_fail_with_the_supported_names(redis: Redis, tmp_path: Path) -> None:
    engine = CutoutEngine('u2net', tmp_path, redis)
    with pytest.raises(CutoutError, match='birefnet-general'):
        await engine.segmenter()


def corrupt_engine(redis: Redis, tmp_path: Path) -> CutoutEngine:
    """模型檔的大小與 SHA-256 都正確，但內容不是 ONNX，載入時會失敗。"""
    content = b'not an onnx model' * 10
    models_dir = tmp_path / 'models'
    models_dir.mkdir()
    (models_dir / 'bad.onnx').write_bytes(content)
    models = {'bad': ModelFile('bad', URL, len(content), hashlib.sha256(content).hexdigest())}
    return CutoutEngine('bad', models_dir, redis, models=models)


async def test_a_model_that_fails_to_load_is_reported_as_failed(redis: Redis, tmp_path: Path) -> None:
    engine = corrupt_engine(redis, tmp_path)
    with pytest.raises(CutoutError, match='去背模型準備失敗'):
        await engine.segmenter()
    failed = await state(redis)
    assert failed['model'] == 'bad'
    assert failed['state'] == 'failed'
    assert str(failed['error']).startswith('去背模型準備失敗')


async def test_warm_up_does_not_raise_for_a_model_that_fails_to_load(redis: Redis, tmp_path: Path) -> None:
    await corrupt_engine(redis, tmp_path).warm_up()
    assert (await state(redis))['state'] == 'failed'


def test_registry_lists_the_benchmarked_models() -> None:
    from app.cutout.models import MODELS

    assert {name: (m.size, m.sha256[:12]) for name, m in MODELS.items()} == {
        'birefnet-general': (972666916, '58f621f00f5d'),
        'birefnet-general-lite': (224005088, '5600024376f5'),
    }
