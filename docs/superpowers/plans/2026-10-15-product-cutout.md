# 商品照去背（BiRefNet）實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增商品時，worker 以 ONNX Runtime 執行 BiRefNet，自動產生透明 PNG；商品庫、預覽與海報合成都改用去背圖。

**Architecture:**
- 新的 `backend/app/cutout/` 負責前後處理、推論、模型下載與狀態。worker 在專用的 SAQ 佇列 `cutouts`（同時 1 個）執行去背，推論放在另一條執行緒。
- 去背狀態（`pending`／`done`／`failed`）存在商品資料裡，由伺服器管理。
- 前端在有商品去背中時，每 2 秒重新讀取商品清單。mock 模式模擬相同的狀態流程，不載入模型。

**Tech Stack:** ONNX Runtime 1.31、NumPy、Pillow、BiRefNet（rembg 的 ONNX 檔，MIT）、FastAPI、SAQ、SQLAlchemy／Alembic、Next.js 16、Zustand、Vitest、Playwright、Docker Compose。

**Spec:** `docs/superpowers/specs/2026-10-15-product-cutout-design.md`

## 開始前

- 在 `main` 上的分支 `feature/product-cutout` 執行；規格已經在這個分支上。
- 需要的工具：
  - Docker Desktop：映像檔取自 AWS 的官方映像鏡像，不必登入 Docker Hub。
  - uv 0.12 以上。
  - Node.js 24、npm 11。
- 後端的資料庫測試需要 `docker compose up -d --wait postgres redis`。
- `docker-compose.yml` 設定了 `name: genai-agent`。在 worktree 執行 `docker compose up` 會取代使用者正在用的整套服務，所以驗收時改用 Task 8 的獨立專案。
- Windows 注意事項：
  - 一律用 `127.0.0.1`，不要用 `localhost`。
  - Git Bash 的 heredoc 遇到含 `'''` 的 Python 程式碼可能解析失敗；這時改用檔案。

## 本計畫的驗證方式

本計畫的程式碼已在獨立副本（分支 `cutout-draft`）上逐 Task 實作並驗證：
- 每段程式碼都直接取自驗證過的版本。
- 每個 Task 都確認過三件事：
  - 「先寫測試」的步驟確實失敗，失敗方式與 Expected 相同。
  - 結束時全部通過，測試數量與 Expected 相同。
  - ruff、`ruff format --check`、mypy（strict）、tsc 與 ESLint 都沒有錯誤。
- 最後的結果：

| 項目 | 結果 |
|---|---|
| 後端 | 97 passed、1 skipped（真模型測試；有模型檔與照片時也通過） |
| 前端 | 42 個測試檔、330 個測試 |
| E2E | mock 5 個、live 6 個 |
| Docker 實機驗收（使用者的商品照，真正的 birefnet-general） | 第一次啟動 98 秒內下載並載入模型；建立商品到去背完成 15.9 秒；worker 平常 1.74 GiB，去背時取樣到的峰值 4.6 GiB；海報使用透明 PNG |

執行時若結果與 Expected 不同，先檢查是否漏了步驟，不要修改測試來配合。

## Global Constraints

- **指令在哪裡執行**：前端在 `web/`，後端在 `backend/`，`docker compose` 在 repo 根目錄。
- **後端**：
  - Python 3.13，以 uv 管理。
  - `uv run ruff check .`、`uv run ruff format --check .`（單引號、行寬 120）與 `uv run mypy`（strict）都必須通過。
- **前後端資料約定**：
  - `backend/app/contract.py` 與 `web/src/types/contract.ts` 的欄位名稱、型別、選填規則完全一致。
  - JSON 一律使用 camelCase；模型拒絕多餘欄位。
- **連線**：本機一律用 `127.0.0.1`。所有連接埠只綁定 `127.0.0.1`。
- **錯誤與文字**：
  - API 錯誤一律回傳 `{ error: { code, message } }`，message 為繁體中文。
  - UI 文字、錯誤訊息、註解都用繁體中文。
- **去背**：
  - 只在 worker 執行，api 不載入模型（也不匯入 onnxruntime）。
  - 同一時間只做一張。
  - 推論時關閉 ONNX Runtime 的記憶體池。
  - 去背狀態由伺服器管理，請求中的 `cutout` 一律忽略。
- **Plan 3 的前端規則**：
  - `getApiClient()` 只能在 client 端呼叫。
  - React Compiler 規則不得用 `eslint-disable` 繞過。
  - 不手動修改 `src/components/ui/*`。
- **Commit**：每個 Task 結束都要 commit，訊息最後一行加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。

## 實作時決定的細節（規格之外）

- **模型狀態多一個 `loading`**：模型檔已在、正在載入（約 15 秒）時回報 `loading`，系統狀態顯示「正在載入 birefnet-general」。規格 4.7 已同步更新。
- **`CutoutError` 繼承 `AppError`**：`failure_reason()` 直接顯示繁體中文訊息，例如「照片無法讀取」，不會加上例外的類別名稱。
- **`resolve_file` 移到 `backend/app/files.py`**：api 與 worker 共用，worker 不必匯入 api 的模組。照片網址轉成檔案的 `photo_path()` 也放在這裡。
- **狀態的 key 放在 `backend/app/cutout/state.py`**：api 只需要讀 key，不匯入 onnxruntime。
- **合約與資料庫遷移在同一個 Task（Task 1）**：合約一改，舊格式的商品就讀不出來。
- **「重新去背」API 在 Task 4 就改為排入佇列**：worker 的 `cutout` 任務簽名改變後，舊的同步呼叫無法運作。
- **遷移寫入的模型名稱**：遷移把待去背的商品寫成 `BiRefNet-general`（沿用舊名）。api 新排入的則是設定值，例如 `birefnet-general`。去背完成後一律改為實際執行的模型名稱。

## File Structure

| 檔案 | 責任 |
|---|---|
| `backend/app/cutout/processing.py` | 純函式：讀照片（EXIF 轉正）、前處理、後處理（sigmoid、min-max、透明度修正）、合成 PNG；`CutoutError` |
| `backend/app/cutout/segmenter.py` | `Segmenter` 介面；`OnnxSegmenter`（關閉記憶體池）、`SimSegmenter`（中央橢圓） |
| `backend/app/cutout/models.py` | 模型清單（網址、位元組數、SHA-256）、下載到 `.part` 後核對再改名 |
| `backend/app/cutout/engine.py` | `CutoutEngine`：準備模型（下載、載入）、回報狀態到 Redis、提供 Segmenter |
| `backend/app/cutout/state.py` | 狀態的 Redis key 與型別（api 也會讀） |
| `backend/app/files.py` | `/files/...` 網址與資料夾的對應（`resolve_file`、`photo_path`） |
| `backend/migrations/versions/0002_product_cutout_status.py` | 既有商品改為去背中 |
| `backend/app/queues.py` | `cutouts` 佇列、`cutout_key`、`enqueue_cutout`；`release_orphans` 也處理 `cutouts` |
| `backend/app/repo/catalog.py` | `set_cutout`（鎖定商品列並確認照片沒換）、`pending_cutouts` |
| `backend/app/worker.py` | `cutout` 任務、第三個 SAQ Worker、啟動時重新排入去背中的商品、背景準備模型 |
| `backend/app/api/catalog.py` | 新增與修改時決定去背狀態、`POST …/cutout` 回 202、刪除時刪資料夾、系統狀態的「去背模型」 |
| `web/src/lib/store/products.ts` | 去背中時每 2 秒重新讀取商品清單 |
| `web/src/lib/api/mock/client.ts` | mock 的去背：新增商品時去背中，約 1.2 秒後完成 |
| `web/src/components/product/*` | 商品卡的三種狀態、預覽的三種底色與重新去背、上傳提示 |

---

### Task 1：合約加上去背狀態，並遷移既有商品

**Files:**
- Create: `backend/migrations/versions/0002_product_cutout_status.py`
- Modify: `backend/app/contract.py`、`backend/app/worker.py`、`web/src/types/contract.ts`、`web/src/lib/api/mock/client.ts`
- Test: `backend/tests/test_contract.py`、`backend/tests/test_catalog.py`、`backend/tests/test_worker.py`、`backend/tests/test_api_catalog.py`、`web/src/lib/api/mock/client.test.ts`、`web/src/lib/compose/assets.test.ts`

**Interfaces:**
- Produces：
  - Python `CutoutStatus = Literal['pending', 'done', 'failed']`；`ProductCutout(model: str, status: CutoutStatus, url: str | None, error: str | None)`。
  - TS `CutoutStatus`、`ProductCutout { model; status; url; error }`。
  - Alembic revision `0002`（down_revision `0001`）。
  - 模擬去背（worker 的 `cutout`、mock 的 `requestCutout`）暫時回傳 `status: 'done'`、`url: null`；Task 4 與 Task 6 會改寫。

- [ ] **Step 1: 修改 `backend/tests/test_contract.py`（先寫測試）**

`backend/tests/test_contract.py`：

找到（1／2）：

```python
    JobStatusEvent,
    JobSummary,
    Product,
    RagHit,
    message_json,
    parse_event,
```

改成：

```python
    JobStatusEvent,
    JobSummary,
    Product,
    ProductCutout,
    RagHit,
    message_json,
    parse_event,
```

找到（2／2）：

```python

def test_channel_templates_match_the_frontend() -> None:
    assert [t.to_json() for t in CHANNEL_TEMPLATES] == load_fixture('brands.json')['templates']
```

改成：

```python

def test_channel_templates_match_the_frontend() -> None:
    assert [t.to_json() for t in CHANNEL_TEMPLATES] == load_fixture('brands.json')['templates']


def test_product_cutout_carries_status_and_error() -> None:
    raw = {'model': 'birefnet-general', 'status': 'failed', 'url': None, 'error': '照片無法讀取'}
    assert ProductCutout.model_validate(raw).to_json() == raw
    with pytest.raises(ValueError):
        ProductCutout.model_validate({'model': 'BiRefNet-general', 'url': None})
```

- [ ] **Step 2: 修改 `backend/tests/test_catalog.py`（先寫測試）**

`backend/tests/test_catalog.py`（遷移：先降到 0001 寫入舊格式的商品，再升級並確認；也確認可以 downgrade）：

找到（1／2）：

```python
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.brands import LoadedBrand, load_brands
from app.contract import FilePhoto, Price, ProductDraft, RagChunk
from app.repo import catalog
from tests.fixtures import BRANDS_DIR, load_fixture

T0 = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)
```

改成：

```python
import json
from datetime import UTC, datetime

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.brands import LoadedBrand, load_brands
from app.contract import FilePhoto, Price, ProductDraft, RagChunk
from app.db.session import Database
from app.repo import catalog
from app.settings import BACKEND_DIR
from tests.fixtures import BRANDS_DIR, load_fixture

T0 = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)
```

找到（2／2）：

```python
    assert await catalog.list_products(session, 'selune') == []
    assert await catalog.get_product(session, 'prod_selune_serum') is None
    assert [p.id for p in await catalog.list_products(session, 'misty-isle')] == ['prod_misty_coldbrew']
```

改成：

```python
    assert await catalog.list_products(session, 'selune') == []
    assert await catalog.get_product(session, 'prod_selune_serum') is None
    assert [p.id for p in await catalog.list_products(session, 'misty-isle')] == ['prod_misty_coldbrew']


async def alembic(db: Database, action: str, revision: str) -> None:
    """在測試資料庫上執行 alembic upgrade／downgrade。"""

    def run(connection: Connection) -> None:
        config = Config(str(BACKEND_DIR / 'alembic.ini'))
        config.attributes['connection'] = connection
        getattr(command, action)(config, revision)

    async with db.engine.begin() as connection:
        await connection.run_sync(run)


async def cutouts(session: AsyncSession) -> dict[str, object]:
    rows = await session.execute(text("SELECT id, data->'cutout' FROM products ORDER BY id"))
    return {product_id: cutout for product_id, cutout in rows.all()}


async def test_migration_0002_queues_photo_products_for_a_real_cutout(db: Database, session: AsyncSession) -> None:
    await catalog.sync_brands(session, demo_brands(), T0)
    await alembic(db, 'downgrade', '0001')
    try:
        # 0001 時代的商品：模擬去背過的上傳照、還沒去背的本機照片
        for product_id, source, cutout in [
            ('prod_old_upload', 'upload', {'model': 'BiRefNet-general', 'url': None}),
            ('prod_old_local', 'local', None),
        ]:
            data: dict[str, object] = {
                'id': product_id,
                'brandId': 'selune',
                'name': product_id,
                'features': [],
                'price': {'sale': 0, 'original': 0},
                'photo': {'source': source, 'url': f'/files/{product_id}.png'},
                'cutout': cutout,
                'createdAt': '2026-10-07T01:00:00.000Z',
            }
            await session.execute(
                text(
                    'INSERT INTO products (id, brand_id, data, sample, deleted, created_at) '
                    "VALUES (:id, 'selune', CAST(:data AS jsonb), false, false, :now)"
                ),
                {'id': product_id, 'data': json.dumps(data), 'now': T0},
            )
        await session.commit()
    finally:
        await alembic(db, 'upgrade', 'head')

    pending = {'model': 'BiRefNet-general', 'status': 'pending', 'url': None, 'error': None}
    assert await cutouts(session) == {
        'prod_misty_coldbrew': None,
        'prod_old_local': pending,
        'prod_old_upload': pending,
        'prod_selune_serum': None,
    }
    assert (await catalog.get_product(session, 'prod_old_upload')) is not None

    await alembic(db, 'downgrade', '0001')
    try:
        assert (await cutouts(session))['prod_old_upload'] == {'model': 'BiRefNet-general', 'url': None}
    finally:
        await alembic(db, 'upgrade', 'head')
```

- [ ] **Step 3: 修改 `backend/tests/test_worker.py`（先寫測試）**

`backend/tests/test_worker.py` 與 `backend/tests/test_api_catalog.py`：模擬去背的結果帶上 `status` 與 `error`。

找到：

```python
    async with running(services, queues):
        done = await queues.run_task('cutout', wait=10, product_id=product.id)
    assert done.completed
    assert done.result['product']['cutout'] == {'model': 'BiRefNet-general', 'url': None}
    assert await cutout(services, 'prod_selune_serum') == {'error': '示範商品已是去背素材'}
```

改成：

```python
    async with running(services, queues):
        done = await queues.run_task('cutout', wait=10, product_id=product.id)
    assert done.completed
    cut = done.result['product']['cutout']
    assert cut == {'model': 'BiRefNet-general', 'status': 'done', 'url': None, 'error': None}
    assert await cutout(services, 'prod_selune_serum') == {'error': '示範商品已是去背素材'}
```

- [ ] **Step 4: 修改 `backend/tests/test_api_catalog.py`（先寫測試）**

找到：

```python
    product = (await api.http.post('/api/products', json=DRAFT)).json()
    async with api.worker():
        res = await api.http.post(f'/api/products/{product["id"]}/cutout')
    assert res.json()['cutout'] == {'model': 'BiRefNet-general', 'url': None}
    listed = (await api.http.get('/api/products', params={'brandId': 'selune'})).json()
    assert listed[-1]['cutout'] == {'model': 'BiRefNet-general', 'url': None}
    sample = await api.http.post('/api/products/prod_selune_serum/cutout')
    assert sample.json() == {'error': {'code': 'invalid', 'message': '示範商品已是去背素材'}}
```

改成：

```python
    product = (await api.http.post('/api/products', json=DRAFT)).json()
    async with api.worker():
        res = await api.http.post(f'/api/products/{product["id"]}/cutout')
    assert res.json()['cutout'] == {'model': 'BiRefNet-general', 'status': 'done', 'url': None, 'error': None}
    listed = (await api.http.get('/api/products', params={'brandId': 'selune'})).json()
    assert listed[-1]['cutout'] == {'model': 'BiRefNet-general', 'status': 'done', 'url': None, 'error': None}
    sample = await api.http.post('/api/products/prod_selune_serum/cutout')
    assert sample.json() == {'error': {'code': 'invalid', 'message': '示範商品已是去背素材'}}
```

- [ ] **Step 5: 確認後端測試失敗**

Run: `uv run pytest -q tests/test_contract.py tests/test_catalog.py tests/test_worker.py::test_cutout_marks_uploaded_products_and_refuses_samples`（在 `backend/`）
Expected: FAIL，3 個測試失敗：
- `test_product_cutout_carries_status_and_error`：多餘欄位 `status` 被拒絕。
- `test_migration_0002_queues_photo_products_for_a_real_cutout`：還沒有 0002，`cutout` 不變。
- `test_cutout_marks_uploaded_products_and_refuses_samples`：結果沒有 `status` 與 `error`。

- [ ] **Step 6: 修改 `web/src/lib/api/mock/client.test.ts`（先寫測試）**

找到：

```ts
    expect(done).toBe(false);
    await vi.advanceTimersByTimeAsync(100);
    const product = await pending;
    expect(product.cutout).toEqual({ model: 'BiRefNet-general', url: null });
    expect(product.createdAt).toBe(saved.createdAt);
    expect((await api.listProducts('selune')).find((p) => p.id === saved.id)?.cutout).not.toBeNull();
    await expect(api.requestCutout('prod_selune_serum')).rejects.toThrow('示範商品已是去背素材');
```

改成：

```ts
    expect(done).toBe(false);
    await vi.advanceTimersByTimeAsync(100);
    const product = await pending;
    expect(product.cutout).toEqual({ model: 'BiRefNet-general', status: 'done', url: null, error: null });
    expect(product.createdAt).toBe(saved.createdAt);
    expect((await api.listProducts('selune')).find((p) => p.id === saved.id)?.cutout).not.toBeNull();
    await expect(api.requestCutout('prod_selune_serum')).rejects.toThrow('示範商品已是去背素材');
```

- [ ] **Step 7: 修改 `web/src/lib/compose/assets.test.ts`（先寫測試）**

找到：

```ts

  it('multiplies an uploaded photo until a real cutout exists', () => {
    expect(productImage(upload, SELUNE)).toEqual({ src: 'data:image/png;base64,AQID', blend: 'multiply' });
    expect(productImage({ ...upload, cutout: { model: 'BiRefNet-general', url: null } }, SELUNE).blend).toBe('multiply');
    expect(productImage({ ...upload, cutout: { model: 'BiRefNet-general', url: '/cutout.png' } }, SELUNE))
      .toEqual({ src: '/cutout.png', blend: 'normal' });
  });
});
```

改成：

```ts

  it('multiplies an uploaded photo until a real cutout exists', () => {
    expect(productImage(upload, SELUNE)).toEqual({ src: 'data:image/png;base64,AQID', blend: 'multiply' });
    expect(productImage({ ...upload, cutout: { model: 'BiRefNet-general', status: 'done', url: null, error: null } }, SELUNE).blend).toBe('multiply');
    expect(productImage({ ...upload, cutout: { model: 'BiRefNet-general', status: 'done', url: '/cutout.png', error: null } }, SELUNE))
      .toEqual({ src: '/cutout.png', blend: 'normal' });
  });
});
```

- [ ] **Step 8: 確認前端測試失敗**

Run: `npx vitest run src/lib/api/mock/client.test.ts src/lib/compose/assets.test.ts` 與 `npm run typecheck`（在 `web/`）
Expected:
- vitest：1 個測試失敗（`simulates a cutout after 1.2 seconds…`，結果沒有 `status` 與 `error`）。
- typecheck：`assets.test.ts` 出現 2 個 TS2353（`'status' does not exist in type 'ProductCutout'`）。

- [ ] **Step 9: 修改 `backend/app/contract.py`**

找到：

```python
ProductPhoto = Annotated[SamplePhoto | FilePhoto, Field(discriminator='source')]


class ProductCutout(Model):
    model: str
    url: str | None


class Price(Model):
```

改成：

```python
ProductPhoto = Annotated[SamplePhoto | FilePhoto, Field(discriminator='source')]


CutoutStatus = Literal['pending', 'done', 'failed']


class ProductCutout(Model):
    """去背結果：pending 去背中、done 完成（url 為透明 PNG；mock 的示意為 null）、failed 失敗（error 為原因）。"""

    model: str
    status: CutoutStatus
    url: str | None
    error: str | None


class Price(Model):
```

- [ ] **Step 10: 建立 `backend/migrations/versions/0002_product_cutout_status.py`**

```python
"""product cutout status

Revision ID: 0002
Revises: 0001

去背改為真正的 BiRefNet：ProductCutout 加上 status 與 error。
上傳與本機匯入的商品（含模擬去背過的）一律改為 pending，worker 啟動時會重新排入去背。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0002'
down_revision: str | Sequence[str] | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE products
            SET data = jsonb_set(
                data, '{cutout}',
                '{"model": "BiRefNet-general", "status": "pending", "url": null, "error": null}'::jsonb
            )
            WHERE data->'photo'->>'source' IN ('upload', 'local')
              AND data->'cutout'->>'status' IS NULL
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE products
            SET data = jsonb_set(data, '{cutout}', (data->'cutout') - 'status' - 'error')
            WHERE jsonb_typeof(data->'cutout') = 'object'
            """
        )
    )
```

- [ ] **Step 11: 修改 `backend/app/worker.py`**

