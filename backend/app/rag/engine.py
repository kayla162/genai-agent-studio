"""worker 持有的 RAG 引擎：下載與核對模型檔、第一次使用時才載入、把狀態寫到 Redis（系統狀態顯示），
並在 RAG 專用的單一執行緒裡向量化與 Rerank。"""

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from redis.asyncio import Redis

from app.modelfiles import ModelFile, ModelFileError, download_client, ensure_model, has_model
from app.rag.encoder import Encoder, OnnxEncoder
from app.rag.errors import RagError
from app.rag.models import MODELS
from app.rag.state import STATE_KEY, RagMode, RagModelState

#: RAG 推論專用的單一執行緒：不與去背共用（去背時檢索不必等），一次只算一筆
INFERENCE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix='rag')


class RagEngine:
    def __init__(
        self,
        mode: RagMode,
        models_dir: Path,
        redis: Redis,
        *,
        models: Sequence[ModelFile] = MODELS,
        load: Callable[[Path], Encoder] = OnnxEncoder,
        http: Callable[[], httpx.AsyncClient] = download_client,
        on_state: Callable[[dict[str, object]], Awaitable[None]] | None = None,
    ) -> None:
        self.mode = mode
        self.models_dir = models_dir
        self.redis = redis
        self.models = models
        self.load = load
        self.http = http
        self.on_state = on_state
        self._files_ready = False
        self._encoder: Encoder | None = None
        # 同一時間只準備一次；準備中的其他呼叫在這裡等
        self._lock = asyncio.Lock()

    @property
    def loaded(self) -> bool:
        """模型已載入：之後的向量化與 Rerank 不必等下載或載入。"""
        return self._encoder is not None

    async def prepare_files(self) -> None:
        """worker 啟動時：下載並核對模型檔，但不載入（standby）。失敗時回報 failed 並丟出 RagError，下一次再試。"""
        async with self._lock:
            if self.mode == 'sim':
                await self._report('sim')
                return
            await self._step(self._ensure_files)

    async def encoder(self) -> Encoder:
        """等模型準備好（第一次呼叫時才載入，之後常駐）。上一次失敗時重新嘗試；仍然失敗就丟出 RagError。"""
        if self.mode == 'sim':
            raise RagError('模擬模式（RAG_MODE=sim）不使用 RAG 模型')
        async with self._lock:
            if self._encoder is None:
                await self._step(self._ensure_files)
                self._encoder = await self._step(self._load)
            return self._encoder

    async def embed(self, text: str) -> list[float]:
        encoder = await self.encoder()
        return await asyncio.get_running_loop().run_in_executor(INFERENCE_EXECUTOR, encoder.embed, text)

    async def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        encoder = await self.encoder()
        return await asyncio.get_running_loop().run_in_executor(INFERENCE_EXECUTOR, encoder.rerank, query, passages)

    async def _step[T](self, step: Callable[[], Awaitable[T]]) -> T:
        """失敗時回報 failed；其他錯誤轉成 RagError。"""
        try:
            return await step()
        except RagError as error:
            await self._report('failed', error.message)
            raise
        except Exception as error:
            message = f'RAG 模型準備失敗：{error}'
            await self._report('failed', message)
            raise RagError(message) from error

    async def _ensure_files(self) -> None:
        if self._files_ready:
            return
        missing = [m for m in self.models if not await asyncio.to_thread(has_model, m, self.models_dir)]
        if missing:
            await self._report('downloading')
            async with self.http() as http:
                for model in missing:
                    try:
                        await ensure_model(model, self.models_dir, http)
                    except ModelFileError as error:
                        raise RagError(f'RAG 模型{error}') from error
        self._files_ready = True
        await self._report('standby')

    async def _load(self) -> Encoder:
        await self._report('loading')
        encoder = await asyncio.to_thread(self.load, self.models_dir)
        await self._report('ready')
        return encoder

    async def _report(self, state: RagModelState, error: str | None = None) -> None:
        message: dict[str, object] = {'model': self.mode, 'state': state, 'error': error}
        await self.redis.set(STATE_KEY, json.dumps(message, ensure_ascii=False))
        if self.on_state is not None:
            await self.on_state(message)
