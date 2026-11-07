"""n8n 工作流（n8n/workflows/*.json）：必要的節點、webhook 路徑、驗簽程式碼與不含憑證。"""

import json
from pathlib import Path
from typing import Any, cast

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
    # Authorization 只能從環境變數組出（AUTOMATION_TOKEN、LINE_CHANNEL_ACCESS_TOKEN），不寫死 token
    for node in flow['nodes']:
        headers = node['parameters'].get('headerParameters', {}).get('parameters', [])
        for header in headers:
            if header['name'] == 'Authorization':
                assert header['value'].startswith('=Bearer {{ $env.'), node['name']


@pytest.mark.parametrize('name', ['poster-error', 'poster-job-finished'])
def test_notifications_go_to_line_push(name: str) -> None:
    # 通知改用 LINE Messaging API 的推播（純文字）；不再有 Discord
    flow = load(name)
    text = (WORKFLOWS / f'{name}.json').read_text(encoding='utf-8')
    assert 'discord' not in text.lower()
    pushes = [n for n in flow['nodes'] if n['parameters'].get('url') == 'https://api.line.me/v2/bot/message/push']
    assert pushes
    for node in pushes:
        params = node['parameters']
        assert params['method'] == 'POST'
        assert {h['name']: h['value'] for h in params['headerParameters']['parameters']} == {
            'Authorization': '=Bearer {{ $env.LINE_CHANNEL_ACCESS_TOKEN }}'
        }
        assert params['jsonBody'].startswith('={{ JSON.stringify({ to: $env.LINE_TO, messages: [{ type: ')
        # 最後一則是文字（LINE 文字訊息上限 5000 字）
        assert "{ type: 'text', text: " in params['jsonBody']
        assert params['jsonBody'].endswith('.slice(0, 5000) }] }) }}')
    # 每個節點的連線都指向存在的節點（移除附圖分支後沒有懸空的連線）
    names = {n['name'] for n in flow['nodes']}
    for src, outputs in flow['connections'].items():
        assert src in names
        for branch in outputs['main']:
            for target in branch:
                assert target['node'] in names


def to(name: str) -> list[dict[str, Any]]:
    return [{'node': name, 'type': 'main', 'index': 0}]


def test_review_message_is_pushed_with_the_r2_poster_or_as_text() -> None:
    # 有審查用海報、也設定了 R2 時：下載預覽圖 → 上傳 R2 → LINE 圖片＋文字；
    # 沒有海報、沒有設定 R2，或下載、上傳失敗時改送純文字，審核照常進行
    flow = load('poster-job-finished')
    c = flow['connections']
    assert c['組出訊息']['main'] == [to('附圖？')]
    assert c['附圖？']['main'] == [to('下載預覽圖'), to('通知 LINE')]
    assert c['下載預覽圖']['main'] == [to('上傳 R2'), to('通知 LINE')]
    assert c['上傳 R2']['main'] == [to('通知 LINE（附圖）'), to('通知 LINE')]
    assert c['通知 LINE（附圖）']['main'] == [to('等待審核')]
    assert c['通知 LINE']['main'] == [to('等待審核')]

    nodes = {n['name']: n for n in flow['nodes']}
    for name in ('下載預覽圖', '上傳 R2'):
        assert nodes[name].get('onError') == 'continueErrorOutput', name
    condition = nodes['附圖？']['parameters']['conditions']['conditions'][0]['leftValue']
    for needle in ('$json.posterKey', '$env.R2_BUCKET', '$env.R2_PUBLIC_BASE_URL'):
        assert needle in condition
    assert nodes['下載預覽圖']['parameters']['url'].endswith('{{ $json.payload.best.imageUrl }}?variant=preview')
    upload = nodes['上傳 R2']
    assert (upload['type'], upload['parameters']['operation']) == ('n8n-nodes-base.s3', 'upload')
    assert upload['parameters']['bucketName'] == '={{ $env.R2_BUCKET }}'
    assert upload['credentials'] == {'s3': {'id': '', 'name': 'Cloudflare R2'}}
    image = nodes['通知 LINE（附圖）']['parameters']['jsonBody']
    assert "type: 'image'" in image and 'originalContentUrl' in image and 'previewImageUrl' in image
    # 錯誤輸出的 $json 是錯誤，不是訊息：兩個 LINE 節點都從「組出訊息」讀文字
    for name in ('通知 LINE', '通知 LINE（附圖）'):
        assert "$('組出訊息').first().json.content" in nodes[name]['parameters']['jsonBody'], name
    key = next(
        a['value'] for a in nodes['組出訊息']['parameters']['assignments']['assignments'] if a['name'] == 'posterKey'
    )
    for needle in ('$json.payload.jobId', '$json.payload.best.renderId', '$json.payload.webhookId'):
        assert needle in key


