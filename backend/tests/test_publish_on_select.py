"""選圖後發布：選定時寫入 history.selected 通知、定稿海報（選定時的文案重畫）。需要 composer。"""

import io
from collections.abc import AsyncIterator
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import select

from app.contract import HistoryEntry
from app.db.models import WebhookOutboxRow
from app.events import WebhookTarget
from app.final_poster import final_poster_path, final_render
from app.webhooks.payload import EVENT as JOB_FINISHED
from app.webhooks.payload import HISTORY_SELECTED
from tests.conftest import LiveApi
from tests.test_api_automation import (  # noqa: F401 - automation、running 是 fixture
    AUTH,
    automation,
    finished_job,
    running,
)

TARGET = WebhookTarget(studio_base_url='http://studio.test')


@pytest.fixture
async def notified(running: LiveApi) -> AsyncIterator[LiveApi]:  # noqa: F811 - running 是 fixture
    """有設定 JOB_WEBHOOK_URL：任務結束與選定都寫 outbox（測試不發送，只看 outbox）。"""
    running.services.store.webhook = TARGET
    yield running
    running.services.store.webhook = None


async def outbox(api: LiveApi, job_id: str) -> list[WebhookOutboxRow]:
    async with api.services.db.session() as s:
        query = select(WebhookOutboxRow).where(WebhookOutboxRow.job_id == job_id).order_by(WebhookOutboxRow.created_at)
        return list(await s.scalars(query))


async def best_render(api: LiveApi, job_id: str) -> dict[str, Any]:
    snap = (await api.http.get(f'/api/jobs/{job_id}')).json()
    render_id = snap['summary']['bestRenderIds']['story']
    renders = [r for e in snap['events'] if e['type'] == 'render.completed' for r in e['renders']]
    return next(r for r in renders if r['id'] == render_id)


async def test_studio_select_and_approve_each_write_a_history_selected(notified: LiveApi) -> None:
    api = notified
    job_id = await finished_job(api)
    render = await best_render(api, job_id)
    edited = {**render['spec']['copy'], 'subhead': '改過的副標'}
    studio = (await api.http.post(f'/api/jobs/{job_id}/select', json={'renderId': render['id'], 'copy': edited})).json()
    approved = (await api.http.post(f'/api/automation/jobs/{job_id}/approve', json={}, headers=AUTH)).json()

    rows = await outbox(api, job_id)
    # job.finished 一則；同一個任務選定兩次 → 兩則 history.selected
    assert [r.event for r in rows] == [JOB_FINISHED, HISTORY_SELECTED, HISTORY_SELECTED]
    first, second = rows[1].payload, rows[2].payload
    assert (first['historyId'], first['source']) == (studio['id'], 'studio')
    assert (second['historyId'], second['source']) == (approved['id'], 'automation')
    assert first == {
        'event': HISTORY_SELECTED,
        'webhookId': rows[1].id,
        'historyId': studio['id'],
        'jobId': job_id,
        'renderId': render['id'],
        'templateId': 'story',
        'brandId': studio['brandId'],
        'productId': studio['productId'],
        'brief': studio['input']['brief'],
        'score': studio['render']['score'],
        'source': 'studio',
        'clientRef': None,
        'posterUrl': f'/api/history/{studio["id"]}/poster.png',
        'studioUrl': f'http://studio.test/agent?job={job_id}',
        'selectedAt': studio['selectedAt'],
    }
    assert all(r.status == 'pending' for r in rows[1:])


async def test_no_history_selected_without_a_webhook(running: LiveApi) -> None:  # noqa: F811
    job_id = await finished_job(running)
    render = await best_render(running, job_id)
    res = await running.http.post(
        f'/api/jobs/{job_id}/select', json={'renderId': render['id'], 'copy': render['spec']['copy']}
    )
    assert res.status_code == 201
    assert await outbox(running, job_id) == []


async def test_final_poster_uses_the_selected_copy_and_is_cached(running: LiveApi) -> None:  # noqa: F811
    api = running
    job_id = await finished_job(api)
    render = await best_render(api, job_id)
    edited = {**render['spec']['copy'], 'headline': ['定稿', '標題']}
    entry = (await api.http.post(f'/api/jobs/{job_id}/select', json={'renderId': render['id'], 'copy': edited})).json()

    res = await api.http.get(f'/api/history/{entry["id"]}/poster.png')
    assert (res.status_code, res.headers['content-type']) == (200, 'image/png')
    with Image.open(io.BytesIO(res.content)) as image:
        # story 模板的原尺寸
        assert image.size == (1152, 2048)
    cached = final_poster_path(api.services.settings, entry['id'])
    assert cached.read_bytes() == res.content
    # 第二次直接讀檔：改掉檔案內容就讀到改過的
    cached.write_bytes(res.content + b'')
    assert (await api.http.get(f'/api/history/{entry["id"]}/poster.png')).content == res.content

    preview = await api.http.get(f'/api/history/{entry["id"]}/poster.png', params={'variant': 'preview'})
    assert preview.headers['content-type'] == 'image/jpeg' and len(preview.content) <= 1_000_000

    # 繪製用的 render：文案換成選定時的，其他不變
    drawn = final_render(HistoryEntry.model_validate(entry))
    assert drawn.spec.copy_.headline == ('定稿', '標題')
    assert drawn.model_dump(exclude={'spec'}) == HistoryEntry.model_validate(entry).render.model_dump(exclude={'spec'})


async def test_final_poster_of_an_unknown_history_is_404(api: LiveApi) -> None:
    for history_id in ('hist_000000000000', '..%2Fsecret'):
        res = await api.http.get(f'/api/history/{history_id}/poster.png')
        assert res.status_code == 404, history_id


async def test_history_selected_carries_the_client_ref_of_sheet_jobs(notified: LiveApi) -> None:
    # 來自試算表的任務：n8n 可以依 clientRef 找到那一列
    job_id = await finished_job(notified, clientRef='sheet:abc:row:2')
    await notified.http.post(f'/api/automation/jobs/{job_id}/approve', json={}, headers=AUTH)
    selected = [r.payload for r in await outbox(notified, job_id) if r.event == HISTORY_SELECTED]
    assert [(p['clientRef'], p['source']) for p in selected] == [('sheet:abc:row:2', 'automation')]
