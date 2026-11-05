"""自動化 API：token 驗證、伺服器端拆解需求並補齊預設值、client_ref 存進任務。需要 composer。"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.contract import JobInput, ParsedBrief
from app.db.models import JobRow
from tests.conftest import LiveApi
from tests.fixtures import load_fixture

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
