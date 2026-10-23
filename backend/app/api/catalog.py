"""可用選項、系統狀態、品牌（含文件上傳）、通路模板、商品與商品照、本機資料夾。"""

import asyncio
import contextlib
import json
import re
import secrets
import shutil
from collections.abc import AsyncIterator, Awaitable
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from app.adapters.composer import ComposerClient, ComposerError
from app.adapters.gemini import NOT_CONFIGURED, GeminiError
from app.api.services import ApiServices, Services
from app.contract import (
    ApiOptions,
    Brand,
    ChannelTemplate,
    ComponentStatus,
    FilePhoto,
    LocalPhoto,
    Model,
    Price,
    Product,
    ProductCutout,
    ProductDraft,
    SystemStatus,
)
from app.core.clock import utc_now
from app.cutout.state import STATE_KEY as CUTOUT_STATE_KEY
from app.errors import Invalid, NotFound, Unavailable
from app.files import product_folder
from app.pipeline.runner import failure_reason
from app.queues import ingest_channel
from app.rag.chunking import chunk_document
from app.rag.extract import MAX_BYTES as MAX_DOCUMENT_BYTES
from app.rag.extract import MAX_CHUNKS, check_type, document_name, extract_text
from app.rag.state import STATE_KEY as RAG_STATE_KEY
from app.repo import catalog
from app.settings import Settings
from app.templates import CHANNEL_TEMPLATES
from app.usage import PricingError, usd

router = APIRouter(tags=['品牌與商品'])

ComponentState = Literal['ok', 'sim', 'off', 'error']

#: 還是模擬版的外部服務（Plan 7 換成真實版）
SIMULATED = [
    ComponentStatus(id='comfyui', label='ComfyUI', status='sim', detail='模擬生圖：程序化背景'),
]
#: 系統狀態每一項最多等待的秒數
STATUS_TIMEOUT = 3
#: 文件上傳最多多久沒有進度（秒）：超過時回報錯誤，worker 仍會繼續處理。
#: 大份手冊向量化需要幾分鐘，只要持續有進度就不算逾時
INGEST_IDLE_TIMEOUT = 120
#: 上傳的商品照：MIME → 副檔名（與本機資料夾支援的格式相同）
UPLOAD_TYPES = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
LOCAL_TYPES = frozenset({'.png', '.jpg', '.jpeg', '.webp'})


def api_options(settings: Settings) -> ApiOptions:
    """AGENT_MODE=gemini 時為實際的模型 ID；模擬模式為與 mock 相同的名稱。"""
    if settings.agent_mode == 'gemini':
        return ApiOptions(llm=[settings.gemini_llm_model], vlm=[settings.gemini_vlm_model], engines=['comfyui'])
    return ApiOptions(llm=[settings.llm_model], vlm=[settings.vlm_model], engines=['comfyui'])


@router.get('/api/health')
async def health() -> dict[str, str]:
    """容器的健康檢查：api 啟動完成（migration 與品牌匯入都已執行）。"""
    return {'status': 'ok'}


@router.get('/api/options')
async def get_options(services: Services) -> ApiOptions:
    return api_options(services.settings)


async def _probe(id_: str, label: str, check: Awaitable[str | tuple[ComponentState, str]]) -> ComponentStatus:
    """check 回傳說明文字（狀態為 ok），或（狀態, 說明文字）；逾時或出錯時狀態為 error。"""
    try:
        result = await asyncio.wait_for(check, STATUS_TIMEOUT)
    except TimeoutError:
        return ComponentStatus(id=id_, label=label, status='error', detail=f'{STATUS_TIMEOUT} 秒內沒有回應')
    except Exception as error:  # noqa: BLE001 - 任何錯誤都顯示在系統狀態
        return ComponentStatus(id=id_, label=label, status='error', detail=failure_reason(error))
    status, detail = ('ok', result) if isinstance(result, str) else result
    return ComponentStatus(id=id_, label=label, status=status, detail=detail)


async def _db(services: ApiServices) -> str:
    async with services.db.session() as s:
        return f'PostgreSQL {await s.scalar(text("SHOW server_version"))}'


async def _redis(services: ApiServices) -> str:
    return f'Redis {(await services.redis.info("server"))["redis_version"]}'


async def _workers(services: ApiServices) -> str:
    info = await services.queues.jobs.info()
    if not info['workers']:
        raise Unavailable('沒有執行中的 worker：任務會停在排隊中')
    return f'{len(info["workers"])} 個 worker；排隊 {info["queued"]}、執行中 {info["active"]}'


