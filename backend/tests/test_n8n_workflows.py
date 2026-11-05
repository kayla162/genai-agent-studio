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


def test_batch_submit_calls_the_automation_api() -> None:
    flow = load('poster-batch-submit')
    urls = [n['parameters'].get('url', '') for n in flow['nodes'] if n['type'] == 'n8n-nodes-base.httpRequest']
    assert any('/api/automation/jobs' in u for u in urls)
    assert {'n8n-nodes-base.scheduleTrigger', 'n8n-nodes-base.googleSheets'} <= node_types(flow)
    assert flow['settings']['errorWorkflow'] == 'poster-error'


@pytest.mark.parametrize('path', sorted(WORKFLOWS.glob('*.json')), ids=lambda p: p.stem)
def test_no_credentials_or_secrets_are_committed(path: Path) -> None:
    text = path.read_text(encoding='utf-8')
    flow = json.loads(text)
    for node in flow['nodes']:
        for credential in node.get('credentials', {}).values():
            assert credential.get('id') in (None, ''), f'{node["name"]} 帶著憑證 id'
    assert 'discord.com/api/webhooks/' not in text
    assert 'Bearer ' + 't' * 8 not in text
