"""api：需求拆解、建立任務、WebSocket 串流與補送、取消、選定海報、歷史紀錄、成效儀表板。需要 composer。"""

import asyncio
import json
import re
from typing import Any

import pytest
from saq.job import Status
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosedError

from app.adapters.gemini import NOT_CONFIGURED, GeminiClient, GeminiError
from app.api import jobs as jobs_api
from app.contract import Brand, JobStatusEvent, ParsedBrief, Product
from app.errors import BudgetExceeded
from app.settings import REPO_ROOT
from app.usage import Pricing, TokenUsage, UsageLedger, UsageScope
from tests.conftest import LiveApi
from tests.fixtures import load_fixture
from tests.test_events import DownPubSub, publish_down


def job_input(**patch: Any) -> dict[str, Any]:
    return {**load_fixture('timelines/selune-retry.json')['input'], **patch}


async def stream(api: LiveApi, job_id: str, after: int = 0) -> list[dict[str, Any]]:
    """收到伺服器關閉連線為止的所有訊息。"""
    async with asyncio.timeout(30), connect(f'{api.ws_url}/ws/jobs/{job_id}?after={after}') as ws:
        return [json.loads(m) async for m in ws]


def stages(messages: list[dict[str, Any]]) -> list[tuple[str, str | None]]:
    return [(m['type'], m.get('stage')) for m in messages]


async def test_parse_brief_matches_the_frontend(api: LiveApi) -> None:
    data = job_input()
    body = {'brandId': 'selune', 'text': data['brief'], 'productId': 'prod_selune_serum'}
    assert (await api.http.post('/api/briefs/parse', json=body)).json() == data['parsedBrief']
    unknown = await api.http.post('/api/briefs/parse', json={**body, 'productId': 'nope'})
    assert unknown.json() == {'error': {'code': 'invalid', 'message': '找不到商品：nope'}}


async def test_create_job_rejects_invalid_input(api: LiveApi) -> None:
    cases: list[tuple[dict[str, Any], str]] = [
        ({'brandId': 'nope'}, '找不到品牌：nope'),
        ({'templateIds': []}, '至少要選一個通路模板'),
        ({'templateIds': ['story', 'story']}, '通路模板不可重複'),
        ({'variantsPerTemplate': 9}, '每個模板的候選張數需為 1–8'),
        ({'maxRetries': -1}, '最大重試次數需為 0 以上的整數'),
        ({'productId': 'prod_misty_coldbrew'}, '商品不屬於所選品牌'),
        ({'llm': 'GPT-9'}, '目前不支援這個 LLM：GPT-9'),
        ({'engine': 'ideogram'}, '目前不支援這個生圖引擎：ideogram'),
    ]
    for patch, message in cases:
        res = await api.http.post('/api/jobs', json=job_input(**patch))
        assert (res.status_code, res.json()) == (400, {'error': {'code': 'invalid', 'message': message}})
    assert (await api.http.get('/api/jobs')).json() == []