找到：

```python
        return {'error': '示範商品已是去背素材'}
    await services.pace(1200)
    fields = {k: v for k, v in product.to_json().items() if k != 'createdAt'}
    cut = ProductCutout(model='BiRefNet-general', url=None)
    draft = ProductDraft.model_validate({**fields, 'cutout': cut.to_json()})
    async with services.db.session() as s:
        saved = await catalog.save_product(s, draft, utc_now())
```

改成：

```python
        return {'error': '示範商品已是去背素材'}
    await services.pace(1200)
    fields = {k: v for k, v in product.to_json().items() if k != 'createdAt'}
    cut = ProductCutout(model='BiRefNet-general', status='done', url=None, error=None)
    draft = ProductDraft.model_validate({**fields, 'cutout': cut.to_json()})
    async with services.db.session() as s:
        saved = await catalog.save_product(s, draft, utc_now())
```

- [ ] **Step 12: 修改 `web/src/types/contract.ts`**

找到：

```ts
  | { source: 'upload' | 'local'; url: string };

/** 去背結果。url 為 null 代表示意：mock 不真的去背，合成時以「色彩增值」讓白底融入背景 */
export interface ProductCutout { model: string; url: string | null }

export interface Product {
  id: string;
```

改成：

```ts
  | { source: 'upload' | 'local'; url: string };

/** 去背結果。url 為 null 代表示意：mock 不真的去背，合成時以「色彩增值」讓白底融入背景 */
/** 去背結果：pending 去背中、done 完成（url 為透明 PNG；mock 的示意為 null）、failed 失敗（error 為原因） */
export type CutoutStatus = 'pending' | 'done' | 'failed';
export interface ProductCutout { model: string; status: CutoutStatus; url: string | null; error: string | null }

export interface Product {
  id: string;
```

- [ ] **Step 13: 修改 `web/src/lib/api/mock/client.ts`**

找到：

```ts
    const product = await this.findProduct(productId);
    if (product.photo.source === 'sample') throw new Error('示範商品已是去背素材');
    await this.sleep(1200);
    return this.saveProduct({ ...product, cutout: { model: 'BiRefNet-general', url: null } });
  }

  async ingestBrandDocument(brandId: string, doc: BrandDocument, onEvent: (e: IngestEvent) => void): Promise<RagChunk[]> {
```

改成：

```ts
    const product = await this.findProduct(productId);
    if (product.photo.source === 'sample') throw new Error('示範商品已是去背素材');
    await this.sleep(1200);
    return this.saveProduct({ ...product, cutout: { model: 'BiRefNet-general', status: 'done', url: null, error: null } });
  }

  async ingestBrandDocument(brandId: string, doc: BrandDocument, onEvent: (e: IngestEvent) => void): Promise<RagChunk[]> {
```

- [ ] **Step 14: 確認全部通過**

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected：沒有錯誤；74 passed。

Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint`
Expected：41 個測試檔、325 個測試通過；沒有錯誤。

- [ ] **Step 15: Commit**

```bash
git add \
  backend/app/contract.py \
  backend/app/worker.py \
  backend/migrations/versions/0002_product_cutout_status.py \
  backend/tests/test_api_catalog.py \
  backend/tests/test_catalog.py \
  backend/tests/test_contract.py \
  backend/tests/test_worker.py \
  web/src/lib/api/mock/client.test.ts \
  web/src/lib/api/mock/client.ts \
  web/src/lib/compose/assets.test.ts \
  web/src/types/contract.ts
git commit -m "feat: give product cutouts a status and error and migrate existing products" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2：去背的前後處理與兩種實作（ONNX、模擬）

**Files:**
- Create: `backend/app/cutout/__init__.py`、`backend/app/cutout/processing.py`、`backend/app/cutout/segmenter.py`
- Modify: `backend/pyproject.toml`、`backend/uv.lock`（由 `uv add` 產生）
- Test: `backend/tests/test_cutout.py`

**Interfaces:**
- Produces：
  - `app.cutout.processing`：`INPUT_SIZE = 1024`、`MEAN`、`STD`、`OPAQUE_FROM = 242`、`CLEAR_UNTIL = 13`；`CutoutError(Exception)`（Task 4 改為繼承 `AppError`）；`load_photo(data: bytes) -> Image.Image`；`to_input(photo) -> NDArray[np.float32]`（1, 3, 1024, 1024）；`to_mask(output, size) -> Image.Image`（L）；`compose(photo, mask) -> bytes`（PNG）。
  - `app.cutout.segmenter`：`Segmenter` Protocol（`name: str`、`cut(photo: bytes) -> bytes`）；`OnnxSegmenter(name, model_path)`（屬性 `session`、`input_name`）；`SimSegmenter()`（`name = 'sim'`）。
  - 測試輔助函式 `tests/test_cutout.py` 的 `png(img)` 與 `tiny_model(path)`（Task 3 會匯入）。

- [ ] **Step 1: 加入相依套件**

在 `backend/` 執行（pyproject.toml 與 uv.lock 由 uv 修改）：

```bash
uv add 'onnxruntime>=1.31.0' 'numpy>=2.5.4' 'pillow>=12.3.0'
uv add --dev 'onnx>=1.23.2'
```

- [ ] **Step 2: 修改 `backend/pyproject.toml`**

onnxruntime 沒有附型別資訊，mypy 要略過它。

找到：

```toml
[[tool.mypy.overrides]]
module = ["asyncpg", "asyncpg.*"]
ignore_missing_imports = true
```

改成：

```toml
[[tool.mypy.overrides]]
module = ["asyncpg", "asyncpg.*"]
ignore_missing_imports = true

# onnxruntime 沒有附型別資訊
[[tool.mypy.overrides]]
module = ["onnxruntime", "onnxruntime.*"]
ignore_missing_imports = true
```

- [ ] **Step 3: 建立 `backend/tests/test_cutout.py`（先寫測試）**

建立 `backend/tests/test_cutout.py`。測試用 onnx 建立一個與 BiRefNet 輸入輸出相同的極小模型（三個色版取平均），不需要真正的模型：

```python
"""去背：前處理、後處理與兩種實作（模擬版、ONNX Runtime）。不需要資料庫，也不需要真正的模型。"""

import io
import math
from pathlib import Path

import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper
from PIL import Image

from app.cutout.processing import INPUT_SIZE, MEAN, STD, CutoutError, compose, load_photo, to_input, to_mask
from app.cutout.segmenter import OnnxSegmenter, SimSegmenter


def png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


def logit(p: float) -> float:
    return math.log(p / (1 - p))


def test_input_is_a_normalized_1024_square() -> None:
    x = to_input(Image.new('RGB', (40, 20), (255, 255, 255)))
    assert x.shape == (1, 3, INPUT_SIZE, INPUT_SIZE)
    assert x.dtype == np.float32
    for c in range(3):
        assert x[0, c, 0, 0] == pytest.approx((1 - MEAN[c]) / STD[c], rel=1e-5)


def test_photos_are_turned_upright_and_converted_to_rgb() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # 拍攝時轉了 90 度
    buf = io.BytesIO()
    Image.new('RGB', (20, 10), (200, 10, 10)).save(buf, 'JPEG', exif=exif)
    photo = load_photo(buf.getvalue())
    assert (photo.size, photo.mode) == ((10, 20), 'RGB')
    assert load_photo(png(Image.new('RGBA', (3, 3)))).mode == 'RGB'


def test_unreadable_photos_raise_a_readable_error() -> None:
    with pytest.raises(CutoutError, match='照片無法讀取'):
        load_photo(b'not an image')


def test_mask_is_resized_and_snaps_near_opaque_and_near_clear_values() -> None:
    # 五個區塊：幾乎透明、偏透明、一半、偏不透明、幾乎不透明
    bands = [-20.0, logit(0.03), 0.0, logit(0.97), 20.0]
    output = np.zeros((1, 1, INPUT_SIZE, INPUT_SIZE), dtype=np.float32)
    width = INPUT_SIZE // len(bands)
    for i, value in enumerate(bands):
        output[0, 0, :, i * width : (i + 1) * width] = value
    output[0, 0, :, len(bands) * width :] = bands[-1]
    mask = to_mask(output, (500, 100))
    assert (mask.size, mask.mode) == ((500, 100), 'L')
    centers = [int(np.asarray(mask)[50, i * 100 + 50]) for i in range(len(bands))]
    assert centers[0] == 0 and centers[1] == 0
    assert 120 <= centers[2] <= 135
    assert centers[3] == 255 and centers[4] == 255


def test_flat_output_does_not_divide_by_zero() -> None:
    mask = to_mask(np.full((1, 1, INPUT_SIZE, INPUT_SIZE), 20.0, dtype=np.float32), (8, 8))
    assert np.asarray(mask)[4, 4] == 255


def test_compose_keeps_the_photo_colors_and_uses_the_mask_as_alpha() -> None:
    photo = Image.new('RGB', (4, 2), (10, 20, 30))
    mask = Image.new('L', (4, 2), 0)
    mask.putpixel((3, 1), 255)
    out = Image.open(io.BytesIO(compose(photo, mask)))
    assert out.mode == 'RGBA'
    px = np.asarray(out)
    assert px[1, 3].tolist() == [10, 20, 30, 255]
    assert px[0, 0, 3] == 0


def test_sim_segmenter_cuts_a_centered_ellipse() -> None:
    out = Image.open(io.BytesIO(SimSegmenter().cut(png(Image.new('RGB', (60, 80), (90, 60, 120))))))
    assert (out.size, out.mode) == ((60, 80), 'RGBA')
    px = np.asarray(out)
    assert px[0, 0, 3] == 0
    assert px[40, 30].tolist() == [90, 60, 120, 255]


def tiny_model(path: Path) -> Path:
    """與 BiRefNet 相同的輸入輸出：output_image = 三個色版的平均（亮的地方是前景）。"""
    graph = helper.make_graph(
        [helper.make_node('ReduceMean', ['input_image'], ['output_image'], axes=[1], keepdims=1)],
        'tiny',
        [helper.make_tensor_value_info('input_image', TensorProto.FLOAT, [1, 3, INPUT_SIZE, INPUT_SIZE])],
        [helper.make_tensor_value_info('output_image', TensorProto.FLOAT, [1, 1, INPUT_SIZE, INPUT_SIZE])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 13)])
    model.ir_version = 8
    onnx.save(model, path)
    return path


def test_onnx_segmenter_runs_the_model_without_a_memory_arena(tmp_path: Path) -> None:
    segmenter = OnnxSegmenter('tiny', tiny_model(tmp_path / 'tiny.onnx'))
    options = segmenter.session.get_session_options()
    assert not options.enable_cpu_mem_arena
    assert not options.enable_mem_pattern
    photo = Image.new('RGB', (64, 32), (0, 0, 0))
    photo.paste((255, 255, 255), (32, 0, 64, 32))
    out = Image.open(io.BytesIO(segmenter.cut(png(photo))))
    assert (out.size, out.mode) == ((64, 32), 'RGBA')
    px = np.asarray(out)
    assert px[16, 8, 3] == 0
    assert px[16, 56].tolist() == [255, 255, 255, 255]
```

- [ ] **Step 4: 確認測試失敗**

Run: `uv run pytest -q tests/test_cutout.py`（在 `backend/`）
Expected: FAIL，收集時出錯：`ModuleNotFoundError: No module named 'app.cutout'`。

- [ ] **Step 5: 建立 `backend/app/cutout/__init__.py`**

```python
"""商品照去背：BiRefNet（ONNX Runtime）。worker 在 cutouts 佇列執行，api 不載入模型。"""
```

- [ ] **Step 6: 建立 `backend/app/cutout/processing.py`**

前後處理與實測時使用的 rembg 2.0.85 相同，另外加上透明度修正：

```python
"""去背的前處理與後處理（純函式）。

與實測時使用的 rembg 2.0.85 相同：縮成 1024×1024、除以像素最大值、以 ImageNet 的平均值與標準差正規化；
輸出經 sigmoid 與 min-max 正規化後縮回原尺寸。另外修正透明度：模型輸出的商品主體約為 98–99.6% 不透明，
接近不透明與接近透明的值直接設為 255 與 0，邊緣保留柔和的過渡。
"""

import io

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageOps, UnidentifiedImageError

INPUT_SIZE = 1024
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)
#: 遮罩值 ≥ 這個值視為完全不透明（95%）
OPAQUE_FROM = 242
#: 遮罩值 ≤ 這個值視為完全透明（5%）
CLEAR_UNTIL = 13


class CutoutError(Exception):
    """去背失敗；訊息為繁體中文，直接顯示在商品卡上。"""


def load_photo(data: bytes) -> Image.Image:
    """讀取照片，依 EXIF 轉正（手機照片常以 EXIF 記錄旋轉方向），轉成 RGB。"""
    try:
        with Image.open(io.BytesIO(data)) as img:
            upright = ImageOps.exif_transpose(img)
            return upright.convert('RGB')
    except (UnidentifiedImageError, OSError) as error:
        raise CutoutError('照片無法讀取') from error


def to_input(photo: Image.Image) -> NDArray[np.float32]:
    """照片 → 模型輸入（1, 3, 1024, 1024）。"""
    resized = photo.resize((INPUT_SIZE, INPUT_SIZE), Image.Resampling.LANCZOS)
    pixels = np.asarray(resized, dtype=np.float64)
    pixels = pixels / max(float(pixels.max()), 1e-6)
    normalized = (pixels - np.array(MEAN)) / np.array(STD)
    batch: NDArray[np.float32] = normalized.transpose(2, 0, 1)[np.newaxis].astype(np.float32)
    return batch


def to_mask(output: NDArray[np.float32], size: tuple[int, int]) -> Image.Image:
    """模型輸出（1, 1, 1024, 1024）→ 原尺寸的透明度遮罩（L）。"""
    pred = 1 / (1 + np.exp(-output[0, 0].astype(np.float64)))
    low, high = float(pred.min()), float(pred.max())
    if high - low > 1e-6:
        pred = (pred - low) / (high - low)
    mask = Image.fromarray((pred * 255).astype(np.uint8), mode='L').resize(size, Image.Resampling.LANCZOS)
    return mask.point(lambda v: 255 if v >= OPAQUE_FROM else 0 if v <= CLEAR_UNTIL else v)


def compose(photo: Image.Image, mask: Image.Image) -> bytes:
    """照片的顏色加上遮罩當透明度 → PNG。"""
    cut = photo.convert('RGBA')
    cut.putalpha(mask)
    buf = io.BytesIO()
    cut.save(buf, 'PNG')
    return buf.getvalue()
```

- [ ] **Step 7: 建立 `backend/app/cutout/segmenter.py`**

```python
"""去背的實作：照片（bytes）→ 透明 PNG（bytes）。同步執行，worker 以 asyncio.to_thread 呼叫。"""

from pathlib import Path
from typing import Protocol

import onnxruntime as ort
from PIL import Image, ImageDraw

from app.cutout.processing import compose, load_photo, to_input, to_mask


class Segmenter(Protocol):
    #: 寫進 ProductCutout.model 的名稱
    name: str

    def cut(self, photo: bytes) -> bytes: ...


class OnnxSegmenter:
    """BiRefNet（ONNX）。關閉 ONNX Runtime 的記憶體池：推論完立刻歸還記憶體（峰值約 6.5 GB，平常約 1.1 GB）。"""

    def __init__(self, name: str, model_path: Path) -> None:
        self.name = name
        options = ort.SessionOptions()
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        self.session = ort.InferenceSession(str(model_path), sess_options=options, providers=['CPUExecutionProvider'])
        self.input_name: str = self.session.get_inputs()[0].name

    def cut(self, photo: bytes) -> bytes:
        image = load_photo(photo)
        (output, *_) = self.session.run(None, {self.input_name: to_input(image)})
        return compose(image, to_mask(output, image.size))


class SimSegmenter:
    """模擬去背（測試與 live E2E）：中央的橢圓是前景，不需要模型。"""

    name = 'sim'

    def cut(self, photo: bytes) -> bytes:
        image = load_photo(photo)
        width, height = image.size
        mask = Image.new('L', image.size, 0)
        ImageDraw.Draw(mask).ellipse((width * 0.1, height * 0.05, width * 0.9, height * 0.95), fill=255)
        return compose(image, mask)
```

- [ ] **Step 8: 確認全部通過**

Run（在 `backend/`）：`uv run pytest -q tests/test_cutout.py -W error`
Expected：8 passed，沒有警告。

Run：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected：沒有錯誤；82 passed。

- [ ] **Step 9: Commit**

```bash
git add \
  backend/app/cutout/__init__.py \
  backend/app/cutout/processing.py \
  backend/app/cutout/segmenter.py \
  backend/pyproject.toml \
  backend/tests/test_cutout.py \
  backend/uv.lock
git commit -m "feat: cut out product photos with BiRefNet on ONNX Runtime" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3：模型下載、核對、載入與狀態

**Files:**
- Create: `backend/app/cutout/models.py`、`backend/app/cutout/engine.py`
- Modify: `backend/app/settings.py`、`backend/pyproject.toml`、`.gitignore`
- Test: `backend/tests/test_cutout_engine.py`、`backend/tests/test_cutout_model.py`

**Interfaces:**
- Consumes：Task 2 的 `CutoutError`、`OnnxSegmenter`、`SimSegmenter`、`Segmenter`；測試輔助函式 `png`、`tiny_model`。
- Produces：
  - `Settings.cutout_model: str = 'birefnet-general'`、`Settings.models_dir: Path = REPO_ROOT / 'models'`。
  - `app.cutout.models`：`ModelFile(name, url, size, sha256)`（`filename` 為 `{name}.onnx`）；`MODELS`（`birefnet-general`、`birefnet-general-lite`）；`has_model(model, models_dir) -> bool`；`async ensure_model(model, models_dir, http) -> Path`。
  - `app.cutout.engine`：
    - `CutoutEngine(model, models_dir, redis, *, models=MODELS, http=…, on_state=None)`。
    - 方法：`async segmenter() -> Segmenter`（失敗時丟出 `CutoutError`，下一次呼叫重試）；`async warm_up()`。
    - 屬性 `model`。
    - Redis key `cutout:model` 的內容為 `{"model", "state", "error"}`，`state` 是 `downloading`、`loading`、`ready`、`failed` 或 `sim`。Task 5 會把 key 與型別移到 `app/cutout/state.py`。

- [ ] **Step 1: 建立 `backend/tests/test_cutout_engine.py`（先寫測試）**

建立 `backend/tests/test_cutout_engine.py`。下載由 `httpx.MockTransport` 提供，不連外網：

```python
"""去背模型：下載與核對、載入、回報狀態到 Redis。下載都由假的 HTTP 回應提供，不連外網。"""

import hashlib
import io
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from PIL import Image
from redis.asyncio import Redis

from app.cutout.engine import STATE_KEY, CutoutEngine
from app.cutout.models import ModelFile, ensure_model
from app.cutout.processing import CutoutError
from app.cutout.segmenter import OnnxSegmenter, SimSegmenter
from tests.test_cutout import png, tiny_model

URL = 'https://models.test/tiny.onnx'


def model_file(content: bytes, name: str = 'tiny') -> ModelFile:
    return ModelFile(name=name, url=URL, size=len(content), sha256=hashlib.sha256(content).hexdigest())


def serve(content: bytes, status: int = 200) -> tuple[Callable[[], httpx.AsyncClient], list[str]]:
    """假的模型伺服器：回傳建立 client 的函式，以及收到的請求網址。"""
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(status, content=content)

    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)), requests


async def state(redis: Redis) -> dict[str, object]:
    raw = await redis.get(STATE_KEY)
    assert raw is not None
    loaded: dict[str, object] = json.loads(raw)
    return loaded


async def test_downloads_into_a_part_file_and_renames_after_the_checksum(tmp_path: Path) -> None:
    content = b'model bytes' * 100
    client, requests = serve(content)
    async with client() as http:
        path = await ensure_model(model_file(content), tmp_path / 'models', http)
    assert path == tmp_path / 'models' / 'tiny.onnx'
    assert path.read_bytes() == content
    assert requests == [URL]
    assert list((tmp_path / 'models').iterdir()) == [path]

    # 已有正確的檔案：不再下載
    async with client() as http:
        assert await ensure_model(model_file(content), tmp_path / 'models', http) == path
    assert requests == [URL]


async def test_a_corrupt_download_leaves_nothing_behind(tmp_path: Path) -> None:
    client, _ = serve(b'truncated')
    with pytest.raises(CutoutError, match='SHA-256'):
        async with client() as http:
            await ensure_model(model_file(b'the real model'), tmp_path, http)
    assert list(tmp_path.iterdir()) == []


async def test_http_errors_are_reported_in_chinese(tmp_path: Path) -> None:
    client, _ = serve(b'', status=503)
    with pytest.raises(CutoutError, match='去背模型下載失敗'):
        async with client() as http:
            await ensure_model(model_file(b'x'), tmp_path, http)


async def test_sim_engine_needs_no_model(redis: Redis, tmp_path: Path) -> None:
    await redis.delete(STATE_KEY)
    engine = CutoutEngine('sim', tmp_path, redis)
    assert isinstance(await engine.segmenter(), SimSegmenter)
    assert await state(redis) == {'model': 'sim', 'state': 'sim', 'error': None}


