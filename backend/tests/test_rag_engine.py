"""RAG 引擎：下載與核對模型檔、按需載入、回報狀態到 Redis、專用的推論執行緒。下載都由假的 HTTP 回應提供，不連外網。"""

import asyncio
import hashlib
import json
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx
import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.modelfiles import ModelFile
from app.rag.encoder import Encoder, OnnxEncoder
from app.rag.engine import RagEngine
from app.rag.errors import RagError
from app.rag.models import EMBEDDER, MODELS, RERANKER, TOKENIZER
from app.rag.state import STATE_KEY
from tests.test_rag_encoder import tiny_models

SERVER = 'https://models.test'


def tiny_files(tmp_path: Path) -> dict[str, bytes]:
    """極小的模型：檔名 → 內容（與真正的模型同名）。"""
    source = tiny_models(tmp_path / 'source')
    return {m.filename: (source / m.filename).read_bytes() for m in MODELS}


def registry(files: dict[str, bytes]) -> list[ModelFile]:
    return [
        ModelFile(
            m.name,
            f'{SERVER}/{m.filename}',
            len(files[m.filename]),
            hashlib.sha256(files[m.filename]).hexdigest(),
            m.filename,
        )
        for m in MODELS
    ]


def serve(
    files: dict[str, bytes], failures: list[int] | None = None
) -> tuple[Callable[[], httpx.AsyncClient], list[str]]:
    """假的模型伺服器：依網址的檔名回傳內容；failures 是前幾個請求依序回的錯誤狀態碼。
    回傳建立 client 的函式，以及收到的請求網址。"""
    requests: list[str] = []
    pending = list(failures or [])

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if pending:
            return httpx.Response(pending.pop(0))
        return httpx.Response(200, content=files[request.url.path.lstrip('/')])

    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)), requests


async def state(redis: Redis) -> dict[str, object]:
    raw = await redis.get(STATE_KEY)
    assert raw is not None
    loaded: dict[str, object] = json.loads(raw)
    return loaded


class Recorder:
    def __init__(self) -> None:
        self.states: list[object] = []

    async def __call__(self, message: dict[str, object]) -> None:
        self.states.append(message['state'])


class StubEncoder:
    """固定的向量與分數；記錄執行的執行緒與同時執行的數量。"""

    def __init__(self) -> None:
        self.threads: set[str] = set()
        self.active = 0
        self.most = 0
        self._lock = threading.Lock()

    def _run(self) -> None:
        with self._lock:
            self.threads.add(threading.current_thread().name)
            self.active += 1
            self.most = max(self.most, self.active)
        time.sleep(0.01)
        with self._lock:
            self.active -= 1

    def embed(self, text: str) -> list[float]:
        self._run()
        return [float(len(text))]

    def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        self._run()
        return [0.5 for _ in passages]


def stub_engine(redis: Redis, models_dir: Path, load: Callable[[Path], Encoder]) -> RagEngine:
    """沒有模型檔要下載的引擎（models 為空），載入時呼叫 load。"""
    return RagEngine('bge', models_dir, redis, models=[], load=load)


async def test_sim_mode_reports_sim_and_never_loads_a_model(redis: Redis, tmp_path: Path) -> None:
    await redis.delete(STATE_KEY)
    engine = RagEngine('sim', tmp_path / 'models', redis)
    await engine.prepare_files()
    assert await state(redis) == {'model': 'sim', 'state': 'sim', 'error': None}
    with pytest.raises(RagError, match='模擬模式'):
        await engine.embed('保濕')
    assert (await state(redis))['state'] == 'sim'
    assert not (tmp_path / 'models').exists()


async def test_prepares_files_without_loading_then_loads_on_first_use(redis: Redis, tmp_path: Path) -> None:
    files = tiny_files(tmp_path)
    client, requests = serve(files)
    seen = Recorder()
    models_dir = tmp_path / 'models'
    engine = RagEngine('bge', models_dir, redis, models=registry(files), http=client, on_state=seen)

    await engine.prepare_files()
    assert seen.states == ['downloading', 'standby']
    assert await state(redis) == {'model': 'bge', 'state': 'standby', 'error': None}
    assert sorted(p.name for p in models_dir.iterdir()) == sorted(files)
    assert [r.rsplit('/', 1)[1] for r in requests] == [TOKENIZER.filename, EMBEDDER.filename, RERANKER.filename]
    assert not engine.loaded

    vector = await engine.embed('serum moisture')
    assert len(vector) == 3
    assert seen.states[2:] == ['loading', 'ready']
    assert engine.loaded
    assert isinstance(await engine.encoder(), OnnxEncoder)
    scores = await engine.rerank('moisture', ['moisture', 'coffee'])
    assert scores[0] > scores[1]
    # 已經載入：不再回報，也不退回 standby
    await engine.prepare_files()
    assert seen.states == ['downloading', 'standby', 'loading', 'ready']
    assert await state(redis) == {'model': 'bge', 'state': 'ready', 'error': None}

    # 第二個 worker：檔案已在，不下載；第一次使用時直接載入
    again = RagEngine('bge', models_dir, redis, models=registry(files), http=client, on_state=seen)
    await again.embed('serum')
    assert seen.states[4:] == ['standby', 'loading', 'ready']
    assert len(requests) == 3


async def test_only_missing_or_corrupt_files_are_downloaded(redis: Redis, tmp_path: Path) -> None:
    files = tiny_files(tmp_path)
    models_dir = tmp_path / 'models'
    models_dir.mkdir()
    (models_dir / TOKENIZER.filename).write_bytes(files[TOKENIZER.filename])
    (models_dir / EMBEDDER.filename).write_bytes(b'corrupt')
    client, requests = serve(files)
    await RagEngine('bge', models_dir, redis, models=registry(files), http=client).prepare_files()
    assert [r.rsplit('/', 1)[1] for r in requests] == [EMBEDDER.filename, RERANKER.filename]
    assert (models_dir / EMBEDDER.filename).read_bytes() == files[EMBEDDER.filename]


