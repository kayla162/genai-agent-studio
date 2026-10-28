"""api：選項、系統狀態、品牌與文件上傳、商品與商品照、本機資料夾、檔案。需要 composer。"""

import asyncio
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image
from pypdf import PdfWriter
from saq.job import Status
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from app.adapters.composer import ComposerClient, ComposerHealth
from app.api import catalog as catalog_api
from app.brands import BrandLoadError
from app.contract import ProductCutout
from app.cutout.state import STATE_KEY
from app.files import resolve_file
from app.queues import cutout_key, ingest_channel
from app.rag.chunking import chunk_document
from app.rag.engine import RagEngine
from app.rag.errors import RagError
from app.rag.extract import MAX_BYTES, MAX_CHUNKS, NO_TEXT
from app.rag.state import STATE_KEY as RAG_STATE_KEY
from app.repo import catalog
from app.settings import Settings
from tests.conftest import LiveApi
from tests.fake_encoder import FakeEncoder
from tests.fixtures import SAMPLE_PDF, load_fixture

PNG = b'\x89PNG\r\n\x1a\n' + bytes(24)
DRAFT = {
    'brandId': 'selune',
    'name': '晚安面膜',
    'features': ['玻尿酸'],
    'price': {'sale': 590, 'original': 790},
    'photo': {'source': 'upload', 'url': '/files/uploads/x.png'},
    'cutout': None,
}


async def test_options_templates_and_brands(api: LiveApi, monkeypatch: pytest.MonkeyPatch) -> None:
    options = (await api.http.get('/api/options')).json()
    assert options == {'llm': ['Gemini 3.7 Flash'], 'vlm': ['Gemini 3.7 Vision'], 'engines': ['comfyui']}
    gemini = api.services.settings.model_copy(update={'agent_mode': 'gemini'})
    monkeypatch.setattr(api.services, 'settings', gemini)
    options = (await api.http.get('/api/options')).json()
    assert options == {'llm': ['gemini-3.8-flash'], 'vlm': ['gemini-3.8-flash'], 'engines': ['comfyui']}
    fixture = load_fixture('brands.json')
    assert (await api.http.get('/api/templates')).json() == fixture['templates']
    assert (await api.http.get('/api/brands')).json() == sorted(fixture['brands'], key=lambda b: b['id'])


async def status_of(api: LiveApi) -> dict[str, dict[str, Any]]:
    return {c['id']: c for c in (await api.http.get('/api/status')).json()['components']}


COMPOSER_LABEL = 'composer（排版、繪製與規則審查）'


async def test_status_reports_each_component(api: LiveApi) -> None:
    status = await status_of(api)
    assert [(k, c['status']) for k, c in status.items()] == [
        ('db', 'ok'),
        ('redis', 'ok'),
        ('worker', 'error'),
        ('composer', 'ok'),
        ('brands', 'ok'),
        ('chroma', 'ok'),
        ('rag', 'error'),
        ('gemini', 'sim'),
        ('comfyui', 'sim'),
        ('cutout', 'error'),
    ]
    assert status['brands']['detail'] == '已載入 2 個品牌'
    # composer 顯示 REVIEW_MODE（預設 composer）與啟動時註冊的海報字型
    assert status['composer'] == {
        'id': 'composer',
        'label': COMPOSER_LABEL,
        'status': 'ok',
        'detail': f'REVIEW_MODE=composer・字型：Noto Sans TC、Noto Serif TC（{api.composer_url}）',
    }
    # Chroma 正常時顯示網址；worker 還沒啟動，RAG 模型的狀態還沒有回報
    chroma_url = api.services.settings.chroma_url
    assert status['chroma'] == {'id': 'chroma', 'label': '向量庫（Chroma）', 'status': 'ok', 'detail': chroma_url}
    assert status['rag']['detail'] == 'worker 尚未回報'
    async with api.worker():
        for _ in range(50):
            if (await status_of(api))['worker']['status'] == 'ok':
                break
            await asyncio.sleep(0.1)
        assert (await status_of(api))['worker']['detail'].endswith('排隊 0、執行中 0')
    api.services.brand_errors = [BrandLoadError('broken.yaml', 'palette.primary：必填')]
    assert (await status_of(api))['brands'] == {
        'id': 'brands',
        'label': '品牌設定檔',
        'status': 'error',
        'detail': '已載入 2 個品牌；略過 broken.yaml：palette.primary：必填',
    }