async def _composer(services: ApiServices) -> str | tuple[ComponentState, str]:
    """composer 的 /health 與 REVIEW_MODE（api 與 worker 讀同一個設定）。
    composer 模式需要海報字型：沒有回報字型（舊版映像檔）時顯示 error，任務會在繪製審查用海報時失敗。"""
    url = services.composer.base_url
    health = await services.composer.health()
    if health is None:
        raise Unavailable(f'連不上 composer（{url}）')
    if services.settings.review_mode == 'sim':
        return 'sim', f'REVIEW_MODE=sim：模擬審查，不繪製審查用海報（{url}）'
    if not health.fonts:
        raise Invalid(f'REVIEW_MODE=composer，但 composer 沒有回報海報字型，請重新建置 composer（{url}）')
    return f'REVIEW_MODE=composer・字型：{"、".join(health.fonts)}（{url}）'


async def glyph_warnings(composer: ComposerClient, brands: list[Brand]) -> str:
    """品牌設定檔的預設文案、註記用語與替代用語中，海報字型沒有的字（會畫成方塊）。
    有缺字時回傳接在系統狀態說明後面的警告；composer 沒有回應時略過（不影響狀態）。"""
    texts: list[tuple[Brand, str]] = []
    for brand in brands:
        for preset in brand.copy_presets.values():
            texts += [(brand, line) for line in (*preset.headline, preset.subhead)]
        texts += [(brand, brand.disclaimer_phrase), *((brand, alt) for alt in brand.replacements.values())]
    try:
        missing = await composer.glyphs([text for _, text in texts])
    except ComposerError:
        return ''
    found: dict[str, list[str]] = {}
    for (brand, _), chars in zip(texts, missing, strict=True):
        known = found.setdefault(brand.name, [])
        known += [ch for ch in chars if ch not in known]
    return ''.join(
        f'；{name} 的預設文案或替代用語有伺服器字型沒有的字：「{"".join(chars)}」'
        for name, chars in found.items()
        if chars
    )


async def _brands(services: ApiServices) -> str:
    """品牌設定檔：載入數、格式錯誤而略過的檔案（error），以及預設文案的缺字（只加警告，不改變狀態）。"""
    async with services.db.session() as s:
        brands = await catalog.list_brands(s)
    warning = await glyph_warnings(services.composer, brands)
    if services.brand_errors:
        skipped = '；'.join(f'{e.file}：{e.message}' for e in services.brand_errors)
        raise Invalid(f'已載入 {len(brands)} 個品牌；略過 {skipped}{warning}')
    return f'已載入 {len(brands)} 個品牌{warning}'


async def _chroma(services: ApiServices) -> str | tuple[ComponentState, str]:
    """Chroma 的 heartbeat（只有 worker 寫入 Chroma，api 只檢查它是否回應）；正常時顯示網址。
    RAG_MODE=sim 時不檢查：模擬模式不連 Chroma，沒有啟動 Chroma 的環境（例如 live E2E）不該顯示錯誤。"""
    if services.settings.rag_mode == 'sim':
        return 'sim', '模擬模式不使用向量庫'
    url = services.settings.chroma_url.rstrip('/')
    try:
        async with httpx.AsyncClient(timeout=STATUS_TIMEOUT) as http:
            res = await http.get(f'{url}/api/v2/heartbeat')
    except httpx.HTTPError as error:
        raise Unavailable(f'連不上 Chroma（{url}）：{failure_reason(error)}') from error
    if res.status_code != 200:
        raise Unavailable(f'Chroma 回應 HTTP {res.status_code}（{url}）')
    return url


async def _gemini(services: ApiServices) -> str | tuple[ComponentState, str]:
    """AGENT_MODE=gemini：key、單價表與模型（models.get，不計費，結果快取 60 秒）都正常時，顯示模型、本月費用與上限、
    key 末 4 碼；任一項有問題時為 error 並說明原因。"""
    settings = services.settings
    if settings.agent_mode == 'sim':
        return 'sim', 'AGENT_MODE=sim：模擬 Agent 與 VLM 審查'
    gemini, ledger = services.gemini, services.ledger
    if gemini is None or not gemini.configured:
        raise GeminiError(NOT_CONFIGURED)
    llm, vlm = settings.gemini_llm_model, settings.gemini_vlm_model
    models = list(dict.fromkeys([llm, vlm]))
    if ledger is not None:
        if ledger.pricing.problem is not None:
            raise PricingError(ledger.pricing.problem)
        for model in models:
            ledger.pricing.price(model, utc_now())
    for model in models:
        await gemini.check_model(model)
    month = await ledger.month_total() if ledger is not None else 0
    cap = settings.gemini_monthly_budget_usd
    shown = f'LLM／VLM {llm}' if llm == vlm else f'LLM {llm}／VLM {vlm}'
    budget = f'上限 US${cap:g}' if cap > 0 else '不設上限'
    return f'{shown}・本月 {usd(month)}／{budget}・key {gemini.key_hint}'


