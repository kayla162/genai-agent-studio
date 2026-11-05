"""webhook 的 body 與簽章：簽的是實際送出的位元組（timestamp + "." + body），接收端要用原始 body 驗證。"""

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any


def encode(payload: Mapping[str, Any]) -> bytes:
    """緊湊的 UTF-8 JSON（不轉義中文），依原本的鍵順序。"""
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f'{timestamp}.'.encode() + body, hashlib.sha256)
    return f'v1={mac.hexdigest()}'


def headers(*, webhook_id: str, event: str, secret: str, timestamp: int, body: bytes) -> dict[str, str]:
    return {
        'Content-Type': 'application/json; charset=utf-8',
        'User-Agent': 'genai-agent-webhook/1',
        'X-Webhook-Id': webhook_id,
        'X-Webhook-Event': event,
        'X-Webhook-Timestamp': str(timestamp),
        'X-Webhook-Signature': sign(secret, timestamp, body),
    }
