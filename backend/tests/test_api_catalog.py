"""api：選項、系統狀態、品牌與文件上傳、商品與商品照、本機資料夾、檔案。需要 composer。"""

import asyncio
import io
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image

from app.brands import BrandLoadError
from app.files import resolve_file
from app.settings import Settings
from tests.conftest import LiveApi
from tests.fixtures import load_fixture

PNG = b'\x89PNG\r\n\x1a\n' + bytes(24)
DRAFT = {
    'brandId': 'selune',
    'name': '晚安面膜',
    'features': ['玻尿酸'],
    'price': {'sale': 590, 'original': 790},
    'photo': {'source': 'upload', 'url': '/files/uploads/x.png'},
    'cutout': None,
}


async def test_options_templates_and_brands(api: LiveApi) -> None:
    options = (await api.http.get('/api/options')).json()
    assert options == {'llm': ['Gemini 3.7 Flash'], 'vlm': ['Gemini 3.7 Vision'], 'engines': ['comfyui']}
    fixture = load_fixture('brands.json')
    assert (await api.http.get('/api/templates')).json() == fixture['templates']
    assert (await api.http.get('/api/brands')).json() == sorted(fixture['brands'], key=lambda b: b['id'])


async def status_of(api: LiveApi) -> dict[str, dict[str, Any]]:
    return {c['id']: c for c in (await api.http.get('/api/status')).json()['components']}


async def test_status_reports_each_component(api: LiveApi) -> None:
    status = await status_of(api)
    assert {k: c['status'] for k, c in status.items()} == {
        'db': 'ok',
        'redis': 'ok',
        'worker': 'error',
        'composer': 'ok',
        'brands': 'ok',
        'rag': 'sim',
        'gemini': 'sim',
        'comfyui': 'sim',
    }
    assert status['brands']['detail'] == '已載入 2 個品牌'
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


async def ingest(api: LiveApi, brand_id: str, name: str, text: str) -> list[dict[str, Any]]:
    body = {'name': name, 'text': text}
    async with api.http.stream('POST', f'/api/brands/{brand_id}/documents', json=body) as res:
        assert (res.status_code, res.headers['content-type']) == (200, 'application/x-ndjson')
        return [json.loads(line) async for line in res.aiter_lines() if line]


async def test_ingest_streams_progress_as_ndjson(api: LiveApi) -> None:
    text = '# 色彩更新\n主色維持 #2F4A44。\n\n# Logo\n- 深色背景使用反白 Logo\n\n2026 春季素材 CTR 3.9%。'
    async with api.worker():
        lines = await ingest(api, 'misty-isle', 'ci_update.md', text)
        assert [m['type'] for m in lines] == ['ingest.chunked'] + ['ingest.embedded'] * 3 + ['ingest.stored']
        assert lines[-1] == {'type': 'ingest.stored', 'collection': 'misty-isle_ci', 'count': 3}
        empty = await ingest(api, 'misty-isle', 'empty.md', '   ')
        assert empty == [{'error': {'code': 'invalid', 'message': '文件沒有可用的文字內容'}}]
    brands = {b['id']: b for b in (await api.http.get('/api/brands')).json()}
    assert [c['source'] for c in brands['misty-isle']['guidelineChunks']].count('ci_update.md') == 3
    missing = await api.http.post('/api/brands/nope/documents', json={'name': 'a.md', 'text': 'x'})
    assert missing.status_code == 404
    assert missing.json() == {'error': {'code': 'not_found', 'message': '找不到品牌：nope'}}


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
    assert malformed['error']['message'].startswith('請求格式錯誤：body.price.sale：')
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
        'cutout': None,
    }
    for name in ('notes.txt', '.hidden.png', 'missing.png'):
        missing = await api.http.post(f'/api/local-photos/{name}/import', json={'brandId': 'misty-isle'})
        assert missing.status_code == 404


def test_files_stay_inside_their_folders(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / 'data', local_photos_dir=tmp_path / 'local', brands_dir=tmp_path / 'brands')
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
