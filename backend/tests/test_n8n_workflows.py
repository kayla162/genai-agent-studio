"""n8n 工作流（n8n/workflows/*.json）：必要的節點、webhook 路徑、驗簽程式碼與不含憑證。"""

import json
from pathlib import Path
from typing import Any

import pytest

from app.settings import REPO_ROOT

WORKFLOWS = REPO_ROOT / 'n8n' / 'workflows'


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((WORKFLOWS / f'{name}.json').read_text(encoding='utf-8'))
    return data


def node_types(flow: dict[str, Any]) -> set[str]:
    return {n['type'] for n in flow['nodes']}


def test_the_three_workflows_exist_with_fixed_ids() -> None:
    assert sorted(p.stem for p in WORKFLOWS.glob('*.json')) == [
        'poster-batch-submit',
        'poster-error',
        'poster-job-finished',
    ]
    for name in ('poster-batch-submit', 'poster-error', 'poster-job-finished'):
        assert load(name)['id'] == name


def test_job_finished_verifies_the_signature_before_responding() -> None:
    flow = load('poster-job-finished')
    webhook = next(n for n in flow['nodes'] if n['type'] == 'n8n-nodes-base.webhook')
    assert webhook['parameters']['path'] == 'poster-job-finished'
    assert webhook['parameters']['responseMode'] == 'responseNode'
    assert webhook['parameters']['options']['rawBody'] is True
    code = next(n for n in flow['nodes'] if n['name'] == '驗證簽章')['parameters']['jsCode']
    for needle in (
        'X-Webhook-Signature'.lower(),
        'x-webhook-timestamp',
        'timingSafeEqual',
        'JOB_WEBHOOK_SECRET',
        '300',
    ):
        assert needle in code
    assert {
        'n8n-nodes-base.respondToWebhook',
        'n8n-nodes-base.wait',
        'n8n-nodes-base.httpRequest',
        'n8n-nodes-base.googleSheets',
    } <= node_types(flow)
    assert flow['settings']['errorWorkflow'] == 'poster-error'


def test_sheet_write_back_never_blocks_the_review() -> None:
    # 回填失敗（沒有憑證、Sheets 5xx、列被刪除）時照樣送出審核：200 已經回覆，後端不會重送
    flow = load('poster-job-finished')
    sheets = [n for n in flow['nodes'] if n['type'] == 'n8n-nodes-base.googleSheets']
    assert [n['name'] for n in sheets] == ['回填試算表']
    for node in sheets:
        assert node.get('onError') == 'continueRegularOutput', node['name']


def test_batch_submit_calls_the_automation_api() -> None:
    flow = load('poster-batch-submit')
    urls = [n['parameters'].get('url', '') for n in flow['nodes'] if n['type'] == 'n8n-nodes-base.httpRequest']
    assert any('/api/automation/jobs' in u for u in urls)
    assert {'n8n-nodes-base.scheduleTrigger', 'n8n-nodes-base.googleSheets'} <= node_types(flow)
    assert flow['settings']['errorWorkflow'] == 'poster-error'


def test_batch_submit_sends_an_idempotency_key_per_row_content() -> None:
    # 排程重疊或回寫試算表失敗後重跑時，同一列（內容沒變）不會再建一個要花錢的任務；
    # 鍵含上一個 jobId，所以跑完之後清空 status 會建新任務
    flow = load('poster-batch-submit')
    node = next(n for n in flow['nodes'] if n['name'] == '建立任務')
    headers = {h['name']: h['value'] for h in node['parameters']['headerParameters']['parameters']}
    key = headers['Idempotency-Key']
    for needle in (
        "'sheet:'",
        '$env.GOOGLE_SHEET_ID',
        '$json.row_number',
        '$json.brand',
        '$json.product',
        '$json.brief',
        '$json.jobId',
        ".hash('sha256')",
    ):
        assert needle in key


@pytest.mark.parametrize('path', sorted(WORKFLOWS.glob('*.json')), ids=lambda p: p.stem)
def test_no_credentials_or_secrets_are_committed(path: Path) -> None:
    text = path.read_text(encoding='utf-8')
    flow = json.loads(text)
    for node in flow['nodes']:
        for credential in node.get('credentials', {}).values():
            assert credential.get('id') in (None, ''), f'{node["name"]} 帶著憑證 id'
    assert 'discord.com/api/webhooks/' not in text
    assert 'Bearer ' + 't' * 8 not in text


def test_workflow_payload_fields_exist_in_the_webhook_payload() -> None:
    """工作流引用的 payload 欄位都要是後端實際送出的欄位（取代 contracts 測資）。"""
    import re

    from app.webhooks.payload import build_job_finished

    text = (WORKFLOWS / 'poster-job-finished.json').read_text(encoding='utf-8')
    used = set(re.findall(r'\.payload\.([A-Za-z_]\w*)', text))
    assert used, '找不到任何 payload 欄位'
    data = build_job_finished(
        webhook_id='wh_1',
        job_id='job_1',
        stage='done',
        round=1,
        job_input={'brandId': 'b', 'productId': 'p', 'brief': 'x'},
        client_ref=None,
        parent_job_id=None,
        best_render_ids={},
        events=[],
        studio_base_url='http://h',
        finished_at='t',
    )
    assert used <= set(data), f'後端沒有這些欄位：{sorted(used - set(data))}'
