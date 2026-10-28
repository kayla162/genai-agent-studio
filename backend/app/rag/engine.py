"""worker 持有的 RAG 引擎：下載與核對模型檔、第一次使用時才載入、把狀態寫到 Redis（系統狀態顯示），
並在 RAG 專用的單一執行緒裡向量化與 Rerank。"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.modelfiles import ModelFile, ModelFileError, download_client, ensure_model, has_model
from app.rag.encoder import Encoder, OnnxEncoder
from app.rag.errors import RagError
from app.rag.models import MODELS
from app.rag.state import STATE_KEY, RagMode, RagModelState

logger = logging.getLogger(__name__)

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
        #: 進行中的模型準備（下載與載入）；失敗後清掉，下一次呼叫重新準備
        self._preparing: asyncio.Task[Encoder] | None = None

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
        if self._encoder is None:
            if self._preparing is None:
                self._preparing = asyncio.create_task(self._prepare())
            preparing = self._preparing
            try:
                # 等待的一方被取消（例如任務在檢索時被取消）不會中斷準備：模型照樣下載、載入，
                # 狀態不會停在下載中或載入中，下一個呼叫也不必重來
                self._encoder = await asyncio.shield(preparing)
            except BaseException:
                if preparing.done() and (preparing.cancelled() or preparing.exception() is not None):
                    self._preparing = None
                raise
        return self._encoder

    async def _prepare(self) -> Encoder:
        async with self._lock:
            await self._step(self._ensure_files)
            return await self._step(self._load)

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
        """狀態只給系統狀態顯示：寫不進 Redis 時只記錄，不影響模型的準備與使用。"""
        message: dict[str, object] = {'model': self.mode, 'state': state, 'error': error}
        try:
            await self.redis.set(STATE_KEY, json.dumps(message, ensure_ascii=False))
        except (RedisError, OSError):
            logger.warning('RAG 模型狀態無法寫入 Redis：%s', state, exc_info=True)
        if self.on_state is not None:
            await self.on_state(message)
