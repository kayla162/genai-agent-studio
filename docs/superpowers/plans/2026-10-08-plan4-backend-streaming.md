# Plan 4：後端骨架與即時串流 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** live 模式以模擬資料跑完整流程。完成後：
- `docker compose up -d --build` 啟動整套服務，在 http://127.0.0.1:3000 使用 live 版前端。
- 任務由後端的 worker 執行，事件經 WebSocket 即時送到前端；斷線、重新整理、API 重新啟動後都能接續。
- 品牌來自 `brands/*.yaml`（含使用者自己的品牌與 Logo 圖檔），商品照可上傳或從 `assets/products/` 匯入。
- Gemini、RAG、ComfyUI 先用模擬版，行為與第一階段的 mock 劇本相同；Plan 5–7 逐一換成真實版。

**Architecture:**
- **後端（`backend/`，Python 3.13、uv）**：
  - api（FastAPI）：REST、WebSocket、`/files`。
  - worker（SAQ）：`jobs` 佇列一次執行一個生圖任務；`tasks` 佇列處理去背、文件上傳、回寫。
  - PostgreSQL（SQLAlchemy 2 async、Alembic）保存品牌、商品、任務事件與歷史紀錄；Redis 負責佇列與事件推送。
- **事件**：每則事件在同一個交易中鎖定任務列、取得下一個 `seq` 並寫入資料庫，commit 後發布到 Redis。WebSocket 先訂閱、再從資料庫補送 `seq` 之後的事件，依 `seq` 去除重複；結束任務的 `job.status` 一定是最後一則。
- **composer（`web/composer/`，Node）**：直接執行前端的 TypeScript（版型、mock 的 Agent 與審查邏輯）。後端的模擬版透過它沿用同一份程式，前後端只有一份實作。
- **一致性**：TypeScript 產生 golden fixtures（`contracts/fixtures/`）。pytest 驗證三件事都與前端完全相同：Pydantic 合約、亂數、模擬流程的每一則事件與儀表板統計。
- **前端**：
  - `HttpApiClient` 實作同一個 `ApiClient` 介面：REST 用 fetch；WebSocket 斷線後以最後的 `seq` 重新連線。
  - 靜態輸出：live 版由 nginx 提供並轉送 `/api`、`/files`、`/ws`、`/docs`；mock 版之後部署到 Cloudflare。

**Tech Stack:**
- 後端：Python 3.13、uv 0.12、FastAPI 0.142、Pydantic 2.13（pydantic-settings 2.15）、SQLAlchemy 2.1（asyncpg 0.32）、Alembic 1.20、SAQ 0.26、redis-py 8.1、uvicorn 0.54（`[standard]`，含 websockets）、httpx 0.28、PyYAML、tzdata。
- 後端測試與檢查：pytest 9.1、pytest-asyncio 1.4、ruff 0.16、mypy 2.4（strict）。
- 服務：PostgreSQL 18、Redis 8、nginx 1.29（映像檔取自 `public.ecr.aws/docker/library`）。
- 前端：沿用 Plan 3（Next.js 16.3、React 19.2、TypeScript strict、Vitest 5、Playwright 1.63），新增 tsx 4.23（執行 composer 與 fixtures 腳本）。

**Spec:** `docs/superpowers/specs/2026-10-07-phase2-backend-design.md`

**Plan series:** 第二階段共 5 份計畫（Plan 4–8），本文件是第 1 份。完成後 live 模式以模擬資料跑完整流程；Plan 5 起逐一把 RAG、Gemini、ComfyUI 換成真實版。

## 開始前

- `main` 必須已合併兩個分支：
  - `fix/agent-job-picker-live-stage`：Agent 透視的任務選單修正。
  - `docs/phase2-spec`：第二階段規格。
- 需要的工具：
  - Docker Desktop。不必登入 Docker Hub，映像檔都取自 AWS 的官方映像鏡像。
  - uv 0.12 以上；Python 3.13 由 uv 自動下載。
  - Node.js 24、npm 11。
- Windows 注意事項：
  - 原生 PostgreSQL 若已使用 5432 埠，Docker 的 postgres 改用 **5433**。
  - 一律用 `127.0.0.1`，不要用 `localhost`：Windows 會先試 IPv6 的 `::1`，每次連線多等約 2 秒。

## 本計畫的驗證方式

本計畫的程式碼已在獨立副本上逐 Task 實作並驗證：
- 從 `main`（合併上述兩個分支後）開始，只依本文件的步驟重建；每一段程式碼都直接取自驗證過的版本。
- 每個 Task 都驗證過三件事：
  - 「先寫測試」的步驟確實失敗，失敗方式與 Expected 相同。
  - 結束時全部通過，測試數量與 Expected 相同。
  - 型別檢查（tsc、mypy strict）與 lint（ESLint、ruff）沒有錯誤。
- 最後全部通過：
  - 後端：`uv run pytest`（63 個）、ruff、mypy。
  - 前端：`npm run test`（41 個測試檔、314 個測試）、`npm run typecheck`、`npm run lint`、`npm run build`。
  - E2E：`npm run e2e`（mock，5 個）、`npm run e2e:live`（live，6 個）。
  - Docker：`docker compose up -d --build` 後，經 nginx 跑完整任務。
- 每個頁面都用瀏覽器在 live 模式實際操作過：
  - 新任務：執行中重新整理後接續、取消。
  - 系統狀態、Agent 透視、儀表板、歷史紀錄。
  - 品牌文件上傳、商品照上傳、去背、本機資料夾匯入。
  - 自己的品牌與 Logo 圖檔。

執行時若結果與 Expected 不同，先檢查是否漏了步驟，不要修改測試來配合。

## Global Constraints

- 指令在哪裡執行：
  - 前端在 `web/`。
  - 後端在 `backend/`。
  - `docker compose` 在 repo 根目錄。
- 後端的資料庫測試需要 `docker compose up -d postgres redis`。
- 後端：
  - Python 3.13，以 uv 管理。
  - `uv run ruff check .`、`uv run ruff format --check .`（單引號、行寬 120）與 `uv run mypy`（strict）都必須通過。
- **前後端資料約定**：
  - `backend/app/contract.py` 與 `web/src/types/contract.ts` 的欄位名稱、型別、選填規則完全一致。
  - JSON 一律使用 camelCase（Pydantic alias 產生）；模型拒絕多餘欄位。
- 時間一律 UTC，字串格式與 JavaScript 的 `Date.toISOString()` 相同（毫秒、結尾 `Z`）。
- 本機連線一律用 `127.0.0.1`。Docker 的 postgres 在 `127.0.0.1:5433`，redis 在 `127.0.0.1:6379`。所有連接埠只綁定 `127.0.0.1`。
- `backend/alembic.ini` 只能有 ASCII：Alembic 以系統編碼讀取，繁體中文 Windows 為 cp950。
- API：
  - 錯誤一律回傳 `{ error: { code, message } }`，message 為繁體中文。
  - UI 文字、錯誤訊息、註解都用繁體中文。
- 外部服務（Gemini、RAG、ComfyUI）在本計畫都是模擬版，行為與 mock 劇本相同（預設第一輪刻意失誤、Query Rewriting 後通過）。
- 沿用 Plan 3 的前端 Global Constraints：
  - `getApiClient()` 只能在 client 端呼叫。
  - 事件與示範資料是凍結的物件。
  - React Compiler 規則不得用 `eslint-disable` 繞過。
  - `useSearchParams` 要包在 `<Suspense>` 裡。
  - 不手動修改 `src/components/ui/*`。
- 每個 Task 結束都要 commit，訊息最後一行加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。

## 介面與設計決策

與規格相同的部分不再重複；下列是實作時決定的細節，以及與規格不同之處。

- **合約變更提前到 Task 1**：
  - `JobStage` 加上 `queued`、`failed`；新增 `job.failed` 事件。
  - `ParsedBrief.period` 取代寫死的活動期間。
  - `Brand.logo`、`RenderBackground` 的 `includesProduct`。
  - `ApiOptions`、`SystemStatus`、`LocalPhoto`。
  - mock 一併實作，第一階段的畫面照常運作。
- **儀表板統計移植提前到 Plan 4**（規格原排在 Plan 5）：live 模式的儀表板需要。Python 版與 `web/src/lib/stats/dashboard.ts` 的結果完全相同。浮點數一律依序相加，因為 Python 3.12 起 `sum()` 會做補償加總，結果可能與 JavaScript 不同。
- **本機資料夾**（規格寫「複製到 `data/products/`」）：照片不複製，api 直接從唯讀掛載的 `assets/products/` 以 `/files/local/{檔名}` 提供。上傳的商品照存在 `data/uploads/`，因為上傳時還沒有商品 id。
- **開發時不需要 CORS**（規格寫以 `NEXT_PUBLIC_API_URL` 加 CORS）：`next dev` 設定 `API_PROXY_URL` 後，以 rewrites 把 `/api`、`/files`、`/ws`（WebSocket）轉給 api。前端一律使用同源網址，與正式版（nginx）相同。
- **`saveProduct`**：
  - `POST /api/products` 新增。
  - `PUT /api/products/{id}` 修改；id 不存在時以該 id 新增，與 mock 相同。
- **任務事件的順序**：任務結束前的最後一則 `log` 在結束的 `job.status` 之前送出，`job.status` 一定是最後一則；串流看到它就結束。
- **live 模式的生圖引擎只有 `comfyui`**：Ideogram 只在 mock 示意。模型選項來自後端設定（`LLM_MODEL`、`VLM_MODEL`）。
- **migration 由 api 在啟動時執行**：worker 等 api 健康檢查通過後才啟動。
- **worker 是單一模組 `app/worker.py`**（規格的目錄圖畫成 `app/worker/`）：目前只有四種工作；之後工作變多再拆成目錄。
- **重新整理後接續**：新任務頁面把目前任務記在 sessionStorage（每個分頁各自獨立），重新整理後從頭重播事件並繼續接收。
- **使用者自己的品牌**（Task 14）：
  - 模擬版第一輪的失誤，對示範品牌以外的品牌改由品牌的主色與禁用詞推算。原本只認得兩個示範品牌，其他品牌的任務會直接失敗。
  - `Brand.logo` 有圖時，海報畫圖檔，載入失敗時改畫原本的標誌與字標。
  - Logo 只接受 PNG、JPEG、WebP、SVG。
- **live 模式的 E2E 使用獨立的 compose 專案**（`genai-agent-e2e`，只開放 3200 埠）：自動啟動、測完移除，不影響平常使用的資料庫、上傳檔與商品照。
- **API 文件**：FastAPI 自動產生的 `/docs` 經 nginx 一併提供，作品集展示用。

## File Structure

| 檔案 | 職責 |
|---|---|
| `web/src/types/contract.ts`（修改） | `queued`、`failed`、`job.failed`、`period`、`logo`、`includesProduct`、`ApiOptions`、`SystemStatus`、`LocalPhoto` |
| `web/src/lib/api/client.ts`（修改） | `getOptions`、`getSystemStatus`、`listLocalPhotos`、`importLocalPhoto` |
| `web/src/lib/api/mock/options.ts` | mock 的模型與引擎選項 |
| `web/next.config.ts`（修改） | 建置時靜態輸出；開發時 rewrites 轉給後端 |
| `web/scripts/serve-static.mjs` | 提供 `out/`（Playwright 使用） |
| `web/src/test/golden.ts`、`web/scripts/fixtures.ts` | 產生 `contracts/fixtures/` |
| `web/composer/` | composer：`/layout`、`/sim/*`、`/health` |
| `web/src/lib/api/http/` | `HttpApiClient`、連線狀態、WebSocket 重新連線 |
| `web/e2e-live/`、`web/playwright.live.config.ts` | live 模式 E2E |
| `web/Dockerfile`、`web/nginx.conf` | web（nginx）與 composer 的映像檔 |
| `backend/app/contract.py` | Pydantic 合約 |
| `backend/app/core/` | 與前端相同的雜湊與亂數（`rng.py`）、時間（`clock.py`） |
| `backend/app/brands.py` | 品牌設定檔的驗證與載入 |
| `backend/app/settings.py` | 設定（環境變數、`.env`） |
| `backend/app/db/` | SQLAlchemy 模型、連線、migration |
| `backend/app/repo/` | 資料存取：`catalog`（品牌、切塊、商品）、`jobs`、`history` |
| `backend/app/events.py` | 事件保存（`seq`）、Redis 推送、串流 |
| `backend/app/pipeline/` | 任務流程（`runner`）、外部服務介面（`ports`）、模擬版（`sim`） |
| `backend/app/adapters/composer.py` | composer 的用戶端 |
| `backend/app/queues.py`、`backend/app/worker.py` | SAQ 佇列與 worker |
| `backend/app/stats.py` | 儀表板統計 |
| `backend/app/api/` | FastAPI：`main`、`catalog`、`jobs`、`files`、`services` |
| `backend/migrations/` | Alembic |
| `brands/` | `selune.yaml`、`misty-isle.yaml`、`_template.yaml` |
| `contracts/fixtures/` | golden fixtures（由 `npm run fixtures` 產生） |
| `docker-compose.yml`、`docker-compose.e2e.yml`、`backend/Dockerfile` | 服務 |
| `.env.example`、`.gitattributes`、`README.md`、`backend/README.md` | 設定範例、換行規則、說明 |

---

### Task 1: 合約變更：排隊中與失敗、活動期間、可用選項


**Files:**
- Modify: `web/src/types/contract.ts`、`web/src/lib/api/client.ts`、`web/src/lib/api/mock/client.ts`、`web/src/lib/api/mock/brief.ts`、`web/src/lib/api/mock/data/brands.ts`、`web/src/lib/agent/prompt.ts`、`web/src/lib/agent/events.ts`、`web/src/lib/agent/flow.ts`、`web/src/lib/jobs/view.ts`、`web/src/lib/store/queue.ts`、`web/src/lib/store/studio.ts`
- Create: `web/src/lib/api/mock/options.ts`
- Test: `web/src/lib/agent/events.test.ts`、`web/src/lib/agent/flow.test.ts`、`web/src/lib/agent/prompt.test.ts`、`web/src/lib/jobs/view.test.ts`、`web/src/lib/api/mock/brief.test.ts`、`web/src/lib/api/mock/client.test.ts`、`web/src/test/fixtures.ts`（皆為修改）

**Interfaces:**
- Consumes：Plan 3 的合約與 `MockApiClient`
- Produces：
  - `JobStage` 加上 `'queued' | 'failed'`；`JobEvent` 加上 `{ type: 'job.failed'; jobId: string; reason: string }`
  - `ParsedBrief.period: string | null`（`10/15–11/15`；分隔符號統一為 `–`）；文案的頁尾改用 `活動期間 ${period}`，刪除 `CAMPAIGN_PERIOD`
  - `Brand.logo: { url: string } | null`；`RenderBackground` 的 url 型別為 `{ kind: 'url'; url: string; includesProduct: boolean }`
  - `interface ApiOptions { llm: string[]; vlm: string[]; engines: Engine[] }`、`interface ComponentStatus { id; label; status: 'ok' | 'sim' | 'off' | 'error'; detail }`、`interface SystemStatus { components: ComponentStatus[] }`、`interface LocalPhoto { file; name; url; size }`
  - `ApiClient.getOptions()`、`getSystemStatus()`、`listLocalPhotos(): Promise<LocalPhoto[] | null>`、`importLocalPhoto(file, brandId)`
  - `MOCK_OPTIONS`（`web/src/lib/api/mock/options.ts`）
  - `JobView.failureReason`、`JobOutcome` 加上 `'failed'`、`STAGE_LABEL.queued = '排隊中'`、`STAGE_LABEL.failed = '失敗'`

- [ ] **Step 1: 修改 `web/src/types/contract.ts`**

找到（1／7）：

```ts
  guidelineChunks: RagChunk[];
  caseStudies: CaseStudy[];
  copyPresets: Record<Tone, { headline: [string, string]; subhead: string }>;
}

/* ---------- 商品與模板 ---------- */
```

改成：

```ts
  guidelineChunks: RagChunk[];
  caseStudies: CaseStudy[];
  copyPresets: Record<Tone, { headline: [string, string]; subhead: string }>;
  /** Logo 圖檔；null 時排版以向量標誌加品牌名稱繪製 */
  logo: { url: string } | null;
}

/* ---------- 商品與模板 ---------- */
```

找到（2／7）：

```ts
  tone: Tone;
  campaign: string | null;
  offer: string | null;
  /** 英文風格標籤，例如 minimal、premium */
  style: string[];
}
```

改成：

```ts
  tone: Tone;
  campaign: string | null;
  offer: string | null;
  /** 活動期間，例如 10/15–11/15；需求沒有提到時為 null */
  period: string | null;
  /** 英文風格標籤，例如 minimal、premium */
  style: string[];
}
```

找到（3／7）：

```ts

export type RenderBackground =
  | { kind: 'procedural'; seed: number; palette: Palette; style: string }
  | { kind: 'url'; url: string };

export interface Render {
  id: string;
```

改成：

```ts

export type RenderBackground =
  | { kind: 'procedural'; seed: number; palette: Palette; style: string }
  /** includesProduct：生成圖已包含商品（ComfyUI 打光融合後），繪製時跳過商品圖層 */
  | { kind: 'url'; url: string; includesProduct: boolean };

export interface Render {
  id: string;
```

找到（4／7）：

```ts

/* ---------- WebSocket 事件 ---------- */
export type JobStage =
  | 'parsing' | 'retrieving' | 'prompting' | 'rendering' | 'composing' | 'reviewing'
  | 'rewriting' | 'saving' | 'done' | 'needs_review' | 'cancelled';
export type RenderNode = 'cutout' | 'generate' | 'relight' | 'upscale';
export type LogSource = 'ws' | 'api' | 'agent' | 'rag' | 'comfy' | 'compose' | 'vlm' | 'db';
export type LogLevel = 'info' | 'ok' | 'warn' | 'error';
```

改成：

```ts

/* ---------- WebSocket 事件 ---------- */
export type JobStage =
  | 'queued' | 'parsing' | 'retrieving' | 'prompting' | 'rendering' | 'composing' | 'reviewing'
  | 'rewriting' | 'saving' | 'done' | 'needs_review' | 'cancelled' | 'failed';
export type RenderNode = 'cutout' | 'generate' | 'relight' | 'upscale';
export type LogSource = 'ws' | 'api' | 'agent' | 'rag' | 'comfy' | 'compose' | 'vlm' | 'db';
export type LogLevel = 'info' | 'ok' | 'warn' | 'error';
```

找到（5／7）：

```ts
  | { type: 'rewrite.started'; round: number; templateId: TemplateId; reasons: CheckId[]; fixes: Fix[]; requery: boolean }
  | { type: 'job.completed'; jobId: string; bestRenderIds: Partial<Record<TemplateId, string>> }
  | { type: 'job.needs_review'; jobId: string; reason: string }
  | { type: 'log'; source: LogSource; level: LogLevel; message: string };

/**
```

改成：

```ts
  | { type: 'rewrite.started'; round: number; templateId: TemplateId; reasons: CheckId[]; fixes: Fix[]; requery: boolean }
  | { type: 'job.completed'; jobId: string; bestRenderIds: Partial<Record<TemplateId, string>> }
  | { type: 'job.needs_review'; jobId: string; reason: string }
  /** 技術故障（外部服務無回應、worker 重新啟動等），與「需人工審核」不同 */
  | { type: 'job.failed'; jobId: string; reason: string }
  | { type: 'log'; source: LogSource; level: LogLevel; message: string };

/**
```

找到（6／7）：

```ts
  createdAt: string;
  stage: JobStage;
  round: number;
  /** 已結束（done／needs_review／cancelled） */
  finished: boolean;
  /** 任務完成時每個模板的最佳候選；尚未完成或需人工審核時為空物件 */
  bestRenderIds: Partial<Record<TemplateId, string>>;
```

改成：

```ts
  createdAt: string;
  stage: JobStage;
  round: number;
  /** 已結束（done／needs_review／cancelled／failed） */
  finished: boolean;
  /** 任務完成時每個模板的最佳候選；尚未完成或需人工審核時為空物件 */
  bestRenderIds: Partial<Record<TemplateId, string>>;
```

找到（7／7）：

```ts
  recent: JobStat[];
}

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';
export interface ConnectionState {
  status: ConnectionStatus;
```

改成：

```ts
  recent: JobStat[];
}

/* ---------- 本機資料夾、可用選項與系統狀態 ---------- */
/** assets/products/ 的照片（只有 live 模式由後端提供） */
export interface LocalPhoto {
  file: string;
  /** 檔名去掉副檔名，底線與連字號換成空白 */
  name: string;
  url: string;
  size: number;
}

/** 目前可用的 LLM、VLM 與生圖引擎（顯示名稱即 JobInput 的值） */
export interface ApiOptions { llm: string[]; vlm: string[]; engines: Engine[] }

/** ok 正常、sim 使用模擬版、off 未啟用、error 異常 */
export interface ComponentStatus { id: string; label: string; status: 'ok' | 'sim' | 'off' | 'error'; detail: string }
export interface SystemStatus { components: ComponentStatus[] }

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';
export interface ConnectionState {
  status: ConnectionStatus;
```

- [ ] **Step 2: 修改 `web/src/lib/api/client.ts`**

找到（1／3）：

```ts
import type {
  Brand, BrandDocument, ChannelTemplate, ConnectionState, Copy, DashboardStats, DemoOptions, HistoryEntry, IngestEvent,
  JobInput, JobMessage, JobSummary, ParsedBrief, Product, ProductPhoto, RagChunk,
} from '@/types/contract';

export type ProductDraft = Omit<Product, 'id' | 'createdAt'> & { id?: string };
```

改成：

```ts
import type {
  ApiOptions, Brand, BrandDocument, ChannelTemplate, ConnectionState, Copy, DashboardStats, DemoOptions, HistoryEntry,
  IngestEvent, JobInput, JobMessage, JobSummary, LocalPhoto, ParsedBrief, Product, ProductPhoto, RagChunk, SystemStatus,
} from '@/types/contract';

export type ProductDraft = Omit<Product, 'id' | 'createdAt'> & { id?: string };
```

找到（2／3）：

```ts
  /** 只有 mock 模式有 Demo 控制台；live 模式為 null */
  readonly demo: DemoControls | null;
  readonly connection: ConnectionChannel;
  /** 包含使用者上傳文件產生的切塊 */
  listBrands(): Promise<Brand[]>;
  /** 上傳品牌文件：切塊 → 向量化 → 寫入知識庫，過程以 onEvent 回報；回傳新增的切塊 */
```

改成：

```ts
  /** 只有 mock 模式有 Demo 控制台；live 模式為 null */
  readonly demo: DemoControls | null;
  readonly connection: ConnectionChannel;
  /** 目前可用的 LLM、VLM 與生圖引擎 */
  getOptions(): Promise<ApiOptions>;
  /** 各服務的狀態（資料庫、佇列、向量庫、composer、ComfyUI、Gemini） */
  getSystemStatus(): Promise<SystemStatus>;
  /** 包含使用者上傳文件產生的切塊 */
  listBrands(): Promise<Brand[]>;
  /** 上傳品牌文件：切塊 → 向量化 → 寫入知識庫，過程以 onEvent 回報；回傳新增的切塊 */
```

找到（3／3）：

```ts
  uploadProductPhoto(file: Blob): Promise<ProductPhoto>;
  /** 對商品照去背並寫回 Product.cutout（mock：示意，約 1.2 秒） */
  requestCutout(productId: string): Promise<Product>;
  parseBrief(brandId: string, text: string, productId: string | null): Promise<ParsedBrief>;
  createJob(input: JobInput): Promise<{ jobId: string }>;
  /**
```

改成：

```ts
  uploadProductPhoto(file: Blob): Promise<ProductPhoto>;
  /** 對商品照去背並寫回 Product.cutout（mock：示意，約 1.2 秒） */
  requestCutout(productId: string): Promise<Product>;
  /** 列出 assets/products/ 的照片；此模式無法讀取本機資料夾時回傳 null */
  listLocalPhotos(): Promise<LocalPhoto[] | null>;
  /** 把 assets/products/ 的照片匯入成商品（檔名當商品名稱） */
  importLocalPhoto(file: string, brandId: string): Promise<Product>;
  parseBrief(brandId: string, text: string, productId: string | null): Promise<ParsedBrief>;
  createJob(input: JobInput): Promise<{ jobId: string }>;
  /**
```

- [ ] **Step 3: 修改 `web/src/test/fixtures.ts`**（測試用的需求帶有活動期間）

找到：

```ts

const SERUM = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_selune_serum')!;

/** 由 buildPromptSpec 產生的合規 spec（週年慶買一送一、溫柔語氣） */
export function cleanSpec(brand: Brand = SELUNE, product: Product = SERUM, templateId: TemplateId = 'ig-post'): PromptSpec {
  return buildPromptSpec({
    jobId: 'job_t', round: 1, brand, product, brief: parseBrief('週年慶主打買一送一，溫柔療癒', brand, product),
    template: getTemplate(templateId), engine: 'comfyui', seed: 42, ragRefs: [], fixes: [],
  });
}
```

改成：

```ts

const SERUM = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_selune_serum')!;

/** 由 buildPromptSpec 產生的合規 spec（週年慶 2026/10/15–11/15 買一送一、溫柔語氣） */
export function cleanSpec(brand: Brand = SELUNE, product: Product = SERUM, templateId: TemplateId = 'ig-post'): PromptSpec {
  return buildPromptSpec({
    jobId: 'job_t', round: 1, brand, product, brief: parseBrief('週年慶 2026/10/15–11/15 主打買一送一，溫柔療癒', brand, product),
    template: getTemplate(templateId), engine: 'comfyui', seed: 42, ragRefs: [], fixes: [],
  });
}
```

- [ ] **Step 4: 修改 `web/src/lib/api/mock/brief.test.ts`**（先寫失敗測試）

找到：

```ts
      tone: 'minimal',
      campaign: null,
      offer: null,
      style: ['minimal'],
    });
  });

  it('extracts campaign, offer, tone and style for skincare', () => {
```

改成：

```ts
      tone: 'minimal',
      campaign: null,
      offer: null,
      period: null,
      style: ['minimal'],
    });
  });

  it('extracts the campaign period and normalises the separator', () => {
    expect(parseBrief('雙11 11/1–11/11 全館85折', SELUNE, serum).period).toBe('11/1–11/11');
    expect(parseBrief('週年慶 2026/10/15 ~ 11/15 買一送一', SELUNE, serum).period).toBe('2026/10/15–11/15');
    expect(parseBrief('週年慶 10/15 至 11/15', SELUNE, serum).period).toBe('10/15–11/15');
    expect(parseBrief('週年慶買一送一', SELUNE, serum).period).toBeNull();
  });

  it('extracts campaign, offer, tone and style for skincare', () => {
```

- [ ] **Step 5: 修改 `web/src/lib/agent/prompt.test.ts`**

找到（1／2）：

```ts

const input = (over: Partial<PromptBuildInput> = {}): PromptBuildInput => ({
  jobId: 'job_t', round: 1, brand: SELUNE, product: serum,
  brief: parseBrief('週年慶主打買一送一，溫柔療癒', SELUNE, serum),
  template: getTemplate('ig-post'), engine: 'comfyui', seed: 123456789, ragRefs: ['selune#color'], fixes: [],
  ...over,
});
```

改成：

```ts

const input = (over: Partial<PromptBuildInput> = {}): PromptBuildInput => ({
  jobId: 'job_t', round: 1, brand: SELUNE, product: serum,
  brief: parseBrief('週年慶 2026/10/15–11/15 主打買一送一，溫柔療癒', SELUNE, serum),
  template: getTemplate('ig-post'), engine: 'comfyui', seed: 123456789, ragRefs: ['selune#color'], fixes: [],
  ...over,
});
```

找到（2／2）：

```ts
    expect(spec.copy.disclaimer).toBe('*使用者感受，效果因個人膚況而異｜活動期間 2026/10/15–11/15｜數量有限，售完為止');
    expect(spec.negativePrompt).toBe(BASE_NEGATIVE);
    expect(spec.ragRefs).toEqual(['selune#color']);
  });

  it('injects prompt, seed, size and layout boxes into the ComfyUI workflow', () => {
```

改成：

```ts
    expect(spec.copy.disclaimer).toBe('*使用者感受，效果因個人膚況而異｜活動期間 2026/10/15–11/15｜數量有限，售完為止');
    expect(spec.negativePrompt).toBe(BASE_NEGATIVE);
    expect(spec.ragRefs).toEqual(['selune#color']);
  });

  it('leaves the campaign period out when the brief does not mention one', () => {
    const spec = buildPromptSpec(input({ brief: parseBrief('週年慶主打買一送一，溫柔療癒', SELUNE, serum) }));
    expect(spec.copy.disclaimer).toBe('*使用者感受，效果因個人膚況而異｜數量有限，售完為止');
  });

  it('injects prompt, seed, size and layout boxes into the ComfyUI workflow', () => {
```

- [ ] **Step 6: 修改 `web/src/lib/jobs/view.test.ts`**

找到（1／2）：

```ts
import { buildTimeline } from '@/lib/api/mock/scenario';
import { makeJobSnapshot } from '@/test/fixtures';
import {
  applyEvents, defaultSelection, emptyJobView, finalCandidates, jobProgress, reduceJob, specKey, withLiveStage,
} from './view';

const serum = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_selune_serum')!;
```

改成：

```ts
import { buildTimeline } from '@/lib/api/mock/scenario';
import { makeJobSnapshot } from '@/test/fixtures';
import {
  applyEvents, defaultSelection, emptyJobView, finalCandidates, jobProgress, reduceJob, specKey, STAGE_LABEL, withLiveStage,
} from './view';

const serum = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_selune_serum')!;
```

找到（2／2）：

```ts
    const v = reduceJob(emptyJobView('j'), { type: 'job.status', stage: 'cancelled', round: 1 });
    expect(v.outcome).toBe('cancelled');
  });
});

describe('jobProgress', () => {
```

改成：

```ts
    const v = reduceJob(emptyJobView('j'), { type: 'job.status', stage: 'cancelled', round: 1 });
    expect(v.outcome).toBe('cancelled');
  });

  it('marks a failed job and keeps the reason', () => {
    let v = reduceJob(emptyJobView('j'), { type: 'job.status', stage: 'rendering', round: 1 });
    v = reduceJob(v, { type: 'job.failed', jobId: 'j', reason: 'ComfyUI 沒有回應' });
    v = reduceJob(v, { type: 'job.status', stage: 'failed', round: 1 });
    expect(v).toMatchObject({ outcome: 'failed', stage: 'failed', failureReason: 'ComfyUI 沒有回應' });
    expect(STAGE_LABEL.failed).toBe('失敗');
  });

  it('keeps a queued job running with no progress yet', () => {
    const v = reduceJob(emptyJobView('j'), { type: 'job.status', stage: 'queued', round: 0 });
    expect(v.outcome).toBe('running');
    expect(STAGE_LABEL.queued).toBe('排隊中');
    expect(jobProgress(v)).toBe(0);
  });
});

describe('jobProgress', () => {
```

- [ ] **Step 7: 修改 `web/src/lib/agent/events.test.ts`**

找到（1／2）：

```ts
      'rewrite.started': 'agent',
    });
    expect(eventGroup({ type: 'job.needs_review', jobId: 'j', reason: 'x' })).toBe('job');
  });
});
```

改成：

```ts
      'rewrite.started': 'agent',
    });
    expect(eventGroup({ type: 'job.needs_review', jobId: 'j', reason: 'x' })).toBe('job');
    expect(eventGroup({ type: 'job.failed', jobId: 'j', reason: 'x' })).toBe('job');
  });
});
```

找到（2／2）：

```ts
  it('summarises status, review and rewrite events', () => {
    expect(describeEvent({ type: 'job.status', stage: 'parsing', round: 0 })).toBe('需求拆解');
    expect(describeEvent({ type: 'job.status', stage: 'reviewing', round: 2 })).toBe('合規審查・第 2 輪');
    expect(describeEvent(pick((e) => e.type === 'review.check' && e.check.id === 'banned_words' && e.round === 1)))
      .toBe('r1_ig-post_v0・✗ 禁用詞檢查：禁用詞「根治」「醫療級」');
    expect(describeEvent(pick((e) => e.type === 'rewrite.started'))).toBe(
```

改成：

```ts
  it('summarises status, review and rewrite events', () => {
    expect(describeEvent({ type: 'job.status', stage: 'parsing', round: 0 })).toBe('需求拆解');
    expect(describeEvent({ type: 'job.status', stage: 'reviewing', round: 2 })).toBe('合規審查・第 2 輪');
    expect(describeEvent({ type: 'job.status', stage: 'queued', round: 0 })).toBe('排隊中');
    expect(describeEvent({ type: 'job.failed', jobId: 'j', reason: 'ComfyUI 沒有回應' })).toBe('ComfyUI 沒有回應');
    expect(describeEvent(pick((e) => e.type === 'review.check' && e.check.id === 'banned_words' && e.round === 1)))
      .toBe('r1_ig-post_v0・✗ 禁用詞檢查：禁用詞「根治」「醫療級」');
    expect(describeEvent(pick((e) => e.type === 'rewrite.started'))).toBe(
```

- [ ] **Step 8: 修改 `web/src/lib/agent/flow.test.ts`**

找到：

```ts
    expect(s.orchestrator).toBe('error');
  });

  it('is idle without messages', () => {
    const flow = flowState([]);
    expect(Object.values(flow.nodes).every((n) => n.status === 'idle' && n.visits === 0)).toBe(true);
```

改成：

```ts
    expect(s.orchestrator).toBe('error');
  });

  it('marks the node that was running when the job failed', () => {
    const { events } = makeJobSnapshot();
    const rendering = events.findIndex((e) => e.type === 'job.status' && e.stage === 'rendering');
    const head = events.slice(0, rendering + 3);
    const ts = head.at(-1)!.ts;
    const tail: JobMessage[] = [
      { type: 'job.failed', jobId: 'job_fixture', reason: 'ComfyUI 沒有回應', seq: head.length + 1, ts },
      { type: 'job.status', stage: 'failed', round: 1, seq: head.length + 2, ts },
    ];
    const s = statuses([...head, ...tail]);
    expect(s.comfy).toBe('error');
    expect(s.orchestrator).toBe('error');
  });

  it('keeps only the orchestrator active while the job is queued', () => {
    const queued: JobMessage[] = [
      { type: 'job.accepted', jobId: 'j', seq: 1, ts: '2026-10-07T01:00:00.000Z' },
      { type: 'job.status', stage: 'queued', round: 0, seq: 2, ts: '2026-10-07T01:00:00.000Z' },
    ];
    expect(statuses(queued)).toEqual({
      orchestrator: 'active', brief: 'idle', rag: 'idle', prompt: 'idle', comfy: 'idle', compose: 'idle', review: 'idle', save: 'idle',
    });
  });

  it('is idle without messages', () => {
    const flow = flowState([]);
    expect(Object.values(flow.nodes).every((n) => n.status === 'idle' && n.visits === 0)).toBe(true);
```

- [ ] **Step 9: 修改 `web/src/lib/api/mock/client.test.ts`**

找到（1／2）：

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobEvent, JobInput, JobMessage } from '@/types/contract';
import { getApiClient } from '../index';
import { MAX_STORED_JOBS, MockApiClient, makeJobId } from './client';
import { MemoryStore } from './store';
```

改成：

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobEvent, JobInput, JobMessage } from '@/types/contract';
import type { ApiClient } from '../client';
import { getApiClient } from '../index';
import { MAX_STORED_JOBS, MockApiClient, makeJobId } from './client';
import { MemoryStore } from './store';
```

找到（2／2）：

```ts
  });
});

describe('getApiClient', () => {
  it('returns a singleton mock client with demo controls by default', () => {
    const api = getApiClient();
```

改成：

```ts
  });
});

describe('options, system status and local photos', () => {
  it('offers every model and engine of the demo', async () => {
    expect(await new MockApiClient().getOptions()).toEqual({
      llm: ['Gemini 3.7 Flash', 'Llama 3.2 Vision（Unsloth 微調）'],
      vlm: ['Gemini 3.7 Vision', 'Llama 3.2 Vision（Unsloth 微調）'],
      engines: ['comfyui', 'ideogram'],
    });
  });

  it('reports a single simulated component', async () => {
    expect(await new MockApiClient().getSystemStatus()).toEqual({
      components: [{ id: 'mock', label: '瀏覽器內模擬', status: 'sim', detail: 'MockApiClient：事件格式與 FastAPI WebSocket 相同' }],
    });
  });

  it('cannot read the local product folder', async () => {
    const api: ApiClient = new MockApiClient();
    expect(await api.listLocalPhotos()).toBeNull();
    await expect(api.importLocalPhoto('mask.png', 'selune')).rejects.toThrow('只有 live 模式可以匯入本機資料夾');
  });
});

describe('getApiClient', () => {
  it('returns a singleton mock client with demo controls by default', () => {
    const api = getApiClient();
```

- [ ] **Step 10: 執行測試確認失敗**

Run: `npx vitest run src/lib/api/mock src/lib/agent src/lib/jobs`
Expected: FAIL，6 個測試檔共 11 個測試失敗：
- `brief.test.ts`：2 個（冷萃咖啡的示範句、活動期間）
- `prompt.test.ts`：1 個（需求沒有活動期間時頁尾不加）
- `view.test.ts`：2 個（失敗的任務、排隊中的任務）
- `events.test.ts`：2 個
- `flow.test.ts`：1 個（失敗時標示執行中的節點）
- `client.test.ts`：3 個（選項、系統狀態、本機資料夾）

- [ ] **Step 11: 建立 `web/src/lib/api/mock/options.ts`**

```ts
import type { ApiOptions } from '@/types/contract';

/** mock 模式提供的模型與引擎（第一階段的示意名稱；live 模式改由後端回傳實際可用的選項） */
export const MOCK_OPTIONS: ApiOptions = {
  llm: ['Gemini 3.7 Flash', 'Llama 3.2 Vision（Unsloth 微調）'],
  vlm: ['Gemini 3.7 Vision', 'Llama 3.2 Vision（Unsloth 微調）'],
  engines: ['comfyui', 'ideogram'],
};
```

- [ ] **Step 12: 修改 `web/src/lib/api/mock/data/brands.ts`**（示範品牌沒有 Logo 圖檔）

找到（1／2）：

```ts
    playful: { headline: ['熬夜也不怕', '肌膚喝飽水！'], subhead: '水潤透亮一起帶走，買一送一只到月底*' },
    minimal: { headline: ['少即是多', '純粹修護'], subhead: '5重玻尿酸・無香精・敏感肌適用*' },
  },
});

export const MISTY_ISLE: Brand = deepFreeze({
```

改成：

```ts
    playful: { headline: ['熬夜也不怕', '肌膚喝飽水！'], subhead: '水潤透亮一起帶走，買一送一只到月底*' },
    minimal: { headline: ['少即是多', '純粹修護'], subhead: '5重玻尿酸・無香精・敏感肌適用*' },
  },
  logo: null,
});

export const MISTY_ISLE: Brand = deepFreeze({
```

找到（2／2）：

```ts
    science: { headline: ['18H 低溫萃取', '每瓶 120mg 咖啡因'], subhead: '單一產區・無添加糖・冷鏈配送' },
    playful: { headline: ['冰冰的', '剛剛好！'], subhead: '買二送一，辦公室續命必備' },
  },
});
```

改成：

```ts
    science: { headline: ['18H 低溫萃取', '每瓶 120mg 咖啡因'], subhead: '單一產區・無添加糖・冷鏈配送' },
    playful: { headline: ['冰冰的', '剛剛好！'], subhead: '買二送一，辦公室續命必備' },
  },
  logo: null,
});
```

- [ ] **Step 13: 修改 `web/src/lib/api/mock/brief.ts`**

找到（1／2）：

```ts
const CAMPAIGN_RE = /週年慶|雙\s*11|中秋|母親節|聖誕|新品上市|夏季|開學/;
const OFFER_RE = /買一送一|買二送一|第二件\s*\d+(?:\.\d+)?\s*折|\d+(?:\.\d+)?\s*折/;
const AUDIENCE_RE = /(?:給|針對|適合)([^，。,.！!]+)/;

/** 以關鍵字規則模擬 LLM 的需求拆解（第二階段改由後端 LLM 產生同格式結果） */
export function parseBrief(text: string, brand: Brand, product: Product | null): ParsedBrief {
```

改成：

```ts
const CAMPAIGN_RE = /週年慶|雙\s*11|中秋|母親節|聖誕|新品上市|夏季|開學/;
const OFFER_RE = /買一送一|買二送一|第二件\s*\d+(?:\.\d+)?\s*折|\d+(?:\.\d+)?\s*折/;
const AUDIENCE_RE = /(?:給|針對|適合)([^，。,.！!]+)/;
/** 10/15–11/15、2026/10/15 ~ 11/15、10/15 至 11/15 */
const PERIOD_RE = /((?:\d{4}\/)?\d{1,2}\/\d{1,2})\s*(?:–|-|~|～|至|到)\s*((?:\d{4}\/)?\d{1,2}\/\d{1,2})/;

/** 以關鍵字規則模擬 LLM 的需求拆解（第二階段改由後端 LLM 產生同格式結果） */
export function parseBrief(text: string, brand: Brand, product: Product | null): ParsedBrief {
```

找到（2／2）：

```ts
  const campaign = text.match(CAMPAIGN_RE)?.[0].replace(/\s+/g, '') ?? null;
  const offer = text.match(OFFER_RE)?.[0].replace(/\s+/g, '') ?? null;
  const audience = text.match(AUDIENCE_RE)?.[1].trim() ?? '一般消費者';
  const style = STYLE_WORDS.filter(([zh]) => text.includes(zh)).map(([, en]) => en);

  const features = product?.features ?? [];
  const mentioned = features.filter((f) => text.includes(f));
  const sellingPoints = [...mentioned, ...features.filter((f) => !mentioned.includes(f))].slice(0, 3);

  return { productName: product?.name ?? null, sellingPoints, audience, tone, campaign, offer, style };
}
```

改成：

```ts
  const campaign = text.match(CAMPAIGN_RE)?.[0].replace(/\s+/g, '') ?? null;
  const offer = text.match(OFFER_RE)?.[0].replace(/\s+/g, '') ?? null;
  const audience = text.match(AUDIENCE_RE)?.[1].trim() ?? '一般消費者';
  const range = text.match(PERIOD_RE);
  const period = range ? `${range[1]}–${range[2]}` : null;
  const style = STYLE_WORDS.filter(([zh]) => text.includes(zh)).map(([, en]) => en);

  const features = product?.features ?? [];
  const mentioned = features.filter((f) => text.includes(f));
  const sellingPoints = [...mentioned, ...features.filter((f) => !mentioned.includes(f))].slice(0, 3);

  return { productName: product?.name ?? null, sellingPoints, audience, tone, campaign, offer, period, style };
}
```

- [ ] **Step 14: 修改 `web/src/lib/agent/prompt.ts`**

找到（1／2）：

```ts
import { computeLayout } from '@/lib/compose/layout';
import { claimTexts, hasClaim } from '@/lib/review/rules';

export const CAMPAIGN_PERIOD = '活動期間 2026/10/15–11/15';
export const BASE_NEGATIVE = 'lowres, blurry, watermark, deformed product, extra objects, garbled text';

const OFFER_SUB: [RegExp, string][] = [
```

改成：

```ts
import { computeLayout } from '@/lib/compose/layout';
import { claimTexts, hasClaim } from '@/lib/review/rules';

export const BASE_NEGATIVE = 'lowres, blurry, watermark, deformed product, extra objects, garbled text';

const OFFER_SUB: [RegExp, string][] = [
```

找到（2／2）：

```ts
  const claim = hasClaim(claimTexts({ headline, subhead, features, badge }), brand.claimWords);
  const notes = [
    claim && brand.disclaimerPhrase ? `*使用者感受，${brand.disclaimerPhrase}` : null,
    brief.campaign ? CAMPAIGN_PERIOD : null,
    brief.offer ? '數量有限，售完為止' : null,
  ].filter((s): s is string => s !== null);
```

改成：

```ts
  const claim = hasClaim(claimTexts({ headline, subhead, features, badge }), brand.claimWords);
  const notes = [
    claim && brand.disclaimerPhrase ? `*使用者感受，${brand.disclaimerPhrase}` : null,
    brief.period ? `活動期間 ${brief.period}` : null,
    brief.offer ? '數量有限，售完為止' : null,
  ].filter((s): s is string => s !== null);
```

- [ ] **Step 15: 修改 `web/src/lib/jobs/view.ts`**

找到（1／5）：

```ts
  TemplateId,
} from '@/types/contract';

export type JobOutcome = 'running' | 'done' | 'needs_review' | 'cancelled';
export interface RewriteInfo { round: number; templateId: TemplateId; reasons: CheckId[]; fixes: Fix[]; requery: boolean }
export interface LogLine { source: LogSource; level: LogLevel; message: string }
export interface RenderProgress { round: number; node: RenderNode; step: number; maxStep: number }
```

改成：

```ts
  TemplateId,
} from '@/types/contract';

export type JobOutcome = 'running' | 'done' | 'needs_review' | 'cancelled' | 'failed';
export interface RewriteInfo { round: number; templateId: TemplateId; reasons: CheckId[]; fixes: Fix[]; requery: boolean }
export interface LogLine { source: LogSource; level: LogLevel; message: string }
export interface RenderProgress { round: number; node: RenderNode; step: number; maxStep: number }
```

找到（2／5）：

```ts
  rewrites: RewriteInfo[];
  bestRenderIds: Partial<Record<TemplateId, string>>;
  needsReviewReason: string | null;
  logs: LogLine[];
}

export const specKey = (round: number, templateId: TemplateId) => `${round}:${templateId}`;

export const STAGE_LABEL: Record<JobStage, string> = {
  parsing: '需求拆解',
  retrieving: 'RAG 檢索',
  prompting: 'Prompt 構建',
```

改成：

```ts
  rewrites: RewriteInfo[];
  bestRenderIds: Partial<Record<TemplateId, string>>;
  needsReviewReason: string | null;
  /** 任務失敗（技術故障）的原因 */
  failureReason: string | null;
  logs: LogLine[];
}

export const specKey = (round: number, templateId: TemplateId) => `${round}:${templateId}`;

export const STAGE_LABEL: Record<JobStage, string> = {
  queued: '排隊中',
  parsing: '需求拆解',
  retrieving: 'RAG 檢索',
  prompting: 'Prompt 構建',
```

找到（3／5）：

```ts
  done: '完成',
  needs_review: '需人工審核',
  cancelled: '已取消',
};

export function emptyJobView(jobId: string | null = null): JobView {
  return {
    jobId, stage: null, round: 0, outcome: 'running', parsedBrief: null, ragHits: [], requeryHits: [], specs: {},
    renders: {}, renderIds: [], progress: null, rewrites: [], bestRenderIds: {}, needsReviewReason: null, logs: [],
  };
}

const OUTCOME: Partial<Record<JobStage, JobOutcome>> = { done: 'done', needs_review: 'needs_review', cancelled: 'cancelled' };

/** 純函式：回傳新的 view，不修改輸入（事件是凍結的物件） */
export function reduceJob(v: JobView, e: JobEvent): JobView {
```

改成：

```ts
  done: '完成',
  needs_review: '需人工審核',
  cancelled: '已取消',
  failed: '失敗',
};

export function emptyJobView(jobId: string | null = null): JobView {
  return {
    jobId, stage: null, round: 0, outcome: 'running', parsedBrief: null, ragHits: [], requeryHits: [], specs: {},
    renders: {}, renderIds: [], progress: null, rewrites: [], bestRenderIds: {}, needsReviewReason: null, failureReason: null, logs: [],
  };
}

const OUTCOME: Partial<Record<JobStage, JobOutcome>> = {
  done: 'done', needs_review: 'needs_review', cancelled: 'cancelled', failed: 'failed',
};

/** 純函式：回傳新的 view，不修改輸入（事件是凍結的物件） */
export function reduceJob(v: JobView, e: JobEvent): JobView {
```

找到（4／5）：

```ts
      return { ...v, bestRenderIds: e.bestRenderIds };
    case 'job.needs_review':
      return { ...v, needsReviewReason: e.reason };
    case 'log':
      return { ...v, logs: [...v.logs, { source: e.source, level: e.level, message: e.message }] };
  }
```

改成：

```ts
      return { ...v, bestRenderIds: e.bestRenderIds };
    case 'job.needs_review':
      return { ...v, needsReviewReason: e.reason };
    case 'job.failed':
      return { ...v, failureReason: e.reason };
    case 'log':
      return { ...v, logs: [...v.logs, { source: e.source, level: e.level, message: e.message }] };
  }
```

找到（5／5）：

```ts
export function jobProgress(v: JobView): number {
  if (v.outcome === 'done' || v.outcome === 'needs_review') return 1;
  switch (v.stage) {
    case null: return 0;
    case 'parsing': return 0.04;
    case 'retrieving': return 0.1;
    case 'prompting': return 0.16;
```

改成：

```ts
export function jobProgress(v: JobView): number {
  if (v.outcome === 'done' || v.outcome === 'needs_review') return 1;
  switch (v.stage) {
    case null:
    case 'queued': return 0;
    case 'parsing': return 0.04;
    case 'retrieving': return 0.1;
    case 'prompting': return 0.16;
```

- [ ] **Step 16: 修改 `web/src/lib/agent/events.ts`**

找到（1／2）：

```ts
    case 'job.status':
    case 'job.completed':
    case 'job.needs_review':
      return 'job';
    case 'brief.parsed':
    case 'prompt.generated':
```

改成：

```ts
    case 'job.status':
    case 'job.completed':
    case 'job.needs_review':
    case 'job.failed':
      return 'job';
    case 'brief.parsed':
    case 'prompt.generated':
```

找到（2／2）：

```ts
    case 'job.completed':
      return `最佳候選 ${Object.keys(e.bestRenderIds).length} 張`;
    case 'job.needs_review':
      return e.reason;
    case 'log':
      return `[${e.source.toUpperCase()}] ${e.message}`;
```

改成：

```ts
    case 'job.completed':
      return `最佳候選 ${Object.keys(e.bestRenderIds).length} 張`;
    case 'job.needs_review':
    case 'job.failed':
      return e.reason;
    case 'log':
      return `[${e.source.toUpperCase()}] ${e.message}`;
```

- [ ] **Step 17: 修改 `web/src/lib/agent/flow.ts`**

找到（1／2）：

```ts
import type { JobMessage, JobStage } from '@/types/contract';

export type FlowNodeId = 'orchestrator' | 'brief' | 'rag' | 'prompt' | 'comfy' | 'compose' | 'review' | 'save';
/** warn：曾經未通過、重試後完成；error：需人工審核或在此節點取消 */
export type FlowStatus = 'idle' | 'active' | 'done' | 'warn' | 'error';

export interface FlowNodeDef { id: FlowNodeId; step: number; label: string; tech: string }
```

改成：

```ts
import type { JobMessage, JobStage } from '@/types/contract';

export type FlowNodeId = 'orchestrator' | 'brief' | 'rag' | 'prompt' | 'comfy' | 'compose' | 'review' | 'save';
/** warn：曾經未通過、重試後完成；error：需人工審核，或在此節點取消／失敗 */
export type FlowStatus = 'idle' | 'active' | 'done' | 'warn' | 'error';

export interface FlowNodeDef { id: FlowNodeId; step: number; label: string; tech: string }
```

找到（2／2）：

```ts
  const end = messages.at(-1);
  if (end) close(Date.parse(end.ts));

  const running = stage !== null && stage !== 'done' && stage !== 'needs_review' && stage !== 'cancelled';
  for (const n of FLOW_NODES) if (nodes[n.id].visits > 0) nodes[n.id].status = 'done';
  if (loop.count > 0) nodes.review.status = 'warn';
  if (stage === 'needs_review') nodes.review.status = 'error';
  if (running && last && last !== 'loop') nodes[last].status = 'active';
  if (stage === 'cancelled' && last && last !== 'loop') nodes[last].status = 'error';
  loop.active = stage === 'rewriting';
  if (nodes.orchestrator.visits) nodes.orchestrator.status = running ? 'active' : stage === 'cancelled' ? 'error' : 'done';

  const elapsedMs = first && end ? Date.parse(end.ts) - Date.parse(first.ts) : 0;
  nodes.orchestrator.ms = elapsedMs;
```

改成：

```ts
  const end = messages.at(-1);
  if (end) close(Date.parse(end.ts));

  const stopped = stage === 'cancelled' || stage === 'failed';
  const running = stage !== null && stage !== 'done' && stage !== 'needs_review' && !stopped;
  for (const n of FLOW_NODES) if (nodes[n.id].visits > 0) nodes[n.id].status = 'done';
  if (loop.count > 0) nodes.review.status = 'warn';
  if (stage === 'needs_review') nodes.review.status = 'error';
  if (running && last && last !== 'loop') nodes[last].status = 'active';
  if (stopped && last && last !== 'loop') nodes[last].status = 'error';
  loop.active = stage === 'rewriting';
  if (nodes.orchestrator.visits) nodes.orchestrator.status = running ? 'active' : stopped ? 'error' : 'done';

  const elapsedMs = first && end ? Date.parse(end.ts) - Date.parse(first.ts) : 0;
  nodes.orchestrator.ms = elapsedMs;
```

- [ ] **Step 18: 修改 `web/src/lib/api/mock/client.ts`**

找到（1／3）：

```ts
import type {
  BrandDocument, ConnectionState, Copy, DashboardStats, DemoOptions, HistoryEntry, IngestEvent, JobEvent, JobInput,
  JobMessage, JobStage, JobSummary, Product, ProductPhoto, RagChunk, Render, TemplateId,
} from '@/types/contract';
import type { ApiClient, ConnectionChannel, DemoControls, JobSnapshot, ProductDraft } from '../client';
import { CHANNEL_TEMPLATES, getTemplate } from '@/lib/compose/templates';
```

改成：

```ts
import type {
  ApiOptions, BrandDocument, ConnectionState, Copy, DashboardStats, DemoOptions, HistoryEntry, IngestEvent, JobEvent,
  JobInput, JobMessage, JobStage, JobSummary, LocalPhoto, Product, ProductPhoto, RagChunk, Render, SystemStatus, TemplateId,
} from '@/types/contract';
import type { ApiClient, ConnectionChannel, DemoControls, JobSnapshot, ProductDraft } from '../client';
import { CHANNEL_TEMPLATES, getTemplate } from '@/lib/compose/templates';
```

找到（2／3）：

```ts
import { dashboardStats } from '@/lib/stats/dashboard';
import { BRANDS, getBrandById, SAMPLE_PRODUCTS } from './data';
import { parseBrief } from './brief';
import { playTimeline, type PlayerHandle } from './player';
import { sampleJobs } from './samples';
import { buildTimeline } from './scenario';
```

改成：

```ts
import { dashboardStats } from '@/lib/stats/dashboard';
import { BRANDS, getBrandById, SAMPLE_PRODUCTS } from './data';
import { parseBrief } from './brief';
import { MOCK_OPTIONS } from './options';
import { playTimeline, type PlayerHandle } from './player';
import { sampleJobs } from './samples';
import { buildTimeline } from './scenario';
```

找到（3／3）：

```ts
  /** 等待 ms（1× 速度），依 Demo 播放速度縮短 */
  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms / this.options.speed));
  }

  /** 示範品牌 + 使用者上傳文件產生的切塊 */
```

改成：

```ts
  /** 等待 ms（1× 速度），依 Demo 播放速度縮短 */
  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms / this.options.speed));
  }

  async getOptions(): Promise<ApiOptions> {
    return structuredClone(MOCK_OPTIONS);
  }

  async getSystemStatus(): Promise<SystemStatus> {
    return {
      components: [{ id: 'mock', label: '瀏覽器內模擬', status: 'sim', detail: 'MockApiClient：事件格式與 FastAPI WebSocket 相同' }],
    };
  }

  /** 瀏覽器讀不到本機資料夾：只有 live 模式由後端提供 */
  async listLocalPhotos(): Promise<LocalPhoto[] | null> {
    return null;
  }

  async importLocalPhoto(): Promise<Product> {
    throw new Error('只有 live 模式可以匯入本機資料夾');
  }

  /** 示範品牌 + 使用者上傳文件產生的切塊 */
```

- [ ] **Step 19: 修改 `web/src/lib/store/queue.ts`**（失敗的任務在批次佇列顯示為錯誤）

找到：

```ts
            const item = get().items.find((i) => i.id === next.id);
            if (!item?.view) return;
            const view = reduceJob(item.view, e);
            const status: QueueStatus = view.outcome === 'running' ? 'running' : view.outcome;
            update(next.id, { view, status });
            if (status !== 'running' && !finished) {
              finished = true;
              unsubscribe?.();
```

改成：

```ts
            const item = get().items.find((i) => i.id === next.id);
            if (!item?.view) return;
            const view = reduceJob(item.view, e);
            const status: QueueStatus = view.outcome === 'running' ? 'running' : view.outcome === 'failed' ? 'error' : view.outcome;
            update(next.id, { view, status, error: view.failureReason });
            if (status !== 'running' && !finished) {
              finished = true;
              unsubscribe?.();
```

- [ ] **Step 20: 修改 `web/src/lib/store/studio.ts`**（模型選項改由 `MOCK_OPTIONS` 提供）

找到：

```ts
import { create } from 'zustand';
import type { Copy, Engine, JobInput, ParsedBrief, TemplateId, Tone } from '@/types/contract';
import { getApiClient } from '@/lib/api';
import { defaultSelection, emptyJobView, reduceJob, type JobView } from '@/lib/jobs/view';

export const LLM_OPTIONS = ['Gemini 3.7 Flash', 'Llama 3.2 Vision（Unsloth 微調）'];
export const VLM_OPTIONS = ['Gemini 3.7 Vision', 'Llama 3.2 Vision（Unsloth 微調）'];
export const ENGINE_LABEL: Record<Engine, string> = { comfyui: 'ComfyUI（SDXL + ControlNet + IP-Adapter）', ideogram: 'Ideogram 4.0' };
export const TONE_LABEL: Record<Tone, string> = { gentle: '溫柔療癒', science: '專業科研', playful: '活潑年輕', minimal: '簡約' };
```

改成：

```ts
import { create } from 'zustand';
import type { Copy, Engine, JobInput, ParsedBrief, TemplateId, Tone } from '@/types/contract';
import { getApiClient } from '@/lib/api';
import { MOCK_OPTIONS } from '@/lib/api/mock/options';
import { defaultSelection, emptyJobView, reduceJob, type JobView } from '@/lib/jobs/view';

export const LLM_OPTIONS = MOCK_OPTIONS.llm;
export const VLM_OPTIONS = MOCK_OPTIONS.vlm;
export const ENGINE_LABEL: Record<Engine, string> = { comfyui: 'ComfyUI（SDXL + ControlNet + IP-Adapter）', ideogram: 'Ideogram 4.0' };
export const TONE_LABEL: Record<Tone, string> = { gentle: '溫柔療癒', science: '專業科研', playful: '活潑年輕', minimal: '簡約' };
```

- [ ] **Step 21: 執行全部測試、型別檢查與 lint**

Run: `npm run test`
Expected: PASS，36 個測試檔、288 個測試（原本 279 個）。

Run: `npm run typecheck && npm run lint`
Expected: 沒有錯誤。

- [ ] **Step 22: Commit**

```bash
git add \
  web/src/lib/agent/events.test.ts \
  web/src/lib/agent/events.ts \
  web/src/lib/agent/flow.test.ts \
  web/src/lib/agent/flow.ts \
  web/src/lib/agent/prompt.test.ts \
  web/src/lib/agent/prompt.ts \
  web/src/lib/api/client.ts \
  web/src/lib/api/mock/brief.test.ts \
  web/src/lib/api/mock/brief.ts \
  web/src/lib/api/mock/client.test.ts \
  web/src/lib/api/mock/client.ts \
  web/src/lib/api/mock/data/brands.ts \
  web/src/lib/api/mock/options.ts \
  web/src/lib/jobs/view.test.ts \
  web/src/lib/jobs/view.ts \
  web/src/lib/store/queue.ts \
  web/src/lib/store/studio.ts \
  web/src/test/fixtures.ts \
  web/src/types/contract.ts
git commit -m "feat: add queued and failed job states, campaign period and live options to the contract" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: 靜態輸出，選項、系統狀態與本機資料夾改經由 `ApiClient`


**Files:**
- Create: `web/src/lib/store/app.test.ts`、`web/scripts/serve-static.mjs`
- Modify: `web/src/lib/store/app.ts`、`web/src/lib/store/studio.ts`、`web/src/lib/store/queue.ts`、`web/src/components/layout/app-shell.tsx`、`web/src/components/layout/connection-badge.tsx`、`web/src/components/product/local-folder.tsx`、`web/src/components/studio/brief-panel.tsx`、`web/src/components/studio/run-status.tsx`、`web/next.config.ts`、`web/playwright.config.ts`
- Delete: `web/src/app/api/local-products/`、`web/src/lib/server/`
- Test: `web/src/lib/store/app.test.ts`、`web/src/lib/store/queue.test.ts`、`web/src/lib/store/studio.test.ts`

**Interfaces:**
- Consumes：Task 1 的 `ApiClient.getOptions`、`getSystemStatus`、`listLocalPhotos`、`importLocalPhoto`、`MOCK_OPTIONS`
- Produces：
  - `useAppStore`：`options: ApiOptions | null`、`loadOptions()`；`AppShell` 在品牌與選項都載入後才 render 頁面
  - 新任務表單的預設值 `defaultForm()`：模型與引擎取 `options` 的第一個；live 模式每個模板預設 2 張
  - 批次佇列建立任務時使用 `options` 的第一個模型與引擎
  - 右上角的連線狀態可展開系統狀態（`getSystemStatus()`）
  - `next build` 輸出靜態檔到 `out/`；`next dev` 設定 `API_PROXY_URL` 時以 rewrites 轉給後端
  - `node scripts/serve-static.mjs <port>`：`/studio` → `studio.html`，找不到時回 `404.html`

- [ ] **Step 1: 建立 `web/src/lib/store/app.test.ts`**（先寫失敗測試）

```ts
import { afterEach, describe, expect, it } from 'vitest';
import { MOCK_OPTIONS } from '@/lib/api/mock/options';
import { useAppStore } from './app';

afterEach(() => useAppStore.setState({ options: null }));

describe('app store', () => {
  it('loads the models and engines the current API offers', async () => {
    expect(useAppStore.getState().options).toBeNull();
    await useAppStore.getState().loadOptions();
    expect(useAppStore.getState().options).toEqual(MOCK_OPTIONS);
  });
});
```

- [ ] **Step 2: 修改 `web/src/lib/store/queue.test.ts`**

找到（1／2）：

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getApiClient } from '@/lib/api';
import { useQueueStore } from './queue';

const q = () => useQueueStore.getState();
```

改成：

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getApiClient } from '@/lib/api';
import { useAppStore } from './app';
import { useQueueStore } from './queue';

const q = () => useQueueStore.getState();
```

找到（2／2）：

```ts
  getApiClient().demo?.set({ speed: 4, firstRoundFail: true, forceAllFail: false });
  useQueueStore.setState({ items: [], paused: false });
});
afterEach(() => vi.useRealTimers());

describe('queue store', () => {
  it('runs one item at a time, in order', async () => {
    q().enqueue(BATCH);
    await vi.advanceTimersByTimeAsync(100);
```

改成：

```ts
  getApiClient().demo?.set({ speed: 4, firstRoundFail: true, forceAllFail: false });
  useQueueStore.setState({ items: [], paused: false });
});
afterEach(() => {
  vi.useRealTimers();
  useAppStore.setState({ options: null });
});

describe('queue store', () => {
  it('creates jobs with the first available models and engine', async () => {
    useAppStore.setState({ options: { llm: ['Gemini 3 Flash'], vlm: ['Gemini 3 Flash'], engines: ['comfyui' as const] } });
    q().enqueue({ ...BATCH, products: [BATCH.products[0]] });
    await vi.advanceTimersByTimeAsync(100);
    const { summary } = await getApiClient().getJob(q().items[0].jobId!);
    expect(summary.input).toMatchObject({ llm: 'Gemini 3 Flash', vlm: 'Gemini 3 Flash', engine: 'comfyui' });
  });

  it('runs one item at a time, in order', async () => {
    q().enqueue(BATCH);
    await vi.advanceTimersByTimeAsync(100);
```

- [ ] **Step 3: 修改 `web/src/lib/store/studio.test.ts`**

找到（1／2）：

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getApiClient } from '@/lib/api';
import { DEMO_BRIEFS, useStudioStore } from './studio';

const store = () => useStudioStore.getState();
```

改成：

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getApiClient } from '@/lib/api';
import { useAppStore } from './app';
import { DEMO_BRIEFS, useStudioStore } from './studio';

const store = () => useStudioStore.getState();
```

找到（2／2）：

```ts
  store().resetForBrand('selune');
  store().setForm({ productId: 'prod_selune_serum', templateIds: ['ig-post'] });
});
afterEach(() => vi.useRealTimers());

describe('studio store', () => {
  it('starts from the brand demo brief', () => {
    expect(store().brief).toBe(DEMO_BRIEFS.selune);
    expect(store().view).toBeNull();
  });

  it('parses the brief and lets the user edit the parsed fields', async () => {
```

改成：

```ts
  store().resetForBrand('selune');
  store().setForm({ productId: 'prod_selune_serum', templateIds: ['ig-post'] });
});
afterEach(() => {
  vi.useRealTimers();
  useAppStore.setState({ options: null });
});

describe('studio store', () => {
  it('starts from the brand demo brief', () => {
    expect(store().brief).toBe(DEMO_BRIEFS.selune);
    expect(store().view).toBeNull();
  });

  it('takes the default models and engine from the available options', () => {
    expect(store()).toMatchObject({ llm: 'Gemini 3.7 Flash', vlm: 'Gemini 3.7 Vision', engine: 'comfyui', variants: 4 });
    useAppStore.setState({ options: { llm: ['Gemini 3 Flash'], vlm: ['Gemini 3 Flash'], engines: ['comfyui' as const] } });
    store().resetForBrand('misty-isle');
    expect(store()).toMatchObject({ llm: 'Gemini 3 Flash', vlm: 'Gemini 3 Flash', engine: 'comfyui' });
  });

  it('parses the brief and lets the user edit the parsed fields', async () => {
```

- [ ] **Step 4: 執行測試確認失敗**

Run: `npx vitest run src/lib/store`
Expected: FAIL，3 個測試失敗：
- `app.test.ts`「loads the models and engines the current API offers」
- `queue.test.ts`「creates jobs with the first available models and engine」
- `studio.test.ts`「takes the default models and engine from the available options」

- [ ] **Step 5: 修改 `web/src/lib/store/app.ts`**

找到（1／2）：

```ts
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Brand } from '@/types/contract';
import { getApiClient } from '@/lib/api';

interface AppState {
  brandId: string;
  brands: Brand[];
  setBrandId: (id: string) => void;
  /** 重新讀取品牌（上傳品牌文件後也要呼叫） */
  loadBrands: () => Promise<void>;
}

/** 全域狀態：目前品牌（記在 localStorage）與品牌清單 */
```

改成：

```ts
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ApiOptions, Brand } from '@/types/contract';
import { getApiClient } from '@/lib/api';

interface AppState {
  brandId: string;
  brands: Brand[];
  /** 目前可用的 LLM、VLM 與生圖引擎；載入前為 null */
  options: ApiOptions | null;
  setBrandId: (id: string) => void;
  /** 重新讀取品牌（上傳品牌文件後也要呼叫） */
  loadBrands: () => Promise<void>;
  loadOptions: () => Promise<void>;
}

/** 全域狀態：目前品牌（記在 localStorage）與品牌清單 */
```

找到（2／2）：

```ts
    (set) => ({
      brandId: 'selune',
      brands: [],
      setBrandId: (brandId) => set({ brandId }),
      loadBrands: async () => {
        set({ brands: await getApiClient().listBrands() });
      },
    }),
    // skipHydration：伺服器 render 用預設值，等 AppShell 掛載後才讀 localStorage，避免 hydration 不一致
```

改成：

```ts
    (set) => ({
      brandId: 'selune',
      brands: [],
      options: null,
      setBrandId: (brandId) => set({ brandId }),
      loadBrands: async () => {
        set({ brands: await getApiClient().listBrands() });
      },
      loadOptions: async () => {
        set({ options: await getApiClient().getOptions() });
      },
    }),
    // skipHydration：伺服器 render 用預設值，等 AppShell 掛載後才讀 localStorage，避免 hydration 不一致
```

- [ ] **Step 6: 修改 `web/src/lib/store/studio.ts`**

找到（1／4）：

```ts
import { create } from 'zustand';
import type { Copy, Engine, JobInput, ParsedBrief, TemplateId, Tone } from '@/types/contract';
import { getApiClient } from '@/lib/api';
import { MOCK_OPTIONS } from '@/lib/api/mock/options';
import { defaultSelection, emptyJobView, reduceJob, type JobView } from '@/lib/jobs/view';

export const LLM_OPTIONS = MOCK_OPTIONS.llm;
export const VLM_OPTIONS = MOCK_OPTIONS.vlm;
export const ENGINE_LABEL: Record<Engine, string> = { comfyui: 'ComfyUI（SDXL + ControlNet + IP-Adapter）', ideogram: 'Ideogram 4.0' };
export const TONE_LABEL: Record<Tone, string> = { gentle: '溫柔療癒', science: '專業科研', playful: '活潑年輕', minimal: '簡約' };
```

改成：

```ts
import { create } from 'zustand';
import type { Copy, Engine, JobInput, ParsedBrief, TemplateId, Tone } from '@/types/contract';
import { API_MODE, getApiClient } from '@/lib/api';
import { MOCK_OPTIONS } from '@/lib/api/mock/options';
import { defaultSelection, emptyJobView, reduceJob, type JobView } from '@/lib/jobs/view';
import { useAppStore } from './app';

export const ENGINE_LABEL: Record<Engine, string> = { comfyui: 'ComfyUI（SDXL + ControlNet + IP-Adapter）', ideogram: 'Ideogram 4.0' };
export const TONE_LABEL: Record<Tone, string> = { gentle: '溫柔療癒', science: '專業科研', playful: '活潑年輕', minimal: '簡約' };
```

找到（2／4）：

```ts
  saveSelection: () => Promise<number>;
}

const DEFAULT_FORM: Omit<StudioForm, 'brief'> = {
  productId: null, parsed: null, templateIds: ['ecom-main', 'ig-post'], variants: 4,
  llm: LLM_OPTIONS[0], engine: 'comfyui', vlm: VLM_OPTIONS[0], maxRetries: 2,
};

/** 事件訂閱放在 store 外：換頁再回來，生成仍在進行 */
let stopListening: (() => void) | null = null;
```

改成：

```ts
  saveSelection: () => Promise<number>;
}

/** 表單預設值：模型與引擎取目前可用的第一個；live 模式真的會用到 GPU，預設每個模板 2 張 */
function defaultForm(): Omit<StudioForm, 'brief'> {
  const options = useAppStore.getState().options ?? MOCK_OPTIONS;
  return {
    productId: null, parsed: null, templateIds: ['ecom-main', 'ig-post'], variants: API_MODE === 'live' ? 2 : 4,
    llm: options.llm[0], engine: options.engines[0], vlm: options.vlm[0], maxRetries: 2,
  };
}

/** 事件訂閱放在 store 外：換頁再回來，生成仍在進行 */
let stopListening: (() => void) | null = null;
```

找到（3／4）：

```ts
const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

export const useStudioStore = create<StudioState>()((set, get) => ({
  ...DEFAULT_FORM,
  brief: '',
  brandId: null,
  parsing: false,
```

改成：

```ts
const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

export const useStudioStore = create<StudioState>()((set, get) => ({
  ...defaultForm(),
  brief: '',
  brandId: null,
  parsing: false,
```

找到（4／4）：

```ts
  resetForBrand: (brandId) => {
    stop();
    set({
      ...DEFAULT_FORM, brandId, brief: DEMO_BRIEFS[brandId] ?? '', parsing: false, starting: false,
      input: null, view: null, selection: {}, copy: null, saved: {}, error: null,
    });
  },
```

改成：

```ts
  resetForBrand: (brandId) => {
    stop();
    set({
      ...defaultForm(), brandId, brief: DEMO_BRIEFS[brandId] ?? '', parsing: false, starting: false,
      input: null, view: null, selection: {}, copy: null, saved: {}, error: null,
    });
  },
```

- [ ] **Step 7: 修改 `web/src/lib/store/queue.ts`**

找到（1／3）：

```ts
import type { TemplateId } from '@/types/contract';
import { getApiClient } from '@/lib/api';
import { emptyJobView, reduceJob, type JobView } from '@/lib/jobs/view';
import { LLM_OPTIONS, VLM_OPTIONS } from './studio';

/** pending 等待中、held 此筆暫停（輪到也不啟動） */
export type QueueStatus = 'pending' | 'held' | 'running' | 'done' | 'needs_review' | 'cancelled' | 'error';
```

改成：

```ts
import type { TemplateId } from '@/types/contract';
import { getApiClient } from '@/lib/api';
import { emptyJobView, reduceJob, type JobView } from '@/lib/jobs/view';
import { MOCK_OPTIONS } from '@/lib/api/mock/options';
import { useAppStore } from './app';

/** pending 等待中、held 此筆暫停（輪到也不啟動） */
export type QueueStatus = 'pending' | 'held' | 'running' | 'done' | 'needs_review' | 'cancelled' | 'error';
```

找到（2／3）：

```ts
      if (!next) return;
      update(next.id, { status: 'running', error: null });
      const api = getApiClient();
      const fail = (err: unknown) => {
        update(next.id, { status: 'error', error: message(err) });
        void get().pump();
```

改成：

```ts
      if (!next) return;
      update(next.id, { status: 'running', error: null });
      const api = getApiClient();
      const options = useAppStore.getState().options ?? MOCK_OPTIONS;
      const fail = (err: unknown) => {
        update(next.id, { status: 'error', error: message(err) });
        void get().pump();
```

找到（3／3）：

```ts
        const parsedBrief = await api.parseBrief(next.brandId, next.brief, next.productId);
        const { jobId } = await api.createJob({
          brandId: next.brandId, productId: next.productId, brief: next.brief, parsedBrief, templateIds: next.templateIds,
          variantsPerTemplate: next.variants, llm: LLM_OPTIONS[0], engine: 'comfyui', vlm: VLM_OPTIONS[0], maxRetries: 2,
        });
        update(next.id, { jobId, view: emptyJobView(jobId) });
        let finished = false;
```

改成：

```ts
        const parsedBrief = await api.parseBrief(next.brandId, next.brief, next.productId);
        const { jobId } = await api.createJob({
          brandId: next.brandId, productId: next.productId, brief: next.brief, parsedBrief, templateIds: next.templateIds,
          variantsPerTemplate: next.variants, llm: options.llm[0], engine: options.engines[0], vlm: options.vlm[0], maxRetries: 2,
        });
        update(next.id, { jobId, view: emptyJobView(jobId) });
        let finished = false;
```

- [ ] **Step 8: 執行測試確認通過**

Run: `npx vitest run src/lib/store`
Expected: PASS（1 + 6 + 9 個測試）。

- [ ] **Step 9: 修改 `web/src/components/layout/app-shell.tsx`**（載入選項）

找到：

```tsx
import { TopBar } from './top-bar';

export function AppShell({ children }: { children: React.ReactNode }) {
  const ready = useAppStore((s) => s.brands.length > 0);

  useEffect(() => {
    void useAppStore.persist.rehydrate();
    void useAppStore.getState().loadBrands();
  }, []);

  return (
```

改成：

```tsx
import { TopBar } from './top-bar';

export function AppShell({ children }: { children: React.ReactNode }) {
  const ready = useAppStore((s) => s.brands.length > 0 && s.options !== null);

  useEffect(() => {
    void useAppStore.persist.rehydrate();
    void useAppStore.getState().loadBrands();
    void useAppStore.getState().loadOptions();
  }, []);

  return (
```

- [ ] **Step 10: 修改 `web/src/components/studio/brief-panel.tsx`**（模型與引擎選項來自 `options`）

找到（1／5）：

```tsx
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { CHANNEL_TEMPLATES } from '@/lib/compose/templates';
import { useProductsStore } from '@/lib/store/products';
import { DEMO_BRIEFS, ENGINE_LABEL, LLM_OPTIONS, TONE_LABEL, useStudioStore, VLM_OPTIONS } from '@/lib/store/studio';

const splitList = (s: string) => s.split(/[,，、]/).map((x) => x.trim()).filter(Boolean);
```

改成：

```tsx
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { MOCK_OPTIONS } from '@/lib/api/mock/options';
import { CHANNEL_TEMPLATES } from '@/lib/compose/templates';
import { useAppStore } from '@/lib/store/app';
import { useProductsStore } from '@/lib/store/products';
import { DEMO_BRIEFS, ENGINE_LABEL, TONE_LABEL, useStudioStore } from '@/lib/store/studio';

const splitList = (s: string) => s.split(/[,，、]/).map((x) => x.trim()).filter(Boolean);
```

找到（2／5）：

```tsx
    setForm: st.setForm, toggleTemplate: st.toggleTemplate, parse: st.parse, start: st.start, cancel: st.cancel,
  })));
  const products = useProductsStore((p) => p.products);
  const running = s.jobRunning || s.starting;

  const chooseProduct = (id: string) => {
```

改成：

```tsx
    setForm: st.setForm, toggleTemplate: st.toggleTemplate, parse: st.parse, start: st.start, cancel: st.cancel,
  })));
  const products = useProductsStore((p) => p.products);
  const options = useAppStore((a) => a.options) ?? MOCK_OPTIONS;
  const running = s.jobRunning || s.starting;

  const chooseProduct = (id: string) => {
```

找到（3／5）：

```tsx
                <Label>LLM（需求拆解、文案、Prompt）</Label>
                <Select disabled={running} value={s.llm} onValueChange={(v) => s.setForm({ llm: v })}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>{LLM_OPTIONS.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
```

改成：

```tsx
                <Label>LLM（需求拆解、文案、Prompt）</Label>
                <Select disabled={running} value={s.llm} onValueChange={(v) => s.setForm({ llm: v })}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>{options.llm.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
```

找到（4／5）：

```tsx
                <Select disabled={running} value={s.engine} onValueChange={(v) => s.setForm({ engine: v as Engine })}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {(Object.keys(ENGINE_LABEL) as Engine[]).map((e) => <SelectItem key={e} value={e}>{ENGINE_LABEL[e]}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
```

改成：

```tsx
                <Select disabled={running} value={s.engine} onValueChange={(v) => s.setForm({ engine: v as Engine })}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {options.engines.map((e) => <SelectItem key={e} value={e}>{ENGINE_LABEL[e]}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
```

找到（5／5）：

```tsx
                <Label>VLM（合規審查）</Label>
                <Select disabled={running} value={s.vlm} onValueChange={(v) => s.setForm({ vlm: v })}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>{VLM_OPTIONS.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            </div>
```

改成：

```tsx
                <Label>VLM（合規審查）</Label>
                <Select disabled={running} value={s.vlm} onValueChange={(v) => s.setForm({ vlm: v })}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>{options.vlm.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            </div>
```

- [ ] **Step 11: 修改 `web/src/components/studio/run-status.tsx`**（顯示失敗原因）

找到（1／3）：

```tsx
'use client';

import Link from 'next/link';
import { CircleCheck, Network, TriangleAlert } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
```

改成：

```tsx
'use client';

import Link from 'next/link';
import { CircleCheck, CircleX, Network, TriangleAlert } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
```

找到（2／3）：

```tsx
        <div className="flex flex-wrap items-center gap-2">
          {view.outcome === 'done' && <CircleCheck className="size-5 text-success" />}
          {view.outcome === 'needs_review' && <TriangleAlert className="size-5 text-warning" />}
          <span className="font-semibold">{view.stage ? STAGE_LABEL[view.stage] : '排隊中'}</span>
          {view.round > 0 && <Badge variant="secondary">第 {view.round} 輪</Badge>}
          <span className="font-mono text-xs text-muted-foreground">{view.jobId}</span>
```

改成：

```tsx
        <div className="flex flex-wrap items-center gap-2">
          {view.outcome === 'done' && <CircleCheck className="size-5 text-success" />}
          {view.outcome === 'needs_review' && <TriangleAlert className="size-5 text-warning" />}
          {view.outcome === 'failed' && <CircleX className="size-5 text-destructive" />}
          <span className="font-semibold">{view.stage ? STAGE_LABEL[view.stage] : '排隊中'}</span>
          {view.round > 0 && <Badge variant="secondary">第 {view.round} 輪</Badge>}
          <span className="font-mono text-xs text-muted-foreground">{view.jobId}</span>
```

找到（3／3）：

```tsx
          <p className="text-sm text-warning">{view.needsReviewReason}。可以檢視候選後手動選用，匯出前請人工確認。</p>
        )}
        {view.outcome === 'cancelled' && <p className="text-sm text-muted-foreground">任務已取消。</p>}
      </CardContent>
    </Card>
  );
```

改成：

```tsx
          <p className="text-sm text-warning">{view.needsReviewReason}。可以檢視候選後手動選用，匯出前請人工確認。</p>
        )}
        {view.outcome === 'cancelled' && <p className="text-sm text-muted-foreground">任務已取消。</p>}
        {view.outcome === 'failed' && <p className="text-sm text-destructive">任務失敗：{view.failureReason}</p>}
      </CardContent>
    </Card>
  );
```

- [ ] **Step 12: 改寫 `web/src/components/layout/connection-badge.tsx`（完整內容）**

點開連線狀態時讀取系統狀態，列出各服務是否正常。

```tsx
'use client';

import { useState, useSyncExternalStore } from 'react';
import type { ComponentStatus, ConnectionState, SystemStatus } from '@/types/contract';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { getApiClient } from '@/lib/api';
import { cn } from '@/lib/utils';

const SERVER_STATE: ConnectionState = { status: 'connecting', transport: 'mock', error: null };
const subscribe = (cb: () => void) => getApiClient().connection.subscribe(cb);
const getSnapshot = () => getApiClient().connection.get();
const getServerSnapshot = () => SERVER_STATE;

const LABEL: Record<ConnectionState['status'], string> = { connecting: '連線中', connected: 'WebSocket 已連線', disconnected: '連線中斷' };
const DOT: Record<ConnectionState['status'], string> = {
  connecting: 'bg-warning shadow-[0_0_0_3px_#fef5e6]',
  connected: 'bg-success shadow-[0_0_0_3px_#e9f8ef]',
  disconnected: 'bg-destructive shadow-[0_0_0_3px_#fdeeee]',
};

const COMPONENT: Record<ComponentStatus['status'], { label: string; className: string }> = {
  ok: { label: '正常', className: 'bg-emerald-50 text-emerald-700' },
  sim: { label: '模擬', className: 'bg-secondary text-primary' },
  off: { label: '未啟用', className: 'bg-muted text-muted-foreground' },
  error: { label: '異常', className: 'bg-red-50 text-red-700' },
};

/** 右上角的連線狀態；點開可看各服務的狀態（開始生圖前確認 ComfyUI 是否開著） */
export function ConnectionBadge() {
  const state = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [failed, setFailed] = useState(false);

  const refresh = () => {
    setFailed(false);
    getApiClient().getSystemStatus().then(setSystem, () => setFailed(true));
  };

  return (
    <Popover onOpenChange={(open) => open && refresh()}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="系統狀態"
          className="inline-flex h-7 items-center gap-2 rounded-full border bg-card px-2.5 text-xs text-muted-foreground sm:px-3"
          title={state.error ?? undefined}
        >
          <span className={cn('size-1.5 rounded-full', DOT[state.status])} />
          <span className="hidden sm:inline">{LABEL[state.status]}</span>
          <span className="hidden font-mono text-[11px] opacity-70 sm:inline">{state.transport}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80">
        <p className="font-semibold">系統狀態</p>
        {failed && <p className="mt-2 text-sm text-destructive">無法取得系統狀態，請確認後端是否啟動。</p>}
        {!failed && !system && <p className="mt-2 text-sm text-muted-foreground">讀取中…</p>}
        {!failed && system && (
          <ul className="mt-2 space-y-2">
            {system.components.map((c) => (
              <li key={c.id} className="text-sm">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{c.label}</span>
                  <span className={cn('ml-auto rounded-full px-2 py-0.5 text-xs font-medium', COMPONENT[c.status].className)}>
                    {COMPONENT[c.status].label}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">{c.detail}</p>
              </li>
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  );
}
```

- [ ] **Step 13: 改寫 `web/src/components/product/local-folder.tsx`（完整內容）**

改用 `listLocalPhotos()`、`importLocalPhoto()`；回傳 `null`（mock 模式）時提示「只有 live 模式可以讀取本機資料夾」。

```tsx
'use client';

import { useEffect, useState } from 'react';
import Image from 'next/image';
import { FolderOpen } from 'lucide-react';
import { toast } from 'sonner';
import type { Brand, LocalPhoto } from '@/types/contract';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { getApiClient } from '@/lib/api';
import { useProductsStore } from '@/lib/store/products';

type FolderState = { status: 'loading' } | { status: 'unavailable' } | { status: 'ready'; photos: LocalPhoto[] };

/** live 模式：列出 assets/products/ 的照片，一鍵匯入成商品（檔名當商品名稱） */
export function LocalFolder({ brand }: { brand: Brand }) {
  const [state, setState] = useState<FolderState>({ status: 'loading' });
  const [importing, setImporting] = useState<string | null>(null);
  const products = useProductsStore((s) => s.products);
  const load = useProductsStore((s) => s.load);

  useEffect(() => {
    let cancelled = false;
    getApiClient().listLocalPhotos().then(
      (photos) => !cancelled && setState(photos ? { status: 'ready', photos } : { status: 'unavailable' }),
      () => !cancelled && setState({ status: 'unavailable' }),
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const imported = new Set(products.flatMap((p) => (p.photo.source === 'local' ? [p.photo.url] : [])));
  const importPhoto = async (photo: LocalPhoto) => {
    setImporting(photo.file);
    try {
      await getApiClient().importLocalPhoto(photo.file, brand.id);
      await load(brand.id);
      toast.success(`已匯入「${photo.name}」`, { description: '請到卡片上補上價格與特徵。' });
    } catch (err) {
      toast.error('匯入失敗', { description: err instanceof Error ? err.message : String(err) });
    } finally {
      setImporting(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FolderOpen className="size-4" />
          本機資料夾 assets/products/
        </CardTitle>
        <CardDescription>把自己的商品照放進 repo 根目錄的 assets/products/（不會上傳 GitHub），live 模式下可直接匯入。</CardDescription>
      </CardHeader>
      <CardContent>
        {state.status === 'loading' && <p className="text-sm text-muted-foreground">讀取中…</p>}
        {state.status === 'unavailable' && <p className="text-sm text-muted-foreground">只有 live 模式可以讀取本機資料夾。</p>}
        {state.status === 'ready' && state.photos.length === 0 && (
          <p className="text-sm text-muted-foreground">資料夾目前沒有圖片（支援 .png、.jpg、.webp）。</p>
        )}
        {state.status === 'ready' && state.photos.length > 0 && (
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
            {state.photos.map((photo) => (
              <li key={photo.file} className="space-y-1.5">
                <div className="relative aspect-square overflow-hidden rounded-lg border bg-muted">
                  <Image src={photo.url} alt={photo.name} fill unoptimized sizes="160px" className="object-contain" />
                </div>
                <p className="truncate text-xs" title={photo.file}>{photo.name}</p>
                <Button
                  size="xs"
                  variant="outline"
                  className="w-full"
                  disabled={imported.has(photo.url) || importing !== null}
                  onClick={() => void importPhoto(photo)}
                >
                  {imported.has(photo.url) ? '已匯入' : importing === photo.file ? '匯入中…' : '匯入'}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 14: 刪除 Next 的本機商品照路由**

靜態輸出不支援 Route Handler，本機資料夾改由後端提供（Task 12）。

```bash
git rm -r web/src/app/api/local-products web/src/lib/server
```

- [ ] **Step 15: 修改 `web/next.config.ts`**

找到：

```ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
```

改成：

```ts
import type { NextConfig } from 'next';
import { PHASE_DEVELOPMENT_SERVER } from 'next/constants';

/**
 * 建置時靜態輸出（out/）：live 版由 nginx 提供，mock 版部署到 Cloudflare Pages。
 * next dev 時若設定 API_PROXY_URL（例如 http://localhost:8000），把 /api 與 /files 轉給本機後端；
 * 靜態輸出不支援 rewrites，所以只在開發伺服器加上。
 */
export default function nextConfig(phase: string): NextConfig {
  const proxy = process.env.API_PROXY_URL;
  if (phase === PHASE_DEVELOPMENT_SERVER) {
    return proxy
      ? {
          rewrites: async () => [
            { source: '/api/:path*', destination: `${proxy}/api/:path*` },
            { source: '/files/:path*', destination: `${proxy}/files/:path*` },
          ],
        }
      : {};
  }
  return { output: 'export', images: { unoptimized: true } };
}
```

- [ ] **Step 16: 建立 `web/scripts/serve-static.mjs`**

```js
// 提供 next build 的靜態輸出（out/）：/studio → studio.html，找不到時回 404.html。Playwright 與本機預覽使用。
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { createServer } from 'node:http';
import path from 'node:path';

const ROOT = path.resolve(import.meta.dirname, '..', 'out');
const PORT = Number(process.argv[2] ?? 3100);
const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json', '.txt': 'text/plain; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png',
  '.ico': 'image/x-icon', '.woff2': 'font/woff2',
};

async function isFile(file) {
  try {
    return (await stat(file)).isFile();
  } catch {
    return false;
  }
}

/**
 * 在 Windows 上 next build 會把預先載入檔 __next.studio.__PAGE__.txt 寫成 __next.studio/__PAGE__.txt
 * （路徑分隔符沒有換成「.」）；Linux 建置（Docker、Cloudflare）沒有這個問題。
 */
function windowsSegmentFile(file) {
  const m = path.basename(file).match(/^__next\.(.+)\.txt$/);
  if (!m) return null;
  const [first, ...rest] = m[1].split('.');
  return rest.length ? path.join(path.dirname(file), `__next.${first}`, ...rest.slice(0, -1), `${rest.at(-1)}.txt`) : null;
}

async function resolveFile(url) {
  const pathname = decodeURIComponent(new URL(url, 'http://localhost').pathname);
  const base = path.join(ROOT, pathname);
  if (base !== ROOT && !base.startsWith(ROOT + path.sep)) return null;
  const candidates = [base, `${base}.html`, path.join(base, 'index.html'), windowsSegmentFile(base)];
  for (const file of candidates) if (file && (await isFile(file))) return file;
  return null;
}

createServer(async (req, res) => {
  const file = await resolveFile(req.url ?? '/');
  const target = file ?? path.join(ROOT, '404.html');
  res.writeHead(file ? 200 : 404, { 'Content-Type': TYPES[path.extname(target)] ?? 'application/octet-stream' });
  createReadStream(target).pipe(res);
}).listen(PORT, () => console.log(`serving ${ROOT} on http://localhost:${PORT}`));
```

- [ ] **Step 17: 修改 `web/playwright.config.ts`**（E2E 改用靜態輸出）

找到（1／2）：

```ts
const PORT = 3100;

/**
 * E2E：先建置正式版，再在 3100 埠啟動（不佔用 next dev 的 3000 埠）。
 * 每個測試都是新的瀏覽器 context，IndexedDB 與 localStorage 從空的開始。
 */
export default defineConfig({
```

改成：

```ts
const PORT = 3100;

/**
 * E2E：先建置靜態輸出（mock 模式），再用 scripts/serve-static.mjs 在 3100 埠提供（不佔用 next dev 的 3000 埠）。
 * 每個測試都是新的瀏覽器 context，IndexedDB 與 localStorage 從空的開始。
 */
export default defineConfig({
```

找到（2／2）：

```ts
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npm run build && npm run start -- --port ${PORT}`,
    url: `http://localhost:${PORT}/studio`,
    reuseExistingServer: !process.env.CI,
    timeout: 240_000,
```

改成：

```ts
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npm run build && node scripts/serve-static.mjs ${PORT}`,
    url: `http://localhost:${PORT}/studio`,
    reuseExistingServer: !process.env.CI,
    timeout: 240_000,
```

- [ ] **Step 18: 全部驗證**

Run: `npm run test`
Expected: PASS，36 個測試檔、286 個測試（刪除了本機商品照工具的測試，新增 app store 的測試）。

Run: `npm run typecheck && npm run lint && npm run build`
Expected: 沒有錯誤；`out/` 內有 `studio.html`、`agent.html`、`dashboard.html` 等頁面。

Run: `npm run e2e`
Expected: 5 passed。

- [ ] **Step 19: Commit**

```bash
git add \
  web/next.config.ts \
  web/playwright.config.ts \
  web/scripts/serve-static.mjs \
  web/src/components/layout/app-shell.tsx \
  web/src/components/layout/connection-badge.tsx \
  web/src/components/product/local-folder.tsx \
  web/src/components/studio/brief-panel.tsx \
  web/src/components/studio/run-status.tsx \
  web/src/lib/store/app.test.ts \
  web/src/lib/store/app.ts \
  web/src/lib/store/queue.test.ts \
  web/src/lib/store/queue.ts \
  web/src/lib/store/studio.test.ts \
  web/src/lib/store/studio.ts
git commit -m "feat: export the frontend as static files and read options, status and local photos through the API" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: golden fixtures：TypeScript 產生、後端比對的固定測資


**Files:**
- Create: `web/src/test/golden.ts`、`web/scripts/fixtures.ts`、`contracts/fixtures/*`（由指令產生）
- Modify: `web/package.json`（`fixtures` 指令、tsx）
- Test: `web/src/test/golden.test.ts`

**Interfaces:**
- Consumes：mock 的 `BRANDS`、`SAMPLE_PRODUCTS`、`CHANNEL_TEMPLATES`、`parseBrief`、`buildTimeline`、`sampleJobs`、`hashString`、`mulberry32`、`dashboardStats`
- Produces（`contracts/fixtures/`，後端 Task 4、5、9、11 使用）：
  - `brands.json`：`{ brands, products, templates }`
  - `rng.json`：`{ hashString: [字串, 雜湊][], mulberry32: [seed, 前 5 個亂數][] }`
  - `timelines/{selune-retry,selune-needs-review,misty-first-pass}.json`：`{ name, jobId, demo, input, events: { at, event }[] }`
  - `stats.json`：`{ snapshots, cases: { brandId, stats }[] }`
  - `npm run fixtures`：重新產生；`golden.test.ts` 檢查檔案沒有過期

- [ ] **Step 1: 修改 `web/package.json`**

找到（1／2）：

```json
    "test": "vitest run",
    "test:watch": "vitest",
    "typecheck": "next typegen && tsc --noEmit",
    "e2e": "playwright test"
  },
  "dependencies": {
    "@fontsource-variable/noto-sans-tc": "^5.3.0",
```

改成：

```json
    "test": "vitest run",
    "test:watch": "vitest",
    "typecheck": "next typegen && tsc --noEmit",
    "e2e": "playwright test",
    "fixtures": "tsx scripts/fixtures.ts"
  },
  "dependencies": {
    "@fontsource-variable/noto-sans-tc": "^5.3.0",
```

找到（2／2）：

```json
    "eslint-config-next": "16.3.8",
    "fake-indexeddb": "^6.2.5",
    "tailwindcss": "^4",
    "typescript": "^5",
    "vitest": "^5.0.3"
  }
```

改成：

```json
    "eslint-config-next": "16.3.8",
    "fake-indexeddb": "^6.2.5",
    "tailwindcss": "^4",
    "tsx": "^4.23.15",
    "typescript": "^5",
    "vitest": "^5.0.3"
  }
```

Run: `npm install`
Expected: 安裝 tsx，`package-lock.json` 更新。

- [ ] **Step 2: 建立 `web/src/test/golden.test.ts`**（先寫失敗測試）

```ts
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { FIXTURES_DIR, goldenFixtures } from './golden';

describe('contracts/fixtures', () => {
  it('matches what the TypeScript code produces (run `npm run fixtures` after changing it)', () => {
    const fixtures = goldenFixtures();
    expect(Object.keys(fixtures).sort()).toEqual([
      'brands.json', 'rng.json', 'stats.json',
      'timelines/misty-first-pass.json', 'timelines/selune-needs-review.json', 'timelines/selune-retry.json',
    ]);
    for (const [file, data] of Object.entries(fixtures)) {
      const onDisk: unknown = JSON.parse(readFileSync(new URL(file, FIXTURES_DIR), 'utf8'));
      expect(onDisk, file).toEqual(JSON.parse(JSON.stringify(data)));
    }
  });

  it('covers a retried job, a job that needs review and a job that passes the first round', () => {
    const fixtures = goldenFixtures();
    const lastStatus = (file: string) =>
      (fixtures[file] as { events: { event: { type: string } }[] }).events.filter((x) => x.event.type === 'job.status').at(-1)!.event;
    expect(lastStatus('timelines/selune-retry.json')).toMatchObject({ stage: 'done', round: 2 });
    expect(lastStatus('timelines/selune-needs-review.json')).toMatchObject({ stage: 'needs_review', round: 2 });
    expect(lastStatus('timelines/misty-first-pass.json')).toMatchObject({ stage: 'done', round: 1 });
  });
});
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `npx vitest run src/test/golden.test.ts`
Expected: FAIL，`Cannot find module './golden'`。

- [ ] **Step 4: 建立 `web/src/test/golden.ts`**

```ts
import type { DemoOptions, JobEvent, JobInput, JobMessage, JobStage, TemplateId } from '@/types/contract';
import type { JobSnapshot } from '@/lib/api/client';
import { BRANDS, getBrandById, SAMPLE_PRODUCTS } from '@/lib/api/mock/data';
import { parseBrief } from '@/lib/api/mock/brief';
import { sampleJobs } from '@/lib/api/mock/samples';
import { buildTimeline } from '@/lib/api/mock/scenario';
import { CHANNEL_TEMPLATES, getTemplate } from '@/lib/compose/templates';
import { hashString, mulberry32 } from '@/lib/core/num';
import { dashboardStats } from '@/lib/stats/dashboard';

/**
 * 給後端（Python）一致性測試的固定測資，寫在 repo 根目錄的 contracts/fixtures/。
 * 第一階段的 TypeScript 是行為的來源：後端解析這些資料、用同樣的輸入重算，結果必須相同。
 * 修改相關程式後執行 `npm run fixtures` 重新產生；golden.test.ts 會檢查檔案是否過期。
 */
export const FIXTURES_DIR = new URL('../../../contracts/fixtures/', import.meta.url);

const DEFAULT_DEMO: DemoOptions = { speed: 1, firstRoundFail: true, forceAllFail: false };

interface Scenario {
  name: string;
  jobId: string;
  brandId: string;
  brief: string;
  templateIds: TemplateId[];
  variants: number;
  maxRetries: number;
  demo: Partial<DemoOptions>;
}

/** 模擬模式的劇本：預設首輪失敗後重試通過、全部失敗轉人工審核、首輪就通過 */
const SCENARIOS: Scenario[] = [
  {
    name: 'selune-retry', jobId: 'job_20261007_1000_a1b2', brandId: 'selune',
    brief: '幫我做週年慶的精華液海報，主打買一送一，要溫柔療癒的感覺', templateIds: ['ig-post', 'story'], variants: 2,
    maxRetries: 2, demo: {},
  },
  {
    name: 'selune-needs-review', jobId: 'job_20261007_1010_c3d4', brandId: 'selune',
    brief: '雙11 11/1–11/11 精華液限時85折，要專業科研感', templateIds: ['ecom-main'], variants: 2, maxRetries: 1,
    demo: { forceAllFail: true },
  },
  {
    name: 'misty-first-pass', jobId: 'job_20261007_1020_e5f6', brandId: 'misty-isle',
    brief: '幫我設計一款簡約風格的冷萃咖啡宣傳海報', templateIds: ['banner'], variants: 3, maxRetries: 2,
    demo: { firstRoundFail: false },
  },
];

function scenarioInput(s: Scenario): JobInput {
  const brand = getBrandById(s.brandId);
  const product = SAMPLE_PRODUCTS.find((p) => p.brandId === brand.id)!;
  return {
    brandId: brand.id, productId: product.id, brief: s.brief, parsedBrief: parseBrief(s.brief, brand, product),
    templateIds: s.templateIds, variantsPerTemplate: s.variants, llm: 'Gemini 3.7 Flash', engine: 'comfyui',
    vlm: 'Gemini 3.7 Vision', maxRetries: s.maxRetries,
  };
}

function timeline(jobId: string, input: JobInput, demo: DemoOptions): { at: number; event: JobEvent }[] {
  const brand = getBrandById(input.brandId);
  const product = SAMPLE_PRODUCTS.find((p) => p.id === input.productId)!;
  const templates = input.templateIds.map((id) => getTemplate(id));
  return buildTimeline({ jobId, input, brand, product, templates, demo, seed: hashString(jobId) }).map(({ at, event }) => ({ at, event }));
}

function snapshot(jobId: string, input: JobInput, createdAt: Date, events: JobEvent[], ats: number[]): JobSnapshot {
  const messages: JobMessage[] = events.map((e, i) => ({ ...e, seq: i + 1, ts: new Date(createdAt.getTime() + ats[i]).toISOString() }));
  let stage: JobStage = 'parsing';
  let round = 0;
  let bestRenderIds: JobSnapshot['summary']['bestRenderIds'] = {};
  for (const e of events) {
    if (e.type === 'job.status') ({ stage, round } = e);
    if (e.type === 'job.completed') bestRenderIds = e.bestRenderIds;
  }
  const finished = ['done', 'needs_review', 'cancelled', 'failed'].includes(stage);
  return { summary: { id: jobId, input, createdAt: createdAt.toISOString(), stage, round, finished, bestRenderIds }, events: messages };
}

/** 儀表板統計的輸入：6 筆示範任務（含需人工審核、首輪通過、Ideogram），加上 1 筆取消、1 筆失敗（兩者都不列入統計） */
function statsSnapshots(): JobSnapshot[] {
  const now = new Date('2026-10-07T02:00:00.000Z');
  const seeded = sampleJobs(6, now).map(({ input, demo, createdAt }, i) => {
    const jobId = `job_sample_${String(i + 1).padStart(2, '0')}`;
    const tl = timeline(jobId, input, demo);
    return snapshot(jobId, input, createdAt, tl.map((x) => x.event), tl.map((x) => x.at));
  });
  const input = scenarioInput(SCENARIOS[0]);
  const tl = timeline('job_sample_cancelled', input, DEFAULT_DEMO);
  const cut = tl.findIndex((x) => x.event.type === 'job.status' && x.event.stage === 'rendering');
  const head = tl.slice(0, cut + 1);
  const at = head.at(-1)!.at;
  const cancelled = snapshot(
    'job_sample_cancelled', input, new Date('2026-10-07T01:00:00.000Z'),
    [...head.map((x) => x.event), { type: 'job.status', stage: 'cancelled', round: 1 }], [...head.map((x) => x.at), at],
  );
  const failed = snapshot(
    'job_sample_failed', input, new Date('2026-10-07T01:30:00.000Z'),
    [
      ...head.map((x) => x.event),
      { type: 'job.failed', jobId: 'job_sample_failed', reason: 'ComfyUI 沒有回應' },
      { type: 'job.status', stage: 'failed', round: 1 },
    ],
    [...head.map((x) => x.at), at, at],
  );
  return [...seeded, cancelled, failed];
}

/** 統計用不到 PromptSpec 與注入參數：拿掉以縮小檔案（後端的統計直接處理事件 JSON） */
function slim(snap: JobSnapshot): unknown {
  return {
    summary: snap.summary,
    events: snap.events.map((m) => {
      if (m.type === 'prompt.generated') return { ...m, spec: null };
      if (m.type === 'comfy.queued') return { ...m, injection: null };
      if (m.type === 'render.completed') return { ...m, renders: m.renders.map((r) => ({ ...r, spec: null })) };
      return m;
    }),
  };
}

export function goldenFixtures(): Record<string, unknown> {
  const out: Record<string, unknown> = {
    'brands.json': { brands: BRANDS, products: SAMPLE_PRODUCTS, templates: CHANNEL_TEMPLATES },
    'rng.json': {
      hashString: ['', 'a', 'selune#color', '週年慶', 'job_20261007_1000_a1b2'].map((s) => [s, hashString(s)]),
      mulberry32: [0, 1, 42, 123456789, -5, 4294967295].map((seed) => {
        const rng = mulberry32(seed);
        return [seed, Array.from({ length: 5 }, () => rng())];
      }),
    },
  };
  for (const s of SCENARIOS) {
    const demo = { ...DEFAULT_DEMO, ...s.demo };
    const input = scenarioInput(s);
    out[`timelines/${s.name}.json`] = { name: s.name, jobId: s.jobId, demo, input, events: timeline(s.jobId, input, demo) };
  }
  const snaps = statsSnapshots();
  out['stats.json'] = {
    snapshots: snaps.map(slim),
    cases: [null, 'selune', 'misty-isle'].map((brandId) => ({
      brandId, stats: dashboardStats(brandId ? snaps.filter((s) => s.summary.input.brandId === brandId) : snaps),
    })),
  };
  return out;
}
```

- [ ] **Step 5: 建立 `web/scripts/fixtures.ts`**

```ts
// 產生 contracts/fixtures/（後端一致性測試的固定測資，不縮排以縮小檔案）：npm run fixtures
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { FIXTURES_DIR, goldenFixtures } from '../src/test/golden';

for (const [file, data] of Object.entries(goldenFixtures())) {
  const target = fileURLToPath(new URL(file, FIXTURES_DIR));
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, `${JSON.stringify(data)}\n`);
  console.log(`wrote contracts/fixtures/${file}`);
}
```

- [ ] **Step 6: 產生 fixtures**

Run: `npm run fixtures`
Expected: 輸出 6 行 `wrote contracts/fixtures/...`（`brands.json`、`rng.json`、三個 `timelines/*.json`、`stats.json`）。檔案不縮排以縮小大小；`stats.json` 只保留 6 個示範任務。

- [ ] **Step 7: 執行測試確認通過**

Run: `npx vitest run src/test/golden.test.ts`
Expected: PASS（2 個測試）。

Run: `npm run test && npm run typecheck && npm run lint`
Expected: 37 個測試檔、288 個測試全部通過；沒有錯誤。

- [ ] **Step 8: Commit**

```bash
git add \
  contracts/fixtures/brands.json \
  contracts/fixtures/rng.json \
  contracts/fixtures/stats.json \
  contracts/fixtures/timelines/misty-first-pass.json \
  contracts/fixtures/timelines/selune-needs-review.json \
  contracts/fixtures/timelines/selune-retry.json \
  web/package-lock.json \
  web/package.json \
  web/scripts/fixtures.ts \
  web/src/test/golden.test.ts \
  web/src/test/golden.ts
git commit -m "test: generate golden fixtures for the backend from the TypeScript mock" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: 後端專案：Pydantic 合約、與前端相同的雜湊與亂數


**Files:**
- Create: `backend/pyproject.toml`、`backend/uv.lock`（由 uv 產生）、`backend/app/__init__.py`、`backend/app/contract.py`、`backend/app/core/__init__.py`、`backend/app/core/rng.py`
- Modify: `.gitignore`
- Test: `backend/tests/__init__.py`、`backend/tests/fixtures.py`、`backend/tests/test_contract.py`、`backend/tests/test_rng.py`

**Interfaces:**
- Consumes：Task 3 的 `contracts/fixtures/`
- Produces：
  - `app.contract`：
    - 基底 `Model`：camelCase alias、`extra='forbid'`、`to_json()`。
    - 對應 `contract.ts` 的所有模型。
    - `JobEvent`（以 `type` 區分的聯集）、`parse_event(data)`、`message_json(event, seq, ts)`、`parse_message(data) -> (event, seq, ts)`。
    - 常數 `TEMPLATE_IDS`、`CHECK_IDS`、`FINISHED_STAGES`。
    - `RagHit.rerank_score` 為 `None` 時不輸出（TypeScript 的選填欄位）。
  - `app.core.rng`：`hash_string(s) -> int`、`Mulberry32(seed)`（`__call__() -> float`），與 `web/src/lib/core/num.ts` 的結果完全相同。
  - `tests.fixtures`：`load_fixture(name)`（每次回傳新的物件）、`FIXTURES_DIR`、`TIMELINES`。

- [ ] **Step 1: 修改 `.gitignore`**（Python 與後端執行時資料）

找到：

```text

# Claude Code worktrees
.claude/worktrees/
```

改成：

```text

# Claude Code worktrees
.claude/worktrees/

# Python（backend/）
.venv/
__pycache__/
.mypy_cache/
.ruff_cache/
.pytest_cache/

# 後端執行時資料（商品照、生成圖、審查用海報）
/data/
```

- [ ] **Step 2: 建立 `backend/pyproject.toml`**

```toml
[project]
name = "genai-agent-backend"
version = "0.1.0"
description = "虛實整合 GenAI Agent 後端：FastAPI、SAQ worker 與外部服務轉接器"
requires-python = ">=3.13"
dependencies = [
    "alembic>=1.20.0",
    "asyncpg>=0.32.0",
    "fastapi>=0.142.2",
    "httpx>=0.28.1",
    "pydantic>=2.13.5",
    "pydantic-settings>=2.15.0",
    "python-multipart>=0.0.32",
    "pyyaml>=6.0.3",
    "redis>=8.1.0",
    "saq>=0.26.4",
    "sqlalchemy[asyncio]>=2.1.3",
    "uvicorn[standard]>=0.54.0",
]

[dependency-groups]
dev = [
    "mypy>=2.4.0",
    "pytest>=9.1.1",
    "pytest-asyncio>=1.4.0",
    "ruff>=0.16.10",
    "types-pyyaml>=6.0.12.20260906",
]

[tool.uv]
package = false

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"

[tool.ruff]
line-length = 120

[tool.ruff.format]
quote-style = "single"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]
files = ["app", "tests"]
```

- [ ] **Step 3: 安裝**

```bash
cd backend
uv sync --python 3.13
```

Expected：uv 下載 Python 3.13（如果還沒有）、建立 `.venv` 與 `uv.lock`。之後的指令都用 `uv run`。

- [ ] **Step 4: 建立 `backend/tests/__init__.py`**（空檔）

```python

```

- [ ] **Step 5: 建立 `backend/tests/fixtures.py`**

```python
"""讀取 contracts/fixtures/（由 web 的 `npm run fixtures` 產生）。"""

import json
from functools import cache
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'contracts' / 'fixtures'
TIMELINES = ('selune-retry', 'selune-needs-review', 'misty-first-pass')


@cache
def _read(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding='utf-8')


def load_fixture(name: str) -> Any:
    """每次回傳新的物件（測試可以放心修改）。"""
    return json.loads(_read(name))
```

- [ ] **Step 6: 建立 `backend/tests/test_rng.py`**（先寫失敗測試）

```python
from app.core.rng import Mulberry32, hash_string
from tests.fixtures import load_fixture


def test_hash_string_matches_the_frontend() -> None:
    for text, expected in load_fixture('rng.json')['hashString']:
        assert hash_string(text) == expected


def test_mulberry32_matches_the_frontend_for_any_seed() -> None:
    for seed, expected in load_fixture('rng.json')['mulberry32']:
        rng = Mulberry32(seed)
        assert [rng() for _ in expected] == expected
```

- [ ] **Step 7: 建立 `backend/tests/test_contract.py`**

前端產生的每一份資料（品牌、商品、模板、三個劇本的每一則事件、任務摘要與儀表板統計）經 Pydantic 解析再輸出，必須與原本的 JSON 完全相同。

```python
"""合約模型必須能無損解析 TypeScript 產生的 golden fixtures（contracts/fixtures/）。"""

import pytest

from app.contract import (
    Brand,
    ChannelTemplate,
    DashboardStats,
    DemoOptions,
    JobInput,
    JobStatusEvent,
    JobSummary,
    Product,
    RagHit,
    message_json,
    parse_event,
    parse_message,
)
from tests.fixtures import TIMELINES, load_fixture


def test_brands_products_and_templates_round_trip() -> None:
    data = load_fixture('brands.json')
    for raw in data['brands']:
        assert Brand.model_validate(raw).to_json() == raw
    for raw in data['products']:
        assert Product.model_validate(raw).to_json() == raw
    for raw in data['templates']:
        assert ChannelTemplate.model_validate(raw).to_json() == raw


@pytest.mark.parametrize('name', TIMELINES)
def test_every_event_of_a_timeline_round_trips(name: str) -> None:
    data = load_fixture(f'timelines/{name}.json')
    assert JobInput.model_validate(data['input']).to_json() == data['input']
    assert DemoOptions.model_validate(data['demo']).to_json() == data['demo']
    types = set()
    for item in data['events']:
        event = parse_event(item['event'])
        types.add(event.type)
        assert event.to_json() == item['event']
    assert {'job.accepted', 'prompt.generated', 'render.completed', 'review.check', 'job.status'} <= types


def test_job_summaries_and_dashboard_stats_round_trip() -> None:
    data = load_fixture('stats.json')
    for snap in data['snapshots']:
        assert JobSummary.model_validate(snap['summary']).to_json() == snap['summary']
    for case in data['cases']:
        assert DashboardStats.model_validate(case['stats']).to_json() == case['stats']


def test_messages_carry_seq_and_ts_next_to_the_event_fields() -> None:
    event = JobStatusEvent(type='job.status', stage='queued', round=0)
    message = message_json(event, 2, '2026-10-07T01:00:00.000Z')
    assert message == {'type': 'job.status', 'stage': 'queued', 'round': 0, 'seq': 2, 'ts': '2026-10-07T01:00:00.000Z'}
    assert parse_message(message) == (event, 2, '2026-10-07T01:00:00.000Z')


def test_rerank_score_is_omitted_until_reranked() -> None:
    hit = RagHit(chunk_id='c', source='s', section='§', tag='law', text='t', vector_score=0.8)
    assert 'rerankScore' not in hit.to_json()
    assert hit.model_copy(update={'rerank_score': 0.9}).to_json()['rerankScore'] == 0.9
```

- [ ] **Step 8: 執行測試確認失敗**

Run: `uv run pytest -q`
Expected: FAIL，2 個測試檔無法載入（`test_contract.py`、`test_rng.py`）：`ModuleNotFoundError: No module named 'app'`。

- [ ] **Step 9: 建立 `backend/app/__init__.py`**

```python
"""虛實整合 GenAI Agent 後端。"""
```

- [ ] **Step 10: 建立 `backend/app/core/__init__.py`**（空檔）

```python

```

- [ ] **Step 11: 建立 `backend/app/core/rng.py`**

JavaScript 的位元運算以 32 位元整數計算，`Math.imul` 取乘積的低 32 位元；這裡以遮罩重現。

```python
"""與 web/src/lib/core/num.ts 相同的雜湊與偽隨機數：模擬模式的 seed 與前端 mock 完全一致。"""

_MASK = 0xFFFFFFFF


def _imul(a: int, b: int) -> int:
    """JavaScript Math.imul：32-bit 乘法取低 32 位（以無號整數表示）。"""
    return (a * b) & _MASK


def hash_string(s: str) -> int:
    """FNV-1a 32-bit 字串雜湊，回傳非負整數；以 Unicode code point 為單位（同 JS 的 for...of）。"""
    h = 2166136261
    for ch in s:
        h = _imul(h ^ ord(ch), 16777619)
    return h


class Mulberry32:
    """可重現的偽隨機數產生器（同一 seed 產生同一序列，回傳 [0, 1) 的浮點數）。"""

    def __init__(self, seed: int) -> None:
        self._a = seed & _MASK

    def __call__(self) -> float:
        self._a = (self._a + 0x6D2B79F5) & _MASK
        a = self._a
        t = _imul(a ^ (a >> 15), 1 | a)
        t = ((t + _imul(t ^ (t >> 7), 61 | t)) & _MASK) ^ t
        return (t ^ (t >> 14)) / 4294967296
```

- [ ] **Step 12: 建立 `backend/app/contract.py`**

```python
"""前後端資料約定：對應 web/src/types/contract.ts（欄位名稱、型別、選填規則都必須一致）。

JSON 一律使用 camelCase（以 alias 產生），Python 端使用 snake_case。
WebSocket 送出的訊息是事件加上 seq 與 ts（見 message_json）。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_serializer
from pydantic.alias_generators import to_camel

TemplateId = Literal['ecom-main', 'scene', 'ig-post', 'story', 'banner']
TEMPLATE_IDS: tuple[TemplateId, ...] = ('ecom-main', 'scene', 'ig-post', 'story', 'banner')
LayoutElementId = Literal['logo', 'headline', 'subhead', 'features', 'product', 'badge', 'price', 'disclaimer']
CheckId = Literal[
    'banned_words',
    'color_delta',
    'logo_clearance',
    'disclaimer',
    'product_ratio',
    'whitespace',
    'ocr_typo',
    'vlm_exaggeration',
    'vlm_occlusion',
    'vlm_quality',
]
CHECK_IDS: tuple[CheckId, ...] = (
    'banned_words',
    'color_delta',
    'logo_clearance',
    'disclaimer',
    'product_ratio',
    'whitespace',
    'ocr_typo',
    'vlm_exaggeration',
    'vlm_occlusion',
    'vlm_quality',
)
Tone = Literal['gentle', 'science', 'playful', 'minimal']
Engine = Literal['comfyui', 'ideogram']
RagTag = Literal['color', 'logo', 'law', 'layout', 'font', 'history', 'general']
JobStage = Literal[
    'queued',
    'parsing',
    'retrieving',
    'prompting',
    'rendering',
    'composing',
    'reviewing',
    'rewriting',
    'saving',
    'done',
    'needs_review',
    'cancelled',
    'failed',
]
FINISHED_STAGES: frozenset[JobStage] = frozenset({'done', 'needs_review', 'cancelled', 'failed'})
RenderNode = Literal['cutout', 'generate', 'relight', 'upscale']
LogSource = Literal['ws', 'api', 'agent', 'rag', 'comfy', 'compose', 'vlm', 'db']
LogLevel = Literal['info', 'ok', 'warn', 'error']
CheckStatus = Literal['pass', 'warn', 'fail']
BBox = tuple[int, int, int, int]


class Model(BaseModel):
    """所有約定模型的基底：camelCase JSON、拒絕多餘欄位。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra='forbid')

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode='json')


# ---------- 品牌與 RAG ----------
class Palette(Model):
    primary: str
    secondary: str
    accent: str
    ink: str


class RagChunk(Model):
    id: str
    source: str
    section: str
    tag: RagTag
    text: str


class CaseStudy(Model):
    id: str
    title: str
    channel: str
    ctr: float
    notes: str


class BrandRules(Model):
    max_delta_e: float
    min_whitespace: float
    product_ratio: tuple[float, float]


class Fonts(Model):
    headline: str
    body: str


class CopyPreset(Model):
    headline: tuple[str, str]
    subhead: str


class BrandLogo(Model):
    url: str


class Brand(Model):
    id: str
    name: str
    category: str
    ci_version: str
    palette: Palette
    fonts: Fonts
    visual_style: str
    default_tone: Tone
    rules: BrandRules
    banned_words: list[str]
    replacements: dict[str, str]
    claim_words: list[str]
    disclaimer_phrase: str
    guideline_chunks: list[RagChunk]
    case_studies: list[CaseStudy]
    copy_presets: dict[Tone, CopyPreset]
    logo: BrandLogo | None


# ---------- 商品與模板 ----------
class SamplePhoto(Model):
    source: Literal['sample']
    art: Literal['serum', 'coldbrew']


class FilePhoto(Model):
    source: Literal['upload', 'local']
    url: str


ProductPhoto = Annotated[SamplePhoto | FilePhoto, Field(discriminator='source')]


class ProductCutout(Model):
    model: str
    url: str | None


class Price(Model):
    sale: int
    original: int


class Product(Model):
    id: str
    brand_id: str
    name: str
    features: list[str]
    price: Price
    photo: ProductPhoto
    cutout: ProductCutout | None
    created_at: str


class ChannelTemplate(Model):
    id: TemplateId
    label: str
    ratio: str
    width: int
    height: int


# ---------- 任務輸入 ----------
class ParsedBrief(Model):
    product_name: str | None
    selling_points: list[str]
    audience: str
    tone: Tone
    campaign: str | None
    offer: str | None
    period: str | None
    style: list[str]


class JobInput(Model):
    brand_id: str
    product_id: str
    brief: str
    parsed_brief: ParsedBrief
    template_ids: list[TemplateId]
    variants_per_template: int
    llm: str
    engine: Engine
    vlm: str
    max_retries: int


class DemoOptions(Model):
    speed: Literal[1, 2, 4]
    first_round_fail: bool
    force_all_fail: bool


# ---------- Agent 輸出 ----------
class Badge(Model):
    top: str
    main: str
    sub: str


class CopyPrice(Model):
    label: str
    sale: int
    original: int


class Copy(Model):
    headline: tuple[str, str]
    subhead: str
    features: list[str]
    badge: Badge
    price: CopyPrice
    product_name: str
    disclaimer: str


class ComfyParam(Model):
    node_id: str
    input: str
    label: str
    value: str | int | float


class ComfyInjection(Model):
    engine: Engine
    workflow_file: str
    params: list[ComfyParam]


class Canvas(Model):
    width: int
    height: int
    ratio: str


class LayoutBox(Model):
    id: LayoutElementId
    bbox: BBox
    z: int


class PromptSpec(Model):
    job_id: str
    round: int
    template_id: TemplateId
    brand_id: str
    canvas: Canvas
    palette: Palette
    copy_: Copy = Field(alias='copy')
    layout: list[LayoutBox]
    positive_prompt: str
    negative_prompt: str
    injection: ComfyInjection
    rag_refs: list[str]


# ---------- 審查與產出 ----------
class ReviewCheck(Model):
    id: CheckId
    name: str
    kind: Literal['rule', 'vlm']
    rule: str
    value: str
    status: CheckStatus
    target: LayoutElementId | Literal['canvas'] | None
    rag_ref: str | None


class ProceduralBackground(Model):
    kind: Literal['procedural']
    seed: int
    palette: Palette
    style: str


class UrlBackground(Model):
    kind: Literal['url']
    url: str
    includes_product: bool


RenderBackground = Annotated[ProceduralBackground | UrlBackground, Field(discriminator='kind')]


class Render(Model):
    id: str
    job_id: str
    round: int
    template_id: TemplateId
    variant: int
    background: RenderBackground
    spec: PromptSpec
    score: int | None
    passed: bool | None
    checks: list[ReviewCheck]


class RagHit(Model):
    chunk_id: str
    source: str
    section: str
    tag: RagTag
    text: str
    vector_score: float
    rerank_score: float | None = None

    @model_serializer(mode='wrap')
    def _omit_missing_rerank(self, handler: Any) -> dict[str, Any]:
        # TypeScript 的 rerankScore 是選填欄位：還沒 Rerank 時不輸出
        data: dict[str, Any] = handler(self)
        for key in ('rerankScore', 'rerank_score'):
            if key in data and data[key] is None:
                del data[key]
        return data


class Fix(Model):
    check_id: CheckId
    title: str
    desc: str


# ---------- WebSocket 事件 ----------
class JobAcceptedEvent(Model):
    type: Literal['job.accepted']
    job_id: str


class JobStatusEvent(Model):
    type: Literal['job.status']
    stage: JobStage
    round: int


class BriefParsedEvent(Model):
    type: Literal['brief.parsed']
    parsed_brief: ParsedBrief


class RagRetrievedEvent(Model):
    type: Literal['rag.retrieved']
    query: str
    hits: list[RagHit]


class RagRerankedEvent(Model):
    type: Literal['rag.reranked']
    hits: list[RagHit]


class PromptGeneratedEvent(Model):
    type: Literal['prompt.generated']
    round: int
    template_id: TemplateId
    spec: PromptSpec


class ComfyQueuedEvent(Model):
    type: Literal['comfy.queued']
    round: int
    template_id: TemplateId
    prompt_id: str
    injection: ComfyInjection


class RenderProgressEvent(Model):
    type: Literal['render.progress']
    round: int
    node: RenderNode
    step: int
    max_step: int


class RenderCompletedEvent(Model):
    type: Literal['render.completed']
    round: int
    renders: list[Render]


class ReviewCheckEvent(Model):
    type: Literal['review.check']
    round: int
    render_id: str
    check: ReviewCheck


class ReviewCompletedEvent(Model):
    type: Literal['review.completed']
    round: int
    render_id: str
    score: int
    passed: bool


class RewriteStartedEvent(Model):
    type: Literal['rewrite.started']
    round: int
    template_id: TemplateId
    reasons: list[CheckId]
    fixes: list[Fix]
    requery: bool


class JobCompletedEvent(Model):
    type: Literal['job.completed']
    job_id: str
    best_render_ids: dict[TemplateId, str]


class JobNeedsReviewEvent(Model):
    type: Literal['job.needs_review']
    job_id: str
    reason: str


class JobFailedEvent(Model):
    type: Literal['job.failed']
    job_id: str
    reason: str


class LogEvent(Model):
    type: Literal['log']
    source: LogSource
    level: LogLevel
    message: str


JobEvent = Annotated[
    JobAcceptedEvent
    | JobStatusEvent
    | BriefParsedEvent
    | RagRetrievedEvent
    | RagRerankedEvent
    | PromptGeneratedEvent
    | ComfyQueuedEvent
    | RenderProgressEvent
    | RenderCompletedEvent
    | ReviewCheckEvent
    | ReviewCompletedEvent
    | RewriteStartedEvent
    | JobCompletedEvent
    | JobNeedsReviewEvent
    | JobFailedEvent
    | LogEvent,
    Field(discriminator='type'),
]
JOB_EVENT: TypeAdapter[JobEvent] = TypeAdapter(JobEvent)


def parse_event(data: dict[str, Any]) -> JobEvent:
    """事件 JSON（不含 seq、ts）→ 事件模型。"""
    return JOB_EVENT.validate_python(data)


def message_json(event: JobEvent, seq: int, ts: str) -> dict[str, Any]:
    """事件模型 → WebSocket 訊息 JSON（JobMessage：事件欄位加上 seq 與 ts）。"""
    return {**event.to_json(), 'seq': seq, 'ts': ts}


def parse_message(data: dict[str, Any]) -> tuple[JobEvent, int, str]:
    """WebSocket 訊息 JSON → (事件, seq, ts)。"""
    body = {k: v for k, v in data.items() if k not in ('seq', 'ts')}
    return parse_event(body), int(data['seq']), str(data['ts'])


# ---------- 歷史紀錄、任務列表 ----------
class HistoryEntry(Model):
    id: str
    job_id: str
    brand_id: str
    product_id: str
    input: JobInput
    template_id: TemplateId
    render: Render
    copy_: Copy = Field(alias='copy')
    selected_at: str
    favorite: bool
    written_to_rag: bool


class JobSummary(Model):
    id: str
    input: JobInput
    created_at: str
    stage: JobStage
    round: int
    finished: bool
    best_render_ids: dict[TemplateId, str]


# ---------- 品牌文件上傳 ----------
class BrandDocument(Model):
    name: str
    text: str


class IngestChunkedEvent(Model):
    type: Literal['ingest.chunked']
    source: str
    chunks: list[RagChunk]


class IngestEmbeddedEvent(Model):
    type: Literal['ingest.embedded']
    chunk_id: str
    index: int
    total: int
    dims: int
    preview: list[float]


class IngestStoredEvent(Model):
    type: Literal['ingest.stored']
    collection: str
    count: int


IngestEvent = Annotated[IngestChunkedEvent | IngestEmbeddedEvent | IngestStoredEvent, Field(discriminator='type')]


# ---------- 成效儀表板 ----------
class CheckFailureStat(Model):
    check_id: CheckId
    name: str
    kind: Literal['rule', 'vlm']
    fail: int
    warn: int


class RerankHitStat(Model):
    k: int
    vector: float
    rerank: float


class JobStat(Model):
    job_id: str
    brand_id: str
    created_at: str
    outcome: Literal['done', 'needs_review']
    templates: int
    rounds: int
    renders: int
    delivered: int
    duration_ms: int
    cost_usd: float


class DashboardStats(Model):
    jobs: int
    renders: int
    pass_rate: float
    first_pass_rate: float
    avg_retries: float
    avg_duration_ms: float
    cost_per_image: float | None
    check_failures: list[CheckFailureStat]
    rerank_hits: list[RerankHitStat]
    recent: list[JobStat]


# ---------- 本機資料夾、可用選項與系統狀態 ----------
class LocalPhoto(Model):
    file: str
    name: str
    url: str
    size: int


class ApiOptions(Model):
    llm: list[str]
    vlm: list[str]
    engines: list[Engine]


class ComponentStatus(Model):
    id: str
    label: str
    status: Literal['ok', 'sim', 'off', 'error']
    detail: str


class SystemStatus(Model):
    components: list[ComponentStatus]
```

- [ ] **Step 13: 執行測試確認通過**

Run: `uv run pytest -q`
Expected: PASS，9 passed（`test_contract.py` 7 個、`test_rng.py` 2 個）。

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: 沒有錯誤。

- [ ] **Step 14: Commit**

```bash
git add \
  .gitignore \
  backend/app/__init__.py \
  backend/app/contract.py \
  backend/app/core/__init__.py \
  backend/app/core/rng.py \
  backend/pyproject.toml \
  backend/tests/__init__.py \
  backend/tests/fixtures.py \
  backend/tests/test_contract.py \
  backend/tests/test_rng.py \
  backend/uv.lock
git commit -m "feat: add the backend project with the Pydantic contract and the frontend hash and RNG" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: 品牌設定檔（`brands/*.yaml`）


**Files:**
- Create: `brands/selune.yaml`、`brands/misty-isle.yaml`、`brands/_template.yaml`、`backend/app/brands.py`
- Modify: `backend/tests/fixtures.py`
- Test: `backend/tests/test_brands.py`

**Interfaces:**
- Consumes：Task 4 的 `Brand`、`Product`、`RagChunk`
- Produces：
  - `load_brands(directory: Path) -> tuple[list[LoadedBrand], list[BrandLoadError]]`：
    - 以底線開頭的檔案（範本）略過。
    - 格式錯誤的檔案不中斷其他品牌的載入。
  - `LoadedBrand(brand, samples: list[Product], logo_path, style_images, source_hash)`；`BrandLoadError(file, message)`（message 為繁體中文）
  - 品牌 YAML 的欄位：
    - 對應 `Brand`，另有 `guidelines`（`key` 在品牌內不可重複）、`samples`、`logo`、`styleImages`。
    - 切塊 id 為 `{品牌 id}#{key}`。
    - 有 `replacements` 而沒有 `law-alt` 切塊時，自動產生「合規替代用語對照」。
  - `Brand.logo.url` 為 `/files/brands/{相對路徑}`；Logo 與參考圖必須放在 `brands/` 資料夾內
  - `tests.fixtures.BRANDS_DIR`

- [ ] **Step 1: 修改 `backend/tests/fixtures.py`**

找到：

```python
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'contracts' / 'fixtures'
TIMELINES = ('selune-retry', 'selune-needs-review', 'misty-first-pass')
```

改成：

```python
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / 'contracts' / 'fixtures'
BRANDS_DIR = REPO_ROOT / 'brands'
TIMELINES = ('selune-retry', 'selune-needs-review', 'misty-first-pass')
```

- [ ] **Step 2: 建立 `backend/tests/test_brands.py`**（先寫失敗測試）

兩個示範品牌的 YAML 載入後，必須與前端的示範資料（`brands.json`）完全相同。

```python
import shutil
from pathlib import Path

from app.brands import load_brands
from tests.fixtures import BRANDS_DIR, load_fixture


def test_demo_brands_match_the_frontend_data() -> None:
    loaded, errors = load_brands(BRANDS_DIR)
    assert errors == []
    fixture = load_fixture('brands.json')
    assert [b.brand.to_json() for b in loaded] == sorted(fixture['brands'], key=lambda b: b['id'])
    samples = [p.to_json() for b in loaded for p in b.samples]
    assert samples == sorted(fixture['products'], key=lambda p: p['brandId'])


def test_the_template_is_skipped_but_valid_once_copied(tmp_path: Path) -> None:
    assert '_template' not in [b.brand.id for b in load_brands(BRANDS_DIR)[0]]
    shutil.copy(BRANDS_DIR / '_template.yaml', tmp_path / 'my-brand.yaml')
    loaded, errors = load_brands(tmp_path)
    assert errors == []
    brand = loaded[0].brand
    assert brand.id == 'my-brand'
    assert brand.logo is None
    alt = brand.guideline_chunks[-1]
    assert alt.model_dump() == {
        'id': 'my-brand#law-alt',
        'source': 'my-brand.yaml',
        'section': '合規替代用語對照',
        'tag': 'law',
        'text': '「根治」→「改善外觀」；「治療」→「保養」；「保證有效」→ 刪除。',
    }


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding='utf-8')


def test_reports_broken_files_and_keeps_loading_the_others(tmp_path: Path) -> None:
    shutil.copy(BRANDS_DIR / 'selune.yaml', tmp_path / 'selune.yaml')
    write(tmp_path / 'broken.yaml', 'id: [unclosed')
    template = (BRANDS_DIR / '_template.yaml').read_text(encoding='utf-8')
    write(tmp_path / 'wrong-name.yaml', template)
    no_palette = template.replace('id: my-brand', 'id: no-palette').replace('palette:', 'colors:')
    write(tmp_path / 'no-palette.yaml', no_palette)
    no_logo = template.replace('id: my-brand', 'id: no-logo').replace('logo: null', 'logo: logo.png')
    write(tmp_path / 'no-logo.yaml', no_logo)
    loaded, errors = load_brands(tmp_path)
    assert [b.brand.id for b in loaded] == ['selune']
    messages = {e.file: e.message for e in errors}
    assert set(messages) == {'broken.yaml', 'wrong-name.yaml', 'no-palette.yaml', 'no-logo.yaml'}
    assert 'YAML' in messages['broken.yaml']
    assert messages['wrong-name.yaml'] == '檔名必須與 id 相同（id 為 my-brand）'
    assert 'palette' in messages['no-palette.yaml']
    assert messages['no-logo.yaml'] == 'Logo 圖檔不存在：logo.png'


def test_logo_and_style_images_resolve_inside_the_brands_folder(tmp_path: Path) -> None:
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets' / 'logo.png').write_bytes(b'\x89PNG')
    (tmp_path / 'assets' / 'mood.jpg').write_bytes(b'\xff\xd8')
    template = (BRANDS_DIR / '_template.yaml').read_text(encoding='utf-8')
    text = template.replace('logo: null', 'logo: assets/logo.png')
    write(tmp_path / 'my-brand.yaml', text.replace('styleImages: []', 'styleImages: [assets/mood.jpg]'))
    escape = template.replace('id: my-brand', 'id: escape').replace('logo: null', 'logo: ../x.png')
    write(tmp_path / 'escape.yaml', escape)
    loaded, errors = load_brands(tmp_path)
    assert [e.message for e in errors] == ['Logo 圖檔必須放在 brands/ 資料夾內：../x.png']
    b = loaded[0]
    assert b.brand.logo is not None
    assert b.brand.logo.url == '/files/brands/assets/logo.png'
    assert b.logo_path == tmp_path / 'assets' / 'logo.png'
    assert b.style_images == [tmp_path / 'assets' / 'mood.jpg']
    assert len(b.source_hash) == 64
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `uv run pytest tests/test_brands.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.brands'`。

- [ ] **Step 4: 建立 `brands/selune.yaml`**

```yaml
# 示範品牌 SÉLUNE 晞月（美妝保養）。欄位說明見 _template.yaml。
id: selune
name: SÉLUNE 晞月
category: 美妝保養
ciVersion: v2.3
palette: {primary: '#B76E79', secondary: '#F6EFE9', accent: '#C9A96E', ink: '#3A3335'}
fonts: {headline: Noto Serif TC, body: Noto Sans TC}
visualStyle: serene luxury skincare, crescent moon halo, aurora light ribbons, pearl-gold bokeh, soft diffused studio light
defaultTone: gentle
rules:
  maxDeltaE: 5
  minWhitespace: 0.3
  productRatio: [0.2, 0.5]
bannedWords: [根治, 治療, 醫療級, 消炎, 保證有效, 永久]
replacements: {根治: 改善外觀, 治療: 保養, 醫療級: 專業配方, 消炎: 舒緩, 保證有效: '', 永久: 持久}
claimWords: [感受, 透亮, 修護, 淡化, 改善, 鎖水]
disclaimerPhrase: 效果因個人膚況而異
copyPresets:
  gentle:
    headline: [一夜溫柔修護, 醒來透亮發光]
    subhead: 7天感受透亮光采・專業修護配方*
  science:
    headline: [5重玻尿酸, 72H 長效鎖水]
    subhead: 神經醯胺 × 5重玻尿酸｜科學配比深層保濕*
  playful:
    headline: [熬夜也不怕, 肌膚喝飽水！]
    subhead: 水潤透亮一起帶走，買一送一只到月底*
  minimal:
    headline: [少即是多, 純粹修護]
    subhead: 5重玻尿酸・無香精・敏感肌適用*
guidelines:
- {key: color, source: brand_guideline_v2.3.pdf, section: §2.1 色彩系統, tag: color, text: 品牌主色「晞月玫瑰」#B76E79，輔助色「月光米白」#F6EFE9、點綴色「珍珠金」#C9A96E、文字「墨灰」#3A3335。主色色差需控制在 ΔE2000 ≤ 5，禁止使用高飽和桃紅與螢光色系。}
- {key: logo, source: brand_guideline_v2.3.pdf, section: §3.4 Logo 使用規範, tag: logo, text: Logo 四周需保留至少 0.5 倍 Logo 高度之淨空區，不得與標題、商品或其他元素重疊；建議置於左上角網格起點。}
- {key: law, source: compliance_cosmetics_tw.md, section: 化粧品衛生安全管理法 §10, tag: law, text: 化粧品之標示、宣傳及廣告不得有虛偽或誇大之情事，且不得宣稱醫療效能。禁用詞例：根治、治療、醫療級、消炎、保證有效、永久。含效果宣稱時應加註「效果因個人膚況而異」。}
- {key: layout, source: layout_style_guide.pdf, section: §1.2 海報版型, tag: layout, text: 標題靠左對齊 8 欄網格；商品主體佔畫面 20–50%；整體留白 ≥ 30%；促銷徽章置於商品左側。}
- {key: font, source: brand_guideline_v2.3.pdf, section: §4.1 字型, tag: font, text: 標題使用 Noto Serif TC Bold，內文使用 Noto Sans TC；標題最多兩行，第二行可使用主色強調。}
- {key: history, source: campaign_history/2025_anniversary.json, section: 2025 週年慶素材成效, tag: history, text: 去年週年慶高互動素材特徵：柔光漸層背景、水波紋與珍珠金點綴，文案以「修護」「透亮」為主軸，平均 CTR 4.2%。}
- {key: law-alt, source: compliance_cosmetics_tw.md, section: 合規替代用語對照, tag: law, text: 「根治」→「改善外觀」；「醫療級」→「專業配方」；「治療」→「保養」；「保證有效」→ 刪除。效果宣稱句尾加註「*」，並於頁尾標示使用者感受說明。}
caseStudies:
- {id: selune-case-1, title: 2025 週年慶 IG 貼文, channel: IG 貼文, ctr: 4.2, notes: 柔光漸層 + 水波紋，文案主打修護}
- {id: selune-case-2, title: 夏季保濕電商主圖, channel: 電商主圖, ctr: 3.1, notes: 淺色背景 + 水珠，強調長效保濕}
logo: null
styleImages: []
samples:
- id: prod_selune_serum
  name: 極光玻尿酸修護精華 30ml
  features: [5重玻尿酸, 神經醯胺, 無香精, 敏感肌適用]
  price: {sale: 1280, original: 1680}
  art: serum
  createdAt: '2026-10-01T09:00:00.000Z'
```

- [ ] **Step 5: 建立 `brands/misty-isle.yaml`**

```yaml
# 示範品牌 霧嶼咖啡 MISTY ISLE（冷萃咖啡）。欄位說明見 _template.yaml。
id: misty-isle
name: 霧嶼咖啡 MISTY ISLE
category: 冷萃咖啡
ciVersion: v1.4
palette: {primary: '#2F4A44', secondary: '#EEF0EC', accent: '#C8A27A', ink: '#1F2624'}
fonts: {headline: Noto Serif TC, body: Noto Sans TC}
visualStyle: minimal Japanese cafe aesthetic, morning mist, matte ceramic surface, soft window light, clean geometric shadows
defaultTone: minimal
rules:
  maxDeltaE: 5
  minWhitespace: 0.4
  productRatio: [0.2, 0.5]
bannedWords: [治療, 保證, 減肥, 瘦身, 降血壓, 醫療, 根治]
replacements: {治療: 舒緩, 保證: '', 減肥: 輕盈, 瘦身: 輕盈, 降血壓: '', 醫療: '', 根治: ''}
claimWords: []
disclaimerPhrase: ''
copyPresets:
  minimal:
    headline: [一口清醒, 慢萃十八小時]
    subhead: 單一產區耶加雪菲・低溫冷萃 18 小時
  gentle:
    headline: [把早晨, 留給自己]
    subhead: 低酸順口・冷藏即飲
  science:
    headline: [18H 低溫萃取, 每瓶 120mg 咖啡因]
    subhead: 單一產區・無添加糖・冷鏈配送
  playful:
    headline: [冰冰的, 剛剛好！]
    subhead: 買二送一，辦公室續命必備
guidelines:
- {key: color, source: misty_isle_ci_v1.4.pdf, section: §2 色彩, tag: color, text: 品牌主色「霧林綠」#2F4A44，輔助色「晨霧白」#EEF0EC、點綴色「牛皮紙棕」#C8A27A。整體低飽和，主色色差 ΔE2000 ≤ 5，避免高彩度藍綠與螢光色。}
- {key: logo, source: misty_isle_ci_v1.4.pdf, section: §3 Logo, tag: logo, text: Logo 淨空區至少 0.5 倍 Logo 高度；深色背景使用反白 Logo。}
- {key: law, source: compliance_food_tw.md, section: 食品安全衛生管理法 §28, tag: law, text: 食品之標示、宣傳或廣告不得有不實、誇張或易生誤解之情形，亦不得宣稱醫療效能。禁用詞例：治療、減肥、瘦身、降血壓、保證。}
- {key: layout, source: misty_isle_ci_v1.4.pdf, section: §5 簡約版型, tag: layout, text: 留白 ≥ 40%，畫面只用一個主色；標題最多兩行，商品置於視覺重心。}
- {key: font, source: misty_isle_ci_v1.4.pdf, section: §4 字型, tag: font, text: 標題 Noto Serif TC，字距略寬；內文 Noto Sans TC Regular。}
- {key: history, source: campaign_history/2025_summer_coldbrew.json, section: 2025 夏季冷萃素材成效, tag: history, text: 霧面陶瓷桌面 + 晨光側光的素材互動最佳，平均 CTR 3.8%；簡約文案優於促銷導向文案。}
- {key: law-alt, source: compliance_food_tw.md, section: 合規替代用語對照, tag: law, text: 「治療疲勞」→ 刪除；「保證提神」→「一口清醒」；「減肥」「瘦身」→「輕盈無負擔」。}
caseStudies:
- {id: misty-case-1, title: 2025 夏季冷萃 IG 貼文, channel: IG 貼文, ctr: 3.8, notes: 霧面陶瓷 + 晨光側光}
logo: null
styleImages: []
samples:
- id: prod_misty_coldbrew
  name: 單一產區冷萃咖啡 330ml
  features: [18小時冷萃, 單一產區, 無添加糖, 低酸順口]
  price: {sale: 120, original: 150}
  art: coldbrew
  createdAt: '2026-10-01T09:00:00.000Z'
```

- [ ] **Step 6: 建立 `brands/_template.yaml`**

```yaml
# 品牌設定檔範本：複製成 brands/<品牌 id>.yaml 再修改內容。
# - 檔名必須與 id 相同，id 只能用小寫英文、數字與連字號
# - 以底線開頭的檔案（例如本檔）不會被匯入
# - 修改後重新啟動後端：docker compose restart api worker
# - 含「#」或「: 」的文字要用引號括起來（YAML 會把「 #」後面當成註解）

id: my-brand
name: 我的品牌
category: 美妝保養
ciVersion: v1.0

# 品牌色票：主色、輔助色、點綴色、文字色（#RRGGBB）
palette: {primary: '#8A5A44', secondary: '#F5EFE8', accent: '#C8A27A', ink: '#2B2522'}

# 目前只支援 Noto Serif TC 與 Noto Sans TC
fonts: {headline: Noto Serif TC, body: Noto Sans TC}

# 生圖時的品牌視覺風格（英文，直接放進 positive prompt）
visualStyle: warm minimal product photography, natural linen texture, soft morning light

# 預設語氣：gentle（溫柔療癒）、science（專業科研）、playful（活潑年輕）、minimal（簡約）
defaultTone: gentle

# 審查門檻：主色色差 ΔE2000 上限、最少留白比例、商品主體佔比（最小、最大）
rules: {maxDeltaE: 5, minWhitespace: 0.3, productRatio: [0.2, 0.5]}

# 禁用詞與合規替代用語（替代詞為空字串代表直接刪除）
bannedWords: [根治, 治療, 保證有效]
replacements: {根治: 改善外觀, 治療: 保養, 保證有效: ''}

# 出現這些詞視為效果宣稱，頁尾會加上 disclaimerPhrase；不需要時兩者都留空（claimWords: []、disclaimerPhrase: ''）
claimWords: [修護, 改善]
disclaimerPhrase: 效果因個人膚況而異

# 四種語氣的文案範例（標題兩行、副標），四種都要填
copyPresets:
  gentle: {headline: [溫柔呵護, 每一天], subhead: 天然成分・溫和配方}
  science: {headline: [科學配方, 看得見的改變], subhead: 專利成分・臨床測試}
  playful: {headline: [今天也要, 閃閃發光！], subhead: 限時優惠，手刀搶購}
  minimal: {headline: [簡單, 就是美], subhead: 純粹成分・無多餘添加}

# CI 規範切塊（RAG 檢索用）。key 在品牌內不可重複；tag 為 color、logo、law、layout、font、history 或 general。
# 沒有 key 為 law-alt 的切塊時，會依 replacements 自動產生「合規替代用語對照」（只在 Query Rewriting 時檢索）。
guidelines:
  - {key: color, source: brand_guideline.pdf, section: 色彩, tag: color, text: '品牌主色 #8A5A44，主色色差需控制在 ΔE2000 ≤ 5。'}
  - {key: logo, source: brand_guideline.pdf, section: Logo, tag: logo, text: Logo 四周保留至少 0.5 倍 Logo 高度的淨空區。}
  - {key: law, source: compliance.md, section: 廣告法規, tag: law, text: 不得宣稱醫療效能。禁用詞例：根治、治療、保證有效。}
  - {key: layout, source: brand_guideline.pdf, section: 版型, tag: layout, text: 商品主體佔畫面 20–50%，整體留白至少 30%。}

# 歷史優秀案例（ctr 為百分比，例如 3.5）
caseStudies: []

# Logo 圖檔（相對於 brands/，例如 assets/my-brand-logo.png）；沒有時填 null
logo: null

# IP-Adapter 參考圖（相對於 brands/），生圖時參考的品牌風格
styleImages: []
```

- [ ] **Step 7: 建立 `backend/app/brands.py`**

```python
"""品牌設定檔（brands/*.yaml）：驗證後轉成合約的 Brand 與示範商品。

- 檔名必須與 id 相同；以底線開頭的檔案（_template.yaml）不匯入。
- 某個檔案有錯時只略過那個品牌，錯誤會顯示在系統狀態。
- 沒有 key 為 law-alt 的切塊時，依替代用語表自動產生「合規替代用語對照」。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError, field_validator

from app.contract import (
    Brand,
    BrandLogo,
    BrandRules,
    CaseStudy,
    CopyPreset,
    Fonts,
    Model,
    Palette,
    Price,
    Product,
    RagChunk,
    RagTag,
    SamplePhoto,
    Tone,
)

TONES: tuple[Tone, ...] = ('gentle', 'science', 'playful', 'minimal')


class GuidelineConfig(Model):
    key: str
    source: str
    section: str
    tag: RagTag
    text: str


class SampleConfig(Model):
    id: str
    name: str
    features: list[str]
    price: Price
    art: Literal['serum', 'coldbrew']
    created_at: str


class BrandConfig(Model):
    id: str = Field(pattern=r'^[a-z0-9]+(-[a-z0-9]+)*$')
    name: str
    category: str
    ci_version: str
    palette: Palette
    fonts: Fonts
    visual_style: str
    default_tone: Tone
    rules: BrandRules
    banned_words: list[str]
    replacements: dict[str, str]
    claim_words: list[str]
    disclaimer_phrase: str
    copy_presets: dict[Tone, CopyPreset]
    guidelines: list[GuidelineConfig]
    case_studies: list[CaseStudy] = []
    logo: str | None = None
    style_images: list[str] = []
    samples: list[SampleConfig] = []

    @field_validator('copy_presets')
    @classmethod
    def _every_tone(cls, presets: dict[Tone, CopyPreset]) -> dict[Tone, CopyPreset]:
        missing = [t for t in TONES if t not in presets]
        if missing:
            raise ValueError(f'缺少語氣：{"、".join(missing)}')
        return presets

    @field_validator('guidelines')
    @classmethod
    def _unique_keys(cls, guidelines: list[GuidelineConfig]) -> list[GuidelineConfig]:
        keys = [g.key for g in guidelines]
        duplicated = sorted({k for k in keys if keys.count(k) > 1})
        if duplicated:
            raise ValueError(f'key 重複：{"、".join(duplicated)}')
        return guidelines


@dataclass(frozen=True)
class LoadedBrand:
    brand: Brand
    samples: list[Product]
    logo_path: Path | None
    style_images: list[Path]
    #: 設定檔內容的 SHA-256；改變時重新寫入切塊
    source_hash: str


@dataclass(frozen=True)
class BrandLoadError:
    file: str
    message: str


class BrandFileError(Exception):
    pass


def load_brands(directory: Path) -> tuple[list[LoadedBrand], list[BrandLoadError]]:
    loaded: list[LoadedBrand] = []
    errors: list[BrandLoadError] = []
    for path in sorted(directory.glob('*.yaml')):
        if path.name.startswith('_'):
            continue
        try:
            item = _load_file(directory, path)
        except BrandFileError as e:
            errors.append(BrandLoadError(path.name, str(e)))
            continue
        loaded.append(item)
    return loaded, errors


def _load_file(directory: Path, path: Path) -> LoadedBrand:
    raw = path.read_bytes()
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise BrandFileError(f'YAML 格式錯誤：{e}') from e
    try:
        cfg = BrandConfig.model_validate(data)
    except ValidationError as e:
        raise BrandFileError(_describe(e)) from e
    if cfg.id != path.stem:
        raise BrandFileError(f'檔名必須與 id 相同（id 為 {cfg.id}）')

    logo_path = _inside(directory, cfg.logo, 'Logo 圖檔') if cfg.logo else None
    style_images = [_inside(directory, p, '參考圖') for p in cfg.style_images]
    alt = _alt_guideline(cfg, path.name)
    guidelines = [*cfg.guidelines, *([alt] if alt else [])]

    brand = Brand(
        id=cfg.id,
        name=cfg.name,
        category=cfg.category,
        ci_version=cfg.ci_version,
        palette=cfg.palette,
        fonts=cfg.fonts,
        visual_style=cfg.visual_style,
        default_tone=cfg.default_tone,
        rules=cfg.rules,
        banned_words=cfg.banned_words,
        replacements=cfg.replacements,
        claim_words=cfg.claim_words,
        disclaimer_phrase=cfg.disclaimer_phrase,
        guideline_chunks=[
            RagChunk(id=f'{cfg.id}#{g.key}', source=g.source, section=g.section, tag=g.tag, text=g.text)
            for g in guidelines
        ],
        case_studies=cfg.case_studies,
        copy_presets=cfg.copy_presets,
        logo=BrandLogo(url=f'/files/brands/{Path(cfg.logo).as_posix()}') if cfg.logo else None,
    )
    samples = [
        Product(
            id=s.id,
            brand_id=cfg.id,
            name=s.name,
            features=s.features,
            price=s.price,
            photo=SamplePhoto(source='sample', art=s.art),
            cutout=None,
            created_at=s.created_at,
        )
        for s in cfg.samples
    ]
    return LoadedBrand(brand, samples, logo_path, style_images, hashlib.sha256(raw).hexdigest())


def _describe(error: ValidationError) -> str:
    return '；'.join(f'{".".join(str(p) for p in e["loc"])}：{e["msg"]}' for e in error.errors())


def _inside(directory: Path, relative: str, what: str) -> Path:
    """相對於 brands/ 的檔案；不可跳出資料夾。"""
    path = directory / relative
    if not path.resolve().is_relative_to(directory.resolve()):
        raise BrandFileError(f'{what}必須放在 brands/ 資料夾內：{relative}')
    if not path.is_file():
        raise BrandFileError(f'{what}不存在：{relative}')
    return path


def _alt_guideline(cfg: BrandConfig, file_name: str) -> GuidelineConfig | None:
    if not cfg.replacements or any(g.key == 'law-alt' for g in cfg.guidelines):
        return None
    pairs = [f'「{word}」→「{alt}」' if alt else f'「{word}」→ 刪除' for word, alt in cfg.replacements.items()]
    return GuidelineConfig(
        key='law-alt', source=file_name, section='合規替代用語對照', tag='law', text='；'.join(pairs) + '。'
    )
```

- [ ] **Step 8: 執行測試確認通過**

Run: `uv run pytest -q`
Expected: PASS，13 passed（`test_brands.py` 4 個）。

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: 沒有錯誤。

- [ ] **Step 9: Commit**

```bash
git add \
  backend/app/brands.py \
  backend/tests/fixtures.py \
  backend/tests/test_brands.py \
  brands/_template.yaml \
  brands/misty-isle.yaml \
  brands/selune.yaml
git commit -m "feat: load brands from YAML config files" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: PostgreSQL、Alembic 與品牌、切塊、商品的資料存取


**Files:**
- Create: `docker-compose.yml`、`backend/.python-version`、`backend/alembic.ini`、`backend/migrations/env.py`、`backend/migrations/script.py.mako`、`backend/migrations/versions/0001_initial_schema.py`、`backend/app/settings.py`、`backend/app/core/clock.py`、`backend/app/db/__init__.py`、`backend/app/db/models.py`、`backend/app/db/session.py`、`backend/app/repo/__init__.py`、`backend/app/repo/catalog.py`
- Modify: `backend/pyproject.toml`、`backend/app/contract.py`
- Test: `backend/tests/conftest.py`、`backend/tests/test_catalog.py`

**Interfaces:**
- Consumes：Task 5 的 `LoadedBrand`
- Produces：
  - `docker-compose.yml`：postgres（`127.0.0.1:5433`）、redis（`127.0.0.1:6379`），皆有健康檢查
  - `app.settings`：
    - 設定項目：`settings.database_url`、`redis_url`、`brands_dir`、`data_dir`、`local_photos_dir`。
    - 常數：`REPO_ROOT`、`BACKEND_DIR`。
    - 設定來源：環境變數或 repo 根目錄的 `.env`。
  - `app.core.clock`：`utc_now()`、`iso(dt) -> '2026-10-07T01:02:03.456Z'`、`parse_iso(text)`
  - `app.db.models`：`BrandRow`、`BrandChunkRow`（origin：`config`、`alt`、`upload`、`history`）、`ProductRow`、`JobRow`（`last_seq`、`cancel_requested`、`failure_reason`）、`JobEventRow`（主鍵 `(job_id, seq)`）、`HistoryRow`
  - `Database(url)`：`session()`（async context manager）、`migrate()`（可在執行中的 event loop 內呼叫）、`truncate_all()`、`dispose()`
  - `app.repo.catalog`：
    - `sync_brands(session, loaded, now)`：內容雜湊改變時取代設定檔的切塊；設定檔已移除的品牌不再列出。
    - `list_brands`、`get_brand`。
    - `replace_document_chunks(session, brand_id, source, chunks, now)`。
    - `list_products(session, brand_id)`：示範商品在前。
    - `get_product`。
    - `save_product(session, draft, now)`：沒有 id 或 id 不存在時新增。
    - `delete_product`：示範商品只標記刪除。
  - `ProductDraft`（`app.contract`）
  - 測試 fixture：
    - `db`（session 範圍）：重建 `genai_test` 資料庫並執行 migration。
    - `session`：每個測試結束後清空資料表。

- [ ] **Step 1: 建立 `docker-compose.yml`**

```yaml
# 虛實整合 GenAI Agent：本機執行（所有連接埠只綁定 127.0.0.1）。ComfyUI 在 Windows 另外啟動。
# 映像檔取自 AWS 的 Docker 官方映像鏡像（public.ecr.aws/docker/library），不需要登入 Docker Hub。
name: genai-agent

services:
  postgres:
    image: public.ecr.aws/docker/library/postgres:18-alpine
    environment:
      POSTGRES_USER: genai
      POSTGRES_PASSWORD: genai
      POSTGRES_DB: genai
    # 5433：避免和 Windows 上原生安裝的 PostgreSQL（5432）衝突；容器之間仍用 postgres:5432
    ports: ['127.0.0.1:5433:5432']
    volumes: ['postgres:/var/lib/postgresql']
    healthcheck:
      test: ['CMD-SHELL', 'pg_isready -U genai -d genai']
      interval: 3s
      timeout: 3s
      retries: 30

  redis:
    image: public.ecr.aws/docker/library/redis:8-alpine
    command: ['redis-server', '--appendonly', 'yes']
    ports: ['127.0.0.1:6379:6379']
    volumes: ['redis:/data']
    healthcheck:
      test: ['CMD', 'redis-cli', 'ping']
      interval: 3s
      timeout: 3s
      retries: 30

volumes:
  postgres:
  redis:
```

- [ ] **Step 2: 啟動資料庫與佇列**

```bash
docker compose up -d --wait postgres redis
```

Expected：`Container genai-agent-postgres-1 Healthy`、`Container genai-agent-redis-1 Healthy`。

- [ ] **Step 3: 修改 `backend/pyproject.toml`**（mypy 也檢查 migrations；asyncpg 沒有型別）

找到：

```toml
[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]
files = ["app", "tests"]
```

改成：

```toml
[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]
files = ["app", "tests", "migrations"]

[[tool.mypy.overrides]]
module = ["asyncpg", "asyncpg.*"]
ignore_missing_imports = true
```

- [ ] **Step 4: 建立 `backend/.python-version`**

```text
3.13
```

- [ ] **Step 5: 建立 `backend/tests/conftest.py`**（先寫失敗測試）

```python
"""資料庫測試需要 docker compose 的 postgres（docker compose up -d postgres redis）。

每次測試開始時重建 genai_test 資料庫並跑 migration；每個測試結束後清空所有資料表。
"""

from collections.abc import AsyncIterator

import asyncpg
import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.settings import settings

TEST_DATABASE = 'genai_test'


@pytest.fixture(scope='session')
async def db() -> AsyncIterator[Database]:
    url = make_url(settings.database_url)
    admin = await asyncpg.connect(
        user=url.username, password=url.password, host=url.host, port=url.port, database='postgres'
    )
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS {TEST_DATABASE} WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE {TEST_DATABASE}')
    finally:
        await admin.close()
    database = Database(url.set(database=TEST_DATABASE).render_as_string(hide_password=False))
    await database.migrate()
    yield database
    await database.dispose()


@pytest.fixture
async def session(db: Database) -> AsyncIterator[AsyncSession]:
    async with db.session() as s:
        yield s
    await db.truncate_all()
```

- [ ] **Step 6: 建立 `backend/tests/test_catalog.py`**

```python
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.brands import LoadedBrand, load_brands
from app.contract import FilePhoto, Price, ProductDraft, RagChunk
from app.repo import catalog
from tests.fixtures import BRANDS_DIR, load_fixture

T0 = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 7, 2, 0, tzinfo=UTC)


def demo_brands() -> list[LoadedBrand]:
    loaded, errors = load_brands(BRANDS_DIR)
    assert errors == []
    return loaded


def draft(name: str, product_id: str | None = None) -> ProductDraft:
    return ProductDraft(
        id=product_id,
        brand_id='selune',
        name=name,
        features=['保濕'],
        price=Price(sale=680, original=880),
        photo=FilePhoto(source='upload', url='/files/products/x.png'),
        cutout=None,
    )


async def test_syncs_brands_from_config_files(session: AsyncSession) -> None:
    await catalog.sync_brands(session, demo_brands(), T0)
    fixture = sorted(load_fixture('brands.json')['brands'], key=lambda b: b['id'])
    assert [b.to_json() for b in await catalog.list_brands(session)] == fixture
    assert (await catalog.get_brand(session, 'selune')) is not None
    assert (await catalog.get_brand(session, 'nope')) is None


async def test_resyncing_replaces_config_chunks_and_hides_removed_brands(session: AsyncSession) -> None:
    loaded = demo_brands()
    await catalog.sync_brands(session, loaded, T0)
    selune = next(b for b in loaded if b.brand.id == 'selune')
    color = selune.brand.guideline_chunks[0].model_copy(update={'text': '主色改為 #A0566A。'})
    changed = LoadedBrand(
        brand=selune.brand.model_copy(update={'guideline_chunks': [color]}),
        samples=selune.samples,
        logo_path=None,
        style_images=[],
        source_hash='changed',
    )
    await catalog.sync_brands(session, [changed], T1)
    brands = await catalog.list_brands(session)
    assert [b.id for b in brands] == ['selune']
    assert [c.text for c in brands[0].guideline_chunks] == ['主色改為 #A0566A。']


async def test_uploaded_chunks_follow_the_config_chunks_and_replace_by_source(session: AsyncSession) -> None:
    await catalog.sync_brands(session, demo_brands(), T0)

    def chunk(n: int) -> RagChunk:
        return RagChunk(
            id=f'selune#doc-abc-{n}', source='ci_update.md', section='色彩更新', tag='color', text=f'第 {n} 塊'
        )

    await catalog.replace_document_chunks(session, 'selune', 'ci_update.md', [chunk(1), chunk(2)], T0)
    await catalog.replace_document_chunks(session, 'selune', 'ci_update.md', [chunk(3)], T1)
    brand = await catalog.get_brand(session, 'selune')
    assert brand is not None
    assert [c.id for c in brand.guideline_chunks][-2:] == ['selune#law-alt', 'selune#doc-abc-3']


async def test_lists_samples_first_and_keeps_deleted_samples_out(session: AsyncSession) -> None:
    await catalog.sync_brands(session, demo_brands(), T0)
    assert [p.id for p in await catalog.list_products(session, 'selune')] == ['prod_selune_serum']

    created = await catalog.save_product(session, draft('晚安面膜'), T0)
    assert created.id.startswith('prod_')
    assert created.created_at == '2026-10-07T01:00:00.000Z'
    updated = await catalog.save_product(session, draft('晚安面膜 50ml', created.id), T1)
    assert (updated.name, updated.created_at) == ('晚安面膜 50ml', '2026-10-07T01:00:00.000Z')
    names = [p.name for p in await catalog.list_products(session, 'selune')]
    assert names == ['極光玻尿酸修護精華 30ml', '晚安面膜 50ml']

    assert await catalog.delete_product(session, 'prod_selune_serum')
    assert await catalog.delete_product(session, created.id)
    assert not await catalog.delete_product(session, created.id)
    await catalog.sync_brands(session, demo_brands(), T1)
    assert await catalog.list_products(session, 'selune') == []
    assert await catalog.get_product(session, 'prod_selune_serum') is None
    assert [p.id for p in await catalog.list_products(session, 'misty-isle')] == ['prod_misty_coldbrew']
```

- [ ] **Step 7: 執行測試確認失敗**

Run: `uv run pytest tests/test_catalog.py -q`
Expected: FAIL，`ImportError while loading conftest`：`ModuleNotFoundError: No module named 'app.db'`。

- [ ] **Step 8: 修改 `backend/app/contract.py`**（新增 `ProductDraft`）

找到：

```python
    photo: ProductPhoto
    cutout: ProductCutout | None
    created_at: str


class ChannelTemplate(Model):
```

改成：

```python
    photo: ProductPhoto
    cutout: ProductCutout | None
    created_at: str


class ProductDraft(Model):
    """新增或修改商品（對應 web/src/lib/api/client.ts 的 ProductDraft：沒有 id 時新增）。"""

    id: str | None = None
    brand_id: str
    name: str
    features: list[str]
    price: Price
    photo: ProductPhoto
    cutout: ProductCutout | None


class ChannelTemplate(Model):
```

- [ ] **Step 9: 建立 `backend/app/settings.py`**

```python
"""後端設定：環境變數（或 repo 根目錄的 .env）覆寫預設值。

預設值對應本機開發：docker compose 的 postgres 在 5433；用 127.0.0.1 而不是 localhost
（Windows 會先嘗試 IPv6 的 ::1，連不上要等約 2 秒才改用 IPv4）。
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / '.env', extra='ignore')

    database_url: str = 'postgresql+asyncpg://genai:genai@127.0.0.1:5433/genai'
    redis_url: str = 'redis://127.0.0.1:6379/0'
    brands_dir: Path = REPO_ROOT / 'brands'
    #: 商品照、去背圖、生成圖、審查用海報
    data_dir: Path = REPO_ROOT / 'data'
    #: 使用者自己的商品照（唯讀）
    local_photos_dir: Path = REPO_ROOT / 'assets' / 'products'


settings = Settings()
```

- [ ] **Step 10: 建立 `backend/app/core/clock.py`**

```python
"""時間：一律 UTC；字串格式與 JavaScript 的 Date.toISOString() 相同（毫秒、結尾 Z）。"""

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    """2026-10-07T01:02:03.456Z"""
    u = dt.astimezone(UTC)
    return u.strftime('%Y-%m-%dT%H:%M:%S.') + f'{u.microsecond // 1000:03d}Z'


def parse_iso(text: str) -> datetime:
    return datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(UTC)
```

- [ ] **Step 11: 建立 `backend/app/db/__init__.py`**（空檔）

```python

```

- [ ] **Step 12: 建立 `backend/app/db/models.py`**

```python
"""資料表：合約物件整份存成 JSONB（data），另外拆出查詢用的欄位。"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Json = dict[str, Any]


class Base(DeclarativeBase):
    type_annotation_map = {Json: JSONB, datetime: DateTime(timezone=True)}


class BrandRow(Base):
    """品牌設定檔匯入的內容（guidelineChunks 另存在 brand_chunks）。"""

    __tablename__ = 'brands'

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    config: Mapped[Json]
    source_hash: Mapped[str]
    #: 設定檔已移除的品牌保留資料列（任務與歷史紀錄仍會參照），但不再列出
    active: Mapped[bool] = mapped_column(Boolean, server_default=false())
    updated_at: Mapped[datetime]


class BrandChunkRow(Base):
    """RAG 切塊。origin：config（設定檔）、alt（合規替代用語）、upload（上傳的手冊）、history（選定海報回寫）。"""

    __tablename__ = 'brand_chunks'

    id: Mapped[str] = mapped_column(String, primary_key=True)
    brand_id: Mapped[str] = mapped_column(ForeignKey('brands.id', ondelete='CASCADE'), index=True)
    source: Mapped[str]
    section: Mapped[str]
    tag: Mapped[str]
    text: Mapped[str] = mapped_column(Text)
    origin: Mapped[str]
    #: 同一來源內的順序
    position: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime]


class ProductRow(Base):
    __tablename__ = 'products'

    id: Mapped[str] = mapped_column(String, primary_key=True)
    brand_id: Mapped[str] = mapped_column(ForeignKey('brands.id'), index=True)
    data: Mapped[Json]
    #: 品牌設定檔的示範商品；刪除時只標記 deleted，重新匯入設定檔也不會加回
    sample: Mapped[bool] = mapped_column(Boolean, server_default=false())
    deleted: Mapped[bool] = mapped_column(Boolean, server_default=false())
    created_at: Mapped[datetime]


class JobRow(Base):
    __tablename__ = 'jobs'

    id: Mapped[str] = mapped_column(String, primary_key=True)
    brand_id: Mapped[str] = mapped_column(String, index=True)
    input: Mapped[Json]
    created_at: Mapped[datetime] = mapped_column(index=True)
    stage: Mapped[str]
    round: Mapped[int] = mapped_column(Integer, server_default='0')
    finished: Mapped[bool] = mapped_column(Boolean, server_default=false())
    best_render_ids: Mapped[Json] = mapped_column(server_default='{}')
    #: 最後一則事件的序號（新增事件時在同一交易內加 1）
    last_seq: Mapped[int] = mapped_column(Integer, server_default='0')
    cancel_requested: Mapped[bool] = mapped_column(Boolean, server_default=false())
    failure_reason: Mapped[str | None] = mapped_column(Text)


class JobEventRow(Base):
    __tablename__ = 'job_events'

    job_id: Mapped[str] = mapped_column(ForeignKey('jobs.id', ondelete='CASCADE'), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime]
    type: Mapped[str]
    #: 事件 JSON（不含 seq、ts）
    payload: Mapped[Json]


class HistoryRow(Base):
    __tablename__ = 'history'

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('jobs.id', ondelete='CASCADE'))
    brand_id: Mapped[str] = mapped_column(String, index=True)
    data: Mapped[Json]
    selected_at: Mapped[datetime] = mapped_column(index=True)
```

- [ ] **Step 13: 建立 `backend/app/db/session.py`**

```python
"""資料庫連線：api 與 worker 各建立一個 Database；測試另外指向測試資料庫。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base
from app.settings import BACKEND_DIR


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True)
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._sessions() as session:
            yield session

    async def migrate(self) -> None:
        """alembic upgrade head（共用目前的連線，可在執行中的 event loop 內呼叫）。"""

        def upgrade(connection: Connection) -> None:
            config = Config(str(BACKEND_DIR / 'alembic.ini'))
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')

        async with self.engine.begin() as connection:
            await connection.run_sync(upgrade)

    async def truncate_all(self) -> None:
        """測試用：清空所有資料表。"""
        tables = ', '.join(t.name for t in Base.metadata.sorted_tables)
        async with self.engine.begin() as connection:
            await connection.execute(text(f'TRUNCATE {tables} CASCADE'))

    async def dispose(self) -> None:
        await self.engine.dispose()
```

- [ ] **Step 14: 建立 `backend/alembic.ini`**（只能有 ASCII）

```ini
[alembic]
script_location = %(here)s/migrations
prepend_sys_path = .
path_separator = os

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 15: 建立 `backend/migrations/env.py`**

```python
"""Alembic：資料表定義來自 app.db.models，網址來自 app.settings。

Database.migrate() 會把連線放在 config.attributes['connection']，在執行中的 event loop 內直接使用；
命令列（uv run alembic upgrade head）則自行建立連線。
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.models import Base
from app.settings import settings

config = context.config
if config.config_file_name is not None and 'connection' not in config.attributes:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_with_own_engine() -> None:
    engine = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif 'connection' in config.attributes:
    run(config.attributes['connection'])
else:
    asyncio.run(run_with_own_engine())
```

- [ ] **Step 16: 建立 `backend/migrations/script.py.mako`**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """Upgrade schema."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Downgrade schema."""
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 17: 建立 `backend/migrations/versions/0001_initial_schema.py`**

```python
"""initial schema

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'brands',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('source_hash', sa.String(), nullable=False),
        sa.Column('active', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'jobs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('brand_id', sa.String(), nullable=False),
        sa.Column('input', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('stage', sa.String(), nullable=False),
        sa.Column('round', sa.Integer(), server_default='0', nullable=False),
        sa.Column('finished', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('best_render_ids', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('last_seq', sa.Integer(), server_default='0', nullable=False),
        sa.Column('cancel_requested', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_jobs_brand_id'), 'jobs', ['brand_id'], unique=False)
    op.create_index(op.f('ix_jobs_created_at'), 'jobs', ['created_at'], unique=False)
    op.create_table(
        'brand_chunks',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('brand_id', sa.String(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('section', sa.String(), nullable=False),
        sa.Column('tag', sa.String(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('origin', sa.String(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_brand_chunks_brand_id'), 'brand_chunks', ['brand_id'], unique=False)
    op.create_table(
        'history',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('brand_id', sa.String(), nullable=False),
        sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('selected_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_history_brand_id'), 'history', ['brand_id'], unique=False)
    op.create_index(op.f('ix_history_selected_at'), 'history', ['selected_at'], unique=False)
    op.create_table(
        'job_events',
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('job_id', 'seq'),
    )
    op.create_table(
        'products',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('brand_id', sa.String(), nullable=False),
        sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('sample', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['brand_id'], ['brands.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_products_brand_id'), 'products', ['brand_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_products_brand_id'), table_name='products')
    op.drop_table('products')
    op.drop_table('job_events')
    op.drop_index(op.f('ix_history_selected_at'), table_name='history')
    op.drop_index(op.f('ix_history_brand_id'), table_name='history')
    op.drop_table('history')
    op.drop_index(op.f('ix_brand_chunks_brand_id'), table_name='brand_chunks')
    op.drop_table('brand_chunks')
    op.drop_index(op.f('ix_jobs_created_at'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_brand_id'), table_name='jobs')
    op.drop_table('jobs')
    op.drop_table('brands')
```

- [ ] **Step 18: 建立 `backend/app/repo/__init__.py`**（空檔）

```python

```

- [ ] **Step 19: 建立 `backend/app/repo/catalog.py`**

```python
"""品牌、RAG 切塊與商品。"""

import secrets
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import case, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.brands import LoadedBrand
from app.contract import Brand, Product, ProductDraft, RagChunk
from app.core.clock import iso, parse_iso
from app.db.models import BrandChunkRow, BrandRow, ProductRow

#: 列出切塊的順序：設定檔、合規替代用語、上傳的手冊、回寫的歷史案例
_ORIGIN_ORDER = case(
    {'config': 0, 'alt': 1, 'upload': 2, 'history': 3},
    value=BrandChunkRow.origin,
)


async def sync_brands(session: AsyncSession, loaded: Sequence[LoadedBrand], now: datetime) -> None:
    """品牌設定檔 → 資料庫。內容改變時取代設定檔的切塊；補上還沒有的示範商品（刪除過的不再加回）；
    設定檔已移除的品牌不再列出。"""
    rows = {row.id: row for row in (await session.scalars(select(BrandRow))).all()}
    for item in loaded:
        brand = item.brand
        row = rows.get(brand.id)
        if row is None:
            row = BrandRow(id=brand.id, source_hash='')
            session.add(row)
        row.active = True
        if row.source_hash == item.source_hash:
            continue
        config = brand.to_json()
        config['guidelineChunks'] = []
        row.name, row.config, row.source_hash, row.updated_at = brand.name, config, item.source_hash, now
        await session.flush()
        await session.execute(
            delete(BrandChunkRow).where(BrandChunkRow.brand_id == brand.id, BrandChunkRow.origin.in_(('config', 'alt')))
        )
        for i, c in enumerate(brand.guideline_chunks):
            origin = 'alt' if c.id.endswith('#law-alt') else 'config'
            session.add(_chunk_row(brand.id, c, origin, i, now))
        for product in item.samples:
            if await session.get(ProductRow, product.id) is None:
                session.add(
                    ProductRow(
                        id=product.id,
                        brand_id=brand.id,
                        data=product.to_json(),
                        sample=True,
                        deleted=False,
                        created_at=parse_iso(product.created_at),
                    )
                )
    active = [b.brand.id for b in loaded]
    await session.execute(update(BrandRow).where(BrandRow.id.not_in(active)).values(active=False))
    await session.commit()


def _chunk_row(brand_id: str, chunk: RagChunk, origin: str, position: int, now: datetime) -> BrandChunkRow:
    return BrandChunkRow(
        id=chunk.id,
        brand_id=brand_id,
        source=chunk.source,
        section=chunk.section,
        tag=chunk.tag,
        text=chunk.text,
        origin=origin,
        position=position,
        created_at=now,
    )


async def _chunks(session: AsyncSession, brand_id: str) -> list[RagChunk]:
    rows = await session.scalars(
        select(BrandChunkRow)
        .where(BrandChunkRow.brand_id == brand_id)
        .order_by(_ORIGIN_ORDER, BrandChunkRow.created_at, BrandChunkRow.position)
    )
    return [
        RagChunk.model_validate({'id': r.id, 'source': r.source, 'section': r.section, 'tag': r.tag, 'text': r.text})
        for r in rows
    ]


async def _brand(session: AsyncSession, row: BrandRow) -> Brand:
    return Brand.model_validate(
        {**row.config, 'guidelineChunks': [c.to_json() for c in await _chunks(session, row.id)]}
    )


async def list_brands(session: AsyncSession) -> list[Brand]:
    rows = await session.scalars(select(BrandRow).where(BrandRow.active).order_by(BrandRow.id))
    return [await _brand(session, row) for row in rows.all()]


async def get_brand(session: AsyncSession, brand_id: str) -> Brand | None:
    row = await session.get(BrandRow, brand_id)
    return await _brand(session, row) if row and row.active else None


async def replace_document_chunks(
    session: AsyncSession, brand_id: str, source: str, chunks: Sequence[RagChunk], now: datetime
) -> None:
    """上傳的手冊：同名文件重新上傳時取代舊的切塊。"""
    await session.execute(
        delete(BrandChunkRow).where(
            BrandChunkRow.brand_id == brand_id, BrandChunkRow.origin == 'upload', BrandChunkRow.source == source
        )
    )
    for i, c in enumerate(chunks):
        session.add(_chunk_row(brand_id, c, 'upload', i, now))
    await session.commit()


async def list_products(session: AsyncSession, brand_id: str) -> list[Product]:
    rows = await session.scalars(
        select(ProductRow)
        .where(ProductRow.brand_id == brand_id, ProductRow.deleted.is_(False))
        .order_by(ProductRow.sample.desc(), ProductRow.created_at, ProductRow.id)
    )
    return [Product.model_validate(r.data) for r in rows]


async def get_product(session: AsyncSession, product_id: str) -> Product | None:
    row = await session.get(ProductRow, product_id)
    return Product.model_validate(row.data) if row and not row.deleted else None


async def save_product(session: AsyncSession, draft: ProductDraft, now: datetime) -> Product:
    """沒有 id（或 id 不存在）時新增；有時更新內容並保留建立時間。"""
    row = await session.get(ProductRow, draft.id) if draft.id else None
    if row is None:
        row = ProductRow(
            id=draft.id or f'prod_{secrets.token_hex(5)}', brand_id=draft.brand_id, sample=False, created_at=now
        )
        session.add(row)
    product = Product(
        id=row.id,
        brand_id=draft.brand_id,
        name=draft.name,
        features=draft.features,
        price=draft.price,
        photo=draft.photo,
        cutout=draft.cutout,
        created_at=iso(row.created_at),
    )
    row.brand_id, row.data, row.deleted = draft.brand_id, product.to_json(), False
    await session.commit()
    return product


async def delete_product(session: AsyncSession, product_id: str) -> bool:
    """示範商品只標記刪除；自建商品直接刪除。回傳是否有刪到。"""
    row = await session.get(ProductRow, product_id)
    if row is None or row.deleted:
        return False
    if row.sample:
        row.deleted = True
    else:
        await session.delete(row)
    await session.commit()
    return True
```

- [ ] **Step 20: 執行測試確認通過**

Run: `uv run pytest -q`
Expected: PASS，17 passed（`test_catalog.py` 4 個）。

Run: `uv run alembic upgrade head && uv run alembic check`
Expected: 開發用的資料庫（`genai`）建立資料表；`No new upgrade operations detected.`（模型與 migration 一致）。

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: 沒有錯誤。

- [ ] **Step 21: Commit**

```bash
git add \
  backend/.python-version \
  backend/alembic.ini \
  backend/app/contract.py \
  backend/app/core/clock.py \
  backend/app/db/__init__.py \
  backend/app/db/models.py \
  backend/app/db/session.py \
  backend/app/repo/__init__.py \
  backend/app/repo/catalog.py \
  backend/app/settings.py \
  backend/migrations/env.py \
  backend/migrations/script.py.mako \
  backend/migrations/versions/0001_initial_schema.py \
  backend/pyproject.toml \
  backend/tests/conftest.py \
  backend/tests/test_catalog.py \
  docker-compose.yml
git commit -m "feat: store brands, chunks and products in PostgreSQL with Alembic migrations" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: 事件序號、Redis 推送與任務、歷史紀錄的資料存取


**Files:**
- Create: `backend/app/errors.py`、`backend/app/events.py`、`backend/app/repo/jobs.py`、`backend/app/repo/history.py`
- Modify: `backend/app/contract.py`、`backend/tests/conftest.py`
- Test: `backend/tests/test_events.py`、`backend/tests/test_jobs.py`

**Interfaces:**
- Consumes：Task 6 的 `Database`、`JobRow`、`JobEventRow`、`HistoryRow`
- Produces：
  - `app.errors`：`AppError`（`status`、`code`、`message`）、`NotFound`（404）、`Invalid`（400）、`Conflict`（409）
  - `EventStore(db, redis)`：
    - `append(job_id, event, *, expect_stage=None) -> int | None`：
      - 鎖定任務列，取得下一個 `seq`，並更新任務摘要（stage、round、finished、best_render_ids、failure_reason）。
      - commit 後發布到 `job:{id}`。
      - `expect_stage` 與目前階段不同時不寫入，回傳 `None`。
    - `stream(job_id, after=0)`（async generator）：
      - 先訂閱 Redis，再從資料庫補送 `seq` 之後的事件，接著轉送即時事件。
      - 依 `seq` 去除重複，漏掉的事件從資料庫補齊。
      - 收到結束的 `job.status` 時停止；任務早已結束且事件都送過時立刻結束。
  - `app.events.channel(job_id)`、`is_final(message)`
  - `app.repo.jobs`：
    - `make_job_id(local_now, suffix=None)`：`job_20261005_0930_7fff`。
    - `create_job`、`list_jobs`（新到舊，最多 100 筆）、`get_job -> JobSnapshot | None`。
    - `request_cancel`（只對未結束的任務）、`cancel_requested`。
    - `get_render(session, job_id, render_id)`：由 `render.completed` 與審查事件組回候選圖。
  - `app.repo.history`：`add_history`、`list_history(session, brand_id=None)`（新到舊）、`set_favorite`
  - `JobSnapshot`（`app.contract`）
  - 測試 fixture `redis`（第 15 號資料庫，開始時清空）、`TEST_REDIS_URL`

- [ ] **Step 1: 修改 `backend/tests/conftest.py`**（Redis fixture）

找到（1／3）：

```python

import asyncpg
import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession
```

改成：

```python

import asyncpg
import pytest
from redis.asyncio import Redis
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession
```

找到（2／3）：

```python
from app.settings import settings

TEST_DATABASE = 'genai_test'


@pytest.fixture(scope='session')
```

改成：

```python
from app.settings import settings

TEST_DATABASE = 'genai_test'
#: 測試使用 Redis 的第 15 個資料庫，開始時清空
TEST_REDIS_URL = settings.redis_url.rsplit('/', 1)[0] + '/15'


@pytest.fixture(scope='session')
```

找到（3／3）：

```python
    await database.dispose()


@pytest.fixture
async def session(db: Database) -> AsyncIterator[AsyncSession]:
    async with db.session() as s:
```

改成：

```python
    await database.dispose()


@pytest.fixture(scope='session')
async def redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    await client.flushdb()
    yield client
    await client.aclose()


@pytest.fixture
async def session(db: Database) -> AsyncIterator[AsyncSession]:
    async with db.session() as s:
```

- [ ] **Step 2: 建立 `backend/tests/test_events.py`**（先寫失敗測試）

```python
import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from redis.asyncio import Redis

from app.contract import JobAcceptedEvent, JobStatusEvent, LogEvent
from app.db.session import Database
from app.errors import NotFound
from app.events import EventStore
from app.repo import jobs
from tests.test_jobs import job_input

NOW = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)


@pytest.fixture
async def store(db: Database, redis: Redis) -> AsyncIterator[EventStore]:
    async with db.session() as s:
        await jobs.create_job(s, 'job_e', job_input(), NOW)
    yield EventStore(db, redis)
    await db.truncate_all()


def status(stage: str, round: int = 0) -> JobStatusEvent:
    return JobStatusEvent.model_validate({'type': 'job.status', 'stage': stage, 'round': round})


def log(message: str) -> LogEvent:
    return LogEvent(type='log', source='api', level='info', message=message)


async def collect(stream: AsyncIterator[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m async for m in stream]


async def test_appends_consecutive_seq_and_updates_the_summary(store: EventStore, db: Database) -> None:
    assert await store.append('job_e', JobAcceptedEvent(type='job.accepted', job_id='job_e')) == 1
    assert await store.append('job_e', status('queued')) == 2
    assert await store.append('job_e', status('parsing'), expect_stage='queued') == 3
    assert await store.append('job_e', status('cancelled'), expect_stage='queued') is None
    assert await store.append('job_e', status('done', 2)) == 4
    async with db.session() as s:
        snap = await jobs.get_job(s, 'job_e')
    assert snap is not None
    assert snap.summary.model_dump(include={'stage', 'round', 'finished'}) == {
        'stage': 'done',
        'round': 2,
        'finished': True,
    }
    assert [m['seq'] for m in snap.events] == [1, 2, 3, 4]
    assert snap.events[2] == {
        'type': 'job.status',
        'stage': 'parsing',
        'round': 0,
        'seq': 3,
        'ts': snap.events[2]['ts'],
    }


async def test_concurrent_appends_never_reuse_a_seq(store: EventStore) -> None:
    seqs = await asyncio.gather(*(store.append('job_e', log(f'#{i}')) for i in range(20)))
    assert sorted(s for s in seqs if s is not None) == list(range(1, 21))


async def test_streams_stored_events_then_live_ones_until_the_job_ends(store: EventStore) -> None:
    await store.append('job_e', JobAcceptedEvent(type='job.accepted', job_id='job_e'))
    await store.append('job_e', status('queued'))
    task = asyncio.create_task(collect(store.stream('job_e', after=1)))
    await asyncio.sleep(0.2)
    await store.append('job_e', status('parsing'))
    await store.append('job_e', log('working'))
    await store.append('job_e', status('done', 1))
    messages = await asyncio.wait_for(task, 5)
    assert [(m['seq'], m['type']) for m in messages] == [
        (2, 'job.status'),
        (3, 'job.status'),
        (4, 'log'),
        (5, 'job.status'),
    ]


async def test_stream_of_a_finished_job_replays_and_ends(store: EventStore) -> None:
    for e in (JobAcceptedEvent(type='job.accepted', job_id='job_e'), status('queued'), status('failed')):
        await store.append('job_e', e)
    assert [m['seq'] for m in await asyncio.wait_for(collect(store.stream('job_e')), 5)] == [1, 2, 3]
    assert await asyncio.wait_for(collect(store.stream('job_e', after=3)), 5) == []


async def test_stream_fills_gaps_from_the_database(store: EventStore, monkeypatch: pytest.MonkeyPatch) -> None:
    task = asyncio.create_task(collect(store.stream('job_e')))
    await asyncio.sleep(0.2)
    await store.append('job_e', JobAcceptedEvent(type='job.accepted', job_id='job_e'))
    publish = store.publish

    async def lost(job_id: str, message: dict[str, Any]) -> None:
        return None

    monkeypatch.setattr(store, 'publish', lost)
    await store.append('job_e', status('queued'))
    monkeypatch.setattr(store, 'publish', publish)
    await store.append('job_e', status('cancelled'))
    assert [m['seq'] for m in await asyncio.wait_for(task, 5)] == [1, 2, 3]


async def test_unknown_jobs_raise(store: EventStore) -> None:
    with pytest.raises(NotFound):
        await collect(store.stream('nope'))
    with pytest.raises(NotFound):
        await store.append('nope', log('x'))
```

- [ ] **Step 3: 建立 `backend/tests/test_jobs.py`**

```python
from datetime import UTC, datetime, timedelta, timezone

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.contract import HistoryEntry, JobInput, Render, parse_event
from app.core.clock import iso
from app.db.session import Database
from app.events import EventStore
from app.repo import history, jobs
from tests.fixtures import load_fixture

T0 = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 7, 2, 0, tzinfo=UTC)


def job_input() -> JobInput:
    return JobInput.model_validate(load_fixture('timelines/selune-retry.json')['input'])


async def replay_fixture(session: AsyncSession, db: Database, redis: Redis) -> tuple[str, dict[str, str]]:
    """把 selune-retry 劇本的事件寫進資料庫；回傳任務 id 與每個模板的最佳候選。"""
    data = load_fixture('timelines/selune-retry.json')
    job_id = data['jobId']
    await jobs.create_job(session, job_id, JobInput.model_validate(data['input']), T0)
    store = EventStore(db, redis)
    best: dict[str, str] = {}
    for item in data['events']:
        await store.append(job_id, parse_event(item['event']))
        if item['event']['type'] == 'job.completed':
            best = item['event']['bestRenderIds']
    return job_id, best


def test_job_ids_use_the_local_date_and_time() -> None:
    now = datetime(2026, 10, 5, 9, 30, tzinfo=timezone(timedelta(hours=8)))
    assert jobs.make_job_id(now, suffix=0x7FFF) == 'job_20261005_0930_7fff'


async def test_lists_jobs_newest_first(session: AsyncSession) -> None:
    await jobs.create_job(session, 'job_a', job_input(), T0)
    await jobs.create_job(session, 'job_b', job_input(), T1)
    summaries = await jobs.list_jobs(session)
    assert [j.id for j in summaries] == ['job_b', 'job_a']
    assert summaries[0].model_dump(include={'stage', 'round', 'finished', 'created_at'}) == {
        'stage': 'queued',
        'round': 0,
        'finished': False,
        'created_at': '2026-10-07T02:00:00.000Z',
    }
    assert await jobs.get_job(session, 'nope') is None


async def test_cancel_is_requested_only_for_unfinished_jobs(session: AsyncSession) -> None:
    await jobs.create_job(session, 'job_a', job_input(), T0)
    assert not await jobs.cancel_requested(session, 'job_a')
    assert await jobs.request_cancel(session, 'job_a')
    assert await jobs.cancel_requested(session, 'job_a')


async def test_rebuilds_a_render_and_its_review_from_the_events(
    session: AsyncSession, db: Database, redis: Redis
) -> None:
    job_id, best = await replay_fixture(session, db, redis)
    render = await jobs.get_render(session, job_id, best['ig-post'])
    assert render is not None
    assert (render.round, render.template_id, render.passed, len(render.checks)) == (2, 'ig-post', True, 10)
    snap = await jobs.get_job(session, job_id)
    assert snap is not None
    assert snap.summary.best_render_ids == best
    assert not await jobs.request_cancel(session, job_id)
    assert await jobs.get_render(session, job_id, 'nope') is None


async def test_history_is_newest_first_per_brand_with_favorites(
    session: AsyncSession, db: Database, redis: Redis
) -> None:
    job_id, best = await replay_fixture(session, db, redis)
    render = await jobs.get_render(session, job_id, best['ig-post'])
    assert isinstance(render, Render)

    def entry(entry_id: str, at: datetime) -> HistoryEntry:
        return HistoryEntry(
            id=entry_id,
            job_id=job_id,
            brand_id='selune',
            product_id='prod_selune_serum',
            input=job_input(),
            template_id='ig-post',
            render=render,
            copy_=render.spec.copy_,
            selected_at=iso(at),
            favorite=False,
            written_to_rag=True,
        )

    await history.add_history(session, entry('hist_a', T0))
    await history.add_history(session, entry('hist_b', T1))
    assert [h.id for h in await history.list_history(session)] == ['hist_b', 'hist_a']
    assert await history.list_history(session, 'misty-isle') == []
    updated = await history.set_favorite(session, 'hist_a', True)
    assert updated is not None and updated.favorite
    assert [h.favorite for h in await history.list_history(session, 'selune')] == [False, True]
    assert await history.set_favorite(session, 'nope', True) is None
```

- [ ] **Step 4: 執行測試確認失敗**

Run: `uv run pytest tests/test_events.py tests/test_jobs.py -q`
Expected: FAIL，2 個測試檔無法載入：`test_events.py`（`No module named 'app.errors'`）、`test_jobs.py`（`No module named 'app.events'`）。

- [ ] **Step 5: 修改 `backend/app/contract.py`**（新增 `JobSnapshot`）

找到：

```python
    best_render_ids: dict[TemplateId, str]


# ---------- 品牌文件上傳 ----------
class BrandDocument(Model):
    name: str
```

改成：

```python
    best_render_ids: dict[TemplateId, str]


class JobSnapshot(Model):
    """任務摘要與完整訊息（對應 web/src/lib/api/client.ts 的 JobSnapshot；訊息保持原始 JSON）。"""

    summary: JobSummary
    events: list[dict[str, Any]]


# ---------- 品牌文件上傳 ----------
class BrandDocument(Model):
    name: str
```

- [ ] **Step 6: 建立 `backend/app/errors.py`**

```python
"""領域錯誤：API 轉成 { error: { code, message } }（message 為繁體中文）。"""


class AppError(Exception):
    status = 400
    code = 'invalid'

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(AppError):
    status = 404
    code = 'not_found'


class Invalid(AppError):
    status = 400
    code = 'invalid'


class Conflict(AppError):
    status = 409
    code = 'conflict'
```

- [ ] **Step 7: 建立 `backend/app/events.py`**

```python
"""任務事件的保存與推送。

- append：同一個交易內鎖定任務列、取得下一個 seq、寫入 job_events 並更新任務摘要；commit 後發布到 Redis。
- stream：先訂閱 Redis，再從資料庫補送 seq 之後的事件，接著轉送即時事件（依 seq 去除重複、補齊漏掉的）。
- 任務結束的 job.status（done／needs_review／cancelled／failed）一定是最後一則事件，串流看到就結束。
"""

import json
from collections.abc import AsyncIterator
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select

from app.contract import FINISHED_STAGES, JobEvent, JobStage, message_json
from app.core.clock import iso, utc_now
from app.db.models import JobEventRow, JobRow
from app.db.session import Database
from app.errors import NotFound


def channel(job_id: str) -> str:
    return f'job:{job_id}'


def is_final(message: dict[str, Any]) -> bool:
    return message['type'] == 'job.status' and message['stage'] in FINISHED_STAGES


def _apply(row: JobRow, event: JobEvent) -> None:
    """事件 → 任務摘要（任務列表與 Agent 透視的選單使用）。"""
    if event.type == 'job.status':
        row.stage, row.round = event.stage, event.round
        row.finished = event.stage in FINISHED_STAGES
    elif event.type == 'job.completed':
        row.best_render_ids = {str(t): r for t, r in event.best_render_ids.items()}
    elif event.type == 'job.failed':
        row.failure_reason = event.reason


def _message(row: JobEventRow) -> dict[str, Any]:
    return {**row.payload, 'seq': row.seq, 'ts': iso(row.ts)}


class EventStore:
    def __init__(self, db: Database, redis: Redis) -> None:
        self.db = db
        self.redis = redis

    async def append(self, job_id: str, event: JobEvent, *, expect_stage: JobStage | None = None) -> int | None:
        """寫入事件並回傳 seq。expect_stage 與目前階段不同時不寫入、回傳 None（例如排隊中的任務已被取消）。"""
        ts = utc_now()
        async with self.db.session() as s:
            row = await s.get(JobRow, job_id, with_for_update=True)
            if row is None:
                raise NotFound(f'找不到任務：{job_id}')
            if expect_stage is not None and row.stage != expect_stage:
                return None
            row.last_seq += 1
            seq = row.last_seq
            _apply(row, event)
            s.add(JobEventRow(job_id=job_id, seq=seq, ts=ts, type=event.type, payload=event.to_json()))
            await s.commit()
        await self.publish(job_id, message_json(event, seq, iso(ts)))
        return seq

    async def publish(self, job_id: str, message: dict[str, Any]) -> None:
        await self.redis.publish(channel(job_id), json.dumps(message, ensure_ascii=False))

    async def _stored(self, job_id: str, after: int, before: int | None = None) -> list[dict[str, Any]]:
        async with self.db.session() as s:
            query = select(JobEventRow).where(JobEventRow.job_id == job_id, JobEventRow.seq > after)
            if before is not None:
                query = query.where(JobEventRow.seq < before)
            return [_message(r) for r in await s.scalars(query.order_by(JobEventRow.seq))]

    async def stream(self, job_id: str, after: int = 0) -> AsyncIterator[dict[str, Any]]:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(channel(job_id))
        try:
            async with self.db.session() as s:
                job = await s.get(JobRow, job_id)
                if job is None:
                    raise NotFound(f'找不到任務：{job_id}')
                final_seq = job.last_seq if job.finished else None
            last = after
            for message in await self._stored(job_id, after):
                yield message
                last = message['seq']
                if is_final(message):
                    return
            # 任務早已結束，呼叫端也已收到全部事件
            if final_seq is not None and last >= final_seq:
                return
            while True:
                raw = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if raw is None:
                    continue
                message = json.loads(raw['data'])
                if message['seq'] <= last:
                    continue
                # Redis 漏掉的訊息從資料庫補齊
                for missing in await self._stored(job_id, last, before=message['seq']):
                    yield missing
                yield message
                last = message['seq']
                if is_final(message):
                    return
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()  # type: ignore[no-untyped-call]
```

- [ ] **Step 8: 建立 `backend/app/repo/jobs.py`**

```python
"""任務：建立、列表、快照、取消要求，以及從事件組回候選圖。"""

import secrets
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contract import JobInput, JobSnapshot, JobSummary, Render, ReviewCheck
from app.core.clock import iso
from app.db.models import JobEventRow, JobRow

#: 任務列表最多列出的筆數（新到舊）
LIST_LIMIT = 100


def make_job_id(local_now: datetime, suffix: int | None = None) -> str:
    """job_20261005_0930_7fff：本地日期時間（與前端 mock 的 makeJobId 相同格式）加上 4 位十六進位亂數。"""
    tail = secrets.randbelow(0xFFFF) if suffix is None else suffix
    return f'job_{local_now:%Y%m%d}_{local_now:%H%M}_{tail:04x}'


def _summary(row: JobRow) -> JobSummary:
    return JobSummary.model_validate(
        {
            'id': row.id,
            'input': row.input,
            'createdAt': iso(row.created_at),
            'stage': row.stage,
            'round': row.round,
            'finished': row.finished,
            'bestRenderIds': row.best_render_ids,
        }
    )


async def create_job(session: AsyncSession, job_id: str, job_input: JobInput, now: datetime) -> None:
    session.add(
        JobRow(id=job_id, brand_id=job_input.brand_id, input=job_input.to_json(), created_at=now, stage='queued')
    )
    await session.commit()


async def list_jobs(session: AsyncSession) -> list[JobSummary]:
    rows = await session.scalars(select(JobRow).order_by(JobRow.created_at.desc(), JobRow.id.desc()).limit(LIST_LIMIT))
    return [_summary(r) for r in rows]


async def get_job(session: AsyncSession, job_id: str) -> JobSnapshot | None:
    row = await session.get(JobRow, job_id)
    if row is None:
        return None
    events = await session.scalars(select(JobEventRow).where(JobEventRow.job_id == job_id).order_by(JobEventRow.seq))
    return JobSnapshot(summary=_summary(row), events=[{**e.payload, 'seq': e.seq, 'ts': iso(e.ts)} for e in events])


async def request_cancel(session: AsyncSession, job_id: str) -> bool:
    """執行中的任務：設定取消旗標（worker 在步驟之間檢查）。已結束或不存在時回傳 False。"""
    result = await session.execute(
        update(JobRow).where(JobRow.id == job_id, JobRow.finished.is_(False)).values(cancel_requested=True)
    )
    await session.commit()
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def cancel_requested(session: AsyncSession, job_id: str) -> bool:
    return bool(await session.scalar(select(JobRow.cancel_requested).where(JobRow.id == job_id)))


async def get_render(session: AsyncSession, job_id: str, render_id: str) -> Render | None:
    """由事件組回候選圖：render.completed 的內容加上 review.check 與 review.completed。"""
    payloads = await session.scalars(
        select(JobEventRow.payload)
        .where(
            JobEventRow.job_id == job_id,
            JobEventRow.type.in_(('render.completed', 'review.check', 'review.completed')),
        )
        .order_by(JobEventRow.seq)
    )
    render: Render | None = None
    for p in payloads:
        if p['type'] == 'render.completed':
            for r in p['renders']:
                if r['id'] == render_id:
                    render = Render.model_validate(r)
        elif render is not None and p.get('renderId') == render_id:
            if p['type'] == 'review.check':
                render.checks.append(ReviewCheck.model_validate(p['check']))
            else:
                render.score, render.passed = p['score'], p['passed']
    return render
```

- [ ] **Step 9: 建立 `backend/app/repo/history.py`**

```python
"""歷史紀錄：選定並匯出的海報（新到舊）。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contract import HistoryEntry
from app.core.clock import parse_iso
from app.db.models import HistoryRow


async def add_history(session: AsyncSession, entry: HistoryEntry) -> None:
    session.add(
        HistoryRow(
            id=entry.id,
            job_id=entry.job_id,
            brand_id=entry.brand_id,
            data=entry.to_json(),
            selected_at=parse_iso(entry.selected_at),
        )
    )
    await session.commit()


async def list_history(session: AsyncSession, brand_id: str | None = None) -> list[HistoryEntry]:
    query = select(HistoryRow).order_by(HistoryRow.selected_at.desc(), HistoryRow.id.desc())
    if brand_id is not None:
        query = query.where(HistoryRow.brand_id == brand_id)
    return [HistoryEntry.model_validate(r.data) for r in await session.scalars(query)]


async def set_favorite(session: AsyncSession, history_id: str, favorite: bool) -> HistoryEntry | None:
    row = await session.get(HistoryRow, history_id)
    if row is None:
        return None
    entry = HistoryEntry.model_validate({**row.data, 'favorite': favorite})
    row.data = entry.to_json()
    await session.commit()
    return entry
```

- [ ] **Step 10: 執行測試確認通過**

Run: `uv run pytest -q`
Expected: PASS，28 passed（`test_events.py` 6 個、`test_jobs.py` 5 個）。

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: 沒有錯誤。

- [ ] **Step 11: Commit**

```bash
git add \
  backend/app/contract.py \
  backend/app/errors.py \
  backend/app/events.py \
  backend/app/repo/history.py \
  backend/app/repo/jobs.py \
  backend/tests/conftest.py \
  backend/tests/test_events.py \
  backend/tests/test_jobs.py
git commit -m "feat: persist job events with sequence numbers and stream them through Redis" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: composer：Node 服務沿用前端的版型與模擬邏輯


**Files:**
- Create: `web/composer/handlers.ts`、`web/composer/app.ts`、`web/composer/server.ts`
- Modify: `web/vitest.config.mts`、`web/package.json`
- Test: `web/composer/handlers.test.ts`、`web/composer/app.test.ts`

**Interfaces:**
- Consumes：前端的 `computeLayout`、`getTemplate`、`parseBrief`、`buildPromptSpec`、`applyFlaws`、`reviewRender`、`planFixes`、`chunkDocument`、`embedPreview`
- Produces（後端 Task 9、10 呼叫；每個 handler 都是 JSON → JSON 的純函式）：
  - `POST /layout { templateId }` → `LayoutBox[]`
  - `POST /sim/brief { brand, product, text }` → `ParsedBrief`
  - `POST /sim/prompt { jobId, round, brand, product, brief, templateId, engine, seed, ragRefs, fixes, flawed }` → `PromptSpec`（`flawed` 時套用 mock 的四種失誤）
  - `POST /sim/review { spec, brand, variant, seed }` → `{ checks, score, passed }`
  - `POST /sim/fixes { checks, brand, spec }` → `Fix[]`
  - `POST /sim/ingest { brandId, doc }` → `{ dims, chunks: { chunk, preview }[] }`
  - `GET /health` → `{ status: 'ok' }`；錯誤為 `{ error: { code, message } }`（找不到路徑 404，其他 400）
  - `handle(path, body)`、`createComposerServer()`；`npm run composer`（`PORT` 預設 3900、`HOST` 預設 127.0.0.1）

- [ ] **Step 1: 修改 `web/vitest.config.mts`**（測試範圍加上 `composer/`）

找到：

```ts
  resolve: { tsconfigPaths: true },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
```

改成：

```ts
  resolve: { tsconfigPaths: true },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts', 'composer/**/*.test.ts'],
  },
});
```

- [ ] **Step 2: 建立 `web/composer/handlers.test.ts`**（先寫失敗測試）

```ts
import { describe, expect, it } from 'vitest';
import type { Product, PromptSpec, ReviewCheck } from '@/types/contract';
import { planFixes } from '@/lib/agent/fixes';
import { buildPromptSpec } from '@/lib/agent/prompt';
import { parseBrief } from '@/lib/api/mock/brief';
import { SAMPLE_PRODUCTS, SELUNE } from '@/lib/api/mock/data';
import { reviewRender } from '@/lib/api/mock/review';
import { computeLayout } from '@/lib/compose/layout';
import { getTemplate } from '@/lib/compose/templates';
import { chunkDocument, EMBED_DIMS } from '@/lib/rag/chunk';
import { handle } from './handlers';

const serum = SAMPLE_PRODUCTS[0] as Product;
const brief = parseBrief('週年慶主打買一送一，溫柔療癒', SELUNE, serum);
const promptBody = (flawed: boolean) => ({
  jobId: 'job_c', round: 1, brand: SELUNE, product: serum, brief, templateId: 'ig-post', engine: 'comfyui',
  seed: 123456789, ragRefs: ['selune#color'], fixes: [], flawed,
});

describe('composer handlers', () => {
  it('returns the preset layout of a template', () => {
    expect(handle('/layout', { templateId: 'story' })).toEqual(computeLayout(getTemplate('story')));
  });

  it('parses a brief like the mock', () => {
    expect(handle('/sim/brief', { brand: SELUNE, product: serum, text: '週年慶主打買一送一，溫柔療癒' })).toEqual(brief);
    expect(handle('/sim/brief', { brand: SELUNE, product: null, text: '隨便' })).toMatchObject({ productName: null });
  });

  it('builds a clean spec, or a flawed one for the first round of the demo', () => {
    const clean = handle('/sim/prompt', promptBody(false)) as PromptSpec;
    expect(clean).toEqual(buildPromptSpec({ ...promptBody(false), template: getTemplate('ig-post'), engine: 'comfyui', fixes: [] }));
    const flawed = handle('/sim/prompt', promptBody(true)) as PromptSpec;
    expect(flawed.palette.primary).toBe('#E0458A');
    expect(flawed.copy.subhead).toBe('7天根治暗沉・醫療級修護');
  });

  it('reviews and plans fixes like the mock', () => {
    const spec = handle('/sim/prompt', promptBody(true)) as PromptSpec;
    const full = reviewRender(spec, SELUNE, 1, 42);
    const review = handle('/sim/review', { spec, brand: SELUNE, variant: 1, seed: 42 }) as { checks: ReviewCheck[] };
    expect(review).toEqual({ checks: full.checks, score: full.score, passed: full.passed });
    expect(handle('/sim/fixes', { checks: review.checks, brand: SELUNE, spec })).toEqual(planFixes(review.checks, SELUNE, spec));
  });

  it('chunks a document with simulated embeddings', () => {
    const doc = { name: 'ci_update.md', text: '# 色彩更新\n主色維持 #2F4A44。\n\n# Logo\n- Logo 淨空區至少 0.5 倍高度' };
    const result = handle('/sim/ingest', { brandId: 'misty-isle', doc }) as { dims: number; chunks: { chunk: unknown; preview: number[] }[] };
    expect(result.dims).toBe(EMBED_DIMS);
    expect(result.chunks.map((c) => c.chunk)).toEqual(chunkDocument('misty-isle', doc));
    expect(result.chunks.every((c) => c.preview.length === 6)).toBe(true);
  });

  it('rejects unknown routes', () => {
    expect(() => handle('/nope', {})).toThrow('Unknown route: /nope');
  });
});
```

- [ ] **Step 3: 建立 `web/composer/app.test.ts`**

```ts
import type { AddressInfo } from 'node:net';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { createComposerServer } from './app';

const server = createComposerServer();
let base = '';

beforeAll(async () => {
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});
afterAll(() => new Promise<void>((resolve) => server.close(() => resolve())));

const post = (path: string, body: string) =>
  fetch(`${base}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body });

describe('composer server', () => {
  it('answers health checks', async () => {
    const res = await fetch(`${base}/health`);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: 'ok' });
  });

  it('runs a handler on POSTed JSON', async () => {
    const res = await post('/layout', JSON.stringify({ templateId: 'ig-post' }));
    expect(res.status).toBe(200);
    expect(await res.json()).toHaveLength(8);
  });

  it('reports bad requests as JSON errors', async () => {
    const unknown = await post('/nope', '{}');
    expect(unknown.status).toBe(404);
    expect(await unknown.json()).toEqual({ error: { code: 'not_found', message: 'Unknown route: /nope' } });
    const broken = await post('/layout', '{');
    expect(broken.status).toBe(400);
    expect((await broken.json()).error.code).toBe('invalid');
  });
});
```

- [ ] **Step 4: 執行測試確認失敗**

Run: `npx vitest run composer`
Expected: FAIL，兩個測試檔都無法載入：`Cannot find module './handlers'`、`Cannot find module './app'`。

- [ ] **Step 5: 建立 `web/composer/handlers.ts`**

```ts
import type {
  Brand, BrandDocument, CheckId, Engine, ParsedBrief, Product, PromptSpec, ReviewCheck, TemplateId,
} from '@/types/contract';
import { planFixes } from '@/lib/agent/fixes';
import { buildPromptSpec } from '@/lib/agent/prompt';
import { parseBrief } from '@/lib/api/mock/brief';
import { applyFlaws, FLAWS } from '@/lib/api/mock/flaws';
import { reviewRender } from '@/lib/api/mock/review';
import { computeLayout } from '@/lib/compose/layout';
import { getTemplate } from '@/lib/compose/templates';
import { chunkDocument, EMBED_DIMS, embedPreview } from '@/lib/rag/chunk';

/** 找不到路徑（伺服器回 404） */
export class UnknownRoute extends Error {}

type Handler = (body: never) => unknown;

/**
 * 後端呼叫的 TypeScript 邏輯：版型，以及模擬模式沿用的 mock 行為（/sim/*）。
 * 每個 handler 都是純函式：輸入與輸出都是合約的 JSON。
 */
const HANDLERS: Record<string, Handler> = {
  '/layout': ({ templateId }: { templateId: TemplateId }) => computeLayout(getTemplate(templateId)),

  '/sim/brief': ({ brand, product, text }: { brand: Brand; product: Product | null; text: string }) =>
    parseBrief(text, brand, product),

  '/sim/prompt': (b: {
    jobId: string; round: number; brand: Brand; product: Product; brief: ParsedBrief; templateId: TemplateId;
    engine: Engine; seed: number; ragRefs: string[]; fixes: CheckId[]; flawed: boolean;
  }) => {
    const spec = buildPromptSpec({ ...b, template: getTemplate(b.templateId) });
    return b.flawed ? applyFlaws(spec, FLAWS) : spec;
  },

  '/sim/review': ({ spec, brand, variant, seed }: { spec: PromptSpec; brand: Brand; variant: number; seed: number }) => {
    const { checks, score, passed } = reviewRender(spec, brand, variant, seed);
    return { checks, score, passed };
  },

  '/sim/fixes': ({ checks, brand, spec }: { checks: ReviewCheck[]; brand: Brand; spec: PromptSpec }) =>
    planFixes(checks, brand, spec),

  '/sim/ingest': ({ brandId, doc }: { brandId: string; doc: BrandDocument }) => ({
    dims: EMBED_DIMS,
    chunks: chunkDocument(brandId, doc).map((chunk) => ({ chunk, preview: embedPreview(chunk.text) })),
  }),
};

export function handle(path: string, body: unknown): unknown {
  const handler = HANDLERS[path];
  if (!handler) throw new UnknownRoute(`Unknown route: ${path}`);
  return handler(body as never);
}
```

- [ ] **Step 6: 建立 `web/composer/app.ts`**

```ts
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import { handle, UnknownRoute } from './handlers';

function send(res: ServerResponse, status: number, body: unknown) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}

async function readJson(req: IncomingMessage): Promise<unknown> {
  const parts: Buffer[] = [];
  for await (const part of req) parts.push(part as Buffer);
  return JSON.parse(Buffer.concat(parts).toString('utf8') || 'null');
}

/** composer 的 HTTP 介面：GET /health；其他都是 POST JSON → JSON。錯誤回 { error: { code, message } }。 */
export function createComposerServer(): Server {
  return createServer(async (req, res) => {
    const path = new URL(req.url ?? '/', 'http://composer').pathname;
    if (req.method === 'GET' && path === '/health') return send(res, 200, { status: 'ok' });
    try {
      const body = await readJson(req);
      send(res, 200, handle(path, body));
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (err instanceof UnknownRoute) send(res, 404, { error: { code: 'not_found', message } });
      else send(res, 400, { error: { code: 'invalid', message } });
    }
  });
}
```

- [ ] **Step 7: 建立 `web/composer/server.ts`**

```ts
// composer：npm run composer（預設 3900 埠，可用 PORT 變更）
import { createComposerServer } from './app';

const port = Number(process.env.PORT ?? 3900);
const host = process.env.HOST ?? '127.0.0.1';
createComposerServer().listen(port, host, () => console.log(`composer listening on http://${host}:${port}`));
```

- [ ] **Step 8: 修改 `web/package.json`**（`composer` 指令）

找到：

```json
    "test:watch": "vitest",
    "typecheck": "next typegen && tsc --noEmit",
    "e2e": "playwright test",
    "fixtures": "tsx scripts/fixtures.ts"
  },
  "dependencies": {
    "@fontsource-variable/noto-sans-tc": "^5.3.0",
```

改成：

```json
    "test:watch": "vitest",
    "typecheck": "next typegen && tsc --noEmit",
    "e2e": "playwright test",
    "fixtures": "tsx scripts/fixtures.ts",
    "composer": "tsx composer/server.ts"
  },
  "dependencies": {
    "@fontsource-variable/noto-sans-tc": "^5.3.0",
```

- [ ] **Step 9: 執行測試確認通過**

Run: `npx vitest run composer`
Expected: PASS（`handlers.test.ts` 6 個、`app.test.ts` 3 個）。

Run: `npm run test && npm run typecheck && npm run lint`
Expected: 39 個測試檔、297 個測試全部通過；沒有錯誤。

- [ ] **Step 10: 手動確認**

```bash
npm run composer
```

另開終端機執行 `curl http://127.0.0.1:3900/health`，Expected：`{"status":"ok"}`。確認後按 Ctrl+C 停止。

- [ ] **Step 11: Commit**

```bash
git add \
  web/composer/app.test.ts \
  web/composer/app.ts \
  web/composer/handlers.test.ts \
  web/composer/handlers.ts \
  web/composer/server.ts \
  web/package.json \
  web/vitest.config.mts
git commit -m "feat: add the composer service that serves layouts and the simulated agent from the frontend code" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: 任務流程與模擬版的外部服務（與 mock 劇本完全相同）


**Files:**
- Create: `backend/app/templates.py`、`backend/app/pipeline/__init__.py`、`backend/app/pipeline/ports.py`、`backend/app/pipeline/sim.py`、`backend/app/pipeline/runner.py`、`backend/app/adapters/__init__.py`、`backend/app/adapters/composer.py`
- Modify: `backend/app/settings.py`、`backend/tests/conftest.py`、`backend/tests/test_contract.py`
- Test: `backend/tests/test_pipeline.py`、`backend/tests/test_parity.py`

**Interfaces:**
- Consumes：Task 7 的 `EventStore`、`app.repo.jobs`；Task 8 的 composer
- Produces：
  - `app.templates`：`CHANNEL_TEMPLATES`（與前端相同）、`get_template(template_id)`
  - `app.pipeline.ports`（任務流程只依賴這些介面；Plan 5–7 加入真實版）：
    - `Retriever`：`retrieve(brand, product, job_input) -> (query, hits)`、`rerank(query, hits)`、`requery(brand, query)`
    - `Agent`：`parse_brief(brand, text, product)`、`build_spec(SpecRequest)`、`plan_rewrite(brand, spec, checks) -> Rewrite(fixes, query)`
    - `ImageEngine`：`render_round(job_id, round, specs, variants, brand, run) -> {(template_id, variant): RenderBackground}`
    - `Reviewer`：`review(brand, render, seed) -> ReviewResult(checks, score, passed)`
    - `RunContext`：`emit`、`log`、`pace`；`Ports(retriever, agent, image, reviewer)`；`SpecRequest`
  - `ComposerClient(base_url)`：
    - 方法：`health()`、`layout(template_id)`、`sim_brief`、`sim_prompt(request, flawed)`、`sim_review`、`sim_fixes`、`sim_ingest -> SimIngest(dims, chunks)`、`aclose()`。
    - 失敗時丟出 `ComposerError`。
  - `sim_ports(composer, *, first_round_fail, force_all_fail) -> Ports`。各模擬版：
    - `SimRetriever`：固定的召回與 Rerank 順序。
    - `SimAgent`、`SimReviewer`：透過 composer 沿用 mock。
    - `SimImageEngine`：程序化背景與 ComfyUI 進度事件。
  - `run_job(job_id, db, store, ports, *, speed)`：
    - 開始：以 `expect_stage='queued'` 取得任務（已取消的任務不執行）。
    - 事件：階段與事件順序與 mock 劇本相同；依 `PHASE_MS` 與 `speed` 等待（`speed=0` 不等待）。
    - 取消：最多每 0.25 秒檢查一次。
    - 失敗：送出 `log`（error）、`job.failed`、`job.status failed`。
  - `failure_reason(error)`：`AppError` 取 message，其他為「類別: 訊息」
  - 設定：`composer_url`、`sim_speed`、`sim_first_round_fail`、`sim_force_all_fail`
  - 測試 fixture `composer_url`：在 3902 埠啟動 composer（需要 `web/` 已 `npm ci`）

- [ ] **Step 1: 修改 `backend/tests/conftest.py`**（測試時自動啟動 composer）

找到（1／2）：

```python
每次測試開始時重建 genai_test 資料庫並跑 migration；每個測試結束後清空所有資料表。
"""

from collections.abc import AsyncIterator

import asyncpg
import pytest
from redis.asyncio import Redis
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.settings import settings

TEST_DATABASE = 'genai_test'
#: 測試使用 Redis 的第 15 個資料庫，開始時清空
```

改成：

```python
每次測試開始時重建 genai_test 資料庫並跑 migration；每個測試結束後清空所有資料表。
"""

import os
import subprocess
import time
from collections.abc import AsyncIterator, Iterator

import asyncpg
import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.settings import REPO_ROOT, settings

TEST_DATABASE = 'genai_test'
#: 測試使用 Redis 的第 15 個資料庫，開始時清空
```

找到（2／2）：

```python
    await client.aclose()


@pytest.fixture
async def session(db: Database) -> AsyncIterator[AsyncSession]:
    async with db.session() as s:
```

改成：

```python
    await client.aclose()


@pytest.fixture(scope='session')
def composer_url() -> Iterator[str]:
    """在 3902 埠啟動 composer（需要 web/ 已 npm install）。"""
    port = 3902
    url = f'http://127.0.0.1:{port}'
    proc = subprocess.Popen(
        ['node', '--import', 'tsx', 'composer/server.ts'],
        cwd=REPO_ROOT / 'web',
        env={**os.environ, 'PORT': str(port)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                if httpx.get(f'{url}/health').status_code == 200:
                    break
            except httpx.HTTPError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)
        yield url
    finally:
        proc.terminate()
        proc.wait(10)


@pytest.fixture
async def session(db: Database) -> AsyncIterator[AsyncSession]:
    async with db.session() as s:
```

- [ ] **Step 2: 修改 `backend/tests/test_contract.py`**（通路模板與前端相同；先寫失敗測試）

找到（1／2）：

```python
    parse_event,
    parse_message,
)
from tests.fixtures import TIMELINES, load_fixture
```

改成：

```python
    parse_event,
    parse_message,
)
from app.templates import CHANNEL_TEMPLATES
from tests.fixtures import TIMELINES, load_fixture
```

找到（2／2）：

```python
    hit = RagHit(chunk_id='c', source='s', section='§', tag='law', text='t', vector_score=0.8)
    assert 'rerankScore' not in hit.to_json()
    assert hit.model_copy(update={'rerank_score': 0.9}).to_json()['rerankScore'] == 0.9
```

改成：

```python
    hit = RagHit(chunk_id='c', source='s', section='§', tag='law', text='t', vector_score=0.8)
    assert 'rerankScore' not in hit.to_json()
    assert hit.model_copy(update={'rerank_score': 0.9}).to_json()['rerankScore'] == 0.9


def test_channel_templates_match_the_frontend() -> None:
    assert [t.to_json() for t in CHANNEL_TEMPLATES] == load_fixture('brands.json')['templates']
```

- [ ] **Step 3: 建立 `backend/tests/test_pipeline.py`**

以測試替身取代外部服務，驗證流程本身：
- 重試只針對未通過的模板。
- 最後一次重試仍未通過時轉人工審核。
- 取消、失敗。
- 任務已不在排隊時不執行。

```python
"""任務流程的行為：重試只針對未通過的模板、需人工審核、取消、失敗、已不在排隊時不執行。

外部服務用測試替身（不需要 composer）。
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from redis.asyncio import Redis

from app.brands import load_brands
from app.contract import (
    Brand,
    Fix,
    JobAcceptedEvent,
    JobInput,
    JobStatusEvent,
    ParsedBrief,
    ProceduralBackground,
    Product,
    PromptSpec,
    RagHit,
    Render,
    RenderBackground,
    ReviewCheck,
    TemplateId,
)
from app.db.session import Database
from app.events import EventStore
from app.pipeline.ports import Ports, ReviewResult, Rewrite, RunContext, SpecRequest
from app.pipeline.runner import run_job
from app.pipeline.sim import SimRetriever
from app.repo import catalog, jobs
from tests.fixtures import BRANDS_DIR, load_fixture

NOW = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)
JOB = 'job_p'

#: 用 selune-retry 劇本裡的一份 PromptSpec 當範本
SPEC = PromptSpec.model_validate(
    next(
        item['event']['spec']
        for item in load_fixture('timelines/selune-retry.json')['events']
        if item['event']['type'] == 'prompt.generated'
    )
)
CHECK = ReviewCheck(
    id='banned_words',
    name='禁用詞檢查',
    kind='rule',
    rule='品牌禁用詞庫',
    value='禁用詞「根治」',
    status='fail',
    target='subhead',
    rag_ref='selune#law',
)


class FakeAgent:
    def __init__(self) -> None:
        self.requests: list[SpecRequest] = []

    async def parse_brief(self, brand: Brand, text: str, product: Product | None) -> ParsedBrief:
        raise NotImplementedError

    async def build_spec(self, request: SpecRequest) -> PromptSpec:
        self.requests.append(request)
        return SPEC.model_copy(update={'round': request.round, 'template_id': request.template.id})

    async def plan_rewrite(self, brand: Brand, spec: PromptSpec, checks: list[ReviewCheck]) -> Rewrite:
        return Rewrite(fixes=[Fix(check_id='banned_words', title='文案改寫', desc='改寫')], query=None)


class FakeImage:
    def __init__(self, on_render: Any = None) -> None:
        self.on_render = on_render

    async def render_round(
        self, job_id: str, round: int, specs: list[PromptSpec], variants: int, brand: Brand, run: RunContext
    ) -> dict[tuple[TemplateId, int], RenderBackground]:
        if self.on_render is not None:
            await self.on_render(run)
        return {
            (s.template_id, v): ProceduralBackground(kind='procedural', seed=v, palette=s.palette, style=brand.id)
            for s in specs
            for v in range(variants)
        }


class FakeReviewer:
    """passing：每一輪會通過的模板。"""

    def __init__(self, passing: dict[int, set[str]]) -> None:
        self.passing = passing

    async def review(self, brand: Brand, render: Render, seed: int) -> ReviewResult:
        ok = render.template_id in self.passing.get(render.round, set())
        return ReviewResult(checks=[] if ok else [CHECK], score=90 - render.variant if ok else 40, passed=ok)


class EmptyRetriever(SimRetriever):
    async def requery(self, brand: Brand, query: str) -> list[RagHit]:
        return []


@pytest.fixture
async def store(db: Database, redis: Redis) -> AsyncIterator[EventStore]:
    data = load_fixture('timelines/selune-retry.json')
    job_input = JobInput.model_validate({**data['input'], 'variantsPerTemplate': 2, 'maxRetries': 1})
    async with db.session() as s:
        await catalog.sync_brands(s, load_brands(BRANDS_DIR)[0], NOW)
        await jobs.create_job(s, JOB, job_input, NOW)
    events = EventStore(db, redis)
    await events.append(JOB, JobAcceptedEvent(type='job.accepted', job_id=JOB))
    await events.append(JOB, JobStatusEvent(type='job.status', stage='queued', round=0))
    yield events
    await db.truncate_all()


async def messages(db: Database) -> list[dict[str, Any]]:
    async with db.session() as s:
        snap = await jobs.get_job(s, JOB)
    assert snap is not None
    return [m for m in snap.events if m['type'] != 'log']


def ports(agent: FakeAgent, reviewer: FakeReviewer, image: FakeImage | None = None) -> Ports:
    return Ports(retriever=EmptyRetriever(), agent=agent, image=image or FakeImage(), reviewer=reviewer)


async def test_retries_only_the_templates_that_failed(store: EventStore, db: Database) -> None:
    agent = FakeAgent()
    await run_job(JOB, db, store, ports(agent, FakeReviewer({1: {'ig-post'}, 2: {'story'}})), speed=0)
    assert [(r.round, r.template.id) for r in agent.requests] == [(1, 'ig-post'), (1, 'story'), (2, 'story')]
    assert agent.requests[2].fixes == ['banned_words']
    events = await messages(db)
    completed = next(m for m in events if m['type'] == 'job.completed')
    assert completed['bestRenderIds'] == {'ig-post': f'{JOB}_r1_ig-post_v0', 'story': f'{JOB}_r2_story_v0'}
    assert events[-1] == {**events[-1], 'type': 'job.status', 'stage': 'done', 'round': 2}


async def test_asks_for_manual_review_after_the_last_retry(store: EventStore, db: Database) -> None:
    await run_job(JOB, db, store, ports(FakeAgent(), FakeReviewer({})), speed=0)
    events = await messages(db)
    assert [m['stage'] for m in events if m['type'] == 'job.status'][-2:] == ['saving', 'needs_review']
    assert not any(m['type'] == 'job.completed' for m in events)


async def test_stops_when_the_job_is_cancelled(store: EventStore, db: Database) -> None:
    async def cancel(run: RunContext) -> None:
        async with db.session() as s:
            await jobs.request_cancel(s, JOB)
        await run.pace(300)

    await run_job(JOB, db, store, ports(FakeAgent(), FakeReviewer({}), FakeImage(cancel)), speed=1)
    events = await messages(db)
    assert events[-1] == {**events[-1], 'type': 'job.status', 'stage': 'cancelled', 'round': 1}
    assert not any(m['type'] == 'render.completed' for m in events)


async def test_reports_a_failure_and_ends_the_job(store: EventStore, db: Database) -> None:
    async def boom(run: RunContext) -> None:
        raise RuntimeError('ComfyUI 沒有回應')

    await run_job(JOB, db, store, ports(FakeAgent(), FakeReviewer({}), FakeImage(boom)), speed=0)
    events = await messages(db)
    assert events[-2:] == [
        {**events[-2], 'type': 'job.failed', 'jobId': JOB, 'reason': 'RuntimeError: ComfyUI 沒有回應'},
        {**events[-1], 'type': 'job.status', 'stage': 'failed', 'round': 1},
    ]
    async with db.session() as s:
        summary = (await jobs.get_job(s, JOB)).summary  # type: ignore[union-attr]
    assert (summary.stage, summary.finished) == ('failed', True)


async def test_does_nothing_when_the_job_is_no_longer_queued(store: EventStore, db: Database) -> None:
    await store.append(JOB, JobStatusEvent(type='job.status', stage='cancelled', round=0))
    before = await messages(db)
    await run_job(JOB, db, store, ports(FakeAgent(), FakeReviewer({})), speed=0)
    assert await messages(db) == before
```

- [ ] **Step 4: 建立 `backend/tests/test_parity.py`**

用模擬版跑三個劇本（重試後通過、需人工審核、首輪通過）。除了 `log` 以外，每一則事件的內容與順序都必須與 TypeScript 產生的劇本相同。

```python
"""模擬模式的任務流程與前端 mock 劇本（contracts/fixtures/timelines/）產生完全相同的事件。

比對除了 log 以外的每一則事件（內容與順序）；需要 composer（測試會自動啟動）。
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from redis.asyncio import Redis

from app.adapters.composer import ComposerClient
from app.brands import load_brands
from app.contract import JobAcceptedEvent, JobInput, JobStatusEvent
from app.db.session import Database
from app.events import EventStore
from app.pipeline.runner import run_job
from app.pipeline.sim import sim_ports
from app.repo import catalog, jobs
from tests.fixtures import BRANDS_DIR, TIMELINES, load_fixture

NOW = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)


def without_meta(message: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in message.items() if k not in ('seq', 'ts')}


@pytest.mark.parametrize('name', TIMELINES)
async def test_simulated_pipeline_matches_the_mock_timeline(
    name: str, db: Database, redis: Redis, composer_url: str
) -> None:
    data = load_fixture(f'timelines/{name}.json')
    job_id, demo = data['jobId'], data['demo']
    async with db.session() as s:
        await catalog.sync_brands(s, load_brands(BRANDS_DIR)[0], NOW)
        await jobs.create_job(s, job_id, JobInput.model_validate(data['input']), NOW)
    store = EventStore(db, redis)
    await store.append(job_id, JobAcceptedEvent(type='job.accepted', job_id=job_id))
    await store.append(job_id, JobStatusEvent(type='job.status', stage='queued', round=0))
    composer = ComposerClient(composer_url)
    try:
        ports = sim_ports(composer, first_round_fail=demo['firstRoundFail'], force_all_fail=demo['forceAllFail'])
        await run_job(job_id, db, store, ports, speed=0)
    finally:
        await composer.aclose()
    async with db.session() as s:
        snap = await jobs.get_job(s, job_id)
    assert snap is not None
    actual = [
        without_meta(m)
        for m in snap.events
        if m['type'] != 'log' and not (m['type'] == 'job.status' and m['stage'] == 'queued')
    ]
    expected = [item['event'] for item in data['events'] if item['event']['type'] != 'log']
    assert actual == expected
    assert snap.events[-1]['type'] == 'job.status'
    await db.truncate_all()
```

- [ ] **Step 5: 執行測試確認失敗**

Run: `uv run pytest -q`
Expected: FAIL，3 個測試檔無法載入：`test_contract.py`（`No module named 'app.templates'`）、`test_parity.py`（`No module named 'app.adapters'`）、`test_pipeline.py`（`No module named 'app.pipeline'`）。

- [ ] **Step 6: 修改 `backend/app/settings.py`**

找到：

```python
    data_dir: Path = REPO_ROOT / 'data'
    #: 使用者自己的商品照（唯讀）
    local_photos_dir: Path = REPO_ROOT / 'assets' / 'products'


settings = Settings()
```

改成：

```python
    data_dir: Path = REPO_ROOT / 'data'
    #: 使用者自己的商品照（唯讀）
    local_photos_dir: Path = REPO_ROOT / 'assets' / 'products'
    composer_url: str = 'http://127.0.0.1:3900'

    #: 模擬模式的播放速度（1 為 1× 時間軸，約 15 秒一個任務；0 為不等待）
    sim_speed: float = 1.0
    #: 模擬模式：第一輪刻意失誤（觸發 Query Rewriting）
    sim_first_round_fail: bool = True
    #: 模擬模式：每一輪都失誤（展示「需人工審核」）
    sim_force_all_fail: bool = False


settings = Settings()
```

- [ ] **Step 7: 建立 `backend/app/templates.py`**

```python
"""通路模板：與 web/src/lib/compose/templates.ts 相同。"""

from app.contract import ChannelTemplate, TemplateId
from app.errors import Invalid

CHANNEL_TEMPLATES: list[ChannelTemplate] = [
    ChannelTemplate(id='ecom-main', label='電商主圖', ratio='1:1', width=1600, height=1600),
    ChannelTemplate(id='scene', label='情境圖', ratio='4:3', width=2048, height=1536),
    ChannelTemplate(id='ig-post', label='IG 貼文', ratio='4:5', width=1440, height=1800),
    ChannelTemplate(id='story', label='限時動態', ratio='9:16', width=1152, height=2048),
    ChannelTemplate(id='banner', label='促銷 Banner', ratio='16:9', width=2048, height=1152),
]


def get_template(template_id: TemplateId) -> ChannelTemplate:
    for t in CHANNEL_TEMPLATES:
        if t.id == template_id:
            return t
    raise Invalid(f'沒有這個通路模板：{template_id}')
```

- [ ] **Step 8: 建立 `backend/app/pipeline/__init__.py`**（空檔）

```python

```

- [ ] **Step 9: 建立 `backend/app/pipeline/ports.py`**

```python
"""任務流程依賴的外部服務介面。每個介面都有真實版與模擬版（app/pipeline/sim.py），由設定切換。"""

from dataclasses import dataclass
from typing import Protocol

from app.contract import (
    Brand,
    ChannelTemplate,
    CheckId,
    Engine,
    Fix,
    JobEvent,
    JobInput,
    LogLevel,
    LogSource,
    ParsedBrief,
    Product,
    PromptSpec,
    RagHit,
    Render,
    RenderBackground,
    ReviewCheck,
    TemplateId,
)


@dataclass(frozen=True)
class SpecRequest:
    job_id: str
    round: int
    brand: Brand
    product: Product
    brief: ParsedBrief
    template: ChannelTemplate
    engine: Engine
    seed: int
    rag_refs: list[str]
    #: 之前各輪未通過的檢查（依出現順序，不重複）
    fixes: list[CheckId]


@dataclass(frozen=True)
class Rewrite:
    fixes: list[Fix]
    #: 需要重新檢索合規用語時的查詢；不需要時為 None
    query: str | None


@dataclass(frozen=True)
class ReviewResult:
    checks: list[ReviewCheck]
    score: int
    passed: bool


class RunContext(Protocol):
    """任務執行中可用的動作（ImageEngine 回報進度用）。"""

    async def emit(self, event: JobEvent) -> None: ...

    async def log(self, source: LogSource, message: str, level: LogLevel = 'info') -> None: ...

    async def pace(self, ms: float) -> None: ...


class Retriever(Protocol):
    async def retrieve(self, brand: Brand, product: Product, job_input: JobInput) -> tuple[str, list[RagHit]]: ...

    async def rerank(self, query: str, hits: list[RagHit]) -> list[RagHit]: ...

    async def requery(self, brand: Brand, query: str) -> list[RagHit]: ...


class Agent(Protocol):
    async def parse_brief(self, brand: Brand, text: str, product: Product | None) -> ParsedBrief: ...

    async def build_spec(self, request: SpecRequest) -> PromptSpec: ...

    async def plan_rewrite(self, brand: Brand, spec: PromptSpec, checks: list[ReviewCheck]) -> Rewrite: ...


class ImageEngine(Protocol):
    async def render_round(
        self, job_id: str, round: int, specs: list[PromptSpec], variants: int, brand: Brand, run: RunContext
    ) -> dict[tuple[TemplateId, int], RenderBackground]: ...


class Reviewer(Protocol):
    async def review(self, brand: Brand, render: Render, seed: int) -> ReviewResult: ...


@dataclass(frozen=True)
class Ports:
    retriever: Retriever
    agent: Agent
    image: ImageEngine
    reviewer: Reviewer
```

- [ ] **Step 10: 建立 `backend/app/adapters/__init__.py`**（空檔）

```python

```

- [ ] **Step 11: 建立 `backend/app/adapters/composer.py`**

```python
"""composer（web/composer）的用戶端：版型，以及模擬模式沿用的前端 mock 邏輯（/sim/*）。"""

from dataclasses import dataclass
from typing import Any

import httpx

from app.contract import (
    Brand,
    BrandDocument,
    Fix,
    LayoutBox,
    ParsedBrief,
    Product,
    PromptSpec,
    RagChunk,
    ReviewCheck,
    TemplateId,
)
from app.pipeline.ports import ReviewResult, SpecRequest


class ComposerError(Exception):
    pass


@dataclass(frozen=True)
class SimIngest:
    dims: int
    #: 切塊與模擬向量的前幾維
    chunks: list[tuple[RagChunk, list[float]]]


class ComposerClient:
    def __init__(self, base_url: str, timeout: float = 30) -> None:
        self.base_url = base_url
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        try:
            res = await self._client.post(path, json=body)
        except httpx.HTTPError as e:
            raise ComposerError(f'composer 沒有回應（{self.base_url}）：{e!r}') from e
        if res.status_code != 200:
            raise ComposerError(f'composer {path} 失敗：{res.json().get("error", {}).get("message", res.text)}')
        return res.json()

    async def health(self) -> bool:
        try:
            return (await self._client.get('/health')).status_code == 200
        except httpx.HTTPError:
            return False

    async def layout(self, template_id: TemplateId) -> list[LayoutBox]:
        return [LayoutBox.model_validate(b) for b in await self._post('/layout', {'templateId': template_id})]

    async def sim_brief(self, brand: Brand, product: Product | None, text: str) -> ParsedBrief:
        body = {'brand': brand.to_json(), 'product': product.to_json() if product else None, 'text': text}
        return ParsedBrief.model_validate(await self._post('/sim/brief', body))

    async def sim_prompt(self, r: SpecRequest, flawed: bool) -> PromptSpec:
        body = {
            'jobId': r.job_id,
            'round': r.round,
            'brand': r.brand.to_json(),
            'product': r.product.to_json(),
            'brief': r.brief.to_json(),
            'templateId': r.template.id,
            'engine': r.engine,
            'seed': r.seed,
            'ragRefs': r.rag_refs,
            'fixes': r.fixes,
            'flawed': flawed,
        }
        return PromptSpec.model_validate(await self._post('/sim/prompt', body))

    async def sim_review(self, spec: PromptSpec, brand: Brand, variant: int, seed: int) -> ReviewResult:
        body = {'spec': spec.to_json(), 'brand': brand.to_json(), 'variant': variant, 'seed': seed}
        data = await self._post('/sim/review', body)
        checks = [ReviewCheck.model_validate(c) for c in data['checks']]
        return ReviewResult(checks=checks, score=data['score'], passed=data['passed'])

    async def sim_fixes(self, checks: list[ReviewCheck], brand: Brand, spec: PromptSpec) -> list[Fix]:
        body = {'checks': [c.to_json() for c in checks], 'brand': brand.to_json(), 'spec': spec.to_json()}
        return [Fix.model_validate(f) for f in await self._post('/sim/fixes', body)]

    async def sim_ingest(self, brand_id: str, doc: BrandDocument) -> SimIngest:
        data = await self._post('/sim/ingest', {'brandId': brand_id, 'doc': doc.to_json()})
        chunks = [(RagChunk.model_validate(c['chunk']), list(c['preview'])) for c in data['chunks']]
        return SimIngest(dims=data['dims'], chunks=chunks)
```

- [ ] **Step 12: 建立 `backend/app/pipeline/sim.py`**

```python
"""模擬版的外部服務：行為與前端 mock 劇本相同（web/src/lib/api/mock/scenario.ts）。

檢索與生圖在這裡實作；Agent 與審查透過 composer 沿用前端的 TypeScript
（buildPromptSpec、applyFlaws、reviewRender、planFixes）。
"""

from app.adapters.composer import ComposerClient
from app.contract import (
    Brand,
    ComfyQueuedEvent,
    JobInput,
    ParsedBrief,
    ProceduralBackground,
    Product,
    PromptSpec,
    RagHit,
    RagTag,
    Render,
    RenderBackground,
    RenderNode,
    RenderProgressEvent,
    ReviewCheck,
    TemplateId,
)
from app.pipeline.ports import Ports, ReviewResult, Rewrite, RunContext, SpecRequest

#: 向量召回順序與 Rerank 後順序刻意不同，用來展示 BGE Reranker 的效果
VECTOR_ORDER: list[RagTag] = ['layout', 'color', 'history', 'logo', 'law']
VECTOR_SCORES = [0.86, 0.84, 0.83, 0.81, 0.79]
RERANK_ORDER: list[RagTag] = ['color', 'law', 'logo', 'layout', 'history']
RERANK_SCORES = [0.97, 0.93, 0.88, 0.74, 0.61]

#: ComfyUI 各節點的步數與時間（1× 毫秒）；每輪共 38 個 render.progress、3,200 ms
RENDER_STEPS: dict[RenderNode, tuple[int, int]] = {
    'cutout': (4, 400),
    'generate': (28, 2000),
    'relight': (4, 500),
    'upscale': (2, 300),
}
NODE_LABEL: dict[RenderNode, str] = {
    'cutout': '去背（BiRefNet）',
    'generate': '背景生成（SDXL + ControlNet + IP-Adapter）',
    'relight': '打光融合（IC-Light）',
    'upscale': '放大至 2K',
}


def seed_of(spec: PromptSpec) -> int:
    return int(next((p.value for p in spec.injection.params if p.label == 'seed'), 0))


class SimRetriever:
    async def retrieve(self, brand: Brand, product: Product, job_input: JobInput) -> tuple[str, list[RagHit]]:
        hits: list[RagHit] = []
        for tag, score in zip(VECTOR_ORDER, VECTOR_SCORES, strict=True):
            chunk = next((c for c in brand.guideline_chunks if c.tag == tag and not c.id.endswith('-alt')), None)
            if chunk is not None:
                hits.append(
                    RagHit(
                        chunk_id=chunk.id,
                        source=chunk.source,
                        section=chunk.section,
                        tag=chunk.tag,
                        text=chunk.text,
                        vector_score=score,
                    )
                )
        return f'{brand.name}｜{product.name}｜{job_input.brief}', hits

    async def rerank(self, query: str, hits: list[RagHit]) -> list[RagHit]:
        scored = [h.model_copy(update={'rerank_score': RERANK_SCORES[RERANK_ORDER.index(h.tag)]}) for h in hits]
        return sorted(scored, key=lambda h: -(h.rerank_score or 0))

    async def requery(self, brand: Brand, query: str) -> list[RagHit]:
        chunk = next((c for c in brand.guideline_chunks if c.id == f'{brand.id}#law-alt'), None)
        if chunk is None:
            return []
        return [
            RagHit(
                chunk_id=chunk.id,
                source=chunk.source,
                section=chunk.section,
                tag=chunk.tag,
                text=chunk.text,
                vector_score=0.884,
                rerank_score=0.95,
            )
        ]


class SimAgent:
    """第一輪（或每一輪）刻意製造 mock 的四種失誤，讓審查與 Query Rewriting 有東西可以修。"""

    def __init__(self, composer: ComposerClient, *, first_round_fail: bool, force_all_fail: bool) -> None:
        self.composer = composer
        self.first_round_fail = first_round_fail
        self.force_all_fail = force_all_fail

    async def parse_brief(self, brand: Brand, text: str, product: Product | None) -> ParsedBrief:
        return await self.composer.sim_brief(brand, product, text)

    async def build_spec(self, request: SpecRequest) -> PromptSpec:
        flawed = self.force_all_fail or (self.first_round_fail and request.round == 1)
        return await self.composer.sim_prompt(request, flawed)

    async def plan_rewrite(self, brand: Brand, spec: PromptSpec, checks: list[ReviewCheck]) -> Rewrite:
        fixes = await self.composer.sim_fixes(checks, brand, spec)
        failing = {c.id for c in checks if c.status != 'pass'}
        query = f'{brand.category} 禁用詞 合規替代用語' if failing & {'banned_words', 'vlm_exaggeration'} else None
        return Rewrite(fixes=fixes, query=query)


class SimImageEngine:
    """不生圖：回報與 mock 相同的 ComfyUI 進度，背景用程序化圖（前端依 seed 與色票繪製）。"""

    async def render_round(
        self, job_id: str, round: int, specs: list[PromptSpec], variants: int, brand: Brand, run: RunContext
    ) -> dict[tuple[TemplateId, int], RenderBackground]:
        for spec in specs:
            await run.emit(
                ComfyQueuedEvent(
                    type='comfy.queued',
                    round=round,
                    template_id=spec.template_id,
                    prompt_id=f'{job_id}_r{round}_{spec.template_id}',
                    injection=spec.injection,
                )
            )
        workflow = specs[0].injection.workflow_file
        await run.log('comfy', f'ws → ComfyUI /prompt × {len(specs)}（{workflow}，batch={variants}）')
        for node, (steps, ms) in RENDER_STEPS.items():
            for step in range(1, steps + 1):
                await run.pace(ms / steps)
                await run.emit(
                    RenderProgressEvent(type='render.progress', round=round, node=node, step=step, max_step=steps)
                )
            await run.log('comfy', f'✓ {NODE_LABEL[node]} 完成')
        return {
            (spec.template_id, v): ProceduralBackground(
                kind='procedural', seed=seed_of(spec) + v, palette=spec.palette, style=brand.id
            )
            for spec in specs
            for v in range(variants)
        }


class SimReviewer:
    def __init__(self, composer: ComposerClient) -> None:
        self.composer = composer

    async def review(self, brand: Brand, render: Render, seed: int) -> ReviewResult:
        return await self.composer.sim_review(render.spec, brand, render.variant, seed)


def sim_ports(composer: ComposerClient, *, first_round_fail: bool, force_all_fail: bool) -> Ports:
    return Ports(
        retriever=SimRetriever(),
        agent=SimAgent(composer, first_round_fail=first_round_fail, force_all_fail=force_all_fail),
        image=SimImageEngine(),
        reviewer=SimReviewer(composer),
    )
```

- [ ] **Step 13: 建立 `backend/app/pipeline/runner.py`**

```python
"""任務流程（Orchestrator）：階段與事件順序與前端 mock 劇本相同（web/src/lib/api/mock/scenario.ts）。

需求拆解 → RAG 檢索 → Rerank → 每一輪：Prompt 構建 → 生圖 → 排版 → 審查 → 未通過的模板 Query Rewriting 後重試
→ 寫入結果。重試以模板為單位。
模擬模式依 1× 時間軸等待（speed 倍速，0 為不等待）；真實版各步驟本身就會花時間。
"""

import asyncio
import math
import time
from dataclasses import dataclass

from app.contract import (
    Brand,
    BriefParsedEvent,
    ChannelTemplate,
    CheckId,
    JobCompletedEvent,
    JobEvent,
    JobFailedEvent,
    JobInput,
    JobNeedsReviewEvent,
    JobStage,
    JobStatusEvent,
    LogEvent,
    LogLevel,
    LogSource,
    Product,
    PromptGeneratedEvent,
    PromptSpec,
    RagRerankedEvent,
    RagRetrievedEvent,
    Render,
    RenderCompletedEvent,
    ReviewCheckEvent,
    ReviewCompletedEvent,
    RewriteStartedEvent,
    TemplateId,
)
from app.core.rng import Mulberry32, hash_string
from app.db.models import JobRow
from app.db.session import Database
from app.errors import AppError
from app.events import EventStore
from app.pipeline.ports import Ports, ReviewResult, SpecRequest
from app.repo import catalog, jobs
from app.templates import get_template

#: 1× 速度下各階段的時間（毫秒），與 mock 的 PHASE_MS 相同
PHASE_MS = {
    'parse': 800,
    'retrieve_start': 1100,
    'retrieved': 1600,
    'reranked': 2300,
    'prompt': 800,
    'compose': 300,
    'review': 1200,
    'rewrite': 800,
    'save': 400,
}
#: 取消旗標最多隔多久檢查一次（秒）
CANCEL_CHECK_INTERVAL = 0.25


class JobCancelled(Exception):
    pass


def truncate(s: str, n: int) -> str:
    return s[:n] + '…' if len(s) > n else s


def failure_reason(error: Exception) -> str:
    return error.message if isinstance(error, AppError) else f'{type(error).__name__}: {error}'


class JobRun:
    """一個任務的執行狀態：送出事件、log、依時間軸等待、檢查取消。"""

    def __init__(self, job_id: str, db: Database, store: EventStore, speed: float) -> None:
        self.job_id = job_id
        self.db = db
        self.store = store
        self.speed = speed
        self.round = 0
        self._checked_at = 0.0

    async def checkpoint(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._checked_at < CANCEL_CHECK_INTERVAL:
            return
        self._checked_at = now
        async with self.db.session() as s:
            if await jobs.cancel_requested(s, self.job_id):
                raise JobCancelled()

    async def emit(self, event: JobEvent) -> None:
        await self.checkpoint()
        if isinstance(event, JobStatusEvent):
            self.round = event.round
        await self.store.append(self.job_id, event)

    async def status(self, stage: JobStage, round: int) -> None:
        await self.emit(JobStatusEvent(type='job.status', stage=stage, round=round))

    async def log(self, source: LogSource, message: str, level: LogLevel = 'info') -> None:
        await self.emit(LogEvent(type='log', source=source, level=level, message=message))

    async def pace(self, ms: float) -> None:
        if self.speed <= 0 or ms <= 0:
            return
        remaining = ms / 1000 / self.speed
        while remaining > 0:
            step = min(CANCEL_CHECK_INTERVAL, remaining)
            await asyncio.sleep(step)
            remaining -= step
            await self.checkpoint(force=True)


@dataclass(frozen=True)
class JobContext:
    job_id: str
    job_input: JobInput
    brand: Brand
    product: Product
    templates: list[ChannelTemplate]


@dataclass(frozen=True)
class Reviewed:
    render: Render
    result: ReviewResult


async def run_job(job_id: str, db: Database, store: EventStore, ports: Ports, *, speed: float) -> None:
    """執行一個排隊中的任務。任務已不在排隊（例如已取消）時直接結束。"""
    run = JobRun(job_id, db, store, speed)
    claimed = await store.append(
        job_id, JobStatusEvent(type='job.status', stage='parsing', round=0), expect_stage='queued'
    )
    if claimed is None:
        return
    try:
        ctx = await _load(db, job_id)
        await _pipeline(run, ctx, ports)
    except JobCancelled:
        await store.append(job_id, JobStatusEvent(type='job.status', stage='cancelled', round=run.round))
    except Exception as error:  # noqa: BLE001 - 任何錯誤都要讓任務結束並回報原因
        reason = failure_reason(error)
        await store.append(job_id, LogEvent(type='log', source='api', level='error', message=reason))
        await store.append(job_id, JobFailedEvent(type='job.failed', job_id=job_id, reason=reason))
        await store.append(job_id, JobStatusEvent(type='job.status', stage='failed', round=run.round))


async def _load(db: Database, job_id: str) -> JobContext:
    async with db.session() as s:
        row = await s.get(JobRow, job_id)
        assert row is not None
        job_input = JobInput.model_validate(row.input)
        brand = await catalog.get_brand(s, job_input.brand_id)
        product = await catalog.get_product(s, job_input.product_id)
    if brand is None:
        raise AppError(f'找不到品牌：{job_input.brand_id}')
    if product is None:
        raise AppError(f'找不到商品：{job_input.product_id}（可能已被刪除）')
    templates = [get_template(t) for t in job_input.template_ids]
    return JobContext(job_id, job_input, brand, product, templates)


async def _pipeline(run: JobRun, ctx: JobContext, ports: Ports) -> None:
    job_id, inp, brand, product = ctx.job_id, ctx.job_input, ctx.brand, ctx.product
    job_seed = hash_string(job_id)
    rng = Mulberry32(job_seed)

    # 1. 需求拆解：沿用使用者在表單確認過的欄位
    await run.log('ws', f'→ job.create brand={brand.id} product={product.id} templates={",".join(inp.template_ids)}')
    await run.pace(300)
    await run.log('agent', f'{inp.llm}：拆解需求「{truncate(inp.brief, 24)}」')
    await run.pace(PHASE_MS['parse'] - 300)
    await run.emit(BriefParsedEvent(type='brief.parsed', parsed_brief=inp.parsed_brief))
    pb = inp.parsed_brief
    await run.log('agent', f'✓ 語氣={pb.tone}・檔期={pb.campaign or "無"}・優惠={pb.offer or "無"}', 'ok')

    # 2. RAG：召回 → Rerank
    await run.pace(PHASE_MS['retrieve_start'] - PHASE_MS['parse'])
    await run.status('retrieving', 0)
    await run.log('rag', f'embed query（bge-m3）→ similarity_search(collection="{brand.id}_ci")')
    query, hits = await ports.retriever.retrieve(brand, product, inp)
    await run.pace(PHASE_MS['retrieved'] - PHASE_MS['retrieve_start'])
    await run.emit(RagRetrievedEvent(type='rag.retrieved', query=query, hits=hits))
    await run.log('rag', f'召回 {len(hits)} 筆品牌規範')
    ranked = await ports.retriever.rerank(query, hits)
    await run.pace(PHASE_MS['reranked'] - PHASE_MS['retrieved'])
    await run.emit(RagRerankedEvent(type='rag.reranked', hits=ranked))
    await run.log('rag', f'✓ BGE Reranker 重新排序：{" > ".join(h.tag for h in ranked)}', 'ok')
    rag_refs = [h.chunk_id for h in ranked]

    round = 1
    pending = list(ctx.templates)
    fixes_next: list[CheckId] = []
    best: dict[TemplateId, str] = {}
    requeried = False
    success = False
    while True:
        # 3. Prompt 構建
        await run.status('prompting', round)
        specs: list[PromptSpec] = []
        for template in pending:
            seed = 100_000_000 + math.floor(rng() * 900_000_000)
            request = SpecRequest(
                job_id, round, brand, product, inp.parsed_brief, template, inp.engine, seed, list(rag_refs), fixes_next
            )
            specs.append(await ports.agent.build_spec(request))
        for spec in specs:
            await run.pace(PHASE_MS['prompt'] / len(specs))
            await run.emit(
                PromptGeneratedEvent(type='prompt.generated', round=round, template_id=spec.template_id, spec=spec)
            )
        boxes = len(specs[0].layout)
        await run.log('agent', f'✓ 第 {round} 輪 JSON Prompt：{len(specs)} 個模板 × {boxes} 個 BBox', 'ok')

        # 4. 生圖
        await run.status('rendering', round)
        backgrounds = await ports.image.render_round(job_id, round, specs, inp.variants_per_template, brand, run)
        renders = [
            Render(
                id=f'{job_id}_r{round}_{spec.template_id}_v{v}',
                job_id=job_id,
                round=round,
                template_id=spec.template_id,
                variant=v,
                background=backgrounds[(spec.template_id, v)],
                spec=spec,
                score=None,
                passed=None,
                checks=[],
            )
            for spec in specs
            for v in range(inp.variants_per_template)
        ]
        await run.emit(RenderCompletedEvent(type='render.completed', round=round, renders=renders))

        # 5. 文字排版合成
        await run.status('composing', round)
        await run.log('compose', f'排版引擎疊加文字圖層（{len(renders)} 張）')
        await run.pace(PHASE_MS['compose'])

        # 6. 合規審查（規則 + VLM）
        await run.status('reviewing', round)
        await run.log('vlm', f'{inp.vlm}：審查 {len(renders)} 張 × 10 項')
        reviewed = [Reviewed(r, await ports.reviewer.review(brand, r, hash_string(r.id) ^ job_seed)) for r in renders]
        dt = PHASE_MS['review'] / max(1, sum(len(x.result.checks) for x in reviewed))
        for x in reviewed:
            for check in x.result.checks:
                await run.pace(dt)
                await run.emit(ReviewCheckEvent(type='review.check', round=round, render_id=x.render.id, check=check))
            await run.emit(
                ReviewCompletedEvent(
                    type='review.completed',
                    round=round,
                    render_id=x.render.id,
                    score=x.result.score,
                    passed=x.result.passed,
                )
            )

        def by_score(template_id: TemplateId, round_reviews: list[Reviewed] = reviewed) -> list[Reviewed]:
            return sorted(
                (x for x in round_reviews if x.render.template_id == template_id), key=lambda x: -x.result.score
            )

        failed: list[ChannelTemplate] = []
        for template in pending:
            top = next((x for x in by_score(template.id) if x.result.passed), None)
            if top is not None:
                best[template.id] = top.render.id
            else:
                failed.append(template)
        passed = len(pending) - len(failed)
        await run.log('vlm', f'第 {round} 輪：{passed}/{len(pending)} 個模板通過', 'warn' if failed else 'ok')
        if not failed:
            success = True
            break
        if round > inp.max_retries:
            break

        # 7. Query Rewriting（必要時重新檢索合規用語）
        await run.status('rewriting', round)
        reasons: list[CheckId] = []
        requery: str | None = None
        for template in failed:
            top = by_score(template.id)[0]
            failing = [c.id for c in top.result.checks if c.status != 'pass']
            reasons += [c for c in failing if c not in reasons]
            rewrite = await ports.agent.plan_rewrite(brand, top.render.spec, top.result.checks)
            requery = requery or rewrite.query
            await run.emit(
                RewriteStartedEvent(
                    type='rewrite.started',
                    round=round,
                    template_id=template.id,
                    reasons=failing,
                    fixes=rewrite.fixes,
                    requery=rewrite.query is not None and not requeried,
                )
            )
        await run.log('api', f'觸發 Query Rewriting（重試 {round}/{inp.max_retries}）', 'warn')
        if requery is not None and not requeried:
            await run.pace(PHASE_MS['rewrite'] / 2)
            requery_hits = await ports.retriever.requery(brand, requery)
            await run.emit(RagRetrievedEvent(type='rag.retrieved', query=requery, hits=requery_hits))
            for hit in requery_hits:
                await run.log('rag', f're-query → {hit.chunk_id}（{hit.vector_score}）', 'ok')
            rag_refs += [h.chunk_id for h in requery_hits if h.chunk_id not in rag_refs]
            requeried = True
            await run.pace(PHASE_MS['rewrite'] / 2)
        else:
            await run.pace(PHASE_MS['rewrite'])
        fixes_next = fixes_next + [c for c in reasons if c not in fixes_next]
        pending = failed
        round += 1

    # 8. 寫入結果；結束的 job.status 一定是最後一則事件
    await run.status('saving', round)
    await run.log('db', f'INSERT INTO renders（{len(best)} 張最佳候選）')
    await run.pace(PHASE_MS['save'])
    if success:
        await run.emit(JobCompletedEvent(type='job.completed', job_id=job_id, best_render_ids=best))
        await run.log('ws', '← job.completed', 'ok')
        await run.status('done', round)
    else:
        reason = '已達最大重試次數，仍未通過合規審查'
        await run.emit(JobNeedsReviewEvent(type='job.needs_review', job_id=job_id, reason=reason))
        await run.log('ws', '← job.needs_review', 'warn')
        await run.status('needs_review', round)
```

- [ ] **Step 14: 執行測試確認通過**

Run: `uv run pytest -q`
Expected: PASS，37 passed（`test_pipeline.py` 5 個、`test_parity.py` 3 個、`test_contract.py` 8 個）。

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: 沒有錯誤。

- [ ] **Step 15: Commit**

```bash
git add \
  backend/app/adapters/__init__.py \
  backend/app/adapters/composer.py \
  backend/app/pipeline/__init__.py \
  backend/app/pipeline/ports.py \
  backend/app/pipeline/runner.py \
  backend/app/pipeline/sim.py \
  backend/app/settings.py \
  backend/app/templates.py \
  backend/tests/conftest.py \
  backend/tests/test_contract.py \
  backend/tests/test_parity.py \
  backend/tests/test_pipeline.py
git commit -m "feat: run the job pipeline with simulated adapters that match the mock timeline" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: SAQ worker：生圖任務、去背、文件上傳、回寫與啟動時復原


**Files:**
- Create: `backend/app/queues.py`、`backend/app/worker.py`
- Modify: `backend/app/repo/history.py`、`backend/pyproject.toml`
- Test: `backend/tests/test_worker.py`

**Interfaces:**
- Consumes：Task 9 的 `run_job`、`sim_ports`、`ComposerClient`；Task 7 的 `EventStore`、`app.repo`
- Produces：
  - `Queues(redis_url)`：
    - 連線：`connect()`、`disconnect()`；兩個佇列 `jobs`、`tasks`。
    - `enqueue_job(job_id)`：key 為任務 id，不會重複排入；不設逾時。
    - `enqueue_task(name, **kwargs)`。
    - `run_task(name, wait, **kwargs) -> TaskResult(completed, result)`：最多等 `wait` 秒；工作失敗時丟出 `RuntimeError`。
  - `app.worker`：
    - `Services(db, redis, store, composer, ports, speed)`、`build_services()`。
    - `cutout(services, product_id)`：回傳 `{'product': ...}` 或 `{'error': ...}`。
    - `ingest(services, task_id, brand_id, name, text)`：每一步發布到 `ingest:{task_id}`；錯誤為 `{'error': {code, message}}`。
    - `write_back(services, history_id) -> bool`。
    - `recover(services, queues)`：執行中的任務標記失敗（`RESTART_REASON`），排隊中的重新放回佇列。
    - `build_workers(services, queues)`：`jobs` 同時 1 個、`tasks` 同時 2 個。
    - `main()`：`uv run python -m app.worker`。
  - `history.mark_written(session, history_id) -> bool`

SAQ 的注意事項：
- 預設逾時 10 秒，所以生圖任務以 `timeout=0` 排入。
- 函式預設以 `__qualname__` 註冊，這裡以 `('run_job', fn)` 指定名稱。
- 工作丟出例外時 SAQ 只保存 traceback，所以任務以 `{'error': ...}` 回傳可顯示的錯誤。

- [ ] **Step 1: 修改 `backend/pyproject.toml`**（SAQ 在 redis-py 8 上呼叫已棄用的 `setex`）

找到：

```toml
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"

[tool.ruff]
line-length = 120
```

改成：

```toml
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
# SAQ 0.26 在 redis-py 8 上呼叫已棄用的 setex
filterwarnings = ["ignore:Call to deprecated setex:DeprecationWarning"]

[tool.ruff]
line-length = 120
```

- [ ] **Step 2: 建立 `backend/tests/test_worker.py`**（先寫失敗測試）

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

from app.adapters.composer import ComposerClient
from app.brands import load_brands
from app.contract import FilePhoto, JobAcceptedEvent, JobInput, JobStatusEvent, Price, ProductDraft
from app.db.session import Database
from app.events import EventStore
from app.pipeline.sim import sim_ports
from app.queues import Queues
from app.repo import catalog, jobs
from app.worker import RESTART_REASON, Services, build_workers, cutout, ingest, ingest_channel, recover
from tests.conftest import TEST_REDIS_URL
from tests.fixtures import BRANDS_DIR, load_fixture

NOW = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)


@pytest.fixture
async def services(db: Database, redis: Redis, composer_url: str) -> AsyncIterator[Services]:
    composer = ComposerClient(composer_url)
    ports = sim_ports(composer, first_round_fail=True, force_all_fail=False)
    async with db.session() as s:
        await catalog.sync_brands(s, load_brands(BRANDS_DIR)[0], NOW)
    yield Services(db, redis, EventStore(db, redis), composer, ports, speed=0)
    await composer.aclose()
    await db.truncate_all()


@pytest.fixture
async def queues(redis: Redis) -> AsyncIterator[Queues]:
    await redis.flushdb()
    q = Queues(TEST_REDIS_URL)
    await q.connect()
    yield q
    await q.disconnect()


@asynccontextmanager
async def running(services: Services, queues: Queues) -> AsyncIterator[None]:
    workers = build_workers(services, queues)
    started = [asyncio.create_task(w.start()) for w in workers]
    try:
        yield
    finally:
        for w in workers:
            await w.stop()
        await asyncio.gather(*started, return_exceptions=True)


async def queued_job(services: Services, job_id: str) -> None:
    data = load_fixture('timelines/selune-retry.json')
    async with services.db.session() as s:
        await jobs.create_job(s, job_id, JobInput.model_validate(data['input']), NOW)
    await services.store.append(job_id, JobAcceptedEvent(type='job.accepted', job_id=job_id))
    await services.store.append(job_id, JobStatusEvent(type='job.status', stage='queued', round=0))


async def summary(services: Services, job_id: str) -> Any:
    async with services.db.session() as s:
        snap = await jobs.get_job(s, job_id)
    assert snap is not None
    return snap.summary


async def test_runs_queued_jobs_one_at_a_time(services: Services, queues: Queues) -> None:
    await queued_job(services, 'job_w1')
    await queued_job(services, 'job_w2')
    await queues.enqueue_job('job_w1')
    await queues.enqueue_job('job_w2')
    await queues.enqueue_job('job_w1')
    async with running(services, queues):
        for _ in range(150):
            if (await summary(services, 'job_w2')).finished:
                break
            await asyncio.sleep(0.2)
    assert [(await summary(services, j)).stage for j in ('job_w1', 'job_w2')] == ['done', 'done']


async def test_recovery_fails_running_jobs_and_requeues_queued_ones(services: Services, queues: Queues) -> None:
    await queued_job(services, 'job_running')
    await services.store.append('job_running', JobStatusEvent(type='job.status', stage='rendering', round=1))
    await queued_job(services, 'job_waiting')
    await recover(services, queues)
    stopped = await summary(services, 'job_running')
    assert (stopped.stage, stopped.round, stopped.finished) == ('failed', 1, True)
    async with services.db.session() as s:
        snap = await jobs.get_job(s, 'job_running')
    assert snap is not None
    assert snap.events[-2]['reason'] == RESTART_REASON
    assert await queues.jobs.job('job_waiting') is not None


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
    assert done.result['product']['cutout'] == {'model': 'BiRefNet-general', 'url': None}
    assert await cutout(services, 'prod_selune_serum') == {'error': '示範商品已是去背素材'}


async def collect_ingest(services: Services, task_id: str, name: str, text: str) -> list[dict[str, Any]]:
    pubsub = services.redis.pubsub()
    await pubsub.subscribe(ingest_channel(task_id))
    await ingest(services, task_id, 'misty-isle', name, text)
    messages: list[dict[str, Any]] = []
    for _ in range(50):
        raw = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
        if raw is None:
            continue
        messages.append(json.loads(raw['data']))
        if 'error' in messages[-1] or messages[-1]['type'] == 'ingest.stored':
            break
    await pubsub.aclose()  # type: ignore[no-untyped-call]
    return messages


async def test_ingest_reports_each_step_and_stores_the_chunks(services: Services) -> None:
    text = '# 色彩更新\n主色維持 #2F4A44。\n\n# Logo\n- 深色背景使用反白 Logo\n\n2026 春季素材 CTR 3.9%。'
    messages = await collect_ingest(services, 't1', 'ci_update.md', text)
    assert [m['type'] for m in messages] == ['ingest.chunked'] + ['ingest.embedded'] * 3 + ['ingest.stored']
    assert messages[-1] == {'type': 'ingest.stored', 'collection': 'misty-isle_ci', 'count': 3}
    async with services.db.session() as s:
        brand = await catalog.get_brand(s, 'misty-isle')
    assert brand is not None
    assert [c.source for c in brand.guideline_chunks].count('ci_update.md') == 3
    assert await collect_ingest(services, 't2', 'empty.md', '   ') == [
        {'error': {'code': 'invalid', 'message': '文件沒有可用的文字內容'}}
    ]
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `uv run pytest tests/test_worker.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.queues'`。

- [ ] **Step 4: 修改 `backend/app/repo/history.py`**（回寫後標記）

找到：

```python
    return [HistoryEntry.model_validate(r.data) for r in await session.scalars(query)]


async def set_favorite(session: AsyncSession, history_id: str, favorite: bool) -> HistoryEntry | None:
    row = await session.get(HistoryRow, history_id)
    if row is None:
```

改成：

```python
    return [HistoryEntry.model_validate(r.data) for r in await session.scalars(query)]


async def mark_written(session: AsyncSession, history_id: str) -> bool:
    """回寫成歷史案例後標記 writtenToRag。"""
    row = await session.get(HistoryRow, history_id)
    if row is None:
        return False
    row.data = {**row.data, 'writtenToRag': True}
    await session.commit()
    return True


async def set_favorite(session: AsyncSession, history_id: str, favorite: bool) -> HistoryEntry | None:
    row = await session.get(HistoryRow, history_id)
    if row is None:
```

- [ ] **Step 5: 建立 `backend/app/queues.py`**

```python
"""SAQ 佇列：api 放入工作，worker 執行。

- jobs：生圖任務，一次只執行一個（只有一張 GPU）；key 為任務 id，同一個任務不會重複排入。
- tasks：去背、文件上傳、回寫歷史案例，最多同時兩個，不必等生圖任務。
"""

from dataclasses import dataclass
from typing import Any

from saq import Queue
from saq.job import Status

JOBS = 'jobs'
TASKS = 'tasks'
#: tasks 佇列裡單一工作最長的執行時間（秒）
TASK_TIMEOUT = 600


@dataclass(frozen=True)
class TaskResult:
    #: 在等待時間內完成
    completed: bool
    result: Any


class Queues:
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

    async def enqueue_task(self, name: str, **kwargs: Any) -> None:
        await self.tasks.enqueue(name, timeout=TASK_TIMEOUT, **kwargs)

    async def run_task(self, name: str, wait: float, **kwargs: Any) -> TaskResult:
        """放入 tasks 佇列並最多等 wait 秒；沒等到時工作仍在背景繼續。失敗時丟出 RuntimeError。"""
        job = await self.tasks.enqueue(name, timeout=TASK_TIMEOUT, **kwargs)
        assert job is not None
        await job.refresh(until_complete=wait)
        if job.status == Status.COMPLETE:
            return TaskResult(True, job.result)
        if job.status in (Status.FAILED, Status.ABORTED):
            raise RuntimeError(f'背景工作 {name} 失敗：{job.error}')
        return TaskResult(False, None)
```

- [ ] **Step 6: 建立 `backend/app/worker.py`**

```python
"""SAQ worker：uv run python -m app.worker

- jobs 佇列：run_job（生圖任務，一次一個）
- tasks 佇列：cutout（去背）、ingest（品牌文件上傳）、write_back（選定海報回寫成歷史案例），最多同時兩個
- 啟動時復原：原本執行中的任務標記失敗（不自動重跑），排隊中的任務重新放回佇列
"""

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from saq import Worker
from saq.types import Context
from sqlalchemy import select

from app.adapters.composer import ComposerClient
from app.contract import (
    BrandDocument,
    IngestChunkedEvent,
    IngestEmbeddedEvent,
    IngestStoredEvent,
    JobFailedEvent,
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
from app.queues import Queues
from app.repo import catalog, history
from app.settings import settings

RESTART_REASON = 'worker 重新啟動，任務中斷'


def ingest_channel(task_id: str) -> str:
    return f'ingest:{task_id}'


@dataclass
class Services:
    db: Database
    redis: Redis
    store: EventStore
    composer: ComposerClient
    ports: Ports
    #: 模擬模式的播放速度（0 為不等待）
    speed: float

    async def pace(self, ms: float) -> None:
        if self.speed > 0:
            await asyncio.sleep(ms / 1000 / self.speed)


def build_services() -> Services:
    db = Database(settings.database_url)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    composer = ComposerClient(settings.composer_url)
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
    cut = ProductCutout(model='BiRefNet-general', url=None)
    draft = ProductDraft.model_validate({**fields, 'cutout': cut.to_json()})
    async with services.db.session() as s:
        saved = await catalog.save_product(s, draft, utc_now())
    return {'product': saved.to_json()}


async def ingest(services: Services, task_id: str, brand_id: str, name: str, text: str) -> None:
    """品牌文件：切塊 → 向量化（模擬）→ 寫入；每一步發布到 Redis 頻道 ingest:{task_id}，api 以 NDJSON 串流轉給前端。"""

    async def send(message: dict[str, Any]) -> None:
        await services.redis.publish(ingest_channel(task_id), json.dumps(message, ensure_ascii=False))

    try:
        async with services.db.session() as s:
            if await catalog.get_brand(s, brand_id) is None:
                raise NotFound(f'找不到品牌：{brand_id}')
        result = await services.composer.sim_ingest(brand_id, BrandDocument(name=name, text=text))
        chunks = [c for c, _ in result.chunks]
        if not chunks:
            raise AppError('文件沒有可用的文字內容')
        await services.pace(400)
        await send(IngestChunkedEvent(type='ingest.chunked', source=name, chunks=chunks).to_json())
        for i, (chunk, preview) in enumerate(result.chunks):
            await services.pace(250)
            embedded = IngestEmbeddedEvent(
                type='ingest.embedded', chunk_id=chunk.id, index=i, total=len(chunks), dims=result.dims, preview=preview
            )
            await send(embedded.to_json())
        async with services.db.session() as s:
            await catalog.replace_document_chunks(s, brand_id, name, chunks, utc_now())
        await services.pace(300)
        await send(IngestStoredEvent(type='ingest.stored', collection=f'{brand_id}_ci', count=len(chunks)).to_json())
    except Exception as error:  # noqa: BLE001 - 錯誤一律轉給前端
        await send({'error': {'code': 'invalid', 'message': failure_reason(error)}})


async def write_back(services: Services, history_id: str) -> bool:
    """選定的海報回寫成歷史案例（模擬：只標記已回寫；Plan 5 改為寫入 Chroma）。"""
    async with services.db.session() as s:
        return await history.mark_written(s, history_id)


async def recover(services: Services, queues: Queues) -> None:
    async with services.db.session() as s:
        rows = (await s.scalars(select(JobRow).where(JobRow.finished.is_(False)).order_by(JobRow.created_at))).all()
    for row in rows:
        if row.stage == 'queued':
            await queues.enqueue_job(row.id)
            continue
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

    async def write_back_fn(ctx: Context, *, history_id: str) -> bool:
        return await write_back(services, history_id)

    jobs = Worker(queues.jobs, [('run_job', run_job_fn)], concurrency=1, **options)
    tasks = Worker(
        queues.tasks,
        [('cutout', cutout_fn), ('ingest', ingest_fn), ('write_back', write_back_fn)],
        concurrency=2,
        **options,
    )
    return jobs, tasks


async def main() -> None:
    services = build_services()
    queues = Queues(settings.redis_url)
    await queues.connect()
    await recover(services, queues)
    jobs, tasks = build_workers(services, queues)
    try:
        await asyncio.gather(jobs.start(), tasks.start())
    finally:
        await queues.disconnect()
        await services.composer.aclose()
        await services.db.dispose()


if __name__ == '__main__':
    asyncio.run(main())
```

- [ ] **Step 7: 執行測試確認通過**

Run: `uv run pytest -q`
Expected: PASS，41 passed（`test_worker.py` 4 個）。

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: 沒有錯誤。

- [ ] **Step 8: Commit**

```bash
git add \
  backend/app/queues.py \
  backend/app/repo/history.py \
  backend/app/worker.py \
  backend/pyproject.toml \
  backend/tests/test_worker.py
git commit -m "feat: add the SAQ worker with job and task queues and startup recovery" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: 成效儀表板統計移植到 Python


**Files:**
- Create: `backend/app/stats.py`
- Test: `backend/tests/test_stats.py`

**Interfaces:**
- Consumes：Task 3 的 `stats.json`；Task 4 的 `JobSnapshot`、`DashboardStats`
- Produces：`dashboard_stats(snapshots: list[JobSnapshot]) -> DashboardStats`（只統計完成與需人工審核的任務）、`job_cost`、`job_stat`、`rerank_hit_curve`、`UNIT_COST_USD`。結果與 `web/src/lib/stats/dashboard.ts` 完全相同（浮點數依序相加）。

- [ ] **Step 1: 建立 `backend/tests/test_stats.py`**（先寫失敗測試）

```python
"""儀表板統計與前端（web/src/lib/stats/dashboard.ts）的結果完全相同。"""

import pytest

from app.contract import JobSnapshot
from app.stats import dashboard_stats
from tests.fixtures import load_fixture


def snapshots(brand_id: str | None) -> list[JobSnapshot]:
    snaps = [JobSnapshot.model_validate(s) for s in load_fixture('stats.json')['snapshots']]
    return [s for s in snaps if brand_id is None or s.summary.input.brand_id == brand_id]


@pytest.mark.parametrize('case', range(3))
def test_matches_the_frontend_dashboard(case: int) -> None:
    expected = load_fixture('stats.json')['cases'][case]
    assert dashboard_stats(snapshots(expected['brandId'])).to_json() == expected['stats']


def test_cancelled_and_failed_jobs_are_left_out() -> None:
    stats = dashboard_stats(snapshots(None))
    assert stats.jobs == 6
    assert {j.job_id for j in stats.recent}.isdisjoint({'job_sample_cancelled', 'job_sample_failed'})


def test_empty_stats() -> None:
    stats = dashboard_stats([])
    assert (stats.jobs, stats.pass_rate, stats.cost_per_image, stats.rerank_hits, stats.recent) == (0, 0, None, [], [])
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_stats.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.stats'`。

- [ ] **Step 3: 建立 `backend/app/stats.py`**

```python
"""成效儀表板：web/src/lib/stats/dashboard.ts 的移植，結果必須完全相同（tests/test_stats.py）。

只統計已結束的任務（完成或需人工審核）；取消與失敗的不列入。事件保持原始 JSON。
浮點數一律依序相加（_fsum）：Python 3.12 起 sum() 對浮點數做補償加總，結果可能和 JavaScript 的 reduce 不同。
"""

from typing import Any

from app.contract import (
    CHECK_IDS,
    CheckFailureStat,
    CheckId,
    DashboardStats,
    JobSnapshot,
    JobStat,
    RerankHitStat,
)
from app.core.clock import parse_iso

#: 估算單價（美元）；Plan 5、6 改用實際用量
UNIT_COST_USD = {
    'llm_call': 0.0006,
    'rerank': 0.0002,
    'comfy_image': 0.0042,
    'ideogram_image': 0.06,
    'vlm_review': 0.0011,
}
RECENT = 8

Message = dict[str, Any]


def _fsum(values: list[float]) -> float:
    total = 0.0
    for v in values:
        total += v
    return total


def _count(events: list[Message], kind: str) -> int:
    return sum(1 for e in events if e['type'] == kind)


def _render_count(events: list[Message]) -> int:
    return sum(len(e['renders']) for e in events if e['type'] == 'render.completed')


def job_cost(snap: JobSnapshot) -> float:
    events = snap.events
    image = UNIT_COST_USD['ideogram_image'] if snap.summary.input.engine == 'ideogram' else UNIT_COST_USD['comfy_image']
    llm_calls = _count(events, 'brief.parsed') + _count(events, 'prompt.generated') + _count(events, 'rewrite.started')
    return (
        UNIT_COST_USD['llm_call'] * llm_calls
        + UNIT_COST_USD['rerank'] * _count(events, 'rag.reranked')
        + image * _render_count(events)
        + UNIT_COST_USD['vlm_review'] * _count(events, 'review.completed')
    )


def job_stat(snap: JobSnapshot) -> JobStat | None:
    s = snap.summary
    if not s.finished or s.stage not in ('done', 'needs_review'):
        return None
    first, last = (snap.events[0], snap.events[-1]) if snap.events else (None, None)
    duration = parse_iso(last['ts']) - parse_iso(first['ts']) if first and last else None
    return JobStat(
        job_id=s.id,
        brand_id=s.input.brand_id,
        created_at=s.created_at,
        outcome=s.stage,
        templates=len(s.input.template_ids),
        rounds=s.round,
        renders=_render_count(snap.events),
        delivered=len(s.best_render_ids),
        duration_ms=round(duration.total_seconds() * 1000) if duration is not None else 0,
        cost_usd=job_cost(snap),
    )


def _first_round_passed(events: list[Message]) -> int:
    template_of: dict[str, str] = {}
    passed: set[str] = set()
    for e in events:
        if e['type'] == 'render.completed' and e['round'] == 1:
            for r in e['renders']:
                template_of[r['id']] = r['templateId']
        if e['type'] == 'review.completed' and e['round'] == 1 and e['passed']:
            t = template_of.get(e['renderId'])
            if t:
                passed.add(t)
    return len(passed)


def rerank_hit_curve(events: list[Message]) -> tuple[list[float], list[float]] | None:
    """前 k 筆（k = 1…n）涵蓋審查未通過項目所引用規範的比例；沒有可比較的引用時回傳 None。"""
    retrieved = next((e for e in events if e['type'] == 'rag.retrieved'), None)
    reranked = next((e for e in events if e['type'] == 'rag.reranked'), None)
    if retrieved is None or reranked is None:
        return None
    vector_order = [h['chunkId'] for h in sorted(retrieved['hits'], key=lambda h: -h['vectorScore'])]
    rerank_order = [h['chunkId'] for h in reranked['hits']]
    cited = {
        e['check']['ragRef']
        for e in events
        if e['type'] == 'review.check' and e['check']['status'] != 'pass' and e['check']['ragRef']
    }
    relevant = [i for i in vector_order if i in cited]
    if not relevant:
        return None

    def curve(order: list[str]) -> list[float]:
        return [sum(1 for i in relevant if i in order[: k + 1]) / len(relevant) for k in range(len(order))]

    return curve(vector_order), curve(rerank_order)


def _check_failures(snaps: list[JobSnapshot]) -> list[CheckFailureStat]:
    stats: dict[CheckId, CheckFailureStat] = {}
    for snap in snaps:
        for e in snap.events:
            if e['type'] != 'review.check':
                continue
            c = e['check']
            s = stats.setdefault(
                c['id'], CheckFailureStat(check_id=c['id'], name=c['name'], kind=c['kind'], fail=0, warn=0)
            )
            if c['status'] == 'fail':
                s.fail += 1
            if c['status'] == 'warn':
                s.warn += 1
    return [stats[i] for i in CHECK_IDS if i in stats]


def _rerank_hits(snaps: list[JobSnapshot]) -> list[RerankHitStat]:
    curves = [c for c in (rerank_hit_curve(s.events) for s in snaps) if c is not None]
    if not curves:
        return []
    n = min(len(v) for v, _ in curves)

    def avg(values: list[float]) -> float:
        return _fsum(values) / len(curves)

    return [
        RerankHitStat(k=i + 1, vector=avg([v[i] for v, _ in curves]), rerank=avg([r[i] for _, r in curves]))
        for i in range(n)
    ]


def _mean(values: list[float]) -> float:
    return _fsum(values) / len(values) if values else 0


def dashboard_stats(snaps: list[JobSnapshot]) -> DashboardStats:
    finished = [(snap, stat) for snap in snaps if (stat := job_stat(snap)) is not None]
    stats = [s for _, s in finished]
    templates = sum(s.templates for s in stats)
    delivered = sum(s.delivered for s in stats)
    cost = _fsum([s.cost_usd for s in stats])
    finished_snaps = [snap for snap, _ in finished]
    return DashboardStats(
        jobs=len(stats),
        renders=sum(s.renders for s in stats),
        pass_rate=sum(1 for s in stats if s.outcome == 'done') / len(stats) if stats else 0,
        first_pass_rate=sum(_first_round_passed(s.events) for s in finished_snaps) / templates if templates else 0,
        avg_retries=_mean([s.rounds - 1 for s in stats]),
        avg_duration_ms=_mean([s.duration_ms for s in stats]),
        cost_per_image=cost / delivered if delivered else None,
        check_failures=_check_failures(finished_snaps),
        rerank_hits=_rerank_hits(finished_snaps),
        recent=sorted(stats, key=lambda s: s.created_at, reverse=True)[:RECENT],
    )
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest -q`
Expected: PASS，46 passed（`test_stats.py` 5 個）。

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: 沒有錯誤。

- [ ] **Step 5: Commit**

```bash
git add \
  backend/app/stats.py \
  backend/tests/test_stats.py
git commit -m "feat: port the dashboard stats to Python with parity tests" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: FastAPI：REST、WebSocket 與檔案


**Files:**
- Create: `backend/app/api/__init__.py`、`backend/app/api/services.py`、`backend/app/api/catalog.py`、`backend/app/api/jobs.py`、`backend/app/api/files.py`、`backend/app/api/main.py`
- Modify: `backend/pyproject.toml`、`backend/uv.lock`、`backend/app/settings.py`、`backend/app/errors.py`、`backend/app/queues.py`、`backend/app/worker.py`、`backend/app/events.py`、`backend/app/repo/jobs.py`
- Test: `backend/tests/conftest.py`、`backend/tests/test_api_catalog.py`、`backend/tests/test_api_jobs.py`、`backend/tests/test_worker.py`

**Interfaces:**
- Consumes：Task 6–11 的所有後端模組
- Produces（規格第 8 節的全部端點）：

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/api/health` | 容器健康檢查 |
| GET | `/api/options` | `{ llm: [LLM_MODEL], vlm: [VLM_MODEL], engines: ['comfyui'] }` |
| GET | `/api/status` | db、redis、worker、composer、品牌設定檔（實際檢查，各最多 3 秒），RAG、Gemini、ComfyUI 為模擬 |
| GET | `/api/brands` | 品牌（含上傳文件的切塊） |
| POST | `/api/brands/{id}/documents` | NDJSON 串流：每行一則 `IngestEvent`，或 `{ error }` |
| GET | `/api/templates` | 通路模板 |
| GET | `/api/products?brandId=` | 商品 |
| POST | `/api/products` | 新增（不可指定 id）→ 201 |
| PUT | `/api/products/{id}` | 修改；id 不存在時以該 id 新增 |
| DELETE | `/api/products/{id}` | 204；找不到時 404 |
| POST | `/api/products/photos` | multipart `file`：PNG、JPEG、WebP，最大 20 MB → `{ source: 'upload', url: '/files/uploads/…' }` |
| POST | `/api/products/{id}/cutout` | 交給 worker，最多等 30 秒 |
| GET | `/api/local-photos` | `assets/products/` 的照片（依檔名排序） |
| POST | `/api/local-photos/{file}/import` | `{ brandId }` → 新商品 |
| POST | `/api/briefs/parse` | `{ brandId, text, productId }` → `ParsedBrief` |
| POST | `/api/jobs` | 驗證後建立 → `{ jobId }` |
| GET | `/api/jobs`、`/api/jobs/{id}` | 任務列表、`JobSnapshot` |
| POST | `/api/jobs/{id}/cancel` | 204 |
| WS | `/ws/jobs/{id}?after={seq}` | 任務結束、事件送完後以 1000 關閉；任務不存在時 4404 |
| POST | `/api/jobs/{id}/select` | `{ renderId, copy }` → `HistoryEntry`（回寫完成時 `writtenToRag: true`） |
| GET | `/api/history?brandId=` | 歷史紀錄 |
| PATCH | `/api/history/{id}` | `{ favorite }` |
| GET | `/api/stats?brandId=` | `DashboardStats`（最近 200 個已結束的任務） |
| GET | `/files/{path}` | `uploads/…` → `data/`；`local/…` → `assets/products/`；`brands/…` → `brands/`；只提供圖片，不可超出資料夾 |

- 其他輸出：
  - `create_app(services=None)`、`app`（`uvicorn app.api.main:app`）。
  - `ApiServices`、`start_services(settings)`：連線、migration、匯入品牌設定檔。
  - `Services`：FastAPI 依賴。
- 錯誤格式 `{ error: { code, message } }`：

  | 錯誤 | 狀態 |
  |---|---|
  | `AppError` | 自己的 status |
  | 請求格式錯誤 | 400 |
  | 找不到網址 | 404 |
  | composer 錯誤 | 503 |
  | 其他例外 | 500 |
- 對既有模組的調整：
  - `ingest_channel(task_id)` 從 `worker.py` 移到 `queues.py`：api 不應 import worker（Plan 5 之後 worker 會載入模型）。
  - `enqueue_task`、`run_task` 的工作名稱改為只能用位置傳入：文件上傳工作本身有一個名為 `name` 的參數。
  - `EventStore.stream` 的型別改為 `AsyncGenerator`（可用 `aclosing` 關閉）。
  - `repo.jobs` 新增 `get_summary`、`finished_snapshots(session, brand_id=None)`。
  - `errors.Unavailable`（503）。
  - 設定 `timezone`（任務 id 使用的本地時間，預設 `Asia/Taipei`；Windows 沒有時區資料，所以加入 `tzdata`）、`llm_model`、`vlm_model`。
- 測試 fixture `api`（`LiveApi`）：
  - 在測試的 event loop 內以 uvicorn 執行 api（隨機埠），`data/` 與本機資料夾指向 `tmp_path`。
  - `api.http`（httpx）、`api.ws_url`。
  - `api.worker(speed)`：需要時才啟動 worker。

- [ ] **Step 1: 修改 `backend/pyproject.toml`**（加入 tzdata）

找到：

```toml
    "redis>=8.1.0",
    "saq>=0.26.4",
    "sqlalchemy[asyncio]>=2.1.3",
    "uvicorn[standard]>=0.54.0",
]
```

改成：

```toml
    "redis>=8.1.0",
    "saq>=0.26.4",
    "sqlalchemy[asyncio]>=2.1.3",
    "tzdata>=2026.5",
    "uvicorn[standard]>=0.54.0",
]
```

Run: `uv sync`
Expected: 安裝 tzdata，`uv.lock` 更新。

- [ ] **Step 2: 修改 `backend/tests/conftest.py`**（先寫失敗測試：`api` fixture）

找到（1／2）：

```python
每次測試開始時重建 genai_test 資料庫並跑 migration；每個測試結束後清空所有資料表。
"""

import os
import subprocess
import time
from collections.abc import AsyncIterator, Iterator

import asyncpg
import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.settings import REPO_ROOT, settings

TEST_DATABASE = 'genai_test'
#: 測試使用 Redis 的第 15 個資料庫，開始時清空
```

改成：

```python
每次測試開始時重建 genai_test 資料庫並跑 migration；每個測試結束後清空所有資料表。
"""

import asyncio
import os
import subprocess
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import httpx
import pytest
import uvicorn
from redis.asyncio import Redis
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.composer import ComposerClient
from app.api.main import create_app
from app.api.services import ApiServices
from app.db.session import Database
from app.events import EventStore
from app.pipeline.sim import SimAgent, sim_ports
from app.queues import Queues
from app.settings import REPO_ROOT, Settings, settings
from app.worker import Services as WorkerServices
from app.worker import build_workers

TEST_DATABASE = 'genai_test'
#: 測試使用 Redis 的第 15 個資料庫，開始時清空
```

找到（2／2）：

```python
    async with db.session() as s:
        yield s
    await db.truncate_all()
```

改成：

```python
    async with db.session() as s:
        yield s
    await db.truncate_all()


@dataclass
class LiveApi:
    """在測試的 event loop 內以 uvicorn 執行的 api；worker 只在需要的測試中啟動。"""

    http: httpx.AsyncClient
    ws_url: str
    services: ApiServices
    composer_url: str

    @asynccontextmanager
    async def worker(self, speed: float = 0) -> AsyncIterator[None]:
        s = self.services
        composer = ComposerClient(self.composer_url)
        ports = sim_ports(composer, first_round_fail=True, force_all_fail=False)
        workers = build_workers(WorkerServices(s.db, s.redis, s.store, composer, ports, speed), s.queues)
        started = [asyncio.create_task(w.start()) for w in workers]
        try:
            yield
        finally:
            for w in workers:
                await w.stop()
            await asyncio.gather(*started, return_exceptions=True)
            await composer.aclose()


@pytest.fixture
async def api(db: Database, redis: Redis, composer_url: str, tmp_path: Path) -> AsyncIterator[LiveApi]:
    """data/ 與本機資料夾指向 tmp_path；品牌設定檔使用 repo 的 brands/。"""
    await redis.flushdb()
    queues = Queues(TEST_REDIS_URL)
    await queues.connect()
    composer = ComposerClient(composer_url)
    agent = SimAgent(composer, first_round_fail=True, force_all_fail=False)
    test_settings = Settings(data_dir=tmp_path / 'data', local_photos_dir=tmp_path / 'local')
    services = ApiServices(test_settings, db, redis, EventStore(db, redis), queues, composer, agent)
    await services.sync_brands()
    server = uvicorn.Server(uvicorn.Config(create_app(services), host='127.0.0.1', port=0, log_level='warning'))
    serving = asyncio.create_task(server.serve())
    while not server.started:
        if serving.done():
            serving.result()
            raise RuntimeError('uvicorn 沒有啟動')
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}', timeout=30) as http:
            yield LiveApi(http, f'ws://127.0.0.1:{port}', services, composer_url)
    finally:
        server.should_exit = True
        await serving
        await queues.disconnect()
        await composer.aclose()
        await db.truncate_all()
```

- [ ] **Step 3: 修改 `backend/tests/test_worker.py`**（`ingest_channel` 改由 `app.queues` 提供）

找到：

```python
from app.db.session import Database
from app.events import EventStore
from app.pipeline.sim import sim_ports
from app.queues import Queues
from app.repo import catalog, jobs
from app.worker import RESTART_REASON, Services, build_workers, cutout, ingest, ingest_channel, recover
from tests.conftest import TEST_REDIS_URL
from tests.fixtures import BRANDS_DIR, load_fixture
```

改成：

```python
from app.db.session import Database
from app.events import EventStore
from app.pipeline.sim import sim_ports
from app.queues import Queues, ingest_channel
from app.repo import catalog, jobs
from app.worker import RESTART_REASON, Services, build_workers, cutout, ingest, recover
from tests.conftest import TEST_REDIS_URL
from tests.fixtures import BRANDS_DIR, load_fixture
```

- [ ] **Step 4: 建立 `backend/tests/test_api_catalog.py`**

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


async def test_cutout_runs_on_the_worker(api: LiveApi) -> None:
    product = (await api.http.post('/api/products', json=DRAFT)).json()
    async with api.worker():
        res = await api.http.post(f'/api/products/{product["id"]}/cutout')
    assert res.json()['cutout'] == {'model': 'BiRefNet-general', 'url': None}
    listed = (await api.http.get('/api/products', params={'brandId': 'selune'})).json()
    assert listed[-1]['cutout'] == {'model': 'BiRefNet-general', 'url': None}
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
```

- [ ] **Step 5: 建立 `backend/tests/test_api_jobs.py`**

```python
"""api：需求拆解、建立任務、WebSocket 串流與補送、取消、選定海報、歷史紀錄、成效儀表板。需要 composer。"""

import asyncio
import json
import re
from typing import Any

import pytest
from saq.job import Status
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosedError

from tests.conftest import LiveApi
from tests.fixtures import load_fixture


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
    assert (await api.http.get('/api/history', params={'brandId': 'misty-isle'})).json() == []
    favorite = await api.http.patch(f'/api/history/{entry["id"]}', json={'favorite': True})
    assert favorite.json() == {**entry, 'favorite': True}
    assert (await api.http.patch('/api/history/hist_nope', json={'favorite': True})).status_code == 404
    stats = (await api.http.get('/api/stats', params={'brandId': 'selune'})).json()
    assert (stats['jobs'], stats['passRate'], stats['recent'][0]['jobId']) == (1, 1, job_id)
    assert (await api.http.get('/api/stats', params={'brandId': 'misty-isle'})).json()['jobs'] == 0
```

- [ ] **Step 6: 執行測試確認失敗**

Run: `uv run pytest -q`
Expected: FAIL，`ImportError while loading conftest`：`ModuleNotFoundError: No module named 'app.api'`。

- [ ] **Step 7: 修改 `backend/app/settings.py`**

找到：

```python
    #: 使用者自己的商品照（唯讀）
    local_photos_dir: Path = REPO_ROOT / 'assets' / 'products'
    composer_url: str = 'http://127.0.0.1:3900'

    #: 模擬模式的播放速度（1 為 1× 時間軸，約 15 秒一個任務；0 為不等待）
    sim_speed: float = 1.0
```

改成：

```python
    #: 使用者自己的商品照（唯讀）
    local_photos_dir: Path = REPO_ROOT / 'assets' / 'products'
    composer_url: str = 'http://127.0.0.1:3900'
    #: 任務 id 使用的本地時間（與前端 mock 的 makeJobId 一樣顯示使用者所在地的日期時間）
    timezone: str = 'Asia/Taipei'

    #: 前端可選的模型（JobInput.llm、JobInput.vlm）；Plan 6 改為實際的 Gemini 模型
    llm_model: str = 'Gemini 3.7 Flash'
    vlm_model: str = 'Gemini 3.7 Vision'

    #: 模擬模式的播放速度（1 為 1× 時間軸，約 15 秒一個任務；0 為不等待）
    sim_speed: float = 1.0
```

- [ ] **Step 8: 修改 `backend/app/errors.py`**

找到：

```python
class Conflict(AppError):
    status = 409
    code = 'conflict'
```

改成：

```python
class Conflict(AppError):
    status = 409
    code = 'conflict'


class Unavailable(AppError):
    """依賴的服務（worker、composer）沒有回應或逾時。"""

    status = 503
    code = 'unavailable'
```

- [ ] **Step 9: 修改 `backend/app/queues.py`**

找到（1／2）：

```python
TASKS = 'tasks'
#: tasks 佇列裡單一工作最長的執行時間（秒）
TASK_TIMEOUT = 600


@dataclass(frozen=True)
```

改成：

```python
TASKS = 'tasks'
#: tasks 佇列裡單一工作最長的執行時間（秒）
TASK_TIMEOUT = 600


def ingest_channel(task_id: str) -> str:
    """品牌文件上傳的進度：worker 發布到這個 Redis 頻道，api 以 NDJSON 串流轉給前端。"""
    return f'ingest:{task_id}'


@dataclass(frozen=True)
```

找到（2／2）：

```python
        """生圖可能花上數十分鐘，不設逾時（流程內各步驟有自己的逾時）。"""
        await self.jobs.enqueue('run_job', key=job_id, timeout=0, job_id=job_id)

    async def enqueue_task(self, name: str, **kwargs: Any) -> None:
        await self.tasks.enqueue(name, timeout=TASK_TIMEOUT, **kwargs)

    async def run_task(self, name: str, wait: float, **kwargs: Any) -> TaskResult:
        """放入 tasks 佇列並最多等 wait 秒；沒等到時工作仍在背景繼續。失敗時丟出 RuntimeError。"""
        job = await self.tasks.enqueue(name, timeout=TASK_TIMEOUT, **kwargs)
        assert job is not None
        await job.refresh(until_complete=wait)
        if job.status == Status.COMPLETE:
            return TaskResult(True, job.result)
        if job.status in (Status.FAILED, Status.ABORTED):
            raise RuntimeError(f'背景工作 {name} 失敗：{job.error}')
        return TaskResult(False, None)
```

改成：

```python
        """生圖可能花上數十分鐘，不設逾時（流程內各步驟有自己的逾時）。"""
        await self.jobs.enqueue('run_job', key=job_id, timeout=0, job_id=job_id)

    async def enqueue_task(self, function: str, /, **kwargs: Any) -> None:
        await self.tasks.enqueue(function, timeout=TASK_TIMEOUT, **kwargs)

    async def run_task(self, function: str, /, wait: float, **kwargs: Any) -> TaskResult:
        """放入 tasks 佇列並最多等 wait 秒；沒等到時工作仍在背景繼續。失敗時丟出 RuntimeError。"""
        job = await self.tasks.enqueue(function, timeout=TASK_TIMEOUT, **kwargs)
        assert job is not None
        await job.refresh(until_complete=wait)
        if job.status == Status.COMPLETE:
            return TaskResult(True, job.result)
        if job.status in (Status.FAILED, Status.ABORTED):
            raise RuntimeError(f'背景工作 {function} 失敗：{job.error}')
        return TaskResult(False, None)
```

- [ ] **Step 10: 修改 `backend/app/worker.py`**

找到：

```python
from app.pipeline.ports import Ports
from app.pipeline.runner import failure_reason, run_job
from app.pipeline.sim import sim_ports
from app.queues import Queues
from app.repo import catalog, history
from app.settings import settings

RESTART_REASON = 'worker 重新啟動，任務中斷'


def ingest_channel(task_id: str) -> str:
    return f'ingest:{task_id}'


@dataclass
```

改成：

```python
from app.pipeline.ports import Ports
from app.pipeline.runner import failure_reason, run_job
from app.pipeline.sim import sim_ports
from app.queues import Queues, ingest_channel
from app.repo import catalog, history
from app.settings import settings

RESTART_REASON = 'worker 重新啟動，任務中斷'


@dataclass
```

- [ ] **Step 11: 修改 `backend/app/events.py`**

找到（1／2）：

```python
"""

import json
from collections.abc import AsyncIterator
from typing import Any

from redis.asyncio import Redis
```

改成：

```python
"""

import json
from collections.abc import AsyncGenerator
from typing import Any

from redis.asyncio import Redis
```

找到（2／2）：

```python
                query = query.where(JobEventRow.seq < before)
            return [_message(r) for r in await s.scalars(query.order_by(JobEventRow.seq))]

    async def stream(self, job_id: str, after: int = 0) -> AsyncIterator[dict[str, Any]]:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(channel(job_id))
        try:
```

改成：

```python
                query = query.where(JobEventRow.seq < before)
            return [_message(r) for r in await s.scalars(query.order_by(JobEventRow.seq))]

    async def stream(self, job_id: str, after: int = 0) -> AsyncGenerator[dict[str, Any]]:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(channel(job_id))
        try:
```

- [ ] **Step 12: 修改 `backend/app/repo/jobs.py`**

找到（1／4）：

```python

import secrets
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
```

改成：

```python

import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
```

找到（2／4）：

```python

#: 任務列表最多列出的筆數（新到舊）
LIST_LIMIT = 100


def make_job_id(local_now: datetime, suffix: int | None = None) -> str:
```

改成：

```python

#: 任務列表最多列出的筆數（新到舊）
LIST_LIMIT = 100
#: 成效儀表板最多統計的任務數（新到舊）
STATS_LIMIT = 200


def make_job_id(local_now: datetime, suffix: int | None = None) -> str:
```

找到（3／4）：

```python
    )


async def create_job(session: AsyncSession, job_id: str, job_input: JobInput, now: datetime) -> None:
    session.add(
        JobRow(id=job_id, brand_id=job_input.brand_id, input=job_input.to_json(), created_at=now, stage='queued')
```

改成：

```python
    )


def _message(row: JobEventRow) -> dict[str, Any]:
    return {**row.payload, 'seq': row.seq, 'ts': iso(row.ts)}


async def create_job(session: AsyncSession, job_id: str, job_input: JobInput, now: datetime) -> None:
    session.add(
        JobRow(id=job_id, brand_id=job_input.brand_id, input=job_input.to_json(), created_at=now, stage='queued')
```

找到（4／4）：

```python
    if row is None:
        return None
    events = await session.scalars(select(JobEventRow).where(JobEventRow.job_id == job_id).order_by(JobEventRow.seq))
    return JobSnapshot(summary=_summary(row), events=[{**e.payload, 'seq': e.seq, 'ts': iso(e.ts)} for e in events])


async def request_cancel(session: AsyncSession, job_id: str) -> bool:
```

改成：

```python
    if row is None:
        return None
    events = await session.scalars(select(JobEventRow).where(JobEventRow.job_id == job_id).order_by(JobEventRow.seq))
    return JobSnapshot(summary=_summary(row), events=[_message(e) for e in events])


async def get_summary(session: AsyncSession, job_id: str) -> JobSummary | None:
    row = await session.get(JobRow, job_id)
    return _summary(row) if row is not None else None


async def finished_snapshots(session: AsyncSession, brand_id: str | None = None) -> list[JobSnapshot]:
    """已完成或需人工審核的任務與全部事件（成效儀表板使用；取消與失敗的任務不列入統計）。"""
    query = select(JobRow).where(JobRow.stage.in_(('done', 'needs_review')))
    if brand_id is not None:
        query = query.where(JobRow.brand_id == brand_id)
    rows = (await session.scalars(query.order_by(JobRow.created_at.desc(), JobRow.id.desc()).limit(STATS_LIMIT))).all()
    events: dict[str, list[dict[str, Any]]] = {r.id: [] for r in rows}
    if events:
        of_jobs = select(JobEventRow).where(JobEventRow.job_id.in_(list(events)))
        stored = await session.scalars(of_jobs.order_by(JobEventRow.job_id, JobEventRow.seq))
        for e in stored:
            events[e.job_id].append(_message(e))
    return [JobSnapshot(summary=_summary(r), events=events[r.id]) for r in rows]


async def request_cancel(session: AsyncSession, job_id: str) -> bool:
```

- [ ] **Step 13: 建立 `backend/app/api/__init__.py`**（空檔）

```python

```

- [ ] **Step 14: 建立 `backend/app/api/services.py`**

```python
"""api 使用的服務：資料庫、Redis、事件、佇列、composer 與 Agent（拆解需求）。

api 不載入任何模型；生圖、文件上傳、去背與回寫都放進佇列交給 worker。
"""

from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from starlette.requests import HTTPConnection

from app.adapters.composer import ComposerClient
from app.brands import BrandLoadError, load_brands
from app.core.clock import utc_now
from app.db.session import Database
from app.events import EventStore
from app.pipeline.ports import Agent
from app.pipeline.sim import SimAgent
from app.queues import Queues
from app.repo import catalog
from app.settings import Settings


@dataclass
class ApiServices:
    settings: Settings
    db: Database
    redis: Redis
    store: EventStore
    queues: Queues
    composer: ComposerClient
    agent: Agent
    #: 格式錯誤而略過的品牌設定檔（系統狀態顯示原因）
    brand_errors: list[BrandLoadError] = field(default_factory=list)

    async def sync_brands(self) -> None:
        """品牌設定檔 → 資料庫（api 啟動時執行）。"""
        loaded, self.brand_errors = load_brands(self.settings.brands_dir)
        async with self.db.session() as s:
            await catalog.sync_brands(s, loaded, utc_now())


async def start_services(settings: Settings) -> ApiServices:
    """連線、執行 migration、匯入品牌設定檔。worker 等 api 健康後才啟動，所以 migration 只在這裡跑。"""
    db = Database(settings.database_url)
    await db.migrate()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    queues = Queues(settings.redis_url)
    await queues.connect()
    composer = ComposerClient(settings.composer_url)
    agent = SimAgent(
        composer, first_round_fail=settings.sim_first_round_fail, force_all_fail=settings.sim_force_all_fail
    )
    services = ApiServices(settings, db, redis, EventStore(db, redis), queues, composer, agent)
    await services.sync_brands()
    return services


async def stop_services(services: ApiServices) -> None:
    await services.queues.disconnect()
    await services.composer.aclose()
    await services.redis.aclose()
    await services.db.dispose()


def get_services(connection: HTTPConnection) -> ApiServices:
    services: ApiServices = connection.app.state.services
    return services


#: 路由函式的參數型別：services: Services
Services = Annotated[ApiServices, Depends(get_services)]
```

- [ ] **Step 15: 建立 `backend/app/api/catalog.py`**

```python
"""可用選項、系統狀態、品牌（含文件上傳）、通路模板、商品與商品照、本機資料夾。"""

import asyncio
import json
import re
import secrets
from collections.abc import AsyncIterator, Awaitable
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from app.api.services import ApiServices, Services
from app.contract import (
    ApiOptions,
    Brand,
    BrandDocument,
    ChannelTemplate,
    ComponentStatus,
    FilePhoto,
    LocalPhoto,
    Model,
    Price,
    Product,
    ProductDraft,
    SystemStatus,
)
from app.core.clock import utc_now
from app.errors import Invalid, NotFound, Unavailable
from app.pipeline.runner import failure_reason
from app.queues import ingest_channel
from app.repo import catalog
from app.settings import Settings
from app.templates import CHANNEL_TEMPLATES

router = APIRouter(tags=['品牌與商品'])

#: 外部服務目前都是模擬版（Plan 5–7 逐一換成真實版）
SIMULATED = [
    ComponentStatus(id='rag', label='向量庫（Chroma＋BGE）', status='sim', detail='模擬檢索：固定的召回與 Rerank 順序'),
    ComponentStatus(id='gemini', label='Gemini（LLM／VLM）', status='sim', detail='模擬 Agent 與 VLM 審查'),
    ComponentStatus(id='comfyui', label='ComfyUI', status='sim', detail='模擬生圖：程序化背景'),
]
#: 系統狀態每一項最多等待的秒數
STATUS_TIMEOUT = 3
#: 文件上傳最多等待的秒數（超過時回報錯誤，worker 仍會繼續處理）
INGEST_TIMEOUT = 120
#: 去背最多等待的秒數
CUTOUT_WAIT = 30
#: 上傳的商品照：MIME → 副檔名（與本機資料夾支援的格式相同）
UPLOAD_TYPES = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
LOCAL_TYPES = frozenset({'.png', '.jpg', '.jpeg', '.webp'})


def api_options(settings: Settings) -> ApiOptions:
    return ApiOptions(llm=[settings.llm_model], vlm=[settings.vlm_model], engines=['comfyui'])


@router.get('/api/health')
async def health() -> dict[str, str]:
    """容器的健康檢查：api 啟動完成（migration 與品牌匯入都已執行）。"""
    return {'status': 'ok'}


@router.get('/api/options')
async def get_options(services: Services) -> ApiOptions:
    return api_options(services.settings)


async def _probe(id_: str, label: str, check: Awaitable[str]) -> ComponentStatus:
    try:
        detail = await asyncio.wait_for(check, STATUS_TIMEOUT)
    except TimeoutError:
        return ComponentStatus(id=id_, label=label, status='error', detail=f'{STATUS_TIMEOUT} 秒內沒有回應')
    except Exception as error:  # noqa: BLE001 - 任何錯誤都顯示在系統狀態
        return ComponentStatus(id=id_, label=label, status='error', detail=failure_reason(error))
    return ComponentStatus(id=id_, label=label, status='ok', detail=detail)


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


async def _composer(services: ApiServices) -> str:
    if not await services.composer.health():
        raise Unavailable(f'連不上 composer（{services.composer.base_url}）')
    return services.composer.base_url


async def _brands(services: ApiServices) -> str:
    async with services.db.session() as s:
        count = len(await catalog.list_brands(s))
    if services.brand_errors:
        skipped = '；'.join(f'{e.file}：{e.message}' for e in services.brand_errors)
        raise Invalid(f'已載入 {count} 個品牌；略過 {skipped}')
    return f'已載入 {count} 個品牌'


@router.get('/api/status')
async def get_status(services: Services) -> SystemStatus:
    probed = await asyncio.gather(
        _probe('db', 'PostgreSQL', _db(services)),
        _probe('redis', 'Redis（佇列與事件推送）', _redis(services)),
        _probe('worker', 'worker（SAQ）', _workers(services)),
        _probe('composer', 'composer（排版與模擬邏輯）', _composer(services)),
        _probe('brands', '品牌設定檔', _brands(services)),
    )
    return SystemStatus(components=[*probed, *SIMULATED])


@router.get('/api/brands')
async def list_brands(services: Services) -> list[Brand]:
    async with services.db.session() as s:
        return await catalog.list_brands(s)


async def _ingest_lines(services: ApiServices, task_id: str, brand_id: str, doc: BrandDocument) -> AsyncIterator[str]:
    """先訂閱再放入佇列，才不會漏掉 worker 發布的訊息；收到 ingest.stored 或錯誤時結束。"""
    pubsub = services.redis.pubsub()
    await pubsub.subscribe(ingest_channel(task_id))
    try:
        await services.queues.enqueue_task('ingest', task_id=task_id, brand_id=brand_id, name=doc.name, text=doc.text)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + INGEST_TIMEOUT
        while loop.time() < deadline:
            raw = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if raw is None:
                continue
            yield raw['data'] + '\n'
            message = json.loads(raw['data'])
            if 'error' in message or message['type'] == 'ingest.stored':
                return
        timeout = {'code': 'unavailable', 'message': '文件處理逾時：請確認 worker 正在執行'}
        yield json.dumps({'error': timeout}, ensure_ascii=False) + '\n'
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()  # type: ignore[no-untyped-call]


@router.post(
    '/api/brands/{brand_id}/documents',
    response_class=StreamingResponse,
    responses={200: {'content': {'application/x-ndjson': {}}, 'description': '每行一則 IngestEvent，或 { error }'}},
)
async def ingest_document(brand_id: str, doc: BrandDocument, services: Services) -> StreamingResponse:
    """上傳品牌文件：切塊 → 向量化 → 寫入知識庫，進度以 NDJSON 串流回報。"""
    async with services.db.session() as s:
        if await catalog.get_brand(s, brand_id) is None:
            raise NotFound(f'找不到品牌：{brand_id}')
    lines = _ingest_lines(services, secrets.token_hex(8), brand_id, doc)
    return StreamingResponse(lines, media_type='application/x-ndjson')


@router.get('/api/templates')
async def list_templates() -> list[ChannelTemplate]:
    return CHANNEL_TEMPLATES


@router.get('/api/products')
async def list_products(services: Services, brand_id: Annotated[str, Query(alias='brandId')]) -> list[Product]:
    async with services.db.session() as s:
        return await catalog.list_products(s, brand_id)


async def _save(services: ApiServices, draft: ProductDraft) -> Product:
    async with services.db.session() as s:
        if await catalog.get_brand(s, draft.brand_id) is None:
            raise Invalid(f'找不到品牌：{draft.brand_id}')
        return await catalog.save_product(s, draft, utc_now())


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
    async with services.db.session() as s:
        if not await catalog.delete_product(s, product_id):
            raise NotFound(f'找不到商品：{product_id}')


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
```

- [ ] **Step 16: 建立 `backend/app/api/jobs.py`**

WebSocket 同時等待兩件事，先發生的一方結束連線：
- 事件串流結束：以 1000 關閉。
- 前端斷線：取消串流，Redis 訂閱由 `aclosing` 關閉。

```python
"""需求拆解、任務（建立、列表、取消、WebSocket 事件串流）、選定海報、歷史紀錄與成效儀表板。"""

import asyncio
import json
import secrets
from contextlib import aclosing
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, WebSocket
from pydantic import Field
from sqlalchemy.exc import IntegrityError

from app.api.catalog import api_options
from app.api.services import ApiServices, Services
from app.contract import (
    Copy,
    DashboardStats,
    HistoryEntry,
    JobAcceptedEvent,
    JobInput,
    JobSnapshot,
    JobStatusEvent,
    JobSummary,
    Model,
    ParsedBrief,
)
from app.core.clock import iso, utc_now
from app.errors import Invalid, NotFound
from app.repo import catalog, history, jobs
from app.stats import dashboard_stats

router = APIRouter(tags=['任務'])

#: 回寫歷史案例最多等待的秒數（逾時時 writtenToRag 為 false，worker 仍會完成）
WRITE_BACK_WAIT = 10
#: WebSocket 關閉代碼：任務不存在（前端不再重新連線）
WS_NOT_FOUND = 4404


class BriefRequest(Model):
    brand_id: str
    text: str
    product_id: str | None


class JobCreated(Model):
    job_id: str


class SelectRequest(Model):
    render_id: str
    copy_: Copy = Field(alias='copy')


class FavoriteRequest(Model):
    favorite: bool


@router.post('/api/briefs/parse')
async def parse_brief(body: BriefRequest, services: Services) -> ParsedBrief:
    async with services.db.session() as s:
        brand = await catalog.get_brand(s, body.brand_id)
        product = await catalog.get_product(s, body.product_id) if body.product_id else None
    if brand is None:
        raise Invalid(f'找不到品牌：{body.brand_id}')
    if body.product_id and product is None:
        raise Invalid(f'找不到商品：{body.product_id}')
    return await services.agent.parse_brief(brand, body.text, product)


async def _validate(services: ApiServices, job_input: JobInput) -> None:
    """與 mock 的 createJob 相同的檢查，再加上模型與引擎必須是目前可用的選項。"""
    async with services.db.session() as s:
        brand = await catalog.get_brand(s, job_input.brand_id)
        product = await catalog.get_product(s, job_input.product_id)
    if brand is None:
        raise Invalid(f'找不到品牌：{job_input.brand_id}')
    if product is None:
        raise Invalid(f'找不到商品：{job_input.product_id}')
    if not job_input.template_ids:
        raise Invalid('至少要選一個通路模板')
    if len(set(job_input.template_ids)) != len(job_input.template_ids):
        raise Invalid('通路模板不可重複')
    if not 1 <= job_input.variants_per_template <= 8:
        raise Invalid('每個模板的候選張數需為 1–8')
    if job_input.max_retries < 0:
        raise Invalid('最大重試次數需為 0 以上的整數')
    if product.brand_id != brand.id:
        raise Invalid('商品不屬於所選品牌')
    options = api_options(services.settings)
    if job_input.llm not in options.llm:
        raise Invalid(f'目前不支援這個 LLM：{job_input.llm}')
    if job_input.vlm not in options.vlm:
        raise Invalid(f'目前不支援這個 VLM：{job_input.vlm}')
    if job_input.engine not in options.engines:
        raise Invalid(f'目前不支援這個生圖引擎：{job_input.engine}')


@router.post('/api/jobs', status_code=201)
async def create_job(job_input: JobInput, services: Services) -> JobCreated:
    """寫入任務、送出 job.accepted 與 job.status queued，放進 jobs 佇列。"""
    await _validate(services, job_input)
    now = utc_now()
    local = now.astimezone(ZoneInfo(services.settings.timezone))
    for attempt in range(5):
        job_id = jobs.make_job_id(local)
        try:
            async with services.db.session() as s:
                await jobs.create_job(s, job_id, job_input, now)
            break
        except IntegrityError:
            # 同一分鐘內 4 位亂數重複：換一個
            if attempt == 4:
                raise
    await services.store.append(job_id, JobAcceptedEvent(type='job.accepted', job_id=job_id))
    await services.store.append(job_id, JobStatusEvent(type='job.status', stage='queued', round=0))
    await services.queues.enqueue_job(job_id)
    return JobCreated(job_id=job_id)


@router.get('/api/jobs')
async def list_jobs(services: Services) -> list[JobSummary]:
    async with services.db.session() as s:
        return await jobs.list_jobs(s)


@router.get('/api/jobs/{job_id}')
async def get_job(job_id: str, services: Services) -> JobSnapshot:
    async with services.db.session() as s:
        snap = await jobs.get_job(s, job_id)
    if snap is None:
        raise NotFound(f'找不到任務：{job_id}')
    return snap


@router.post('/api/jobs/{job_id}/cancel', status_code=204)
async def cancel_job(job_id: str, services: Services) -> None:
    """排隊中：直接取消。執行中：設定取消旗標，worker 在步驟之間停止。已結束：不做任何事。"""
    cancelled = JobStatusEvent(type='job.status', stage='cancelled', round=0)
    if await services.store.append(job_id, cancelled, expect_stage='queued') is None:
        async with services.db.session() as s:
            await jobs.request_cancel(s, job_id)


@router.websocket('/ws/jobs/{job_id}')
async def stream_job(websocket: WebSocket, job_id: str, services: Services, after: int = 0) -> None:
    """先補送 seq 大於 after 的事件，再轉送即時事件；任務結束且事件送完後由伺服器關閉連線。"""
    await websocket.accept()
    async with services.db.session() as s:
        if await jobs.get_summary(s, job_id) is None:
            await websocket.close(code=WS_NOT_FOUND, reason='job not found')
            return

    async def forward() -> None:
        async with aclosing(services.store.stream(job_id, after)) as messages:
            async for message in messages:
                await websocket.send_text(json.dumps(message, ensure_ascii=False))

    async def until_disconnect() -> None:
        # 前端不送訊息；收到 disconnect 代表連線已經關閉
        while (await websocket.receive())['type'] != 'websocket.disconnect':
            pass

    sender = asyncio.create_task(forward())
    watcher = asyncio.create_task(until_disconnect())
    done, pending = await asyncio.wait({sender, watcher}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    if sender in done:
        error = sender.exception()
        await websocket.close(code=1011 if error else 1000)
        if error:
            raise error


@router.post('/api/jobs/{job_id}/select', status_code=201)
async def select_render(job_id: str, body: SelectRequest, services: Services) -> HistoryEntry:
    """選定候選圖：寫入歷史紀錄，再由 worker 回寫成歷史案例（writtenToRag）。"""
    async with services.db.session() as s:
        summary = await jobs.get_summary(s, job_id)
        if summary is None:
            raise NotFound(f'找不到任務：{job_id}')
        render = await jobs.get_render(s, job_id, body.render_id)
        if render is None:
            raise NotFound(f'找不到候選圖：{body.render_id}')
        entry = HistoryEntry(
            id=f'hist_{secrets.token_hex(6)}',
            job_id=job_id,
            brand_id=summary.input.brand_id,
            product_id=summary.input.product_id,
            input=summary.input,
            template_id=render.template_id,
            render=render,
            copy_=body.copy_,
            selected_at=iso(utc_now()),
            favorite=False,
            written_to_rag=False,
        )
        await history.add_history(s, entry)
    done = await services.queues.run_task('write_back', wait=WRITE_BACK_WAIT, history_id=entry.id)
    if done.completed and done.result:
        entry = entry.model_copy(update={'written_to_rag': True})
    return entry


@router.get('/api/history')
async def list_history(
    services: Services, brand_id: Annotated[str | None, Query(alias='brandId')] = None
) -> list[HistoryEntry]:
    async with services.db.session() as s:
        return await history.list_history(s, brand_id)


@router.patch('/api/history/{history_id}')
async def set_favorite(history_id: str, body: FavoriteRequest, services: Services) -> HistoryEntry:
    async with services.db.session() as s:
        entry = await history.set_favorite(s, history_id, body.favorite)
    if entry is None:
        raise NotFound(f'找不到歷史紀錄：{history_id}')
    return entry


@router.get('/api/stats')
async def get_stats(
    services: Services, brand_id: Annotated[str | None, Query(alias='brandId')] = None
) -> DashboardStats:
    async with services.db.session() as s:
        return dashboard_stats(await jobs.finished_snapshots(s, brand_id))
```

- [ ] **Step 17: 建立 `backend/app/api/files.py`**

```python
"""/files/...（唯讀）：

- /files/uploads/…、之後的去背圖與生成圖 → data/
- /files/local/{檔名} → 本機資料夾 assets/products/
- /files/brands/… → 品牌設定檔資料夾（Logo 等圖檔）
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.api.services import Services
from app.errors import NotFound
from app.settings import Settings

router = APIRouter(tags=['檔案'])

#: 只提供圖片；MIME 固定，不依賴作業系統的對照表
FILE_TYPES = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
    '.svg': 'image/svg+xml',
}


def resolve_file(settings: Settings, path: str) -> Path | None:
    """網址路徑 → 檔案。不允許超出各自的資料夾（.. 與絕對路徑都會被擋下）。"""
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


@router.get('/files/{path:path}')
async def read_file(path: str, services: Services) -> FileResponse:
    target = resolve_file(services.settings, path)
    if target is None:
        raise NotFound(f'找不到檔案：{path}')
    return FileResponse(
        target, media_type=FILE_TYPES[target.suffix.lower()], headers={'X-Content-Type-Options': 'nosniff'}
    )
```

- [ ] **Step 18: 建立 `backend/app/api/main.py`**

```python
"""FastAPI 入口：uv run uvicorn app.api.main:app --port 8000

錯誤一律回傳 { error: { code, message } }（message 為繁體中文）。OpenAPI 文件在 /docs。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.adapters.composer import ComposerError
from app.api import catalog, files, jobs
from app.api.services import ApiServices, start_services, stop_services
from app.errors import AppError
from app.pipeline.runner import failure_reason
from app.settings import settings

HTTP_CODES = {404: 'not_found', 405: 'method_not_allowed'}


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({'error': {'code': code, 'message': message}}, status_code=status)


def _describe(error: Any) -> str:
    """Pydantic 的錯誤 → 「body.templateIds.0：Input should be ...」"""
    location = '.'.join(str(part) for part in error['loc'])
    return f'{location}：{error["msg"]}'


def create_app(services: ApiServices | None = None) -> FastAPI:
    """測試傳入已建立的 services；省略時依設定在啟動時建立、結束時關閉。"""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if services is not None:
            app.state.services = services
            yield
            return
        started = await start_services(settings)
        app.state.services = started
        try:
            yield
        finally:
            await stop_services(started)

    app = FastAPI(title='虛實整合 GenAI Agent API', version='0.4.0', lifespan=lifespan)
    app.include_router(catalog.router)
    app.include_router(jobs.router)
    app.include_router(files.router)

    @app.exception_handler(AppError)
    async def app_error(request: Request, error: AppError) -> JSONResponse:
        return error_response(error.status, error.code, error.message)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        errors = error.errors()
        return error_response(400, 'invalid', '請求格式錯誤' + (f'：{_describe(errors[0])}' if errors else ''))

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        message = '找不到這個網址' if error.status_code == 404 else str(error.detail)
        return error_response(error.status_code, HTTP_CODES.get(error.status_code, 'http_error'), message)

    @app.exception_handler(ComposerError)
    async def composer_error(request: Request, error: ComposerError) -> JSONResponse:
        return error_response(503, 'unavailable', str(error))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception) -> JSONResponse:
        return error_response(500, 'internal', failure_reason(error))

    return app


app = create_app()
```

- [ ] **Step 19: 執行測試確認通過**

Run: `uv run pytest -q`
Expected: PASS，62 passed（`test_api_catalog.py` 9 個、`test_api_jobs.py` 7 個）。

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: 沒有錯誤。

- [ ] **Step 20: 手動確認**

各開一個終端機：
- `web/`：`npm run composer`
- `backend/`：`uv run uvicorn app.api.main:app --port 8000`
- `backend/`：`uv run python -m app.worker`

然後確認：
- `curl http://127.0.0.1:8000/api/status`：db、redis、worker、composer、brands 為 `ok`，rag、gemini、comfyui 為 `sim`。
- http://127.0.0.1:8000/docs 列出全部端點。

確認後停止這三個服務。

- [ ] **Step 21: Commit**

```bash
git add \
  backend/app/api/__init__.py \
  backend/app/api/catalog.py \
  backend/app/api/files.py \
  backend/app/api/jobs.py \
  backend/app/api/main.py \
  backend/app/api/services.py \
  backend/app/errors.py \
  backend/app/events.py \
  backend/app/queues.py \
  backend/app/repo/jobs.py \
  backend/app/settings.py \
  backend/app/worker.py \
  backend/pyproject.toml \
  backend/tests/conftest.py \
  backend/tests/test_api_catalog.py \
  backend/tests/test_api_jobs.py \
  backend/tests/test_worker.py \
  backend/uv.lock
git commit -m "feat: serve the REST API, job WebSocket stream and files with FastAPI" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: 前端 live 模式：`HttpApiClient`、重新連線與重新整理後接續


**Files:**
- Create: `web/src/lib/api/http/connection.ts`、`web/src/lib/api/http/job-socket.ts`、`web/src/lib/api/http/client.ts`
- Modify: `web/src/lib/api/index.ts`、`web/src/lib/store/studio.ts`、`web/src/app/studio/page.tsx`、`web/src/components/product/upload-zone.tsx`、`web/next.config.ts`
- Test: `web/src/lib/api/http/client.test.ts`、`web/src/lib/api/http/job-socket.test.ts`、`web/src/lib/store/studio.test.ts`

**Interfaces:**
- Consumes：Task 12 的 API；`ApiClient` 介面
- Produces：
  - `HttpApiClient({ baseUrl?, fetch?, WebSocket? })`：
    - `ApiClient` 的每個方法對應 Task 12 的端點；`demo` 為 `null`。
    - 非 2xx 時丟出 `ApiError(code, message, status)`，message 是後端的繁體中文訊息。
    - 連不上後端時丟出 `ApiError('network', …)`。
  - `subscribe`（`openJobSocket`）：
    - WebSocket 正常關閉（1000）或收到結束的 `job.status` 後不再連線。
    - 4404 以 `onError(找不到任務)` 回報，只報一次。
    - 其他中斷以最後收到的 `seq` 重新連線：等待 1 秒起每次加倍，最長 10 秒；依 `seq` 略過重複。
  - `ingestBrandDocument`：逐行讀取 NDJSON（一個 chunk 可能只有半行），回傳 `ingest.chunked` 的切塊。
  - `connection`（`ConnectionTracker`）：
    - 狀態來自最近一次請求或 WebSocket。
    - 有人訂閱（右上角的連線狀態）時才確認 `/api/health`；中斷時定期重試，直到恢復。
  - `getApiClient()`：`NEXT_PUBLIC_API_MODE=live` 時使用 `HttpApiClient`（同源網址）
  - `useStudioStore.restore(brandId)`：
    - 新任務頁面第一次進入時呼叫。
    - 這個分頁剛才有這個品牌的任務（sessionStorage）時，接續顯示：重播事件並繼續接收。
    - 任務已不存在時忘掉它。
  - `next dev` 的 rewrites 加上 `/ws`（Next 的開發伺服器會轉送 WebSocket 升級請求）

- [ ] **Step 1: 建立 `web/src/lib/api/http/job-socket.test.ts`**（先寫失敗測試）

以假的 WebSocket 扮演伺服器（`open`、`send`、`drop`），fake timers 控制重新連線的等待時間。

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobMessage } from '@/types/contract';
import { HttpApiClient } from './client';

/** 測試用 WebSocket：由測試扮演伺服器（open、send、drop） */
class FakeSocket {
  static all: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    FakeSocket.all.push(this);
  }

  close() {
    this.closed = true;
  }

  open() {
    this.onopen?.();
  }

  send(message: Partial<JobMessage> & { seq: number }) {
    this.onmessage?.({ data: JSON.stringify({ type: 'log', source: 'api', level: 'info', message: '', ts: '', ...message }) });
  }

  drop(code: number) {
    this.onclose?.({ code });
  }
}

const sockets = () => FakeSocket.all;
const last = () => FakeSocket.all.at(-1)!;
const done = (seq: number) => ({ type: 'job.status' as const, stage: 'done' as const, round: 1, seq });

function client() {
  return new HttpApiClient({
    baseUrl: 'http://api.test',
    fetch: vi.fn(async () => Response.json({ status: 'ok' })),
    WebSocket: FakeSocket as unknown as typeof WebSocket,
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeSocket.all = [];
});
afterEach(() => vi.useRealTimers());

describe('HttpApiClient.subscribe', () => {
  it('replays and streams events, then stops when the server closes after the final event', async () => {
    const api = client();
    const seqs: number[] = [];
    api.subscribe('job_1', (m) => seqs.push(m.seq));
    expect(last().url).toBe('ws://api.test/ws/jobs/job_1?after=0');
    last().open();
    expect(api.connection.get().status).toBe('connected');
    last().send({ seq: 1 });
    last().send({ seq: 2 });
    last().send(done(3));
    last().drop(1000);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(seqs).toEqual([1, 2, 3]);
    expect(sockets()).toHaveLength(1);
  });

  it('reconnects after the last seq with a growing delay and skips repeated events', async () => {
    const api = client();
    const seqs: number[] = [];
    api.subscribe('job_1', (m) => seqs.push(m.seq));
    last().open();
    last().send({ seq: 1 });
    last().send({ seq: 2 });
    last().drop(1006);
    expect(api.connection.get()).toMatchObject({ status: 'disconnected', error: '任務事件的連線中斷，1 秒後重新連線' });
    await vi.advanceTimersByTimeAsync(999);
    expect(sockets()).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(last().url).toBe('ws://api.test/ws/jobs/job_1?after=2');
    // 還沒連上就又斷了：等待時間加倍
    last().drop(1006);
    await vi.advanceTimersByTimeAsync(1_999);
    expect(sockets()).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(sockets()).toHaveLength(3);
    last().open();
    last().send({ seq: 2 });
    last().send({ seq: 3 });
    expect(seqs).toEqual([1, 2, 3]);
    expect(api.connection.get().status).toBe('connected');
  });

  it('reports an unknown job once and does not reconnect', async () => {
    const onError = vi.fn();
    client().subscribe('job_nope', () => {}, onError);
    last().drop(4404);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0].message).toBe('找不到任務：job_nope');
    expect(sockets()).toHaveLength(1);
  });

  it('stops delivering events and cancels a pending reconnect once unsubscribed', async () => {
    const api = client();
    const seqs: number[] = [];
    const stop = api.subscribe('job_1', (m) => seqs.push(m.seq));
    last().open();
    last().send({ seq: 1 });
    last().drop(1006);
    stop();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(sockets()).toHaveLength(1);

    const stopAgain = api.subscribe('job_2', (m) => seqs.push(m.seq));
    last().open();
    stopAgain();
    expect(last().closed).toBe(true);
    last().send({ seq: 1 });
    expect(seqs).toEqual([1]);
  });

  it('keeps streaming when a subscriber throws', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const seqs: number[] = [];
    client().subscribe('job_1', (m) => {
      seqs.push(m.seq);
      if (m.seq === 1) throw new Error('boom');
    });
    last().open();
    last().send({ seq: 1 });
    last().send({ seq: 2 });
    expect(seqs).toEqual([1, 2]);
    expect(error).toHaveBeenCalledTimes(1);
    error.mockRestore();
  });
});
```

- [ ] **Step 2: 建立 `web/src/lib/api/http/client.test.ts`**

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { IngestEvent, Product } from '@/types/contract';
import type { ProductDraft } from '../client';
import { ApiError, HttpApiClient } from './client';

type Handler = (url: string, init: RequestInit) => Response | Promise<Response>;

function setup(handler: Handler) {
  const fetch = vi.fn(async (url: string | URL | Request, init: RequestInit = {}) => handler(String(url), init));
  const api = new HttpApiClient({ baseUrl: 'http://api.test', fetch: fetch as unknown as typeof globalThis.fetch });
  const call = (i: number) => {
    const [url, init = {}] = fetch.mock.calls[i];
    return { url: String(url), method: init.method, body: typeof init.body === 'string' ? JSON.parse(init.body) : init.body };
  };
  return { api, fetch, call };
}

const DRAFT: ProductDraft = {
  brandId: 'selune', name: '晚安面膜', features: [], price: { sale: 590, original: 790 },
  photo: { source: 'upload', url: '/files/uploads/x.png' }, cutout: null,
};
const PRODUCT: Product = { ...DRAFT, id: 'prod_1', createdAt: '2026-10-08T01:00:00.000Z' };

/** 把 NDJSON 切成任意大小的片段送出（片段可能只有半行） */
function ndjson(lines: object[], size = 7): Response {
  const text = lines.map((l) => JSON.stringify(l)).join('\n') + '\n';
  const bytes = new TextEncoder().encode(text);
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (let i = 0; i < bytes.length; i += size) controller.enqueue(bytes.slice(i, i + size));
      controller.close();
    },
  });
  return new Response(body, { headers: { 'content-type': 'application/x-ndjson' } });
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('HttpApiClient REST', () => {
  it('maps each method to its endpoint', async () => {
    const { api, call } = setup((url, init) => (init.method === 'DELETE' ? new Response(null, { status: 204 }) : Response.json(PRODUCT)));
    expect(await api.saveProduct(DRAFT)).toEqual(PRODUCT);
    await api.saveProduct({ ...DRAFT, id: 'prod_1' });
    await api.listProducts('selune');
    expect(await api.deleteProduct('prod_1')).toBeUndefined();
    await api.importLocalPhoto('精華液.png', 'selune');
    await api.listHistory();
    await api.getDashboardStats('misty-isle');
    await api.selectRender('job_1', 'r1', { headline: ['a', 'b'] } as never);
    expect([0, 1, 2, 3, 4, 5, 6, 7].map((i) => [call(i).method, call(i).url])).toEqual([
      ['POST', 'http://api.test/api/products'],
      ['PUT', 'http://api.test/api/products/prod_1'],
      ['GET', 'http://api.test/api/products?brandId=selune'],
      ['DELETE', 'http://api.test/api/products/prod_1'],
      ['POST', 'http://api.test/api/local-photos/%E7%B2%BE%E8%8F%AF%E6%B6%B2.png/import'],
      ['GET', 'http://api.test/api/history'],
      ['GET', 'http://api.test/api/stats?brandId=misty-isle'],
      ['POST', 'http://api.test/api/jobs/job_1/select'],
    ]);
    expect(call(0).body).toEqual(DRAFT);
    expect(call(4).body).toEqual({ brandId: 'selune' });
    expect(call(7).body).toEqual({ renderId: 'r1', copy: { headline: ['a', 'b'] } });
  });

  it('uploads product photos as multipart form data', async () => {
    const { api, call } = setup(() => Response.json({ source: 'upload', url: '/files/uploads/a.png' }, { status: 201 }));
    const photo = await api.uploadProductPhoto(new File([new Uint8Array([1, 2, 3])], 'serum.png', { type: 'image/png' }));
    expect(photo).toEqual({ source: 'upload', url: '/files/uploads/a.png' });
    const form = call(0).body as FormData;
    expect((form.get('file') as File).name).toBe('serum.png');
  });

  it('throws the server error message and tracks whether the backend is reachable', async () => {
    let reply: () => Response = () => Response.json({ error: { code: 'invalid', message: '至少要選一個通路模板' } }, { status: 400 });
    const { api } = setup(() => reply());
    const rejected = await api.createJob({} as never).catch((e: unknown) => e);
    expect(rejected).toBeInstanceOf(ApiError);
    expect(rejected).toMatchObject({ code: 'invalid', message: '至少要選一個通路模板', status: 400 });
    expect(api.connection.get().status).toBe('connected');

    reply = () => new Response('<html>Bad Gateway</html>', { status: 502 });
    await expect(api.listJobs()).rejects.toMatchObject({ code: 'http_error', message: '後端回應 HTTP 502' });
    expect(api.connection.get()).toMatchObject({ status: 'disconnected', error: '後端沒有回應（HTTP 502）' });

    reply = () => {
      throw new TypeError('fetch failed');
    };
    await expect(api.listJobs()).rejects.toMatchObject({ code: 'network', message: '無法連線到後端，請確認服務已啟動' });
    expect(api.connection.get()).toMatchObject({ status: 'disconnected', error: '無法連線到後端' });

    reply = () => Response.json([]);
    expect(await api.listJobs()).toEqual([]);
    expect(api.connection.get()).toMatchObject({ status: 'connected', error: null });
  });

  it('checks the backend while someone watches the connection, until it answers', async () => {
    let up = false;
    const { api, fetch } = setup(() => {
      if (!up) throw new TypeError('fetch failed');
      return Response.json({ status: 'ok' });
    });
    const states: string[] = [];
    api.connection.subscribe((s) => states.push(s.status));
    await vi.advanceTimersByTimeAsync(0);
    expect(states).toEqual(['disconnected']);
    await vi.advanceTimersByTimeAsync(1_000);
    up = true;
    await vi.advanceTimersByTimeAsync(2_000);
    expect(states).toEqual(['disconnected', 'connected']);
    const probes = fetch.mock.calls.length;
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetch.mock.calls.length).toBe(probes);
    expect(fetch.mock.calls.every(([url]) => String(url) === 'http://api.test/api/health')).toBe(true);
  });
});

describe('HttpApiClient.ingestBrandDocument', () => {
  const chunk = { id: 'selune#doc-1', source: 'a.md', section: '色彩', tag: 'color' as const, text: '主色' };
  const progress: IngestEvent[] = [
    { type: 'ingest.chunked', source: 'a.md', chunks: [chunk] },
    { type: 'ingest.embedded', chunkId: chunk.id, index: 0, total: 1, dims: 1024, preview: [0.1, -0.2] },
    { type: 'ingest.stored', collection: 'selune_ci', count: 1 },
  ];

  it('reports each NDJSON line and returns the new chunks', async () => {
    const { api, call } = setup(() => ndjson(progress));
    const seen: IngestEvent[] = [];
    expect(await api.ingestBrandDocument('selune', { name: 'a.md', text: '# 色彩\n主色' }, (e) => seen.push(e))).toEqual([chunk]);
    expect(seen).toEqual(progress);
    expect([call(0).method, call(0).url, call(0).body]).toEqual([
      'POST', 'http://api.test/api/brands/selune/documents', { name: 'a.md', text: '# 色彩\n主色' },
    ]);
  });

  it('throws the error line, or when the stream ends early', async () => {
    let reply = () => ndjson([{ error: { code: 'invalid', message: '文件沒有可用的文字內容' } }]);
    const { api } = setup(() => reply());
    await expect(api.ingestBrandDocument('selune', { name: 'a.md', text: ' ' }, () => {})).rejects.toThrow('文件沒有可用的文字內容');
    reply = () => ndjson(progress.slice(0, 2));
    await expect(api.ingestBrandDocument('selune', { name: 'a.md', text: 'x' }, () => {})).rejects.toThrow('文件上傳的進度中斷');
  });
});
```

- [ ] **Step 3: 修改 `web/src/lib/store/studio.test.ts`**

找到：

```ts
    expect(store().brief).toBe(DEMO_BRIEFS['misty-isle']);
  });

  it('prefills the form from a previous job input', async () => {
    await store().parse();
    const input = {
```

改成：

```ts
    expect(store().brief).toBe(DEMO_BRIEFS['misty-isle']);
  });

  it('picks up the current job again after the page reloads', async () => {
    await store().start();
    await vi.advanceTimersByTimeAsync(3_000);
    const jobId = store().view!.jobId;
    // 重新整理：store 回到初始狀態，任務仍在執行
    useStudioStore.setState({ brandId: null, view: null, input: null, templateIds: ['ecom-main'] });
    await store().restore('selune');
    expect(store()).toMatchObject({ brandId: 'selune', templateIds: ['ig-post'], input: { templateIds: ['ig-post'] } });
    expect(store().view!.jobId).toBe(jobId);
    await vi.advanceTimersByTimeAsync(14_500);
    expect(store().view!.outcome).toBe('done');
    expect(store().selection['ig-post']).toBe(store().view!.bestRenderIds['ig-post']);
  });

  it('starts empty after a reload when the job belongs to another brand or no longer exists', async () => {
    await store().start();
    useStudioStore.setState({ brandId: null, view: null });
    await store().restore('misty-isle');
    expect(store()).toMatchObject({ brandId: 'misty-isle', view: null });

    const getJob = vi.spyOn(getApiClient(), 'getJob').mockRejectedValueOnce(new Error('Unknown job'));
    useStudioStore.setState({ brandId: null, view: null });
    await store().restore('selune');
    expect(store().view).toBeNull();
    // 找不到的任務不再記住
    useStudioStore.setState({ brandId: null, view: null });
    await store().restore('selune');
    expect(getJob).toHaveBeenCalledTimes(1);
    getJob.mockRestore();
  });

  it('prefills the form from a previous job input', async () => {
    await store().parse();
    const input = {
```

- [ ] **Step 4: 執行測試確認失敗**

Run: `npx vitest run src/lib/api/http src/lib/store/studio.test.ts`
Expected: FAIL：
- `client.test.ts`、`job-socket.test.ts` 無法載入（`Cannot find module './client'`）。
- `studio.test.ts` 2 個測試失敗：「picks up the current job again after the page reloads」、「starts empty after a reload when the job belongs to another brand or no longer exists」。

- [ ] **Step 5: 建立 `web/src/lib/api/http/connection.ts`**

```ts
import type { ConnectionState, ConnectionStatus } from '@/types/contract';
import type { ConnectionChannel } from '../client';

/** 連線狀態：最近一次請求或 WebSocket 的結果。狀態沒變時 get() 回傳同一個物件（給 useSyncExternalStore）。 */
export class ConnectionTracker implements ConnectionChannel {
  private state: ConnectionState = Object.freeze({ status: 'connecting', transport: 'websocket', error: null });
  private readonly listeners = new Set<(state: ConnectionState) => void>();

  /** onWatch：第一次有人訂閱時呼叫（連線狀態有人看，才需要主動確認後端是否在線） */
  constructor(private readonly onWatch?: () => void) {}

  get watched(): boolean {
    return this.listeners.size > 0;
  }

  get(): ConnectionState {
    return this.state;
  }

  subscribe(listener: (state: ConnectionState) => void): () => void {
    this.listeners.add(listener);
    if (this.listeners.size === 1) this.onWatch?.();
    return () => {
      this.listeners.delete(listener);
    };
  }

  set(status: ConnectionStatus, error: string | null = null): void {
    if (this.state.status === status && this.state.error === error) return;
    this.state = Object.freeze({ status, transport: 'websocket', error });
    for (const listener of this.listeners) listener(this.state);
  }
}
```

- [ ] **Step 6: 建立 `web/src/lib/api/http/job-socket.ts`**

```ts
import type { JobMessage } from '@/types/contract';
import type { ConnectionTracker } from './connection';

/** 伺服器關閉代碼：任務不存在（不再重新連線） */
export const WS_NOT_FOUND = 4404;
/** 重新連線的等待時間：1 秒起每次加倍，最長 10 秒 */
export const RECONNECT_DELAY = { min: 1_000, max: 10_000 };

const FINISHED = new Set(['done', 'needs_review', 'cancelled', 'failed']);
const isFinal = (m: JobMessage) => m.type === 'job.status' && FINISHED.has(m.stage);

export interface JobSocketOptions {
  /** 從 seq 之後開始補送的 WebSocket 網址 */
  url: (after: number) => string;
  WebSocket: typeof WebSocket;
  connection: ConnectionTracker;
}

/**
 * 訂閱任務事件：伺服器先補送已發生的事件，再轉送即時事件；任務結束且事件送完後以 1000 關閉。
 * 連線中斷時以最後收到的 seq 重新連線，並依 seq 略過重複的事件。回傳取消訂閱的函式。
 */
export function openJobSocket(
  jobId: string,
  onEvent: (message: JobMessage) => void,
  onError: (error: Error) => void,
  { url, WebSocket, connection }: JobSocketOptions,
): () => void {
  let socket: WebSocket | null = null;
  let retry: ReturnType<typeof setTimeout> | null = null;
  let delay = RECONNECT_DELAY.min;
  let lastSeq = 0;
  let finished = false;
  let stopped = false;

  const fail = (error: Error) => {
    stopped = true;
    socket?.close();
    onError(error);
  };

  const connect = () => {
    retry = null;
    let ws: WebSocket;
    try {
      ws = new WebSocket(url(lastSeq));
    } catch (err) {
      // 與 WebSocket 的其他錯誤一樣非同步回報
      queueMicrotask(() => {
        if (!stopped) fail(err instanceof Error ? err : new Error(String(err)));
      });
      return;
    }
    socket = ws;
    ws.onopen = () => {
      delay = RECONNECT_DELAY.min;
      connection.set('connected');
    };
    ws.onmessage = (e: MessageEvent) => {
      if (stopped) return;
      let message: JobMessage;
      try {
        message = JSON.parse(String(e.data)) as JobMessage;
      } catch {
        fail(new Error(`任務 ${jobId} 的事件格式錯誤`));
        return;
      }
      // 重新連線時伺服器從 lastSeq 之後補送；保險起見仍略過重複的事件
      if (message.seq <= lastSeq) return;
      lastSeq = message.seq;
      finished ||= isFinal(message);
      try {
        onEvent(message);
      } catch (err) {
        // 單一訂閱者出錯不可中斷事件流（與 mock 相同）
        console.error('[HttpApiClient] subscriber threw while handling', message.type, err);
      }
    };
    ws.onclose = (e: CloseEvent) => {
      socket = null;
      if (stopped || finished || e.code === 1000) return;
      if (e.code === WS_NOT_FOUND) {
        fail(new Error(`找不到任務：${jobId}`));
        return;
      }
      connection.set('disconnected', `任務事件的連線中斷，${delay / 1000} 秒後重新連線`);
      retry = setTimeout(connect, delay);
      delay = Math.min(delay * 2, RECONNECT_DELAY.max);
    };
  };

  connect();
  return () => {
    stopped = true;
    if (retry) clearTimeout(retry);
    socket?.close();
  };
}
```

- [ ] **Step 7: 建立 `web/src/lib/api/http/client.ts`**

```ts
import type {
  ApiOptions, Brand, BrandDocument, ChannelTemplate, Copy, DashboardStats, HistoryEntry, IngestEvent, JobInput, JobMessage,
  JobSummary, LocalPhoto, ParsedBrief, Product, ProductPhoto, RagChunk, SystemStatus,
} from '@/types/contract';
import type { ApiClient, JobSnapshot, ProductDraft } from '../client';
import { ConnectionTracker } from './connection';
import { openJobSocket, RECONNECT_DELAY } from './job-socket';

/** 後端回傳的錯誤（{ error: { code, message } }，message 為繁體中文，可直接顯示） */
export class ApiError extends Error {
  constructor(readonly code: string, message: string, readonly status: number) {
    super(message);
    this.name = 'ApiError';
  }
}

export interface HttpApiClientOptions {
  /** 後端網址；省略時同源（正式版由 nginx、開發時由 next dev 的 rewrites 轉給 api） */
  baseUrl?: string;
  fetch?: typeof fetch;
  WebSocket?: typeof WebSocket;
}

type IngestLine = IngestEvent | { error: { code: string; message: string } };

const q = encodeURIComponent;
const query = (brandId?: string) => (brandId ? `?brandId=${q(brandId)}` : '');
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function toApiError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as { error?: { code?: string; message?: string } };
    if (body.error?.message) return new ApiError(body.error.code ?? 'error', body.error.message, res.status);
  } catch {
    // 不是後端的 JSON（例如 nginx 的錯誤頁）
  }
  return new ApiError('http_error', `後端回應 HTTP ${res.status}`, res.status);
}

/** 逐行讀取 NDJSON（一個 chunk 可能含多行，也可能只有半行） */
async function* readLines(res: Response): AsyncGenerator<string> {
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = done ? '' : (lines.pop() ?? '');
    for (const line of lines) if (line.trim()) yield line;
    if (done) return;
  }
}

/** live 模式：連線 FastAPI。REST 使用 fetch；任務事件使用 WebSocket，斷線後以最後的 seq 重新連線。 */
export class HttpApiClient implements ApiClient {
  readonly demo = null;
  readonly connection: ConnectionTracker;
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly WebSocketImpl: typeof WebSocket;
  private probing = false;

  constructor(options: HttpApiClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? '';
    // 不可直接存 fetch 再以 this.fetchImpl() 呼叫：瀏覽器會丟出 Illegal invocation
    this.fetchImpl = options.fetch ?? ((input, init) => fetch(input, init));
    this.WebSocketImpl = options.WebSocket ?? WebSocket;
    this.connection = new ConnectionTracker(() => void this.probe());
  }

  /** 送出請求；連不上後端時更新連線狀態，非 2xx 時丟出 ApiError */
  private async send(path: string, init: RequestInit = {}): Promise<Response> {
    let res: Response;
    try {
      res = await this.fetchImpl(this.baseUrl + path, init);
    } catch {
      this.lost('無法連線到後端');
      throw new ApiError('network', '無法連線到後端，請確認服務已啟動', 0);
    }
    // 502、504：nginx 連不上 api
    if (res.status === 502 || res.status === 504) this.lost(`後端沒有回應（HTTP ${res.status}）`);
    else this.connection.set('connected');
    if (!res.ok) throw await toApiError(res);
    return res;
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const init: RequestInit = { method };
    if (body instanceof FormData) init.body = body;
    else if (body !== undefined) {
      init.body = JSON.stringify(body);
      init.headers = { 'content-type': 'application/json' };
    }
    const res = await this.send(path, init);
    return (res.status === 204 ? undefined : await res.json()) as T;
  }

  private lost(error: string) {
    this.connection.set('disconnected', error);
    if (this.connection.watched) void this.probe();
  }

  /** 連線中斷時定期確認後端是否恢復（有人看連線狀態時才做） */
  private async probe() {
    if (this.probing) return;
    this.probing = true;
    try {
      for (let delay = RECONNECT_DELAY.min; ; delay = Math.min(delay * 2, RECONNECT_DELAY.max)) {
        try {
          await this.send('/api/health');
          return;
        } catch {
          await sleep(delay);
        }
      }
    } finally {
      this.probing = false;
    }
  }

  private socketUrl(path: string): string {
    const url = new URL(path, this.baseUrl || window.location.origin);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    return url.toString();
  }

  getOptions(): Promise<ApiOptions> {
    return this.request('GET', '/api/options');
  }

  getSystemStatus(): Promise<SystemStatus> {
    return this.request('GET', '/api/status');
  }

  listBrands(): Promise<Brand[]> {
    return this.request('GET', '/api/brands');
  }

  async ingestBrandDocument(brandId: string, doc: BrandDocument, onEvent: (e: IngestEvent) => void): Promise<RagChunk[]> {
    const res = await this.send(`/api/brands/${q(brandId)}/documents`, {
      method: 'POST', body: JSON.stringify(doc), headers: { 'content-type': 'application/json' },
    });
    let chunks: RagChunk[] = [];
    for await (const line of readLines(res)) {
      const message = JSON.parse(line) as IngestLine;
      if ('error' in message) throw new ApiError(message.error.code, message.error.message, res.status);
      if (message.type === 'ingest.chunked') chunks = message.chunks;
      try {
        onEvent(message);
      } catch (err) {
        console.error('[HttpApiClient] ingest listener threw while handling', message.type, err);
      }
      if (message.type === 'ingest.stored') return chunks;
    }
    throw new ApiError('network', '文件上傳的進度中斷，請重新整理後確認知識庫', 0);
  }

  listTemplates(): Promise<ChannelTemplate[]> {
    return this.request('GET', '/api/templates');
  }

  listProducts(brandId: string): Promise<Product[]> {
    return this.request('GET', `/api/products${query(brandId)}`);
  }

  saveProduct(draft: ProductDraft): Promise<Product> {
    return draft.id ? this.request('PUT', `/api/products/${q(draft.id)}`, draft) : this.request('POST', '/api/products', draft);
  }

  deleteProduct(id: string): Promise<void> {
    return this.request('DELETE', `/api/products/${q(id)}`);
  }

  uploadProductPhoto(file: Blob): Promise<ProductPhoto> {
    const form = new FormData();
    form.append('file', file, file instanceof File ? file.name : 'photo');
    return this.request('POST', '/api/products/photos', form);
  }

  requestCutout(productId: string): Promise<Product> {
    return this.request('POST', `/api/products/${q(productId)}/cutout`);
  }

  listLocalPhotos(): Promise<LocalPhoto[] | null> {
    return this.request('GET', '/api/local-photos');
  }

  importLocalPhoto(file: string, brandId: string): Promise<Product> {
    return this.request('POST', `/api/local-photos/${q(file)}/import`, { brandId });
  }

  parseBrief(brandId: string, text: string, productId: string | null): Promise<ParsedBrief> {
    return this.request('POST', '/api/briefs/parse', { brandId, text, productId });
  }

  createJob(input: JobInput): Promise<{ jobId: string }> {
    return this.request('POST', '/api/jobs', input);
  }

  subscribe(jobId: string, onEvent: (event: JobMessage) => void, onError?: (error: Error) => void): () => void {
    return openJobSocket(jobId, onEvent, onError ?? ((err) => console.error('[HttpApiClient]', err.message)), {
      url: (after) => this.socketUrl(`/ws/jobs/${q(jobId)}?after=${after}`),
      WebSocket: this.WebSocketImpl,
      connection: this.connection,
    });
  }

  cancelJob(jobId: string): Promise<void> {
    return this.request('POST', `/api/jobs/${q(jobId)}/cancel`);
  }

  listJobs(): Promise<JobSummary[]> {
    return this.request('GET', '/api/jobs');
  }

  getJob(jobId: string): Promise<JobSnapshot> {
    return this.request('GET', `/api/jobs/${q(jobId)}`);
  }

  selectRender(jobId: string, renderId: string, copy: Copy): Promise<HistoryEntry> {
    return this.request('POST', `/api/jobs/${q(jobId)}/select`, { renderId, copy });
  }

  listHistory(brandId?: string): Promise<HistoryEntry[]> {
    return this.request('GET', `/api/history${query(brandId)}`);
  }

  setFavorite(historyId: string, favorite: boolean): Promise<HistoryEntry> {
    return this.request('PATCH', `/api/history/${q(historyId)}`, { favorite });
  }

  getDashboardStats(brandId?: string): Promise<DashboardStats> {
    return this.request('GET', `/api/stats${query(brandId)}`);
  }
}
```

- [ ] **Step 8: 修改 `web/src/lib/api/index.ts`**

找到（1／2）：

```ts
import type { ApiClient } from './client';
import { MockApiClient } from './mock/client';
import { IdbStore } from './mock/idb-store';
import { MemoryStore } from './mock/store';
```

改成：

```ts
import type { ApiClient } from './client';
import { HttpApiClient } from './http/client';
import { MockApiClient } from './mock/client';
import { IdbStore } from './mock/idb-store';
import { MemoryStore } from './mock/store';
```

找到（2／2）：

```ts
let instance: ApiClient | null = null;

/**
 * 依 NEXT_PUBLIC_API_MODE 選擇實作（預設 mock）。第二階段加入 live → HttpApiClient。
 * 單例內含計時器與訂閱，只能在 client component 的事件處理、effect 或 store action 中呼叫，不可在伺服器端 render 時呼叫。
 */
export function getApiClient(): ApiClient {
  if (instance) return instance;
  if (API_MODE !== 'mock') throw new Error(`API 模式「${API_MODE}」尚未實作：第二階段會加入連線 FastAPI 的 HttpApiClient`);
  // 瀏覽器把商品、歷史紀錄與上傳文件存在 IndexedDB；測試環境沒有 indexedDB，改用記憶體
  instance = new MockApiClient(typeof indexedDB === 'undefined' ? new MemoryStore() : new IdbStore());
  return instance;
}
```

改成：

```ts
let instance: ApiClient | null = null;

/**
 * 依 NEXT_PUBLIC_API_MODE 選擇實作：mock（預設，瀏覽器內模擬）或 live（連線 FastAPI）。
 * 單例內含計時器與訂閱，只能在 client component 的事件處理、effect 或 store action 中呼叫，不可在伺服器端 render 時呼叫。
 */
export function getApiClient(): ApiClient {
  if (instance) return instance;
  if (API_MODE === 'live') instance = new HttpApiClient();
  else if (API_MODE === 'mock') {
    // 瀏覽器把商品、歷史紀錄與上傳文件存在 IndexedDB；測試環境沒有 indexedDB，改用記憶體
    instance = new MockApiClient(typeof indexedDB === 'undefined' ? new MemoryStore() : new IdbStore());
  } else throw new Error(`不支援的 API 模式「${API_MODE}」：NEXT_PUBLIC_API_MODE 請設定為 mock 或 live`);
  return instance;
}
```

- [ ] **Step 9: 改寫 `web/src/lib/store/studio.ts`（完整內容）**

事件訂閱抽成 `follow(jobId)`，`start` 與 `restore` 共用；store 的建立函式因此改為區塊，整個檔案的縮排都變了。

```ts
import { create } from 'zustand';
import type { Copy, Engine, JobInput, ParsedBrief, TemplateId, Tone } from '@/types/contract';
import { API_MODE, getApiClient } from '@/lib/api';
import { MOCK_OPTIONS } from '@/lib/api/mock/options';
import { defaultSelection, emptyJobView, reduceJob, type JobView } from '@/lib/jobs/view';
import { useAppStore } from './app';

export const ENGINE_LABEL: Record<Engine, string> = { comfyui: 'ComfyUI（SDXL + ControlNet + IP-Adapter）', ideogram: 'Ideogram 4.0' };
export const TONE_LABEL: Record<Tone, string> = { gentle: '溫柔療癒', science: '專業科研', playful: '活潑年輕', minimal: '簡約' };

/** 各品牌的示範需求（第一個就是規格書的 Demo 句） */
export const DEMO_BRIEFS: Record<string, string> = {
  selune: '幫我做週年慶的精華液海報，主打買一送一，要溫柔療癒的感覺',
  'misty-isle': '幫我設計一款簡約風格的冷萃咖啡宣傳海報',
};

export interface StudioForm {
  brief: string;
  productId: string | null;
  parsed: ParsedBrief | null;
  templateIds: TemplateId[];
  variants: number;
  llm: string;
  engine: Engine;
  vlm: string;
  maxRetries: number;
}

interface StudioState extends StudioForm {
  brandId: string | null;
  parsing: boolean;
  starting: boolean;
  /** 目前（或上一個）任務的輸入 */
  input: JobInput | null;
  /** 還沒開始任務時為 null */
  view: JobView | null;
  /** 每個模板選定的候選 */
  selection: Partial<Record<TemplateId, string>>;
  /** 文字編輯器中的文案（所有選定的模板共用） */
  copy: Copy | null;
  /** 已寫入歷史紀錄的候選：renderId → 當時的文案（JSON），重複匯出時不重複寫入 */
  saved: Record<string, string>;
  error: string | null;
  setForm: (patch: Partial<StudioForm>) => void;
  patchParsed: (patch: Partial<ParsedBrief>) => void;
  toggleTemplate: (id: TemplateId) => void;
  /** 切換品牌：清掉表單與結果 */
  resetForBrand: (brandId: string) => void;
  /** 頁面載入後第一次進入：重設表單；這個分頁剛才有這個品牌的任務時接續顯示（執行中的繼續接收事件） */
  restore: (brandId: string) => Promise<void>;
  /** 歷史紀錄「以相同設定重做」 */
  prefill: (input: JobInput) => void;
  parse: () => Promise<void>;
  start: () => Promise<void>;
  cancel: () => Promise<void>;
  select: (templateId: TemplateId, renderId: string) => void;
  setCopy: (copy: Copy) => void;
  /** 把選定的候選與目前文案寫入歷史紀錄（標記已回寫 RAG）；回傳新寫入的筆數 */
  saveSelection: () => Promise<number>;
}

/** 表單預設值：模型與引擎取目前可用的第一個；live 模式真的會用到 GPU，預設每個模板 2 張 */
function defaultForm(): Omit<StudioForm, 'brief'> {
  const options = useAppStore.getState().options ?? MOCK_OPTIONS;
  return {
    productId: null, parsed: null, templateIds: ['ecom-main', 'ig-post'], variants: API_MODE === 'live' ? 2 : 4,
    llm: options.llm[0], engine: options.engines[0], vlm: options.vlm[0], maxRetries: 2,
  };
}

function formOf(input: JobInput): StudioForm {
  return {
    brief: input.brief, productId: input.productId, parsed: structuredClone(input.parsedBrief), templateIds: [...input.templateIds],
    variants: input.variantsPerTemplate, llm: input.llm, engine: input.engine, vlm: input.vlm, maxRetries: input.maxRetries,
  };
}

/** 這個分頁目前的任務（sessionStorage，重新整理後仍在）；沒有 sessionStorage 時（測試）記在模組內 */
interface CurrentJob { jobId: string; brandId: string }
const CURRENT_JOB_KEY = 'genai-agent:studio-job';
let currentJobFallback: CurrentJob | null = null;

function rememberJob(job: CurrentJob | null) {
  currentJobFallback = job;
  try {
    if (job) sessionStorage.setItem(CURRENT_JOB_KEY, JSON.stringify(job));
    else sessionStorage.removeItem(CURRENT_JOB_KEY);
  } catch {
    // 沒有 sessionStorage（測試環境、或瀏覽器停用儲存）
  }
}

function rememberedJob(): CurrentJob | null {
  try {
    const raw = sessionStorage.getItem(CURRENT_JOB_KEY);
    return raw ? (JSON.parse(raw) as CurrentJob) : null;
  } catch {
    return currentJobFallback;
  }
}

/** 事件訂閱放在 store 外：換頁再回來，生成仍在進行 */
let stopListening: (() => void) | null = null;
const stop = () => {
  stopListening?.();
  stopListening = null;
};

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

export const useStudioStore = create<StudioState>()((set, get) => {
  /** 接收任務事件（伺服器先重播已發生的事件）；任務結束時預設選最佳候選，文案編輯器帶入它的文案 */
  const follow = (jobId: string) => {
    stopListening = getApiClient().subscribe(
      jobId,
      (e) =>
        set((st) => {
          if (!st.view || st.view.jobId !== jobId) return {};
          const view = reduceJob(st.view, e);
          if (st.view.outcome === 'running' && (view.outcome === 'done' || view.outcome === 'needs_review')) {
            const selection = defaultSelection(view);
            const first = Object.values(selection)[0];
            return { view, selection, copy: first ? structuredClone(view.renders[first].spec.copy) : null };
          }
          return { view };
        }),
      (err) => set({ error: message(err) }),
    );
  };

  return {
    ...defaultForm(),
    brief: '',
    brandId: null,
    parsing: false,
    starting: false,
    input: null,
    view: null,
    selection: {},
    copy: null,
    saved: {},
    error: null,

    setForm: (patch) => set(patch),
    patchParsed: (patch) => {
      const parsed = get().parsed;
      if (parsed) set({ parsed: { ...parsed, ...patch } });
    },
    toggleTemplate: (id) => {
      const ids = get().templateIds;
      set({ templateIds: ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id] });
    },

    resetForBrand: (brandId) => {
      stop();
      set({
        ...defaultForm(), brandId, brief: DEMO_BRIEFS[brandId] ?? '', parsing: false, starting: false,
        input: null, view: null, selection: {}, copy: null, saved: {}, error: null,
      });
    },

    restore: async (brandId) => {
      get().resetForBrand(brandId);
      const current = rememberedJob();
      if (current?.brandId !== brandId) return;
      let input: JobInput;
      try {
        input = (await getApiClient().getJob(current.jobId)).summary.input;
      } catch {
        // 任務已不存在（例如 mock 模式重新整理後，執行中的任務不會保留）
        rememberJob(null);
        return;
      }
      // 讀取期間使用者已切換品牌或開始新任務
      if (get().brandId !== brandId || get().view) return;
      set({ ...formOf(input), input, view: emptyJobView(current.jobId), selection: {}, copy: null, saved: {}, error: null });
      follow(current.jobId);
    },

    prefill: (input) => {
      stop();
      rememberJob(null);
      set({
        ...formOf(input), brandId: input.brandId, input: null, view: null, selection: {}, copy: null, saved: {}, error: null,
      });
    },

    parse: async () => {
      const { brandId, brief, productId } = get();
      if (!brandId || !brief.trim()) return;
      set({ parsing: true, error: null });
      try {
        set({ parsed: await getApiClient().parseBrief(brandId, brief, productId) });
      } catch (err) {
        set({ error: message(err) });
      } finally {
        set({ parsing: false });
      }
    },

    start: async () => {
      const s = get();
      if (!s.brandId) return;
      if (!s.brief.trim()) return set({ error: '請先輸入一句話需求' });
      if (!s.productId) return set({ error: '請先選擇商品' });
      if (!s.templateIds.length) return set({ error: '至少要選一個通路模板' });
      set({ starting: true, error: null });
      const api = getApiClient();
      try {
        const parsed = s.parsed ?? (await api.parseBrief(s.brandId, s.brief, s.productId));
        const input: JobInput = {
          brandId: s.brandId, productId: s.productId, brief: s.brief, parsedBrief: parsed, templateIds: [...s.templateIds],
          variantsPerTemplate: s.variants, llm: s.llm, engine: s.engine, vlm: s.vlm, maxRetries: s.maxRetries,
        };
        const { jobId } = await api.createJob(input);
        stop();
        rememberJob({ jobId, brandId: input.brandId });
        set({ parsed, input, view: emptyJobView(jobId), selection: {}, copy: null, saved: {} });
        follow(jobId);
      } catch (err) {
        set({ error: message(err) });
      } finally {
        set({ starting: false });
      }
    },

    cancel: async () => {
      const jobId = get().view?.jobId;
      if (jobId) await getApiClient().cancelJob(jobId);
    },

    select: (templateId, renderId) => set({ selection: { ...get().selection, [templateId]: renderId } }),
    setCopy: (copy) => set({ copy }),

    saveSelection: async () => {
      const { view, selection, copy, saved } = get();
      if (!view?.jobId || !copy) return 0;
      const key = JSON.stringify(copy);
      const todo = Object.values(selection).filter((id): id is string => id !== undefined && saved[id] !== key);
      const api = getApiClient();
      for (const id of todo) await api.selectRender(view.jobId, id, copy);
      set({ saved: { ...get().saved, ...Object.fromEntries(todo.map((id) => [id, key])) } });
      return todo.length;
    },
  };
});
```

- [ ] **Step 10: 修改 `web/src/app/studio/page.tsx`**

找到：

```tsx
  const studioBrandId = useStudioStore((s) => s.brandId);
  const productId = useStudioStore((s) => s.productId);
  const resetForBrand = useStudioStore((s) => s.resetForBrand);
  const setForm = useStudioStore((s) => s.setForm);

  useEffect(() => {
    void loadProducts(brand.id);
  }, [brand.id, loadProducts]);

  useEffect(() => {
    if (studioBrandId !== brand.id) resetForBrand(brand.id);
  }, [brand.id, studioBrandId, resetForBrand]);

  // 預設選第一個商品
  useEffect(() => {
```

改成：

```tsx
  const studioBrandId = useStudioStore((s) => s.brandId);
  const productId = useStudioStore((s) => s.productId);
  const resetForBrand = useStudioStore((s) => s.resetForBrand);
  const restore = useStudioStore((s) => s.restore);
  const setForm = useStudioStore((s) => s.setForm);

  useEffect(() => {
    void loadProducts(brand.id);
  }, [brand.id, loadProducts]);

  // 頁面載入後第一次進入時接續這個分頁的任務；之後切換品牌則清掉表單與結果
  useEffect(() => {
    if (studioBrandId === null) void restore(brand.id);
    else if (studioBrandId !== brand.id) resetForBrand(brand.id);
  }, [brand.id, studioBrandId, resetForBrand, restore]);

  // 預設選第一個商品
  useEffect(() => {
```

- [ ] **Step 11: 執行測試確認通過**

Run: `npx vitest run src/lib/api/http src/lib/store/studio.test.ts`
Expected: PASS（`job-socket.test.ts` 5 個、`client.test.ts` 6 個、`studio.test.ts` 11 個）。

- [ ] **Step 12: 修改 `web/next.config.ts`**（開發時 `/ws` 也轉給後端）

找到（1／2）：

```ts

/**
 * 建置時靜態輸出（out/）：live 版由 nginx 提供，mock 版部署到 Cloudflare Pages。
 * next dev 時若設定 API_PROXY_URL（例如 http://localhost:8000），把 /api 與 /files 轉給本機後端；
 * 靜態輸出不支援 rewrites，所以只在開發伺服器加上。
 */
export default function nextConfig(phase: string): NextConfig {
  const proxy = process.env.API_PROXY_URL;
```

改成：

```ts

/**
 * 建置時靜態輸出（out/）：live 版由 nginx 提供，mock 版部署到 Cloudflare Pages。
 * next dev 時若設定 API_PROXY_URL（例如 http://127.0.0.1:8000），把 /api、/files 與 /ws（WebSocket）轉給本機後端，
 * 前端一律使用同源網址；靜態輸出不支援 rewrites，所以只在開發伺服器加上。
 */
export default function nextConfig(phase: string): NextConfig {
  const proxy = process.env.API_PROXY_URL;
```

找到（2／2）：

```ts
          rewrites: async () => [
            { source: '/api/:path*', destination: `${proxy}/api/:path*` },
            { source: '/files/:path*', destination: `${proxy}/files/:path*` },
          ],
        }
      : {};
```

改成：

```ts
          rewrites: async () => [
            { source: '/api/:path*', destination: `${proxy}/api/:path*` },
            { source: '/files/:path*', destination: `${proxy}/files/:path*` },
            { source: '/ws/:path*', destination: `${proxy}/ws/:path*` },
          ],
        }
      : {};
```

- [ ] **Step 13: 修改 `web/src/components/product/upload-zone.tsx`**（live 模式的照片存在後端）

找到（1／2）：

```tsx
import { toast } from 'sonner';
import type { Brand } from '@/types/contract';
import { Button } from '@/components/ui/button';
import { getApiClient } from '@/lib/api';
import { downscaleImage, nameFromFile } from '@/lib/image/downscale';
import { useProductsStore } from '@/lib/store/products';
import { cn } from '@/lib/utils';

/** 上傳／拖放商品照：縮圖後交給 ApiClient 保存，再建立商品（價格與特徵之後再補） */
export function UploadZone({ brand }: { brand: Brand }) {
```

改成：

```tsx
import { toast } from 'sonner';
import type { Brand } from '@/types/contract';
import { Button } from '@/components/ui/button';
import { API_MODE, getApiClient } from '@/lib/api';
import { downscaleImage, nameFromFile } from '@/lib/image/downscale';
import { useProductsStore } from '@/lib/store/products';
import { cn } from '@/lib/utils';

const STORED_AT = API_MODE === 'live' ? '照片已上傳到後端（data/uploads/）。' : '照片存在這台電腦的瀏覽器（IndexedDB）。';

/** 上傳／拖放商品照：縮圖後交給 ApiClient 保存，再建立商品（價格與特徵之後再補） */
export function UploadZone({ brand }: { brand: Brand }) {
```

找到（2／2）：

```tsx
        const photo = await api.uploadProductPhoto(await downscaleImage(file));
        await save({ brandId: brand.id, name: nameFromFile(file.name), features: [], price: { sale: 0, original: 0 }, photo, cutout: null });
      }
      toast.success(`已新增 ${images.length} 個商品`, { description: '照片存在這台電腦的瀏覽器（IndexedDB）。請補上價格與特徵。' });
    } catch (err) {
      toast.error('上傳失敗', { description: err instanceof Error ? err.message : String(err) });
    } finally {
```

改成：

```tsx
        const photo = await api.uploadProductPhoto(await downscaleImage(file));
        await save({ brandId: brand.id, name: nameFromFile(file.name), features: [], price: { sale: 0, original: 0 }, photo, cutout: null });
      }
      toast.success(`已新增 ${images.length} 個商品`, { description: `${STORED_AT}請補上價格與特徵。` });
    } catch (err) {
      toast.error('上傳失敗', { description: err instanceof Error ? err.message : String(err) });
    } finally {
```

- [ ] **Step 14: 全部驗證**

Run: `npm run test && npm run typecheck && npm run lint`
Expected: 41 個測試檔、310 個測試全部通過；沒有錯誤。

Run: `npm run e2e`
Expected: 5 passed（mock 模式不受影響）。

- [ ] **Step 15: 在瀏覽器確認 live 模式**

1. 啟動後端（Task 12 Step 20 的三個服務）。
2. 在 `web/` 執行 `NEXT_PUBLIC_API_MODE=live API_PROXY_URL=http://127.0.0.1:8000 npm run dev`，開啟 http://localhost:3000/studio。

確認：
- 右上角顯示「WebSocket 已連線」，點開列出各服務的狀態。
- 開始生成後進度即時更新；生成途中重新整理，頁面接續同一個任務並完成。
- 歷史紀錄、Agent 透視、成效儀表板顯示後端的資料。
- 品牌知識庫上傳 `.md` 文件時逐步顯示進度；商品庫可上傳照片與去背。

- [ ] **Step 16: Commit**

```bash
git add \
  web/next.config.ts \
  web/src/app/studio/page.tsx \
  web/src/components/product/upload-zone.tsx \
  web/src/lib/api/http/client.test.ts \
  web/src/lib/api/http/client.ts \
  web/src/lib/api/http/connection.ts \
  web/src/lib/api/http/job-socket.test.ts \
  web/src/lib/api/http/job-socket.ts \
  web/src/lib/api/index.ts \
  web/src/lib/store/studio.test.ts \
  web/src/lib/store/studio.ts
git commit -m "feat: connect the frontend to FastAPI in live mode with a reconnecting WebSocket client" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: 使用者自己的品牌：模擬流程與 Logo 圖檔


**Files:**
- Modify: `web/src/lib/api/mock/flaws.ts`、`web/src/lib/api/mock/scenario.ts`、`web/composer/handlers.ts`、`web/src/lib/compose/scene.ts`、`web/src/lib/compose/paint.ts`、`web/src/lib/compose/render.ts`、`backend/app/brands.py`、`brands/_template.yaml`
- Test: `web/src/lib/api/mock/flaws.test.ts`、`web/src/lib/compose/scene.test.ts`、`web/src/lib/api/mock/review.test.ts`、`web/src/lib/review/recheck.test.ts`、`backend/tests/test_brands.py`、`backend/tests/test_parity.py`

**Interfaces:**
- Consumes：Task 5 的品牌設定檔；Task 8 的 composer；Task 12 的 `/files/brands/…`
- Produces：
  - `flawData(brand)`、`applyFlaws(spec, flaws, brand)`：
    - 示範品牌沿用固定的失誤。
    - 其他品牌的偏色取兩組示範偏色中、與品牌主色色差較大的一組。
    - 含禁用詞的副標取品牌前兩個禁用詞；沒有禁用詞時不製造這個失誤。
    - 示範品牌的結果不變，golden fixtures 不需要重新產生。
  - `LogoOp.image: string | null`、`fitLogoImage(box, width, height): Rect`（等比例、靠左、垂直置中）、`PaintAssets.logo`：
    - 有 Logo 圖檔時畫圖檔。
    - 載入失敗時改畫原本的標誌與字標。
  - `brands.LOGO_TYPES`：Logo 只接受 PNG、JPEG、WebP、SVG（與 `/files` 提供的格式相同），其他格式在系統狀態顯示原因

這個 Task 修正驗證時發現的問題：以 `_template.yaml` 建立自己的品牌後，第一輪的模擬失誤只認得兩個示範品牌，任務直接失敗（`No flaw data for brand`）；`Brand.logo` 也沒有畫到海報上。

- [ ] **Step 1: 修改 `web/src/lib/api/mock/flaws.test.ts`**（先寫失敗測試）

找到（1／2）：

```ts
describe('applyFlaws', () => {
  it('applies every flaw without mutating the input', () => {
    const spec = cleanSpec();
    const bad = applyFlaws(spec, FLAWS);
    expect(spec.palette).toEqual(SELUNE.palette);
    expect(bad.palette.primary).toBe('#E0458A');
    expect(bad.copy.subhead).toBe('7天根治暗沉・醫療級修護');
```

改成：

```ts
describe('applyFlaws', () => {
  it('applies every flaw without mutating the input', () => {
    const spec = cleanSpec();
    const bad = applyFlaws(spec, FLAWS, SELUNE);
    expect(spec.palette).toEqual(SELUNE.palette);
    expect(bad.palette.primary).toBe('#E0458A');
    expect(bad.copy.subhead).toBe('7天根治暗沉・醫療級修護');
```

找到（2／2）：

```ts
  });

  it('applies only the requested flaws', () => {
    const bad = applyFlaws(cleanSpec(), ['bannedCopy']);
    expect(bad.palette).toEqual(SELUNE.palette);
    expect(bad.copy.subhead).toBe('7天根治暗沉・醫療級修護');
  });

  it('throws for brands without flaw data', () => {
    expect(() => applyFlaws({ ...cleanSpec(), brandId: 'nope' }, ['bannedCopy'])).toThrow('No flaw data');
  });
});
```

改成：

```ts
  });

  it('applies only the requested flaws', () => {
    const bad = applyFlaws(cleanSpec(), ['bannedCopy'], SELUNE);
    expect(bad.palette).toEqual(SELUNE.palette);
    expect(bad.copy.subhead).toBe('7天根治暗沉・醫療級修護');
  });

  it('derives the flaws of other brands from their own palette and banned words', () => {
    const blue = { ...SELUNE, id: 'my-brand', palette: { ...SELUNE.palette, primary: '#1E6FD9' as const }, bannedWords: ['根治', '治療', '保證有效'] };
    const bad = applyFlaws(cleanSpec(), FLAWS, blue);
    // 兩組示範偏色中，與品牌主色差最多的一組
    expect(bad.palette.primary).toBe('#E0458A');
    expect(bad.copy.subhead).toBe('根治・治療');
    const pink = { ...blue, palette: { ...blue.palette, primary: '#E0458A' as const } };
    expect(applyFlaws(cleanSpec(), ['offPalette'], pink).palette.primary).toBe('#1E88E5');
  });

  it('leaves the subhead alone when the brand has no banned words', () => {
    const plain = { ...SELUNE, id: 'my-brand', bannedWords: [] };
    expect(applyFlaws(cleanSpec(), ['bannedCopy'], plain).copy.subhead).toBe(cleanSpec().copy.subhead);
  });
});
```

- [ ] **Step 2: 修改 `web/src/lib/compose/scene.test.ts`**

找到（1／2）：

```ts
import { CHANNEL_TEMPLATES } from './templates';
import { boxMap } from './layout';
import {
  composePoster, formatPrice, logoFor, textBounds, type BadgeOp, type LogoOp, type PillOp, type SceneInput, type TextOp,
} from './scene';
import { cleanSpec } from '@/test/fixtures';
import { SELUNE } from '@/lib/api/mock/data';
```

改成：

```ts
import { CHANNEL_TEMPLATES } from './templates';
import { boxMap } from './layout';
import {
  composePoster, fitLogoImage, formatPrice, logoFor, textBounds, type BadgeOp, type LogoOp, type PillOp, type SceneInput,
  type TextOp,
} from './scene';
import { cleanSpec } from '@/test/fixtures';
import { SELUNE } from '@/lib/api/mock/data';
```

找到（2／2）：

```ts
  });
});

describe('helpers', () => {
  it('logoFor picks a mark and the latin wordmark', () => {
    expect(logoFor({ id: 'selune', name: 'SÉLUNE 晞月' })).toEqual({ mark: 'crescent', wordmark: 'SÉLUNE' });
```

改成：

```ts
  });
});

describe('brand logo image', () => {
  const spec = cleanSpec();
  const logoOf = (input: SceneInput) => composePoster(input).ops.find((o): o is LogoOp => o.kind === 'logo')!;

  it('draws the vector mark when the brand has no logo image', () => {
    expect(logoOf(sceneInput(spec)).image).toBeNull();
  });

  it('uses the logo image and keeps the wordmark as the fallback', () => {
    const logo = logoOf({ ...sceneInput(spec), brand: { ...SELUNE, logo: { url: '/files/brands/assets/selune.png' } } });
    expect(logo.image).toBe('/files/brands/assets/selune.png');
    expect(logo.wordmark?.text).toBe('SÉLUNE');
  });

  it('fits the image inside the logo box: same aspect ratio, left aligned and vertically centred', () => {
    const box = { x: 10, y: 20, w: 300, h: 60 };
    expect(fitLogoImage(box, 400, 100)).toEqual({ x: 10, y: 20, w: 240, h: 60 });
    expect(fitLogoImage(box, 1200, 100)).toEqual({ x: 10, y: 37.5, w: 300, h: 25 });
    expect(fitLogoImage(box, 100, 200)).toEqual({ x: 10, y: 20, w: 30, h: 60 });
  });
});

describe('helpers', () => {
  it('logoFor picks a mark and the latin wordmark', () => {
    expect(logoFor({ id: 'selune', name: 'SÉLUNE 晞月' })).toEqual({ mark: 'crescent', wordmark: 'SÉLUNE' });
```

- [ ] **Step 3: 修改 `web/src/lib/api/mock/review.test.ts`**（`applyFlaws` 多了品牌參數）

找到：

```ts
  });

  it('fails a fully flawed spec on both rules and VLM', () => {
    const r = reviewRender(applyFlaws(cleanSpec(), FLAWS), SELUNE, 0, 1);
    expect(r.passed).toBe(false);
    expect(r.checks.filter((c) => c.status === 'fail').map((c) => c.id)).toEqual([
      'banned_words', 'color_delta', 'logo_clearance', 'vlm_exaggeration', 'vlm_occlusion',
```

改成：

```ts
  });

  it('fails a fully flawed spec on both rules and VLM', () => {
    const r = reviewRender(applyFlaws(cleanSpec(), FLAWS, SELUNE), SELUNE, 0, 1);
    expect(r.passed).toBe(false);
    expect(r.checks.filter((c) => c.status === 'fail').map((c) => c.id)).toEqual([
      'banned_words', 'color_delta', 'logo_clearance', 'vlm_exaggeration', 'vlm_occlusion',
```

- [ ] **Step 4: 修改 `web/src/lib/review/recheck.test.ts`**

找到：

```ts
  });

  it('keeps the color result of an off-brand render', () => {
    const r = renderOf(applyFlaws(cleanSpec(), ['offPalette']));
    expect(recheckCopy(r, SELUNE, r.spec.copy).find((c) => c.id === 'color_delta')!.status).toBe('fail');
  });
});
```

改成：

```ts
  });

  it('keeps the color result of an off-brand render', () => {
    const r = renderOf(applyFlaws(cleanSpec(), ['offPalette'], SELUNE));
    expect(recheckCopy(r, SELUNE, r.spec.copy).find((c) => c.id === 'color_delta')!.status).toBe('fail');
  });
});
```

- [ ] **Step 5: 執行測試確認失敗**

Run: `npx vitest run src/lib/api/mock/flaws.test.ts src/lib/compose/scene.test.ts`
Expected: FAIL，5 個測試失敗：
- `flaws.test.ts`：「derives the flaws of other brands from their own palette and banned words」、「leaves the subhead alone when the brand has no banned words」
- `scene.test.ts`：「brand logo image」的 3 個測試（`expected undefined to be null` 等）

- [ ] **Step 6: 修改 `backend/tests/test_brands.py`**

找到：

```python
    write(tmp_path / 'my-brand.yaml', text.replace('styleImages: []', 'styleImages: [assets/mood.jpg]'))
    escape = template.replace('id: my-brand', 'id: escape').replace('logo: null', 'logo: ../x.png')
    write(tmp_path / 'escape.yaml', escape)
    loaded, errors = load_brands(tmp_path)
    assert [e.message for e in errors] == ['Logo 圖檔必須放在 brands/ 資料夾內：../x.png']
    b = loaded[0]
    assert b.brand.logo is not None
    assert b.brand.logo.url == '/files/brands/assets/logo.png'
```

改成：

```python
    write(tmp_path / 'my-brand.yaml', text.replace('styleImages: []', 'styleImages: [assets/mood.jpg]'))
    escape = template.replace('id: my-brand', 'id: escape').replace('logo: null', 'logo: ../x.png')
    write(tmp_path / 'escape.yaml', escape)
    (tmp_path / 'assets' / 'logo.gif').write_bytes(b'GIF89a')
    gif_logo = template.replace('id: my-brand', 'id: gif-logo').replace('logo: null', 'logo: assets/logo.gif')
    write(tmp_path / 'gif-logo.yaml', gif_logo)
    loaded, errors = load_brands(tmp_path)
    assert [e.message for e in errors] == [
        'Logo 圖檔必須放在 brands/ 資料夾內：../x.png',
        'Logo 圖檔只支援 PNG、JPEG、WebP 與 SVG：assets/logo.gif',
    ]
    b = loaded[0]
    assert b.brand.logo is not None
    assert b.brand.logo.url == '/files/brands/assets/logo.png'
```

- [ ] **Step 7: 修改 `backend/tests/test_parity.py`**（用 `_template.yaml` 建立的品牌跑完整的模擬流程）

找到（1／3）：

```python
比對除了 log 以外的每一則事件（內容與順序）；需要 composer（測試會自動啟動）。
"""

from datetime import UTC, datetime
from typing import Any

import pytest
```

改成：

```python
比對除了 log 以外的每一則事件（內容與順序）；需要 composer（測試會自動啟動）。
"""

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
```

找到（2／3）：

```python

from app.adapters.composer import ComposerClient
from app.brands import load_brands
from app.contract import JobAcceptedEvent, JobInput, JobStatusEvent
from app.db.session import Database
from app.events import EventStore
from app.pipeline.runner import run_job
```

改成：

```python

from app.adapters.composer import ComposerClient
from app.brands import load_brands
from app.contract import FilePhoto, JobAcceptedEvent, JobInput, JobStatusEvent, Price, ProductDraft
from app.db.session import Database
from app.events import EventStore
from app.pipeline.runner import run_job
```

找到（3／3）：

```python
    assert actual == expected
    assert snap.events[-1]['type'] == 'job.status'
    await db.truncate_all()
```

改成：

```python
    assert actual == expected
    assert snap.events[-1]['type'] == 'job.status'
    await db.truncate_all()


async def test_a_brand_made_from_the_template_also_fails_first_and_passes_after_rewriting(
    tmp_path: Path, db: Database, redis: Redis, composer_url: str
) -> None:
    """使用者自己的品牌（複製 _template.yaml）：第一輪的失誤由品牌的主色與禁用詞推算。"""
    shutil.copy(BRANDS_DIR / '_template.yaml', tmp_path / 'my-brand.yaml')
    loaded, errors = load_brands(tmp_path)
    assert errors == []
    data = load_fixture('timelines/selune-retry.json')
    job_input = JobInput.model_validate({**data['input'], 'brandId': 'my-brand', 'productId': 'prod_mine'})
    product = ProductDraft(
        id='prod_mine',
        brand_id='my-brand',
        name='晚安面膜',
        features=['玻尿酸'],
        price=Price(sale=590, original=790),
        photo=FilePhoto(source='upload', url='/files/uploads/mine.png'),
        cutout=None,
    )
    async with db.session() as s:
        await catalog.sync_brands(s, loaded, NOW)
        await catalog.save_product(s, product, NOW)
        await jobs.create_job(s, 'job_mine', job_input, NOW)
    store = EventStore(db, redis)
    await store.append('job_mine', JobAcceptedEvent(type='job.accepted', job_id='job_mine'))
    await store.append('job_mine', JobStatusEvent(type='job.status', stage='queued', round=0))
    composer = ComposerClient(composer_url)
    try:
        await run_job('job_mine', db, store, sim_ports(composer, first_round_fail=True, force_all_fail=False), speed=0)
    finally:
        await composer.aclose()
    async with db.session() as s:
        snap = await jobs.get_job(s, 'job_mine')
    assert snap is not None
    assert (snap.summary.stage, snap.summary.round) == ('done', 2)
    reasons = {r for m in snap.events if m['type'] == 'rewrite.started' for r in m['reasons']}
    assert {'color_delta', 'banned_words'} <= reasons
    await db.truncate_all()
```

- [ ] **Step 8: 執行後端測試確認失敗**

Run: `uv run pytest tests/test_brands.py tests/test_parity.py -q`
Expected: FAIL，2 個測試失敗：
- `test_logo_and_style_images_resolve_inside_the_brands_folder`：少了「Logo 圖檔只支援 PNG、JPEG、WebP 與 SVG：assets/logo.gif」。
- `test_a_brand_made_from_the_template_also_fails_first_and_passes_after_rewriting`：`assert ('failed', 1) == ('done', 2)`。

- [ ] **Step 9: 修改 `web/src/lib/api/mock/flaws.ts`**

找到（1／3）：

```ts
import type { Palette, PromptSpec } from '@/types/contract';
import { setParam } from '@/lib/agent/prompt';

export const FLAWS = ['offPalette', 'bannedCopy', 'logoCrowding', 'missingDisclaimer'] as const;
export type Flaw = (typeof FLAWS)[number];

export const FLAW_DATA: Record<string, { offPalette: Palette; bannedSubhead: string }> = {
  selune: {
    offPalette: { primary: '#E0458A', secondary: '#FFE3EF', accent: '#F49AC1', ink: '#3B1F2E' },
    bannedSubhead: '7天根治暗沉・醫療級修護',
```

改成：

```ts
import type { Brand, Palette, PromptSpec } from '@/types/contract';
import { setParam } from '@/lib/agent/prompt';
import { deltaEHex } from '@/lib/review/color';

export const FLAWS = ['offPalette', 'bannedCopy', 'logoCrowding', 'missingDisclaimer'] as const;
export type Flaw = (typeof FLAWS)[number];

interface FlawData {
  offPalette: Palette;
  /** 含禁用詞的副標；品牌沒有禁用詞時為 null（不製造這個失誤） */
  bannedSubhead: string | null;
}

export const FLAW_DATA: Record<string, FlawData> = {
  selune: {
    offPalette: { primary: '#E0458A', secondary: '#FFE3EF', accent: '#F49AC1', ink: '#3B1F2E' },
    bannedSubhead: '7天根治暗沉・醫療級修護',
```

找到（2／3）：

```ts
  },
};

/** 模擬第一輪 LLM／生圖常見的失誤，讓審查與 Query Rewriting 有東西可以修 */
export function applyFlaws(spec: PromptSpec, flaws: readonly Flaw[]): PromptSpec {
  const data = FLAW_DATA[spec.brandId];
  if (!data) throw new Error(`No flaw data for brand: ${spec.brandId}`);
  const out = structuredClone(spec);

  if (flaws.includes('offPalette')) {
```

改成：

```ts
  },
};

/** 示範品牌用固定的失誤；其他品牌（使用者自己的設定檔）由品牌的主色與禁用詞推算 */
export function flawData(brand: Pick<Brand, 'id' | 'palette' | 'bannedWords'>): FlawData {
  const known = FLAW_DATA[brand.id];
  if (known) return known;
  // 兩組示範偏色中，與品牌主色差最多的一組，確保主色色差檢查會未通過
  const [a, b] = [FLAW_DATA.selune.offPalette, FLAW_DATA['misty-isle'].offPalette];
  const primary = brand.palette.primary;
  const offPalette = deltaEHex(a.primary, primary) >= deltaEHex(b.primary, primary) ? a : b;
  return { offPalette, bannedSubhead: brand.bannedWords.length ? brand.bannedWords.slice(0, 2).join('・') : null };
}

/** 模擬第一輪 LLM／生圖常見的失誤，讓審查與 Query Rewriting 有東西可以修 */
export function applyFlaws(spec: PromptSpec, flaws: readonly Flaw[], brand: Pick<Brand, 'id' | 'palette' | 'bannedWords'>): PromptSpec {
  const data = flawData(brand);
  const out = structuredClone(spec);

  if (flaws.includes('offPalette')) {
```

找到（3／3）：

```ts
    out.positivePrompt = `${out.positivePrompt}, vivid saturated colors`;
    out.injection = setParam(out.injection, 'positive_prompt', out.positivePrompt);
  }
  if (flaws.includes('bannedCopy')) {
    out.copy.subhead = data.bannedSubhead;
  }
  if (flaws.includes('logoCrowding')) {
```

改成：

```ts
    out.positivePrompt = `${out.positivePrompt}, vivid saturated colors`;
    out.injection = setParam(out.injection, 'positive_prompt', out.positivePrompt);
  }
  if (flaws.includes('bannedCopy') && data.bannedSubhead) {
    out.copy.subhead = data.bannedSubhead;
  }
  if (flaws.includes('logoCrowding')) {
```

- [ ] **Step 10: 修改 `web/src/lib/api/mock/scenario.ts`**

找到：

```ts
        jobId, round, brand, product, brief: input.parsedBrief, template, engine: input.engine,
        seed: 100_000_000 + Math.floor(rng() * 900_000_000), ragRefs, fixes: fixesForNext,
      });
      return flawed ? applyFlaws(spec, FLAWS) : spec;
    });
    specs.forEach((spec, i) =>
      emit(t + ((i + 1) * PHASE_MS.prompt) / specs.length, { type: 'prompt.generated', round, templateId: spec.templateId, spec }),
```

改成：

```ts
        jobId, round, brand, product, brief: input.parsedBrief, template, engine: input.engine,
        seed: 100_000_000 + Math.floor(rng() * 900_000_000), ragRefs, fixes: fixesForNext,
      });
      return flawed ? applyFlaws(spec, FLAWS, brand) : spec;
    });
    specs.forEach((spec, i) =>
      emit(t + ((i + 1) * PHASE_MS.prompt) / specs.length, { type: 'prompt.generated', round, templateId: spec.templateId, spec }),
```

- [ ] **Step 11: 修改 `web/composer/handlers.ts`**

找到：

```ts
    engine: Engine; seed: number; ragRefs: string[]; fixes: CheckId[]; flawed: boolean;
  }) => {
    const spec = buildPromptSpec({ ...b, template: getTemplate(b.templateId) });
    return b.flawed ? applyFlaws(spec, FLAWS) : spec;
  },

  '/sim/review': ({ spec, brand, variant, seed }: { spec: PromptSpec; brand: Brand; variant: number; seed: number }) => {
```

改成：

```ts
    engine: Engine; seed: number; ragRefs: string[]; fixes: CheckId[]; flawed: boolean;
  }) => {
    const spec = buildPromptSpec({ ...b, template: getTemplate(b.templateId) });
    return b.flawed ? applyFlaws(spec, FLAWS, b.brand) : spec;
  },

  '/sim/review': ({ spec, brand, variant, seed }: { spec: PromptSpec; brand: Brand; variant: number; seed: number }) => {
```

- [ ] **Step 12: 修改 `web/src/lib/compose/scene.ts`**

找到（1／4）：

```ts
  shadow: string;
  texts: TextOp[];
}
export interface LogoOp { kind: 'logo'; rect: Rect; mark: LogoMark; color: string; wordmark: TextOp | null }
export interface ProductOp { kind: 'product'; rect: Rect; shadow: string }
export type SceneOp = { kind: 'background' } | ProductOp | LogoOp | TextOp | PillOp | BadgeOp;
```

改成：

```ts
  shadow: string;
  texts: TextOp[];
}
/** image：品牌的 Logo 圖檔；有圖時畫圖檔，沒有或載入失敗時畫標誌圖形與字標 */
export interface LogoOp { kind: 'logo'; rect: Rect; mark: LogoMark; color: string; wordmark: TextOp | null; image: string | null }
export interface ProductOp { kind: 'product'; rect: Rect; shadow: string }
export type SceneOp = { kind: 'background' } | ProductOp | LogoOp | TextOp | PillOp | BadgeOp;
```

找到（2／4）：

```ts
  layout: LayoutBox[];
  palette: Palette;
  copy: Copy;
  brand: { id: string; name: string };
}

const MARKS: Record<string, LogoMark> = { selune: 'crescent', 'misty-isle': 'isle' };
```

改成：

```ts
  layout: LayoutBox[];
  palette: Palette;
  copy: Copy;
  brand: { id: string; name: string; logo?: { url: string } | null };
}

const MARKS: Record<string, LogoMark> = { selune: 'crescent', 'misty-isle': 'isle' };
```

找到（3／4）：

```ts
export function logoFor(brand: { id: string; name: string }): { mark: LogoMark; wordmark: string } {
  const latin = brand.name.match(/[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ&.' -]*[A-Za-zÀ-ÿ]/)?.[0];
  return { mark: MARKS[brand.id] ?? 'monogram', wordmark: latin ?? brand.name };
}

export const formatPrice = (n: number): string => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
```

改成：

```ts
export function logoFor(brand: { id: string; name: string }): { mark: LogoMark; wordmark: string } {
  const latin = brand.name.match(/[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ&.' -]*[A-Za-zÀ-ÿ]/)?.[0];
  return { mark: MARKS[brand.id] ?? 'monogram', wordmark: latin ?? brand.name };
}

/** Logo 圖檔放進 Logo 框：等比例縮放、靠左、垂直置中 */
export function fitLogoImage(box: Rect, width: number, height: number): Rect {
  const scale = Math.min(box.w / width, box.h / height);
  const w = width * scale;
  const h = height * scale;
  return { x: box.x, y: box.y + (box.h - h) / 2, w, h };
}

export const formatPrice = (n: number): string => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
```

找到（4／4）：

```ts
  const wordChars = [...logo.wordmark].length;
  const wordSize = Math.min(L.h * 0.62, wordW / (visLen(logo.wordmark) + 0.08 * Math.max(0, wordChars - 1)));
  ops.push({
    kind: 'logo', rect: L, mark: logo.mark, color: P.accent,
    wordmark: wordW > 0
      ? text({ el: 'logo', text: logo.wordmark, x: L.x + L.h * 1.12, y: L.y + L.h / 2, size: wordSize, weight: 700, role: 'headline', color: P.ink, letterSpacing: wordSize * 0.08 })
      : null,
```

改成：

```ts
  const wordChars = [...logo.wordmark].length;
  const wordSize = Math.min(L.h * 0.62, wordW / (visLen(logo.wordmark) + 0.08 * Math.max(0, wordChars - 1)));
  ops.push({
    kind: 'logo', rect: L, mark: logo.mark, color: P.accent, image: brand.logo?.url ?? null,
    wordmark: wordW > 0
      ? text({ el: 'logo', text: logo.wordmark, x: L.x + L.h * 1.12, y: L.y + L.h / 2, size: wordSize, weight: 700, role: 'headline', color: P.ink, letterSpacing: wordSize * 0.08 })
      : null,
```

- [ ] **Step 13: 修改 `web/src/lib/compose/paint.ts`**

找到（1／3）：

```ts
import type { Rect } from '@/lib/core/geometry';
import type { BadgeOp, LogoOp, PillOp, PosterScene, ProductOp, TextOp } from './scene';
import { textBounds } from './scene';

/** 繪製海報需要的圖片與字型（由 render.ts 準備） */
export interface PaintAssets {
  background: CanvasImageSource;
  /** blend = multiply：沒有真正去背的商品照，用色彩增值讓白底融入背景 */
  product: { image: CanvasImageSource; width: number; height: number; blend: 'normal' | 'multiply' } | null;
  /** CSS font-family 字串 */
  fonts: { headline: string; body: string };
}
```

改成：

```ts
import type { Rect } from '@/lib/core/geometry';
import type { BadgeOp, LogoOp, PillOp, PosterScene, ProductOp, TextOp } from './scene';
import { fitLogoImage, textBounds } from './scene';

/** 繪製海報需要的圖片與字型（由 render.ts 準備） */
export interface PaintAssets {
  background: CanvasImageSource;
  /** blend = multiply：沒有真正去背的商品照，用色彩增值讓白底融入背景 */
  product: { image: CanvasImageSource; width: number; height: number; blend: 'normal' | 'multiply' } | null;
  /** 品牌的 Logo 圖檔（品牌沒有 Logo 圖檔或載入失敗時為 null） */
  logo: { image: CanvasImageSource; width: number; height: number } | null;
  /** CSS font-family 字串 */
  fonts: { headline: string; body: string };
}
```

找到（2／3）：

```ts
  ctx.restore();
}

function drawLogo(ctx: Ctx, op: LogoOp, fonts: PaintAssets['fonts']) {
  const { x, y, h: s } = op.rect;
  ctx.save();
  ctx.fillStyle = op.color;
```

改成：

```ts
  ctx.restore();
}

function drawLogo(ctx: Ctx, op: LogoOp, assets: PaintAssets) {
  if (op.image && assets.logo) {
    const r = fitLogoImage(op.rect, assets.logo.width, assets.logo.height);
    ctx.drawImage(assets.logo.image, r.x, r.y, r.w, r.h);
    return;
  }
  const fonts = assets.fonts;
  const { x, y, h: s } = op.rect;
  ctx.save();
  ctx.fillStyle = op.color;
```

找到（3／3）：

```ts
        drawProduct(ctx, op, assets.product);
        break;
      case 'logo':
        drawLogo(ctx, op, assets.fonts);
        break;
      case 'text':
        drawText(ctx, op, assets.fonts);
```

改成：

```ts
        drawProduct(ctx, op, assets.product);
        break;
      case 'logo':
        drawLogo(ctx, op, assets);
        break;
      case 'text':
        drawText(ctx, op, assets.fonts);
```

- [ ] **Step 14: 修改 `web/src/lib/compose/render.ts`**

找到（1／2）：

```ts
    : bg.url;
  const prod = product ? productImage(product, brand) : null;
  const fonts = fontStacks(brand);
  const [background, productImg] = await Promise.all([
    loadImage(bgSrc),
    prod ? loadImage(prod.src).catch(() => null) : Promise.resolve(null),
    ensureFonts(scene, fonts),
  ]);
  return {
```

改成：

```ts
    : bg.url;
  const prod = product ? productImage(product, brand) : null;
  const fonts = fontStacks(brand);
  const [background, productImg, logoImg] = await Promise.all([
    loadImage(bgSrc),
    prod ? loadImage(prod.src).catch(() => null) : Promise.resolve(null),
    // Logo 圖檔載入失敗時改畫標誌圖形與字標
    brand.logo ? loadImage(brand.logo.url).catch(() => null) : Promise.resolve(null),
    ensureFonts(scene, fonts),
  ]);
  return {
```

找到（2／2）：

```ts
      product: productImg && prod
        ? { image: productImg, width: productImg.naturalWidth || 500, height: productImg.naturalHeight || 800, blend: prod.blend }
        : null,
      fonts,
    },
  };
```

改成：

```ts
      product: productImg && prod
        ? { image: productImg, width: productImg.naturalWidth || 500, height: productImg.naturalHeight || 800, blend: prod.blend }
        : null,
      // 沒有固有尺寸的 SVG 以 3:1 計算
      logo: logoImg ? { image: logoImg, width: logoImg.naturalWidth || 300, height: logoImg.naturalHeight || 100 } : null,
      fonts,
    },
  };
```

- [ ] **Step 15: 修改 `backend/app/brands.py`**

找到（1／2）：

```python
)

TONES: tuple[Tone, ...] = ('gentle', 'science', 'playful', 'minimal')


class GuidelineConfig(Model):
```

改成：

```python
)

TONES: tuple[Tone, ...] = ('gentle', 'science', 'playful', 'minimal')
#: Logo 圖檔支援的格式（與 app/api/files.py 提供的圖片格式相同）
LOGO_TYPES = frozenset({'.png', '.jpg', '.jpeg', '.webp', '.svg'})


class GuidelineConfig(Model):
```

找到（2／2）：

```python
        raise BrandFileError(f'檔名必須與 id 相同（id 為 {cfg.id}）')

    logo_path = _inside(directory, cfg.logo, 'Logo 圖檔') if cfg.logo else None
    style_images = [_inside(directory, p, '參考圖') for p in cfg.style_images]
    alt = _alt_guideline(cfg, path.name)
    guidelines = [*cfg.guidelines, *([alt] if alt else [])]
```

改成：

```python
        raise BrandFileError(f'檔名必須與 id 相同（id 為 {cfg.id}）')

    logo_path = _inside(directory, cfg.logo, 'Logo 圖檔') if cfg.logo else None
    if logo_path is not None and logo_path.suffix.lower() not in LOGO_TYPES:
        raise BrandFileError(f'Logo 圖檔只支援 PNG、JPEG、WebP 與 SVG：{cfg.logo}')
    style_images = [_inside(directory, p, '參考圖') for p in cfg.style_images]
    alt = _alt_guideline(cfg, path.name)
    guidelines = [*cfg.guidelines, *([alt] if alt else [])]
```

- [ ] **Step 16: 修改 `brands/_template.yaml`**（說明支援的 Logo 格式）

找到：

```yaml
# 歷史優秀案例（ctr 為百分比，例如 3.5）
caseStudies: []

# Logo 圖檔（相對於 brands/，例如 assets/my-brand-logo.png）；沒有時填 null
logo: null

# IP-Adapter 參考圖（相對於 brands/），生圖時參考的品牌風格
```

改成：

```yaml
# 歷史優秀案例（ctr 為百分比，例如 3.5）
caseStudies: []

# Logo 圖檔（相對於 brands/，例如 assets/my-brand-logo.png）；支援 PNG、JPEG、WebP、SVG，沒有時填 null。
# 海報上等比例縮放放進 Logo 框（靠左），所以建議用去背的橫式 Logo
logo: null

# IP-Adapter 參考圖（相對於 brands/），生圖時參考的品牌風格
```

- [ ] **Step 17: 執行測試確認通過**

Run: `npm run test && npm run typecheck && npm run lint`（在 `web/`）
Expected: 41 個測試檔、314 個測試全部通過（`golden.test.ts` 仍通過：示範品牌的劇本不變）；沒有錯誤。

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy`（在 `backend/`）
Expected: 63 passed；沒有錯誤。

- [ ] **Step 18: 在瀏覽器確認自己的品牌**

1. 建立一個測試品牌：
   - 複製 `brands/_template.yaml` 成 `brands/logo-test.yaml`，把 `id` 改成 `logo-test`、`logo` 改成 `assets/logo-test.svg`。
   - 在 `brands/assets/logo-test.svg` 放一個橫式 SVG。
2. 以 live 模式啟動（Task 13 Step 15），在右上角切換到這個品牌：
   - 商品庫上傳一張商品照。
   - 新任務輸入一句話需求並開始生成。
3. 確認：
   - 第一輪未通過、Query Rewriting 後完成。
   - 每張海報左上角畫出 SVG Logo（等比例、靠左）。
4. 確認後刪除 `brands/logo-test.yaml` 與 `brands/assets/`。

- [ ] **Step 19: Commit**

```bash
git add \
  backend/app/brands.py \
  backend/tests/test_brands.py \
  backend/tests/test_parity.py \
  brands/_template.yaml \
  web/composer/handlers.ts \
  web/src/lib/api/mock/flaws.test.ts \
  web/src/lib/api/mock/flaws.ts \
  web/src/lib/api/mock/review.test.ts \
  web/src/lib/api/mock/scenario.ts \
  web/src/lib/compose/paint.ts \
  web/src/lib/compose/render.ts \
  web/src/lib/compose/scene.test.ts \
  web/src/lib/compose/scene.ts \
  web/src/lib/review/recheck.test.ts
git commit -m "feat: draw brand logo images and let custom brands run the simulated flow" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Docker：整套服務與 nginx


**Files:**
- Create: `backend/Dockerfile`、`backend/.dockerignore`、`web/Dockerfile`、`web/.dockerignore`、`web/nginx.conf`、`.env.example`、`.gitattributes`
- Modify: `docker-compose.yml`、`web/.env.example`、`backend/app/api/catalog.py`

**Interfaces:**
- Consumes：Task 12 的 api 與 worker、Task 8 的 composer、Task 2 的靜態輸出
- Produces：
  - `docker compose up -d --build`：postgres、redis、composer、api（`127.0.0.1:8000`）、worker、web（`127.0.0.1:3000`）。
    - 啟動順序：web、worker 等 api 健康；api 等 postgres、redis、composer 健康。
    - `restart: unless-stopped`。
  - 映像檔：
    - api 與 worker 共用 `backend/Dockerfile`。
    - web 與 composer 是 `web/Dockerfile` 的兩個 target：
      - web：以 `NEXT_PUBLIC_API_MODE=live` 建置後由 nginx 提供。
      - composer：`HOST=0.0.0.0`。
  - 掛載：
    - `./brands`、`./assets/products`：唯讀。
    - `./data`：上傳的商品照。
    - 容器內的路徑以環境變數固定，不受 `.env` 影響。
  - nginx：
    - `/api/`、`/files/`、`/ws/`（WebSocket，保持 1 小時）、`/docs`、`/openapi.json` 轉給 api；每次請求才解析 api 的位址。
    - 上傳上限 25 MB；`/_next/static/` 長期快取。
  - 文件上傳的 NDJSON 回應加上 `X-Accel-Buffering: no`：nginx 預設會緩衝回應，關掉才能一行一行送到前端。
  - `.env.example`：模擬速度、首輪失誤、全部失誤、時區
  - `.gitattributes`：`*.sh`、`Dockerfile`、`*.conf` 一律 LF（Windows 的 autocrlf 會改成 CRLF）

- [ ] **Step 1: 建立 `.gitattributes`**

```text
# 會放進 Linux 容器的檔案一律使用 LF（Windows 的 core.autocrlf 取出時會改成 CRLF，shell script 會因此無法執行）
*.sh text eol=lf
Dockerfile text eol=lf
*.conf text eol=lf
```

- [ ] **Step 2: 建立 `backend/Dockerfile`**

```dockerfile
# api 與 worker 共用的映像檔（compose 以不同的指令啟動）
FROM public.ecr.aws/docker/library/python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv

# 先編譯位元組碼；使用映像檔內的 Python 3.13，不讓 uv 另外下載
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

# 程式在 /app/backend，設定推算的 repo 根目錄為 /app（brands/、data/、assets/products/ 由 compose 掛載）
WORKDIR /app/backend
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
ENV PATH="/app/backend/.venv/bin:$PATH"

EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: 建立 `backend/.dockerignore`**

```text
.venv
**/__pycache__
.mypy_cache
.ruff_cache
.pytest_cache
tests
```

- [ ] **Step 4: 建立 `web/Dockerfile`**

```dockerfile
# 兩個映像檔：
# - web：nginx 提供 live 版的靜態輸出，並把 /api、/files、/ws、/docs 轉給 api
# - composer：Node 服務，直接執行 src/lib 的 TypeScript（版型與模擬邏輯）
FROM public.ecr.aws/docker/library/node:24-alpine AS source
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app/web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .

FROM source AS build
RUN NEXT_PUBLIC_API_MODE=live npm run build

FROM public.ecr.aws/docker/library/nginx:1.29-alpine AS web
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/web/out /usr/share/nginx/html

FROM source AS composer
ENV HOST=0.0.0.0 PORT=3900
EXPOSE 3900
CMD ["node", "--import", "tsx", "composer/server.ts"]
```

- [ ] **Step 5: 建立 `web/.dockerignore`**

```text
node_modules
.next
out
coverage
test-results
playwright-report
*.tsbuildinfo
.env
.env.*
```

- [ ] **Step 6: 建立 `web/nginx.conf`**

```nginx
# live 版：提供 next build 的靜態輸出（out/），/api、/files、/ws、/docs 轉給 FastAPI
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;

    # 每次請求才解析 api 的位址：api 容器重建後 IP 改變也不必重啟 nginx
    resolver 127.0.0.11 valid=10s ipv6=off;
    set $api http://api:8000;

    # 商品照上傳（api 限制 20 MB）
    client_max_body_size 25m;

    location /api/ {
        proxy_pass $api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /files/ {
        proxy_pass $api;
        proxy_http_version 1.1;
    }

    # 任務事件：生圖時事件可能隔比較久，連線最長保持 1 小時（前端斷線後也會自動重新連線）
    location /ws/ {
        proxy_pass $api;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 1h;
        proxy_send_timeout 1h;
    }

    # FastAPI 自動產生的 API 文件
    location = /docs {
        proxy_pass $api;
    }

    location = /openapi.json {
        proxy_pass $api;
    }

    # 建置檔名含雜湊，可以長期快取
    location /_next/static/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # /studio → studio.html
    location / {
        try_files $uri $uri.html $uri/ =404;
    }

    error_page 404 /404.html;
}
```

- [ ] **Step 7: 修改 `backend/app/api/catalog.py`**（NDJSON 不經 nginx 緩衝）

找到：

```python
        if await catalog.get_brand(s, brand_id) is None:
            raise NotFound(f'找不到品牌：{brand_id}')
    lines = _ingest_lines(services, secrets.token_hex(8), brand_id, doc)
    return StreamingResponse(lines, media_type='application/x-ndjson')


@router.get('/api/templates')
```

改成：

```python
        if await catalog.get_brand(s, brand_id) is None:
            raise NotFound(f'找不到品牌：{brand_id}')
    lines = _ingest_lines(services, secrets.token_hex(8), brand_id, doc)
    # nginx 預設會先緩衝回應；關掉才能一行一行送到前端
    return StreamingResponse(lines, media_type='application/x-ndjson', headers={'X-Accel-Buffering': 'no'})


@router.get('/api/templates')
```

- [ ] **Step 8: 改寫 `docker-compose.yml`（完整內容）**

```yaml
# 虛實整合 GenAI Agent：本機執行（所有連接埠只綁定 127.0.0.1）。ComfyUI 在 Windows 另外啟動。
# 映像檔取自 AWS 的 Docker 官方映像鏡像（public.ecr.aws/docker/library），不需要登入 Docker Hub。
#
#   docker compose up -d --build     整套服務：瀏覽器開 http://127.0.0.1:3000
#   docker compose up -d postgres redis   只開資料庫與佇列（在本機用 uv、npm 開發與測試）
name: genai-agent

# api 與 worker 共用：同一個映像檔，設定來自 .env（可省略）；容器之間的位址與容器內的路徑固定在這裡
x-backend: &backend
  build: ./backend
  env_file:
    - path: .env
      required: false
  environment:
    DATABASE_URL: postgresql+asyncpg://genai:genai@postgres:5432/genai
    REDIS_URL: redis://redis:6379/0
    COMPOSER_URL: http://composer:3900
    BRANDS_DIR: /app/brands
    DATA_DIR: /app/data
    LOCAL_PHOTOS_DIR: /app/assets/products
  volumes:
    - ./brands:/app/brands:ro
    - ./assets/products:/app/assets/products:ro
    - ./data:/app/data
  restart: unless-stopped

services:
  postgres:
    image: public.ecr.aws/docker/library/postgres:18-alpine
    environment:
      POSTGRES_USER: genai
      POSTGRES_PASSWORD: genai
      POSTGRES_DB: genai
    # 5433：避免和 Windows 上原生安裝的 PostgreSQL（5432）衝突；容器之間仍用 postgres:5432
    ports: ['127.0.0.1:5433:5432']
    volumes: ['postgres:/var/lib/postgresql']
    healthcheck:
      test: ['CMD-SHELL', 'pg_isready -U genai -d genai']
      interval: 3s
      timeout: 3s
      retries: 30
    restart: unless-stopped

  redis:
    image: public.ecr.aws/docker/library/redis:8-alpine
    command: ['redis-server', '--appendonly', 'yes']
    ports: ['127.0.0.1:6379:6379']
    volumes: ['redis:/data']
    healthcheck:
      test: ['CMD', 'redis-cli', 'ping']
      interval: 3s
      timeout: 3s
      retries: 30
    restart: unless-stopped

  # 版型與模擬邏輯（直接執行 web/src/lib 的 TypeScript）；只給 api 與 worker 使用，不對外開放
  composer:
    build:
      context: ./web
      target: composer
    healthcheck:
      test: ['CMD', 'node', '-e', "fetch('http://127.0.0.1:3900/health').then((r) => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]
      interval: 3s
      timeout: 3s
      retries: 30
    restart: unless-stopped

  # REST、WebSocket 與檔案；啟動時執行 migration 並匯入品牌設定檔
  api:
    <<: *backend
    command: ['uvicorn', 'app.api.main:app', '--host', '0.0.0.0', '--port', '8000']
    # 8000：API 文件（/docs），以及 next dev 以 API_PROXY_URL 連線
    ports: ['127.0.0.1:8000:8000']
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
      composer: { condition: service_healthy }
    healthcheck:
      test: ['CMD', 'python', '-c', "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"]
      interval: 3s
      timeout: 3s
      retries: 30

  # 生圖任務、文件上傳、去背與回寫；等 api 完成 migration 後才啟動
  worker:
    <<: *backend
    command: ['python', '-m', 'app.worker']
    depends_on:
      api: { condition: service_healthy }

  # live 版前端：nginx 提供靜態輸出，/api、/files、/ws、/docs 轉給 api
  web:
    build:
      context: ./web
      target: web
    ports: ['127.0.0.1:3000:80']
    depends_on:
      api: { condition: service_healthy }
    restart: unless-stopped

volumes:
  postgres:
  redis:
```

- [ ] **Step 9: 建立 `.env.example`**

```text
# 複製成 .env 後依需要修改（.env 不會上傳 GitHub）。
# docker compose 的 api、worker，以及在本機執行的後端（uv run）都會讀取。

# 模擬模式的播放速度：1 為 1× 時間軸（約 15 秒一個任務），0 為不等待
SIM_SPEED=1
# 模擬模式：第一輪刻意失誤，展示合規審查與 Query Rewriting
SIM_FIRST_ROUND_FAIL=true
# 模擬模式：每一輪都失誤，展示「需人工審核」
SIM_FORCE_ALL_FAIL=false
# 任務 id 使用的時區
TIMEZONE=Asia/Taipei

# 之後的計畫會加入：
# GEMINI_API_KEY=                                  Plan 6：Gemini（LLM 與 VLM）
# COMFYUI_URL=http://host.docker.internal:8188     Plan 7：ComfyUI 生圖
```

- [ ] **Step 10: 修改 `web/.env.example`**

找到：

```text
# mock：前端模擬資料（第一階段）；live：連線 FastAPI（第二階段）
NEXT_PUBLIC_API_MODE=mock
```

改成：

```text
# mock：瀏覽器內模擬（預設，作品集 Demo 使用）；live：連線 FastAPI 後端
NEXT_PUBLIC_API_MODE=mock
# live 模式以 next dev 開發時，把 /api、/files、/ws 轉給後端（docker compose 的 api，或 uv run uvicorn）
# API_PROXY_URL=http://127.0.0.1:8000
```

- [ ] **Step 11: 建置並啟動整套服務**

```bash
docker compose up -d --build --wait
```

Expected：
- 6 個服務都 `Healthy`。
- 第一次建置需要數分鐘：npm ci、Next 建置、uv sync。
- 映像檔大小約為 web 117 MB、api 與 worker 各 493 MB、composer 1.5 GB（含完整的 node_modules）。

- [ ] **Step 12: 經 nginx 確認**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/studio
curl -s http://127.0.0.1:3000/api/status
curl -sN -X POST -H "content-type: application/json" -d '{"name":"check.md","text":"# 色彩\n主色 #2F4A44。\n\n# Logo\n反白 Logo"}' http://127.0.0.1:3000/api/brands/selune/documents
```

Expected：
- `/studio` 回 `200`。
- 系統狀態中 db、redis、worker、composer、brands 為 `ok`。
- 文件上傳逐行輸出 `ingest.chunked`、`ingest.embedded` ×2、`ingest.stored`，每行之間有約 0.25 秒的間隔（沒有被緩衝）。

再用瀏覽器開啟 http://127.0.0.1:3000/studio 跑一個任務，以及 http://127.0.0.1:3000/docs。

- [ ] **Step 13: 測試仍然通過**

Run: `uv run pytest -q`（在 `backend/`；整套服務執行中也可以跑，測試使用自己的資料庫與 Redis 第 15 號資料庫）
Expected: 63 passed。

- [ ] **Step 14: Commit**

```bash
git add \
  .env.example \
  .gitattributes \
  backend/.dockerignore \
  backend/Dockerfile \
  backend/app/api/catalog.py \
  docker-compose.yml \
  web/.dockerignore \
  web/.env.example \
  web/Dockerfile \
  web/nginx.conf
git commit -m "build: run the whole stack with Docker Compose behind an nginx proxy" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 16: live 模式 E2E（獨立的 compose 專案）


**Files:**
- Create: `docker-compose.e2e.yml`、`web/playwright.live.config.ts`、`web/e2e-live/stack.ts`、`web/e2e-live/global-setup.ts`、`web/e2e-live/global-teardown.ts`、`web/e2e-live/live.spec.ts`
- Modify: `web/package.json`、`web/.dockerignore`

**Interfaces:**
- Consumes：Task 15 的 Docker 設定
- Produces：
  - `docker compose -p genai-agent-e2e -f docker-compose.yml -f docker-compose.e2e.yml`：
    - 使用自己的 volume 與 `data/`。
    - 只開放 web（`127.0.0.1:3200`）。
    - 模擬設定固定為 1× 速度、首輪失誤。
  - `npm run e2e:live`：
    - 建置並啟動上述專案，測完以 `down -v` 移除（映像檔保留）。
    - 後端一次只執行一個生圖任務，所以測試依序執行。
  - 測試項目：
    - 主流程（第一輪失敗、重試後通過、匯出並寫入歷史、Agent 透視與儀表板）。
    - 重新整理後接續。
    - API 重新啟動後自動重新連線。
    - 取消。
    - 品牌文件上傳、商品照上傳。

- [ ] **Step 1: 建立 `docker-compose.e2e.yml`**

compose 的 `!override` 會整個取代清單，`!reset` 則清空清單（Docker Compose 2.24 以上）。

```yaml
# live 模式 E2E 專用（web 的 npm run e2e:live 會自動啟動與移除）：
#   docker compose -p genai-agent-e2e -f docker-compose.yml -f docker-compose.e2e.yml up -d --build --wait
# 獨立的專案名稱與 volume，不影響平常使用的資料庫、上傳檔與商品照；只開放 web（127.0.0.1:3200）。
x-e2e-backend: &e2e-backend
  environment:
    SIM_SPEED: '1'
    SIM_FIRST_ROUND_FAIL: 'true'
    SIM_FORCE_ALL_FAIL: 'false'
  volumes: !override
    - ./brands:/app/brands:ro
    - e2e-photos:/app/assets/products:ro
    - e2e-data:/app/data

services:
  postgres:
    ports: !reset []
  redis:
    ports: !reset []
  api:
    <<: *e2e-backend
    ports: !reset []
  worker:
    <<: *e2e-backend
  web:
    ports: !override ['127.0.0.1:3200:80']

volumes:
  e2e-data:
  e2e-photos:
```

確認合併後的設定：`docker compose -p genai-agent-e2e -f docker-compose.yml -f docker-compose.e2e.yml config`。只有 web 有 `ports`（3200）；api 與 worker 的 volumes 為 `brands`（唯讀）、`e2e-photos`、`e2e-data`。

- [ ] **Step 2: 建立 `web/e2e-live/stack.ts`**

```ts
import { execFileSync } from 'node:child_process';
import path from 'node:path';

/** live 模式 E2E 使用的獨立 docker compose 專案（見 repo 根目錄的 docker-compose.e2e.yml） */
export const E2E_URL = 'http://127.0.0.1:3200';
const REPO_ROOT = path.resolve(__dirname, '..', '..');

export function compose(...args: string[]): void {
  execFileSync(
    'docker',
    ['compose', '-p', 'genai-agent-e2e', '-f', 'docker-compose.yml', '-f', 'docker-compose.e2e.yml', ...args],
    { cwd: REPO_ROOT, stdio: 'inherit' },
  );
}
```

- [ ] **Step 3: 建立 `web/e2e-live/global-setup.ts`**

```ts
import { compose } from './stack';

/** 建置並啟動整套服務（外部服務用模擬版），等到所有健康檢查通過 */
export default function globalSetup(): void {
  compose('up', '-d', '--build', '--wait');
}
```

- [ ] **Step 4: 建立 `web/e2e-live/global-teardown.ts`**

```ts
import { compose } from './stack';

/** 移除 E2E 的容器與資料（映像檔保留，下次建置較快） */
export default function globalTeardown(): void {
  compose('down', '-v');
}
```

- [ ] **Step 5: 建立 `web/playwright.live.config.ts`**

```ts
import { defineConfig, devices } from '@playwright/test';
import { E2E_URL } from './e2e-live/stack';

/**
 * live 模式 E2E：以 docker compose 啟動獨立的整套服務（外部服務用模擬版，1× 速度約 16 秒一個任務），測完移除。
 * 後端一次只執行一個生圖任務，所以測試依序執行。需要 Docker；npm run e2e:live
 */
export default defineConfig({
  testDir: './e2e-live',
  timeout: 120_000,
  expect: { timeout: 45_000 },
  workers: 1,
  forbidOnly: !!process.env.CI,
  reporter: [['list']],
  globalSetup: './e2e-live/global-setup.ts',
  globalTeardown: './e2e-live/global-teardown.ts',
  use: {
    baseURL: E2E_URL,
    locale: 'zh-TW',
    timezoneId: 'Asia/Taipei',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
```

- [ ] **Step 6: 建立 `web/e2e-live/live.spec.ts`**

「API 重新啟動」的測試在任務執行中重新啟動 api 容器。worker 繼續執行任務；前端斷線後以最後的 `seq` 重新連線，中斷期間的事件由資料庫補送。

```ts
import { expect, test, type Page } from '@playwright/test';
import { compose } from './stack';

// 對 docker compose 啟動的整套服務測試：任務由 worker 執行，事件經 nginx 的 WebSocket 送到前端

/** 只留 IG 貼文（1 個模板 × 2 張）開始生成；回傳任務 id */
async function startJob(page: Page): Promise<string> {
  await page.goto('/studio');
  await page.getByRole('checkbox', { name: '電商主圖' }).click();
  await expect(page.getByRole('checkbox', { name: 'IG 貼文' })).toBeChecked();
  await page.getByRole('button', { name: '開始生成（1 個模板 × 2 張）' }).click();
  const id = page.getByText(/^job_\d{8}_\d{4}_[0-9a-f]{4}$/);
  await expect(id).toBeVisible();
  return (await id.textContent())!;
}

async function job(page: Page, jobId: string) {
  return (await page.request.get(`/api/jobs/${jobId}`)).json();
}

const roundOne = (page: Page) => page.getByText('第 1 輪', { exact: true }).first();
const editor = (page: Page) => page.getByText('文字編輯器', { exact: true });

test('一句話需求 → 後端生成（第一輪失敗、重試後通過）→ 匯出並寫入歷史 → Agent 透視與儀表板', async ({ page }) => {
  const jobId = await startJob(page);
  await expect(page.getByText('第 1 輪未通過審查，Query Rewriting 後重試')).toBeVisible();
  await expect(editor(page)).toBeVisible();

  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: '匯出 zip 並寫入歷史（1 張）' }).click();
  await downloading;
  await expect(page.getByText('已匯出 1 張海報')).toBeVisible();
  const history = await (await page.request.get('/api/history?brandId=selune')).json();
  expect(history[0]).toMatchObject({ jobId, templateId: 'ig-post', writtenToRag: true });
  await page.goto('/history');
  await expect(page.getByText('已回寫 RAG').first()).toBeVisible();

  const { events } = await job(page, jobId);
  await page.goto(`/agent?job=${jobId}`);
  await expect(page.getByText(`${events.length} 則事件`)).toBeVisible();
  await page.goto('/dashboard');
  await expect(page.getByText(jobId)).toBeVisible();
});

test('重新整理後接續執行中的任務', async ({ page }) => {
  const jobId = await startJob(page);
  await expect(roundOne(page)).toBeVisible();
  expect((await job(page, jobId)).summary.finished).toBe(false);
  await page.reload();
  await expect(page.getByText(jobId)).toBeVisible();
  await expect(editor(page)).toBeVisible();
  await expect(page.getByRole('button', { name: '匯出 zip 並寫入歷史（1 張）' })).toBeEnabled();
});

test('API 重新啟動時自動重新連線，補上中斷期間的事件', async ({ page }) => {
  const jobId = await startJob(page);
  await expect(roundOne(page)).toBeVisible();
  // 任務在 worker 繼續執行；api 重新啟動期間的事件由重新連線時從資料庫補送
  compose('restart', 'api');
  await expect(editor(page)).toBeVisible();
  expect((await job(page, jobId)).summary).toMatchObject({ stage: 'done', finished: true });
  await expect(page.getByRole('button', { name: '系統狀態' })).toContainText('WebSocket 已連線');
});

test('取消執行中的任務', async ({ page }) => {
  const jobId = await startJob(page);
  await expect(roundOne(page)).toBeVisible();
  await page.getByRole('button', { name: '取消任務' }).click();
  await expect(page.getByText('任務已取消。')).toBeVisible();
  expect((await job(page, jobId)).summary).toMatchObject({ stage: 'cancelled', finished: true });
});

test('上傳品牌文件：切塊 → 向量化 → 寫入，知識庫列出新的切塊', async ({ page }) => {
  await page.goto('/brands');
  await page.locator('input[type="file"]').setInputFiles({
    name: 'e2e_ci.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from('# 色彩更新\n主色維持 #2F4A44。\n\n# Logo\n- 深色背景使用反白 Logo'),
  });
  await expect(page.getByText('collection「selune_ci」新增 2 筆')).toBeVisible();
  const brands: { id: string; guidelineChunks: { source: string }[] }[] = await (await page.request.get('/api/brands')).json();
  const selune = brands.find((b) => b.id === 'selune')!;
  expect(selune.guidelineChunks.filter((c) => c.source === 'e2e_ci.md')).toHaveLength(2);
});

test('上傳商品照到後端並建立商品', async ({ page }) => {
  await page.goto('/products');
  const png = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 60;
    canvas.height = 90;
    const g = canvas.getContext('2d')!;
    g.fillStyle = '#c9a27e';
    g.fillRect(15, 10, 30, 70);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  await page.locator('input[type="file"]').first().setInputFiles({
    name: 'e2e_cream.png', mimeType: 'image/png', buffer: Buffer.from(png, 'base64'),
  });
  await expect(page.getByText('照片已上傳到後端（data/uploads/）。請補上價格與特徵。')).toBeVisible();
  const products: { photo: { source: string; url?: string } }[] = await (await page.request.get('/api/products?brandId=selune')).json();
  const url = products.find((p) => p.photo.source === 'upload')!.photo.url!;
  expect(url).toMatch(/^\/files\/uploads\/[0-9a-f]{16}\.(png|jpg|webp)$/);
  const img = page.locator(`img[src="${url}"]`).first();
  await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0);
});
```

- [ ] **Step 7: 修改 `web/package.json`**（`e2e:live` 指令）

找到：

```json
    "test:watch": "vitest",
    "typecheck": "next typegen && tsc --noEmit",
    "e2e": "playwright test",
    "fixtures": "tsx scripts/fixtures.ts",
    "composer": "tsx composer/server.ts"
  },
```

改成：

```json
    "test:watch": "vitest",
    "typecheck": "next typegen && tsc --noEmit",
    "e2e": "playwright test",
    "e2e:live": "playwright test -c playwright.live.config.ts",
    "fixtures": "tsx scripts/fixtures.ts",
    "composer": "tsx composer/server.ts"
  },
```

- [ ] **Step 8: 修改 `web/.dockerignore`**

E2E 檔案不放進映像檔。`playwright.live.config.ts` 會 import `e2e-live/`，所以設定檔也一併排除，否則 `next build` 的型別檢查找不到模組。

找到：

```text
coverage
test-results
playwright-report
*.tsbuildinfo
.env
.env.*
```

改成：

```text
coverage
test-results
playwright-report
e2e
e2e-live
playwright*.config.ts
*.tsbuildinfo
.env
.env.*
```

- [ ] **Step 9: 執行**

Run: `npm run e2e:live`
Expected: 6 passed（約 2–3 分鐘，含建置與啟動）。結束時移除 `genai-agent-e2e` 的容器與 volume。

Run: `npm run typecheck && npm run lint`
Expected: 沒有錯誤。

- [ ] **Step 10: Commit**

```bash
git add \
  docker-compose.e2e.yml \
  web/.dockerignore \
  web/e2e-live/global-setup.ts \
  web/e2e-live/global-teardown.ts \
  web/e2e-live/live.spec.ts \
  web/e2e-live/stack.ts \
  web/package.json \
  web/playwright.live.config.ts
git commit -m "test: add live-mode Playwright E2E against an isolated Docker Compose stack" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 17: README 與全套驗收


**Files:**
- Create: `README.md`、`backend/README.md`
- Modify: `web/README.md`

- [ ] **Step 1: 建立 `README.md`**

````markdown
# 虛實整合 GenAI Agent

一句話需求 → Agent 拆解 → RAG 檢索品牌規範 → 多通路生圖 → 合規審查與自動重試 → 挑圖改字 → 匯出。
既是每天做商品圖的工具，也是全端技術的作品集。

- **前端**：Next.js 16（靜態輸出）、TypeScript、Tailwind CSS v4、shadcn/ui、Zustand：[web/README.md](web/README.md)
- **後端**：FastAPI、SAQ worker、PostgreSQL（SQLAlchemy、Alembic）、Redis：[backend/README.md](backend/README.md)
- **composer**：Node 服務，直接執行前端的 TypeScript（版型與模擬邏輯），讓前後端只有一份實作
- **規格**：[第二階段設計規格](docs/superpowers/specs/2026-10-07-phase2-backend-design.md)；各計畫在 [docs/superpowers/plans/](docs/superpowers/plans/)

## 進度

| 計畫 | 內容 | 狀態 |
|---|---|---|
| Plan 1–3 | 前端與瀏覽器內模擬（mock 模式）、Agent 透視、成效儀表板 | 完成 |
| Plan 4 | 後端骨架與即時串流：全部 API、WebSocket、worker、Docker | 完成（外部服務為模擬版） |
| Plan 5 | RAG：Chroma、BGE-M3 與 Reranker | |
| Plan 6 | Gemini Agent、伺服器端排版與 VLM 審查 | |
| Plan 7 | ComfyUI 生圖 | |
| Plan 8 | 作品集 Demo（Cloudflare Pages＋Access） | |

## 架構

```
瀏覽器 ── 127.0.0.1:3000 ── web（nginx：前端靜態檔；/api、/ws、/files、/docs 轉給 api）
                              │
                            api（FastAPI）── postgres
                              │            └ data/（上傳的商品照；之後的生成圖）
                              │ SAQ 佇列＋事件推送
                            redis
                              │
                            worker（SAQ）── composer（Node：版型、模擬邏輯）
```

- 每則任務事件都在同一個交易中取得序號（`seq`）並寫入資料庫，再經 Redis 推送到 WebSocket；斷線或重新整理後，前端以最後收到的 `seq` 接續。
- Gemini、RAG 與 ComfyUI 目前是模擬版，行為與 mock 模式的劇本相同（第一輪刻意失誤，Query Rewriting 後通過）。右上角的連線狀態可以展開各服務的狀態，模擬版會標示「模擬」。

## 用 Docker 執行（live 模式）

需要 Docker Desktop（映像檔取自 AWS 的官方映像鏡像，不必登入 Docker Hub）。

```bash
docker compose up -d --build
```

- 前端：http://127.0.0.1:3000
- API 文件：http://127.0.0.1:3000/docs
- 停止：`docker compose down`（資料保留在 volume；加上 `-v` 會清空資料庫）
- 設定：複製 `.env.example` 成 `.env` 後修改（模擬速度、首輪是否刻意失誤等），再 `docker compose up -d`

自己的資料：

- **品牌**：複製 `brands/_template.yaml` 成 `brands/<品牌 id>.yaml` 填寫，改完執行 `docker compose restart api worker`。格式錯誤的品牌會略過，原因顯示在系統狀態。
- **商品照**：放在 `assets/products/`，到「商品庫 → 本機資料夾」匯入；也可以直接上傳（存在 `data/`）。這兩個資料夾都不會上傳 GitHub。

## 只看前端（mock 模式）

```bash
cd web
npm ci
npm run dev
```

瀏覽器內模擬整條流程，不需要後端；作品集 Demo 也是這個模式。

## 開發 live 模式

```bash
docker compose up -d postgres redis
```

接著各開一個終端機（不要同時執行 Docker 的 api，兩者都使用 8000 埠）：

| 目錄 | 指令 | 服務 |
|---|---|---|
| `backend/` | `uv run uvicorn app.api.main:app --port 8000 --reload` | api |
| `backend/` | `uv run python -m app.worker` | worker |
| `web/` | `npm run composer` | composer（3900 埠） |
| `web/` | `NEXT_PUBLIC_API_MODE=live API_PROXY_URL=http://127.0.0.1:8000 npm run dev` | 前端（/api、/files、/ws 轉給 api） |

## 測試

| 目錄 | 指令 | 內容 |
|---|---|---|
| `backend/` | `uv run pytest` | 後端（需要 `docker compose up -d postgres redis`；會自行啟動 composer） |
| `web/` | `npm run test` | 前端與 composer 的單元測試 |
| `web/` | `npm run e2e` | mock 模式 E2E |
| `web/` | `npm run e2e:live` | live 模式 E2E：以獨立的 compose 專案啟動整套服務，測完移除，不影響平常的資料 |
| `web/` | `npm run fixtures` | 重新產生 `contracts/fixtures/`（後端與前端一致性測試的固定測資） |
````

- [ ] **Step 2: 建立 `backend/README.md`**

````markdown
# 虛實整合 GenAI Agent — 後端

FastAPI（REST、WebSocket、檔案）與 SAQ worker（任務流程、文件上傳、去背、回寫），共用同一份程式碼與映像檔。
Python 3.13，以 [uv](https://docs.astral.sh/uv/) 管理。

## 開始

```bash
docker compose up -d postgres redis   # 在 repo 根目錄
cd backend
uv sync
```

| 指令 | 用途 |
|---|---|
| `uv run uvicorn app.api.main:app --port 8000 --reload` | api（啟動時執行 migration 並匯入 `brands/*.yaml`） |
| `uv run python -m app.worker` | worker（啟動時把中斷的任務標記失敗，排隊中的重新放回佇列） |
| `uv run pytest` | 測試：重建 `genai_test` 資料庫、使用 Redis 第 15 號資料庫，並在 3902 埠啟動 composer（需要 `web/` 已 `npm ci`） |
| `uv run ruff check . && uv run ruff format --check .` | lint 與格式 |
| `uv run mypy` | 型別檢查（strict） |
| `uv run alembic revision --autogenerate -m "說明"` | 新增 migration |

設定來自環境變數或 repo 根目錄的 `.env`（見 `app/settings.py` 與 `.env.example`）。預設值對應本機開發：PostgreSQL 在 5433 埠（避開 Windows 原生的 5432）、一律使用 `127.0.0.1`。

## API

- 文件：http://127.0.0.1:8000/docs
- 錯誤一律回傳 `{ error: { code, message } }`，message 為繁體中文，前端直接顯示。
- `WS /ws/jobs/{id}?after={seq}`：先補送 `seq` 大於 `after` 的事件，再轉送即時事件；任務結束且事件送完後以 1000 關閉，任務不存在時以 4404 關閉。
- `POST /api/brands/{id}/documents`：以 NDJSON 串流回報切塊、向量化與寫入的進度。

## 任務流程

1. `POST /api/jobs` 驗證後寫入任務，送出 `job.accepted` 與 `job.status queued`，放進 `jobs` 佇列。
2. worker 一次執行一個生圖任務（只有一張 GPU）；去背、文件上傳與回寫在 `tasks` 佇列，最多同時兩個。
3. 每則事件在同一個交易中鎖定任務列並取得下一個 `seq`，commit 後發布到 Redis 頻道 `job:{id}`；結束任務的 `job.status` 一定是最後一則。
4. 取消：排隊中的直接取消；執行中的設定旗標，worker 在步驟之間停止。

外部服務都經過 `app/pipeline/ports.py` 的介面；目前由 `app/pipeline/sim.py` 的模擬版實作（Agent 與審查透過 composer 沿用前端 mock 的 TypeScript），之後的計畫逐一換成 Chroma、Gemini 與 ComfyUI。

## 目錄

```
app/
├─ api/            FastAPI：main.py（入口與錯誤格式）、catalog、jobs、files、services
├─ pipeline/       任務流程（runner）、外部服務介面（ports）、模擬版（sim）
├─ adapters/       composer 用戶端
├─ db/             SQLAlchemy 模型與連線
├─ repo/           資料存取：品牌與商品（catalog）、任務（jobs）、歷史紀錄（history）
├─ contract.py     Pydantic 模型（對應 web/src/types/contract.ts）
├─ events.py       事件保存與推送、WebSocket 串流
├─ queues.py       SAQ 佇列
├─ worker.py       worker 的任務與啟動時復原
├─ brands.py       品牌設定檔（brands/*.yaml）的驗證與匯入
├─ stats.py        成效儀表板統計（與前端的結果完全相同）
└─ settings.py
migrations/        Alembic
tests/             pytest；與前端的一致性測試讀取 contracts/fixtures/（由 web 的 npm run fixtures 產生）
```
````

- [ ] **Step 3: 修改 `web/README.md`**

找到（1／4）：

```markdown
# 虛實整合 GenAI Agent — 前端（第一階段）

Next.js 16（App Router）+ TypeScript + Tailwind CSS v4 + shadcn/ui + Zustand。第一階段由瀏覽器內的 `MockApiClient` 模擬整條 Agent 流程，送出的事件與第二階段 FastAPI WebSocket 相同，所以不需要後端。

## 需求
```

改成：

```markdown
# 虛實整合 GenAI Agent — 前端

Next.js 16（App Router，靜態輸出）+ TypeScript + Tailwind CSS v4 + shadcn/ui + Zustand。畫面只依賴 `ApiClient` 介面，有兩種實作，送出的事件格式相同（`src/types/contract.ts`）：

- **mock**（預設）：瀏覽器內的 `MockApiClient` 模擬整條 Agent 流程，不需要後端；作品集 Demo 使用。
- **live**：`HttpApiClient` 連線 FastAPI（REST＋WebSocket），任務由後端執行。整套服務的執行方式見 [repo 根目錄的 README](../README.md)。

## 需求
```

找到（2／4）：

````markdown
npm run dev
```

開啟 http://localhost:3000（會導向「新任務」）。預設就是 mock 模式；要明確設定時複製 `.env.example` 成 `.env.local`。

## 指令

| 指令 | 用途 |
|---|---|
| `npm run dev` | 開發伺服器 |
| `npm run test` | Vitest 單元測試 |
| `npm run e2e` | Playwright E2E（自動建置並在 3100 埠啟動正式版；第一次要先執行 `npx playwright install chromium`） |
| `npm run typecheck` | 型別檢查（含路由型別） |
| `npm run lint` | ESLint |
| `npm run build` | 正式建置 |

## 頁面

| 模式 | 路由 | 頁面 |
|---|---|---|
| 工作台 | `/studio` | 新任務：一句話需求 → 生成 → 挑圖改字 → 匯出 zip |
| 工作台 | `/products` | 商品庫：上傳／拖放、去背預覽（示意）、本機資料夾匯入 |
| 工作台 | `/queue` | 批次佇列：多商品 × 多模板 |
| 工作台 | `/history` | 歷史紀錄：篩選、收藏、以相同設定重做 |
| 工作台 | `/brands` | 品牌知識庫：CI、禁用詞、RAG 切塊、上傳文件 |
````

改成：

````markdown
npm run dev
```

開啟 http://localhost:3000（會導向「新任務」），預設為 mock 模式。

live 模式：先啟動後端，再以 `NEXT_PUBLIC_API_MODE=live API_PROXY_URL=http://127.0.0.1:8000 npm run dev` 執行，開發伺服器會把 `/api`、`/files`、`/ws` 轉給後端；也可以把這兩個值寫進 `.env.local`（見 `.env.example`）。正式的 live 版由 Docker 的 nginx 提供靜態輸出。

## 指令

| 指令 | 用途 |
|---|---|
| `npm run dev` | 開發伺服器 |
| `npm run build` | 靜態輸出到 `out/` |
| `npm run test` | Vitest 單元測試（含 composer） |
| `npm run e2e` | mock 模式 E2E（建置後在 3100 埠提供靜態輸出；第一次要先執行 `npx playwright install chromium`） |
| `npm run e2e:live` | live 模式 E2E（以 docker compose 啟動獨立的整套服務，3200 埠，測完移除） |
| `npm run composer` | composer（3900 埠）：後端使用的版型與模擬邏輯 |
| `npm run fixtures` | 產生 `../contracts/fixtures/`（後端的一致性測試使用） |
| `npm run typecheck` | 型別檢查（含路由型別） |
| `npm run lint` | ESLint |

## 頁面

| 模式 | 路由 | 頁面 |
|---|---|---|
| 工作台 | `/studio` | 新任務：一句話需求 → 生成 → 挑圖改字 → 匯出 zip |
| 工作台 | `/products` | 商品庫：上傳／拖放、去背預覽（示意）、本機資料夾匯入（live 模式） |
| 工作台 | `/queue` | 批次佇列：多商品 × 多模板 |
| 工作台 | `/history` | 歷史紀錄：篩選、收藏、以相同設定重做 |
| 工作台 | `/brands` | 品牌知識庫：CI、禁用詞、RAG 切塊、上傳文件 |
````

找到（3／4）：

```markdown

## 資料保存

- 商品、歷史紀錄、上傳的品牌文件，以及已結束的任務（最近 40 筆，含完整事件）存在瀏覽器的 IndexedDB（資料庫 `genai-poster-agent`）；清除網站資料就會重置。
- 每則事件都帶序號（`seq`）與時間戳（`ts`）。Agent 透視用來顯示事件串流與各節點耗時；儀表板依此統計耗時。
- 自己的商品照可放在 repo 根目錄的 `assets/products/`（已在 `.gitignore`，不會上傳 GitHub），開發模式下到「商品庫」一鍵匯入，檔名即商品名稱。
- 字型使用 `@fontsource-variable` 自帶的 Noto Sans／Serif TC，執行時不連外部網路。

## Demo 控制台

畫面右下角「Demo」：播放速度 1×／2×／4×、強制首輪失敗（展示 Query Rewriting 與重試）、強制全部失敗（展示「需人工審核」）。
```

改成：

```markdown

## 資料保存

- **mock 模式**：商品、歷史紀錄、上傳的品牌文件，以及已結束的任務（最近 40 筆，含完整事件）存在瀏覽器的 IndexedDB（資料庫 `genai-poster-agent`）；清除網站資料就會重置。
- **live 模式**：存在後端的 PostgreSQL；上傳的商品照存在 repo 根目錄的 `data/`。WebSocket 斷線時以最後收到的序號重新連線（1 秒起，最長 10 秒）；重新整理後，新任務頁面會接續這個分頁的任務。
- 每則事件都帶序號（`seq`）與時間戳（`ts`）。Agent 透視用來顯示事件串流與各節點耗時；儀表板依此統計耗時。
- 自己的商品照可放在 repo 根目錄的 `assets/products/`（已在 `.gitignore`，不會上傳 GitHub），live 模式下到「商品庫」一鍵匯入，檔名即商品名稱。
- 字型使用 `@fontsource-variable` 自帶的 Noto Sans／Serif TC，執行時不連外部網路。

## Demo 控制台（只有 mock 模式）

畫面右下角「Demo」：播放速度 1×／2×／4×、強制首輪失敗（展示 Query Rewriting 與重試）、強制全部失敗（展示「需人工審核」）。
```

找到（4／4）：

````markdown

```
src/
├─ app/                 路由與 api/local-products（開發用）
├─ components/          ui（shadcn）、layout、studio、product、queue、history、brands、poster、agent、dashboard
├─ lib/
│  ├─ api/              ApiClient 介面、mock/（MockApiClient、劇本、示範資料與示範任務、IndexedDB）
│  ├─ agent/            Prompt 構建、修正策略、版本差異、流程節點狀態、事件摘要、透視用的資料整理
│  ├─ compose/          版型、排版引擎（scene）、程序化素材（art）、Canvas 繪製（paint／render）
│  ├─ review/           規則型合規審查、ΔE2000、文案重新檢查
│  ├─ jobs/             事件 → 畫面狀態（reducer）
│  ├─ stats/            成效儀表板統計與成本估算
│  ├─ export/           檔名、zip、下載
│  ├─ store/            Zustand stores
│  └─ server/           只在伺服器端執行的工具
└─ types/contract.ts    前後端資料約定
e2e/                    Playwright：主流程（含匯出 zip）、Agent 透視重試 diff、儀表板、手機寬度
```
````

改成：

````markdown

```
src/
├─ app/                 路由
├─ components/          ui（shadcn）、layout、studio、product、queue、history、brands、poster、agent、dashboard
├─ lib/
│  ├─ api/              ApiClient 介面；mock/（MockApiClient、劇本、示範資料與示範任務、IndexedDB）；http/（HttpApiClient、WebSocket 重新連線）
│  ├─ agent/            Prompt 構建、修正策略、版本差異、流程節點狀態、事件摘要、透視用的資料整理
│  ├─ compose/          版型、排版引擎（scene）、程序化素材（art）、Canvas 繪製（paint／render）
│  ├─ review/           規則型合規審查、ΔE2000、文案重新檢查
│  ├─ jobs/             事件 → 畫面狀態（reducer）
│  ├─ stats/            成效儀表板統計與成本估算
│  ├─ export/           檔名、zip、下載
│  └─ store/            Zustand stores
└─ types/contract.ts    前後端資料約定
composer/               Node 服務：版型與模擬邏輯（/layout、/sim/*），由後端呼叫
scripts/                產生 fixtures、提供靜態輸出（Playwright 使用）
e2e/                    Playwright（mock）：主流程（含匯出 zip）、Agent 透視重試 diff、儀表板、手機寬度
e2e-live/               Playwright（live）：主流程、重新整理後接續、API 重新啟動後重新連線、取消、文件與商品照上傳
Dockerfile、nginx.conf  live 版（nginx）與 composer 的映像檔
```
````

- [ ] **Step 4: 全套驗收**

在 `backend/`（需要 `docker compose up -d postgres redis`）：

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest -q
```

Expected：沒有錯誤；63 passed。

在 `web/`：

```bash
npm run test
npm run typecheck && npm run lint && npm run build
npm run e2e
npm run e2e:live
```

Expected：41 個測試檔、314 個測試通過；沒有錯誤；mock E2E 5 passed；live E2E 6 passed。

在 repo 根目錄：

```bash
docker compose up -d --build --wait
```

Expected：6 個服務都 `Healthy`。在 http://127.0.0.1:3000 依 Task 13 Step 15 的項目操作一次。

- [ ] **Step 5: Commit**

```bash
git add \
  README.md \
  backend/README.md \
  web/README.md
git commit -m "docs: explain how to run, develop and test the full stack" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 完成後（留給 Plan 5 以後）

- **Plan 5：RAG**：
  - 加入 chroma 服務。
  - 以 Chroma 與 BGE-M3／Reranker（ONNX int8）實作 `Retriever`。
  - 文件上傳的向量化、歷史回寫寫入 Chroma。
  - 系統狀態的「向量庫」改為實際檢查。
  - 儀表板改用實際用量計算成本。
- **Plan 6：Gemini**：
  - `Agent` 與 `Reviewer` 的真實版。
  - composer 的 `/render`、`/review`、`measurePrimary`、`ocrDiffs` 與字型。
  - 伺服器端繪製海報時也要畫 `Brand.logo`。
  - 新增 `job_usage` 資料表（新的 migration），記錄每次呼叫的 tokens 與成本（規格 5.8、6.1）。
  - `.env` 的 `GEMINI_API_KEY`。
- **Plan 7：ComfyUI**：
  - `ImageEngine` 的真實版：上傳、進度、輸出、取消。
  - `RenderBackground.includesProduct` 為 true 時跳過商品圖層。
  - 去背改為真正的 BiRefNet。
  - `.env` 的 `COMFYUI_URL`（`host.docker.internal:8188`）。
- **效能**：每則事件各自一個交易，加上 Redis 發布。
  - 實測一個任務約 224 則事件：在 Docker 內 1× 速度約 16–17 秒，比劇本的 15 秒多約 10%。
  - 真實生圖的耗時遠大於此，暫不需要批次寫入。
- **作品集 Demo（Plan 8）**：mock 版的靜態輸出（`NEXT_PUBLIC_API_MODE` 不設定）部署到 Cloudflare Pages，以 Access 限制名單。