async def test_a_failed_download_is_reported_and_retried_on_the_next_call(redis: Redis, tmp_path: Path) -> None:
    files = tiny_files(tmp_path)
    client, _ = serve(files, failures=[503])
    engine = RagEngine('bge', tmp_path / 'models', redis, models=registry(files), http=client)
    with pytest.raises(RagError, match='RAG 模型下載失敗'):
        await engine.prepare_files()
    failed = await state(redis)
    assert failed['state'] == 'failed'
    assert str(failed['error']).startswith('RAG 模型下載失敗')
    assert await engine.embed('serum')
    assert (await state(redis))['state'] == 'ready'


async def test_a_mismatched_download_names_the_model(redis: Redis, tmp_path: Path) -> None:
    files = tiny_files(tmp_path)
    client, _ = serve({**files, EMBEDDER.filename: b'truncated'})
    engine = RagEngine('bge', tmp_path / 'models', redis, models=registry(files), http=client)
    with pytest.raises(RagError, match=r'RAG 模型下載不完整（bge-m3）：檔案大小或 SHA-256 不符'):
        await engine.encoder()
    assert (await state(redis))['state'] == 'failed'
    assert not (tmp_path / 'models' / EMBEDDER.filename).exists()


async def test_a_model_that_fails_to_load_is_reported_and_retried(redis: Redis, tmp_path: Path) -> None:
    attempts: list[Path] = []
    stub = StubEncoder()

    def load(models_dir: Path) -> Encoder:
        attempts.append(models_dir)
        if len(attempts) == 1:
            raise RuntimeError('not an onnx model')
        return stub

    seen = Recorder()
    engine = RagEngine('bge', tmp_path, redis, models=[], load=load, on_state=seen)
    with pytest.raises(RagError, match='RAG 模型準備失敗：not an onnx model'):
        await engine.embed('serum')
    assert await state(redis) == {'model': 'bge', 'state': 'failed', 'error': 'RAG 模型準備失敗：not an onnx model'}
    assert not engine.loaded
    assert await engine.embed('serum') == [5.0]
    assert seen.states == ['standby', 'loading', 'failed', 'loading', 'ready']
    assert attempts == [tmp_path, tmp_path]


async def test_concurrent_callers_load_once(redis: Redis, tmp_path: Path) -> None:
    loads: list[Path] = []

    def load(models_dir: Path) -> Encoder:
        loads.append(models_dir)
        return StubEncoder()

    engine = stub_engine(redis, tmp_path, load)
    await asyncio.gather(*(engine.embed(str(i)) for i in range(5)))
    assert len(loads) == 1


async def test_inference_runs_one_at_a_time_on_the_rag_thread(redis: Redis, tmp_path: Path) -> None:
    stub = StubEncoder()
    engine = stub_engine(redis, tmp_path, lambda _: stub)
    results = await asyncio.gather(*(engine.embed('x' * i) for i in range(1, 5)), engine.rerank('q', ['a', 'b']))
    assert results == [[1.0], [2.0], [3.0], [4.0], [0.5, 0.5]]
    assert stub.most == 1
    assert len(stub.threads) == 1
    assert next(iter(stub.threads)).startswith('rag')


def test_registry_lists_the_benchmarked_models() -> None:
    assert [(m.name, m.filename, m.size, m.sha256[:12]) for m in MODELS] == [
        ('bge-m3-tokenizer', 'bge-m3-tokenizer.json', 17082821, '6710678b1267'),
        ('bge-m3', 'bge-m3-int8.onnx', 568599071, 'e5b42096865c'),
        ('bge-reranker-v2-m3', 'bge-reranker-v2-m3-int8.onnx', 570727094, '912fc1215c2d'),
    ]
    assert all('/resolve/' in m.url and m.url.startswith('https://huggingface.co/') for m in MODELS)


async def test_a_cancelled_caller_does_not_stop_the_preparation(redis: Redis, tmp_path: Path) -> None:
    """任務在檢索時被取消（等模型載入中）：載入照樣完成，狀態不會停在載入中，下一個呼叫不必重新載入。"""
    started, release = threading.Event(), threading.Event()
    loads: list[Path] = []

    def load(models_dir: Path) -> Encoder:
        loads.append(models_dir)
        started.set()
        release.wait(2)
        return StubEncoder()

    engine = stub_engine(redis, tmp_path, load)
    waiting = asyncio.create_task(engine.embed('serum'))
    assert await asyncio.to_thread(started.wait, 2)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    release.set()
    assert await engine.embed('serum') == [5.0]
    assert loads == [tmp_path]
    assert (await state(redis))['state'] == 'ready'


async def test_a_redis_failure_while_reporting_the_state_keeps_the_loaded_model(
    redis: Redis, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """狀態只是給系統狀態顯示：寫不進 Redis 時記錄下來就好，已載入的模型照常使用。"""
    loads: list[Path] = []

    def load(models_dir: Path) -> Encoder:
        loads.append(models_dir)
        return StubEncoder()

    engine = stub_engine(redis, tmp_path, load)

    async def down(*args: object, **kwargs: object) -> None:
        raise RedisConnectionError('Redis 已停止')

    monkeypatch.setattr(engine.redis, 'set', down)
    assert await engine.embed('serum') == [5.0]
    assert engine.loaded
    assert await engine.embed('mask') == [4.0]
    assert loads == [tmp_path]
