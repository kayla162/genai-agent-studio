"""job.finished 的內容：由任務列的欄位與任務的全部事件（payload，不含 seq、ts）組成。

每個模板挑一張候選：job.completed 指定的最佳候選優先，其次為已審查的候選中分數最高者（同分取較晚的一輪）。
needs_review 沒有 job.completed，所以一樣依分數挑選；failed、cancelled 通常沒有候選，best 為 None。
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal, TypedDict

from app.contract import TEMPLATE_IDS, HistoryEntry

EVENT = 'job.finished'


class Candidate(TypedDict):
    renderId: str
    templateId: str
    round: int
    variant: int
    score: int | None
    passed: bool | None
    #: 伺服器端繪製的審查用海報（/files/...）；REVIEW_MODE=sim 時為 None
    imageUrl: str | None


def _collect(events: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Candidate], dict[str, list[dict[str, Any]]]]:
    found: dict[str, Candidate] = {}
    checks: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        if e['type'] == 'render.completed':
            for r in e['renders']:
                found[r['id']] = Candidate(
                    renderId=r['id'],
                    templateId=r['templateId'],
                    round=r['round'],
                    variant=r['variant'],
                    score=None,
                    passed=None,
                    imageUrl=None,
                )
                checks[r['id']] = []
        elif e['type'] == 'review.check' and e['renderId'] in found:
            checks[e['renderId']].append(e['check'])
        elif e['type'] == 'review.completed' and e['renderId'] in found:
            c = found[e['renderId']]
            c['score'], c['passed'], c['imageUrl'] = e['score'], e['passed'], e.get('image')
    return found, checks


def candidates(best_render_ids: Mapping[Any, str], events: Iterable[Mapping[str, Any]]) -> list[Candidate]:
    found, _ = _collect(events)
    by_template: dict[str, Candidate] = {}
    for c in found.values():
        if c['score'] is None:
            continue
        current = by_template.get(c['templateId'])
        if current is None or (c['score'], c['round']) >= (current['score'] or 0, current['round']):
            by_template[c['templateId']] = c
    for template, render_id in best_render_ids.items():
        if render_id in found:
            by_template[template] = found[render_id]
    return [by_template[t] for t in TEMPLATE_IDS if t in by_template]


def best(picked: list[Candidate]) -> Candidate | None:
    return max(picked, key=lambda c: c['score'] or 0, default=None)


def studio_url(base: str, job_id: str) -> str:
    return f'{base.rstrip("/")}/agent?job={job_id}'


def _reason(events: Sequence[Mapping[str, Any]]) -> str | None:
    for e in reversed(events):
        if e['type'] in ('job.failed', 'job.needs_review'):
            return str(e['reason'])
    return None


def build_job_finished(
    *,
    webhook_id: str,
    job_id: str,
    stage: str,
    round: int,
    job_input: Mapping[str, Any],
    client_ref: str | None,
    parent_job_id: str | None,
    best_render_ids: Mapping[str, str],
    events: Sequence[Mapping[str, Any]],
    studio_base_url: str,
    finished_at: str,
) -> dict[str, Any]:
    picked = candidates(best_render_ids, events)
    top = best(picked)
    _, checks = _collect(events)
    failed = [
        {'id': c['id'], 'name': c['name'], 'status': c['status'], 'value': c['value']}
        for c in (checks.get(top['renderId'], []) if top else [])
        if c['status'] != 'pass'
    ]
    return {
        'event': EVENT,
        'webhookId': webhook_id,
        'jobId': job_id,
        'clientRef': client_ref,
        'parentJobId': parent_job_id,
        'stage': stage,
        'round': round,
        'brandId': job_input['brandId'],
        'productId': job_input['productId'],
        'brief': job_input['brief'],
        'best': top,
        'renders': picked,
        'failedChecks': failed,
        'reason': _reason(events),
        'studioUrl': studio_url(studio_base_url, job_id),
        'finishedAt': finished_at,
    }


def minimal_job_finished(
    *,
    webhook_id: str,
    job_id: str,
    stage: str,
    round: int,
    client_ref: str | None,
    studio_base_url: str,
    finished_at: str,
    error: str,
) -> dict[str, Any]:
    """build_job_finished 失敗時的替代內容：只用任務列本身的欄位，並以 payloadError 說明原因（收端到 Studio 查看）。"""
    return {
        'event': EVENT,
        'webhookId': webhook_id,
        'jobId': job_id,
        'clientRef': client_ref,
        'stage': stage,
        'round': round,
        'studioUrl': studio_url(studio_base_url, job_id),
        'finishedAt': finished_at,
        'payloadError': error,
    }


#: 選定海報（Studio 的選定或自動化 API 的核准）：n8n 下載定稿、上傳 R2 並推送
HISTORY_SELECTED = 'history.selected'


def history_poster_path(history_id: str) -> str:
    """定稿 PNG 的 api 路徑（n8n 以 AUTOMATION_API_URL 加上這個路徑下載）。"""
    return f'/api/history/{history_id}/poster.png'


def build_history_selected(
    *,
    webhook_id: str,
    entry: HistoryEntry,
    source: Literal['studio', 'automation'],
    client_ref: str | None,
    studio_base_url: str,
) -> dict[str, Any]:
    return {
        'event': HISTORY_SELECTED,
        'webhookId': webhook_id,
        'historyId': entry.id,
        'jobId': entry.job_id,
        'renderId': entry.render.id,
        'templateId': entry.template_id,
        'brandId': entry.brand_id,
        'productId': entry.product_id,
        'brief': entry.input.brief,
        'score': entry.render.score,
        'source': source,
        'clientRef': client_ref,
        'posterUrl': history_poster_path(entry.id),
        'studioUrl': studio_url(studio_base_url, entry.job_id),
        'selectedAt': entry.selected_at,
    }
