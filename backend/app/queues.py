"""SAQ 佇列：api 放入工作，worker 執行。

- jobs：生圖任務，一次只執行一個（只有一張 GPU）；key 為任務 id，同一個任務不會重複排入。
- tasks：去背、文件上傳、回寫歷史案例，最多同時兩個，不必等生圖任務。
"""

from dataclasses import dataclass
from typing import Any

from saq import Queue
from saq.job import Status

JOBS = 'jobs'
TASKS = 'tasks'
#: tasks 佇列裡單一工作最長的執行時間（秒）
TASK_TIMEOUT = 600


@dataclass(frozen=True)
class TaskResult:
    #: 在等待時間內完成
    completed: bool
    result: Any


class Queues:
    def __init__(self, redis_url: str) -> None:
        self.jobs = Queue.from_url(redis_url, name=JOBS)
        self.tasks = Queue.from_url(redis_url, name=TASKS)

    async def connect(self) -> None:
        await self.jobs.connect()
        await self.tasks.connect()

    async def disconnect(self) -> None:
        await self.jobs.disconnect()
        await self.tasks.disconnect()

    async def enqueue_job(self, job_id: str) -> None:
        """生圖可能花上數十分鐘，不設逾時（流程內各步驟有自己的逾時）。"""
        await self.jobs.enqueue('run_job', key=job_id, timeout=0, job_id=job_id)

    async def enqueue_task(self, name: str, **kwargs: Any) -> None:
        await self.tasks.enqueue(name, timeout=TASK_TIMEOUT, **kwargs)

    async def run_task(self, name: str, wait: float, **kwargs: Any) -> TaskResult:
        """放入 tasks 佇列並最多等 wait 秒；沒等到時工作仍在背景繼續。失敗時丟出 RuntimeError。"""
        job = await self.tasks.enqueue(name, timeout=TASK_TIMEOUT, **kwargs)
        assert job is not None
        await job.refresh(until_complete=wait)
        if job.status == Status.COMPLETE:
            return TaskResult(True, job.result)
        if job.status in (Status.FAILED, Status.ABORTED):
            raise RuntimeError(f'背景工作 {name} 失敗：{job.error}')
        return TaskResult(False, None)
