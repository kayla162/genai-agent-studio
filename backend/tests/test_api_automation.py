"""自動化 API：token 驗證、伺服器端拆解需求並補齊預設值、client_ref 存進任務。需要 composer。"""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.contract import JobInput, ParsedBrief
from app.core.clock import utc_now
from app.db.models import AutomationRequestRow, HistoryRow, JobRow
from tests.conftest import LiveApi
from tests.fixtures import load_fixture
from tests.test_api_jobs import stream

TOKEN = 't' * 32
AUTH = {'Authorization': f'Bearer {TOKEN}'}
#: 與 test_api_jobs 相同的劇本：SimAgent 對這句需求的拆解結果就是劇本的 parsedBrief
FIXTURE = load_fixture('timelines/selune-retry.json')['input']
BRIEF = {'brandId': FIXTURE['brandId'], 'productId': FIXTURE['productId'], 'brief': FIXTURE['brief']}


@pytest.fixture
async def automation(api: LiveApi) -> AsyncIterator[LiveApi]:
    api.services.settings.automation_token = SecretStr(TOKEN)
    yield api
    api.services.settings.automation_token = SecretStr('')


async def job_row(api: LiveApi, job_id: str) -> JobRow:
    async with api.services.db.session() as s:
        row = await s.scalar(select(JobRow).where(JobRow.id == job_id))
        assert row is not None
        return row


async def test_disabled_without_a_token(api: LiveApi) -> None:
    res = await api.http.post('/api/automation/jobs', json=BRIEF, headers=AUTH)
    assert res.status_code == 404


@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Bearer wrong'}, {'Authorization': f'Basic {TOKEN}'}])
async def test_rejects_missing_or_wrong_tokens(automation: LiveApi, headers: dict[str, str]) -> None:
    res = await automation.http.post('/api/automation/jobs', json=BRIEF, headers=headers)
    assert res.status_code == 401
    assert res.json() == {'error': {'code': 'unauthorized', 'message': '缺少或錯誤的 automation token'}}
    assert TOKEN not in res.text


async def test_create_job_fills_in_the_defaults(automation: LiveApi) -> None:
    res = await automation.http.post(
        '/api/automation/jobs', json={**BRIEF, 'clientRef': 'sheet:abc:row:2'}, headers=AUTH
    )
    assert res.status_code == 201
    row = await job_row(automation, res.json()['jobId'])
    assert (row.stage, row.client_ref, row.parent_job_id, row.reviewer_feedback) == (
        'queued',
        'sheet:abc:row:2',
        None,
        None,
    )
    inp = JobInput.model_validate(row.input)
    assert inp.brief == BRIEF['brief']
    assert inp.template_ids == ['ig-post', 'story', 'ecom-main']
    assert (inp.variants_per_template, inp.max_retries, inp.visual_style_id) == (2, 2, None)
    assert inp.parsed_brief == ParsedBrief.model_validate(FIXTURE['parsedBrief'])
    options = (await automation.http.get('/api/options')).json()
    assert (inp.llm, inp.vlm, inp.engine) == (options['llm'][0], options['vlm'][0], options['engines'][0])


async def test_create_job_with_explicit_options(automation: LiveApi) -> None:
    body: dict[str, Any] = {**BRIEF, 'templateIds': ['banner'], 'variantsPerTemplate': 1}
    res = await automation.http.post('/api/automation/jobs', json=body, headers=AUTH)
    inp = JobInput.model_validate((await job_row(automation, res.json()['jobId'])).input)
    assert (inp.template_ids, inp.variants_per_template) == (['banner'], 1)


async def test_create_job_reports_invalid_input(automation: LiveApi) -> None:
    res = await automation.http.post('/api/automation/jobs', json={**BRIEF, 'productId': 'nope'}, headers=AUTH)
    assert res.json() == {'error': {'code': 'invalid', 'message': '找不到商品：nope'}}
    res = await automation.http.post('/api/automation/jobs', json={**BRIEF, 'brief': ''}, headers=AUTH)
    assert res.status_code == 400


