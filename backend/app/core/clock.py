"""時間：一律 UTC；字串格式與 JavaScript 的 Date.toISOString() 相同（毫秒、結尾 Z）。"""

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    """2026-10-07T01:02:03.456Z"""
    u = dt.astimezone(UTC)
    return u.strftime('%Y-%m-%dT%H:%M:%S.') + f'{u.microsecond // 1000:03d}Z'


def parse_iso(text: str) -> datetime:
    return datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(UTC)