@router.get('/api/status')
async def get_status(services: Services) -> SystemStatus:
    *probed, gemini, cutout = await asyncio.gather(
        _probe('db', 'PostgreSQL', _db(services)),
        _probe('redis', 'Redis（佇列與事件推送）', _redis(services)),
        _probe('worker', 'worker（SAQ）', _workers(services)),
        _probe('composer', 'composer（排版、繪製與規則審查）', _composer(services)),
        _probe('brands', '品牌設定檔', _brands(services)),
        _probe('chroma', '向量庫（Chroma）', _chroma(services)),
        _probe('rag', 'RAG 模型（BGE-M3＋Reranker）', _rag_model(services)),
        _probe('gemini', 'Gemini（LLM／VLM）', _gemini(services)),
        _probe('cutout', '去背模型（BiRefNet）', _cutout_model(services)),
    )
    return SystemStatus(components=[*probed, gemini, *SIMULATED, cutout])


async def _rag_model(services: ApiServices) -> tuple[ComponentState, str]:
    """worker 寫在 Redis 的 RAG 模型狀態（只讀 app.rag.state，api 不載入 onnxruntime）；
    讀不到、格式不對或不認得的狀態都顯示為 error，不能讓系統狀態整個失敗。"""
    raw = await services.redis.get(RAG_STATE_KEY)
    if raw is None:
        raise Unavailable('worker 尚未回報')
    try:
        state = json.loads(raw)
        name = state['state']
        shown: dict[str, tuple[ComponentState, str]] = {
            'sim': ('sim', '模擬檢索：固定的召回與 Rerank 順序'),
            'downloading': ('off', '第一次使用，正在下載模型（約 1.2 GB）'),
            'standby': ('ok', '模型已就緒，第一次檢索時載入'),
            'loading': ('off', '正在載入模型'),
            'ready': ('ok', 'bge-m3＋bge-reranker-v2-m3 已載入'),
            'failed': ('error', str(state.get('error') or 'RAG 模型準備失敗')),
        }
        return shown[name]
    except (ValueError, KeyError, TypeError) as error:
        raise Invalid('RAG 模型狀態無法辨識') from error


async def _cutout_model(services: ApiServices) -> tuple[ComponentState, str]:
    """worker 寫在 Redis 的去背模型狀態；讀不到、格式不對或不認得的狀態都顯示為 error，不能讓系統狀態整個失敗。"""
    raw = await services.redis.get(CUTOUT_STATE_KEY)
    if raw is None:
        raise Unavailable('worker 尚未回報')
    try:
        state = json.loads(raw)
        model, name = state['model'], state['state']
        shown: dict[str, tuple[ComponentState, str]] = {
            'ready': ('ok', f'{model} 已載入'),
            'loading': ('off', f'正在載入 {model}'),
            'downloading': ('off', '第一次使用，正在下載模型（約 1 GB）'),
            'failed': ('error', str(state.get('error') or '去背模型準備失敗')),
            'sim': ('sim', '模擬去背：中央的橢圓'),
        }
        return shown[name]
    except (ValueError, KeyError, TypeError) as error:
        raise Invalid('去背模型狀態無法辨識') from error


@router.get('/api/brands')
async def list_brands(services: Services) -> list[Brand]:
    async with services.db.session() as s:
        return await catalog.list_brands(s)


async def _ingest_lines(services: ApiServices, task_id: str, brand_id: str, name: str, text: str) -> AsyncIterator[str]:
    """先訂閱再放入佇列，才不會漏掉 worker 發布的訊息；收到 ingest.stored 或錯誤時結束。
    每收到一則進度就重新計算逾時：只有連續 INGEST_IDLE_TIMEOUT 秒沒有進度才算逾時。"""
    pubsub = services.redis.pubsub()
    await pubsub.subscribe(ingest_channel(task_id))
    try:
        await services.queues.enqueue_task('ingest', task_id=task_id, brand_id=brand_id, name=name, text=text)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + INGEST_IDLE_TIMEOUT
        while loop.time() < deadline:
            raw = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if raw is None:
                continue
            deadline = loop.time() + INGEST_IDLE_TIMEOUT
            yield raw['data'] + '\n'
            message = json.loads(raw['data'])
            if 'error' in message or message['type'] == 'ingest.stored':
                return
        message = (
            f'文件處理逾時：{INGEST_IDLE_TIMEOUT} 秒沒有任何進度。第一次使用時 worker 可能仍在下載 RAG 模型，'
            '請稍後再試；若持續發生，請確認 worker 正在執行'
        )
        yield json.dumps({'error': {'code': 'unavailable', 'message': message}}, ensure_ascii=False) + '\n'
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()  # type: ignore[no-untyped-call]


