"""HeavyMemoryLock：生圖與商品去背互斥（Plan 7 規格 §4.7）。以記憶體裡的假鎖（與 redis-py 的 asyncio Lock
相同的 acquire、reacquire、release 與到期）測試，不需要 Redis。"""

import asyncio
from dataclasses import dataclass, field

import pytest

from app.pipeline.memory import HeavyMemoryLock
from app.pipeline.ports import JobCancelled
from tests.fake_run import FakeRun


@dataclass
class Store:
    """一個 Redis 鍵：持有者與到期時間（event loop 的時間）。"""

    owner: object | None = None
    expires: float = 0.0
    acquired: list[str] = field(default_factory=list)

    def free(self) -> bool:
        return self.owner is None or asyncio.get_running_loop().time() >= self.expires


class FakeLock:
    def __init__(self, store: Store, ttl: float, label: str) -> None:
        self.store, self.ttl, self.label = store, ttl, label

    async def acquire(self, blocking: bool | None = None) -> bool:
        assert blocking is False
        if not self.store.free():
            return False
        self.store.owner, self.store.expires = self, asyncio.get_running_loop().time() + self.ttl
        self.store.acquired.append(self.label)
        return True

    async def reacquire(self) -> bool:
        assert self.store.owner is self, '只有持有者可以延長'
        self.store.expires = asyncio.get_running_loop().time() + self.ttl
        return True

    async def release(self) -> None:
        if self.store.owner is self:
            self.store.owner = None


def lock(store: Store, label: str, ttl: float = 0.2, enabled: bool = True) -> HeavyMemoryLock:
    return HeavyMemoryLock(lambda name, ttl: FakeLock(store, ttl, label), ttl=ttl, poll=0.01, enabled=enabled)


async def test_the_second_holder_waits_and_is_told_once() -> None:
    store = Store()
    told: list[str] = []
    entered = asyncio.Event()

    async def first() -> None:
        async with lock(store, 'render').hold():
            entered.set()
            await asyncio.sleep(0.1)

    async def second() -> None:
        await entered.wait()

        async def waiting() -> None:
            told.append('等待')

        async with lock(store, 'cutout').hold(waiting):
            assert store.owner is not None

    await asyncio.gather(first(), second())
    assert store.acquired == ['render', 'cutout']
    assert told == ['等待']


async def test_holding_longer_than_the_ttl_keeps_the_lock() -> None:
    store = Store()
    other = lock(store, 'cutout', ttl=0.2)
    async with lock(store, 'render', ttl=0.2).hold():
        await asyncio.sleep(0.5)
        # 持有者每 ttl / 3 延長一次：別人一直拿不到
        assert not await FakeLock(store, 0.2, 'probe').acquire(blocking=False)
    async with other.hold():
        pass
    assert store.acquired == ['render', 'cutout']


async def test_a_holder_that_died_releases_the_lock_when_it_expires() -> None:
    store = Store()
    # 模擬 worker 異常結束：拿到鎖但沒有延長也沒有釋放
    assert await FakeLock(store, 0.1, 'dead').acquire(blocking=False)
    async with lock(store, 'render').hold():
        pass
    assert store.acquired == ['dead', 'render']


async def test_cancelling_while_waiting_does_not_take_the_lock() -> None:
    store = Store()
    fake = FakeRun()
    async with lock(store, 'cutout').hold():
        task = asyncio.create_task(lock(store, 'render').hold(run=fake).__aenter__())
        await asyncio.sleep(0.05)
        fake.cancelled = True
        with pytest.raises(JobCancelled):
            await task
    assert store.acquired == ['cutout']


async def test_a_disabled_lock_never_touches_redis() -> None:
    def explode(name: str, ttl: float) -> FakeLock:
        raise AssertionError('MEMORY_LOCK=false 不應該建立鎖')

    async with HeavyMemoryLock(explode, enabled=False).hold():
        pass