async def test_create_job_fails_the_job_when_it_cannot_be_queued(
    api: LiveApi, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def down(job_id: str) -> None:
        raise ConnectionError('redis 沒有回應')

    monkeypatch.setattr(api.services.queues, 'enqueue_job', down)
    res = await api.http.post('/api/jobs', json=job_input())
    assert (res.status_code, res.json()['error']['code']) == (503, 'unavailable')
    assert res.json()['error']['message'] == '目前無法排入任務（佇列服務沒有回應），請稍後再試'
    assert 'redis 沒有回應' in caplog.text
    # 任務不能留在排隊中：之後 worker 重新啟動時會意外執行它
    [listed] = (await api.http.get('/api/jobs')).json()
    assert (listed['stage'], listed['finished']) == ('failed', True)
    events = (await api.http.get(f'/api/jobs/{listed["id"]}')).json()['events']
    assert stages(events) == [
        ('job.accepted', None),
        ('job.status', 'queued'),
        ('log', None),
        ('job.failed', None),
        ('job.status', 'failed'),
    ]
    reason = '無法排入佇列：佇列服務沒有回應'
    assert (events[2]['source'], events[2]['level'], events[2]['message']) == ('api', 'error', reason)
    assert events[3]['reason'] == reason
    assert events[4]['round'] == 0


async def test_create_job_still_answers_503_when_the_failure_events_cannot_be_written(
    api: LiveApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(job_id: str) -> None:
        raise ConnectionError('redis 沒有回應')

    append = api.services.store.append

    async def append_unless_failed(job_id: str, event: Any, **kwargs: Any) -> int | None:
        if event.type == 'job.failed':
            raise ConnectionError('資料庫沒有回應')
        return await append(job_id, event, **kwargs)

    monkeypatch.setattr(api.services.queues, 'enqueue_job', down)
    monkeypatch.setattr(api.services.store, 'append', append_unless_failed)
    res = await api.http.post('/api/jobs', json=job_input())
    assert (res.status_code, res.json()['error']['code']) == (503, 'unavailable')


async def test_create_job_keeps_a_job_the_worker_already_took_when_the_enqueue_reply_is_lost(
    api: LiveApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def lost_reply(job_id: str) -> None:
        # 排入其實成功了，worker 已經取走任務，只是回應遺失
        await api.services.store.append(job_id, JobStatusEvent(type='job.status', stage='parsing', round=0))
        raise ConnectionError('redis 沒有回應')

    monkeypatch.setattr(api.services.queues, 'enqueue_job', lost_reply)
    res = await api.http.post('/api/jobs', json=job_input())
    assert res.status_code == 201
    job_id = res.json()['jobId']
    events = (await api.http.get(f'/api/jobs/{job_id}')).json()['events']
    assert stages(events) == [('job.accepted', None), ('job.status', 'queued'), ('job.status', 'parsing')]


async def test_job_streams_every_event_and_replays_after_seq(api: LiveApi) -> None:
    async with api.worker():
        res = await api.http.post('/api/jobs', json=job_input())
        assert res.status_code == 201
        job_id = res.json()['jobId']
        messages = await stream(api, job_id)
    assert re.fullmatch(r'job_\d{8}_\d{4}_[0-9a-f]{4}', job_id)
    assert [m['seq'] for m in messages] == list(range(1, len(messages) + 1))
    assert messages[0] == {'type': 'job.accepted', 'jobId': job_id, 'seq': 1, 'ts': messages[0]['ts']}
    assert stages(messages[1:3]) == [('job.status', 'queued'), ('job.status', 'parsing')]
    assert stages(messages[-1:]) == [('job.status', 'done')]
    snap = (await api.http.get(f'/api/jobs/{job_id}')).json()
    assert snap['events'] == messages
    assert (snap['summary']['stage'], snap['summary']['round'], snap['summary']['finished']) == ('done', 2, True)
    assert [j['id'] for j in (await api.http.get('/api/jobs')).json()] == [job_id]
    # 重新連線：只補送 seq 之後的事件；任務已結束時送完就關閉
    assert await stream(api, job_id, after=len(messages) - 3) == messages[-3:]
    assert await stream(api, job_id, after=len(messages)) == []
    missing = await api.http.get('/api/jobs/job_nope')
    assert (missing.status_code, missing.json()['error']['code']) == (404, 'not_found')


async def test_websocket_streams_from_the_database_when_redis_is_down(
    api: LiveApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 訂閱與發布都失敗：事件只在資料庫，串流每秒讀取一次，任務結束後正常關閉（不是 1011）
    monkeypatch.setattr(api.services.store.redis, 'pubsub', lambda: DownPubSub(subscribe_fails=True))
    monkeypatch.setattr(api.services.store, 'publish', publish_down)
    async with api.worker():
        job_id = (await api.http.post('/api/jobs', json=job_input())).json()['jobId']
        messages = await stream(api, job_id)
    assert [m['seq'] for m in messages] == list(range(1, len(messages) + 1))
    assert stages(messages[-1:]) == [('job.status', 'done')]
    assert (await api.http.get(f'/api/jobs/{job_id}')).json()['events'] == messages


async def test_websocket_closes_with_4404_for_unknown_jobs(api: LiveApi) -> None:
    async with connect(f'{api.ws_url}/ws/jobs/job_nope') as ws:
        with pytest.raises(ConnectionClosedError) as closed:
            await ws.recv()
    assert closed.value.rcvd is not None and closed.value.rcvd.code == 4404


async def test_cancel_stops_a_running_job(api: LiveApi) -> None:
    messages: list[dict[str, Any]] = []
    async with api.worker(speed=2):
        job_id = (await api.http.post('/api/jobs', json=job_input())).json()['jobId']
        async with asyncio.timeout(30), connect(f'{api.ws_url}/ws/jobs/{job_id}') as ws:
            async for raw in ws:
                messages.append(json.loads(raw))
                if messages[-1].get('stage') == 'retrieving':
                    assert (await api.http.post(f'/api/jobs/{job_id}/cancel')).status_code == 204
    assert stages(messages[-1:]) == [('job.status', 'cancelled')]
    assert 'render.completed' not in {m['type'] for m in messages}


async def test_cancel_a_queued_job_before_the_worker_takes_it(api: LiveApi) -> None:
    job_id = (await api.http.post('/api/jobs', json=job_input())).json()['jobId']
    assert (await api.http.post(f'/api/jobs/{job_id}/cancel')).status_code == 204
    # 已結束的任務：不做任何事
    assert (await api.http.post(f'/api/jobs/{job_id}/cancel')).status_code == 204
    async with api.worker():
        # worker 取出這個任務時發現已取消，直接結束
        for _ in range(100):
            queued = await api.services.queues.jobs.job(job_id)
            if queued is not None and queued.status == Status.COMPLETE:
                break
            await asyncio.sleep(0.05)
    assert queued is not None and queued.status == Status.COMPLETE
    expected = [('job.accepted', None), ('job.status', 'queued'), ('job.status', 'cancelled')]
    assert stages((await api.http.get(f'/api/jobs/{job_id}')).json()['events']) == expected
    assert stages(await stream(api, job_id)) == expected
    assert (await api.http.post('/api/jobs/job_nope/cancel')).status_code == 404


async def test_select_a_render_then_favorite_it_and_count_the_job(api: LiveApi) -> None:
    async with api.worker():
        job_id = (await api.http.post('/api/jobs', json=job_input())).json()['jobId']
        messages = await stream(api, job_id)
        render_id = (await api.http.get(f'/api/jobs/{job_id}')).json()['summary']['bestRenderIds']['story']
        rendered = [r for m in messages if m['type'] == 'render.completed' for r in m['renders']]
        copy = next(r for r in rendered if r['id'] == render_id)['spec']['copy']
        res = await api.http.post(f'/api/jobs/{job_id}/select', json={'renderId': render_id, 'copy': copy})
        unknown = await api.http.post(f'/api/jobs/{job_id}/select', json={'renderId': 'r_nope', 'copy': copy})
    assert res.status_code == 201
    entry = res.json()
    assert (entry['jobId'], entry['templateId'], entry['render']['id'], entry['copy']) == (
        job_id,
        'story',
        render_id,
        copy,
    )
    assert (entry['render']['passed'], len(entry['render']['checks']), entry['favorite'], entry['writtenToRag']) == (
        True,
        10,
        False,
        True,
    )
    assert unknown.json() == {'error': {'code': 'not_found', 'message': '找不到候選圖：r_nope'}}
    assert (await api.http.get('/api/history', params={'brandId': 'selune'})).json() == [entry]
    # 回寫的歷史切塊列在知識庫的最後
    brands = {b['id']: b for b in (await api.http.get('/api/brands')).json()}
    last = brands['selune']['guidelineChunks'][-1]
    assert (last['id'], last['source'], last['tag']) == (f'selune#hist-{entry["id"]}', f'history/{job_id}', 'history')
    assert (await api.http.get('/api/history', params={'brandId': 'misty-isle'})).json() == []
    favorite = await api.http.patch(f'/api/history/{entry["id"]}', json={'favorite': True})
    assert favorite.json() == {**entry, 'favorite': True}
    assert (await api.http.patch('/api/history/hist_nope', json={'favorite': True})).status_code == 404
    stats = (await api.http.get('/api/stats', params={'brandId': 'selune'})).json()
    assert (stats['jobs'], stats['passRate'], stats['recent'][0]['jobId']) == (1, 1, job_id)
    assert (await api.http.get('/api/stats', params={'brandId': 'misty-isle'})).json()['jobs'] == 0


async def test_select_answers_written_to_rag_false_when_the_write_back_fails(
    api: LiveApi, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def broken(services: Any, history_id: str) -> bool:
        raise RuntimeError('向量庫（Chroma）無法連線')

    monkeypatch.setattr('app.worker.write_back', broken)
    async with api.worker():
        job_id = (await api.http.post('/api/jobs', json=job_input())).json()['jobId']
        messages = await stream(api, job_id)
        render_id = (await api.http.get(f'/api/jobs/{job_id}')).json()['summary']['bestRenderIds']['story']
        rendered = [r for m in messages if m['type'] == 'render.completed' for r in m['renders']]
        copy = next(r for r in rendered if r['id'] == render_id)['spec']['copy']
        res = await api.http.post(f'/api/jobs/{job_id}/select', json={'renderId': render_id, 'copy': copy})
    # 歷史紀錄已經建立，所以不回 500；重送也不會重複建立
    assert res.status_code == 201
    entry = res.json()
    assert entry['writtenToRag'] is False
    assert (await api.http.get('/api/history', params={'brandId': 'selune'})).json() == [entry]
    assert f'歷史回寫失敗：history_id={entry["id"]}' in caplog.text


class SlowAgent:
    """需求拆解：依 behaviour 等待、丟出錯誤或回傳結果。"""

    def __init__(self, error: Exception | None = None, delay: float = 0) -> None:
        self.error = error
        self.delay = delay

    async def parse_brief(self, brand: Brand, text: str, product: Product | None) -> ParsedBrief:
        await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        raise AssertionError('unreachable')


async def test_parse_brief_reports_gemini_failures_in_chinese(api: LiveApi, monkeypatch: pytest.MonkeyPatch) -> None:
    body = {'brandId': 'selune', 'text': '週年慶主打買一送一', 'productId': 'prod_selune_serum'}
    cases: list[tuple[SlowAgent, int, str, str]] = [
        (SlowAgent(delay=1), 503, 'unavailable', 'Gemini 沒有在 0.05 秒內完成需求拆解，請稍後再試'),
        (SlowAgent(GeminiError(NOT_CONFIGURED)), 503, 'unavailable', NOT_CONFIGURED),
        (
            SlowAgent(BudgetExceeded('本月 Gemini 費用已達上限（US$20.00）')),
            429,
            'budget_exceeded',
            '本月 Gemini 費用已達上限（US$20.00）',
        ),
    ]
    monkeypatch.setattr(jobs_api, 'BRIEF_TIMEOUT', 0.05)
    for agent, status, code, message in cases:
        monkeypatch.setattr(api.services, 'agent', agent)
        res = await api.http.post('/api/briefs/parse', json=body)
        assert (res.status_code, res.json()) == (status, {'error': {'code': code, 'message': message}})


async def test_create_job_needs_a_key_and_room_in_the_monthly_budget(
    api: LiveApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    gemini = api.services.settings.model_copy(update={'agent_mode': 'gemini', 'gemini_monthly_budget_usd': 1.0})
    monkeypatch.setattr(api.services, 'settings', gemini)
    data = job_input(llm='gemini-3.8-flash', vlm='gemini-3.8-flash')

    res = await api.http.post('/api/jobs', json=data)
    assert (res.status_code, res.json()) == (503, {'error': {'code': 'unavailable', 'message': NOT_CONFIGURED}})

    ledger = UsageLedger(api.services.db, Pricing.load(REPO_ROOT / 'pricing.yaml'), job_budget=1, monthly_budget=1)
    keyed = gemini.model_copy(update={'gemini_api_key': 'AIza-test-key-0000'})
    client = GeminiClient(keyed, ledger)
    monkeypatch.setattr(api.services, 'gemini', client)
    monkeypatch.setattr(api.services, 'ledger', ledger)
    try:
        assert (await api.http.post('/api/jobs', json=data)).status_code == 201
        # 需求拆解的用量（沒有任務）也算進每月的費用
        scope = UsageScope(job_id=None, brand_id='selune', round=None, target=None)
        await ledger.record(scope, 'brief', 'gemini-3.8-flash', TokenUsage(0, 0, 300_000, 0))
        res = await api.http.post('/api/jobs', json=data)
        assert (res.status_code, res.json()) == (
            429,
            {'error': {'code': 'budget_exceeded', 'message': '本月 Gemini 費用已達上限（US$1.00）'}},
        )
    finally:
        await client.aclose()


async def test_validation_errors_are_described_in_chinese(api: LiveApi) -> None:
    res = await api.http.post('/api/jobs', json=job_input(templateIds=['poster']))
    assert res.status_code == 400
    assert res.json()['error']['message'] == (
        '請求格式錯誤：templateIds.0：必須是 ecom-main、scene、ig-post、story、banner 其中之一'
    )