async def test_downloads_loads_and_reports_each_state(redis: Redis, tmp_path: Path) -> None:
    content = tiny_model(tmp_path / 'source.onnx').read_bytes()
    client, requests = serve(content)
    seen: list[object] = []

    async def record(message: dict[str, object]) -> None:
        seen.append(message['state'])

    models = {'tiny': model_file(content)}
    engine = CutoutEngine('tiny', tmp_path / 'models', redis, models=models, http=client, on_state=record)
    segmenter = await engine.segmenter()
    assert isinstance(segmenter, OnnxSegmenter)
    assert await engine.segmenter() is segmenter
    assert seen == ['downloading', 'loading', 'ready']
    assert await state(redis) == {'model': 'tiny', 'state': 'ready', 'error': None}
    assert len(requests) == 1
    assert Image.open(io.BytesIO(segmenter.cut(png(Image.new('RGB', (8, 8)))))).mode == 'RGBA'

    # 第二個 worker：檔案已在，只載入
    again = CutoutEngine('tiny', tmp_path / 'models', redis, models=models, http=client, on_state=record)
    await again.segmenter()
    assert seen[3:] == ['loading', 'ready']
    assert len(requests) == 1


async def test_a_failed_download_is_reported_and_retried_on_the_next_cutout(redis: Redis, tmp_path: Path) -> None:
    content = tiny_model(tmp_path / 'source.onnx').read_bytes()
    replies = [httpx.Response(503), httpx.Response(200, content=content)]

    def handler(request: httpx.Request) -> httpx.Response:
        return replies.pop(0)

    engine = CutoutEngine(
        'tiny',
        tmp_path / 'models',
        redis,
        models={'tiny': model_file(content)},
        http=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(CutoutError, match='去背模型下載失敗'):
        await engine.segmenter()
    failed = await state(redis)
    assert failed['state'] == 'failed'
    assert '去背模型下載失敗' in str(failed['error'])
    assert isinstance(await engine.segmenter(), OnnxSegmenter)
    assert (await state(redis))['state'] == 'ready'


async def test_unknown_models_fail_with_the_supported_names(redis: Redis, tmp_path: Path) -> None:
    engine = CutoutEngine('u2net', tmp_path, redis)
    with pytest.raises(CutoutError, match='birefnet-general'):
        await engine.segmenter()


def test_registry_lists_the_benchmarked_models() -> None:
    from app.cutout.models import MODELS

    assert {name: (m.size, m.sha256[:12]) for name, m in MODELS.items()} == {
        'birefnet-general': (972666916, '58f621f00f5d'),
        'birefnet-general-lite': (224005088, '5600024376f5'),
    }
```

- [ ] **Step 2: 建立 `backend/tests/test_cutout_model.py`（先寫測試）**

建立 `backend/tests/test_cutout_model.py`。這是真模型測試，沒有模型檔或 `CUTOUT_TEST_PHOTO` 時略過：

```python
"""真正的 BiRefNet：只在本機已有模型檔（models/）且以 CUTOUT_TEST_PHOTO 指定商品照時執行，否則略過。

照片的商品要在畫面中央、四個角是背景，例如：
    CUTOUT_TEST_PHOTO=../data/uploads/xxx.jpg uv run pytest -m model
"""

import io
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.cutout.models import MODELS
from app.cutout.segmenter import OnnxSegmenter
from app.settings import settings

MODEL = MODELS.get(settings.cutout_model, MODELS['birefnet-general'])
PATH = settings.models_dir / MODEL.filename
PHOTO = os.environ.get('CUTOUT_TEST_PHOTO')

pytestmark = [
    pytest.mark.model,
    pytest.mark.skipif(not PATH.is_file() or not PHOTO, reason='需要 models/ 的模型檔與 CUTOUT_TEST_PHOTO'),
]


def test_real_model_keeps_the_product_and_clears_the_corners() -> None:
    assert PHOTO is not None
    cut = OnnxSegmenter(MODEL.name, PATH).cut(Path(PHOTO).read_bytes())
    alpha = np.asarray(Image.open(io.BytesIO(cut)))[:, :, 3]
    h, w = alpha.shape
    assert [alpha[2, 2], alpha[2, w - 3], alpha[h - 3, 2], alpha[h - 3, w - 3]] == [0, 0, 0, 0]
    assert alpha[h // 2, w // 2] == 255
```

- [ ] **Step 3: 確認測試失敗**

Run: `uv run pytest -q tests/test_cutout_engine.py`（在 `backend/`）
Expected: FAIL，收集時出錯：`ModuleNotFoundError: No module named 'app.cutout.engine'`。

- [ ] **Step 4: 修改 `backend/app/settings.py`**

找到：

```python
    llm_model: str = 'Gemini 3.7 Flash'
    vlm_model: str = 'Gemini 3.7 Vision'

    #: 模擬模式的播放速度（1 為 1× 時間軸，約 15 秒一個任務；0 為不等待）
    sim_speed: float = 1.0
    #: 模擬模式：第一輪刻意失誤（觸發 Query Rewriting）
```

改成：

```python
    llm_model: str = 'Gemini 3.7 Flash'
    vlm_model: str = 'Gemini 3.7 Vision'

    #: 去背模型：birefnet-general（預設）、birefnet-general-lite，或不需要模型的 sim（測試與 live E2E）
    cutout_model: str = 'birefnet-general'
    #: 去背模型的存放位置（Docker 為 models volume）
    models_dir: Path = REPO_ROOT / 'models'

    #: 模擬模式的播放速度（1 為 1× 時間軸，約 15 秒一個任務；0 為不等待）
    sim_speed: float = 1.0
    #: 模擬模式：第一輪刻意失誤（觸發 Query Rewriting）
```

- [ ] **Step 5: 修改 `backend/pyproject.toml`**

找到：

```toml
asyncio_default_test_loop_scope = "session"
# SAQ 0.26 在 redis-py 8 上呼叫已棄用的 setex
filterwarnings = ["ignore:Call to deprecated setex:DeprecationWarning"]

[tool.ruff]
line-length = 120
```

改成：

```toml
asyncio_default_test_loop_scope = "session"
# SAQ 0.26 在 redis-py 8 上呼叫已棄用的 setex
filterwarnings = ["ignore:Call to deprecated setex:DeprecationWarning"]
markers = ["model: 需要真正的去背模型檔（models/）與 CUTOUT_TEST_PHOTO 指定的照片，沒有時略過"]

[tool.ruff]
line-length = 120
```

- [ ] **Step 6: 修改 `.gitignore`**

找到：

```text

# 後端執行時資料（商品照、生成圖、審查用海報）
/data/
```

改成：

```text

# 後端執行時資料（商品照、生成圖、審查用海報）
/data/

# 去背模型（第一次去背時下載，約 1 GB）
/models/
```

- [ ] **Step 7: 建立 `backend/app/cutout/models.py`**

```python
"""去背模型的清單、下載與核對。

模型取自 rembg 的 GitHub releases（BiRefNet，MIT 授權）；位元組數與 SHA-256 是 2026-10-15 實測時下載的檔案。
"""

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.cutout.processing import CutoutError

RELEASES = 'https://github.com/danielgatis/rembg/releases/download/v0.0.0'
#: 下載時每次讀取的位元組數
CHUNK = 1 << 20


@dataclass(frozen=True)
class ModelFile:
    name: str
    url: str
    size: int
    sha256: str

    @property
    def filename(self) -> str:
        return f'{self.name}.onnx'


MODELS: dict[str, ModelFile] = {
    'birefnet-general': ModelFile(
        'birefnet-general',
        f'{RELEASES}/BiRefNet-general-epoch_244.onnx',
        972666916,
        '58f621f00f5d756097615970a88a791584600dcf7c45b18a0a6267535a1ebd3c',
    ),
    'birefnet-general-lite': ModelFile(
        'birefnet-general-lite',
        f'{RELEASES}/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx',
        224005088,
        '5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333',
    ),
}


def _matches(path: Path, model: ModelFile) -> bool:
    if path.stat().st_size != model.size:
        return False
    digest = hashlib.sha256()
    with path.open('rb') as f:
        while block := f.read(CHUNK):
            digest.update(block)
    return digest.hexdigest() == model.sha256


def has_model(model: ModelFile, models_dir: Path) -> bool:
    """已有大小與 SHA-256 都正確的檔案。"""
    path = models_dir / model.filename
    return path.is_file() and _matches(path, model)


async def ensure_model(model: ModelFile, models_dir: Path, http: httpx.AsyncClient) -> Path:
    """回傳模型檔的路徑；沒有正確的檔案時先下載到 .part，核對大小與 SHA-256 後才改名。"""
    target = models_dir / model.filename
    if await asyncio.to_thread(has_model, model, models_dir):
        return target
    models_dir.mkdir(parents=True, exist_ok=True)
    part = models_dir / f'{model.filename}.part'
    digest = hashlib.sha256()
    size = 0
    try:
        async with http.stream('GET', model.url, follow_redirects=True) as res:
            res.raise_for_status()
            with part.open('wb') as f:
                async for chunk in res.aiter_bytes(CHUNK):
                    f.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
        if size != model.size or digest.hexdigest() != model.sha256:
            raise CutoutError(f'去背模型下載不完整（{model.name}）：檔案大小或 SHA-256 不符')
        part.replace(target)
    except httpx.HTTPError as error:
        raise CutoutError(f'去背模型下載失敗：{error}') from error
    finally:
        part.unlink(missing_ok=True)
    return target
```

- [ ] **Step 8: 建立 `backend/app/cutout/engine.py`**

```python
"""worker 持有的去背引擎：準備模型（下載、載入）、把狀態寫到 Redis（系統狀態顯示）、提供 Segmenter。"""

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Literal

import httpx
from redis.asyncio import Redis

from app.cutout.models import MODELS, ModelFile, ensure_model, has_model
from app.cutout.processing import CutoutError
from app.cutout.segmenter import OnnxSegmenter, Segmenter, SimSegmenter

#: worker 回報模型狀態的 Redis key（api 的系統狀態讀取）
STATE_KEY = 'cutout:model'
#: 下載模型的逾時（秒）：連線與兩次讀取之間的間隔
DOWNLOAD_TIMEOUT = 60

ModelState = Literal['downloading', 'loading', 'ready', 'failed', 'sim']


class CutoutEngine:
    def __init__(
        self,
        model: str,
        models_dir: Path,
        redis: Redis,
        *,
        models: Mapping[str, ModelFile] = MODELS,
        http: Callable[[], httpx.AsyncClient] = lambda: httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT),
        on_state: Callable[[dict[str, object]], Awaitable[None]] | None = None,
    ) -> None:
        self.model = model
        self.models_dir = models_dir
        self.redis = redis
        self.models = models
        self.http = http
        self.on_state = on_state
        self._segmenter: Segmenter | None = None
        # 同一時間只準備一次；準備中的其他去背任務在這裡等
        self._lock = asyncio.Lock()

    async def segmenter(self) -> Segmenter:
        """等模型準備好。上一次準備失敗時重新嘗試；仍然失敗就丟出 CutoutError。"""
        async with self._lock:
            if self._segmenter is None:
                try:
                    self._segmenter = await self._prepare()
                except CutoutError as error:
                    await self._report('failed', str(error))
                    raise
            return self._segmenter

    async def warm_up(self) -> None:
        """worker 啟動時在背景準備模型；失敗只記錄狀態，下一次去背時再試。"""
        with contextlib.suppress(CutoutError):
            await self.segmenter()

    async def _prepare(self) -> Segmenter:
        if self.model == 'sim':
            await self._report('sim')
            return SimSegmenter()
        model = self.models.get(self.model)
        if model is None:
            supported = '、'.join([*self.models, 'sim'])
            raise CutoutError(f'不支援的去背模型：{self.model}（可用：{supported}）')
        if not await asyncio.to_thread(has_model, model, self.models_dir):
            await self._report('downloading')
            async with self.http() as http:
                await ensure_model(model, self.models_dir, http)
        await self._report('loading')
        segmenter = await asyncio.to_thread(OnnxSegmenter, model.name, self.models_dir / model.filename)
        await self._report('ready')
        return segmenter

    async def _report(self, state: ModelState, error: str | None = None) -> None:
        message: dict[str, object] = {'model': self.model, 'state': state, 'error': error}
        await self.redis.set(STATE_KEY, json.dumps(message, ensure_ascii=False))
        if self.on_state is not None:
            await self.on_state(message)
```

- [ ] **Step 9: 確認全部通過**

Run（在 `backend/`）：`uv run pytest -q tests/test_cutout_engine.py -W error`
Expected：8 passed，沒有警告。

Run：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected：沒有錯誤；90 passed、1 skipped（`test_cutout_model.py`）。

- [ ] **Step 10（選做）: 真模型測試**

本機已有 `models/birefnet-general.onnx`（例如從 Task 8 的驗收複製出來）時，可以用一張商品在中央的照片執行：

```bash
CUTOUT_TEST_PHOTO='C:\path\to\photo.jpg' uv run pytest -q -m model
```

Expected：1 passed，約 20 秒（含載入模型）。

- [ ] **Step 11: Commit**

```bash
git add \
  .gitignore \
  backend/app/cutout/engine.py \
  backend/app/cutout/models.py \
  backend/app/settings.py \
  backend/pyproject.toml \
  backend/tests/test_cutout_engine.py \
  backend/tests/test_cutout_model.py
git commit -m "feat: download, verify and load the cutout model and report its state" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4：`cutouts` 佇列、worker 的去背任務與啟動時復原

**Files:**
- Create: `backend/app/files.py`
- Modify: `backend/app/api/files.py`、`backend/app/api/catalog.py`、`backend/app/cutout/processing.py`、`backend/app/queues.py`、`backend/app/repo/catalog.py`、`backend/app/worker.py`
- Test: `backend/tests/conftest.py`、`backend/tests/test_worker.py`、`backend/tests/test_api_catalog.py`

**Interfaces:**
- Consumes：Task 3 的 `CutoutEngine`；Task 1 的 `ProductCutout`。
- Produces：
  - `app.files`：`FILE_TYPES`、`resolve_file(settings, path) -> Path | None`、`photo_path(settings, url) -> Path`（找不到時丟出 `NotFound('找不到商品照：…')`）。
  - `app.queues`：`CUTOUTS = 'cutouts'`、`CUTOUT_TIMEOUT = 600`、`cutout_key(product_id, photo_url) -> str`、`Queues.cutouts`、`Queues.enqueue_cutout(product_id, photo_url)`；`Queues.release_orphans` 同時處理 `jobs` 與 `cutouts`。
  - `app.repo.catalog`：`set_cutout(session, product_id, photo_url, cutout) -> Product | None`（照片網址不同或商品已刪除時不寫入）、`pending_cutouts(session) -> list[Product]`。
  - `app.worker`：
    - `Services` 新增 `settings: Settings` 與 `cutouts: CutoutEngine` 兩個欄位。
    - `async cutout(services, product_id, photo_url) -> None`。
    - `build_workers()` 回傳 `(jobs, tasks, cutouts)`，同時處理的數量依序為 1、2、1。
  - `app.api.catalog.queue_cutout(services, product_id, photo_url) -> Product`；`POST /api/products/{id}/cutout` 回 202。

- [ ] **Step 1: 修改 `backend/tests/conftest.py`（先寫測試）**

`backend/tests/conftest.py`（`LiveApi.worker` 與 api 共用測試的 `data/`，去背用模擬版）：

找到（1／2）：

```python
from app.adapters.composer import ComposerClient
from app.api.main import create_app
from app.api.services import ApiServices
from app.db.session import Database
from app.events import EventStore
from app.pipeline.sim import SimAgent, sim_ports
```

改成：

```python
from app.adapters.composer import ComposerClient
from app.api.main import create_app
from app.api.services import ApiServices
from app.cutout.engine import CutoutEngine
from app.db.session import Database
from app.events import EventStore
from app.pipeline.sim import SimAgent, sim_ports
```

找到（2／2）：

```python
        s = self.services
        composer = ComposerClient(self.composer_url)
        ports = sim_ports(composer, first_round_fail=True, force_all_fail=False)
        workers = build_workers(WorkerServices(s.db, s.redis, s.store, composer, ports, speed), s.queues)
        started = [asyncio.create_task(w.start()) for w in workers]
        try:
            yield
```

改成：

```python
        s = self.services
        composer = ComposerClient(self.composer_url)
        ports = sim_ports(composer, first_round_fail=True, force_all_fail=False)
        cutouts = CutoutEngine('sim', s.settings.data_dir / 'models', s.redis)
        worker_services = WorkerServices(s.db, s.redis, s.store, composer, ports, speed, s.settings, cutouts)
        workers = build_workers(worker_services, s.queues)
        started = [asyncio.create_task(w.start()) for w in workers]
        try:
            yield
```

- [ ] **Step 2: 修改 `backend/tests/test_worker.py`（先寫測試）**

`backend/tests/test_worker.py`：
- 移除舊的模擬去背測試，改為新的去背任務測試：寫入 PNG、照片無法讀取、本機照片、途中換照片、啟動時復原。
- 同一張照片重複排入只排一次。
- 釋放殘留紀錄時的 log 改為只寫 key。

找到（1／4）：

```python
"""worker：任務經過佇列執行、啟動時復原、去背、品牌文件上傳、回寫。需要 composer。"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from redis.asyncio import Redis
from saq.job import Status

from app.adapters.composer import ComposerClient
from app.brands import load_brands
from app.contract import FilePhoto, JobAcceptedEvent, JobInput, JobStatusEvent, Price, ProductDraft
from app.db.session import Database
from app.events import EventStore
from app.pipeline.sim import sim_ports
from app.queues import Queues, ingest_channel
from app.repo import catalog, jobs
from app.worker import RESTART_REASON, Services, build_workers, cutout, ingest, recover
from tests.conftest import TEST_REDIS_URL
from tests.fixtures import BRANDS_DIR, load_fixture
```

改成：

```python
"""worker：任務經過佇列執行、啟動時復原、去背、品牌文件上傳、回寫。需要 composer。"""

import asyncio
import io
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import numpy as np
import pytest
from PIL import Image
from redis.asyncio import Redis
from saq.job import Status

from app.adapters.composer import ComposerClient
from app.brands import load_brands
from app.contract import (
    FilePhoto,
    JobAcceptedEvent,
    JobInput,
    JobStatusEvent,
    Price,
    Product,
    ProductCutout,
    ProductDraft,
)
from app.cutout.engine import CutoutEngine
from app.cutout.segmenter import Segmenter, SimSegmenter
from app.db.session import Database
from app.events import EventStore
from app.pipeline.sim import sim_ports
from app.queues import Queues, cutout_key, ingest_channel
from app.repo import catalog, jobs
from app.settings import Settings
from app.worker import RESTART_REASON, Services, build_workers, cutout, ingest, recover
from tests.conftest import TEST_REDIS_URL
from tests.fixtures import BRANDS_DIR, load_fixture
```

找到（2／4）：

```python


@pytest.fixture
async def services(db: Database, redis: Redis, composer_url: str) -> AsyncIterator[Services]:
    composer = ComposerClient(composer_url)
    ports = sim_ports(composer, first_round_fail=True, force_all_fail=False)
    async with db.session() as s:
        await catalog.sync_brands(s, load_brands(BRANDS_DIR)[0], NOW)
    yield Services(db, redis, EventStore(db, redis), composer, ports, speed=0)
    await composer.aclose()
    await db.truncate_all()
```

改成：

```python


@pytest.fixture
async def services(db: Database, redis: Redis, composer_url: str, tmp_path: Path) -> AsyncIterator[Services]:
    composer = ComposerClient(composer_url)
    ports = sim_ports(composer, first_round_fail=True, force_all_fail=False)
    async with db.session() as s:
        await catalog.sync_brands(s, load_brands(BRANDS_DIR)[0], NOW)
    settings = Settings(data_dir=tmp_path / 'data', local_photos_dir=tmp_path / 'local')
    cutouts = CutoutEngine('sim', tmp_path / 'models', redis)
    yield Services(db, redis, EventStore(db, redis), composer, ports, speed=0, settings=settings, cutouts=cutouts)
    await composer.aclose()
    await db.truncate_all()
```

找到（3／4）：

```python
    assert await queues.jobs.count('active') == 0
    # worker 上次是當掉的：每放掉一筆紀錄記一則警告
    assert [r.getMessage() for r in caplog.records if r.name == 'app.worker'] == [
        '釋放前一個 worker 留下的佇列紀錄：job_id=job_dead'
    ]
    assert (await summary(services, 'job_dead')).stage == 'failed'
    # 其他狀態的紀錄不動
```

改成：

```python
    assert await queues.jobs.count('active') == 0
    # worker 上次是當掉的：每放掉一筆紀錄記一則警告
    assert [r.getMessage() for r in caplog.records if r.name == 'app.worker'] == [
        '釋放前一個 worker 留下的佇列紀錄：job_dead'
    ]
    assert (await summary(services, 'job_dead')).stage == 'failed'
    # 其他狀態的紀錄不動
```

找到（4／4）：

```python
    assert (await summary(services, 'job_finished')).stage == 'done'


async def test_cutout_marks_uploaded_products_and_refuses_samples(services: Services, queues: Queues) -> None:
    async with services.db.session() as s:
        product = await catalog.save_product(
            s,
            ProductDraft(
                brand_id='selune',
                name='晚安面膜',
                features=[],
                price=Price(sale=0, original=0),
                photo=FilePhoto(source='upload', url='/files/products/x.png'),
                cutout=None,
            ),
            NOW,
        )
    async with running(services, queues):
        done = await queues.run_task('cutout', wait=10, product_id=product.id)
    assert done.completed
    cut = done.result['product']['cutout']
    assert cut == {'model': 'BiRefNet-general', 'status': 'done', 'url': None, 'error': None}
    assert await cutout(services, 'prod_selune_serum') == {'error': '示範商品已是去背素材'}


async def test_run_task_returns_unfinished_when_the_wait_runs_out(queues: Queues) -> None:
```

改成：

```python
    assert (await summary(services, 'job_finished')).stage == 'done'


PENDING = ProductCutout(model='BiRefNet-general', status='pending', url=None, error=None)


def photo_bytes(size: tuple[int, int] = (40, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new('RGB', size, (120, 80, 160)).save(buf, 'JPEG')
    return buf.getvalue()


async def photo_product(services: Services, url: str, source: str = 'upload') -> Product:
    """去背中的商品；照片檔由呼叫端寫入 data/ 或本機資料夾。"""
    async with services.db.session() as s:
        return await catalog.save_product(
            s,
            ProductDraft(
                brand_id='selune',
                name='晚安面膜',
                features=[],
                price=Price(sale=0, original=0),
                photo=FilePhoto.model_validate({'source': source, 'url': url}),
                cutout=PENDING,
            ),
            NOW,
        )


async def current(services: Services, product_id: str) -> Product:
    async with services.db.session() as s:
        product = await catalog.get_product(s, product_id)
    assert product is not None
    return product


def write_upload(services: Services, name: str, data: bytes) -> str:
    folder = services.settings.data_dir / 'uploads'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    return f'/files/uploads/{name}'


async def test_cutout_runs_on_its_own_queue_and_writes_a_transparent_png(services: Services, queues: Queues) -> None:
    product = await photo_product(services, write_upload(services, 'mask.jpg', photo_bytes()))
    assert isinstance(product.photo, FilePhoto)
    await queues.enqueue_cutout(product.id, product.photo.url)
    await queues.enqueue_cutout(product.id, product.photo.url)
    assert await queues.cutouts.count('queued') == 1
    async with running(services, queues):
        for _ in range(50):
            if (await current(services, product.id)).cutout != PENDING:
                break
            await asyncio.sleep(0.1)
    cut = (await current(services, product.id)).cutout
    assert cut is not None and (cut.model, cut.status, cut.error) == ('sim', 'done', None)
    assert cut.url is not None and cut.url.startswith(f'/files/products/{product.id}/cutout-')
    alpha = np.asarray(Image.open(services.settings.data_dir / cut.url.removeprefix('/files/')))[:, :, 3]
    assert (alpha[0, 0], alpha[30, 20]) == (0, 255)
    assert [w.concurrency for w in build_workers(services, queues)] == [1, 2, 1]


async def test_cutout_reports_missing_and_unreadable_photos(services: Services) -> None:
    missing = await photo_product(services, '/files/uploads/gone.jpg')
    broken = await photo_product(services, write_upload(services, 'broken.jpg', b'not an image'))
    for product in (missing, broken):
        assert isinstance(product.photo, FilePhoto)
        await cutout(services, product.id, product.photo.url)
    assert (await current(services, missing.id)).cutout == ProductCutout(
        model='sim', status='failed', url=None, error='找不到商品照：/files/uploads/gone.jpg'
    )
    assert (await current(services, broken.id)).cutout == ProductCutout(
        model='sim', status='failed', url=None, error='照片無法讀取'
    )


async def test_cutout_reads_local_photos_by_their_quoted_url(services: Services) -> None:
    folder = services.settings.local_photos_dir
    folder.mkdir(parents=True)
    (folder / '精華液 30ml.jpg').write_bytes(photo_bytes())
    product = await photo_product(services, f'/files/local/{quote("精華液 30ml.jpg", safe="")}', source='local')
    assert isinstance(product.photo, FilePhoto)
    await cutout(services, product.id, product.photo.url)
    cut = (await current(services, product.id)).cutout
    assert cut is not None and cut.status == 'done'


async def test_cutout_discards_its_result_when_the_photo_changed_meanwhile(services: Services) -> None:
    old_url = write_upload(services, 'old.jpg', photo_bytes())
    product = await photo_product(services, old_url)
    newer = ProductCutout(model='sim', status='done', url='/files/products/x/cutout-newer.png', error=None)

    class PhotoChangedWhileWaiting(CutoutEngine):
        async def segmenter(self) -> Segmenter:
            # 等模型時，使用者換了照片，新照片的去背也已經完成
            fields = {k: v for k, v in product.to_json().items() if k != 'createdAt'}
            changed = {**fields, 'photo': {'source': 'upload', 'url': '/files/uploads/new.jpg'}}
            async with services.db.session() as s:
                await catalog.save_product(s, ProductDraft.model_validate({**changed, 'cutout': newer.to_json()}), NOW)
            return SimSegmenter()

    services.cutouts = PhotoChangedWhileWaiting('sim', services.settings.data_dir, services.redis)
    folder = services.settings.data_dir / 'products' / product.id
    folder.mkdir(parents=True)
    (folder / 'cutout-newer.png').write_bytes(b'newer')
    await cutout(services, product.id, old_url)
    assert (await current(services, product.id)).cutout == newer
    # 舊照片的結果丟掉，新照片的檔案留著
    assert [f.name for f in folder.iterdir()] == ['cutout-newer.png']
    # 照片早已換掉的任務直接結束
    await cutout(services, product.id, old_url)
    assert (await current(services, product.id)).cutout == newer


async def test_recovery_releases_cutout_orphans_and_requeues_pending_cutouts(
    services: Services, queues: Queues
) -> None:
    product = await photo_product(services, write_upload(services, 'a.jpg', photo_bytes()))
    assert isinstance(product.photo, FilePhoto)
    key = cutout_key(product.id, product.photo.url)
    await queues.enqueue_cutout(product.id, product.photo.url)
    taken = await queues.cutouts.dequeue(timeout=1)
    assert taken is not None and taken.key == key
    await taken.update(status=Status.ACTIVE)
    await recover(services, queues)
    record = await queues.cutouts.job(key)
    assert record is not None and record.status == Status.QUEUED
    assert await queues.cutouts.count('active') == 0


async def test_run_task_returns_unfinished_when_the_wait_runs_out(queues: Queues) -> None:
```

- [ ] **Step 3: 修改 `backend/tests/test_api_catalog.py`（先寫測試）**

`backend/tests/test_api_catalog.py`：去背改為排入佇列，回 202。

找到（1／2）：

```python
"""api：選項、系統狀態、品牌與文件上傳、商品與商品照、本機資料夾、檔案。需要 composer。"""

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from app.api.files import resolve_file
from app.brands import BrandLoadError
from app.settings import Settings
from tests.conftest import LiveApi
from tests.fixtures import load_fixture
```

改成：

```python
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
```

找到（2／2）：

```python
        assert (rejected.status_code, rejected.json()['error']['message']) == (400, message)


async def test_cutout_runs_on_the_worker(api: LiveApi) -> None:
    product = (await api.http.post('/api/products', json=DRAFT)).json()
    async with api.worker():
        res = await api.http.post(f'/api/products/{product["id"]}/cutout')
    assert res.json()['cutout'] == {'model': 'BiRefNet-general', 'status': 'done', 'url': None, 'error': None}
    listed = (await api.http.get('/api/products', params={'brandId': 'selune'})).json()
    assert listed[-1]['cutout'] == {'model': 'BiRefNet-general', 'status': 'done', 'url': None, 'error': None}
    sample = await api.http.post('/api/products/prod_selune_serum/cutout')
    assert sample.json() == {'error': {'code': 'invalid', 'message': '示範商品已是去背素材'}}
```

改成：

```python
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
```

- [ ] **Step 4: 確認測試失敗**

Run: `uv run pytest -q tests/test_worker.py tests/test_api_catalog.py`（在 `backend/`）
Expected: FAIL，收集 `tests/test_worker.py` 時出錯：`ImportError: cannot import name 'cutout_key' from 'app.queues'`。

- [ ] **Step 5: 建立 `backend/app/files.py`，`app/api/files.py` 改為使用它**

```python
"""/files/... 網址與檔案的對應（api 提供檔案、worker 讀取商品照共用）：

- /files/uploads/…、/files/products/{id}/…（去背圖）→ data/
- /files/local/{檔名} → 本機資料夾 assets/products/
- /files/brands/… → 品牌設定檔資料夾（Logo 等圖檔）
"""

from pathlib import Path
from urllib.parse import unquote

from app.errors import NotFound
from app.settings import Settings

#: 只提供圖片；MIME 固定，不依賴作業系統的對照表
FILE_TYPES = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
    '.svg': 'image/svg+xml',
}
PREFIX = '/files/'


def resolve_file(settings: Settings, path: str) -> Path | None:
    """網址路徑（/files/ 之後的部分）→ 檔案。不允許超出各自的資料夾（.. 與絕對路徑都會被擋下）。"""
    head, _, rest = path.partition('/')
    if head == 'local':
        root, relative = settings.local_photos_dir, rest
    elif head == 'brands':
        root, relative = settings.brands_dir, rest
    else:
        root, relative = settings.data_dir, path
    base = root.resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base) or target.suffix.lower() not in FILE_TYPES or not target.is_file():
        return None
    return target


def photo_path(settings: Settings, url: str) -> Path:
    """商品照的網址（/files/uploads/…、/files/local/…，檔名經過 URL 編碼）→ 檔案。"""
    target = resolve_file(settings, unquote(url.removeprefix(PREFIX))) if url.startswith(PREFIX) else None
    if target is None:
        raise NotFound(f'找不到商品照：{url}')
    return target
```

- [ ] **Step 6: 改寫 `backend/app/api/files.py`（完整內容）**

改寫 `backend/app/api/files.py`（完整內容）：

```python
"""/files/...（唯讀）：網址與資料夾的對應見 app/files.py。"""

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.api.services import Services
from app.errors import NotFound
from app.files import FILE_TYPES, resolve_file

router = APIRouter(tags=['檔案'])


@router.get('/files/{path:path}')
async def read_file(path: str, services: Services) -> FileResponse:
    target = resolve_file(services.settings, path)
    if target is None:
        raise NotFound(f'找不到檔案：{path}')
    return FileResponse(
        target, media_type=FILE_TYPES[target.suffix.lower()], headers={'X-Content-Type-Options': 'nosniff'}
    )
```

- [ ] **Step 7: 修改 `backend/app/cutout/processing.py`**

找到（1／2）：

```python
from numpy.typing import NDArray
from PIL import Image, ImageOps, UnidentifiedImageError

INPUT_SIZE = 1024
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)
```

改成：

```python
from numpy.typing import NDArray
from PIL import Image, ImageOps, UnidentifiedImageError

from app.errors import AppError

INPUT_SIZE = 1024
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)
```

找到（2／2）：

```python
CLEAR_UNTIL = 13


class CutoutError(Exception):
    """去背失敗；訊息為繁體中文，直接顯示在商品卡上。"""
```

改成：

```python
CLEAR_UNTIL = 13


class CutoutError(AppError):
    """去背失敗；訊息為繁體中文，直接顯示在商品卡上。"""
```

- [ ] **Step 8: 修改 `backend/app/queues.py`**

找到（1／3）：

```python
"""SAQ 佇列：api 放入工作，worker 執行。

- jobs：生圖任務，一次只執行一個（只有一張 GPU）；key 為任務 id，同一個任務不會重複排入。
- tasks：去背、文件上傳、回寫歷史案例，最多同時兩個，不必等生圖任務。
"""

import asyncio
from dataclasses import dataclass
from typing import Any
```

改成：

```python
"""SAQ 佇列：api 放入工作，worker 執行。

- jobs：生圖任務，一次只執行一個（只有一張 GPU）；key 為任務 id，同一個任務不會重複排入。
- tasks：文件上傳、回寫歷史案例，最多同時兩個，不必等生圖任務。
- cutouts：商品照去背，一次一個（推論時約 6.5 GB 記憶體）；大量新增商品時不會擋住文件上傳。
"""

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Any
```

找到（2／3）：

```python

JOBS = 'jobs'
TASKS = 'tasks'
#: tasks 佇列裡單一工作最長的執行時間（秒）
TASK_TIMEOUT = 600


def ingest_channel(task_id: str) -> str:
    """品牌文件上傳的進度：worker 發布到這個 Redis 頻道，api 以 NDJSON 串流轉給前端。"""
    return f'ingest:{task_id}'


@dataclass(frozen=True)
```

改成：

```python

JOBS = 'jobs'
TASKS = 'tasks'
CUTOUTS = 'cutouts'
#: tasks 佇列裡單一工作最長的執行時間（秒）
TASK_TIMEOUT = 600
#: 單張去背最長的時間（秒）：含第一次下載模型（約 1 GB）與推論
CUTOUT_TIMEOUT = 600


def ingest_channel(task_id: str) -> str:
    """品牌文件上傳的進度：worker 發布到這個 Redis 頻道，api 以 NDJSON 串流轉給前端。"""
    return f'ingest:{task_id}'


def cutout_key(product_id: str, photo_url: str) -> str:
    """同一張照片的去背還在排隊或執行時不會重複排入；換了照片 key 就不同，一定會排入。"""
    return f'cutout:{product_id}:{hashlib.sha256(photo_url.encode()).hexdigest()[:8]}'


@dataclass(frozen=True)
```

找到（3／3）：

```python
    def __init__(self, redis_url: str) -> None:
        self.jobs = Queue.from_url(redis_url, name=JOBS)
        self.tasks = Queue.from_url(redis_url, name=TASKS)

    async def connect(self) -> None:
        await self.jobs.connect()
        await self.tasks.connect()

    async def disconnect(self) -> None:
        await self.jobs.disconnect()
        await self.tasks.disconnect()

    async def enqueue_job(self, job_id: str) -> None:
        """生圖可能花上數十分鐘，不設逾時（流程內各步驟有自己的逾時）。"""
        await self.jobs.enqueue('run_job', key=job_id, timeout=0, job_id=job_id)

    async def release_orphans(self, reason: str) -> list[str]:
        """放掉前一個 worker 留下的 ACTIVE 紀錄，回傳被放掉的 key（任務 id）。

        worker 被強制終止時，紀錄會永遠停在執行中：系統狀態一直算它執行中，
        同一個任務也無法重新排入（key 相同會被當成重複）。
        只在 worker 啟動前呼叫：只有一個 worker 行程，這時候 ACTIVE 的紀錄一定屬於已經結束的行程。
        """
        # 先收集再放掉：放掉會改寫紀錄，不要一邊掃描一邊改
        orphans = [job async for job in self.jobs.iter_jobs(statuses=[Status.ACTIVE])]
        for job in orphans:
            await self.jobs.finish(job, Status.ABORTED, error=reason)
        return [job.key for job in orphans]

    async def enqueue_task(self, function: str, /, **kwargs: Any) -> None:
        await self.tasks.enqueue(function, timeout=TASK_TIMEOUT, **kwargs)
```

改成：

```python
    def __init__(self, redis_url: str) -> None:
        self.jobs = Queue.from_url(redis_url, name=JOBS)
        self.tasks = Queue.from_url(redis_url, name=TASKS)
        self.cutouts = Queue.from_url(redis_url, name=CUTOUTS)

    async def connect(self) -> None:
        for queue in (self.jobs, self.tasks, self.cutouts):
            await queue.connect()

    async def disconnect(self) -> None:
        for queue in (self.jobs, self.tasks, self.cutouts):
            await queue.disconnect()

    async def enqueue_job(self, job_id: str) -> None:
        """生圖可能花上數十分鐘，不設逾時（流程內各步驟有自己的逾時）。"""
        await self.jobs.enqueue('run_job', key=job_id, timeout=0, job_id=job_id)

    async def enqueue_cutout(self, product_id: str, photo_url: str) -> None:
        await self.cutouts.enqueue(
            'cutout',
            key=cutout_key(product_id, photo_url),
            timeout=CUTOUT_TIMEOUT,
            product_id=product_id,
            photo_url=photo_url,
        )

    async def release_orphans(self, reason: str) -> list[str]:
        """放掉前一個 worker 留下的 ACTIVE 紀錄（生圖與去背），回傳被放掉的 key。

        worker 被強制終止時，紀錄會永遠停在執行中：系統狀態一直算它執行中，
        同一個任務也無法重新排入（key 相同會被當成重複）。
        只在 worker 啟動前呼叫：只有一個 worker 行程，這時候 ACTIVE 的紀錄一定屬於已經結束的行程。
        """
        released: list[str] = []
        for queue in (self.jobs, self.cutouts):
            # 先收集再放掉：放掉會改寫紀錄，不要一邊掃描一邊改
            orphans = [job async for job in queue.iter_jobs(statuses=[Status.ACTIVE])]
            for job in orphans:
                await queue.finish(job, Status.ABORTED, error=reason)
            released += [job.key for job in orphans]
        return released

    async def enqueue_task(self, function: str, /, **kwargs: Any) -> None:
        await self.tasks.enqueue(function, timeout=TASK_TIMEOUT, **kwargs)
```

- [ ] **Step 9: 修改 `backend/app/repo/catalog.py`**

找到（1／2）：

```python
from sqlalchemy.ext.asyncio import AsyncSession

from app.brands import LoadedBrand
from app.contract import Brand, Product, ProductDraft, RagChunk
from app.core.clock import iso, parse_iso
from app.db.models import BrandChunkRow, BrandRow, ProductRow
```

改成：

```python
from sqlalchemy.ext.asyncio import AsyncSession

from app.brands import LoadedBrand
from app.contract import Brand, FilePhoto, Product, ProductCutout, ProductDraft, RagChunk
from app.core.clock import iso, parse_iso
from app.db.models import BrandChunkRow, BrandRow, ProductRow
```

找到（2／2）：

```python
    return product


async def delete_product(session: AsyncSession, product_id: str) -> bool:
    """示範商品只標記刪除；自建商品直接刪除。回傳是否有刪到。"""
    row = await session.get(ProductRow, product_id)
```

改成：

```python
    return product


async def set_cutout(session: AsyncSession, product_id: str, photo_url: str, cutout: ProductCutout) -> Product | None:
    """鎖定商品列，確認商品仍在、照片沒換才寫入去背狀態；否則不寫入並回傳 None。"""
    row = await session.get(ProductRow, product_id, with_for_update=True)
    product = Product.model_validate(row.data) if row and not row.deleted else None
    if row is None or product is None or not isinstance(product.photo, FilePhoto) or product.photo.url != photo_url:
        await session.rollback()
        return None
    updated = product.model_copy(update={'cutout': cutout})
    row.data = updated.to_json()
    await session.commit()
    return updated


async def pending_cutouts(session: AsyncSession) -> list[Product]:
    """還在去背中的商品（worker 啟動時重新排入）。"""
    rows = await session.scalars(
        select(ProductRow).where(ProductRow.deleted.is_(False), ProductRow.data['cutout']['status'].astext == 'pending')
    )
    return [Product.model_validate(r.data) for r in rows]


async def delete_product(session: AsyncSession, product_id: str) -> bool:
    """示範商品只標記刪除；自建商品直接刪除。回傳是否有刪到。"""
    row = await session.get(ProductRow, product_id)
```

- [ ] **Step 10: 修改 `backend/app/worker.py`**

找到（1／9）：

```python
"""SAQ worker：uv run python -m app.worker

- jobs 佇列：run_job（生圖任務，一次一個）
- tasks 佇列：cutout（去背）、ingest（品牌文件上傳）、write_back（選定海報回寫成歷史案例），最多同時兩個
- 啟動時復原：原本執行中的任務標記失敗（不自動重跑），排隊中的任務重新放回佇列
"""

import asyncio
import json
import logging
import os
import signal
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
```

改成：

```python
"""SAQ worker：uv run python -m app.worker

- jobs 佇列：run_job（生圖任務，一次一個）
- tasks 佇列：ingest（品牌文件上傳）、write_back（選定海報回寫成歷史案例），最多同時兩個
- cutouts 佇列：cutout（商品照去背，一次一個）
- 啟動時復原：原本執行中的任務標記失敗（不自動重跑），排隊中的任務與去背中的商品重新放回佇列
"""

import asyncio
import hashlib
import json
import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from redis.asyncio import Redis
```

找到（2／9）：

```python
from app.adapters.composer import ComposerClient
from app.contract import (
    BrandDocument,
    IngestChunkedEvent,
    IngestEmbeddedEvent,
    IngestStoredEvent,
```

改成：

```python
from app.adapters.composer import ComposerClient
from app.contract import (
    BrandDocument,
    FilePhoto,
    IngestChunkedEvent,
    IngestEmbeddedEvent,
    IngestStoredEvent,
```

找到（3／9）：

```python
    JobStatusEvent,
    LogEvent,
    ProductCutout,
    ProductDraft,
)
from app.core.clock import utc_now
from app.db.models import JobRow
from app.db.session import Database
from app.errors import AppError, NotFound
from app.events import EventStore
from app.pipeline.ports import Ports
from app.pipeline.runner import failure_reason, run_job
from app.pipeline.sim import sim_ports
from app.queues import Queues, ingest_channel
from app.repo import catalog, history
from app.settings import settings

logger = logging.getLogger(__name__)
```

改成：

```python
    JobStatusEvent,
    LogEvent,
    ProductCutout,
)
from app.core.clock import utc_now
from app.cutout.engine import CutoutEngine
from app.db.models import JobRow
from app.db.session import Database
from app.errors import AppError, NotFound
from app.events import EventStore
from app.files import photo_path
from app.pipeline.ports import Ports
from app.pipeline.runner import failure_reason, run_job
from app.pipeline.sim import sim_ports
from app.queues import Queues, ingest_channel
from app.repo import catalog, history
from app.settings import Settings, settings

logger = logging.getLogger(__name__)
```

找到（4／9）：

```python
    ports: Ports
    #: 模擬模式的播放速度（0 為不等待）
    speed: float

    async def pace(self, ms: float) -> None:
        if self.speed > 0:
```

改成：

```python
    ports: Ports
    #: 模擬模式的播放速度（0 為不等待）
    speed: float
    settings: Settings
    cutouts: CutoutEngine

    async def pace(self, ms: float) -> None:
        if self.speed > 0:
```

找到（5／9）：

```python
    ports = sim_ports(
        composer, first_round_fail=settings.sim_first_round_fail, force_all_fail=settings.sim_force_all_fail
    )
    return Services(db, redis, EventStore(db, redis), composer, ports, settings.sim_speed)


async def cutout(services: Services, product_id: str) -> dict[str, Any]:
    """去背（模擬：約 1.2 秒，不產生圖檔，合成時以色彩增值讓白底融入背景）。"""
    async with services.db.session() as s:
        product = await catalog.get_product(s, product_id)
    if product is None:
        return {'error': f'找不到商品：{product_id}'}
    if product.photo.source == 'sample':
        return {'error': '示範商品已是去背素材'}
    await services.pace(1200)
    fields = {k: v for k, v in product.to_json().items() if k != 'createdAt'}
    cut = ProductCutout(model='BiRefNet-general', status='done', url=None, error=None)
    draft = ProductDraft.model_validate({**fields, 'cutout': cut.to_json()})
    async with services.db.session() as s:
        saved = await catalog.save_product(s, draft, utc_now())
    return {'product': saved.to_json()}


async def ingest(services: Services, task_id: str, brand_id: str, name: str, text: str) -> None:
```

改成：

```python
    ports = sim_ports(
        composer, first_round_fail=settings.sim_first_round_fail, force_all_fail=settings.sim_force_all_fail
    )
    cutouts = CutoutEngine(settings.cutout_model, settings.models_dir, redis)
    return Services(db, redis, EventStore(db, redis), composer, ports, settings.sim_speed, settings, cutouts)


async def cutout(services: Services, product_id: str, photo_url: str) -> None:
    """去背：讀照片 → 等模型 → 推論（另一條執行緒，不阻擋其他任務）→ 寫入 PNG → 確認商品沒變才寫入結果。"""
    async with services.db.session() as s:
        product = await catalog.get_product(s, product_id)
    # 商品已刪除，或照片已經換掉（較新的任務會處理新照片）
    if product is None or not isinstance(product.photo, FilePhoto) or product.photo.url != photo_url:
        return
    folder = services.settings.data_dir / 'products' / product_id
    written: Path | None = None
    try:
        photo = await asyncio.to_thread(photo_path(services.settings, photo_url).read_bytes)
        segmenter = await services.cutouts.segmenter()
        png = await asyncio.to_thread(segmenter.cut, photo)
        name = f'cutout-{hashlib.sha256(png).hexdigest()[:12]}.png'
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        written = folder / name
        await asyncio.to_thread(written.write_bytes, png)
        result = ProductCutout(
            model=segmenter.name, status='done', url=f'/files/products/{product_id}/{name}', error=None
        )
    except Exception as error:  # noqa: BLE001 - 任何錯誤都顯示在商品卡上
        logger.exception('去背失敗：product_id=%s', product_id)
        result = ProductCutout(model=services.cutouts.model, status='failed', url=None, error=failure_reason(error))
    async with services.db.session() as s:
        saved = await catalog.set_cutout(s, product_id, photo_url, result)
    if written is not None:
        await asyncio.to_thread(_remove_cutouts, folder, keep=written if saved is not None else None, only=written)


def _remove_cutouts(folder: Path, *, keep: Path | None, only: Path) -> None:
    """寫入成功時刪掉同一商品的舊去背圖；沒寫入（商品已刪除或換了照片）時只刪掉這次寫的檔案。"""
    targets = [only] if keep is None else [f for f in folder.glob('cutout-*.png') if f != keep]
    for f in targets:
        f.unlink(missing_ok=True)


async def ingest(services: Services, task_id: str, brand_id: str, name: str, text: str) -> None:
```

找到（6／9）：

```python
async def recover(services: Services, queues: Queues) -> None:
    # 前一個 worker 被強制終止時，佇列紀錄會停在執行中：不放掉的話，系統狀態永遠算它執行中，
    # 排隊中的任務也會因為 key 相同被當成重複而不再執行。任務在資料庫裡可能已經結束，所以不依資料庫的任務逐筆處理
    for job_id in await queues.release_orphans(RESTART_REASON):
        logger.warning('釋放前一個 worker 留下的佇列紀錄：job_id=%s', job_id)
    async with services.db.session() as s:
        rows = (await s.scalars(select(JobRow).where(JobRow.finished.is_(False)).order_by(JobRow.created_at))).all()
    for row in rows:
```

改成：

```python
async def recover(services: Services, queues: Queues) -> None:
    # 前一個 worker 被強制終止時，佇列紀錄會停在執行中：不放掉的話，系統狀態永遠算它執行中，
    # 排隊中的任務也會因為 key 相同被當成重複而不再執行。任務在資料庫裡可能已經結束，所以不依資料庫的任務逐筆處理
    for key in await queues.release_orphans(RESTART_REASON):
        logger.warning('釋放前一個 worker 留下的佇列紀錄：%s', key)
    async with services.db.session() as s:
        rows = (await s.scalars(select(JobRow).where(JobRow.finished.is_(False)).order_by(JobRow.created_at))).all()
    for row in rows:
```

找到（7／9）：

```python
        await services.store.append(row.id, LogEvent(type='log', source='api', level='error', message=RESTART_REASON))
        await services.store.append(row.id, JobFailedEvent(type='job.failed', job_id=row.id, reason=RESTART_REASON))
        await services.store.append(row.id, JobStatusEvent(type='job.status', stage='failed', round=row.round))


def build_workers(services: Services, queues: Queues, **options: Any) -> tuple[Worker[Context], Worker[Context]]:
    async def run_job_fn(ctx: Context, *, job_id: str) -> None:
        await run_job(job_id, services.db, services.store, services.ports, speed=services.speed)

    async def cutout_fn(ctx: Context, *, product_id: str) -> dict[str, Any]:
        return await cutout(services, product_id)

    async def ingest_fn(ctx: Context, *, task_id: str, brand_id: str, name: str, text: str) -> None:
        await ingest(services, task_id, brand_id, name, text)
```

改成：

```python
        await services.store.append(row.id, LogEvent(type='log', source='api', level='error', message=RESTART_REASON))
        await services.store.append(row.id, JobFailedEvent(type='job.failed', job_id=row.id, reason=RESTART_REASON))
        await services.store.append(row.id, JobStatusEvent(type='job.status', stage='failed', round=row.round))
    # 去背中斷的商品重新排入
    async with services.db.session() as s:
        pending = await catalog.pending_cutouts(s)
    for product in pending:
        if isinstance(product.photo, FilePhoto):
            await queues.enqueue_cutout(product.id, product.photo.url)


def build_workers(services: Services, queues: Queues, **options: Any) -> tuple[Worker[Context], ...]:
    async def run_job_fn(ctx: Context, *, job_id: str) -> None:
        await run_job(job_id, services.db, services.store, services.ports, speed=services.speed)

    async def cutout_fn(ctx: Context, *, product_id: str, photo_url: str) -> None:
        await cutout(services, product_id, photo_url)

    async def ingest_fn(ctx: Context, *, task_id: str, brand_id: str, name: str, text: str) -> None:
        await ingest(services, task_id, brand_id, name, text)
```

找到（8／9）：

```python
    jobs = Worker(queues.jobs, [('run_job', run_job_fn)], concurrency=1, startup=[sweep_first], **options)
    tasks = Worker(
        queues.tasks,
        [('cutout', cutout_fn), ('ingest', ingest_fn), ('write_back', write_back_fn)],
        concurrency=2,
        startup=[sweep_first],
        **options,
    )
    # 兩個 worker 在同一個 event loop：每個 worker 自己註冊的 SIGINT/SIGTERM 處理會互相取代，
    # 只有最後啟動的那個會停下來，另一個繼續跑到被 Docker 強制終止。所以關掉，改由 main 統一處理。
    jobs.SIGNALS = []
    tasks.SIGNALS = []
    return jobs, tasks


def stop_on_signals(workers: tuple[Worker[Context], ...]) -> None:
```

改成：

```python
    jobs = Worker(queues.jobs, [('run_job', run_job_fn)], concurrency=1, startup=[sweep_first], **options)
    tasks = Worker(
        queues.tasks,
        [('ingest', ingest_fn), ('write_back', write_back_fn)],
        concurrency=2,
        startup=[sweep_first],
        **options,
    )
    cutouts = Worker(queues.cutouts, [('cutout', cutout_fn)], concurrency=1, startup=[sweep_first], **options)
    workers = (jobs, tasks, cutouts)
    # 多個 worker 在同一個 event loop：每個 worker 自己註冊的 SIGINT/SIGTERM 處理會互相取代，
    # 只有最後啟動的那個會停下來，其他的繼續跑到被 Docker 強制終止。所以關掉，改由 main 統一處理。
    for worker in workers:
        worker.SIGNALS = []
    return workers


def stop_on_signals(workers: tuple[Worker[Context], ...]) -> None:
```

找到（9／9）：

```python
    queues = Queues(settings.redis_url)
    await queues.connect()
    await recover(services, queues)
    jobs, tasks = build_workers(services, queues)
    stop_on_signals((jobs, tasks))
    try:
        await asyncio.gather(jobs.start(), tasks.start())
    finally:
        await queues.disconnect()
        await services.composer.aclose()
        await services.db.dispose()
```

改成：

```python
    queues = Queues(settings.redis_url)
    await queues.connect()
    await recover(services, queues)
    # 第一次啟動時下載模型（約 1 GB）；在背景進行，不擋住生圖與文件上傳
    warming = asyncio.create_task(services.cutouts.warm_up())
    workers = build_workers(services, queues)
    stop_on_signals(workers)
    try:
        await asyncio.gather(*(w.start() for w in workers))
    finally:
        warming.cancel()
        await queues.disconnect()
        await services.composer.aclose()
        await services.db.dispose()
```

- [ ] **Step 11: 修改 `backend/app/api/catalog.py`**

找到（1／3）：

```python
    Model,
    Price,
    Product,
    ProductDraft,
    SystemStatus,
)
```

改成：

```python
    Model,
    Price,
    Product,
    ProductCutout,
    ProductDraft,
    SystemStatus,
)
```

找到（2／3）：

```python
STATUS_TIMEOUT = 3
#: 文件上傳最多等待的秒數（超過時回報錯誤，worker 仍會繼續處理）
INGEST_TIMEOUT = 120
#: 去背最多等待的秒數
CUTOUT_WAIT = 30
#: 上傳的商品照：MIME → 副檔名（與本機資料夾支援的格式相同）
UPLOAD_TYPES = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
```

改成：

```python
STATUS_TIMEOUT = 3
#: 文件上傳最多等待的秒數（超過時回報錯誤，worker 仍會繼續處理）
INGEST_TIMEOUT = 120
#: 上傳的商品照：MIME → 副檔名（與本機資料夾支援的格式相同）
UPLOAD_TYPES = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
```

找到（3／3）：

```python
    return FilePhoto(source='upload', url=f'/files/uploads/{name}')


@router.post('/api/products/{product_id}/cutout')
async def request_cutout(product_id: str, services: Services) -> Product:
    async with services.db.session() as s:
        product = await catalog.get_product(s, product_id)
    if product is None:
        raise NotFound(f'找不到商品：{product_id}')
    if product.photo.source == 'sample':
        raise Invalid('示範商品已是去背素材')
    done = await services.queues.run_task('cutout', wait=CUTOUT_WAIT, product_id=product_id)
    if not done.completed:
        raise Unavailable('去背還沒完成：請確認 worker 正在執行，稍後再重新整理')
    if 'error' in done.result:
        raise Invalid(done.result['error'])
    return Product.model_validate(done.result['product'])


def local_photo_url(file: str) -> str:
```

改成：

```python
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
```

- [ ] **Step 12: 確認全部通過**

Run（在 `backend/`）：`uv run pytest -q tests/test_worker.py tests/test_api_catalog.py`
Expected：21 passed。

Run：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected：沒有錯誤；94 passed、1 skipped。

- [ ] **Step 13: Commit**

```bash
git add \
  backend/app/api/catalog.py \
  backend/app/api/files.py \
  backend/app/cutout/processing.py \
  backend/app/files.py \
  backend/app/queues.py \
  backend/app/repo/catalog.py \
  backend/app/worker.py \
  backend/tests/conftest.py \
  backend/tests/test_api_catalog.py \
  backend/tests/test_worker.py
git commit -m "feat: cut out products on a dedicated queue and recover pending cutouts at startup" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5：新增與修改商品時決定去背狀態、刪除時清掉去背圖、系統狀態

**Files:**
- Create: `backend/app/cutout/state.py`
- Modify: `backend/app/cutout/engine.py`、`backend/app/api/catalog.py`
- Test: `backend/tests/test_api_catalog.py`、`backend/tests/test_cutout_engine.py`

**Interfaces:**
- Consumes：Task 4 的 `enqueue_cutout`、`cutout_key`、`set_cutout`。
- Produces：
  - `app.cutout.state`：`STATE_KEY = 'cutout:model'`、`ModelState`。engine 改從這裡匯入。
  - API 行為：
    - 新增商品，或換了照片（`upload`／`local`）時，設為 `pending` 並排入佇列。
    - 其餘情況沿用原本的 `cutout`，忽略請求中的值。
    - 刪除商品時刪除 `data/products/{id}/`。
    - `GET /api/status` 多一個 `{ id: 'cutout', label: '去背模型（BiRefNet）' }`。

- [ ] **Step 1: 修改 `backend/tests/test_api_catalog.py`（先寫測試）**

找到（1／4）：

```python
from PIL import Image

from app.brands import BrandLoadError
from app.files import resolve_file
from app.settings import Settings
from tests.conftest import LiveApi
from tests.fixtures import load_fixture
```

改成：

```python
from PIL import Image

from app.brands import BrandLoadError
from app.cutout.state import STATE_KEY
from app.files import resolve_file
from app.queues import cutout_key
from app.settings import Settings
from tests.conftest import LiveApi
from tests.fixtures import load_fixture
```

找到（2／4）：

```python
        'rag': 'sim',
        'gemini': 'sim',
        'comfyui': 'sim',
    }
    assert status['brands']['detail'] == '已載入 2 個品牌'
    async with api.worker():
