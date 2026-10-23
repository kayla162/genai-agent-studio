"""測試用的 RunContext：記錄事件與 log，不連資料庫；cancelled 設為 True 後，等待中的 wait() 會中斷。"""

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

from app.contract import JobEvent, LogLevel, LogSource
from app.pipeline.ports import JobCancelled

T = TypeVar('T')

#: 測試中檢查取消旗標的間隔（秒）
POLL = 0.01


class FakeRun:
    def __init__(self, job_id: str = 'job_fake') -> None:
        self.job_id = job_id
        self.events: list[JobEvent] = []
        self.logs: list[tuple[LogSource, LogLevel, str]] = []
        self.cancelled = False

    async def emit(self, event: JobEvent) -> None:
        self.events.append(event)

    async def log(self, source: LogSource, message: str, level: LogLevel = 'info') -> None:
        self.logs.append((source, level, message))

    async def pace(self, ms: float) -> None:
        return None

    async def wait(self, awaitable: Awaitable[T], note: str | None = None) -> T:
        task = asyncio.ensure_future(awaitable)
        while True:
            done, _ = await asyncio.wait({task}, timeout=POLL)
            if done:
                return task.result()
            if self.cancelled:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                if note:
                    self.logs.append(('api', 'warn', note))
                raise JobCancelled()

    def messages(self, level: LogLevel | None = None) -> list[str]:
        return [m for _, lv, m in self.logs if level is None or lv == level]
