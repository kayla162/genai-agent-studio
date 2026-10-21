"""worker 持有的去背引擎：準備模型（下載、載入）、把狀態寫到 Redis（系統狀態顯示）、提供 Segmenter。"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

import httpx
from redis.asyncio import Redis

from app.cutout.models import MODELS, ensure_model
from app.cutout.processing import CutoutError
from app.cutout.segmenter import OnnxSegmenter, Segmenter, SimSegmenter
from app.cutout.state import STATE_KEY, ModelState
from app.modelfiles import ModelFile, has_model

#: 下載模型的逾時（秒）：連線與兩次讀取之間的間隔
DOWNLOAD_TIMEOUT = 60


class CutoutEngine:
    def __init__(
        self,
        model: str,
        models_dir: Path,
        redis: Redis,
        *,
        models: Mapping[str, ModelFile] = MODELS,
        http: Callable[[], httpx.AsyncClient] = lambda: httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT),
        on_state: Callable[[dict[str, object]], Awaitable[None]] | None = None,
    ) -> None:
        self.model = model
        self.models_dir = models_dir
        self.redis = redis
        self.models = models
        self.http = http
        self.on_state = on_state
        self._segmenter: Segmenter | None = None
        # 同一時間只準備一次；準備中的其他去背任務在這裡等
        self._lock = asyncio.Lock()

    async def segmenter(self) -> Segmenter:
        """等模型準備好。上一次準備失敗時重新嘗試；仍然失敗就丟出 CutoutError。"""
        async with self._lock:
            if self._segmenter is None:
                try:
                    self._segmenter = await self._prepare()
                except CutoutError as error:
                    await self._report('failed', str(error))
                    raise
                except Exception as error:
                    message = f'去背模型準備失敗：{error}'
                    await self._report('failed', message)
                    raise CutoutError(message) from error
            return self._segmenter

    async def warm_up(self) -> None:
        """worker 啟動時在背景準備模型；失敗只記錄狀態，下一次去背時再試。"""
        try:
            await self.segmenter()
        except Exception:
            logging.getLogger(__name__).exception('去背模型準備失敗')

    async def _prepare(self) -> Segmenter:
        if self.model == 'sim':
            await self._report('sim')
            return SimSegmenter()
        model = self.models.get(self.model)
        if model is None:
            supported = '、'.join([*self.models, 'sim'])
            raise CutoutError(f'不支援的去背模型：{self.model}（可用：{supported}）')
        if not await asyncio.to_thread(has_model, model, self.models_dir):
            await self._report('downloading')
            async with self.http() as http:
                await ensure_model(model, self.models_dir, http)
        await self._report('loading')
        segmenter = await asyncio.to_thread(OnnxSegmenter, model.name, self.models_dir / model.filename)
        await self._report('ready')
        return segmenter

    async def _report(self, state: ModelState, error: str | None = None) -> None:
        message: dict[str, object] = {'model': self.model, 'state': state, 'error': error}
        await self.redis.set(STATE_KEY, json.dumps(message, ensure_ascii=False))
        if self.on_state is not None:
            await self.on_state(message)
