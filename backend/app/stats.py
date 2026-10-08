"""成效儀表板：web/src/lib/stats/dashboard.ts 的移植，結果必須完全相同（tests/test_stats.py）。

只統計已結束的任務（完成或需人工審核）；取消與失敗的不列入。事件保持原始 JSON。
浮點數一律依序相加（_fsum）：Python 3.12 起 sum() 對浮點數做補償加總，結果可能和 JavaScript 的 reduce 不同。
"""

from typing import Any

from app.contract import (
    CHECK_IDS,
    CheckFailureStat,
    CheckId,
    DashboardStats,
    JobSnapshot,
    JobStat,
    RerankHitStat,
)
from app.core.clock import parse_iso

#: 估算單價（美元）；Plan 5、6 改用實際用量
UNIT_COST_USD = {
    'llm_call': 0.0006,
    'rerank': 0.0002,
    'comfy_image': 0.0042,
    'ideogram_image': 0.06,
    'vlm_review': 0.0011,
}
RECENT = 8

Message = dict[str, Any]


def _fsum(values: list[float]) -> float:
    total = 0.0
    for v in values:
        total += v
    return total


def _count(events: list[Message], kind: str) -> int:
    return sum(1 for e in events if e['type'] == kind)


def _render_count(events: list[Message]) -> int:
    return sum(len(e['renders']) for e in events if e['type'] == 'render.completed')


def job_cost(snap: JobSnapshot) -> float:
    events = snap.events
    image = UNIT_COST_USD['ideogram_image'] if snap.summary.input.engine == 'ideogram' else UNIT_COST_USD['comfy_image']
    llm_calls = _count(events, 'brief.parsed') + _count(events, 'prompt.generated') + _count(events, 'rewrite.started')
    return (
        UNIT_COST_USD['llm_call'] * llm_calls
        + UNIT_COST_USD['rerank'] * _count(events, 'rag.reranked')
        + image * _render_count(events)
        + UNIT_COST_USD['vlm_review'] * _count(events, 'review.completed')
    )


def job_stat(snap: JobSnapshot) -> JobStat | None:
    s = snap.summary
    if not s.finished or s.stage not in ('done', 'needs_review'):
        return None
    first, last = (snap.events[0], snap.events[-1]) if snap.events else (None, None)
    duration = parse_iso(last['ts']) - parse_iso(first['ts']) if first and last else None
    return JobStat(
        job_id=s.id,
        brand_id=s.input.brand_id,
        created_at=s.created_at,
        outcome=s.stage,
        templates=len(s.input.template_ids),
        rounds=s.round,
        renders=_render_count(snap.events),
        delivered=len(s.best_render_ids),
        duration_ms=round(duration.total_seconds() * 1000) if duration is not None else 0,
        cost_usd=job_cost(snap),
    )


def _first_round_passed(events: list[Message]) -> int:
    template_of: dict[str, str] = {}
    passed: set[str] = set()
    for e in events:
        if e['type'] == 'render.completed' and e['round'] == 1:
            for r in e['renders']:
                template_of[r['id']] = r['templateId']
        if e['type'] == 'review.completed' and e['round'] == 1 and e['passed']:
            t = template_of.get(e['renderId'])
            if t:
                passed.add(t)
    return len(passed)


def rerank_hit_curve(events: list[Message]) -> tuple[list[float], list[float]] | None:
    """前 k 筆（k = 1…n）涵蓋審查未通過項目所引用規範的比例；沒有可比較的引用時回傳 None。"""
    retrieved = next((e for e in events if e['type'] == 'rag.retrieved'), None)
    reranked = next((e for e in events if e['type'] == 'rag.reranked'), None)
    if retrieved is None or reranked is None:
        return None
    vector_order = [h['chunkId'] for h in sorted(retrieved['hits'], key=lambda h: -h['vectorScore'])]
    rerank_order = [h['chunkId'] for h in reranked['hits']]
    cited = {
        e['check']['ragRef']
        for e in events
        if e['type'] == 'review.check' and e['check']['status'] != 'pass' and e['check']['ragRef']
    }
    relevant = [i for i in vector_order if i in cited]
    if not relevant:
        return None

    def curve(order: list[str]) -> list[float]:
        return [sum(1 for i in relevant if i in order[: k + 1]) / len(relevant) for k in range(len(order))]

    return curve(vector_order), curve(rerank_order)


def _check_failures(snaps: list[JobSnapshot]) -> list[CheckFailureStat]:
    stats: dict[CheckId, CheckFailureStat] = {}
    for snap in snaps:
        for e in snap.events:
            if e['type'] != 'review.check':
                continue
            c = e['check']
            s = stats.setdefault(
                c['id'], CheckFailureStat(check_id=c['id'], name=c['name'], kind=c['kind'], fail=0, warn=0)
            )
            if c['status'] == 'fail':
                s.fail += 1
            if c['status'] == 'warn':
                s.warn += 1
    return [stats[i] for i in CHECK_IDS if i in stats]


def _rerank_hits(snaps: list[JobSnapshot]) -> list[RerankHitStat]:
    curves = [c for c in (rerank_hit_curve(s.events) for s in snaps) if c is not None]
    if not curves:
        return []
    n = min(len(v) for v, _ in curves)

    def avg(values: list[float]) -> float:
        return _fsum(values) / len(curves)

    return [
        RerankHitStat(k=i + 1, vector=avg([v[i] for v, _ in curves]), rerank=avg([r[i] for _, r in curves]))
        for i in range(n)
    ]


def _mean(values: list[float]) -> float:
    return _fsum(values) / len(values) if values else 0


def dashboard_stats(snaps: list[JobSnapshot]) -> DashboardStats:
    finished = [(snap, stat) for snap in snaps if (stat := job_stat(snap)) is not None]
    stats = [s for _, s in finished]
    templates = sum(s.templates for s in stats)
    delivered = sum(s.delivered for s in stats)
    cost = _fsum([s.cost_usd for s in stats])
    finished_snaps = [snap for snap, _ in finished]
    return DashboardStats(
        jobs=len(stats),
        renders=sum(s.renders for s in stats),
        pass_rate=sum(1 for s in stats if s.outcome == 'done') / len(stats) if stats else 0,
        first_pass_rate=sum(_first_round_passed(s.events) for s in finished_snaps) / templates if templates else 0,
        avg_retries=_mean([s.rounds - 1 for s in stats]),
        avg_duration_ms=_mean([s.duration_ms for s in stats]),
        cost_per_image=cost / delivered if delivered else None,
        check_failures=_check_failures(finished_snaps),
        rerank_hits=_rerank_hits(finished_snaps),
        recent=sorted(stats, key=lambda s: s.created_at, reverse=True)[:RECENT],
    )
