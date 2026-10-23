"""ordered：並行執行、依原本順序取得結果（Prompt 構建與審查的事件依模板與候選順序送出）。不需要資料庫。"""

import asyncio
from contextlib import aclosing

import pytest

from app.pipeline.runner import ordered


async def test_yields_in_order_even_when_later_ones_finish_first() -> None:
    finished: list[int] = []

    async def work(i: int, delay: float) -> int:
        await asyncio.sleep(delay)
        finished.append(i)
        return i

    got: list[int] = []
    async with aclosing(ordered([work(0, 0.05), work(1, 0.0), work(2, 0.02)])) as results:
        async for value in results:
            got.append(value)
    assert got == [0, 1, 2]
    assert finished == [1, 2, 0]


async def test_a_failure_cancels_the_rest_and_raises_the_original_error() -> None:
    cancelled = asyncio.Event()

    async def ok() -> int:
        return 1

    async def boom() -> int:
        await asyncio.sleep(0.01)
        raise RuntimeError('第二個失敗')

    async def slow() -> int:
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return 3

    got: list[int] = []
    with pytest.raises(RuntimeError, match='第二個失敗'):
        async with aclosing(ordered([ok(), boom(), slow()])) as results:
            async for value in results:
                got.append(value)
    assert got == [1]
    assert cancelled.is_set()


async def test_stopping_early_cancels_the_pending_work() -> None:
    cancelled = asyncio.Event()

    async def slow() -> int:
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return 2

    async def first() -> int:
        return 1

    with pytest.raises(KeyError):
        async with aclosing(ordered([first(), slow()])) as results:
            async for _ in results:
                raise KeyError('取消任務')
    assert cancelled.is_set()


async def test_nothing_to_do() -> None:
    async with aclosing(ordered(list[asyncio.Future[int]]())) as results:
        assert [v async for v in results] == []