```

改成：

```python
        'rag': 'sim',
        'gemini': 'sim',
        'comfyui': 'sim',
        'cutout': 'error',
    }
    assert status['brands']['detail'] == '已載入 2 個品牌'
    async with api.worker():
```

找到（3／4）：

```python
        assert (rejected.status_code, rejected.json()['error']['message']) == (400, message)


def real_png() -> bytes:
    buf = io.BytesIO()
    Image.new('RGB', (40, 60), (120, 80, 160)).save(buf, 'PNG')
```

改成：

```python
        assert (rejected.status_code, rejected.json()['error']['message']) == (400, message)


PENDING = {'model': 'birefnet-general', 'status': 'pending', 'url': None, 'error': None}


async def test_new_photo_products_are_queued_for_a_cutout_and_keep_it_on_edit(api: LiveApi) -> None:
    done = {'model': 'sim', 'status': 'done', 'url': '/files/products/x/cutout-a.png', 'error': None}
    # 去背狀態由伺服器管理：送來的 cutout 一律忽略
    product = (await api.http.post('/api/products', json={**DRAFT, 'cutout': done})).json()
    assert product['cutout'] == PENDING
    queue = api.services.queues.cutouts
    assert await queue.job(cutout_key(product['id'], '/files/uploads/x.png')) is not None
    renamed = await api.http.put(f'/api/products/{product["id"]}', json={**DRAFT, 'name': '改名', 'cutout': done})
    assert renamed.json()['cutout'] == PENDING
    assert await queue.count('queued') == 1
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