def test_workflow_payload_fields_exist_in_the_webhook_payload() -> None:
    """工作流引用的 payload 欄位都要是後端實際送出的欄位（取代 contracts 測資）。"""
    import re
    from types import SimpleNamespace

    from app.contract import HistoryEntry
    from app.webhooks.payload import build_history_selected, build_job_finished

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
    # history.selected（定稿分支）的欄位
    entry = HistoryEntry.model_construct(
        id='hist_1',
        job_id='job_1',
        brand_id='b',
        product_id='p',
        template_id='ig-post',
        selected_at='t',
        favorite=False,
        written_to_rag=False,
        # build_history_selected 只讀 input.brief 與 render 的 id、score
        input=cast(Any, SimpleNamespace(brief='x')),
        render=cast(Any, SimpleNamespace(id='r1', score=80)),
        copy_=cast(Any, None),
    )
    selected = build_history_selected(
        webhook_id='wh_2', entry=entry, source='studio', client_ref=None, studio_base_url='http://h'
    )
    assert used <= set(data) | set(selected), f'後端沒有這些欄位：{sorted(used - set(data) - set(selected))}'


def test_history_selected_publishes_the_final_poster() -> None:
    # 定稿：下載原圖與預覽 → 上傳 R2 → LINE 圖片＋下載連結；沒有設定 R2 或任何一步失敗 → 只送文字
    flow = load('poster-job-finished')
    c = flow['connections']
    nodes = {n['name']: n for n in flow['nodes']}
    assert c['重複？']['main'][1] == to('定稿？')
    assert (
        "$json.payload.event === 'history.selected'"
        in nodes['定稿？']['parameters']['conditions']['conditions'][0]['leftValue']
    )
    # job.finished 照原本的流程
    assert c['定稿？']['main'][1] == to('來自試算表？') + to('需要審核？')
    assert c['定稿？']['main'][0] == to('組出定稿訊息')
    assert c['定稿附圖？']['main'] == [to('下載定稿'), to('通知 LINE（定稿文字）')]
    chain = ['下載定稿', '上傳定稿', '下載定稿預覽', '上傳定稿預覽', '通知 LINE（定稿）']
    for here, after in zip(chain, chain[1:], strict=False):
        assert c[here]['main'] == [to(after), to('通知 LINE（定稿文字）')], here
        assert nodes[here].get('onError') == 'continueErrorOutput', here
    assert nodes['下載定稿']['parameters']['url'].endswith('.json.payload.posterUrl }}')
    assert nodes['下載定稿預覽']['parameters']['url'].endswith('.json.payload.posterUrl }}?variant=preview')
    for name in ('上傳定稿', '上傳定稿預覽'):
        assert nodes[name]['credentials'] == {'s3': {'id': '', 'name': 'Cloudflare R2'}}
    keys = {a['name']: a['value'] for a in nodes['組出定稿訊息']['parameters']['assignments']['assignments']}
    assert "'final/' + $json.payload.jobId + '/' + $json.payload.historyId + '.png'" in keys['finalKey']
    image = nodes['通知 LINE（定稿）']['parameters']['jsonBody']
    assert 'originalContentUrl' in image and '.finalKey' in image and '.finalPreviewKey' in image
    assert '下載原圖' in image


def test_successful_approvals_are_announced_by_the_final_poster_only() -> None:
    # 核准成功時定稿訊息會送到 LINE；只有核准失敗才回覆「回覆結果」，退回照舊回覆
    c = load('poster-job-finished')['connections']
    assert c['核准']['main'] == [to('核准失敗？')]
    assert c['核准失敗？']['main'] == [to('回覆結果'), []]
    assert c['退回']['main'] == [to('回覆結果')]
