"""SAQ 佇列：api 放入工作，worker 執行。

- jobs：生圖任務，一次只執行一個（只有一張 GPU）；key 為任務 id，同一個任務不會重複排入。
- tasks：文件上傳、回寫歷史切塊，最多同時兩個，不必等生圖任務。
- cutouts：商品照去背，一次一個（推論時約 8 GB 記憶體，Docker 實測尖峰約 7.6 GiB）；大量新增商品時不會擋住文件上傳。
"""

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Any

from saq import Queue
from saq.job import Status

JOBS = 'jobs'
TASKS = 'tasks'
CUTOUTS = 'cutouts'
#: tasks 佇列裡單一工作最長的執行時間（秒）
TASK_TIMEOUT = 600


def ingest_channel(task_id: str) -> str:
    """品牌文件上傳的進度：worker 發布到這個 Redis 頻道，api 以 NDJSON 串流轉給前端。"""
    return f'ingest:{task_id}'


def cutout_key(product_id: str, photo_url: str) -> str:
    """同一張照片的去背還在排隊或執行時不會重複排入；換了照片 key 就不同，一定會排入。"""
    return f'cutout:{product_id}:{hashlib.sha256(photo_url.encode()).hexdigest()[:8]}'


class TaskFailed(RuntimeError):
    """背景工作失敗或被中止（SAQ 的 FAILED、ABORTED）。"""


@dataclass(frozen=True)
class TaskResult:
    #: 在等待時間內完成
    completed: bool
    result: Any


class Queues:
    def __init__(self, redis_url: str) -> None:
        self.jobs = Queue.from_url(redis_url, name=JOBS)
        self.tasks = Queue.from_url(redis_url, name=TASKS)
        self.cutouts = Queue.from_url(redis_url, name=CUTOUTS)

    async def connect(self) -> None:
        for queue in (self.jobs, self.tasks, self.cutouts):
            await queue.connect()

    async def disconnect(self) -> None:
        for queue in (self.jobs, self.tasks, self.cutouts):
            await queue.disconnect()

    async def enqueue_job(self, job_id: str) -> None:
        """生圖可能花上數十分鐘，不設逾時（流程內各步驟有自己的逾時）。"""
        await self.jobs.enqueue('run_job', key=job_id, timeout=0, job_id=job_id)

    async def enqueue_cutout(self, product_id: str, photo_url: str) -> bool:
        """第一次下載模型（約 1 GB）可能花很久，佇列不設逾時；推論另有自己的逾時（見 worker）。
        回傳是否新排入：同一張照片的工作還在排隊或執行時，SAQ 以 key 去重，回傳 False。"""
        job = await self.cutouts.enqueue(
            'cutout',
            key=cutout_key(product_id, photo_url),
            timeout=0,
            product_id=product_id,
            photo_url=photo_url,
        )
        return job is not None

    async def release_orphans(self, reason: str) -> list[str]:
        """放掉前一個 worker 留下的 ACTIVE 紀錄（生圖與去背），回傳被放掉的 key。

        worker 被強制終止時，紀錄會永遠停在執行中：系統狀態一直算它執行中，
        同一個任務也無法重新排入（key 相同會被當成重複）。
        只在 worker 啟動前呼叫：只有一個 worker 行程，這時候 ACTIVE 的紀錄一定屬於已經結束的行程。
        """
        released: list[str] = []
        for queue in (self.jobs, self.cutouts):
            # 先收集再放掉：放掉會改寫紀錄，不要一邊掃描一邊改
            orphans = [job async for job in queue.iter_jobs(statuses=[Status.ACTIVE])]
            for job in orphans:
                await queue.finish(job, Status.ABORTED, error=reason)
            released += [job.key for job in orphans]
        return released

    async def enqueue_task(self, function: str, /, **kwargs: Any) -> None:
        await self.tasks.enqueue(function, timeout=TASK_TIMEOUT, **kwargs)

    async def run_task(self, function: str, /, wait: float, **kwargs: Any) -> TaskResult:
        """放入 tasks 佇列並最多等 wait 秒；沒等到時工作仍在背景繼續。失敗或被中止時丟出 TaskFailed。"""
        job = await self.tasks.enqueue(function, timeout=TASK_TIMEOUT, **kwargs)
        assert job is not None
        try:
            # until_complete=0 是一直等；SAQ 自己的逾時只算單一則通知的間隔，總等待時間改由 asyncio.timeout 控制
            async with asyncio.timeout(wait):
                await job.refresh(until_complete=0)
        except TimeoutError:
            # 等待時間到了不是錯誤（工作仍在背景繼續）；最後再讀一次狀態，
            # 因為完成通知可能發生在讀取狀態與開始訂閱之間而漏掉
            await job.refresh()
        if job.status == Status.COMPLETE:
            return TaskResult(True, job.result)
        if job.status in (Status.FAILED, Status.ABORTED):
            raise TaskFailed(f'背景工作 {function} 失敗：{job.error}')
        return TaskResult(False, None)