def real_png() -> bytes:
    buf = io.BytesIO()
    Image.new('RGB', (40, 60), (120, 80, 160)).save(buf, 'PNG')
```

找到（4／4）：

```python
        'features': [],
        'price': {'sale': 0, 'original': 0},
        'photo': {'source': 'local', 'url': '/files/local/night_cream-v2.png'},
        'cutout': None,
    }
    for name in ('notes.txt', '.hidden.png', 'missing.png'):
        missing = await api.http.post(f'/api/local-photos/{name}/import', json={'brandId': 'misty-isle'})
        assert missing.status_code == 404
```

改成：

```python
        'features': [],
        'price': {'sale': 0, 'original': 0},
        'photo': {'source': 'local', 'url': '/files/local/night_cream-v2.png'},
        'cutout': PENDING,
    }
    assert await api.services.queues.cutouts.job(cutout_key(product['id'], product['photo']['url'])) is not None
    for name in ('notes.txt', '.hidden.png', 'missing.png'):
        missing = await api.http.post(f'/api/local-photos/{name}/import', json={'brandId': 'misty-isle'})
        assert missing.status_code == 404
```

- [ ] **Step 2: 修改 `backend/tests/test_cutout_engine.py`（先寫測試）**

`backend/tests/test_cutout_engine.py` 改從 `app.cutout.state` 匯入 `STATE_KEY`：

找到：

```python
from PIL import Image
from redis.asyncio import Redis

from app.cutout.engine import STATE_KEY, CutoutEngine
from app.cutout.models import ModelFile, ensure_model
from app.cutout.processing import CutoutError
from app.cutout.segmenter import OnnxSegmenter, SimSegmenter
from tests.test_cutout import png, tiny_model

URL = 'https://models.test/tiny.onnx'
```

改成：

```python
from PIL import Image
from redis.asyncio import Redis

from app.cutout.engine import CutoutEngine
from app.cutout.models import ModelFile, ensure_model
from app.cutout.processing import CutoutError
from app.cutout.segmenter import OnnxSegmenter, SimSegmenter
from app.cutout.state import STATE_KEY
from tests.test_cutout import png, tiny_model

URL = 'https://models.test/tiny.onnx'
```

- [ ] **Step 3: 確認測試失敗**

Run: `uv run pytest -q tests/test_api_catalog.py`（在 `backend/`）
Expected: FAIL，收集時出錯：`ModuleNotFoundError: No module named 'app.cutout.state'`。

- [ ] **Step 4: 建立 `backend/app/cutout/state.py`，engine 改用它**

```python
"""去背模型的狀態：worker 寫入 Redis，api 的系統狀態讀取（api 不必載入 onnxruntime）。"""

from typing import Literal

#: worker 回報模型狀態的 Redis key：{"model": …, "state": …, "error": …}
STATE_KEY = 'cutout:model'

ModelState = Literal['downloading', 'loading', 'ready', 'failed', 'sim']
```

- [ ] **Step 5: 修改 `backend/app/cutout/engine.py`**

找到（1／2）：

```python
import json
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Literal

import httpx
from redis.asyncio import Redis
```

改成：

```python
import json
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

import httpx
from redis.asyncio import Redis
```

找到（2／2）：

```python
from app.cutout.models import MODELS, ModelFile, ensure_model, has_model
from app.cutout.processing import CutoutError
from app.cutout.segmenter import OnnxSegmenter, Segmenter, SimSegmenter

#: worker 回報模型狀態的 Redis key（api 的系統狀態讀取）
STATE_KEY = 'cutout:model'
#: 下載模型的逾時（秒）：連線與兩次讀取之間的間隔
DOWNLOAD_TIMEOUT = 60

ModelState = Literal['downloading', 'loading', 'ready', 'failed', 'sim']


class CutoutEngine:
```

改成：

```python
from app.cutout.models import MODELS, ModelFile, ensure_model, has_model
from app.cutout.processing import CutoutError
from app.cutout.segmenter import OnnxSegmenter, Segmenter, SimSegmenter
from app.cutout.state import STATE_KEY, ModelState

