"""測試用的 Gemini：依呼叫種類從佇列取出預先寫好的結果（Pydantic 物件、dict 或例外），並記錄收到的呼叫。"""

from typing import Any

from pydantic import BaseModel

from app.adapters.gemini import GeminiCall
from app.pipeline.ports import RunContext


class FakeGemini:
    def __init__(self, **responses: list[Any]) -> None:
        self.queues = {kind: list(items) for kind, items in responses.items()}
        self.calls: list[GeminiCall[Any]] = []

    async def generate[T: BaseModel](self, call: GeminiCall[T], run: RunContext) -> T:
        self.calls.append(call)
        queue = self.queues.get(call.kind)
        if not queue:
            raise AssertionError(f'FakeGemini 沒有準備 {call.kind} 的回應（第 {len(self.calls)} 次呼叫）')
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        data = item.model_dump(by_alias=True, mode='json') if isinstance(item, BaseModel) else item
        return call.schema.model_validate(data)

    def calls_of(self, kind: str) -> list[GeminiCall[Any]]:
        return [c for c in self.calls if c.kind == kind]
