"""生圖與商品去背互斥（Plan 7 規格 §4.7）：16 GB 記憶體的筆電上，ComfyUI 生圖與 BiRefNet 去背同時執行會不夠。

以 Redis 鎖實作（worker 的任務與去背可能在不同的程序）：持有期間每 ttl / 3 秒延長；worker 異常結束時，
沒有延長的鎖在 ttl 秒後自動釋放。等待時每 poll 秒重試，傳入 run 時以 run.wait 等待（取消任務會中止等待）。
MEMORY_LOCK=false 時不建立鎖，直接進入。
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import LockError

from app.pipeline.ports import RunContext

#: Redis 的鍵
LOCK_NAME = 'heavy-memory'


class LockLike(Protocol):
    """redis-py 的 asyncio Lock 用到的部分（測試以記憶體裡的假鎖取代）。"""

    def acquire(self, blocking: bool | None = ...) -> Awaitable[bool]: ...

    def reacquire(self) -> Awaitable[bool]: ...

    def release(self) -> Awaitable[None]: ...


MakeLock = Callable[[str, float], LockLike]


class HeavyMemoryLock:
    def __init__(self, make_lock: MakeLock, *, enabled: bool = True, ttl: float = 60, poll: float = 0.5) -> None:
        self.make_lock = make_lock
        self.enabled = enabled
        self.ttl = ttl
        self.poll = poll

    @classmethod
    def from_redis(cls, redis: Redis, *, enabled: bool = True, poll: float = 0.5) -> 'HeavyMemoryLock':
        return cls(lambda name, ttl: redis.lock(name, timeout=ttl, thread_local=False), enabled=enabled, poll=poll)

    @contextlib.asynccontextmanager
    async def hold(
        self, waiting: Callable[[], Awaitable[None]] | None = None, run: RunContext | None = None
    ) -> AsyncIterator[None]:
        """取得鎖後進入；別人持有時先呼叫一次 waiting()（例如送出「等待商品去背完成」），再等到拿到為止。"""
        if not self.enabled:
            yield
            return
        lock = self.make_lock(LOCK_NAME, self.ttl)
        if not await lock.acquire(blocking=False):
            if waiting is not None:
                await waiting()
            acquiring = self._acquire(lock)
            await (run.wait(acquiring) if run is not None else acquiring)
        renewing = asyncio.create_task(self._renew(lock))
        try:
            yield
        finally:
            renewing.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await renewing
            with contextlib.suppress(LockError):
                await lock.release()

    async def _acquire(self, lock: LockLike) -> None:
        while not await lock.acquire(blocking=False):
            await asyncio.sleep(self.poll)

    async def _renew(self, lock: LockLike) -> None:
        while True:
            await asyncio.sleep(self.ttl / 3)
            with contextlib.suppress(LockError):
                await lock.reacquire()