#: 下載模型的逾時（秒）：連線與兩次讀取之間的間隔
DOWNLOAD_TIMEOUT = 60


class CutoutEngine:
```

- [ ] **Step 6: 修改 `backend/app/api/catalog.py`**

找到（1／5）：

```python
import json
import re
import secrets
from collections.abc import AsyncIterator, Awaitable
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Query, UploadFile
```

改成：

```python
import json
import re
import secrets
import shutil
from collections.abc import AsyncIterator, Awaitable
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, UploadFile
```

找到（2／5）：

```python
    SystemStatus,
)
from app.core.clock import utc_now
from app.errors import Invalid, NotFound, Unavailable
from app.pipeline.runner import failure_reason
from app.queues import ingest_channel
```

改成：

```python
    SystemStatus,
)
from app.core.clock import utc_now
from app.cutout.state import STATE_KEY
from app.errors import Invalid, NotFound, Unavailable
from app.pipeline.runner import failure_reason
from app.queues import ingest_channel
```

找到（3／5）：

```python
        _probe('composer', 'composer（排版與模擬邏輯）', _composer(services)),
        _probe('brands', '品牌設定檔', _brands(services)),
    )
    return SystemStatus(components=[*probed, *SIMULATED])


@router.get('/api/brands')
```

改成：

```python
        _probe('composer', 'composer（排版與模擬邏輯）', _composer(services)),
        _probe('brands', '品牌設定檔', _brands(services)),
    )
    return SystemStatus(components=[*probed, *SIMULATED, await _cutout_model(services)])


async def _cutout_model(services: ApiServices) -> ComponentStatus:
    """worker 寫在 Redis 的去背模型狀態。"""
    label = '去背模型（BiRefNet）'
    try:
        raw = await asyncio.wait_for(services.redis.get(STATE_KEY), STATUS_TIMEOUT)
    except Exception as error:  # noqa: BLE001 - 任何錯誤都顯示在系統狀態
        return ComponentStatus(id='cutout', label=label, status='error', detail=failure_reason(error))
    if raw is None:
        return ComponentStatus(id='cutout', label=label, status='error', detail='worker 尚未回報')
    state = json.loads(raw)
    model = state['model']
    shown: dict[str, tuple[Literal['ok', 'sim', 'off', 'error'], str]] = {
        'ready': ('ok', f'{model} 已載入'),
        'loading': ('off', f'正在載入 {model}'),
        'downloading': ('off', '第一次使用，正在下載模型（約 1 GB）'),
        'failed': ('error', state['error']),
        'sim': ('sim', '模擬去背：中央的橢圓'),
    }
    status, detail = shown[state['state']]
    return ComponentStatus(id='cutout', label=label, status=status, detail=detail)


@router.get('/api/brands')
```

找到（4／5）：

```python


async def _save(services: ApiServices, draft: ProductDraft) -> Product:
    async with services.db.session() as s:
        if await catalog.get_brand(s, draft.brand_id) is None:
            raise Invalid(f'找不到品牌：{draft.brand_id}')
        return await catalog.save_product(s, draft, utc_now())


@router.post('/api/products', status_code=201)
```

改成：

```python


async def _save(services: ApiServices, draft: ProductDraft) -> Product:
    """去背狀態由伺服器管理，請求中的 cutout 一律忽略：新的商品照（新增或換照片）設為去背中並排入佇列，
    其餘沿用原本的值（避免開著編輯視窗時完成的去背被蓋回去背中）。"""
    async with services.db.session() as s:
        if await catalog.get_brand(s, draft.brand_id) is None:
            raise Invalid(f'找不到品牌：{draft.brand_id}')
        previous = await catalog.get_product(s, draft.id) if draft.id else None
        photo = draft.photo if isinstance(draft.photo, FilePhoto) else None
        new_photo = photo is not None and (previous is None or previous.photo != photo)
        cutout: ProductCutout | None
        if new_photo:
            cutout = ProductCutout(model=services.settings.cutout_model, status='pending', url=None, error=None)
        else:
            cutout = previous.cutout if previous else None
        saved = await catalog.save_product(s, draft.model_copy(update={'cutout': cutout}), utc_now())
    if new_photo and photo is not None:
        await services.queues.enqueue_cutout(saved.id, photo.url)
    return saved


@router.post('/api/products', status_code=201)
```

找到（5／5）：

```python

@router.delete('/api/products/{product_id}', status_code=204)
async def delete_product(product_id: str, services: Services) -> None:
    async with services.db.session() as s:
        if not await catalog.delete_product(s, product_id):
            raise NotFound(f'找不到商品：{product_id}')


@router.post('/api/products/photos', status_code=201)
```

改成：

```python

@router.delete('/api/products/{product_id}', status_code=204)
async def delete_product(product_id: str, services: Services) -> None:
    """刪除商品，連同 data/products/{id}/ 的去背圖。"""
    async with services.db.session() as s:
        if not await catalog.delete_product(s, product_id):
            raise NotFound(f'找不到商品：{product_id}')
    folder = services.settings.data_dir / 'products' / product_id
    await asyncio.to_thread(shutil.rmtree, folder, ignore_errors=True)


@router.post('/api/products/photos', status_code=201)
```

- [ ] **Step 7: 確認全部通過**

Run（在 `backend/`）：`uv run pytest -q tests/test_api_catalog.py tests/test_cutout_engine.py`
Expected：20 passed。

Run：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected：沒有錯誤；97 passed、1 skipped。

- [ ] **Step 8: Commit**

```bash
git add \
  backend/app/api/catalog.py \
  backend/app/cutout/engine.py \
  backend/app/cutout/state.py \
  backend/tests/test_api_catalog.py \
  backend/tests/test_cutout_engine.py
git commit -m "feat: queue a cutout for every new product photo and show the model state" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6：前端資料層：定時重新讀取、mock 的去背、海報合成的判斷

**Files:**
- Modify: `web/src/lib/store/products.ts`、`web/src/lib/api/mock/client.ts`、`web/src/lib/compose/assets.ts`
- Test: `web/src/lib/store/products.test.ts`（新）、`web/src/lib/api/mock/client.test.ts`、`web/src/lib/compose/assets.test.ts`

**Interfaces:**
- Consumes：Task 1 的 `ProductCutout`；Task 4 的 `POST …/cutout` 回 202 與 `pending` 的商品。
- Produces：
  - `CUTOUT_POLL_MS = 2_000`（`@/lib/store/products`）。
  - `useProductsStore`：
    - `load` 之後，只要有 `pending` 的商品就排下一次讀取，同一時間只有一個計時器。
    - 讀取失敗時下一輪再試。
    - 切換品牌後停止。
    - `cutout(id)` 之後也會開始讀取。
  - mock：
    - `saveProduct` 忽略送來的 `cutout`；新的商品照設為 `pending`，約 1.2 秒後改為 `done`（`url: null`）。
    - `requestCutout` 立即回傳 `pending`。
    - `listProducts` 會直接完成沒有計時器的 `pending`（例如重新整理頁面後）。
  - `productImage()` 只在 `status === 'done'` 且有 `url` 時使用 PNG。

- [ ] **Step 1: 建立 `web/src/lib/store/products.test.ts`（先寫測試）**

建立 `web/src/lib/store/products.test.ts`：

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Product, ProductCutout } from '@/types/contract';
import { getApiClient } from '@/lib/api';
import { CUTOUT_POLL_MS, useProductsStore } from './products';

const PENDING: ProductCutout = { model: 'birefnet-general', status: 'pending', url: null, error: null };
const DONE: ProductCutout = { model: 'birefnet-general', status: 'done', url: '/files/products/prod_a/cutout-1.png', error: null };

const product = (cutout: ProductCutout | null): Product => ({
  id: 'prod_a', brandId: 'selune', name: '晚安面膜', features: [], price: { sale: 0, original: 0 },
  photo: { source: 'upload', url: '/files/uploads/a.png' }, cutout, createdAt: '2026-10-15T00:00:00.000Z',
});

beforeEach(() => {
  vi.useFakeTimers();
  useProductsStore.setState({ brandId: null, products: [], loading: false, cutting: [] });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('products store', () => {
  it('re-reads the list every 2 seconds while a cutout is pending, without showing the loading state', async () => {
    const list = vi.spyOn(getApiClient(), 'listProducts')
      .mockResolvedValueOnce([product(PENDING)])
      .mockResolvedValueOnce([product(PENDING)])
      .mockResolvedValue([product(DONE)]);
    await useProductsStore.getState().load('selune');
    expect(CUTOUT_POLL_MS).toBe(2_000);
    await vi.advanceTimersByTimeAsync(1_999);
    expect(list).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(list).toHaveBeenCalledTimes(2);
    expect(useProductsStore.getState().loading).toBe(false);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(list).toHaveBeenCalledTimes(3);
    expect(useProductsStore.getState().products[0].cutout).toEqual(DONE);
    // 全部完成後停止
    await vi.advanceTimersByTimeAsync(10_000);
    expect(list).toHaveBeenCalledTimes(3);
  });

  it('stops polling the previous brand after switching brands', async () => {
    const list = vi.spyOn(getApiClient(), 'listProducts')
      .mockImplementation(async (brandId) => (brandId === 'selune' ? [product(PENDING)] : []));
    await useProductsStore.getState().load('selune');
    await useProductsStore.getState().load('misty-isle');
    await vi.advanceTimersByTimeAsync(10_000);
    expect(list.mock.calls.map(([brandId]) => brandId)).toEqual(['selune', 'misty-isle']);
  });

  it('keeps polling after a failed read', async () => {
    const list = vi.spyOn(getApiClient(), 'listProducts')
      .mockResolvedValueOnce([product(PENDING)])
      .mockRejectedValueOnce(new Error('無法連線到後端'))
      .mockResolvedValue([product(DONE)]);
    await useProductsStore.getState().load('selune');
    await vi.advanceTimersByTimeAsync(4_000);
    expect(list).toHaveBeenCalledTimes(3);
    expect(useProductsStore.getState().products[0].cutout).toEqual(DONE);
  });

  it('starts polling after asking for a new cutout', async () => {
    vi.spyOn(getApiClient(), 'listProducts').mockResolvedValueOnce([product(DONE)]).mockResolvedValue([product(DONE)]);
    vi.spyOn(getApiClient(), 'requestCutout').mockResolvedValue(product(PENDING));
    await useProductsStore.getState().load('selune');
    const updated = await useProductsStore.getState().cutout('prod_a');
    expect(updated.cutout).toEqual(PENDING);
    expect(useProductsStore.getState().products[0].cutout).toEqual(PENDING);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(useProductsStore.getState().products[0].cutout).toEqual(DONE);
  });
});
```

- [ ] **Step 2: 修改 `web/src/lib/api/mock/client.test.ts`（先寫測試）**

找到（1／2）：

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobEvent, JobInput, JobMessage } from '@/types/contract';
import type { ApiClient } from '../client';
import { getApiClient } from '../index';
import { MAX_STORED_JOBS, MockApiClient, makeJobId } from './client';
import { MemoryStore } from './store';
```

改成：

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobEvent, JobInput, JobMessage, ProductCutout } from '@/types/contract';
import type { ApiClient, ProductDraft } from '../client';
import { getApiClient } from '../index';
import { MAX_STORED_JOBS, MockApiClient, makeJobId } from './client';
import { MemoryStore } from './store';
```

找到（2／2）：

```ts
    await expect(api.uploadProductPhoto(new Blob(['x'], { type: 'text/plain' }))).rejects.toThrow('只能上傳圖片檔');
  });

  it('simulates a cutout after 1.2 seconds and keeps it on the product', async () => {
    const api = new MockApiClient();
    const saved = await api.saveProduct({
      brandId: 'selune', name: '晚安面膜', features: [], price: { sale: 680, original: 880 },
      photo: { source: 'upload', url: 'data:image/png;base64,AQID' }, cutout: null,
    });
    let done = false;
    const pending = api.requestCutout(saved.id).then((p) => { done = true; return p; });
    await vi.advanceTimersByTimeAsync(1_100);
    expect(done).toBe(false);
    await vi.advanceTimersByTimeAsync(100);
    const product = await pending;
    expect(product.cutout).toEqual({ model: 'BiRefNet-general', status: 'done', url: null, error: null });
    expect(product.createdAt).toBe(saved.createdAt);
    expect((await api.listProducts('selune')).find((p) => p.id === saved.id)?.cutout).not.toBeNull();
    await expect(api.requestCutout('prod_selune_serum')).rejects.toThrow('示範商品已是去背素材');
  });
});
```

改成：

```ts
    await expect(api.uploadProductPhoto(new Blob(['x'], { type: 'text/plain' }))).rejects.toThrow('只能上傳圖片檔');
  });

  const PENDING: ProductCutout = { model: 'BiRefNet-general', status: 'pending', url: null, error: null };
  const DONE: ProductCutout = { model: 'BiRefNet-general', status: 'done', url: null, error: null };
  const DRAFT: ProductDraft = {
    brandId: 'selune', name: '晚安面膜', features: [], price: { sale: 680, original: 880 },
    photo: { source: 'upload', url: 'data:image/png;base64,AQID' }, cutout: null,
  };
  const cutoutOf = async (api: MockApiClient, id: string) => (await api.listProducts('selune')).find((p) => p.id === id)?.cutout;

  it('simulates the cutout of a new photo product in the background, like the backend', async () => {
    const api = new MockApiClient();
    const saved = await api.saveProduct({ ...DRAFT, cutout: DONE });
    // 去背狀態由「伺服器」管理：送來的 cutout 一律忽略
    expect(saved.cutout).toEqual(PENDING);
    await vi.advanceTimersByTimeAsync(1_100);
    expect(await cutoutOf(api, saved.id)).toEqual(PENDING);
    await vi.advanceTimersByTimeAsync(100);
    expect(await cutoutOf(api, saved.id)).toEqual(DONE);
    // 只改名稱：沿用原本的去背結果
    const renamed = await api.saveProduct({ ...DRAFT, id: saved.id, name: '晚安修護面膜' });
    expect(renamed.cutout).toEqual(DONE);
    // 示範商品不需要去背
    const sample = (await api.listProducts('selune'))[0];
    expect((await api.saveProduct({ ...sample, name: '改名' })).cutout).toBeNull();
  });

  it('re-runs a cutout on request and finishes cutouts left pending by a reload', async () => {
    const store = new MemoryStore();
    const api = new MockApiClient(store);
    const saved = await api.saveProduct(DRAFT);
    await vi.advanceTimersByTimeAsync(1_200);
    const again = await api.requestCutout(saved.id);
    expect(again.cutout).toEqual(PENDING);
    expect(again.createdAt).toBe(saved.createdAt);
    await vi.advanceTimersByTimeAsync(1_200);
    expect(await cutoutOf(api, saved.id)).toEqual(DONE);
    await expect(api.requestCutout('prod_selune_serum')).rejects.toThrow('示範商品已是去背素材');
    // 重新整理頁面：排程不在了，下一次讀取時直接完成
    await api.requestCutout(saved.id);
    expect(await cutoutOf(new MockApiClient(store), saved.id)).toEqual(DONE);
  });
});
```

- [ ] **Step 3: 修改 `web/src/lib/compose/assets.test.ts`（先寫測試）**

找到：

```ts
    expect(productImage({ ...upload, cutout: { model: 'BiRefNet-general', status: 'done', url: null, error: null } }, SELUNE).blend).toBe('multiply');
    expect(productImage({ ...upload, cutout: { model: 'BiRefNet-general', status: 'done', url: '/cutout.png', error: null } }, SELUNE))
      .toEqual({ src: '/cutout.png', blend: 'normal' });
  });
});
```

改成：

```ts
    expect(productImage({ ...upload, cutout: { model: 'BiRefNet-general', status: 'done', url: null, error: null } }, SELUNE).blend).toBe('multiply');
    expect(productImage({ ...upload, cutout: { model: 'BiRefNet-general', status: 'done', url: '/cutout.png', error: null } }, SELUNE))
      .toEqual({ src: '/cutout.png', blend: 'normal' });
    // 去背中或失敗：沿用色彩增值
    for (const status of ['pending', 'failed'] as const) {
      expect(productImage({ ...upload, cutout: { model: 'birefnet-general', status, url: '/old.png', error: null } }, SELUNE).blend)
        .toBe('multiply');
    }
  });
});
```

- [ ] **Step 4: 確認測試失敗**

Run: `npx vitest run src/lib/store/products.test.ts src/lib/api/mock/client.test.ts src/lib/compose/assets.test.ts`（在 `web/`）
Expected: FAIL，6 個測試失敗：
- `multiplies an uploaded photo until a real cutout exists`
- `re-reads the list every 2 seconds while a cutout is pending, …`
- `keeps polling after a failed read`
- `starts polling after asking for a new cutout`
- `simulates the cutout of a new photo product in the background, like the backend`
- `re-runs a cutout on request and finishes cutouts left pending by a reload`

（`stops polling the previous brand after switching brands` 在還沒有定時讀取時就會通過。）

- [ ] **Step 5: 修改 `web/src/lib/compose/assets.ts`**

找到：

```ts

export interface ProductImageSource { src: string; blend: 'normal' | 'multiply' }

/** 示範商品用 SVG 素材；上傳照片優先用去背圖，沒有就以色彩增值（multiply）合成 */
export function productImage(product: Product, brand: Brand): ProductImageSource {
  if (product.photo.source === 'sample') {
    return { src: svgDataUrl(productArtSvg(product.photo.art, brand.palette, product.name, logoFor(brand).wordmark)), blend: 'normal' };
  }
  return product.cutout?.url ? { src: product.cutout.url, blend: 'normal' } : { src: product.photo.url, blend: 'multiply' };
}

/** 品牌字型（@fontsource-variable 註冊的名稱帶 Variable），找不到時退回系統字型 */
```

改成：

```ts

export interface ProductImageSource { src: string; blend: 'normal' | 'multiply' }

/** 示範商品用 SVG 素材；上傳照片在去背完成後用透明 PNG，去背中、失敗或示意（url 為 null）時以色彩增值（multiply）合成 */
export function productImage(product: Product, brand: Brand): ProductImageSource {
  if (product.photo.source === 'sample') {
    return { src: svgDataUrl(productArtSvg(product.photo.art, brand.palette, product.name, logoFor(brand).wordmark)), blend: 'normal' };
  }
  const cut = product.cutout;
  return cut?.status === 'done' && cut.url ? { src: cut.url, blend: 'normal' } : { src: product.photo.url, blend: 'multiply' };
}

/** 品牌字型（@fontsource-variable 註冊的名稱帶 Variable），找不到時退回系統字型 */
```

- [ ] **Step 6: 修改 `web/src/lib/api/mock/client.ts`**

找到（1／7）：

```ts
import type {
  ApiOptions, BrandDocument, ConnectionState, Copy, DashboardStats, DemoOptions, HistoryEntry, IngestEvent, JobEvent,
  JobInput, JobMessage, JobStage, JobSummary, LocalPhoto, Product, ProductPhoto, RagChunk, Render, SystemStatus, TemplateId,
} from '@/types/contract';
import type { ApiClient, ConnectionChannel, DemoControls, JobSnapshot, ProductDraft } from '../client';
import { CHANNEL_TEMPLATES, getTemplate } from '@/lib/compose/templates';
```

改成：

```ts
import type {
  ApiOptions, BrandDocument, ConnectionState, Copy, DashboardStats, DemoOptions, HistoryEntry, IngestEvent, JobEvent,
  JobInput, JobMessage, JobStage, JobSummary, LocalPhoto, Product, ProductCutout, ProductPhoto, RagChunk, Render, SystemStatus,
  TemplateId,
} from '@/types/contract';
import type { ApiClient, ConnectionChannel, DemoControls, JobSnapshot, ProductDraft } from '../client';
import { CHANNEL_TEMPLATES, getTemplate } from '@/lib/compose/templates';
```

找到（2／7）：

```ts
  return `job_${date}_${time}_${Math.floor(rand() * 0xffff).toString(16).padStart(4, '0')}`;
}

const makeId = (prefix: string) => `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;

export class MockApiClient implements ApiClient {
```

改成：

```ts
  return `job_${date}_${time}_${Math.floor(rand() * 0xffff).toString(16).padStart(4, '0')}`;
}

/** mock 的去背（示意）：約 1.2 秒後完成，url 為 null（合成時以色彩增值示意） */
const CUTOUT_MS = 1200;
const PENDING_CUTOUT: ProductCutout = { model: 'BiRefNet-general', status: 'pending', url: null, error: null };
const DONE_CUTOUT: ProductCutout = { ...PENDING_CUTOUT, status: 'done' };

const makeId = (prefix: string) => `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;

export class MockApiClient implements ApiClient {
```

找到（3／7）：

```ts
  readonly connection: ConnectionChannel = { get: () => MOCK_CONNECTION, subscribe: () => () => {} };
  private options: DemoOptions = { speed: 1, firstRoundFail: true, forceAllFail: false };
  private readonly jobs = new Map<string, JobRecord>();
  private tail: Promise<unknown> = Promise.resolve();