async def test_status_shows_the_review_mode_and_a_composer_without_fonts(
    api: LiveApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = api.composer_url
    sim = api.services.settings.model_copy(update={'review_mode': 'sim'})
    monkeypatch.setattr(api.services, 'settings', sim)
    assert (await status_of(api))['composer'] == {
        'id': 'composer',
        'label': COMPOSER_LABEL,
        'status': 'sim',
        'detail': f'REVIEW_MODE=sim：模擬審查，不繪製審查用海報（{url}）',
    }
    monkeypatch.undo()

    # 舊版 composer 不回報字型：composer 模式畫不出審查用海報
    async def no_fonts() -> ComposerHealth:
        return ComposerHealth(fonts=[])

    monkeypatch.setattr(api.services.composer, 'health', no_fonts)
    composer = (await status_of(api))['composer']
    assert (composer['status'], composer['detail']) == (
        'error',
        f'REVIEW_MODE=composer，但 composer 沒有回報海報字型，請重新建置 composer（{url}）',
    )

    async def down() -> None:
        return None

    monkeypatch.setattr(api.services.composer, 'health', down)
    composer = (await status_of(api))['composer']
    assert (composer['status'], composer['detail']) == ('error', f'連不上 composer（{url}）')


async def test_composer_health_reads_the_fonts_and_tolerates_other_bodies() -> None:
    bodies: list[httpx.Response] = [
        httpx.Response(200, json={'status': 'ok', 'fonts': ['Noto Sans TC', 'Noto Serif TC']}),
        httpx.Response(200, json={'status': 'ok'}),
        httpx.Response(200, json=['ok']),
        httpx.Response(200, text='ok'),
        httpx.Response(503, json={'status': 'down'}),
    ]
    client = ComposerClient('http://composer.test')
    await client.aclose()
    client._client = httpx.AsyncClient(  # 換成假的連線，依序回應 bodies
        base_url='http://composer.test', transport=httpx.MockTransport(lambda request: bodies.pop(0))
    )
    try:
        assert await client.health() == ComposerHealth(fonts=['Noto Sans TC', 'Noto Serif TC'])
        assert await client.health() == ComposerHealth(fonts=[])
        assert await client.health() == ComposerHealth(fonts=[])
        assert await client.health() == ComposerHealth(fonts=[])
        assert await client.health() is None
    finally:
        await client.aclose()


async def ingest(api: LiveApi, brand_id: str, name: str, data: bytes) -> list[dict[str, Any]]:
    files = {'file': (name, data, 'application/octet-stream')}
    async with api.http.stream('POST', f'/api/brands/{brand_id}/documents', files=files) as res:
        assert (res.status_code, res.headers['content-type']) == (200, 'application/x-ndjson')
        return [json.loads(line) async for line in res.aiter_lines() if line]


async def test_ingest_streams_progress_as_ndjson(api: LiveApi) -> None:
    text = '# 色彩更新\n主色維持 #2F4A44。\n\n# Logo\n- 深色背景使用反白 Logo\n\n2026 春季素材 CTR 3.9%。'
    async with api.worker():
        lines = await ingest(api, 'misty-isle', 'ci_update.md', text.encode())
        assert [m['type'] for m in lines] == ['ingest.chunked'] + ['ingest.embedded'] * 3 + ['ingest.stored']
        assert lines[0]['chunks'] == [c.to_json() for c in chunk_document('misty-isle', 'ci_update.md', text)]
        assert lines[-1] == {'type': 'ingest.stored', 'collection': 'misty-isle_ci', 'count': 3}
        pdf = await ingest(api, 'misty-isle', 'C:\\fakepath\\ci-sample.pdf', SAMPLE_PDF.read_bytes())
        assert pdf[-1] == {'type': 'ingest.stored', 'collection': 'misty-isle_ci', 'count': 2}
        assert pdf[0]['source'] == 'ci-sample.pdf'
        empty = await ingest(api, 'misty-isle', 'empty.md', b'   ')
        assert empty == [{'error': {'code': 'invalid', 'message': '文件沒有可用的文字內容'}}]
    brands = {b['id']: b for b in (await api.http.get('/api/brands')).json()}
    sources = [c['source'] for c in brands['misty-isle']['guidelineChunks']]
    assert (sources.count('ci_update.md'), sources.count('ci-sample.pdf')) == (3, 2)


async def test_delete_an_uploaded_document(api: LiveApi) -> None:
    now = datetime(2026, 10, 25, tzinfo=UTC)
    async with api.services.db.session() as s:
        for name in ('手冊 v1.md', 'b.md'):
            text = f'# 色彩\n{name} 主色維持 #2F4A44。\n\n# Logo\n深色背景使用反白 Logo。'
            chunks = chunk_document('misty-isle', name, text)
            await catalog.replace_document_chunks(s, 'misty-isle', name, chunks, now)

    async def sources() -> list[str]:
        brands = {b['id']: b for b in (await api.http.get('/api/brands')).json()}
        return [c['source'] for c in brands['misty-isle']['guidelineChunks']]

    assert (await sources()).count('手冊 v1.md') == 2
    res = await api.http.delete('/api/brands/misty-isle/documents', params={'source': '手冊 v1.md'})
    assert res.status_code == 204
    after = await sources()
    assert '手冊 v1.md' not in after and after.count('b.md') == 2
    missing = await api.http.delete('/api/brands/misty-isle/documents', params={'source': '手冊 v1.md'})
    assert (missing.status_code, missing.json()['error']['message']) == (404, '找不到這份上傳的手冊：手冊 v1.md')
    # 品牌設定檔的規範（不是上傳的手冊）不能從這裡刪除
    config = await api.http.delete('/api/brands/misty-isle/documents', params={'source': 'misty_isle_ci_v1.4.pdf'})
    assert config.status_code == 404
    assert 'misty_isle_ci_v1.4.pdf' in await sources()
    no_brand = await api.http.delete('/api/brands/nope/documents', params={'source': 'b.md'})
    assert (no_brand.status_code, no_brand.json()['error']['message']) == (404, '找不到品牌：nope')


async def upload_error(api: LiveApi, brand_id: str, files: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    res = await api.http.post(f'/api/brands/{brand_id}/documents', files=files)
    assert res.headers['content-type'] == 'application/json'
    return res.status_code, res.json()['error']


async def test_ingest_rejects_bad_files_before_streaming(api: LiveApi) -> None:
    """不需要 worker：檔案的問題在放入佇列之前就回應錯誤。"""
    blank = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(420, 595)
    writer.write(blank)
    cases: list[tuple[str, dict[str, Any], int, str]] = [
        ('nope', {'file': ('a.md', b'x')}, 404, '找不到品牌：nope'),
        ('selune', {'file': ('a.docx', b'x')}, 400, '只支援 .md、.txt、.pdf'),
        ('selune', {'file': ('a.txt', '主色'.encode('big5'))}, 400, '文字檔需為 UTF-8 編碼'),
        ('selune', {'file': ('scan.pdf', blank.getvalue())}, 400, NO_TEXT),
        ('selune', {'file': ('big.md', b'a' * (MAX_BYTES + 1))}, 400, '檔案不可超過 20 MB'),
        ('selune', {'other': ('a.md', b'x')}, 400, '請求格式錯誤：file：缺少欄位'),
    ]
    for brand_id, files, status, message in cases:
        code = 'not_found' if status == 404 else 'invalid'
        assert await upload_error(api, brand_id, files) == (status, {'code': code, 'message': message})
    assert await api.services.queues.tasks.count('queued') == 0


async def test_ingest_rejects_too_many_chunks_before_streaming(api: LiveApi, monkeypatch: pytest.MonkeyPatch) -> None:
    """很多短段落（FAQ、詞彙表）字數不多，切塊卻可能上萬：切塊數在放入佇列之前就檢查，剛好 2,000 塊仍可上傳。"""
    monkeypatch.setattr(catalog_api, 'INGEST_IDLE_TIMEOUT', 1)

    def faq(n: int) -> str:
        return '\n\n'.join(f'問題 {i}：請見說明。' for i in range(n))

    assert MAX_CHUNKS == 2000
    assert len(chunk_document('selune', 'faq.md', faq(2001))) == 2001
    message = '切塊太多（2,001 塊，上限 2,000），請分成幾份上傳'
    assert await upload_error(api, 'selune', {'file': ('faq.md', faq(2001).encode())}) == (
        400,
        {'code': 'invalid', 'message': message},
    )
    assert await api.services.queues.tasks.count('queued') == 0

    queued: list[int] = []

    async def no_worker(function: str, /, **kwargs: Any) -> None:
        queued.append(len(chunk_document(kwargs['brand_id'], kwargs['name'], kwargs['text'])))

    monkeypatch.setattr(api.services.queues, 'enqueue_task', no_worker)
    lines = await ingest(api, 'selune', 'faq.md', faq(2000).encode())
    assert queued == [2000]
    assert [line['error']['code'] for line in lines] == ['unavailable']


async def test_ingest_times_out_only_after_a_pause_in_progress(api: LiveApi, monkeypatch: pytest.MonkeyPatch) -> None:
    """閒置逾時：持續有進度時，總時間超過逾時也照常完成；沒有進度（沒有 worker）時才回報逾時。"""
    monkeypatch.setattr(catalog_api, 'INGEST_IDLE_TIMEOUT', 1)
    publishing: list[asyncio.Task[None]] = []

    async def slow_worker(function: str, /, **kwargs: Any) -> None:
        async def publish() -> None:
            channel = ingest_channel(kwargs['task_id'])
            for i in range(6):
                await asyncio.sleep(0.4)
                event = {'type': 'ingest.embedded', 'chunkId': 'x', 'index': i, 'total': 6, 'dims': 1, 'preview': []}
                await api.services.redis.publish(channel, json.dumps(event))
            stored = {'type': 'ingest.stored', 'collection': 'selune_ci', 'count': 6}
            await api.services.redis.publish(channel, json.dumps(stored))

        publishing.append(asyncio.create_task(publish()))

    monkeypatch.setattr(api.services.queues, 'enqueue_task', slow_worker)
    loop = asyncio.get_running_loop()
    started = loop.time()
    lines = await ingest(api, 'selune', 'a.md', '# 色彩\n主色'.encode())
    assert loop.time() - started > 2
    assert [m['type'] for m in lines] == ['ingest.embedded'] * 6 + ['ingest.stored']
    await asyncio.gather(*publishing)

    async def no_worker(function: str, /, **kwargs: Any) -> None:
        pass

    monkeypatch.setattr(api.services.queues, 'enqueue_task', no_worker)
    message = (
        '文件處理逾時：1 秒沒有任何進度。第一次使用時 worker 可能仍在下載 RAG 模型，請稍後再試；'
        '若持續發生，請確認 worker 正在執行'
    )
    assert await ingest(api, 'selune', 'a.md', '# 色彩\n主色'.encode()) == [
        {'error': {'code': 'unavailable', 'message': message}}
    ]


async def test_create_update_and_delete_products(api: LiveApi) -> None:
    created = await api.http.post('/api/products', json=DRAFT)
    assert created.status_code == 201
    product = created.json()
    assert product['id'].startswith('prod_') and product['name'] == '晚安面膜'
    renamed = {**DRAFT, 'name': '晚安修護面膜'}
    updated = (await api.http.put(f'/api/products/{product["id"]}', json=renamed)).json()
    assert updated == {**product, 'name': '晚安修護面膜'}
    listed = (await api.http.get('/api/products', params={'brandId': 'selune'})).json()
    assert [p['id'] for p in listed] == ['prod_selune_serum', product['id']]
    for product_id in (product['id'], 'prod_selune_serum'):
        assert (await api.http.delete(f'/api/products/{product_id}')).status_code == 204
    assert (await api.http.get('/api/products', params={'brandId': 'selune'})).json() == []
    missing = await api.http.delete(f'/api/products/{product["id"]}')
    assert missing.json() == {'error': {'code': 'not_found', 'message': f'找不到商品：{product["id"]}'}}


async def test_errors_use_one_format(api: LiveApi) -> None:
    unknown_brand = await api.http.post('/api/products', json={**DRAFT, 'brandId': 'nope'})
    assert (unknown_brand.status_code, unknown_brand.json()['error']) == (
        400,
        {'code': 'invalid', 'message': '找不到品牌：nope'},
    )
    assert (await api.http.post('/api/products', json={**DRAFT, 'id': 'prod_x'})).status_code == 400
    mismatch = await api.http.put('/api/products/prod_a', json={**DRAFT, 'id': 'prod_b'})
    assert mismatch.json()['error']['message'] == '網址與內容的商品 id 不一致'
    malformed = (await api.http.post('/api/products', json={**DRAFT, 'price': {'sale': 'free'}})).json()
    assert malformed['error']['code'] == 'invalid'
    assert malformed['error']['message'] == '請求格式錯誤：price.sale：必須是整數'
    no_route = await api.http.get('/api/nope')
    assert no_route.status_code == 404
    assert no_route.json() == {'error': {'code': 'not_found', 'message': '找不到這個網址'}}


async def test_upload_photo_and_read_it_back(api: LiveApi) -> None:
    res = await api.http.post('/api/products/photos', files={'file': ('serum.png', PNG, 'image/png')})
    assert res.status_code == 201
    photo = res.json()
    assert photo['source'] == 'upload' and re.fullmatch(r'/files/uploads/[0-9a-f]{16}\.png', photo['url'])
    served = await api.http.get(photo['url'])
    assert (served.status_code, served.headers['content-type'], served.content) == (200, 'image/png', PNG)
    for name, kind, message in [
        ('notes.txt', 'text/plain', '只能上傳圖片檔'),
        ('anim.gif', 'image/gif', '只支援 PNG、JPEG 與 WebP 圖片'),
    ]:
        rejected = await api.http.post('/api/products/photos', files={'file': (name, b'x', kind)})
        assert (rejected.status_code, rejected.json()['error']['message']) == (400, message)


PENDING = {'model': 'birefnet-general', 'status': 'pending', 'url': None, 'error': None}


async def test_new_photo_products_are_queued_for_a_cutout_and_keep_it_on_edit(api: LiveApi) -> None:
    sent = {'model': 'sim', 'status': 'done', 'url': '/files/products/x/cutout-a.png', 'error': None}
    # 去背狀態由伺服器管理：送來的 cutout 一律忽略
    product = (await api.http.post('/api/products', json={**DRAFT, 'cutout': sent})).json()
    assert product['cutout'] == PENDING
    queue = api.services.queues.cutouts
    key = cutout_key(product['id'], '/files/uploads/x.png')
    assert await queue.job(key) is not None
    # worker 完成去背：取出佇列裡的工作、標記完成，結果寫進商品（與請求送來的不同）
    taken = await queue.dequeue(timeout=1)
    assert taken is not None and taken.key == key
    await queue.finish(taken, Status.COMPLETE)
    stored = ProductCutout(
        model='birefnet-general', status='done', url=f'/files/products/{product["id"]}/cutout-b.png', error=None
    )
    async with api.services.db.session() as s:
        assert await catalog.set_cutout(s, product['id'], '/files/uploads/x.png', stored) is not None
    # 只改名稱：沿用資料庫裡的去背結果（不是送來的，也不是重設為去背中），也沒有再排入新的工作
    renamed = await api.http.put(f'/api/products/{product["id"]}', json={**DRAFT, 'name': '改名', 'cutout': sent})
    assert renamed.json()['cutout'] == stored.to_json()
    assert await queue.count('queued') == 0
    record = await queue.job(key)
    assert record is not None and record.status == Status.COMPLETE
    # 換了照片：重新去背（新照片有自己的 key）
    photo = {'source': 'upload', 'url': '/files/uploads/y.png'}
    moved = (await api.http.put(f'/api/products/{product["id"]}', json={**DRAFT, 'photo': photo})).json()
    assert moved['cutout'] == PENDING
    assert await queue.job(cutout_key(product['id'], '/files/uploads/y.png')) is not None
    # 示範商品不需要去背
    sample = (await api.http.get('/api/products', params={'brandId': 'selune'})).json()[0]
    fields = {k: v for k, v in sample.items() if k not in ('id', 'createdAt')}
    kept = (await api.http.put(f'/api/products/{sample["id"]}', json={**fields, 'name': '改名'})).json()
    assert kept['cutout'] is None


async def test_a_product_whose_photo_becomes_a_sample_has_no_cutout(api: LiveApi) -> None:
    product = (await api.http.post('/api/products', json=DRAFT)).json()
    assert product['cutout'] == PENDING
    sample_photo = {'source': 'sample', 'art': 'serum'}
    saved = await api.http.put(f'/api/products/{product["id"]}', json={**DRAFT, 'photo': sample_photo})
    assert (saved.json()['photo'], saved.json()['cutout']) == (sample_photo, None)


async def test_deleting_a_product_removes_its_cutouts(api: LiveApi) -> None:
    product = (await api.http.post('/api/products', json=DRAFT)).json()
    folder = api.services.settings.data_dir / 'products' / product['id']
    folder.mkdir(parents=True)
    (folder / 'cutout-a.png').write_bytes(PNG)
    assert (await api.http.delete(f'/api/products/{product["id"]}')).status_code == 204
    assert not folder.exists()


async def test_status_shows_the_cutout_model_state(api: LiveApi) -> None:
    model = 'birefnet-general'
    cases = [
        (model, 'ready', None, 'ok', 'birefnet-general 已載入'),
        (model, 'loading', None, 'off', '正在載入 birefnet-general'),
        (model, 'downloading', None, 'off', '第一次使用，正在下載模型（約 1 GB）'),
        (model, 'failed', '去背模型下載失敗：x', 'error', '去背模型下載失敗：x'),
        ('sim', 'sim', None, 'sim', '模擬去背：中央的橢圓'),
    ]
    for name, state, error, status, detail in cases:
        message = {'model': name, 'state': state, 'error': error}
        await api.services.redis.set(STATE_KEY, json.dumps(message, ensure_ascii=False))
        component = (await status_of(api))['cutout']
        assert component == {'id': 'cutout', 'label': '去背模型（BiRefNet）', 'status': status, 'detail': detail}
    await api.services.redis.delete(STATE_KEY)
    assert (await status_of(api))['cutout']['detail'] == 'worker 尚未回報'


async def test_status_never_fails_on_an_unreadable_cutout_state(api: LiveApi) -> None:
    unreadable = [
        'not json',
        '[1, 2]',
        '"ready"',
        json.dumps({'model': 'x'}),
        json.dumps({'model': 'x', 'state': 'weird'}),
    ]
    for raw in unreadable:
        await api.services.redis.set(STATE_KEY, raw)
        res = await api.http.get('/api/status')
        assert res.status_code == 200
        component = (await status_of(api))['cutout']
        assert (component['status'], component['detail']) == ('error', '去背模型狀態無法辨識'), raw
    # 失敗時沒有附上原因也不能壞掉
    await api.services.redis.set(STATE_KEY, json.dumps({'model': 'x', 'state': 'failed', 'error': None}))
    assert (await status_of(api))['cutout']['status'] == 'error'


async def test_status_reports_a_redis_error_and_a_timeout_for_the_cutout_state(
    api: LiveApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(key: str) -> None:
        raise RuntimeError('redis 讀取失敗')

    monkeypatch.setattr(api.services.redis, 'get', broken)
    res = await api.http.get('/api/status')
    assert res.status_code == 200
    component = (await status_of(api))['cutout']
    assert (component['status'], component['detail']) == ('error', 'RuntimeError: redis 讀取失敗')

    async def stuck(key: str) -> None:
        await asyncio.sleep(5)

    monkeypatch.setattr(api.services.redis, 'get', stuck)
    monkeypatch.setattr(catalog_api, 'STATUS_TIMEOUT', 0.1)
    component = (await status_of(api))['cutout']
    assert (component['status'], component['detail']) == ('error', '0.1 秒內沒有回應')


RAG_LABEL = 'RAG 模型（BGE-M3＋Reranker）'


async def test_status_shows_the_rag_model_state(api: LiveApi) -> None:
    cases = [
        ('sim', 'sim', None, 'sim', '模擬檢索：固定的召回與 Rerank 順序'),
        ('bge', 'downloading', None, 'off', '第一次使用，正在下載模型（約 1.2 GB）'),
        ('bge', 'standby', None, 'ok', '模型已就緒，第一次檢索時載入'),
        ('bge', 'loading', None, 'off', '正在載入模型'),
        ('bge', 'ready', None, 'ok', 'bge-m3＋bge-reranker-v2-m3 已載入'),
        ('bge', 'failed', 'RAG 模型下載失敗：x', 'error', 'RAG 模型下載失敗：x'),
    ]
    for mode, state, error, status, detail in cases:
        message = {'model': mode, 'state': state, 'error': error}
        await api.services.redis.set(RAG_STATE_KEY, json.dumps(message, ensure_ascii=False))
        assert (await status_of(api))['rag'] == {'id': 'rag', 'label': RAG_LABEL, 'status': status, 'detail': detail}
    await api.services.redis.delete(RAG_STATE_KEY)
    missing = {'id': 'rag', 'label': RAG_LABEL, 'status': 'error', 'detail': 'worker 尚未回報'}
    assert (await status_of(api))['rag'] == missing


async def test_status_reads_what_the_rag_engine_reports(api: LiveApi, tmp_path: Path) -> None:
    await RagEngine('sim', tmp_path, api.services.redis).prepare_files()
    assert (await status_of(api))['rag']['status'] == 'sim'
    engine = RagEngine('bge', tmp_path, api.services.redis, models=[], load=lambda _: FakeEncoder())
    await engine.prepare_files()
    assert (await status_of(api))['rag']['detail'] == '模型已就緒，第一次檢索時載入'
    await engine.encoder()
    assert (await status_of(api))['rag']['detail'] == 'bge-m3＋bge-reranker-v2-m3 已載入'

    def broken(models_dir: Path) -> FakeEncoder:
        raise RuntimeError('模型檔損毀')

    with pytest.raises(RagError):
        await RagEngine('bge', tmp_path, api.services.redis, models=[], load=broken).encoder()
    component = (await status_of(api))['rag']
    assert (component['status'], component['detail']) == ('error', 'RAG 模型準備失敗：模型檔損毀')


async def test_status_never_fails_on_an_unreadable_rag_state(api: LiveApi) -> None:
    unreadable = [
        'not json',
        '[1, 2]',
        '"ready"',
        json.dumps({'model': 'bge'}),
        json.dumps({'model': 'bge', 'state': 'weird'}),
    ]
    for raw in unreadable:
        await api.services.redis.set(RAG_STATE_KEY, raw)
        res = await api.http.get('/api/status')
        assert res.status_code == 200
        component = {c['id']: c for c in res.json()['components']}['rag']
        assert (component['status'], component['detail']) == ('error', 'RAG 模型狀態無法辨識'), raw
    # 失敗時沒有附上原因
    await api.services.redis.set(RAG_STATE_KEY, json.dumps({'model': 'bge', 'state': 'failed', 'error': None}))
    component = (await status_of(api))['rag']
    assert (component['status'], component['detail']) == ('error', 'RAG 模型準備失敗')


async def test_status_reports_an_unreachable_or_wrong_chroma(api: LiveApi, monkeypatch: pytest.MonkeyPatch) -> None:
    # Windows 對沒有開的埠約 2 秒才拒絕連線：放寬逾時，確認是「連不上」而不是逾時
    monkeypatch.setattr(catalog_api, 'STATUS_TIMEOUT', 10)
    down = api.services.settings.model_copy(update={'chroma_url': 'http://127.0.0.1:9'})
    monkeypatch.setattr(api.services, 'settings', down)
    res = await api.http.get('/api/status')
    assert res.status_code == 200
    chroma = {c['id']: c for c in res.json()['components']}['chroma']
    assert chroma['status'] == 'error'
    assert chroma['detail'].startswith('連不上 Chroma（http://127.0.0.1:9）：ConnectError')
    # 有回應但不是 Chroma（例如網址填成 api）
    url = str(api.http.base_url).rstrip('/')
    monkeypatch.setattr(api.services, 'settings', api.services.settings.model_copy(update={'chroma_url': url}))
    chroma = (await status_of(api))['chroma']
    assert (chroma['status'], chroma['detail']) == ('error', f'Chroma 回應 HTTP 404（{url}）')


async def test_status_does_not_probe_chroma_in_sim_mode(api: LiveApi, monkeypatch: pytest.MonkeyPatch) -> None:
    # 網址指向沒有開的埠：有檢查的話會是 error
    sim = api.services.settings.model_copy(update={'rag_mode': 'sim', 'chroma_url': 'http://127.0.0.1:9'})
    monkeypatch.setattr(api.services, 'settings', sim)
    chroma = (await status_of(api))['chroma']
    assert chroma == {'id': 'chroma', 'label': '向量庫（Chroma）', 'status': 'sim', 'detail': '模擬模式不使用向量庫'}


def test_the_api_does_not_import_the_model_runtimes() -> None:
    """系統狀態只讀 Redis 的 rag:model（app.rag.state）與 Chroma 的 heartbeat：api 不載入 onnxruntime 等套件。"""
    heavy = ('onnxruntime', 'tokenizers', 'chromadb', 'app.rag.engine', 'app.cutout.engine')
    code = f'import sys, app.api.main; print([m for m in {heavy!r} if m in sys.modules])'
    backend = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, '-c', code], cwd=backend, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == '[]'


def real_png() -> bytes:
    buf = io.BytesIO()
    Image.new('RGB', (40, 60), (120, 80, 160)).save(buf, 'PNG')
    return buf.getvalue()


async def products(api: LiveApi) -> list[dict[str, Any]]:
    listed: list[dict[str, Any]] = (await api.http.get('/api/products', params={'brandId': 'selune'})).json()
    return listed


async def test_cutout_is_queued_and_finished_by_the_worker(api: LiveApi) -> None:
    photo = (await api.http.post('/api/products/photos', files={'file': ('a.png', real_png(), 'image/png')})).json()
    product = (await api.http.post('/api/products', json={**DRAFT, 'photo': photo})).json()
    res = await api.http.post(f'/api/products/{product["id"]}/cutout')
    assert res.status_code == 202
    assert res.json()['cutout'] == {'model': 'birefnet-general', 'status': 'pending', 'url': None, 'error': None}
    async with api.worker():
        for _ in range(50):
            if (await products(api))[-1]['cutout']['status'] != 'pending':
                break
            await asyncio.sleep(0.1)
    cut = (await products(api))[-1]['cutout']
    assert (cut['model'], cut['status'], cut['error']) == ('sim', 'done', None)
    served = await api.http.get(cut['url'])
    assert (served.status_code, served.headers['content-type']) == (200, 'image/png')
    sample = await api.http.post('/api/products/prod_selune_serum/cutout')
    assert sample.json() == {'error': {'code': 'invalid', 'message': '示範商品已是去背素材'}}


async def test_list_and_import_local_photos(api: LiveApi) -> None:
    folder = api.services.settings.local_photos_dir
    assert (await api.http.get('/api/local-photos')).json() == []
    folder.mkdir(parents=True)
    for name in ('night_cream-v2.png', '精華液.JPG', '.hidden.png', 'notes.txt'):
        (folder / name).write_bytes(PNG)
    photos = (await api.http.get('/api/local-photos')).json()
    assert photos == [
        {'file': 'night_cream-v2.png', 'name': 'night cream v2', 'url': '/files/local/night_cream-v2.png', 'size': 32},
        {'file': '精華液.JPG', 'name': '精華液', 'url': '/files/local/%E7%B2%BE%E8%8F%AF%E6%B6%B2.JPG', 'size': 32},
    ]
    served = await api.http.get(photos[1]['url'])
    assert (served.headers['content-type'], served.content) == ('image/jpeg', PNG)
    res = await api.http.post('/api/local-photos/night_cream-v2.png/import', json={'brandId': 'misty-isle'})
    assert res.status_code == 201
    product = res.json()
    assert {k: v for k, v in product.items() if k not in ('id', 'createdAt')} == {
        'brandId': 'misty-isle',
        'name': 'night cream v2',
        'features': [],
        'price': {'sale': 0, 'original': 0},
        'photo': {'source': 'local', 'url': '/files/local/night_cream-v2.png'},
        'cutout': PENDING,
    }
    assert await api.services.queues.cutouts.job(cutout_key(product['id'], product['photo']['url'])) is not None
    for name in ('notes.txt', '.hidden.png', 'missing.png'):
        missing = await api.http.post(f'/api/local-photos/{name}/import', json={'brandId': 'misty-isle'})
        assert missing.status_code == 404


def _other_drive(drive: str) -> str | None:
    """Windows 上另一個可以寫入的磁碟機（例如 D:），沒有時為 None。"""
    if os.name != 'nt':
        return None
    for letter in 'CDEFGH':
        other = f'{letter}:'
        if other.lower() != drive.lower() and os.access(f'{other}\\', os.W_OK):
            return other
    return None


def test_local_photos_refuse_drive_prefixed_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows 上「D:secret.png」是 D 槽目前資料夾裡的檔案（本機資料夾在別的磁碟機時），不在本機資料夾裡。"""
    other = _other_drive(tmp_path.drive)
    if other is None:
        pytest.skip('需要 Windows 與另一個可寫入的磁碟機')
    settings = Settings(_env_file=None, image_mode='sim', agent_mode='sim', local_photos_dir=tmp_path / 'local')
    (tmp_path / 'local').mkdir()
    with tempfile.TemporaryDirectory(dir=f'{other}\\') as outside:
        (Path(outside) / 'secret.png').write_bytes(PNG)
        # chdir 到另一個磁碟機時也設定了那個磁碟機的「目前資料夾」
        monkeypatch.chdir(outside)
        assert catalog_api._local_photo(settings, f'{other}secret.png') is None
        monkeypatch.undo()


def test_files_stay_inside_their_folders(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        image_mode='sim',
        agent_mode='sim',
        data_dir=tmp_path / 'data',
        local_photos_dir=tmp_path / 'local',
        brands_dir=tmp_path / 'brands',
    )
    files = ['secret.png', 'data/uploads/a.png', 'local/b.jpg', 'brands/assets/logo.svg', 'brands/selune.yaml']
    for name in files:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(PNG)
    assert resolve_file(settings, 'uploads/a.png') == (tmp_path / 'data/uploads/a.png').resolve()
    assert resolve_file(settings, 'local/b.jpg') == (tmp_path / 'local/b.jpg').resolve()
    assert resolve_file(settings, 'brands/assets/logo.svg') == (tmp_path / 'brands/assets/logo.svg').resolve()
    for path in [
        '../secret.png',
        'uploads/../../secret.png',
        'local/../secret.png',
        'brands/../secret.png',
        str(tmp_path / 'secret.png'),
        'brands/selune.yaml',
        'uploads/missing.png',
    ]:
        assert resolve_file(settings, path) is None, path


async def test_requests_with_an_unknown_host_are_refused(api: LiveApi) -> None:
    """DNS rebinding：惡意網頁把自己的網域指到 127.0.0.1 後，瀏覽器送出的 Host 是那個網域，一律拒絕。"""
    assert (await api.http.get('/api/health')).status_code == 200
    assert (await api.http.get('/api/health', headers={'Host': 'localhost:3000'})).status_code == 200
    for host in ('rebind.example', 'rebind.example:3000', '127.0.0.1.rebind.example'):
        res = await api.http.get('/api/brands', headers={'Host': host})
        assert res.status_code == 400
        assert res.json() == {'error': {'code': 'invalid_host', 'message': f'不接受的主機名稱：{host.split(":")[0]}'}}


async def test_websockets_with_an_unknown_host_are_refused(api: LiveApi) -> None:
    port = int(api.ws_url.rsplit(':', 1)[1])
    # 網址的主機名稱成為 Host 標頭，實際連到 127.0.0.1
    with pytest.raises(InvalidStatus) as refused:
        async with connect(f'ws://rebind.example:{port}/ws/jobs/job_nope', host='127.0.0.1', port=port):
            pass
    assert refused.value.response.status_code == 403
