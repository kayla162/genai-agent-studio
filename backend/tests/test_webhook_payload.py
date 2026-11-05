"""job.finished payload：每個模板挑一張、最佳候選、未通過的檢查、失敗原因與 studioUrl。"""

from typing import Any

from app.webhooks.payload import EVENT, best, build_job_finished, candidates, studio_url

INPUT = {'brandId': 'selune', 'productId': 'prod_selune_serum', 'brief': '週年慶買一送一'}


def render(id_: str, template: str, round_: int, variant: int = 0) -> dict[str, Any]:
    return {'id': id_, 'templateId': template, 'round': round_, 'variant': variant}


def check(id_: str, status: str) -> dict[str, Any]:
    return {
        'id': id_,
        'name': f'檢查 {id_}',
        'kind': 'rule',
        'rule': 'r',
        'value': 'v',
        'status': status,
        'target': None,
        'ragRef': None,
    }


EVENTS: list[dict[str, Any]] = [
    {'type': 'render.completed', 'round': 1, 'renders': [render('r1', 'story', 1), render('r2', 'ig-post', 1)]},
    {'type': 'review.check', 'round': 1, 'renderId': 'r1', 'check': check('banned_words', 'fail')},
    {
        'type': 'review.completed',
        'round': 1,
        'renderId': 'r1',
        'score': 60,
        'passed': False,
        'image': '/files/jobs/j/r1.png',
    },
    {
        'type': 'review.completed',
        'round': 1,
        'renderId': 'r2',
        'score': 92,
        'passed': True,
        'image': '/files/jobs/j/r2.png',
    },
    {'type': 'render.completed', 'round': 2, 'renders': [render('r3', 'story', 2)]},
    {'type': 'review.check', 'round': 2, 'renderId': 'r3', 'check': check('whitespace', 'warn')},
    {'type': 'review.check', 'round': 2, 'renderId': 'r3', 'check': check('contrast', 'pass')},
    {
        'type': 'review.completed',
        'round': 2,
        'renderId': 'r3',
        'score': 95,
        'passed': True,
        'image': '/files/jobs/j/r3.png',
    },
]


def test_candidates_pick_one_per_template_in_template_order() -> None:
    picked = candidates({}, EVENTS)
    assert [c['renderId'] for c in picked] == ['r2', 'r3']  # ig-post 在 story 之前（TEMPLATE_IDS 的順序）
    assert picked[1] == {
        'renderId': 'r3',
        'templateId': 'story',
        'round': 2,
        'variant': 0,
        'score': 95,
        'passed': True,
        'imageUrl': '/files/jobs/j/r3.png',
    }


def test_best_render_ids_win_over_scores() -> None:
    picked = candidates({'story': 'r1'}, EVENTS)
    assert [c['renderId'] for c in picked] == ['r2', 'r1']


def test_unreviewed_renders_are_skipped_and_best_is_the_highest_score() -> None:
    events = [{'type': 'render.completed', 'round': 1, 'renders': [render('r9', 'banner', 1)]}, *EVENTS]
    picked = candidates({}, events)
    assert 'r9' not in [c['renderId'] for c in picked]
    top = best(picked)
    assert top is not None and top['renderId'] == 'r3'
    assert best([]) is None


def test_studio_url() -> None:
    assert studio_url('http://127.0.0.1:3000/', 'job_1') == 'http://127.0.0.1:3000/agent?job=job_1'


def test_build_job_finished_for_a_done_job() -> None:
    data = build_job_finished(
        webhook_id='wh_1',
        job_id='job_1',
        stage='done',
        round=2,
        job_input=INPUT,
        client_ref='sheet:x:row:3',
        parent_job_id=None,
        best_render_ids={},
        events=EVENTS,
        studio_base_url='http://127.0.0.1:3000',
        finished_at='2026-11-05T10:00:00+08:00',
    )
    assert data['event'] == EVENT
    assert (data['webhookId'], data['jobId'], data['clientRef'], data['stage'], data['round']) == (
        'wh_1',
        'job_1',
        'sheet:x:row:3',
        'done',
        2,
    )
    assert (data['brandId'], data['productId'], data['brief']) == ('selune', 'prod_selune_serum', '週年慶買一送一')
    assert data['best']['renderId'] == 'r3'
    assert [r['renderId'] for r in data['renders']] == ['r2', 'r3']
    assert data['failedChecks'] == [{'id': 'whitespace', 'name': '檢查 whitespace', 'status': 'warn', 'value': 'v'}]
    assert data['reason'] is None
    assert data['studioUrl'] == 'http://127.0.0.1:3000/agent?job=job_1'
    assert data['finishedAt'] == '2026-11-05T10:00:00+08:00'
    assert list(data) == [
        'event',
        'webhookId',
        'jobId',
        'clientRef',
        'parentJobId',
        'stage',
        'round',
        'brandId',
        'productId',
        'brief',
        'best',
        'renders',
        'failedChecks',
        'reason',
        'studioUrl',
        'finishedAt',
    ]


def test_build_job_finished_for_failed_and_needs_review_jobs() -> None:
    common: dict[str, Any] = {
        'webhook_id': 'wh_2',
        'job_id': 'job_2',
        'round': 1,
        'job_input': INPUT,
        'client_ref': None,
        'parent_job_id': 'job_1',
        'best_render_ids': {},
        'studio_base_url': 'http://h',
        'finished_at': 't',
    }
    failed = build_job_finished(
        stage='failed', events=[{'type': 'job.failed', 'jobId': 'job_2', 'reason': 'composer 沒有回應'}], **common
    )
    assert (failed['best'], failed['renders'], failed['failedChecks']) == (None, [], [])
    assert (failed['reason'], failed['parentJobId']) == ('composer 沒有回應', 'job_1')
    review = build_job_finished(
        stage='needs_review',
        events=[*EVENTS, {'type': 'job.needs_review', 'jobId': 'job_2', 'reason': '已達最大重試次數'}],
        **common,
    )
    assert review['best']['renderId'] == 'r3'
    assert review['reason'] == '已達最大重試次數'