  constructor(
```

改成：

```ts
  readonly connection: ConnectionChannel = { get: () => MOCK_CONNECTION, subscribe: () => () => {} };
  private options: DemoOptions = { speed: 1, firstRoundFail: true, forceAllFail: false };
  private readonly jobs = new Map<string, JobRecord>();
  /** 去背中的商品 → 完成的計時器（只在記憶體；重新整理後由 listProducts 直接完成） */
  private readonly cutoutTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private tail: Promise<unknown> = Promise.resolve();

  constructor(
```

找到（4／7）：

```ts
  }

  async listProducts(brandId: string): Promise<Product[]> {
    const custom = await this.customProducts();
    const deleted = new Set((await this.store.get<string[]>(KEYS.deleted)) ?? []);
    const customIds = new Set(custom.map((p) => p.id));
```

改成：

```ts
  }

  async listProducts(brandId: string): Promise<Product[]> {
    await this.finishOrphanCutouts();
    const custom = await this.customProducts();
    const deleted = new Set((await this.store.get<string[]>(KEYS.deleted)) ?? []);
    const customIds = new Set(custom.map((p) => p.id));
```

找到（5／7）：

```ts
    return [...samples, ...custom].filter((p) => p.brandId === brandId);
  }

  saveProduct(draft: ProductDraft): Promise<Product> {
    return this.serial(async () => {
      getBrandById(draft.brandId);
```

改成：

```ts
    return [...samples, ...custom].filter((p) => p.brandId === brandId);
  }

  /** 與後端相同：去背狀態由這裡管理，送來的 cutout 一律忽略；新的商品照（新增或換照片）設為去背中 */
  saveProduct(draft: ProductDraft): Promise<Product> {
    return this.serial(async () => {
      getBrandById(draft.brandId);
```

找到（6／7）：

```ts
      const existing = draft.id
        ? (custom.find((p) => p.id === draft.id) ?? SAMPLE_PRODUCTS.find((p) => p.id === draft.id))
        : undefined;
      const product: Product = { ...draft, id: draft.id ?? makeId('prod'), createdAt: existing?.createdAt ?? this.now().toISOString() };
      await this.store.set(KEYS.products, [...custom.filter((p) => p.id !== product.id), product]);
      return product;
    });
  }

  deleteProduct(id: string): Promise<void> {
```

改成：

```ts
      const existing = draft.id
        ? (custom.find((p) => p.id === draft.id) ?? SAMPLE_PRODUCTS.find((p) => p.id === draft.id))
        : undefined;
      const newPhoto = draft.photo.source !== 'sample' && JSON.stringify(existing?.photo) !== JSON.stringify(draft.photo);
      const product: Product = {
        id: draft.id ?? makeId('prod'), brandId: draft.brandId, name: draft.name, features: draft.features, price: draft.price,
        photo: draft.photo, cutout: newPhoto ? PENDING_CUTOUT : (existing?.cutout ?? null),
        createdAt: existing?.createdAt ?? this.now().toISOString(),
      };
      await this.store.set(KEYS.products, [...custom.filter((p) => p.id !== product.id), product]);
      if (newPhoto) this.scheduleCutout(product.id);
      return product;
    });
  }

  private scheduleCutout(id: string): void {
    clearTimeout(this.cutoutTimers.get(id));
    this.cutoutTimers.set(id, setTimeout(() => void this.finishCutouts([id]), CUTOUT_MS / this.options.speed));
  }

  /** 把仍在去背中的商品改為完成 */
  private finishCutouts(ids: string[]): Promise<void> {
    return this.serial(async () => {
      for (const id of ids) {
        clearTimeout(this.cutoutTimers.get(id));
        this.cutoutTimers.delete(id);
      }
      const custom = await this.customProducts();
      const done = (p: Product) => ids.includes(p.id) && p.cutout?.status === 'pending';
      if (custom.some(done)) await this.store.set(KEYS.products, custom.map((p) => (done(p) ? { ...p, cutout: DONE_CUTOUT } : p)));
    });
  }

  /** 沒有計時器的去背中商品（例如重新整理頁面後）直接完成 */
  private async finishOrphanCutouts(): Promise<void> {
    const orphans = (await this.customProducts())
      .filter((p) => p.cutout?.status === 'pending' && !this.cutoutTimers.has(p.id))
      .map((p) => p.id);
    if (orphans.length) await this.finishCutouts(orphans);
  }

  deleteProduct(id: string): Promise<void> {
```

找到（7／7）：

```ts
    return { source: 'upload', url: await toDataUrl(file) };
  }

  async requestCutout(productId: string): Promise<Product> {
    const product = await this.findProduct(productId);
    if (product.photo.source === 'sample') throw new Error('示範商品已是去背素材');
    await this.sleep(1200);
    return this.saveProduct({ ...product, cutout: { model: 'BiRefNet-general', status: 'done', url: null, error: null } });
  }

  async ingestBrandDocument(brandId: string, doc: BrandDocument, onEvent: (e: IngestEvent) => void): Promise<RagChunk[]> {
```

改成：

```ts
    return { source: 'upload', url: await toDataUrl(file) };
  }

  /** 重新去背：設為去背中並立即回傳，約 1.2 秒後完成 */
  async requestCutout(productId: string): Promise<Product> {
    const product = await this.findProduct(productId);
    if (product.photo.source === 'sample') throw new Error('示範商品已是去背素材');
    return this.serial(async () => {
      const pending = { ...product, cutout: PENDING_CUTOUT };
      const custom = await this.customProducts();
      await this.store.set(KEYS.products, custom.map((p) => (p.id === productId ? pending : p)));
      this.scheduleCutout(productId);
      return pending;
    });
  }

  async ingestBrandDocument(brandId: string, doc: BrandDocument, onEvent: (e: IngestEvent) => void): Promise<RagChunk[]> {
```

- [ ] **Step 7: 修改 `web/src/lib/store/products.ts`**

找到：

```ts
  cutout: (id: string) => Promise<Product>;
}

/** 目前品牌的商品清單（商品庫、新任務、批次佇列、歷史紀錄共用） */
export const useProductsStore = create<ProductsState>()((set, get) => ({
  brandId: null,
  products: [],
  loading: false,
  cutting: [],
  load: async (brandId) => {
    set({ brandId, loading: true });
    const products = await getApiClient().listProducts(brandId);
    // 載入期間切換了品牌就丟棄舊結果
    if (get().brandId === brandId) set({ products, loading: false });
  },
  save: async (draft) => {
    const saved = await getApiClient().saveProduct(draft);
    if (get().brandId) await get().load(get().brandId!);
    return saved;
  },
  remove: async (id) => {
    await getApiClient().deleteProduct(id);
    set({ products: get().products.filter((p) => p.id !== id) });
  },
  cutout: async (id) => {
    set({ cutting: [...get().cutting, id] });
    try {
      const updated = await getApiClient().requestCutout(id);
      set({ products: get().products.map((p) => (p.id === id ? updated : p)) });
      return updated;
    } finally {
      set({ cutting: get().cutting.filter((x) => x !== id) });
    }
  },
}));
```

改成：

```ts
  cutout: (id: string) => Promise<Product>;
}

/** 有商品在去背中時，每隔這麼久重新讀取一次商品清單（毫秒） */
export const CUTOUT_POLL_MS = 2_000;

/** 目前品牌的商品清單（商品庫、新任務、批次佇列、歷史紀錄共用） */
export const useProductsStore = create<ProductsState>()((set, get) => {
  let poll: ReturnType<typeof setTimeout> | null = null;

  /** 有去背中的商品就排下一次讀取（同一時間只有一個計時器）；全部完成或失敗、或切換品牌後停止 */
  const schedulePoll = (brandId: string) => {
    if (poll) clearTimeout(poll);
    poll = null;
    if (!get().products.some((p) => p.cutout?.status === 'pending')) return;
    poll = setTimeout(() => {
      poll = null;
      if (get().brandId !== brandId) return;
      getApiClient().listProducts(brandId).then(
        (products) => {
          if (get().brandId !== brandId) return;
          set({ products });
          schedulePoll(brandId);
        },
        // 讀取失敗（例如後端重新啟動）：下一輪再試
        () => {
          if (get().brandId === brandId) schedulePoll(brandId);
        },
      );
    }, CUTOUT_POLL_MS);
  };

  return {
    brandId: null,
    products: [],
    loading: false,
    cutting: [],
    load: async (brandId) => {
      if (poll) clearTimeout(poll);
      poll = null;
      set({ brandId, loading: true });
      const products = await getApiClient().listProducts(brandId);
      // 載入期間切換了品牌就丟棄舊結果
      if (get().brandId !== brandId) return;
      set({ products, loading: false });
      schedulePoll(brandId);
    },
    save: async (draft) => {
      const saved = await getApiClient().saveProduct(draft);
      if (get().brandId) await get().load(get().brandId!);
      return saved;
    },
    remove: async (id) => {
      await getApiClient().deleteProduct(id);
      set({ products: get().products.filter((p) => p.id !== id) });
    },
    cutout: async (id) => {
      set({ cutting: [...get().cutting, id] });
      try {
        const updated = await getApiClient().requestCutout(id);
        set({ products: get().products.map((p) => (p.id === id ? updated : p)) });
        const brandId = get().brandId;
        if (brandId) schedulePoll(brandId);
        return updated;
      } finally {
        set({ cutting: get().cutting.filter((x) => x !== id) });
      }
    },
  };
});
```

- [ ] **Step 8: 確認全部通過**

Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint`
Expected：42 個測試檔、330 個測試通過；沒有錯誤。

- [ ] **Step 9: Commit**

```bash
git add \
  web/src/lib/api/mock/client.test.ts \
  web/src/lib/api/mock/client.ts \
  web/src/lib/compose/assets.test.ts \
  web/src/lib/compose/assets.ts \
  web/src/lib/store/products.test.ts \
  web/src/lib/store/products.ts
git commit -m "feat: poll the product list while cutouts run and simulate them in mock mode" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7：前端畫面：商品卡、去背預覽、上傳提示

**Files:**
- Modify: `web/src/components/product/product-image.tsx`、`web/src/components/product/cutout-dialog.tsx`、`web/src/components/product/product-card.tsx`、`web/src/components/product/upload-zone.tsx`、`web/src/components/product/local-folder.tsx`、`web/src/app/products/page.tsx`、`web/e2e-live/live.spec.ts`

**Interfaces:**
- Consumes：Task 6 的 `useProductsStore`（`cutout`、`cutting`、定時讀取）。
- Produces：
  - `PreviewBackground = 'checker' | 'light' | 'dark'`。
  - `ProductImage` 的 `cutoutPreview` 改為 `preview?: PreviewBackground`：淺色是 `brand.palette.secondary`，深色是 `brand.palette.ink`。
  - `CutoutDialog` 新增 `onRecut(product)`。
  - 上傳提示改為「…正在背景去背，完成後會自動更新；請補上價格與特徵。」（live E2E 的文字同步修改）。

這個專案沒有元件測試，畫面以 typecheck、lint、build、E2E 與瀏覽器檢查驗證。

- [ ] **Step 1: 改寫 `web/src/components/product/product-image.tsx`（完整內容）**

```tsx
import Image from 'next/image';
import type { Brand, Product } from '@/types/contract';
import { productImage } from '@/lib/compose/assets';
import { cn } from '@/lib/utils';

/** 去背預覽的底：透明格紋、品牌輔助色（淺）、品牌文字色（深）；邊緣的殘留在深色上最明顯 */
export type PreviewBackground = 'checker' | 'light' | 'dark';

/**
 * 商品縮圖。preview 時以指定的底色呈現去背結果；還沒有去背圖的照片用色彩增值讓白底「消失」（示意）。
 * 圖片都是 data URL 或本機 API，所以用 unoptimized。
 */
export function ProductImage({
  product, brand, preview, className,
}: { product: Product; brand: Brand; preview?: PreviewBackground; className?: string }) {
  const { src, blend } = productImage(product, brand);
  const background = preview === 'light' ? brand.palette.secondary : preview === 'dark' ? brand.palette.ink : undefined;
  return (
    <div
      className={cn('relative overflow-hidden', preview === 'checker' ? 'bg-checker' : !preview && 'bg-muted', className)}
      style={background ? { backgroundColor: background } : undefined}
    >
      <Image
        src={src}
        alt={product.name}
        fill
        unoptimized
        sizes="320px"
        className={cn('object-contain p-1', preview && blend === 'multiply' && 'mix-blend-multiply')}
      />
    </div>
  );
}
```

- [ ] **Step 2: 改寫 `web/src/components/product/cutout-dialog.tsx`（完整內容）**

```tsx
'use client';

import { useState } from 'react';
import { LoaderCircle, RotateCcw } from 'lucide-react';
import type { Brand, Product } from '@/types/contract';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { ProductImage, type PreviewBackground } from './product-image';

const BACKGROUNDS: { id: PreviewBackground; label: string }[] = [
  { id: 'checker', label: '透明' },
  { id: 'light', label: '淺色' },
  { id: 'dark', label: '深色' },
];

/** 去背預覽：左邊原圖、右邊去背結果（可換底色檢查邊緣），可重新去背 */
export function CutoutDialog({ product, brand, onRecut, onClose }: {
  product: Product | null;
  brand: Brand;
  onRecut: (product: Product) => void;
  onClose: () => void;
}) {
  const [background, setBackground] = useState<PreviewBackground>('checker');
  const cut = product?.cutout;
  return (
    <Dialog open={product !== null} onOpenChange={(o) => !o && onClose()}>
      {product && (
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>去背預覽：{product.name}</DialogTitle>
            <DialogDescription>
              {cut?.status === 'done' && !cut.url
                ? '示意：mock 模式不執行模型，合成時以「色彩增值」讓白底融入背景。'
                : `模型 ${cut?.model ?? 'birefnet-general'}。切換底色可以檢查邊緣是否乾淨，深色最容易看出殘邊。`}
            </DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-4">
            <figure className="space-y-2">
              <ProductImage product={{ ...product, cutout: null }} brand={brand} className="aspect-[4/5] rounded-lg border" />
              <figcaption className="text-center text-xs text-muted-foreground">原圖</figcaption>
            </figure>
            <figure className="space-y-2">
              <div className="relative">
                <ProductImage product={product} brand={brand} preview={background} className="aspect-[4/5] rounded-lg border" />
                {cut?.status === 'pending' && (
                  <div className="absolute inset-0 grid place-items-center rounded-lg bg-background/70 text-sm text-muted-foreground">
                    <span className="flex items-center gap-2"><LoaderCircle className="size-4 animate-spin" />去背中…</span>
                  </div>
                )}
                {cut?.status === 'failed' && (
                  <div className="absolute inset-0 grid place-items-center rounded-lg bg-background/80 p-4 text-center text-sm text-destructive">
                    去背失敗：{cut.error}
                  </div>
                )}
              </div>
              <figcaption className="flex justify-center">
                <ToggleGroup
                  type="single"
                  variant="outline"
                  size="sm"
                  value={background}
                  onValueChange={(v) => v && setBackground(v as PreviewBackground)}
                  aria-label="預覽底色"
                >
                  {BACKGROUNDS.map((b) => (
                    <ToggleGroupItem key={b.id} value={b.id} className="px-3">{b.label}</ToggleGroupItem>
                  ))}
                </ToggleGroup>
              </figcaption>
            </figure>
          </div>
          <DialogFooter>
            <Button variant="outline" disabled={cut?.status === 'pending'} onClick={() => onRecut(product)}>
              <RotateCcw />
              重新去背
            </Button>
          </DialogFooter>
        </DialogContent>
      )}
    </Dialog>
  );
}
```

- [ ] **Step 3: 修改 `web/src/components/product/product-card.tsx`**

找到（1／4）：

```tsx
'use client';

import { LoaderCircle, Pencil, Scissors, Trash } from 'lucide-react';
import type { Brand, Product } from '@/types/contract';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
```

改成：

```tsx
'use client';

import { LoaderCircle, Pencil, RotateCcw, Scissors, Trash } from 'lucide-react';
import type { Brand, Product } from '@/types/contract';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
```

找到（2／4）：

```tsx

const SOURCE_LABEL = { sample: '示範素材', upload: '上傳', local: '本機資料夾' } as const;

export function ProductCard({ product, brand, onEdit, onCutout, onDelete }: {
  product: Product;
  brand: Brand;
```

改成：

```tsx

const SOURCE_LABEL = { sample: '示範素材', upload: '上傳', local: '本機資料夾' } as const;

/** 去背狀態的標籤（示範商品與沒有去背的商品不顯示） */
function CutoutBadge({ product }: { product: Product }) {
  const cut = product.cutout;
  if (!cut) return null;
  if (cut.status === 'pending') {
    return (
      <Badge variant="outline" className="gap-1 border-sky-200 bg-sky-50 text-sky-700">
        <LoaderCircle className="animate-spin" />
        去背中…
      </Badge>
    );
  }
  if (cut.status === 'failed') {
    return <Badge variant="outline" className="border-red-200 bg-red-50 text-red-700" title={cut.error ?? undefined}>去背失敗</Badge>;
  }
  return (
    <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-emerald-700">
      {cut.url ? '已去背' : '已去背（示意）'}
    </Badge>
  );
}

export function ProductCard({ product, brand, onEdit, onCutout, onDelete }: {
  product: Product;
  brand: Brand;
```

找到（3／4）：

```tsx
  onCutout: () => void;
  onDelete: () => void;
}) {
  const cutting = useProductsStore((s) => s.cutting.includes(product.id));
  const isPhoto = product.photo.source !== 'sample';
  return (
    <div className="flex flex-col overflow-hidden rounded-xl border bg-card">
      <ProductImage product={product} brand={brand} className="aspect-[4/5]" />
      <div className="flex flex-1 flex-col gap-2 p-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="secondary">{SOURCE_LABEL[product.photo.source]}</Badge>
          {product.cutout && <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-emerald-700">已去背（示意）</Badge>}
          {product.price.sale === 0 && <Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-800">請補上價格</Badge>}
        </div>
        <p className="leading-snug font-semibold">{product.name}</p>
```

改成：

```tsx
  onCutout: () => void;
  onDelete: () => void;
}) {
  const requesting = useProductsStore((s) => s.cutting.includes(product.id));
  const isPhoto = product.photo.source !== 'sample';
  const status = product.cutout?.status;
  const busy = requesting || status === 'pending';
  return (
    <div className="flex flex-col overflow-hidden rounded-xl border bg-card">
      <ProductImage product={product} brand={brand} className="aspect-[4/5]" />
      <div className="flex flex-1 flex-col gap-2 p-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="secondary">{SOURCE_LABEL[product.photo.source]}</Badge>
          <CutoutBadge product={product} />
          {product.price.sale === 0 && <Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-800">請補上價格</Badge>}
        </div>
        <p className="leading-snug font-semibold">{product.name}</p>
```

找到（4／4）：

```tsx
            編輯
          </Button>
          {isPhoto && (
            <Button size="sm" variant="outline" disabled={cutting} onClick={onCutout}>
              {cutting ? <LoaderCircle className="animate-spin" /> : <Scissors />}
              {cutting ? '去背中…' : '去背預覽'}
            </Button>
          )}
          <Button size="icon-sm" variant="ghost" className="ml-auto text-muted-foreground hover:text-destructive" aria-label={`刪除 ${product.name}`} onClick={onDelete}>
```

改成：

```tsx
            編輯
          </Button>
          {isPhoto && (
            <Button size="sm" variant="outline" disabled={busy} onClick={onCutout}>
              {busy ? <LoaderCircle className="animate-spin" /> : status === 'failed' ? <RotateCcw /> : <Scissors />}
              {busy ? '去背中…' : status === 'failed' ? '重試去背' : status === 'done' ? '去背預覽' : '去背'}
            </Button>
          )}
          <Button size="icon-sm" variant="ghost" className="ml-auto text-muted-foreground hover:text-destructive" aria-label={`刪除 ${product.name}`} onClick={onDelete}>
```

- [ ] **Step 4: 修改 `web/src/app/products/page.tsx`**

找到（1／3）：

```tsx
    void load(brand.id);
  }, [brand.id, load]);

  const startCutout = async (p: Product) => {
    if (p.cutout) {
      setPreviewId(p.id);
      return;
    }
    try {
      await cutout(p.id);
      setPreviewId(p.id);
    } catch (err) {
      toast.error('去背失敗', { description: err instanceof Error ? err.message : String(err) });
    }
  };

  return (
```

改成：

```tsx
    void load(brand.id);
  }, [brand.id, load]);

  /** 重新去背：排入佇列後立即回來，完成時商品清單會自動更新 */
  const recut = async (p: Product) => {
    try {
      await cutout(p.id);
      toast.success(`已重新排入去背：${p.name}`, { description: '完成後會自動更新。' });
    } catch (err) {
      toast.error('無法重新去背', { description: err instanceof Error ? err.message : String(err) });
    }
  };

  const startCutout = (p: Product) => {
    if (p.cutout?.status === 'done') setPreviewId(p.id);
    else void recut(p);
  };

  return (
```

找到（2／3）：

```tsx
                product={p}
                brand={brand}
                onEdit={() => setEditing(p)}
                onCutout={() => void startCutout(p)}
                onDelete={() => setDeleting(p)}
              />
            ))}
```

改成：

```tsx
                product={p}
                brand={brand}
                onEdit={() => setEditing(p)}
                onCutout={() => startCutout(p)}
                onDelete={() => setDeleting(p)}
              />
            ))}
