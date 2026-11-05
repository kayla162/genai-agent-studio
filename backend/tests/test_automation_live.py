"""live：對執行中的 docker compose（--profile automation、AGENT_MODE=sim、IMAGE_MODE=sim）跑一輪
「建任務 → webhook 送達 n8n → 核准」與「退回 → 新任務 → webhook」。

需要 AUTOMATION_TOKEN（環境變數或 .env），以及在 n8n 發布 poster-job-finished（見 n8n/README.md）。
api 的位址取自 AUTOMATION_LIVE_API（預設 http://127.0.0.1:8000）；
資料庫取自 DATABASE_URL（預設為開發用的資料庫，只讀 webhook_outbox）。
手動執行：uv run pytest -m live tests/test_automation_live.py -v（一般的 pytest 不收集這個測試）。
"""

import asyncio
import os

import httpx
import pytest
from sqlalchemy import select

from app.db.models import WebhookOutboxRow
from app.db.session import Database
from app.settings import Settings

API = os.environ.get('AUTOMATION_LIVE_API', 'http://127.0.0.1:8000')
BRIEF: dict[str, str | list[str] | int] = {
    'brandId': 'selune',
    'productId': 'prod_selune_serum',
    'brief': '週年慶主打買一送一，要溫柔療癒的感覺',
    'templateIds': ['story'],
    'variantsPerTemplate': 1,
}
#: 一個任務從建立到通知送達（或判定失敗）最多等幾秒
DELIVERY_TIMEOUT = 300


def reachable() -> bool:
    try:
        return httpx.get(f'{API}/api/health', timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not reachable(), reason=f'api 沒有回應（{API}），略過 live 測試'),
]


async def wait_delivered(db: Database, job_id: str, timeout: float = DELIVERY_TIMEOUT) -> WebhookOutboxRow:
    """等到該任務的結束通知不再是 pending（delivered 或 dead）。"""
    async with asyncio.timeout(timeout):
        while True:
            async with db.session() as s:
                row = await s.scalar(select(WebhookOutboxRow).where(WebhookOutboxRow.job_id == job_id))
            if row is not None and row.status != 'pending':
                return row
            await asyncio.sleep(2)


async def test_job_webhook_reaches_n8n_and_approve_and_revise_work() -> None:
    # 刻意讀 .env：live 測試對著使用者執行中的 compose，token 與資料庫位址和容器一致；環境變數優先
    settings = Settings()
    token = settings.automation_token.get_secret_value()
    if not token:
        pytest.skip('沒有設定 AUTOMATION_TOKEN')
    auth = {'Authorization': f'Bearer {token}'}
    db = Database(settings.database_url)
    try:
        async with httpx.AsyncClient(base_url=API, headers=auth, timeout=60) as http:
            job_id = (await http.post('/api/automation/jobs', json=BRIEF)).raise_for_status().json()['jobId']
            row = await wait_delivered(db, job_id)
            assert row.status == 'delivered', row.last_error
            assert row.payload['jobId'] == job_id
            assert row.payload['parentJobId'] is None

            res = await http.post(
                f'/api/automation/jobs/{job_id}/approve', json={}, headers={'Idempotency-Key': f'{row.id}:approve'}
            )
            assert res.status_code == 201, res.text
            entry = res.json()
            # 同一個冪等鍵再送一次：回傳第一次的結果，不重複寫入歷史紀錄
            again = await http.post(
                f'/api/automation/jobs/{job_id}/approve', json={}, headers={'Idempotency-Key': f'{row.id}:approve'}
            )
            assert again.status_code == 201
            assert again.json()['id'] == entry['id']
            history = (await http.get('/api/history', params={'brandId': 'selune'})).json()
            assert [h['id'] for h in history].count(entry['id']) == 1

            res = await http.post(f'/api/automation/jobs/{job_id}/revise', json={'feedback': '標題改成限時三天'})
            assert res.status_code == 201, res.text
            child = res.json()['jobId']
            child_row = await wait_delivered(db, child)
            assert child_row.status == 'delivered', child_row.last_error
            assert child_row.payload['parentJobId'] == job_id
            snap = (await http.get(f'/api/jobs/{child}')).json()
            assert any(e['type'] == 'log' and '審核者退回' in e['message'] for e in snap['events'])
    finally:
        await db.dispose()