@pytest.mark.parametrize(
    ('extra', 'message'),
    [
        ({'variantsPerTemplate': 9}, '每個模板的候選張數需為 1–8'),
        ({'variantsPerTemplate': 0}, '每個模板的候選張數需為 1–8'),
        ({'templateIds': []}, '至少要選一個通路模板'),
        ({'templateIds': ['story', 'story']}, '通路模板不可重複'),
    ],
)
async def test_create_job_validates_the_selection_before_the_paid_parse(
    automation: LiveApi, monkeypatch: pytest.MonkeyPatch, extra: dict[str, Any], message: str
) -> None:
    calls: list[str] = []

    async def counting_parse(*args: Any, **kwargs: Any) -> ParsedBrief:
        calls.append('parse')
        raise AssertionError('不該呼叫需求拆解')

    monkeypatch.setattr('app.api.automation.parse_text', counting_parse)
    res = await automation.http.post('/api/automation/jobs', json={**BRIEF, **extra}, headers=AUTH)
    assert res.status_code == 400
    assert res.json() == {'error': {'code': 'invalid', 'message': message}}
    assert calls == []
    async with automation.services.db.session() as s:
        assert (await s.scalars(select(JobRow))).all() == []


@pytest.fixture
async def running(automation: LiveApi) -> AsyncIterator[LiveApi]:
    """整個測試期間 worker 都在執行：任務跑得完，選定後的歷史回寫也不必等到逾時。"""
    async with automation.worker(speed=0):
        yield automation


async def finished_job(api: LiveApi, **extra: Any) -> str:
    """以自動化 API 建立任務並等它跑完（模擬模式、不等待時間軸；需要 running fixture）。"""
    res = await api.http.post('/api/automation/jobs', json={**BRIEF, 'templateIds': ['story'], **extra}, headers=AUTH)
    job_id: str = res.json()['jobId']
    await stream(api, job_id)
    return job_id


async def test_approve_defaults_to_the_best_render(running: LiveApi) -> None:
    automation = running
    job_id = await finished_job(automation)
    res = await automation.http.post(f'/api/automation/jobs/{job_id}/approve', json={}, headers=AUTH)
    assert res.status_code == 201
    entry = res.json()
    snap = (await automation.http.get(f'/api/jobs/{job_id}')).json()
    assert entry['render']['id'] == snap['summary']['bestRenderIds']['story']
    assert entry['copy'] == entry['render']['spec']['copy']


async def test_approve_a_specific_render_and_reject_unknown_ones(running: LiveApi) -> None:
    automation = running
    job_id = await finished_job(automation)
    snap = (await automation.http.get(f'/api/jobs/{job_id}')).json()
    first = next(e for e in snap['events'] if e['type'] == 'render.completed')['renders'][0]['id']
    res = await automation.http.post(f'/api/automation/jobs/{job_id}/approve', json={'renderId': first}, headers=AUTH)
    assert res.json()['render']['id'] == first
    res = await automation.http.post(f'/api/automation/jobs/{job_id}/approve', json={'renderId': 'nope'}, headers=AUTH)
    assert res.json() == {'error': {'code': 'not_found', 'message': '找不到候選圖：nope'}}


async def test_approve_needs_a_finished_job_with_renders(automation: LiveApi) -> None:
    res = await automation.http.post('/api/automation/jobs', json=BRIEF, headers=AUTH)  # 沒有 worker：停在排隊中
    job_id = res.json()['jobId']
    res = await automation.http.post(f'/api/automation/jobs/{job_id}/approve', json={}, headers=AUTH)
    assert res.json() == {'error': {'code': 'conflict', 'message': '任務還沒有可選的候選圖（目前階段：queued）'}}


async def test_revise_creates_a_child_job(running: LiveApi) -> None:
    automation = running
    job_id = await finished_job(automation, clientRef='sheet:abc:row:5')
    res = await automation.http.post(
        f'/api/automation/jobs/{job_id}/revise', json={'feedback': '標題改成限時三天'}, headers=AUTH
    )
    assert res.status_code == 201
    child = await job_row(automation, res.json()['jobId'])
    parent = await job_row(automation, job_id)
    assert (child.parent_job_id, child.reviewer_feedback, child.client_ref) == (
        job_id,
        '標題改成限時三天',
        'sheet:abc:row:5',
    )
    assert child.input == parent.input