@router.post(
    '/api/brands/{brand_id}/documents',
    response_class=StreamingResponse,
    responses={200: {'content': {'application/x-ndjson': {}}, 'description': '每行一則 IngestEvent，或 { error }'}},
)
async def ingest_document(brand_id: str, file: UploadFile, services: Services) -> StreamingResponse:
    """上傳品牌手冊（multipart 的 file 欄位：.md、.txt、.pdf）：切塊 → 向量化 → 寫入知識庫，進度以 NDJSON 串流回報。

    檔案的問題（格式、大小、編碼、PDF 加密或沒有文字、切塊太多）在開始串流之前就回應錯誤；
    之後只把文字放進佇列，不傳原檔。
    """
    async with services.db.session() as s:
        if await catalog.get_brand(s, brand_id) is None:
            raise NotFound(f'找不到品牌：{brand_id}')
    name = document_name(file.filename or '')
    check_type(name)
    data = await file.read(MAX_DOCUMENT_BYTES + 1)
    text = await asyncio.to_thread(extract_text, name, data)
    # 切塊很快（20 萬字約幾十毫秒）；worker 會再切一次，這裡只檢查塊數，確保向量化在任務時限內完成
    chunks = len(await asyncio.to_thread(chunk_document, brand_id, name, text))
    if chunks > MAX_CHUNKS:
        raise Invalid(f'切塊太多（{chunks:,} 塊，上限 {MAX_CHUNKS:,}），請分成幾份上傳')
    lines = _ingest_lines(services, secrets.token_hex(8), brand_id, name, text)
    # nginx 預設會先緩衝回應；關掉才能一行一行送到前端
    return StreamingResponse(lines, media_type='application/x-ndjson', headers={'X-Accel-Buffering': 'no'})


@router.get('/api/templates')
async def list_templates() -> list[ChannelTemplate]:
    return CHANNEL_TEMPLATES


@router.get('/api/products')
async def list_products(services: Services, brand_id: Annotated[str, Query(alias='brandId')]) -> list[Product]:
    async with services.db.session() as s:
        return await catalog.list_products(s, brand_id)


async def _save(services: ApiServices, draft: ProductDraft) -> Product:
    """去背狀態由伺服器管理，請求中的 cutout 一律忽略：新的商品照（新增或換照片）設為去背中並排入佇列，
    其餘沿用原本的值（避免開著編輯視窗時完成的去背被蓋回去背中）。"""
    async with services.db.session() as s:
        if await catalog.get_brand(s, draft.brand_id) is None:
            raise Invalid(f'找不到品牌：{draft.brand_id}')
        previous = await catalog.get_product(s, draft.id, for_update=True) if draft.id else None
        photo = draft.photo if isinstance(draft.photo, FilePhoto) else None
        new_photo = photo is not None and (previous is None or previous.photo != photo)
        cutout: ProductCutout | None
        if photo is None:
            # 示範商品照已是去背素材：照片換成示範圖時，之前的去背結果也不再適用
            cutout = None
        elif new_photo:
            cutout = ProductCutout(model=services.settings.cutout_model, status='pending', url=None, error=None)
        else:
            cutout = previous.cutout if previous else None
        saved = await catalog.save_product(s, draft.model_copy(update={'cutout': cutout}), utc_now())
    if new_photo and photo is not None:
        await services.queues.enqueue_cutout(saved.id, photo.url)
    return saved


@router.post('/api/products', status_code=201)
async def create_product(draft: ProductDraft, services: Services) -> Product:
    if draft.id is not None:
        raise Invalid('新增商品時不可指定 id；修改請用 PUT /api/products/{id}')
    return await _save(services, draft)


@router.put('/api/products/{product_id}')
async def update_product(product_id: str, draft: ProductDraft, services: Services) -> Product:
    """修改商品；id 不存在時以這個 id 新增（與 mock 的 saveProduct 相同）。"""
    if draft.id not in (None, product_id):
        raise Invalid('網址與內容的商品 id 不一致')
    return await _save(services, draft.model_copy(update={'id': product_id}))