```

找到（3／3）：

```tsx
      </div>

      <ProductEditDialog product={editing} onClose={() => setEditing(null)} />
      <CutoutDialog product={preview} brand={brand} onClose={() => setPreviewId(null)} />
      <Dialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)}>
        {deleting && (
          <DialogContent className="sm:max-w-sm">
```

改成：

```tsx
      </div>

      <ProductEditDialog product={editing} onClose={() => setEditing(null)} />
      <CutoutDialog product={preview} brand={brand} onRecut={(p) => void recut(p)} onClose={() => setPreviewId(null)} />
      <Dialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)}>
        {deleting && (
          <DialogContent className="sm:max-w-sm">
```

- [ ] **Step 5: 修改 `web/src/components/product/upload-zone.tsx`**

找到：

```tsx
        const photo = await api.uploadProductPhoto(await downscaleImage(file));
        await save({ brandId: brand.id, name: nameFromFile(file.name), features: [], price: { sale: 0, original: 0 }, photo, cutout: null });
      }
      toast.success(`已新增 ${images.length} 個商品`, { description: `${STORED_AT}請補上價格與特徵。` });
    } catch (err) {
      toast.error('上傳失敗', { description: err instanceof Error ? err.message : String(err) });
    } finally {
```

改成：

```tsx
        const photo = await api.uploadProductPhoto(await downscaleImage(file));
        await save({ brandId: brand.id, name: nameFromFile(file.name), features: [], price: { sale: 0, original: 0 }, photo, cutout: null });
      }
      toast.success(`已新增 ${images.length} 個商品`, { description: `${STORED_AT}正在背景去背，完成後會自動更新；請補上價格與特徵。` });
    } catch (err) {
      toast.error('上傳失敗', { description: err instanceof Error ? err.message : String(err) });
    } finally {
```

- [ ] **Step 6: 修改 `web/src/components/product/local-folder.tsx`**

找到：

```tsx
    try {
      await getApiClient().importLocalPhoto(photo.file, brand.id);
      await load(brand.id);
      toast.success(`已匯入「${photo.name}」`, { description: '請到卡片上補上價格與特徵。' });
    } catch (err) {
      toast.error('匯入失敗', { description: err instanceof Error ? err.message : String(err) });
    } finally {
```

改成：

```tsx
    try {
      await getApiClient().importLocalPhoto(photo.file, brand.id);
      await load(brand.id);
      toast.success(`已匯入「${photo.name}」`, { description: '正在背景去背，完成後會自動更新；請到卡片上補上價格與特徵。' });
    } catch (err) {
      toast.error('匯入失敗', { description: err instanceof Error ? err.message : String(err) });
    } finally {
```

- [ ] **Step 7: 修改 `web/e2e-live/live.spec.ts`（先寫測試）**

找到：

```ts
  await page.locator('input[type="file"]').first().setInputFiles({
    name: 'e2e_cream.png', mimeType: 'image/png', buffer: Buffer.from(png, 'base64'),
  });
  await expect(page.getByText('照片已上傳到後端（data/uploads/）。請補上價格與特徵。')).toBeVisible();
  const products: { photo: { source: string; url?: string } }[] = await (await page.request.get('/api/products?brandId=selune')).json();
  const url = products.find((p) => p.photo.source === 'upload')!.photo.url!;
  expect(url).toMatch(/^\/files\/uploads\/[0-9a-f]{16}\.(png|jpg|webp)$/);
```

改成：

```ts
  await page.locator('input[type="file"]').first().setInputFiles({
    name: 'e2e_cream.png', mimeType: 'image/png', buffer: Buffer.from(png, 'base64'),
  });
  await expect(page.getByText('照片已上傳到後端（data/uploads/）。正在背景去背，完成後會自動更新；請補上價格與特徵。')).toBeVisible();
  const products: { photo: { source: string; url?: string } }[] = await (await page.request.get('/api/products?brandId=selune')).json();
  const url = products.find((p) => p.photo.source === 'upload')!.photo.url!;
  expect(url).toMatch(/^\/files\/uploads\/[0-9a-f]{16}\.(png|jpg|webp)$/);
```

- [ ] **Step 8: 確認通過**

Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint && npm run build && npm run e2e`
Expected：42 個測試檔、330 個測試通過；沒有錯誤；mock E2E 5 passed。

- [ ] **Step 9: 在瀏覽器確認（mock 模式）**

Docker 的 web 佔用 3000，所以改用別的埠：

```bash
npx next dev -p 3110
```

打開 http://127.0.0.1:3110/products：
- 上傳一張商品照：提示含「正在背景去背」；商品卡先顯示「去背中…」，不必重新整理就變成「已去背（示意）」。
- 「去背預覽」→ 切換「深色」：右邊的底色是品牌的文字色（Selune 為 `#3A3335`）。
- 「重新去背」：右邊蓋上「去背中…」，按鈕停用，並出現「已重新排入去背」；約 1.2 秒後恢復。

做完後停止開發伺服器。

- [ ] **Step 10: Commit**

```bash
git add \
  web/e2e-live/live.spec.ts \
  web/src/app/products/page.tsx \
  web/src/components/product/cutout-dialog.tsx \
  web/src/components/product/local-folder.tsx \
  web/src/components/product/product-card.tsx \
  web/src/components/product/product-image.tsx \
  web/src/components/product/upload-zone.tsx
git commit -m "feat: show cutout progress on product cards and preview cutouts on three backgrounds" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8：Docker、設定與文件，以及實機驗收

**Files:**
- Modify: `docker-compose.yml`、`docker-compose.e2e.yml`、`.env.example`、`README.md`、`backend/README.md`、`web/README.md`、`web/e2e-live/live.spec.ts`

**Interfaces:**
- Consumes：Task 3 的 `CUTOUT_MODEL`、`MODELS_DIR`；Task 7 的「已去背」標籤與「去背預覽」按鈕。
- Produces：
  - worker 掛載 `models` volume（`/app/models`）。
  - live E2E 以 `CUTOUT_MODEL=sim` 執行。
  - `.env.example` 說明 `CUTOUT_MODEL`。

- [ ] **Step 1: 修改 `docker-compose.yml`**

找到（1／3）：

```yaml
    BRANDS_DIR: /app/brands
    DATA_DIR: /app/data
    LOCAL_PHOTOS_DIR: /app/assets/products
  volumes:
    - ./brands:/app/brands:ro
    - ./assets/products:/app/assets/products:ro
```

改成：

```yaml
    BRANDS_DIR: /app/brands
    DATA_DIR: /app/data
    LOCAL_PHOTOS_DIR: /app/assets/products
    MODELS_DIR: /app/models
  volumes:
    - ./brands:/app/brands:ro
    - ./assets/products:/app/assets/products:ro
```

找到（2／3）：

```yaml
  worker:
    <<: *backend
    command: ['python', '-m', 'app.worker']
    depends_on:
      api: { condition: service_healthy }
```

改成：

```yaml
  worker:
    <<: *backend
    command: ['python', '-m', 'app.worker']
    volumes:
      - ./brands:/app/brands:ro
      - ./assets/products:/app/assets/products:ro
      - ./data:/app/data
      # 去背模型（BiRefNet）：第一次啟動時下載，約 1 GB
      - models:/app/models
    depends_on:
      api: { condition: service_healthy }
```

找到（3／3）：

```yaml
volumes:
  postgres:
  redis:
```

改成：

```yaml
volumes:
  postgres:
  redis:
  models:
```

- [ ] **Step 2: 修改 `docker-compose.e2e.yml`**

找到：

```yaml
    SIM_SPEED: '1'
    SIM_FIRST_ROUND_FAIL: 'true'
    SIM_FORCE_ALL_FAIL: 'false'
  volumes: !override
    - ./brands:/app/brands:ro
    - e2e-photos:/app/assets/products:ro
```

改成：

```yaml
    SIM_SPEED: '1'
    SIM_FIRST_ROUND_FAIL: 'true'
    SIM_FORCE_ALL_FAIL: 'false'
    # 模擬去背：不下載約 1 GB 的模型
    CUTOUT_MODEL: sim
  volumes: !override
    - ./brands:/app/brands:ro
    - e2e-photos:/app/assets/products:ro
```

- [ ] **Step 3: 修改 `.env.example`**

找到：

```text
SIM_FORCE_ALL_FAIL=false
# 任務 id 使用的時區
TIMEZONE=Asia/Taipei

# 之後的計畫會加入：
# GEMINI_API_KEY=                                  Plan 6：Gemini（LLM 與 VLM）
```

改成：

```text
SIM_FORCE_ALL_FAIL=false
# 任務 id 使用的時區
TIMEZONE=Asia/Taipei
# 商品照去背的模型：birefnet-general（預設，效果最好，每張約 10 秒）、birefnet-general-lite（較快，邊緣較粗糙），
# 或不需要模型的 sim（測試用）。第一次啟動時下載模型（約 1 GB），去背時約使用 6.5 GB 記憶體
CUTOUT_MODEL=birefnet-general

# 之後的計畫會加入：
# GEMINI_API_KEY=                                  Plan 6：Gemini（LLM 與 VLM）
```

- [ ] **Step 4: 修改 `README.md`**

找到：

```markdown
- 前端：http://127.0.0.1:3000
- API 文件：http://127.0.0.1:3000/docs
- 停止：`docker compose down`（資料保留在 volume；加上 `-v` 會清空資料庫）
- 設定：複製 `.env.example` 成 `.env` 後修改（模擬速度、首輪是否刻意失誤等），再 `docker compose up -d`

自己的資料：

- **品牌**：複製 `brands/_template.yaml` 成 `brands/<品牌 id>.yaml` 填寫，改完執行 `docker compose restart api worker`。格式錯誤的品牌會略過，原因顯示在系統狀態。
- **商品照**：放在 `assets/products/`，到「商品庫 → 本機資料夾」匯入；也可以直接上傳（存在 `data/`）。這兩個資料夾都不會上傳 GitHub。

## 只看前端（mock 模式）
```

改成：

```markdown
- 前端：http://127.0.0.1:3000
- API 文件：http://127.0.0.1:3000/docs
- 停止：`docker compose down`（資料保留在 volume；加上 `-v` 會清空資料庫）
- 設定：複製 `.env.example` 成 `.env` 後修改（模擬速度、首輪是否刻意失誤、去背模型等），再 `docker compose up -d`
- 商品照去背：worker 以 BiRefNet（ONNX Runtime）執行，新增商品時自動去背，每張約 10 秒。第一次啟動時下載模型（約 1 GB，存在 `models` volume），右上角的系統狀態會顯示下載與載入進度。去背時 worker 約使用 6.5 GB 記憶體

自己的資料：

- **品牌**：複製 `brands/_template.yaml` 成 `brands/<品牌 id>.yaml` 填寫，改完執行 `docker compose restart api worker`。格式錯誤的品牌會略過，原因顯示在系統狀態。
- **商品照**：放在 `assets/products/`，到「商品庫 → 本機資料夾」匯入；也可以直接上傳（存在 `data/`）。這兩個資料夾都不會上傳 GitHub。去背結果存在 `data/products/{商品 id}/`。

## 只看前端（mock 模式）
```

- [ ] **Step 5: 修改 `backend/README.md`**

找到（1／3）：

```markdown
## 任務流程

1. `POST /api/jobs` 驗證後寫入任務，送出 `job.accepted` 與 `job.status queued`，放進 `jobs` 佇列。
2. worker 一次執行一個生圖任務（只有一張 GPU）；去背、文件上傳與回寫在 `tasks` 佇列，最多同時兩個。
3. 每則事件在同一個交易中鎖定任務列並取得下一個 `seq`，commit 後發布到 Redis 頻道 `job:{id}`；結束任務的 `job.status` 一定是最後一則。
4. 取消：排隊中的直接取消；執行中的設定旗標，worker 在步驟之間停止。
```

改成：

```markdown
## 任務流程

1. `POST /api/jobs` 驗證後寫入任務，送出 `job.accepted` 與 `job.status queued`，放進 `jobs` 佇列。
2. worker 一次執行一個生圖任務（只有一張 GPU）；文件上傳與回寫在 `tasks` 佇列，最多同時兩個；商品照去背在 `cutouts` 佇列，一次一個。
3. 每則事件在同一個交易中鎖定任務列並取得下一個 `seq`，commit 後發布到 Redis 頻道 `job:{id}`；結束任務的 `job.status` 一定是最後一則。
4. 取消：排隊中的直接取消；執行中的設定旗標，worker 在步驟之間停止。
```

找到（2／3）：

```markdown
├─ api/            FastAPI：main.py（入口與錯誤格式）、catalog、jobs、files、services
├─ pipeline/       任務流程（runner）、外部服務介面（ports）、模擬版（sim）
├─ adapters/       composer 用戶端
├─ core/           時間（clock：一律 UTC）與偽隨機數（rng：與前端的 num.ts 相同，模擬的 seed 才會一致）
├─ db/             SQLAlchemy 模型與連線
├─ repo/           資料存取：品牌與商品（catalog）、任務（jobs）、歷史紀錄（history）
```

改成：

```markdown
├─ api/            FastAPI：main.py（入口與錯誤格式）、catalog、jobs、files、services
├─ pipeline/       任務流程（runner）、外部服務介面（ports）、模擬版（sim）
├─ adapters/       composer 用戶端
├─ cutout/         商品照去背：前後處理（processing）、BiRefNet 與模擬版（segmenter）、模型下載（models）、準備與狀態（engine）
├─ core/           時間（clock：一律 UTC）與偽隨機數（rng：與前端的 num.ts 相同，模擬的 seed 才會一致）
├─ db/             SQLAlchemy 模型與連線
├─ repo/           資料存取：品牌與商品（catalog）、任務（jobs）、歷史紀錄（history）
```

找到（3／3）：

```markdown
├─ errors.py       領域錯誤（AppError 與子類別）；api 轉成 { error: { code, message } }
├─ templates.py    通路模板（與 web/src/lib/compose/templates.ts 相同）
├─ events.py       事件保存與推送、WebSocket 串流
├─ queues.py       SAQ 佇列
├─ worker.py       worker 的任務與啟動時復原
├─ brands.py       品牌設定檔（brands/*.yaml）的驗證與匯入
```

改成：

```markdown
├─ errors.py       領域錯誤（AppError 與子類別）；api 轉成 { error: { code, message } }
├─ templates.py    通路模板（與 web/src/lib/compose/templates.ts 相同）
├─ events.py       事件保存與推送、WebSocket 串流
├─ files.py        /files/... 網址與資料夾的對應（api 提供檔案、worker 讀取商品照）
├─ queues.py       SAQ 佇列
├─ worker.py       worker 的任務與啟動時復原
├─ brands.py       品牌設定檔（brands/*.yaml）的驗證與匯入
```

- [ ] **Step 6: 修改 `web/README.md`**

找到：

```markdown
| 模式 | 路由 | 頁面 |
|---|---|---|
| 工作台 | `/studio` | 新任務：一句話需求 → 生成 → 挑圖改字 → 匯出 zip |
| 工作台 | `/products` | 商品庫：上傳／拖放、去背預覽（示意）、本機資料夾匯入（live 模式） |
| 工作台 | `/queue` | 批次佇列：多商品 × 多模板 |
| 工作台 | `/history` | 歷史紀錄：篩選、收藏、以相同設定重做 |
| 工作台 | `/brands` | 品牌知識庫：CI、禁用詞、RAG 切塊、上傳文件 |
```

改成：

```markdown
| 模式 | 路由 | 頁面 |
|---|---|---|
| 工作台 | `/studio` | 新任務：一句話需求 → 生成 → 挑圖改字 → 匯出 zip |
| 工作台 | `/products` | 商品庫：上傳／拖放、自動去背（live：BiRefNet；mock：示意）與預覽、本機資料夾匯入（live 模式） |
| 工作台 | `/queue` | 批次佇列：多商品 × 多模板 |
| 工作台 | `/history` | 歷史紀錄：篩選、收藏、以相同設定重做 |
| 工作台 | `/brands` | 品牌知識庫：CI、禁用詞、RAG 切塊、上傳文件 |
```

- [ ] **Step 7: 修改 `web/e2e-live/live.spec.ts`（先寫測試）**

去背完成後，商品卡的縮圖會換成透明 PNG，所以改為檢查去背圖，原圖改到預覽視窗裡檢查：

找到：

```ts
  const products: { photo: { source: string; url?: string } }[] = await (await page.request.get('/api/products?brandId=selune')).json();
  const url = products.find((p) => p.photo.source === 'upload')!.photo.url!;
  expect(url).toMatch(/^\/files\/uploads\/[0-9a-f]{16}\.(png|jpg|webp)$/);
  const img = page.locator(`img[src="${url}"]`).first();
  await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0);
});
```

改成：

```ts
  const products: { photo: { source: string; url?: string } }[] = await (await page.request.get('/api/products?brandId=selune')).json();
  const url = products.find((p) => p.photo.source === 'upload')!.photo.url!;
  expect(url).toMatch(/^\/files\/uploads\/[0-9a-f]{16}\.(png|jpg|webp)$/);
  // 背景去背（CUTOUT_MODEL=sim）完成後，商品卡改用透明 PNG
  await expect(page.getByText('已去背', { exact: true })).toBeVisible();
  const cut = page.locator('img[src^="/files/products/"]').first();
  await expect.poll(() => cut.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0);
  await page.getByRole('button', { name: '去背預覽' }).click();
  const original = page.getByRole('dialog').locator(`img[src="${url}"]`);
  await expect.poll(() => original.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0);
});
```

- [ ] **Step 8: 確認通過**

Run（在 repo 根目錄）：`docker compose config --quiet`
Expected：沒有輸出。

Run（在 `web/`）：`npm run e2e:live`
Expected：
- 6 passed（約 2 分鐘，含建置）。
- 結束時移除 `genai-agent-e2e` 的容器與 volume。

- [ ] **Step 9: 實機驗收（真正的 birefnet-general）**

1. **啟動獨立的專案。** 不要直接 `docker compose up`：專案名稱 `genai-agent` 會取代使用者正在用的服務。改用獨立專案，只開放 `127.0.0.1:3300`，並用真正的模型。
   - 在暫存資料夾建立 `cutout-accept.yml`：

```yaml
services:
  api:
    environment:
      CUTOUT_MODEL: birefnet-general
  worker:
    environment:
      CUTOUT_MODEL: birefnet-general
    volumes: !override
      - ./brands:/app/brands:ro
      - e2e-photos:/app/assets/products:ro
      - e2e-data:/app/data
      - models:/app/models
  web:
    ports: !override ['127.0.0.1:3300:80']
```

   - 在 repo 根目錄啟動：

```bash
docker compose -p cutout-accept -f docker-compose.yml -f docker-compose.e2e.yml -f <暫存資料夾>/cutout-accept.yml up -d --build --wait
```

2. **等模型準備好。**
   - 每 5 秒讀一次 `http://127.0.0.1:3300/api/status`。
   - `cutout` 元件依序出現「第一次使用，正在下載模型（約 1 GB）」→「正在載入 birefnet-general」→「birefnet-general 已載入」（`ok`）。
   - 實測約 98 秒。
3. **上傳並計時。**
   - 經 `http://127.0.0.1:3300` 上傳一張真實商品照（`POST /api/products/photos`），建立商品，再每 0.5 秒讀一次商品清單，直到 `cutout.status` 不再是 `pending`。
   - Expected：
     - `done`，`url` 為 `/files/products/{id}/cutout-….png`；
     - 從建立到完成約 16 秒；
     - PNG 四個角透明、商品中央不透明；
     - `docker stats` 取樣的 worker 記憶體：平常約 1.7 GiB，去背時約 4.6–6.5 GiB。
4. **瀏覽器檢查。**
   - 打開 http://127.0.0.1:3300/products：商品卡顯示「已去背」，縮圖是去背 PNG。
   - 到 `/studio` 選這個商品，按「開始生成」，等文字編輯器出現。
   - 網路請求中應該有 `GET /files/products/{id}/cutout-….png`（200）。海報上的商品沒有原照片的背景。
5. **結束後移除。**

```bash
docker compose -p cutout-accept -f docker-compose.yml -f docker-compose.e2e.yml -f <暫存資料夾>/cutout-accept.yml down -v
```

- [ ] **Step 10: Commit**

```bash
git add \
  .env.example \
  README.md \
  backend/README.md \
  docker-compose.e2e.yml \
  docker-compose.yml \
  web/README.md \
  web/e2e-live/live.spec.ts
git commit -m "build: keep the cutout model in a Docker volume and document automatic cutouts" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 完成後

- 使用者的 Docker 版（專案 `genai-agent`）在合併後執行 `docker compose up -d --build`，就會使用新版。
  - worker 第一次啟動時下載模型，存在 `genai-agent_models` volume。
  - 資料庫遷移 `0002` 會把既有的上傳商品改為去背中，worker 啟動後自動補做。
- Plan 7（ComfyUI）的 workflow 直接讀取 `cutout.url` 的透明 PNG，不再在 ComfyUI 裡去背（規格已更新）。