async def test_revise_carries_the_feedback_along_the_chain(running: LiveApi) -> None:
    automation = running
    job_id = await finished_job(automation)
    res = await automation.http.post(f'/api/automation/jobs/{job_id}/revise', json={'feedback': 'A'}, headers=AUTH)
    first = res.json()['jobId']
    await stream(automation, first)
    res = await automation.http.post(f'/api/automation/jobs/{first}/revise', json={'feedback': 'B'}, headers=AUTH)
    assert (await job_row(automation, res.json()['jobId'])).reviewer_feedback == 'A；B'


async def test_revise_needs_a_finished_job(automation: LiveApi) -> None:
    job_id = (await automation.http.post('/api/automation/jobs', json=BRIEF, headers=AUTH)).json()['jobId']
    res = await automation.http.post(f'/api/automation/jobs/{job_id}/revise', json={'feedback': 'x'}, headers=AUTH)
    assert res.json() == {'error': {'code': 'conflict', 'message': '任務還沒結束，不能退回'}}


async def test_revise_stops_after_three_revisions(running: LiveApi) -> None:
    automation = running
    job_id = await finished_job(automation)
    for n in range(3):
        res = await automation.http.post(
            f'/api/automation/jobs/{job_id}/revise', json={'feedback': f'第 {n + 1} 次'}, headers=AUTH
        )
        assert res.status_code == 201
        job_id = res.json()['jobId']
        await stream(automation, job_id)
    res = await automation.http.post(
        f'/api/automation/jobs/{job_id}/revise', json={'feedback': '第 4 次'}, headers=AUTH
    )
    assert res.json() == {'error': {'code': 'conflict', 'message': '已退回 3 次，請到 Studio 手動處理'}}


async def test_idempotency_key_replays_the_first_response(running: LiveApi) -> None:
    automation = running
    job_id = await finished_job(automation)
    headers = {**AUTH, 'Idempotency-Key': 'wh_abc:revise'}
    first = await automation.http.post(f'/api/automation/jobs/{job_id}/revise', json={'feedback': 'a'}, headers=headers)
    again = await automation.http.post(f'/api/automation/jobs/{job_id}/revise', json={'feedback': 'a'}, headers=headers)
    assert (first.status_code, again.status_code) == (201, 201)
    assert first.json() == again.json()
    async with automation.services.db.session() as s:
        children = list(await s.scalars(select(JobRow).where(JobRow.parent_job_id == job_id)))
    assert len(children) == 1
    headers = {**AUTH, 'Idempotency-Key': 'wh_abc:approve'}
    for _ in range(2):
        await automation.http.post(f'/api/automation/jobs/{job_id}/approve', json={}, headers=headers)
    async with automation.services.db.session() as s:
        assert len(list(await s.scalars(select(HistoryRow).where(HistoryRow.job_id == job_id)))) == 1


async def test_failed_requests_release_the_idempotency_key(automation: LiveApi) -> None:
    headers = {**AUTH, 'Idempotency-Key': 'k1'}
    res = await automation.http.post('/api/automation/jobs/job_nope/approve', json={}, headers=headers)
    assert res.status_code == 404
    async with automation.services.db.session() as s:
        assert await s.get(AutomationRequestRow, ('k1', 'approve')) is None


async def test_old_idempotency_keys_are_removed(running: LiveApi) -> None:
    automation = running
    async with automation.services.db.session() as s:
        s.add(
            AutomationRequestRow(
                key='old', action='approve', job_id='j', response={}, created_at=utc_now() - timedelta(days=8)
            )
        )
        await s.commit()
    job_id = await finished_job(automation)
    await automation.http.post(
        f'/api/automation/jobs/{job_id}/approve', json={}, headers={**AUTH, 'Idempotency-Key': 'new'}
    )
    async with automation.services.db.session() as s:
        assert await s.get(AutomationRequestRow, ('old', 'approve')) is None
        assert await s.get(AutomationRequestRow, ('new', 'approve')) is not None