@router.delete('/api/products/{product_id}', status_code=204)
async def delete_product(product_id: str, services: Services) -> None:
    """刪除商品，連同 data/products/{id}/ 的去背圖。"""
    async with services.db.session() as s:
        if not await catalog.delete_product(s, product_id):
            raise NotFound(f'找不到商品：{product_id}')
    # 只刪 data/products/{id}/：id 格式不對時不刪（worker 也不會為這種 id 建資料夾）
    with contextlib.suppress(Invalid):
        folder = product_folder(services.settings, product_id)
        await asyncio.to_thread(shutil.rmtree, folder, ignore_errors=True)


@router.post('/api/products/photos', status_code=201)
async def upload_photo(file: UploadFile, services: Services) -> FilePhoto:
    """上傳商品照，存到 data/uploads/，回傳可放進 Product.photo 的參照。"""
    content_type = file.content_type or ''
    if not content_type.startswith('image/'):
        raise Invalid('只能上傳圖片檔')
    ext = UPLOAD_TYPES.get(content_type)
    if ext is None:
        raise Invalid('只支援 PNG、JPEG 與 WebP 圖片')
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise Invalid(f'圖片不可超過 {MAX_UPLOAD_BYTES // 1024 // 1024} MB')
    name = f'{secrets.token_hex(8)}{ext}'
    folder = services.settings.data_dir / 'uploads'
    await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread((folder / name).write_bytes, data)
    return FilePhoto(source='upload', url=f'/files/uploads/{name}')


async def queue_cutout(services: ApiServices, product_id: str, photo_url: str) -> Product:
    """設為去背中並排入 cutouts 佇列，立即回傳（前端在去背中時定時重新讀取商品清單）。"""
    pending = ProductCutout(model=services.settings.cutout_model, status='pending', url=None, error=None)
    async with services.db.session() as s:
        saved = await catalog.set_cutout(s, product_id, photo_url, pending)
    if saved is None:
        raise NotFound(f'找不到商品：{product_id}')
    await services.queues.enqueue_cutout(product_id, photo_url)
    return saved


@router.post('/api/products/{product_id}/cutout', status_code=202)
async def request_cutout(product_id: str, services: Services) -> Product:
    """重新去背。"""
    async with services.db.session() as s:
        product = await catalog.get_product(s, product_id)
    if product is None:
        raise NotFound(f'找不到商品：{product_id}')
    if not isinstance(product.photo, FilePhoto):
        raise Invalid('示範商品已是去背素材')
    return await queue_cutout(services, product_id, product.photo.url)


def local_photo_url(file: str) -> str:
    return f'/files/local/{quote(file, safe="")}'


def _local_name(file: str) -> str:
    """檔名去掉副檔名，底線與連字號換成空白（當商品名稱）。"""
    return re.sub(r'[_-]+', ' ', Path(file).stem).strip()


def _local_photo(settings: Settings, file: str) -> Path | None:
    """拒絕子目錄、隱藏檔與非圖片檔。"""
    if not file or '/' in file or '\\' in file or file.startswith('.') or Path(file).suffix.lower() not in LOCAL_TYPES:
        return None
    path = settings.local_photos_dir / file
    return path if path.is_file() else None


@router.get('/api/local-photos')
async def list_local_photos(services: Services) -> list[LocalPhoto]:
    """assets/products/ 的照片（依檔名排序）；資料夾不存在時回傳空陣列。"""
    folder = services.settings.local_photos_dir
    if not folder.is_dir():
        return []
    return [
        LocalPhoto(file=p.name, name=_local_name(p.name), url=local_photo_url(p.name), size=p.stat().st_size)
        for p in sorted(folder.iterdir(), key=lambda p: p.name)
        if _local_photo(services.settings, p.name) is not None
    ]


class ImportRequest(Model):
    brand_id: str


@router.post('/api/local-photos/{file}/import', status_code=201)
async def import_local_photo(file: str, body: ImportRequest, services: Services) -> Product:
    """把本機照片匯入成商品：檔名當商品名稱，價格與特徵之後在卡片上補。照片直接從唯讀的資料夾讀取。"""
    if _local_photo(services.settings, file) is None:
        raise NotFound(f'找不到本機照片：{file}')
    draft = ProductDraft(
        brand_id=body.brand_id,
        name=_local_name(file),
        features=[],
        price=Price(sale=0, original=0),
        photo=FilePhoto(source='local', url=local_photo_url(file)),
        cutout=None,
    )
    return await _save(services, draft)
