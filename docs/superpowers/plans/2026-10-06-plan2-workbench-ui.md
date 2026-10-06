# Plan 2：工作台 UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Plan 1 的核心邏輯上，完成「工作台」模式的全部頁面：App Shell（模式切換、品牌切換、Demo 控制台、連線狀態）、新任務（需求拆解 → 生成 → 結果牆 → 文字編輯 → 匯出 zip）、商品庫、批次佇列、歷史紀錄、品牌知識庫。第一個任務先定案 `ApiClient` 介面。

**Architecture:** UI 只透過 `ApiClient` 讀資料、訂閱事件。事件由純函式 reducer（`lib/jobs/view.ts`）累積成畫面狀態。海報分兩層：`lib/compose/scene.ts` 依 BBox 與文案算出繪製指令並自動縮字（純函式、可測），`lib/compose/paint.ts` 把指令畫到 Canvas，預覽與匯出共用。狀態放在 Zustand（`lib/store/*`），事件訂閱放在 store 外，換頁不會中斷生成。瀏覽器資料存在 IndexedDB。

**Tech Stack:** Next.js 16.3（App Router、Turbopack）、React 19.2、TypeScript strict、Tailwind CSS v4、shadcn/ui 4.21（Radix）、lucide-react、Zustand 5、idb-keyval、JSZip、@fontsource-variable（Noto Sans／Serif TC）、Vitest（+ fake-indexeddb）

**Spec:** `docs/superpowers/specs/2026-10-05-genai-poster-agent-frontend-design.md`

**Plan series:** 本文件是 3 份計畫中的第 2 份。Plan 3（Agent 透視、成效儀表板、Playwright E2E）在本計畫完成後撰寫。

## Plan 1 驗收結果（2026-10-06）

撰寫本計畫前重新驗證了 Plan 1：

- 逐一比對 Plan 1 每個程式碼區塊與 `web/` 的實際檔案：內容一致，或差異已記在 Plan 1 的「執行紀錄」中（Vitest 路徑別名、`copyTexts`／`claimTexts`、修正累積、`serial()`／`deliver()`、F1–F9）。`lib/core/freeze.ts` 是 F2 新增的檔案。
- `npm run test`：19 個測試檔、131 個測試全部通過。`npm run typecheck` 與 `npm run lint` 都沒有錯誤。
- 規格對照：
  - 1× 時間軸含一次重試共 14,500 ms（規格寫約 15 秒）。
  - 重試以模板為單位。
  - 第一輪有四種失誤：ΔE、禁用詞、Logo 淨空區、缺效果註記。
  - 第二輪各候選分數不同，部分附警告。
  - Demo 預設首輪失敗。
- 結論：Plan 1 正確完成，可以開始 Plan 2。

## 本計畫的驗證方式

本計畫的程式碼已在獨立副本上逐 Task 實作並驗證：
- 從 Plan 1 的狀態開始，只依本文件的步驟重建。
- 每個 Task 結束時都通過型別檢查，測試數量與各 Task 的 Expected 相符。
- 最後的 `npm run test`、`npm run typecheck`、`npm run lint`、`npm run build` 全部通過。
- 每個頁面都用瀏覽器實際操作過。

執行時若結果與 Expected 不同，先檢查是否漏了步驟，不要修改測試來配合。

## Global Constraints

- 前端程式碼全部在 `web/`；除非另外註明，指令都在 `web/` 目錄執行
- 環境：Node 24、npm 11、Windows + Git Bash
- 沿用 Plan 1：TypeScript strict、路徑別名 `@/*`；資料型別只定義在 `web/src/types/contract.ts`
- `web/src/lib/**` 分三類：
  - 純函式模組：不 import React、不使用 `window`／`document`，必須有 Vitest 測試。
  - 瀏覽器模組：檔頭註明，只能在 client component 的 effect、事件處理或 store action 中呼叫。包含 `compose/paint.ts`、`compose/render.ts`、`export/download.ts`、`export/posters.ts`、`image/downscale.ts`、`api/mock/idb-store.ts`。
  - 伺服器模組：`lib/server/**`，只在 Route Handler 使用。
- `getApiClient()` 不可在伺服器端 render 時呼叫。只能在 effect、事件處理、store action，或 `useSyncExternalStore` 的 client snapshot 中呼叫。
- 事件與示範資料是凍結的物件，修改前先 `structuredClone`
- 不使用 `next/font/google`。字型用 `@fontsource-variable` npm 套件（字型檔隨套件發佈），執行時不發出外部網路請求；唯一的請求是同源的 `/api/local-products`。
- `eslint-config-next` 把 React Compiler 規則設為錯誤等級：
  - 不可在 effect 裡同步呼叫 setState（非同步回呼裡呼叫可以）。
  - 不可在 render 時讀 `ref.current`、呼叫 `Date.now()` 或 `Math.random()`。
  - 不得用 `eslint-disable` 繞過。
- 呼叫 `useSearchParams` 的頁面必須包在 `<Suspense>` 裡，否則 `next build` 會失敗
- 圖片一律用 `next/image` 加 `unoptimized`（data URL 與本機 API），避免 `@next/next/no-img-element` 警告
- shadcn 元件由 CLI 產生（固定 `shadcn@4.21.3`、Radix 底層、nova 預設），不要手動修改 `src/components/ui/*`
- UI 文字與使用者可見字串用繁體中文；程式識別字用英文
- 每個 Task 結束都要 commit，訊息最後一行加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

## 介面與設計決策

Plan 1「交接給 Plan 2 的事項」的處理方式：

| 交接事項 | 本計畫的處理 |
|---|---|
| 擴充 `ApiClient`、定案 `subscribe` 簽名 | Task 1 把簽名定為 `subscribe(jobId, onEvent, onError?)`：任務不存在或連線中斷時，以 onError 非同步回報，不丟例外（WebSocket 也只能非同步得知失敗）。同時新增 `connection`、`listJobs`、`getJob`、`setFavorite`。Task 2 再新增 `uploadProductPhoto`、`requestCutout`、`ingestBrandDocument`。 |
| 模板管理 | 不做。規格頁面沒有模板管理介面，版型又以模板 id 對應（`LAYOUT_PRESETS`），所以 `listTemplates()` 維持唯讀。 |
| 儀表板統計 | 留給 Plan 3。新增方法不影響既有 UI。 |
| `Product.cutout` | Task 2 加入 `ProductCutout { model; url \| null }`。`url` 為 null 代表示意：合成時用色彩增值（multiply），讓白底融入淺色背景。 |
| `getApiClient()` 只能在 client 呼叫 | 寫進 Global Constraints 與 `lib/api/index.ts` 的註解；`ConnectionBadge` 用 `useSyncExternalStore` 的 server snapshot。 |
| 事件與示範資料凍結 | `lib/jobs/view.ts` 只做不可變更新；文字編輯器帶入文案前先 `structuredClone`。 |
| 文字編輯器重跑審查 | Task 12 的 `recheckCopy` 重跑 7 項規則型檢查，VLM 結果沿用生成時的；含禁用詞時不能匯出。 |
| 取代 `layout.tsx`／`page.tsx`、不用 `next/font/google` | Task 9。 |
| `CAMPAIGN_PERIOD` 與單一商品文案預設 | 文字編輯器可以改所有文案（含頁尾的活動期間）後再匯出。改成品牌或任務層級設定，等正式品牌資料進來時再做。 |
| 事件沒有時間戳與序號 | 留給 Plan 3（事件串流）與第二階段（重新連線）。 |

本計畫的其他決策：

- **批次佇列**：佇列在前端排程，一次執行一筆，每筆是一個商品的任務。
  - 「暫停佇列」：執行中的那筆跑完後，不再啟動下一筆。
  - 「暫停此筆」：等待中的項目輪到時也不啟動。
  - 執行中的任務只能取消，因為 ComfyUI 生成到一半無法暫停。
- **匯出即寫入歷史**：「匯出 zip 並寫入歷史」同時呼叫 `selectRender`，標記「已回寫 RAG」。同一張圖配同一份文案不會重複寫入。
- **需人工審核**：沒有候選通過時，仍可手動選圖。匯出前必須勾選「我已人工確認」。
- **去背示意**：上傳的商品照在海報上以 multiply 合成，商品庫的去背預覽在透明格紋上用 `mix-blend-multiply` 顯示。示範商品是向量素材，不需要去背。
- **商品照**：
  - 上傳前縮到最長邊 1600px，轉成 data URL 存進 IndexedDB。
  - `assets/products/` 的照片透過開發用 API 讀取，正式環境回傳 404。

## File Structure

| 檔案 | 責任 |
|---|---|
| `web/src/types/contract.ts`（修改） | 新增 `JobSummary`、`ConnectionState`、`ProductCutout`、`BrandDocument`、`IngestEvent`；`Product.cutout`；`RagTag` 加 `general` |
| `web/src/lib/api/client.ts`（修改） | `ApiClient` 定案、`ConnectionChannel`、`JobSnapshot` |
| `web/src/lib/api/mock/client.ts`（修改） | 實作新方法 |
| `web/src/lib/api/mock/idb-store.ts` | IndexedDB 版 `KeyValueStore` |
| `web/src/lib/api/index.ts`（修改） | `API_MODE`；瀏覽器用 `IdbStore` |
| `web/src/lib/rag/chunk.ts` | 品牌文件切塊、標籤判斷、模擬向量 |
| `web/src/lib/jobs/view.ts` | 事件 → `JobView`、結果牆候選、預設選擇、進度 |
| `web/src/lib/compose/scene.ts` | 排版引擎：BBox + 文案 → 繪製指令（自動縮字） |
| `web/src/lib/compose/art.ts` | 程序化背景 SVG、示範商品圖 SVG |
| `web/src/lib/compose/assets.ts` | 商品圖來源與字型（純函式） |
| `web/src/lib/compose/paint.ts`、`render.ts` | Canvas 繪製；準備圖片與字型、預覽與匯出 |
| `web/src/lib/export/naming.ts`、`zip.ts`、`download.ts`、`posters.ts` | 檔名、zip、下載、匯出流程 |
| `web/src/lib/server/local-products.ts` | 讀取 `assets/products/` |
| `web/src/app/api/local-products/route.ts`、`[file]/route.ts` | 開發用 API |
| `web/src/lib/review/recheck.ts` | 文字編輯後重新審查 |
| `web/src/lib/history/filter.ts` | 歷史紀錄篩選 |
| `web/src/lib/image/downscale.ts` | 上傳前縮圖 |
| `web/src/lib/store/app.ts`、`products.ts`、`studio.ts`、`queue.ts` | Zustand stores |
| `web/src/components/ui/*` | shadcn 產生 |
| `web/src/components/layout/*` | App Shell：頂列、側欄、品牌切換、連線狀態、Demo 控制台 |
| `web/src/components/common/*` | `PageHeader`、`EmptyState` |
| `web/src/components/poster/*` | `PosterCanvas`、`ScoreBadge`、`CheckList` |
| `web/src/components/product/*` | 商品縮圖、卡片、編輯、去背預覽、上傳、本機資料夾 |
| `web/src/components/studio/*` | 需求表單、進度、結果牆、文字編輯器 |
| `web/src/components/queue/*`、`history/*`、`brands/*` | 各頁元件 |
| `web/src/components/agent/agent-preview.tsx` | `/agent` 簡易版（事件 Log；完整版在 Plan 3） |
| `web/src/app/**/page.tsx` | 路由頁面 |

測試檔與被測檔放在同一資料夾，命名 `*.test.ts`。

---

### Task 1: `ApiClient` 介面定案（任務列表、連線狀態、收藏）

**Files:**
- Modify: `web/src/types/contract.ts`、`web/src/lib/api/client.ts`、`web/src/lib/api/mock/client.ts`
- Test: `web/src/lib/api/mock/client.test.ts`（修改）

**Interfaces:**
- Consumes：Plan 1 的 `MockApiClient`、`buildTimeline`、`playTimeline`
- Produces：
  - 型別 `JobSummary`、`ConnectionStatus`、`ConnectionState`
  - `interface ConnectionChannel { get(): ConnectionState; subscribe(listener): () => void }`
  - `interface JobSnapshot { summary: JobSummary; events: JobEvent[] }`
  - `ApiClient` 新增 `connection`、`listJobs()`、`getJob(jobId)`、`setFavorite(historyId, favorite)`
  - `subscribe(jobId, onEvent, onError?)`：任務不存在時以 `setTimeout(…, 0)` 呼叫 onError，不丟例外
  - `createJob` 會複製輸入（呼叫端之後修改 input 不影響任務）

- [ ] **Step 1: 修改 `web/src/types/contract.ts`**

找到：

```ts
export interface DemoOptions { speed: 1 | 2 | 4; firstRoundFail: boolean; forceAllFail: boolean }
```

改成：

```ts
export interface DemoOptions { speed: 1 | 2 | 4; firstRoundFail: boolean; forceAllFail: boolean }

/* ---------- 任務列表與連線狀態 ---------- */
export interface JobSummary {
  id: string;
  input: JobInput;
  createdAt: string;
  stage: JobStage;
  round: number;
  /** 已結束（done／needs_review／cancelled） */
  finished: boolean;
  /** 任務完成時每個模板的最佳候選；尚未完成或需人工審核時為空物件 */
  bestRenderIds: Partial<Record<TemplateId, string>>;
}

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';
export interface ConnectionState {
  status: ConnectionStatus;
  /** mock：瀏覽器內模擬；websocket：連線 FastAPI（第二階段） */
  transport: 'mock' | 'websocket';
  error: string | null;
}
```

- [ ] **Step 2: 修改 `web/src/lib/api/mock/client.test.ts`**（先寫失敗測試）

找到（1／2）：

```ts

  it('rejects unknown jobs and empty template lists', async () => {
    const api = new MockApiClient();
    expect(() => api.subscribe('nope', () => {})).toThrow('Unknown job');
    await expect(startJob(api, { templateIds: [] })).rejects.toThrow('至少要選一個通路模板');
  });
```

改成：

```ts

  it('rejects empty template lists', async () => {
    const api = new MockApiClient();
    await expect(startJob(api, { templateIds: [] })).rejects.toThrow('至少要選一個通路模板');
  });

  it('reports unknown jobs through onError instead of throwing', async () => {
    const api = new MockApiClient();
    const onError = vi.fn();
    api.subscribe('nope', () => {}, onError);
    expect(onError).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(0);
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: 'Unknown job: nope' }));
  });
```

找到（2／2）：

```ts

describe('getApiClient', () => {
```

改成：

```ts

describe('job queries, connection and favorites', () => {
  it('lists jobs newest first with their live status', async () => {
    const api = new MockApiClient();
    const first = await startJob(api);
    await vi.advanceTimersByTimeAsync(14_500);
    const second = await startJob(api, { templateIds: ['story'] });
    await vi.advanceTimersByTimeAsync(1_000);
    const jobs = await api.listJobs();
    expect(jobs.map((j) => j.id)).toEqual([second.jobId, first.jobId]);
    expect(jobs[1]).toMatchObject({ stage: 'done', round: 2, finished: true, createdAt: NOW.toISOString() });
    expect(jobs[1].bestRenderIds['ig-post']).toMatch(/_r2_ig-post_v\d$/);
    expect(jobs[0]).toMatchObject({ stage: 'parsing', finished: false, bestRenderIds: {} });
    expect(jobs[0].input.templateIds).toEqual(['story']);
  });

  it('returns a snapshot of a job and its events', async () => {
    const api = new MockApiClient();
    const { jobId, events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(5_000);
    const snap = await api.getJob(jobId);
    expect(snap.summary.id).toBe(jobId);
    expect(snap.events).toEqual(events);
    await expect(api.getJob('nope')).rejects.toThrow('Unknown job');
  });

  it('keeps the input it was given, even if the caller mutates it later', async () => {
    const api = new MockApiClient();
    const parsedBrief = await api.parseBrief('selune', BRIEF, 'prod_selune_serum');
    const input: JobInput = {
      brandId: 'selune', productId: 'prod_selune_serum', brief: BRIEF, parsedBrief, templateIds: ['ig-post'],
      variantsPerTemplate: 4, llm: 'Gemini 3.7 Flash', engine: 'comfyui', vlm: 'Gemini 3.7 Vision', maxRetries: 2,
    };
    const { jobId } = await api.createJob(input);
    input.templateIds.push('story');
    expect((await api.getJob(jobId)).summary.input.templateIds).toEqual(['ig-post']);
  });

  it('is always connected in mock mode', () => {
    const api = new MockApiClient();
    expect(api.connection.get()).toEqual({ status: 'connected', transport: 'mock', error: null });
    expect(api.connection.get()).toBe(api.connection.get());
    const unsubscribe = api.connection.subscribe(() => {});
    expect(typeof unsubscribe).toBe('function');
  });

  it('toggles favorites on history entries', async () => {
    const api = new MockApiClient();
    const { jobId, events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(14_500);
    const done = events.find((e) => e.type === 'job.completed');
    if (done?.type !== 'job.completed') throw new Error('job did not complete');
    const prompt = events.find((e) => e.type === 'prompt.generated' && e.round === 2);
    if (prompt?.type !== 'prompt.generated') throw new Error('missing round 2 prompt');
    const entry = await api.selectRender(jobId, done.bestRenderIds['ig-post']!, prompt.spec.copy);
    expect((await api.setFavorite(entry.id, true)).favorite).toBe(true);
    expect((await api.listHistory('selune'))[0].favorite).toBe(true);
    await expect(api.setFavorite('nope', true)).rejects.toThrow('Unknown history entry');
  });
});

describe('getApiClient', () => {
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `npx vitest run src/lib/api/mock/client.test.ts`
Expected: FAIL。`api.listJobs is not a function`、`api.connection` 為 undefined，`subscribe('nope')` 仍會丟出例外。

- [ ] **Step 4: 取代 `web/src/lib/api/client.ts`**

```ts
import type {
  Brand, ChannelTemplate, ConnectionState, Copy, DemoOptions, HistoryEntry, JobEvent, JobInput, JobSummary, ParsedBrief,
  Product,
} from '@/types/contract';

export type ProductDraft = Omit<Product, 'id' | 'createdAt'> & { id?: string };

export interface DemoControls {
  get(): DemoOptions;
  set(patch: Partial<DemoOptions>): void;
}

export interface ConnectionChannel {
  /** 狀態沒變時回傳同一個物件（可直接給 useSyncExternalStore 使用） */
  get(): ConnectionState;
  /** 狀態改變時通知；回傳取消訂閱的函式 */
  subscribe(listener: (state: ConnectionState) => void): () => void;
}

export interface JobSnapshot { summary: JobSummary; events: JobEvent[] }

/** UI 只依賴這個介面：第一階段由 MockApiClient 實作，第二階段由連線 FastAPI 的 HttpApiClient 實作 */
export interface ApiClient {
  /** 只有 mock 模式有 Demo 控制台；live 模式為 null */
  readonly demo: DemoControls | null;
  readonly connection: ConnectionChannel;
  listBrands(): Promise<Brand[]>;
  listTemplates(): Promise<ChannelTemplate[]>;
  listProducts(brandId: string): Promise<Product[]>;
  saveProduct(draft: ProductDraft): Promise<Product>;
  deleteProduct(id: string): Promise<void>;
  parseBrief(brandId: string, text: string, productId: string | null): Promise<ParsedBrief>;
  createJob(input: JobInput): Promise<{ jobId: string }>;
  /**
   * 先重播已發生的事件，再接收即時事件；回傳取消訂閱的函式。
   * 任務不存在或連線中斷時以 onError 非同步回報，不丟出例外（與 WebSocket 的行為一致）。
   */
  subscribe(jobId: string, onEvent: (event: JobEvent) => void, onError?: (error: Error) => void): () => void;
  cancelJob(jobId: string): Promise<void>;
  /** 最新的任務在前 */
  listJobs(): Promise<JobSummary[]>;
  getJob(jobId: string): Promise<JobSnapshot>;
  selectRender(jobId: string, renderId: string, copy: Copy): Promise<HistoryEntry>;
  listHistory(brandId?: string): Promise<HistoryEntry[]>;
  setFavorite(historyId: string, favorite: boolean): Promise<HistoryEntry>;
}
```

- [ ] **Step 5: 修改 `web/src/lib/api/mock/client.ts`**

原本的私有方法 `getJob` 與介面的 `getJob` 同名，所以改名為 `requireJob`。

找到（1／12）：

```ts
import type { Copy, DemoOptions, HistoryEntry, JobEvent, JobInput, Product, Render } from '@/types/contract';
import type { ApiClient, DemoControls, ProductDraft } from '../client';
import { CHANNEL_TEMPLATES, getTemplate } from '@/lib/compose/templates';
```

改成：

```ts
import type {
  ConnectionState, Copy, DemoOptions, HistoryEntry, JobEvent, JobInput, JobStage, JobSummary, Product, Render, TemplateId,
} from '@/types/contract';
import type { ApiClient, ConnectionChannel, DemoControls, JobSnapshot, ProductDraft } from '../client';
import { CHANNEL_TEMPLATES, getTemplate } from '@/lib/compose/templates';
```

找到（2／12）：

```ts
  input: JobInput;
  events: JobEvent[];
```

改成：

```ts
  input: JobInput;
  createdAt: string;
  events: JobEvent[];
```

找到（3／12）：

```ts
  renders: Map<string, Render>;
  round: number;
  finished: boolean;
```

改成：

```ts
  renders: Map<string, Render>;
  stage: JobStage;
  round: number;
  bestRenderIds: Partial<Record<TemplateId, string>>;
  finished: boolean;
```

找到（4／12）：

```ts
  player: PlayerHandle | null;
}

const KEYS = { products: 'products', deleted: 'deletedSampleIds', history: 'history' } as const;
```

改成：

```ts
  player: PlayerHandle | null;
}

/** mock 沒有真正的連線：永遠是「已連線」 */
const MOCK_CONNECTION: ConnectionState = Object.freeze({ status: 'connected', transport: 'mock', error: null });

const KEYS = { products: 'products', deleted: 'deletedSampleIds', history: 'history' } as const;
```

找到（5／12）：

```ts
  readonly demo: DemoControls;
  private options: DemoOptions = { speed: 1, firstRoundFail: true, forceAllFail: false };
```

改成：

```ts
  readonly demo: DemoControls;
  readonly connection: ConnectionChannel = { get: () => MOCK_CONNECTION, subscribe: () => () => {} };
  private options: DemoOptions = { speed: 1, firstRoundFail: true, forceAllFail: false };
```

找到（6／12）：

```ts

    const jobId = makeJobId(this.now());
    const rec: JobRecord = {
      id: jobId, input, events: [], listeners: new Set(), renders: new Map(), round: 0, finished: false, player: null,
    };
```

改成：

```ts

    const now = this.now();
    const jobId = makeJobId(now);
    const rec: JobRecord = {
      id: jobId, input: structuredClone(input), createdAt: now.toISOString(), events: [], listeners: new Set(),
      renders: new Map(), stage: 'parsing', round: 0, bestRenderIds: {}, finished: false, player: null,
    };
```

找到（7／12）：

```ts
      case 'job.status':
        rec.round = e.round;
        break;
```

改成：

```ts
      case 'job.status':
        rec.stage = e.stage;
        rec.round = e.round;
        break;
      case 'job.completed':
        rec.bestRenderIds = { ...e.bestRenderIds };
        break;
```

找到（8／12）：

```ts

  private getJob(jobId: string): JobRecord {
    const rec = this.jobs.get(jobId);
```

改成：

```ts

  private requireJob(jobId: string): JobRecord {
    const rec = this.jobs.get(jobId);
```

找到（9／12）：

```ts

  subscribe(jobId: string, onEvent: (event: JobEvent) => void): () => void {
    const rec = this.getJob(jobId);
    for (const e of rec.events) this.deliver(onEvent, e);
```

改成：

```ts

  subscribe(jobId: string, onEvent: (event: JobEvent) => void, onError?: (error: Error) => void): () => void {
    const rec = this.jobs.get(jobId);
    if (!rec) {
      const timer = setTimeout(() => {
        const error = new Error(`Unknown job: ${jobId}`);
        if (onError) onError(error);
        else console.error('[MockApiClient]', error.message);
      }, 0);
      return () => clearTimeout(timer);
    }
    for (const e of rec.events) this.deliver(onEvent, e);
```

找到（10／12）：

```ts

  async cancelJob(jobId: string): Promise<void> {
    const rec = this.getJob(jobId);
    if (rec.finished) return;
```

改成：

```ts

  private summary(rec: JobRecord): JobSummary {
    return {
      id: rec.id, input: structuredClone(rec.input), createdAt: rec.createdAt, stage: rec.stage, round: rec.round,
      finished: rec.finished, bestRenderIds: { ...rec.bestRenderIds },
    };
  }

  async listJobs(): Promise<JobSummary[]> {
    return [...this.jobs.values()].reverse().map((rec) => this.summary(rec));
  }

  async getJob(jobId: string): Promise<JobSnapshot> {
    const rec = this.requireJob(jobId);
    return { summary: this.summary(rec), events: [...rec.events] };
  }

  async cancelJob(jobId: string): Promise<void> {
    const rec = this.requireJob(jobId);
    if (rec.finished) return;
```

找到（11／12）：

```ts
    return this.serial(async () => {
      const rec = this.getJob(jobId);
      const render = rec.renders.get(renderId);
```

改成：

```ts
    return this.serial(async () => {
      const rec = this.requireJob(jobId);
      const render = rec.renders.get(renderId);
```

找到（12／12）：

```ts
  }
}
```

改成：

```ts
  }

  setFavorite(historyId: string, favorite: boolean): Promise<HistoryEntry> {
    return this.serial(async () => {
      const history = (await this.store.get<HistoryEntry[]>(KEYS.history)) ?? [];
      const entry = history.find((h) => h.id === historyId);
      if (!entry) throw new Error(`Unknown history entry: ${historyId}`);
      const updated = { ...entry, favorite };
      await this.store.set(KEYS.history, history.map((h) => (h.id === historyId ? updated : h)));
      return updated;
    });
  }
}
```

- [ ] **Step 6: 執行測試與型別檢查確認通過**

Run: `npm run test && npm run typecheck`
Expected: `client.test.ts` 20 個測試 PASS；全部 19 個測試檔、137 個測試 PASS；typecheck 無錯誤

- [ ] **Step 7: Commit**

```bash
git add web/src/types/contract.ts web/src/lib/api
git commit -m "feat: finalize ApiClient with job queries, connection state and favorites" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: 商品照上傳、去背示意與品牌文件切塊

**Files:**
- Create: `web/src/lib/rag/chunk.ts`
- Modify: `web/src/types/contract.ts`、`web/src/lib/api/mock/data/products.ts`、`web/src/lib/api/client.ts`、`web/src/lib/api/mock/client.ts`
- Test: `web/src/lib/rag/chunk.test.ts`、`web/src/lib/api/mock/client.test.ts`（修改）

**Interfaces:**
- Consumes：`hashString`、`mulberry32`（Plan 1）；`getBrandById`、`SAMPLE_PRODUCTS`（Plan 1）
- Produces：
  - 型別 `ProductCutout { model: string; url: string | null }`，`Product.cutout: ProductCutout | null`，`RagTag` 加 `'general'`，`BrandDocument { name; text }`，`IngestEvent`（`ingest.chunked`／`ingest.embedded`／`ingest.stored`）
  - `EMBED_DIMS = 1024`、`guessTag(text): RagTag`、`chunkDocument(brandId, doc, { maxChars? }): RagChunk[]`（切塊 id 格式 `${brandId}#doc-${hash}-${n}`）、`embedPreview(text, n = 6): number[]`
  - `ApiClient.uploadProductPhoto(file: Blob): Promise<ProductPhoto>`、`requestCutout(productId): Promise<Product>`、`ingestBrandDocument(brandId, doc, onEvent): Promise<RagChunk[]>`
  - `listBrands()` 會附上使用者上傳文件產生的切塊。同名文件重新上傳時取代舊切塊。

- [ ] **Step 1: 修改 `web/src/types/contract.ts`**

找到（1／4）：

```ts
/* ---------- 品牌與 RAG ---------- */
export type RagTag = 'color' | 'logo' | 'law' | 'layout' | 'font' | 'history';
export interface RagChunk { id: string; source: string; section: string; tag: RagTag; text: string }
```

改成：

```ts
/* ---------- 品牌與 RAG ---------- */
/** general：使用者上傳、無法歸類的文件切塊 */
export type RagTag = 'color' | 'logo' | 'law' | 'layout' | 'font' | 'history' | 'general';
export interface RagChunk { id: string; source: string; section: string; tag: RagTag; text: string }
```

找到（2／4）：

```ts

export interface Product {
```

改成：

```ts

/** 去背結果。url 為 null 代表示意：mock 不真的去背，合成時以「色彩增值」讓白底融入背景 */
export interface ProductCutout { model: string; url: string | null }

export interface Product {
```

找到（3／4）：

```ts
  photo: ProductPhoto;
  createdAt: string;
```

改成：

```ts
  photo: ProductPhoto;
  /** 尚未去背為 null；示範商品是向量素材，不需要去背 */
  cutout: ProductCutout | null;
  createdAt: string;
```

找到（4／4）：

```ts

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';
```

改成：

```ts

/* ---------- 品牌文件上傳（chunking → embedding → 寫入 Chroma） ---------- */
export interface BrandDocument { name: string; text: string }
export type IngestEvent =
  | { type: 'ingest.chunked'; source: string; chunks: RagChunk[] }
  | { type: 'ingest.embedded'; chunkId: string; index: number; total: number; dims: number; preview: number[] }
  | { type: 'ingest.stored'; collection: string; count: number };

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';
```

- [ ] **Step 2: 修改 `web/src/lib/api/mock/data/products.ts`**

找到（1／2）：

```ts
    price: { sale: 1280, original: 1680 }, photo: { source: 'sample', art: 'serum' },
    createdAt: '2026-10-01T09:00:00.000Z',
```

改成：

```ts
    price: { sale: 1280, original: 1680 }, photo: { source: 'sample', art: 'serum' },
    cutout: null,
    createdAt: '2026-10-01T09:00:00.000Z',
```

找到（2／2）：

```ts
    price: { sale: 120, original: 150 }, photo: { source: 'sample', art: 'coldbrew' },
    createdAt: '2026-10-01T09:00:00.000Z',
```

改成：

```ts
    price: { sale: 120, original: 150 }, photo: { source: 'sample', art: 'coldbrew' },
    cutout: null,
    createdAt: '2026-10-01T09:00:00.000Z',
```

- [ ] **Step 3: 寫失敗測試 `web/src/lib/rag/chunk.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import { chunkDocument, embedPreview, guessTag, EMBED_DIMS } from './chunk';

const DOC = {
  name: 'ci_update_2026.md',
  text: [
    '# 色彩更新',
    '主色維持 #B76E79，新增輔助色「霧粉」#E8C7C8。',
    '',
    '# Logo 規範',
    '- Logo 淨空區至少 0.5 倍 Logo 高度',
    '- 深色背景使用反白 Logo',
    '',
    '週年慶素材的平均 CTR 為 4.2%。',
  ].join('\n'),
};

describe('chunkDocument', () => {
  it('splits by heading and paragraph, keeping the latest heading as the section', () => {
    const chunks = chunkDocument('selune', DOC);
    expect(chunks.map((c) => c.section)).toEqual(['色彩更新', 'Logo 規範', 'Logo 規範']);
    expect(chunks[1].text).toBe('Logo 淨空區至少 0.5 倍 Logo 高度。深色背景使用反白 Logo。');
    expect(chunks.every((c) => c.source === 'ci_update_2026.md')).toBe(true);
  });

  it('joins wrapped lines without adding spaces between Chinese characters', () => {
    const text = '標題靠左\n對齊網格。\nLogo\n置於左上。';
    expect(chunkDocument('selune', { name: 'a.txt', text })[0].text).toBe('標題靠左對齊網格。Logo 置於左上。');
  });

  it('uses the file name as the section before any heading', () => {
    expect(chunkDocument('selune', { name: '規範.txt', text: '標題最多兩行。' })[0].section).toBe('規範');
  });

  it('tags chunks by keywords', () => {
    expect(chunkDocument('selune', DOC).map((c) => c.tag)).toEqual(['color', 'logo', 'history']);
  });

  it('packs sentences into chunks no longer than maxChars', () => {
    const text = '第一句話很短。第二句話也很短。第三句話一樣很短。';
    const chunks = chunkDocument('selune', { name: 'a.txt', text }, { maxChars: 16 });
    expect(chunks.map((c) => c.text)).toEqual(['第一句話很短。第二句話也很短。', '第三句話一樣很短。']);
    const long = chunkDocument('selune', { name: 'b.txt', text: '字'.repeat(40) }, { maxChars: 16 });
    expect(long.map((c) => [...c.text].length)).toEqual([16, 16, 8]);
  });

  it('gives stable ids that are unique per document', () => {
    const a = chunkDocument('selune', DOC);
    expect(chunkDocument('selune', DOC).map((c) => c.id)).toEqual(a.map((c) => c.id));
    expect(new Set(a.map((c) => c.id)).size).toBe(a.length);
    expect(a[0].id).toMatch(/^selune#doc-[0-9a-z]+-1$/);
    expect(chunkDocument('selune', { ...DOC, name: 'other.md' })[0].id).not.toBe(a[0].id);
  });

  it('returns no chunks for blank text', () => {
    expect(chunkDocument('selune', { name: 'empty.txt', text: ' \n\n ' })).toEqual([]);
  });
});

describe('guessTag', () => {
  it('falls back to general', () => {
    expect(guessTag('禁止宣稱療效')).toBe('law');
    expect(guessTag('標題使用思源宋體字型')).toBe('font');
    expect(guessTag('商品主體置中，留白 40%')).toBe('layout');
    expect(guessTag('門市營業時間')).toBe('general');
  });
});

describe('embedPreview', () => {
  it('is deterministic and bounded', () => {
    const v = embedPreview('品牌主色');
    expect(v).toEqual(embedPreview('品牌主色'));
    expect(v).toHaveLength(6);
    for (const x of v) expect(Math.abs(x)).toBeLessThanOrEqual(1);
    expect(embedPreview('另一段文字')).not.toEqual(v);
    expect(EMBED_DIMS).toBe(1024);
  });
});
```

- [ ] **Step 4: 執行測試確認失敗**

Run: `npx vitest run src/lib/rag`
Expected: FAIL，找不到 `./chunk`

- [ ] **Step 5: 實作 `web/src/lib/rag/chunk.ts`**

```ts
import type { BrandDocument, RagChunk, RagTag } from '@/types/contract';
import { hashString, mulberry32 } from '@/lib/core/num';

/** bge-m3 的向量維度 */
export const EMBED_DIMS = 1024;

/** 依序比對，第一個命中的規則決定標籤 */
const TAG_RULES: [RegExp, RagTag][] = [
  [/禁用|法規|宣稱|療效|誇大|廣告|§/, 'law'],
  [/色彩|主色|輔助色|點綴色|色票|色差|ΔE|#[0-9a-fA-F]{6}/, 'color'],
  [/logo|標誌|淨空/i, 'logo'],
  [/字型|字體|字重|font/i, 'font'],
  [/版型|版面|留白|網格|構圖|佔比/, 'layout'],
  [/成效|CTR|點擊|互動|案例/i, 'history'],
];

export function guessTag(text: string): RagTag {
  return TAG_RULES.find(([re]) => re.test(text))?.[1] ?? 'general';
}

/** 先看內文，內文無法判斷時再看段落標題 */
const tagOf = (section: string, text: string): RagTag => {
  const tag = guessTag(text);
  return tag === 'general' ? guessTag(section) : tag;
};

/** 兩個漢字之間的空白（合併多行時產生）要拿掉 */
const CJK_GAP = /(\p{Script=Han})\s+(?=\p{Script=Han})/gu;

/** 依句號等標點切句，再把句子裝進不超過 maxChars 的塊；單句過長時硬切 */
function pack(text: string, maxChars: number): string[] {
  const sentences = text.match(/[^。！？!?；;]+[。！？!?；;]?/g) ?? [];
  const out: string[] = [];
  let cur = '';
  for (const raw of sentences) {
    const s = raw.trim();
    if (!s) continue;
    if ([...cur].length + [...s].length <= maxChars) {
      cur += s;
      continue;
    }
    if (cur) out.push(cur);
    const chars = [...s];
    for (let i = 0; i + maxChars < chars.length; i += maxChars) out.push(chars.slice(i, i + maxChars).join(''));
    cur = chars.slice(Math.floor((chars.length - 1) / maxChars) * maxChars).join('');
  }
  if (cur) out.push(cur);
  return out;
}

/**
 * 把品牌文件切成 RAG 切塊：Markdown 標題（#）成為之後段落的 section，空行分段，
 * 段落再依句子裝塊。第二階段改由後端切塊，輸出格式不變。
 */
export function chunkDocument(brandId: string, doc: BrandDocument, { maxChars = 180 } = {}): RagChunk[] {
  const docKey = hashString(doc.name).toString(36);
  let section = doc.name.replace(/\.[^.]+$/, '');
  const pieces: { section: string; text: string }[] = [];
  const flush = (lines: string[]) => {
    const text = lines.join(' ').replace(/\s+/g, ' ').replace(CJK_GAP, '$1').trim();
    for (const t of pack(text, maxChars)) pieces.push({ section, text: t });
    lines.length = 0;
  };

  for (const block of doc.text.replace(/\r\n?/g, '\n').split(/\n\s*\n/)) {
    const body: string[] = [];
    for (const line of block.split('\n').map((l) => l.trim()).filter(Boolean)) {
      const heading = line.match(/^#{1,6}\s+(.+)$/);
      if (heading) {
        flush(body);
        section = heading[1].trim();
      } else {
        const bullet = line.match(/^[-*•]\s+(.+)$/);
        // 條列項目各自成句，避免合併後黏在一起
        body.push(bullet ? bullet[1].replace(/([^。！？!?；;])$/, '$1。') : line);
      }
    }
    flush(body);
  }

  return pieces.map((p, i) => ({
    id: `${brandId}#doc-${docKey}-${i + 1}`,
    source: doc.name,
    section: p.section,
    tag: tagOf(p.section, p.text),
    text: p.text,
  }));
}

/** 模擬向量的前幾維（第二階段由 bge-m3 產生真實向量） */
export function embedPreview(text: string, n = 6): number[] {
  const rng = mulberry32(hashString(text));
  return Array.from({ length: n }, () => Math.round((rng() * 2 - 1) * 1000) / 1000);
}
```

- [ ] **Step 6: 執行測試確認通過**

Run: `npx vitest run src/lib/rag`
Expected: 9 個測試 PASS

- [ ] **Step 7: 修改 `web/src/lib/api/mock/client.test.ts`**（先寫失敗測試；既有的草稿商品補上 `cutout: null`）

找到（1／3）：

```ts
      brandId: 'selune', name: '晚安面膜', features: ['保濕'], price: { sale: 680, original: 880 },
      photo: { source: 'upload', url: 'blob:test' },
    });
```

改成：

```ts
      brandId: 'selune', name: '晚安面膜', features: ['保濕'], price: { sale: 680, original: 880 },
      photo: { source: 'upload', url: 'blob:test' }, cutout: null,
    });
```

找到（2／3）：

```ts
    expect(await api.listProducts('misty-isle')).toHaveLength(1);
  });
```

改成：

```ts
    expect(await api.listProducts('misty-isle')).toHaveLength(1);
  });
});

describe('product photos and cutout', () => {
  it('turns an uploaded image into a data URL photo', async () => {
    const api = new MockApiClient();
    const photo = await api.uploadProductPhoto(new Blob([new Uint8Array([1, 2, 3])], { type: 'image/png' }));
    expect(photo).toEqual({ source: 'upload', url: 'data:image/png;base64,AQID' });
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
    expect(product.cutout).toEqual({ model: 'BiRefNet-general', url: null });
    expect(product.createdAt).toBe(saved.createdAt);
    expect((await api.listProducts('selune')).find((p) => p.id === saved.id)?.cutout).not.toBeNull();
    await expect(api.requestCutout('prod_selune_serum')).rejects.toThrow('示範商品已是去背素材');
  });
});

describe('brand documents', () => {
  const DOC = { name: 'ci_update.md', text: ['# 色彩更新', '新增輔助色「霧粉」#E8C7C8。', '', '# Logo', '深色背景使用反白 Logo。'].join('\n') };

  it('reports chunking, embedding and storing, then lists the new chunks on the brand', async () => {
    const api = new MockApiClient();
    const seen: string[] = [];
    const pending = api.ingestBrandDocument('selune', DOC, (e) => seen.push(e.type));
    await vi.advanceTimersByTimeAsync(1_300);
    const chunks = await pending;
    expect(seen).toEqual(['ingest.chunked', 'ingest.embedded', 'ingest.embedded', 'ingest.stored']);
    expect(chunks.map((c) => c.tag)).toEqual(['color', 'logo']);
    const selune = (await api.listBrands()).find((b) => b.id === 'selune')!;
    expect(selune.guidelineChunks.slice(-2).map((c) => c.id)).toEqual(chunks.map((c) => c.id));
    expect((await api.listBrands()).find((b) => b.id === 'misty-isle')!.guidelineChunks).toHaveLength(7);
  });

  it('replaces chunks when the same document is uploaded again', async () => {
    const api = new MockApiClient();
    api.demo.set({ speed: 4 });
    const first = api.ingestBrandDocument('selune', DOC, () => {});
    await vi.advanceTimersByTimeAsync(400);
    await first;
    const second = api.ingestBrandDocument('selune', { ...DOC, text: '只剩一段。' }, () => {});
    await vi.advanceTimersByTimeAsync(400);
    await second;
    const selune = (await api.listBrands()).find((b) => b.id === 'selune')!;
    expect(selune.guidelineChunks.filter((c) => c.source === 'ci_update.md').map((c) => c.text)).toEqual(['只剩一段。']);
  });

  it('rejects documents without text', async () => {
    const api = new MockApiClient();
    await expect(api.ingestBrandDocument('selune', { name: 'a.txt', text: '  ' }, () => {})).rejects.toThrow('文件沒有可用的文字內容');
  });
```

找到（3／3）：

```ts
      brandId: 'selune', name, features: [], price: { sale: 1, original: 1 }, photo: { source: 'upload' as const, url: 'blob:x' },
    });
```

改成：

```ts
      brandId: 'selune', name, features: [], price: { sale: 1, original: 1 }, photo: { source: 'upload' as const, url: 'blob:x' },
      cutout: null,
    });
```

- [ ] **Step 8: 執行測試確認失敗**

Run: `npx vitest run src/lib/api/mock/client.test.ts`
Expected: FAIL，`api.uploadProductPhoto is not a function` 等

- [ ] **Step 9: 取代 `web/src/lib/api/client.ts`**

```ts
import type {
  Brand, BrandDocument, ChannelTemplate, ConnectionState, Copy, DemoOptions, HistoryEntry, IngestEvent, JobEvent, JobInput,
  JobSummary, ParsedBrief, Product, ProductPhoto, RagChunk,
} from '@/types/contract';

export type ProductDraft = Omit<Product, 'id' | 'createdAt'> & { id?: string };

export interface DemoControls {
  get(): DemoOptions;
  set(patch: Partial<DemoOptions>): void;
}

export interface ConnectionChannel {
  /** 狀態沒變時回傳同一個物件（可直接給 useSyncExternalStore 使用） */
  get(): ConnectionState;
  /** 狀態改變時通知；回傳取消訂閱的函式 */
  subscribe(listener: (state: ConnectionState) => void): () => void;
}

export interface JobSnapshot { summary: JobSummary; events: JobEvent[] }

/** UI 只依賴這個介面：第一階段由 MockApiClient 實作，第二階段由連線 FastAPI 的 HttpApiClient 實作 */
export interface ApiClient {
  /** 只有 mock 模式有 Demo 控制台；live 模式為 null */
  readonly demo: DemoControls | null;
  readonly connection: ConnectionChannel;
  /** 包含使用者上傳文件產生的切塊 */
  listBrands(): Promise<Brand[]>;
  /** 上傳品牌文件：切塊 → 向量化 → 寫入知識庫，過程以 onEvent 回報；回傳新增的切塊 */
  ingestBrandDocument(brandId: string, doc: BrandDocument, onEvent: (e: IngestEvent) => void): Promise<RagChunk[]>;
  listTemplates(): Promise<ChannelTemplate[]>;
  listProducts(brandId: string): Promise<Product[]>;
  saveProduct(draft: ProductDraft): Promise<Product>;
  deleteProduct(id: string): Promise<void>;
  /** 上傳商品照，回傳可放進 Product.photo 的參照（mock：轉成 data URL 存在本機；live：上傳到後端） */
  uploadProductPhoto(file: Blob): Promise<ProductPhoto>;
  /** 對商品照去背並寫回 Product.cutout（mock：示意，約 1.2 秒） */
  requestCutout(productId: string): Promise<Product>;
  parseBrief(brandId: string, text: string, productId: string | null): Promise<ParsedBrief>;
  createJob(input: JobInput): Promise<{ jobId: string }>;
  /**
   * 先重播已發生的事件，再接收即時事件；回傳取消訂閱的函式。
   * 任務不存在或連線中斷時以 onError 非同步回報，不丟出例外（與 WebSocket 的行為一致）。
   */
  subscribe(jobId: string, onEvent: (event: JobEvent) => void, onError?: (error: Error) => void): () => void;
  cancelJob(jobId: string): Promise<void>;
  /** 最新的任務在前 */
  listJobs(): Promise<JobSummary[]>;
  getJob(jobId: string): Promise<JobSnapshot>;
  selectRender(jobId: string, renderId: string, copy: Copy): Promise<HistoryEntry>;
  listHistory(brandId?: string): Promise<HistoryEntry[]>;
  setFavorite(historyId: string, favorite: boolean): Promise<HistoryEntry>;
}
```

- [ ] **Step 10: 修改 `web/src/lib/api/mock/client.ts`**

找到（1／6）：

```ts
import type {
  ConnectionState, Copy, DemoOptions, HistoryEntry, JobEvent, JobInput, JobStage, JobSummary, Product, Render, TemplateId,
} from '@/types/contract';
```

改成：

```ts
import type {
  BrandDocument, ConnectionState, Copy, DemoOptions, HistoryEntry, IngestEvent, JobEvent, JobInput, JobStage, JobSummary,
  Product, ProductPhoto, RagChunk, Render, TemplateId,
} from '@/types/contract';
```

找到（2／6）：

```ts
import { hashString } from '@/lib/core/num';
import { BRANDS, getBrandById, SAMPLE_PRODUCTS } from './data';
```

改成：

```ts
import { hashString } from '@/lib/core/num';
import { chunkDocument, EMBED_DIMS, embedPreview } from '@/lib/rag/chunk';
import { BRANDS, getBrandById, SAMPLE_PRODUCTS } from './data';
```

找到（3／6）：

```ts

const KEYS = { products: 'products', deleted: 'deletedSampleIds', history: 'history' } as const;
const pad = (n: number) => String(n).padStart(2, '0');
```

改成：

```ts

const KEYS = { products: 'products', deleted: 'deletedSampleIds', history: 'history', docChunks: 'docChunks' } as const;

/** Blob → data URL（mock 把上傳的照片直接存在本機） */
async function toDataUrl(file: Blob): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return `data:${file.type};base64,${btoa(binary)}`;
}
const pad = (n: number) => String(n).padStart(2, '0');
```

找到（4／6）：

```ts

  async listBrands() { return BRANDS; }
```

改成：

```ts

  /** 等待 ms（1× 速度），依 Demo 播放速度縮短 */
  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms / this.options.speed));
  }

  /** 示範品牌 + 使用者上傳文件產生的切塊 */
  async listBrands() {
    const uploaded = (await this.store.get<Record<string, RagChunk[]>>(KEYS.docChunks)) ?? {};
    return BRANDS.map((b) => (uploaded[b.id]?.length ? { ...b, guidelineChunks: [...b.guidelineChunks, ...uploaded[b.id]] } : b));
  }
```

找到（5／6）：

```ts
    return p;
  }
```

改成：

```ts
    return p;
  }

  async uploadProductPhoto(file: Blob): Promise<ProductPhoto> {
    if (!file.type.startsWith('image/')) throw new Error('只能上傳圖片檔');
    return { source: 'upload', url: await toDataUrl(file) };
  }

  async requestCutout(productId: string): Promise<Product> {
    const product = await this.findProduct(productId);
    if (product.photo.source === 'sample') throw new Error('示範商品已是去背素材');
    await this.sleep(1200);
    return this.saveProduct({ ...product, cutout: { model: 'BiRefNet-general', url: null } });
  }

  async ingestBrandDocument(brandId: string, doc: BrandDocument, onEvent: (e: IngestEvent) => void): Promise<RagChunk[]> {
    getBrandById(brandId);
    const chunks = chunkDocument(brandId, doc);
    if (!chunks.length) throw new Error('文件沒有可用的文字內容');
    await this.sleep(400);
    this.deliver(onEvent, { type: 'ingest.chunked', source: doc.name, chunks: structuredClone(chunks) });
    for (const [index, c] of chunks.entries()) {
      await this.sleep(250);
      this.deliver(onEvent, {
        type: 'ingest.embedded', chunkId: c.id, index, total: chunks.length, dims: EMBED_DIMS, preview: embedPreview(c.text),
      });
    }
    await this.serial(async () => {
      const all = (await this.store.get<Record<string, RagChunk[]>>(KEYS.docChunks)) ?? {};
      // 同名文件重新上傳時取代舊的切塊
      const kept = (all[brandId] ?? []).filter((c) => c.source !== doc.name);
      await this.store.set(KEYS.docChunks, { ...all, [brandId]: [...kept, ...chunks] });
    });
    await this.sleep(300);
    this.deliver(onEvent, { type: 'ingest.stored', collection: `${brandId}_ci`, count: chunks.length });
    return chunks;
  }
```

找到（6／6）：

```ts
  /** 單一訂閱者出錯不可中斷整條事件流（與 WebSocket 各自處理訊息的行為一致）；即時推送與重播共用 */
  private deliver(listener: (e: JobEvent) => void, e: JobEvent) {
    try {
```

改成：

```ts
  /** 單一訂閱者出錯不可中斷整條事件流（與 WebSocket 各自處理訊息的行為一致）；即時推送與重播共用 */
  private deliver<E extends { type: string }>(listener: (e: E) => void, e: E) {
    try {
```

- [ ] **Step 11: 執行全部測試與型別檢查確認通過**

Run: `npm run test && npm run typecheck`
Expected: 20 個測試檔、151 個測試 PASS；typecheck 無錯誤

- [ ] **Step 12: Commit**

```bash
git add web/src/types/contract.ts web/src/lib/rag web/src/lib/api
git commit -m "feat: add product photo upload, simulated cutout and brand document ingest" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: IndexedDB 保存

**Files:**
- Create: `web/src/lib/api/mock/idb-store.ts`
- Modify: `web/src/lib/api/mock/store.ts`（註解）、`web/src/lib/api/index.ts`
- Test: `web/src/lib/api/mock/idb-store.test.ts`

**Interfaces:**
- Consumes：`KeyValueStore`、`MemoryStore`（Plan 1）
- Produces：`class IdbStore implements KeyValueStore`（建構子 `(dbName = 'genai-poster-agent', storeName = 'kv')`）；`API_MODE`（建置時內嵌的 `NEXT_PUBLIC_API_MODE`，預設 `mock`）；`getApiClient()` 在有 `indexedDB` 的環境使用 `IdbStore`

- [ ] **Step 1: 安裝套件**

```bash
npm i idb-keyval@^6.3.0
npm i -D fake-indexeddb@^6.2.5
```

- [ ] **Step 2: 寫失敗測試 `web/src/lib/api/mock/idb-store.test.ts`**

```ts
import 'fake-indexeddb/auto';
import { describe, it, expect } from 'vitest';
import { IdbStore } from './idb-store';

describe('IdbStore', () => {
  it('round-trips values and returns undefined for missing keys', async () => {
    const store = new IdbStore('test-db-1');
    expect(await store.get('missing')).toBeUndefined();
    await store.set('products', [{ id: 'p1', price: { sale: 1 } }]);
    expect(await store.get('products')).toEqual([{ id: 'p1', price: { sale: 1 } }]);
  });

  it('persists across instances that share a database name', async () => {
    await new IdbStore('test-db-2').set('history', ['h1']);
    expect(await new IdbStore('test-db-2').get('history')).toEqual(['h1']);
    expect(await new IdbStore('test-db-3').get('history')).toBeUndefined();
  });

  it('stores frozen objects and returns mutable copies', async () => {
    const store = new IdbStore('test-db-4');
    await store.set('k', Object.freeze({ a: 1 }));
    const v = await store.get<{ a: number }>('k');
    expect(Object.isFrozen(v)).toBe(false);
  });
});
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `npx vitest run src/lib/api/mock/idb-store.test.ts`
Expected: FAIL，找不到 `./idb-store`

- [ ] **Step 4: 實作 `web/src/lib/api/mock/idb-store.ts`**

```ts
import { createStore, get, set, type UseStore } from 'idb-keyval';
import type { KeyValueStore } from './store';

/** 瀏覽器版本：資料存在 IndexedDB，重新整理後仍在。只能在有 indexedDB 的環境建立。 */
export class IdbStore implements KeyValueStore {
  private readonly db: UseStore;

  constructor(dbName = 'genai-poster-agent', storeName = 'kv') {
    this.db = createStore(dbName, storeName);
  }

  get<T>(key: string): Promise<T | undefined> {
    return get<T>(key, this.db);
  }

  set<T>(key: string, value: T): Promise<void> {
    return set(key, value, this.db);
  }
}
```

- [ ] **Step 5: 修改 `web/src/lib/api/mock/store.ts`**

找到：

```ts

/** 記憶體版本（測試與預設使用）；Plan 2 會加入 IndexedDB 版本 */
export class MemoryStore implements KeyValueStore {
```

改成：

```ts

/** 記憶體版本（測試與沒有 IndexedDB 的環境使用）；瀏覽器使用 `IdbStore` */
export class MemoryStore implements KeyValueStore {
```

- [ ] **Step 6: 取代 `web/src/lib/api/index.ts`**

```ts
import type { ApiClient } from './client';
import { MockApiClient } from './mock/client';
import { IdbStore } from './mock/idb-store';
import { MemoryStore } from './mock/store';

export type { ApiClient, ConnectionChannel, DemoControls, JobSnapshot, ProductDraft } from './client';

/** 建置時由 Next 內嵌；伺服器與瀏覽器看到的值相同，可直接用於 render */
export const API_MODE = process.env.NEXT_PUBLIC_API_MODE || 'mock';

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

- [ ] **Step 7: 執行全部測試與型別檢查確認通過**

Run: `npm run test && npm run typecheck`
Expected: 21 個測試檔、154 個測試 PASS（`getApiClient` 測試在 Node 沒有 indexedDB，仍使用 `MemoryStore`）；typecheck 無錯誤

- [ ] **Step 8: Commit**

```bash
git add web/package.json web/package-lock.json web/src/lib/api
git commit -m "feat: persist mock data in IndexedDB" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: 任務事件 reducer（`JobView`）

**Files:**
- Create: `web/src/lib/jobs/view.ts`
- Test: `web/src/lib/jobs/view.test.ts`

**Interfaces:**
- Consumes：`JobEvent` 等型別（contract）；測試使用 `buildTimeline`、`parseBrief`（Plan 1）
- Produces：
  - `type JobOutcome = 'running' | 'done' | 'needs_review' | 'cancelled'`、`RewriteInfo`、`LogLine`、`RenderProgress`、`interface JobView`
  - `specKey(round, templateId)`、`STAGE_LABEL: Record<JobStage, string>`、`emptyJobView(jobId?)`
  - `reduceJob(view, event): JobView`：純函式，不修改輸入。`rag.retrieved` 在 `rewriting` 階段收到時算重新檢索。
  - `applyEvents(events, jobId?)`
  - `finalCandidates(view)`：每個模板最後一輪的候選，依 variant 排序
  - `defaultSelection(view)`：優先取 `bestRenderIds`，否則取分數最高的候選
  - `jobProgress(view)`：0–1，每輪從 Prompt 構建往前推進

- [ ] **Step 1: 寫失敗測試 `web/src/lib/jobs/view.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import type { DemoOptions, JobEvent, JobInput, TemplateId } from '@/types/contract';
import { getTemplate } from '@/lib/compose/templates';
import { SELUNE, SAMPLE_PRODUCTS } from '@/lib/api/mock/data';
import { parseBrief } from '@/lib/api/mock/brief';
import { buildTimeline } from '@/lib/api/mock/scenario';
import { applyEvents, defaultSelection, emptyJobView, finalCandidates, jobProgress, reduceJob, specKey } from './view';

const serum = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_selune_serum')!;
const BRIEF = '週年慶主打買一送一，溫柔療癒';

function events(demo: Partial<DemoOptions> = {}, input: Partial<JobInput> = {}): JobEvent[] {
  const templateIds: TemplateId[] = input.templateIds ?? ['ig-post', 'story'];
  return buildTimeline({
    jobId: 'job_v', seed: 11, brand: SELUNE, product: serum, templates: templateIds.map(getTemplate),
    demo: { speed: 1, firstRoundFail: true, forceAllFail: false, ...demo },
    input: {
      brandId: 'selune', productId: serum.id, brief: BRIEF, parsedBrief: parseBrief(BRIEF, SELUNE, serum), templateIds,
      variantsPerTemplate: 4, llm: 'Gemini 3.7 Flash', engine: 'comfyui', vlm: 'Gemini 3.7 Vision', maxRetries: 2, ...input,
    },
  }).map((x) => x.event);
}

describe('reduceJob (default demo: fail → rewrite → pass)', () => {
  const evs = events();
  const v = applyEvents(evs);

  it('ends done in round 2 with one rewrite per template', () => {
    expect(v).toMatchObject({ jobId: 'job_v', stage: 'done', round: 2, outcome: 'done', needsReviewReason: null });
    expect(v.rewrites.map((r) => r.templateId)).toEqual(['ig-post', 'story']);
    expect(v.rewrites[0].fixes.length).toBeGreaterThan(0);
  });

  it('keeps reranked hits and the re-query hit separately', () => {
    expect(v.ragHits).toHaveLength(5);
    expect(v.ragHits.every((h) => h.rerankScore !== undefined)).toBe(true);
    expect(v.requeryHits.map((h) => h.chunkId)).toEqual(['selune#law-alt']);
  });

  it('accumulates checks and scores onto renders', () => {
    expect(v.renderIds).toHaveLength(16);
    for (const id of v.renderIds) {
      expect(v.renders[id].checks).toHaveLength(10);
      expect(v.renders[id].score).not.toBeNull();
    }
    expect(v.specs[specKey(2, 'story')].round).toBe(2);
  });

  it('shows only the final round as candidates and selects the best render', () => {
    const c = finalCandidates(v);
    expect(c['ig-post']!.map((r) => [r.round, r.variant])).toEqual([[2, 0], [2, 1], [2, 2], [2, 3]]);
    expect(defaultSelection(v)).toEqual(v.bestRenderIds);
  });

  it('collects log lines', () => {
    expect(v.logs.length).toBe(evs.filter((e) => e.type === 'log').length);
  });

  it('never mutates the previous view', () => {
    const before = emptyJobView();
    const after = reduceJob(before, { type: 'job.status', stage: 'parsing', round: 0 });
    expect(before.stage).toBeNull();
    expect(after.stage).toBe('parsing');
  });
});

describe('needs review and cancel', () => {
  it('falls back to the highest score when no render passed', () => {
    const v = applyEvents(events({ forceAllFail: true }, { maxRetries: 1, templateIds: ['ig-post'] }));
    expect(v.outcome).toBe('needs_review');
    expect(v.needsReviewReason).toContain('最大重試次數');
    expect(v.bestRenderIds).toEqual({});
    const candidates = finalCandidates(v)['ig-post']!;
    const top = [...candidates].sort((a, b) => b.score! - a.score!)[0];
    expect(defaultSelection(v)['ig-post']).toBe(top.id);
  });

  it('marks a cancelled job', () => {
    const v = reduceJob(emptyJobView('j'), { type: 'job.status', stage: 'cancelled', round: 1 });
    expect(v.outcome).toBe('cancelled');
  });
});

describe('jobProgress', () => {
  it('starts at 0, ends at 1 and never moves backwards within a round', () => {
    const evs = events({}, { templateIds: ['ig-post'] });
    let v = emptyJobView();
    expect(jobProgress(v)).toBe(0);
    let last = 0;
    for (const e of evs) {
      v = reduceJob(v, e);
      if (v.stage === 'rewriting' || v.round === 2) break;
      const p = jobProgress(v);
      expect(p).toBeGreaterThanOrEqual(last);
      last = p;
    }
    expect(last).toBeGreaterThan(0.9);
    expect(jobProgress(applyEvents(evs))).toBe(1);
  });

  it('moves through the rendering range as ComfyUI steps arrive', () => {
    const evs = events({}, { templateIds: ['ig-post'] });
    const firstGenerate = evs.findIndex((e) => e.type === 'render.progress' && e.node === 'generate');
    const p = jobProgress(applyEvents(evs.slice(0, firstGenerate + 1)));
    expect(p).toBeGreaterThan(0.2);
    expect(p).toBeLessThan(0.7);
  });
});
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `npx vitest run src/lib/jobs`
Expected: FAIL，找不到 `./view`

- [ ] **Step 3: 實作 `web/src/lib/jobs/view.ts`**

```ts
import type {
  CheckId, Fix, JobEvent, JobStage, LogLevel, LogSource, ParsedBrief, PromptSpec, RagHit, Render, RenderNode, TemplateId,
} from '@/types/contract';

export type JobOutcome = 'running' | 'done' | 'needs_review' | 'cancelled';
export interface RewriteInfo { round: number; templateId: TemplateId; reasons: CheckId[]; fixes: Fix[]; requery: boolean }
export interface LogLine { source: LogSource; level: LogLevel; message: string }
export interface RenderProgress { round: number; node: RenderNode; step: number; maxStep: number }

/** 由事件串流累積出來的任務畫面狀態。mock 與 live 共用（UI 只看事件，不看實作）。 */
export interface JobView {
  jobId: string | null;
  stage: JobStage | null;
  round: number;
  outcome: JobOutcome;
  parsedBrief: ParsedBrief | null;
  /** 第一次檢索的結果（Rerank 後會帶 rerankScore） */
  ragHits: RagHit[];
  /** Query Rewriting 時重新檢索到的切塊 */
  requeryHits: RagHit[];
  /** key 為 specKey(round, templateId) */
  specs: Record<string, PromptSpec>;
  renders: Record<string, Render>;
  /** 依收到的順序 */
  renderIds: string[];
  progress: RenderProgress | null;
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
  rendering: 'ComfyUI 生成',
  composing: '文字排版',
  reviewing: '合規審查',
  rewriting: 'Query Rewriting',
  saving: '寫入資料庫',
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
  switch (e.type) {
    case 'job.accepted':
      return { ...v, jobId: e.jobId };
    case 'job.status':
      return { ...v, stage: e.stage, round: e.round, outcome: OUTCOME[e.stage] ?? v.outcome };
    case 'brief.parsed':
      return { ...v, parsedBrief: e.parsedBrief };
    case 'rag.retrieved':
      return v.stage === 'rewriting' ? { ...v, requeryHits: [...v.requeryHits, ...e.hits] } : { ...v, ragHits: e.hits };
    case 'rag.reranked':
      return { ...v, ragHits: e.hits };
    case 'prompt.generated':
      return { ...v, specs: { ...v.specs, [specKey(e.round, e.templateId)]: e.spec } };
    case 'comfy.queued':
      return v;
    case 'render.progress':
      return { ...v, progress: { round: e.round, node: e.node, step: e.step, maxStep: e.maxStep } };
    case 'render.completed': {
      const renders = { ...v.renders };
      for (const r of e.renders) renders[r.id] = r;
      return { ...v, renders, renderIds: [...v.renderIds, ...e.renders.map((r) => r.id).filter((id) => !v.renders[id])] };
    }
    case 'review.check': {
      const r = v.renders[e.renderId];
      return r ? { ...v, renders: { ...v.renders, [r.id]: { ...r, checks: [...r.checks, e.check] } } } : v;
    }
    case 'review.completed': {
      const r = v.renders[e.renderId];
      return r ? { ...v, renders: { ...v.renders, [r.id]: { ...r, score: e.score, passed: e.passed } } } : v;
    }
    case 'rewrite.started':
      return {
        ...v,
        rewrites: [...v.rewrites, { round: e.round, templateId: e.templateId, reasons: e.reasons, fixes: e.fixes, requery: e.requery }],
      };
    case 'job.completed':
      return { ...v, bestRenderIds: e.bestRenderIds };
    case 'job.needs_review':
      return { ...v, needsReviewReason: e.reason };
    case 'log':
      return { ...v, logs: [...v.logs, { source: e.source, level: e.level, message: e.message }] };
  }
}

export const applyEvents = (events: JobEvent[], jobId: string | null = null): JobView =>
  events.reduce(reduceJob, emptyJobView(jobId));

/** 每個模板最後一輪的候選（依 variant 排序）；結果牆只顯示這些 */
export function finalCandidates(v: JobView): Partial<Record<TemplateId, Render[]>> {
  const out: Partial<Record<TemplateId, Render[]>> = {};
  for (const id of v.renderIds) {
    const r = v.renders[id];
    const list = out[r.templateId];
    if (!list || list[0].round < r.round) out[r.templateId] = [r];
    else if (list[0].round === r.round) list.push(r);
  }
  for (const list of Object.values(out)) list.sort((a, b) => a.variant - b.variant);
  return out;
}

/** 預設選擇：任務的最佳候選優先；需人工審核時取最後一輪分數最高的 */
export function defaultSelection(v: JobView): Partial<Record<TemplateId, string>> {
  const out: Partial<Record<TemplateId, string>> = {};
  for (const [templateId, list] of Object.entries(finalCandidates(v)) as [TemplateId, Render[]][]) {
    const best = v.bestRenderIds[templateId];
    out[templateId] = best ?? [...list].sort((a, b) => (b.score ?? -1) - (a.score ?? -1))[0].id;
  }
  return out;
}

/** ComfyUI 各節點在一輪生成中所佔的比例（依 1× 時間：400／2000／500／300 ms） */
const NODE_SPAN: Record<RenderNode, [start: number, span: number]> = {
  cutout: [0, 0.125],
  generate: [0.125, 0.625],
  relight: [0.75, 0.156],
  upscale: [0.906, 0.094],
};

/** 精簡進度條用的 0–1 進度。重試時每一輪會從 Prompt 構建重新往前推。 */
export function jobProgress(v: JobView): number {
  if (v.outcome === 'done' || v.outcome === 'needs_review') return 1;
  switch (v.stage) {
    case null: return 0;
    case 'parsing': return 0.04;
    case 'retrieving': return 0.1;
    case 'prompting': return 0.16;
    case 'rendering': {
      const p = v.progress && v.progress.round === v.round ? v.progress : null;
      const frac = p ? NODE_SPAN[p.node][0] + (NODE_SPAN[p.node][1] * p.step) / p.maxStep : 0;
      return 0.2 + 0.5 * frac;
    }
    case 'composing': return 0.72;
    case 'reviewing': {
      const current = v.renderIds.map((id) => v.renders[id]).filter((r) => r.round === v.round);
      const reviewed = current.filter((r) => r.score !== null).length;
      return 0.74 + (0.18 * reviewed) / Math.max(1, current.length);
    }
    case 'rewriting': return 0.93;
    case 'saving': return 0.97;
    default: return 1;
  }
}
```

- [ ] **Step 4: 執行測試確認通過**

Run: `npx vitest run src/lib/jobs`
Expected: 10 個測試 PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/jobs
git commit -m "feat: add job event reducer for the UI" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: 排版引擎繪製指令 `composePoster`

**Files:**
- Create: `web/src/lib/compose/scene.ts`
- Test: `web/src/lib/compose/scene.test.ts`

**Interfaces:**
- Consumes：`boxMap`、`fitFontSize`（Plan 1）；`visLen`（Plan 1）；`mixHex`（Plan 1）；測試使用 `cleanSpec`（Plan 1 fixture）
- Produces：
  - 型別 `FontRole`、`LogoMark`、`TextOp`（`y` 為文字垂直中心）、`PillOp`、`BadgeOp`、`LogoOp`、`ProductOp`、`SceneOp`、`PosterScene`、`SceneInput`
  - `composePoster(input: SceneInput): PosterScene`：繪製順序是背景、商品、Logo、文字，徽章最後。字級依框自動縮放，放不下的賣點膠囊不畫，空欄位不畫。
  - `logoFor(brand)`：已知品牌回傳專屬標誌；字標取品牌名稱中的拉丁字，沒有就用全名。
  - `formatPrice(n)`
  - `textBounds(op)`：以 visLen 估算的外框

- [ ] **Step 1: 寫失敗測試 `web/src/lib/compose/scene.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import type { Copy, LayoutElementId, PromptSpec } from '@/types/contract';
import { CHANNEL_TEMPLATES } from './templates';
import { boxMap } from './layout';
import {
  composePoster, formatPrice, logoFor, textBounds, type BadgeOp, type LogoOp, type PillOp, type SceneInput, type TextOp,
} from './scene';
import { cleanSpec } from '@/test/fixtures';
import { SELUNE } from '@/lib/api/mock/data';

const sceneInput = (spec: PromptSpec, copy: Partial<Copy> = {}): SceneInput => ({
  canvas: spec.canvas, layout: spec.layout, palette: spec.palette, copy: { ...spec.copy, ...copy }, brand: SELUNE,
});
const texts = (ops: ReturnType<typeof composePoster>['ops']) => ops.filter((o): o is TextOp => o.kind === 'text');
const inside = (r: { x: number; y: number; w: number; h: number }, box: { x: number; y: number; w: number; h: number }) =>
  r.x >= box.x - 0.5 && r.y >= box.y - 0.5 && r.x + r.w <= box.x + box.w + 0.5 && r.y + r.h <= box.y + box.h + 0.5;

describe.each(CHANNEL_TEMPLATES)('composePoster($id)', (t) => {
  const spec = cleanSpec(SELUNE, undefined, t.id);
  const B = boxMap(spec.layout);
  const scene = composePoster(sceneInput(spec));

  it('keeps every text inside its layout box', () => {
    for (const op of texts(scene.ops)) expect(inside(textBounds(op), B[op.el]), `${op.el}: ${op.text}`).toBe(true);
    const logo = scene.ops.find((o): o is LogoOp => o.kind === 'logo')!;
    expect(inside(textBounds(logo.wordmark!), B.logo)).toBe(true);
  });

  it('keeps badge texts inside the badge circle', () => {
    const badge = scene.ops.find((o): o is BadgeOp => o.kind === 'badge')!;
    for (const op of badge.texts) {
      const b = textBounds(op);
      expect(Math.abs(b.x + b.w / 2 - badge.cx)).toBeLessThan(0.01);
      expect(b.w / 2).toBeLessThanOrEqual(badge.r * 0.75);
      expect(Math.abs(op.y - badge.cy) + op.size / 2).toBeLessThanOrEqual(badge.r * 0.75);
    }
  });

  it('keeps feature pills inside the features box', () => {
    const pills = scene.ops.filter((o): o is PillOp => o.kind === 'pill' && o.el === 'features');
    expect(pills.length).toBeGreaterThan(0);
    for (const p of pills) expect(inside(p.rect, B.features)).toBe(true);
  });

  it('draws the background first, the product second and the badge last', () => {
    expect(scene.ops[0].kind).toBe('background');
    expect(scene.ops[1].kind).toBe('product');
    expect(scene.ops.at(-1)!.kind).toBe('badge');
    expect(scene).toMatchObject({ width: t.width, height: t.height });
  });
});

describe('composePoster with edited copy', () => {
  const spec = cleanSpec();
  const B = boxMap(spec.layout);

  it('shrinks a long headline so it still fits', () => {
    const base = texts(composePoster(sceneInput(spec)).ops).find((o) => o.el === 'headline')!;
    const long = texts(composePoster(sceneInput(spec, { headline: ['這是一個非常非常非常長的標題', '第二行'] })).ops)
      .filter((o) => o.el === 'headline');
    expect(long[0].size).toBeLessThan(base.size);
    for (const op of long) expect(inside(textBounds(op), B.headline)).toBe(true);
  });

  it('shows the edited price with thousands separators', () => {
    const ops = texts(composePoster(sceneInput(spec, { price: { ...spec.copy.price, sale: 12800 } })).ops);
    expect(ops.map((o) => o.text)).toContain('12,800');
    expect(ops.map((o) => o.text)).toContain('NT$');
  });

  it('skips empty optional fields', () => {
    const scene = composePoster(sceneInput(spec, {
      subhead: '', features: [], disclaimer: '', badge: { top: '', main: '', sub: '' },
      price: { label: '', sale: 100, original: 100 }, headline: ['只有一行', ''],
    }));
    const els = new Set<LayoutElementId>(texts(scene.ops).map((o) => o.el));
    expect(els.has('subhead') || els.has('features') || els.has('disclaimer')).toBe(false);
    expect(scene.ops.some((o) => o.kind === 'badge')).toBe(false);
    expect(texts(scene.ops).filter((o) => o.el === 'headline')).toHaveLength(1);
    expect(texts(scene.ops).some((o) => o.strike)).toBe(false);
  });

  it('drops feature pills that do not fit', () => {
    const many = ['超長的賣點文字一號', '超長的賣點文字二號', '超長的賣點文字三號', '超長的賣點文字四號'];
    const pills = composePoster(sceneInput(spec, { features: many })).ops.filter((o) => o.kind === 'pill' && o.el === 'features');
    expect(pills.length).toBeGreaterThan(0);
    expect(pills.length).toBeLessThan(many.length);
  });
});

describe('helpers', () => {
  it('logoFor picks a mark and the latin wordmark', () => {
    expect(logoFor({ id: 'selune', name: 'SÉLUNE 晞月' })).toEqual({ mark: 'crescent', wordmark: 'SÉLUNE' });
    expect(logoFor({ id: 'misty-isle', name: '霧嶼咖啡 MISTY ISLE' })).toEqual({ mark: 'isle', wordmark: 'MISTY ISLE' });
    expect(logoFor({ id: 'x', name: '測試品牌' })).toEqual({ mark: 'monogram', wordmark: '測試品牌' });
  });

  it('formatPrice adds thousands separators', () => {
    expect(formatPrice(1280)).toBe('1,280');
    expect(formatPrice(120)).toBe('120');
    expect(formatPrice(1234567)).toBe('1,234,567');
  });
});
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `npx vitest run src/lib/compose/scene.test.ts`
Expected: FAIL，找不到 `./scene`

- [ ] **Step 3: 實作 `web/src/lib/compose/scene.ts`**

```ts
import type { Copy, LayoutBox, LayoutElementId, Palette } from '@/types/contract';
import type { Rect } from '@/lib/core/geometry';
import { visLen } from '@/lib/core/text';
import { mixHex } from '@/lib/review/color';
import { boxMap, fitFontSize } from './layout';

/** headline → 品牌標題字型（襯線）；body → 品牌內文字型 */
export type FontRole = 'headline' | 'body';
export type LogoMark = 'crescent' | 'isle' | 'monogram';

/** 一段文字。y 是文字的垂直中心（繪製時 textBaseline = 'middle'）。 */
export interface TextOp {
  kind: 'text';
  el: LayoutElementId;
  text: string;
  x: number;
  y: number;
  size: number;
  weight: number;
  role: FontRole;
  color: string;
  alpha: number;
  align: 'left' | 'center';
  letterSpacing: number;
  strike: boolean;
}
export interface PillOp {
  kind: 'pill';
  el: LayoutElementId;
  rect: Rect;
  fill: string;
  fillAlpha: number;
  stroke: string | null;
  strokeAlpha: number;
  lineWidth: number;
}
export interface BadgeOp {
  kind: 'badge';
  cx: number;
  cy: number;
  r: number;
  /** 角度（度） */
  rotate: number;
  fill: string;
  ring: string;
  shadow: string;
  texts: TextOp[];
}
export interface LogoOp { kind: 'logo'; rect: Rect; mark: LogoMark; color: string; wordmark: TextOp | null }
export interface ProductOp { kind: 'product'; rect: Rect; shadow: string }
export type SceneOp = { kind: 'background' } | ProductOp | LogoOp | TextOp | PillOp | BadgeOp;

export interface PosterScene { width: number; height: number; ops: SceneOp[] }

export interface SceneInput {
  canvas: { width: number; height: number };
  layout: LayoutBox[];
  palette: Palette;
  copy: Copy;
  brand: { id: string; name: string };
}

const MARKS: Record<string, LogoMark> = { selune: 'crescent', 'misty-isle': 'isle' };

/** 品牌標誌：已知品牌用專屬圖形，字標取品牌名稱中的拉丁字（沒有就用全名） */
export function logoFor(brand: { id: string; name: string }): { mark: LogoMark; wordmark: string } {
  const latin = brand.name.match(/[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ&.' -]*[A-Za-zÀ-ÿ]/)?.[0];
  return { mark: MARKS[brand.id] ?? 'monogram', wordmark: latin ?? brand.name };
}

export const formatPrice = (n: number): string => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');

/** 依 visLen 估算的文字外框（測試與 BBox 疊圖用） */
export function textBounds(op: TextOp): Rect {
  const w = visLen(op.text) * op.size + op.letterSpacing * Math.max(0, [...op.text].length - 1);
  return { x: op.align === 'center' ? op.x - w / 2 : op.x, y: op.y - op.size / 2, w, h: op.size };
}

const CTA_TEXT = '立即選購 →';

type TextInit = Pick<TextOp, 'el' | 'text' | 'x' | 'y' | 'size' | 'color'> & Partial<TextOp>;
const text = (t: TextInit): TextOp => ({
  kind: 'text', weight: 500, role: 'body', alpha: 1, align: 'left', letterSpacing: 0, strike: false, ...t,
});

/**
 * 排版引擎：依版面 BBox 與文案產生繪製指令。字級一律依框的寬高自動縮放，所以使用者改文案時不會溢出。
 * 預覽與匯出共用同一份指令（由 paint.ts 畫到 Canvas）。
 */
export function composePoster({ canvas, layout, palette: P, copy: C, brand }: SceneInput): PosterScene {
  const B = boxMap(layout);
  const ops: SceneOp[] = [{ kind: 'background' }, { kind: 'product', rect: B.product, shadow: P.ink }];

  // Logo：標誌圖形 + 字標
  const L = B.logo;
  const logo = logoFor(brand);
  const wordW = L.w - L.h * 1.12;
  const wordChars = [...logo.wordmark].length;
  const wordSize = Math.min(L.h * 0.62, wordW / (visLen(logo.wordmark) + 0.08 * Math.max(0, wordChars - 1)));
  ops.push({
    kind: 'logo', rect: L, mark: logo.mark, color: P.accent,
    wordmark: wordW > 0
      ? text({ el: 'logo', text: logo.wordmark, x: L.x + L.h * 1.12, y: L.y + L.h / 2, size: wordSize, weight: 700, role: 'headline', color: P.ink, letterSpacing: wordSize * 0.08 })
      : null,
  });

  // 標題：最多兩行，第二行用品牌主色強調
  const H = B.headline;
  const lines = C.headline.filter((l) => l.trim() !== '');
  if (lines.length) {
    const size = fitFontSize(lines, H);
    lines.forEach((line, i) =>
      ops.push(text({ el: 'headline', text: line, x: H.x, y: H.y + size * 1.2 * (i + 0.5), size, weight: 900, role: 'headline', color: i === 0 ? P.ink : P.primary })),
    );
  }

  // 副標
  const S = B.subhead;
  if (C.subhead.trim()) {
    const size = Math.min(S.h * 0.8, S.w / visLen(C.subhead));
    ops.push(text({ el: 'subhead', text: C.subhead, x: S.x, y: S.y + S.h / 2, size, color: P.ink, alpha: 0.85 }));
  }

  // 賣點膠囊：放不下的就不畫
  const F = B.features;
  const features = C.features.filter((f) => f.trim() !== '');
  if (features.length) {
    const size = Math.min(F.h * 0.46, F.w / (visLen(features[0]) + 1.5));
    const pad = size * 0.75;
    let x = F.x;
    for (const f of features) {
      const w = visLen(f) * size + pad * 2;
      if (x + w > F.x + F.w) break;
      ops.push({ kind: 'pill', el: 'features', rect: { x, y: F.y, w, h: F.h }, fill: '#ffffff', fillAlpha: 0.72, stroke: P.primary, strokeAlpha: 0.45, lineWidth: F.h * 0.03 });
      ops.push(text({ el: 'features', text: f, x: x + w / 2, y: F.y + F.h / 2, size, align: 'center', color: mixHex(P.primary, P.ink, 0.3) }));
      x += w + size * 0.45;
    }
  }

  // 價格：商品名稱｜價格標籤、特價、原價；寬版型右側加 CTA
  const R = B.price;
  const cta = R.w / R.h > 3;
  const top = [C.productName, C.price.label].filter((s) => s.trim() !== '').join('｜');
  if (top) {
    const size = Math.min(R.h * 0.15, (cta ? R.w * 0.62 : R.w) / visLen(top));
    ops.push(text({ el: 'price', text: top, x: R.x, y: R.y + R.h * 0.1, size, color: P.ink, alpha: 0.72 }));
  }
  const sale = formatPrice(C.price.sale);
  const saleSize = Math.min(R.h * 0.46, (cta ? R.w * 0.6 : R.w * 0.95) / (visLen(sale) + 1));
  const prefixSize = saleSize * 0.42;
  ops.push(text({ el: 'price', text: 'NT$', x: R.x, y: R.y + R.h * 0.55, size: prefixSize, weight: 700, color: P.primary }));
  ops.push(text({ el: 'price', text: sale, x: R.x + prefixSize * 2.2, y: R.y + R.h * 0.53, size: saleSize, weight: 900, role: 'headline', color: P.primary }));
  if (C.price.original > C.price.sale) {
    const orig = `原價 NT$${formatPrice(C.price.original)}`;
    const size = Math.min(R.h * 0.13, (cta ? R.w * 0.6 : R.w) / visLen(orig));
    ops.push(text({ el: 'price', text: orig, x: R.x, y: R.y + R.h * 0.9, size, color: P.ink, alpha: 0.5, strike: true }));
  }
  if (cta) {
    const size = R.h * 0.16;
    const w = visLen(CTA_TEXT) * size + size * 2.4;
    const h = size * 2.5;
    const rect = { x: R.x + R.w - w, y: R.y + R.h * 0.5 - h / 2, w, h };
    ops.push({ kind: 'pill', el: 'price', rect, fill: P.ink, fillAlpha: 1, stroke: null, strokeAlpha: 0, lineWidth: 0 });
    ops.push(text({ el: 'price', text: CTA_TEXT, x: rect.x + w / 2, y: rect.y + h / 2, size, weight: 700, align: 'center', color: '#ffffff' }));
  }

  // 頁尾註記
  const D = B.disclaimer;
  if (C.disclaimer.trim()) {
    const size = Math.min(D.h * 0.75, D.w / visLen(C.disclaimer));
    ops.push(text({ el: 'disclaimer', text: C.disclaimer, x: D.x, y: D.y + D.h / 2, size, weight: 400, color: P.ink, alpha: 0.55 }));
  }

  // 促銷徽章（z 最高，最後畫）
  const G = B.badge;
  if (C.badge.main.trim()) {
    const r = Math.min(G.w, G.h) / 2;
    const cx = G.x + G.w / 2;
    const cy = G.y + G.h / 2;
    const texts: TextOp[] = [];
    if (C.badge.top.trim()) {
      texts.push(text({ el: 'badge', text: C.badge.top, x: cx, y: cy - r * 0.42, size: Math.min(r * 0.15, (r * 1.3) / visLen(C.badge.top)), align: 'center', color: P.secondary }));
    }
    texts.push(text({ el: 'badge', text: C.badge.main, x: cx, y: cy + r * 0.02, size: Math.min(r * 0.4, (r * 1.45) / visLen(C.badge.main)), weight: 900, role: 'headline', align: 'center', color: '#ffffff' }));
    if (C.badge.sub.trim()) {
      const n = [...C.badge.sub].length;
      const size = Math.min(r * 0.105, (r * 1.3) / (visLen(C.badge.sub) + 0.28 * Math.max(0, n - 1)));
      texts.push(text({ el: 'badge', text: C.badge.sub, x: cx, y: cy + r * 0.46, size, weight: 700, align: 'center', color: mixHex(P.accent, '#ffffff', 0.35), letterSpacing: size * 0.28 }));
    }
    ops.push({ kind: 'badge', cx, cy, r, rotate: -6, fill: P.primary, ring: P.accent, shadow: P.ink, texts });
  }

  return { width: canvas.width, height: canvas.height, ops };
}
```

- [ ] **Step 4: 執行測試確認通過**

Run: `npx vitest run src/lib/compose`
Expected: `scene.test.ts` 26 個測試（5 個模板 × 4 項 + 6 項）PASS，`layout.test.ts` 仍全部 PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/compose/scene.ts web/src/lib/compose/scene.test.ts
git commit -m "feat: add poster scene composer with auto-fitting text" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: 程序化背景與示範商品圖

**Files:**
- Create: `web/src/lib/compose/art.ts`
- Test: `web/src/lib/compose/art.test.ts`

**Interfaces:**
- Consumes：`mulberry32`、`round1`、`visLen`、`mixHex`（Plan 1）
- Produces：
  - `esc(s)`、`shade(hex, t)`、`svgDataUrl(svg)`
  - `interface BackgroundOptions { width; height; palette; seed; style; focus: Rect }`
  - `backgroundSvg(opts): string`：`style` 為 `selune` 時畫極光緞帶、光暈與月環；`misty-isle` 時畫晨霧、窗光與陶瓷桌面；其他值用漸層加散景。輸出不含文字與外部資源。
  - `bottleLabel(name)`：回傳 `{ lines, size }`
  - `productArtSvg(art, palette, name, wordmark)`：500×800。商品是真實存在的東西，所以永遠用品牌色票畫，不跟背景一起變色。

- [ ] **Step 1: 寫失敗測試 `web/src/lib/compose/art.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import { MISTY_ISLE, SELUNE } from '@/lib/api/mock/data';
import { backgroundSvg, bottleLabel, esc, productArtSvg, shade, svgDataUrl, type BackgroundOptions } from './art';

const opts = (over: Partial<BackgroundOptions> = {}): BackgroundOptions => ({
  width: 1440, height: 1800, palette: SELUNE.palette, seed: 42, style: 'selune', focus: { x: 634, y: 720, w: 720, h: 918 }, ...over,
});

describe('backgroundSvg', () => {
  it('is a standalone SVG sized to the template', () => {
    const svg = backgroundSvg(opts());
    expect(svg.startsWith('<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="1800" viewBox="0 0 1440 1800">')).toBe(true);
    expect(svg.endsWith('</svg>')).toBe(true);
    expect(svg).toContain(SELUNE.palette.secondary);
  });

  it('is deterministic per seed and differs between seeds and styles', () => {
    expect(backgroundSvg(opts())).toBe(backgroundSvg(opts()));
    expect(backgroundSvg(opts({ seed: 43 }))).not.toBe(backgroundSvg(opts()));
    const misty = backgroundSvg(opts({ style: 'misty-isle', palette: MISTY_ISLE.palette }));
    expect(misty).toContain('id="mist"');
    expect(backgroundSvg(opts({ style: 'unknown' }))).not.toBe(backgroundSvg(opts()));
  });

  it('contains no text and no external references', () => {
    for (const style of ['selune', 'misty-isle', 'unknown']) {
      const svg = backgroundSvg(opts({ style }));
      expect(svg).not.toContain('<text');
      expect(svg).not.toMatch(/href=|<image/);
    }
  });
});

describe('productArtSvg', () => {
  it('draws the serum and cold brew bottles with the product name on the label', () => {
    const serum = productArtSvg('serum', SELUNE.palette, '極光玻尿酸修護精華 30ml', 'SÉLUNE');
    expect(serum).toContain('viewBox="0 0 500 800"');
    expect(serum).toContain('極光玻尿酸');
    expect(serum).toContain('30 ml');
    const brew = productArtSvg('coldbrew', MISTY_ISLE.palette, '單一產區冷萃咖啡 330ml', 'MISTY ISLE');
    expect(brew).toContain('MISTY ISLE');
    expect(brew).toContain('clipPath');
  });

  it('escapes user-provided names', () => {
    const svg = productArtSvg('serum', SELUNE.palette, '<新>&', 'A&B');
    expect(svg).toContain('&lt;新&gt;&amp;');
    expect(svg).toContain('A&amp;B');
  });
});

describe('helpers', () => {
  it('bottleLabel splits long names and extracts the size', () => {
    expect(bottleLabel('極光玻尿酸修護精華 30ml')).toEqual({ lines: ['極光玻尿酸', '修護精華'], size: '30 ml' });
    expect(bottleLabel('冷萃 330ML')).toEqual({ lines: ['冷萃'], size: '330 ml' });
    expect(bottleLabel('晚安面膜')).toEqual({ lines: ['晚安面膜'], size: '' });
  });

  it('esc, shade and svgDataUrl', () => {
    expect(esc('"a" & <b>')).toBe('&quot;a&quot; &amp; &lt;b&gt;');
    expect(shade('#808080', 1)).toBe('#ffffff');
    expect(shade('#808080', -1)).toBe('#000000');
    expect(svgDataUrl('<svg/>')).toBe('data:image/svg+xml;charset=utf-8,%3Csvg%2F%3E');
  });
});
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `npx vitest run src/lib/compose/art.test.ts`
Expected: FAIL，找不到 `./art`

- [ ] **Step 3: 實作 `web/src/lib/compose/art.ts`**

```ts
import type { Palette } from '@/types/contract';
import type { Rect } from '@/lib/core/geometry';
import { mulberry32, round1 as r1 } from '@/lib/core/num';
import { visLen } from '@/lib/core/text';
import { mixHex } from '@/lib/review/color';

/** 程序化 SVG 素材：背景（第二階段由 ComfyUI 生成的圖取代）與示範商品圖。全部是純字串，不含文字以外的外部資源。 */

const SVG_NS = 'http://www.w3.org/2000/svg';
const SERIF = "'Noto Serif TC',serif";
const SANS = "'Noto Sans TC',sans-serif";

export const esc = (s: string) =>
  s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] ?? c);

/** t > 0 往白色混、t < 0 往黑色混 */
export const shade = (hex: string, t: number) => mixHex(hex, t < 0 ? '#000000' : '#ffffff', Math.abs(t));

export const svgDataUrl = (svg: string) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;

export interface BackgroundOptions {
  width: number;
  height: number;
  palette: Palette;
  seed: number;
  /** 背景風格（目前以品牌 id 區分） */
  style: string;
  /** 商品所在的框，光暈與桌面會以它為中心 */
  focus: Rect;
}

function seluneBackground({ width: W, height: H, palette: P, seed, focus: F }: BackgroundOptions): string {
  const R = mulberry32(seed);
  const cx = F.x + F.w / 2;
  const cy = F.y + F.h * 0.48;
  const halo = Math.min(F.w, F.h) * 0.46;
  let o = `<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${P.secondary}"/><stop offset=".55" stop-color="${mixHex(P.secondary, P.primary, 0.16)}"/><stop offset="1" stop-color="${mixHex(P.secondary, P.primary, 0.45)}"/></linearGradient>
<radialGradient id="glow"><stop offset="0" stop-color="#fff" stop-opacity=".9"/><stop offset=".45" stop-color="${mixHex(P.secondary, '#ffffff', 0.5)}" stop-opacity=".55"/><stop offset="1" stop-color="${P.secondary}" stop-opacity="0"/></radialGradient>
<linearGradient id="rib" x1="0" x2="1"><stop offset="0" stop-color="${P.primary}" stop-opacity="0"/><stop offset=".4" stop-color="${P.primary}"/><stop offset=".7" stop-color="${P.accent}"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
<filter id="blur" x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur stdDeviation="${r1(W * 0.012)}"/></filter>
</defs>`;
  o += `<rect width="${W}" height="${H}" fill="url(#bg)"/>`;
  o += `<circle cx="${r1(cx)}" cy="${r1(cy)}" r="${r1(F.w * 0.75)}" fill="url(#glow)"/>`;
  [0.3, 0.58, 0.84].forEach((k, i) => {
    const y0 = H * k + (R() - 0.5) * H * 0.06;
    const d = `M${r1(-W * 0.1)} ${r1(y0)} C${r1(W * 0.3)} ${r1(y0 - H * 0.12)} ${r1(W * 0.62)} ${r1(y0 + H * 0.1)} ${r1(W * 1.1)} ${r1(y0 - H * 0.05)}`;
    o += `<path d="${d}" fill="none" stroke="url(#rib)" stroke-width="${r1(W * (0.05 - i * 0.012))}" opacity=".32" filter="url(#blur)"/>`;
    o += `<path d="${d}" fill="none" stroke="${P.accent}" stroke-width="${r1(W * 0.0016)}" opacity=".55" transform="translate(0 ${r1(H * 0.018)})"/>`;
  });
  o += `<circle cx="${r1(cx)}" cy="${r1(cy)}" r="${r1(halo)}" fill="#fff" fill-opacity=".38"/>`;
  o += `<circle cx="${r1(cx)}" cy="${r1(cy)}" r="${r1(halo * 1.08)}" fill="none" stroke="${P.accent}" stroke-width="${r1(W * 0.0018)}" opacity=".75"/>`;
  for (let i = 0; i < 24; i++) {
    const x = R() * W, y = R() * H, rr = W * (0.003 + R() * 0.014), col = R() < 0.3 ? P.accent : '#ffffff', op = 0.25 + R() * 0.45;
    o += `<circle cx="${r1(x)}" cy="${r1(y)}" r="${r1(rr)}" fill="${col}" opacity="${r1(op)}"/>`;
  }
  return o;
}

function mistyBackground({ width: W, height: H, palette: P, seed, focus: F }: BackgroundOptions): string {
  const R = mulberry32(seed);
  const table = F.y + F.h * 0.9;
  const tilt = (R() - 0.5) * W * 0.08;
  let o = `<defs>
<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${mixHex(P.secondary, '#ffffff', 0.4)}"/><stop offset=".6" stop-color="${P.secondary}"/><stop offset="1" stop-color="${mixHex(P.secondary, P.primary, 0.18)}"/></linearGradient>
<linearGradient id="desk" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${mixHex(P.secondary, P.accent, 0.35)}"/><stop offset="1" stop-color="${mixHex(P.secondary, P.accent, 0.6)}"/></linearGradient>
<filter id="soft" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="${r1(W * 0.02)}"/></filter>
<filter id="mist" x="-20%" y="-100%" width="140%" height="300%"><feGaussianBlur stdDeviation="${r1(H * 0.03)}"/></filter>
</defs>`;
  o += `<rect width="${W}" height="${H}" fill="url(#bg)"/>`;
  // 窗光：左上斜射的光帶
  for (let i = 0; i < 3; i++) {
    const x0 = W * (0.05 + i * 0.16) + tilt;
    const w = W * (0.06 + R() * 0.04);
    o += `<path d="M${r1(x0)} 0 H${r1(x0 + w)} L${r1(x0 + w + W * 0.35)} ${r1(table)} H${r1(x0 + W * 0.35)} Z" fill="#fff" opacity=".28" filter="url(#soft)"/>`;
  }
  // 晨霧
  [0.22, 0.45, 0.68].forEach((k) => {
    o += `<ellipse cx="${r1(W * (0.3 + R() * 0.4))}" cy="${r1(H * k)}" rx="${r1(W * 0.6)}" ry="${r1(H * 0.05)}" fill="#fff" opacity=".45" filter="url(#mist)"/>`;
  });
  // 霧面陶瓷桌面與商品投影
  o += `<rect x="0" y="${r1(table)}" width="${W}" height="${r1(H - table)}" fill="url(#desk)"/>`;
  o += `<rect x="0" y="${r1(table)}" width="${W}" height="${r1(H * 0.004)}" fill="#fff" opacity=".6"/>`;
  const sx = F.x + F.w * 0.5;
  o += `<path d="M${r1(sx - F.w * 0.2)} ${r1(table)} L${r1(sx + F.w * 0.2)} ${r1(table)} L${r1(sx + F.w * 0.75)} ${r1(table + (H - table) * 0.7)} L${r1(sx + F.w * 0.25)} ${r1(table + (H - table) * 0.7)} Z" fill="${P.ink}" opacity=".12" filter="url(#soft)"/>`;
  for (let i = 0; i < 18; i++) {
    o += `<circle cx="${r1(R() * W)}" cy="${r1(R() * table)}" r="${r1(W * (0.002 + R() * 0.004))}" fill="${P.accent}" opacity=".25"/>`;
  }
  return o;
}

function plainBackground({ width: W, height: H, palette: P, seed }: BackgroundOptions): string {
  const R = mulberry32(seed);
  let o = `<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${P.secondary}"/><stop offset="1" stop-color="${mixHex(P.secondary, P.primary, 0.3)}"/></linearGradient></defs>`;
  o += `<rect width="${W}" height="${H}" fill="url(#bg)"/>`;
  for (let i = 0; i < 16; i++) {
    o += `<circle cx="${r1(R() * W)}" cy="${r1(R() * H)}" r="${r1(W * (0.004 + R() * 0.012))}" fill="#fff" opacity=".4"/>`;
  }
  return o;
}

const STYLES: Record<string, (o: BackgroundOptions) => string> = { selune: seluneBackground, 'misty-isle': mistyBackground };

/** 依品牌色、模板比例與 seed 產生的背景（模擬 ComfyUI 生成的情境背景）。同一組參數輸出相同字串。 */
export function backgroundSvg(opts: BackgroundOptions): string {
  const body = (STYLES[opts.style] ?? plainBackground)(opts);
  return `<svg xmlns="${SVG_NS}" width="${opts.width}" height="${opts.height}" viewBox="0 0 ${opts.width} ${opts.height}">${body}</svg>`;
}

/** 由商品名稱產生瓶身標籤：去掉容量後超過 6 個字就拆成兩行 */
export function bottleLabel(name: string): { lines: string[]; size: string } {
  const m = name.match(/(\d+)\s*(ml|g)\s*$/i);
  const size = m ? `${m[1]} ${m[2].toLowerCase()}` : '';
  const base = (m ? name.slice(0, m.index) : name).trim() || name;
  const chars = [...base];
  if (chars.length <= 6) return { lines: [base], size };
  const half = Math.ceil(chars.length / 2);
  return { lines: [chars.slice(0, half).join(''), chars.slice(half).join('')], size };
}

function labelTexts(name: string, wordmark: string, top: number, ink: string, accent: string, width: number): string {
  const { lines, size } = bottleLabel(name);
  const fs = Math.min(23, width / Math.max(...lines.map(visLen)));
  const y0 = lines.length > 1 ? top + 94 : top + 112;
  let o = `<text x="250" y="${top + 42}" text-anchor="middle" font-family="${SERIF}" font-weight="700" font-size="19" letter-spacing="3" fill="${ink}">${esc(wordmark)}</text>`;
  o += `<line x1="222" x2="278" y1="${top + 56}" y2="${top + 56}" stroke="${accent}" stroke-width="1.5"/>`;
  lines.forEach((t, i) => {
    o += `<text x="250" y="${r1(y0 + i * fs * 1.35)}" text-anchor="middle" font-family="${SERIF}" font-weight="700" font-size="${r1(fs)}" fill="${ink}">${esc(t)}</text>`;
  });
  if (size) o += `<text x="250" y="${top + 172}" text-anchor="middle" font-family="${SANS}" font-size="14" letter-spacing="2" fill="${ink}" fill-opacity=".6">${esc(size)}</text>`;
  return o;
}

/** 精華液滴管瓶 + 珍珠石台（座標 500×800） */
function serumArt(P: Palette, name: string, wordmark: string): string {
  let o = `<defs>
<linearGradient id="glass" x1="0" x2="1"><stop offset="0" stop-color="${shade(P.primary, -0.35)}"/><stop offset=".16" stop-color="${shade(P.primary, 0.25)}"/><stop offset=".45" stop-color="${P.primary}"/><stop offset=".8" stop-color="${shade(P.primary, 0.12)}"/><stop offset="1" stop-color="${shade(P.primary, -0.4)}"/></linearGradient>
<linearGradient id="gold" x1="0" x2="1"><stop offset="0" stop-color="#8E6F3A"/><stop offset=".3" stop-color="#F3E3B8"/><stop offset=".55" stop-color="#C9A96E"/><stop offset=".8" stop-color="#F6EACB"/><stop offset="1" stop-color="#9A7B45"/></linearGradient>
<linearGradient id="bulb" x1="0" x2="1"><stop offset="0" stop-color="${shade(P.primary, -0.6)}"/><stop offset=".35" stop-color="${shade(P.primary, -0.25)}"/><stop offset="1" stop-color="${shade(P.primary, -0.62)}"/></linearGradient>
<linearGradient id="pTop" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="${mixHex(P.secondary, '#ffffff', 0.3)}"/></linearGradient>
<linearGradient id="pSide" x1="0" x2="1"><stop offset="0" stop-color="${mixHex(P.secondary, P.ink, 0.12)}"/><stop offset=".45" stop-color="#ffffff"/><stop offset="1" stop-color="${mixHex(P.secondary, P.ink, 0.16)}"/></linearGradient>
<radialGradient id="bub" cx=".35" cy=".35" r=".65"><stop offset="0" stop-color="#fff" stop-opacity=".95"/><stop offset=".6" stop-color="#fff" stop-opacity=".2"/><stop offset="1" stop-color="#fff" stop-opacity=".55"/></radialGradient>
<filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="10"/></filter>
</defs>`;
  o += `<ellipse cx="250" cy="778" rx="236" ry="30" fill="${P.ink}" opacity=".16" filter="url(#soft)"/>`;
  o += `<path d="M30 700 V762 A220 36 0 0 0 470 762 V700 Z" fill="url(#pSide)"/>`;
  o += `<ellipse cx="250" cy="700" rx="220" ry="36" fill="url(#pTop)"/>`;
  o += `<ellipse cx="250" cy="700" rx="168" ry="26" fill="none" stroke="#fff" stroke-width="2.5" opacity=".9"/>`;
  o += `<ellipse cx="250" cy="700" rx="200" ry="31" fill="none" stroke="${P.accent}" stroke-width="1.5" opacity=".5"/>`;
  o += `<ellipse cx="250" cy="702" rx="112" ry="14" fill="${P.ink}" opacity=".28" filter="url(#soft)"/>`;
  o += `<path d="M214 236 V168 Q214 98 250 98 Q286 98 286 168 V236 Z" fill="url(#bulb)"/>`;
  o += `<rect x="226" y="118" width="9" height="104" rx="4.5" fill="#fff" opacity=".28"/>`;
  o += `<rect x="194" y="228" width="112" height="66" rx="10" fill="url(#gold)"/>`;
  for (let i = 0; i < 5; i++) o += `<line x1="198" x2="302" y1="${240 + i * 11}" y2="${240 + i * 11}" stroke="#7A5E2E" stroke-width="1" opacity=".22"/>`;
  o += `<rect x="210" y="290" width="80" height="44" fill="url(#glass)"/>`;
  o += `<path d="M150 384 Q150 330 210 328 H290 Q350 330 350 384 V668 Q350 702 316 702 H184 Q150 702 150 668 Z" fill="url(#glass)"/>`;
  o += `<path d="M164 420 H336 V660 Q336 688 310 688 H190 Q164 688 164 660 Z" fill="#fff" opacity=".07"/>`;
  o += `<rect x="172" y="440" width="156" height="196" rx="8" fill="${P.secondary}" opacity=".95"/>`;
  o += `<rect x="180" y="448" width="140" height="180" rx="5" fill="none" stroke="${P.accent}" stroke-width="1.2" opacity=".8"/>`;
  o += labelTexts(name, wordmark, 440, P.ink, P.accent, 128);
  o += `<rect x="160" y="356" width="11" height="310" rx="5.5" fill="#fff" opacity=".42"/>`;
  o += `<rect x="333" y="390" width="5" height="250" rx="2.5" fill="#fff" opacity=".22"/>`;
  for (const [x, y, r] of [[96, 430, 15], [402, 300, 10], [424, 520, 19], [84, 600, 9], [388, 642, 7], [120, 320, 6]]) {
    o += `<circle cx="${x}" cy="${y}" r="${r}" fill="url(#bub)" stroke="#fff" stroke-opacity=".7" stroke-width="1"/>`;
  }
  return o;
}

/** 冷萃咖啡玻璃瓶 + 陶瓷杯墊（座標 500×800） */
function coldbrewArt(P: Palette, name: string, wordmark: string): string {
  const bottle = 'M220 120 H280 V190 C280 215 340 225 340 265 V668 Q340 700 308 700 H192 Q160 700 160 668 V265 C160 225 220 215 220 190 Z';
  let o = `<defs>
<clipPath id="body"><path d="${bottle}"/></clipPath>
<linearGradient id="coffee" x1="0" x2="1"><stop offset="0" stop-color="#1A0F09"/><stop offset=".35" stop-color="#4A2C1A"/><stop offset=".7" stop-color="#2E1B10"/><stop offset="1" stop-color="#140B06"/></linearGradient>
<linearGradient id="cTop" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${mixHex(P.secondary, '#ffffff', 0.5)}"/><stop offset="1" stop-color="${mixHex(P.secondary, P.ink, 0.08)}"/></linearGradient>
<linearGradient id="cSide" x1="0" x2="1"><stop offset="0" stop-color="${mixHex(P.secondary, P.ink, 0.22)}"/><stop offset=".45" stop-color="${mixHex(P.secondary, '#ffffff', 0.3)}"/><stop offset="1" stop-color="${mixHex(P.secondary, P.ink, 0.26)}"/></linearGradient>
<filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="10"/></filter>
</defs>`;
  o += `<ellipse cx="250" cy="778" rx="220" ry="28" fill="${P.ink}" opacity=".18" filter="url(#soft)"/>`;
  o += `<path d="M50 712 V756 A200 30 0 0 0 450 756 V712 Z" fill="url(#cSide)"/>`;
  o += `<ellipse cx="250" cy="712" rx="200" ry="30" fill="url(#cTop)"/>`;
  o += `<ellipse cx="250" cy="706" rx="104" ry="12" fill="${P.ink}" opacity=".3" filter="url(#soft)"/>`;
  o += `<g clip-path="url(#body)"><rect x="150" y="300" width="200" height="420" fill="url(#coffee)"/><rect x="150" y="296" width="200" height="8" fill="#6B4630" opacity=".8"/></g>`;
  o += `<path d="${bottle}" fill="#fff" fill-opacity=".14" stroke="#fff" stroke-opacity=".6" stroke-width="2"/>`;
  o += `<rect x="212" y="84" width="76" height="46" rx="7" fill="${P.ink}"/>`;
  for (let i = 0; i < 6; i++) o += `<line x1="${220 + i * 12}" x2="${220 + i * 12}" y1="90" y2="124" stroke="#fff" stroke-opacity=".12" stroke-width="2"/>`;
  o += `<rect x="172" y="420" width="156" height="200" rx="4" fill="${mixHex(P.accent, '#ffffff', 0.25)}"/>`;
  o += `<rect x="180" y="428" width="140" height="184" rx="2" fill="none" stroke="${P.primary}" stroke-width="1.2" opacity=".7"/>`;
  o += labelTexts(name, wordmark, 424, P.primary, P.primary, 128);
  o += `<rect x="172" y="250" width="10" height="400" rx="5" fill="#fff" opacity=".35"/>`;
  o += `<rect x="324" y="300" width="5" height="300" rx="2.5" fill="#fff" opacity=".2"/>`;
  return o;
}

const ARTS = { serum: serumArt, coldbrew: coldbrewArt } as const;

/** 示範商品圖（模擬已去背的商品照）。商品是真實存在的東西，所以永遠用品牌色票繪製，不跟背景一起變色。 */
export function productArtSvg(art: keyof typeof ARTS, palette: Palette, name: string, wordmark: string): string {
  return `<svg xmlns="${SVG_NS}" width="500" height="800" viewBox="0 0 500 800">${ARTS[art](palette, name, wordmark)}</svg>`;
}
```

- [ ] **Step 4: 執行測試確認通過**

Run: `npx vitest run src/lib/compose/art.test.ts`
Expected: 7 個測試 PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/compose/art.ts web/src/lib/compose/art.test.ts
git commit -m "feat: add procedural background and sample product art" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Canvas 繪製與匯出工具

**Files:**
- Create: `web/src/lib/compose/assets.ts`、`web/src/lib/compose/paint.ts`、`web/src/lib/compose/render.ts`、`web/src/lib/export/naming.ts`、`web/src/lib/export/zip.ts`、`web/src/lib/export/download.ts`、`web/src/lib/export/posters.ts`
- Test: `web/src/lib/compose/assets.test.ts`、`web/src/lib/export/export.test.ts`

**Interfaces:**
- Consumes：`composePoster`、`textBounds`、`logoFor`（Task 5）；`backgroundSvg`、`productArtSvg`、`svgDataUrl`（Task 6）；`boxMap`、`getTemplate`（Plan 1）
- Produces：
  - 純函式：
    - `productImage(product, brand)`：回傳 `{ src, blend }`。
    - `fontStacks(brand)`。
    - `safeName`、`dateStamp`。
    - `posterFileName(...)`：產生「品牌_商品_通路_日期.png」。
    - `zipFileName(...)`：產生「品牌_商品_日期.zip」。
    - `uniqueName(name, used)`。
    - `buildZip(entries)`：回傳 `Promise<Blob>`。
  - 瀏覽器：
    - `paintScene(ctx, scene, assets)`。
    - `loadImage(src)`：有快取，最多 80 張。
    - `preparePoster(input)`、`paintPoster(canvas, prepared, pixelWidth)`。
    - `posterBlob(input)`：原尺寸 PNG。
    - `downloadBlob(blob, name)`。
    - `exportPosterZip(brand, product, items, date?)`、`exportPosterPng(brand, product, item, date?)`。
  - `interface PosterInput { render: Render; copy: Copy; product: Product | null; brand: Brand }`

- [ ] **Step 1: 安裝 JSZip**

```bash
npm i jszip@^3.10.2
```

- [ ] **Step 2: 寫失敗測試 `web/src/lib/compose/assets.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import type { Product } from '@/types/contract';
import { SAMPLE_PRODUCTS, SELUNE } from '@/lib/api/mock/data';
import { fontStacks, productImage } from './assets';

const upload: Product = {
  ...SAMPLE_PRODUCTS[0], id: 'p_up', photo: { source: 'upload', url: 'data:image/png;base64,AQID' }, cutout: null,
};

describe('productImage', () => {
  it('uses the SVG art for sample products', () => {
    const img = productImage(SAMPLE_PRODUCTS[0], SELUNE);
    expect(img.blend).toBe('normal');
    expect(img.src.startsWith('data:image/svg+xml')).toBe(true);
    expect(decodeURIComponent(img.src)).toContain('SÉLUNE');
  });

  it('multiplies an uploaded photo until a real cutout exists', () => {
    expect(productImage(upload, SELUNE)).toEqual({ src: 'data:image/png;base64,AQID', blend: 'multiply' });
    expect(productImage({ ...upload, cutout: { model: 'BiRefNet-general', url: null } }, SELUNE).blend).toBe('multiply');
    expect(productImage({ ...upload, cutout: { model: 'BiRefNet-general', url: '/cutout.png' } }, SELUNE))
      .toEqual({ src: '/cutout.png', blend: 'normal' });
  });
});

describe('fontStacks', () => {
  it('prefers the self-hosted variable fonts', () => {
    expect(fontStacks(SELUNE).headline.startsWith('"Noto Serif TC Variable", "Noto Serif TC"')).toBe(true);
    expect(fontStacks(SELUNE).body).toContain('sans-serif');
  });
});
```

- [ ] **Step 3: 寫失敗測試 `web/src/lib/export/export.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import JSZip from 'jszip';
import { dateStamp, posterFileName, safeName, zipFileName } from './naming';
import { buildZip, uniqueName } from './zip';

const DATE = new Date(2026, 9, 6, 23, 59);

describe('naming', () => {
  it('builds 品牌_商品_通路_日期 file names', () => {
    expect(posterFileName({ brandName: 'SÉLUNE 晞月', productName: '極光玻尿酸修護精華 30ml', channel: 'IG 貼文', date: DATE }))
      .toBe('SÉLUNE晞月_極光玻尿酸修護精華30ml_IG貼文_20261006.png');
    expect(zipFileName({ brandName: '霧嶼咖啡 MISTY ISLE', productName: '單一產區冷萃咖啡 330ml', date: DATE }))
      .toBe('霧嶼咖啡MISTYISLE_單一產區冷萃咖啡330ml_20261006.zip');
  });

  it('removes characters that are not allowed in file names', () => {
    expect(safeName('a/b:c*d?"e"<f>|g')).toBe('abcdefg');
    expect(safeName(' / ')).toBe('未命名');
    expect(dateStamp(new Date(2026, 0, 2))).toBe('20260102');
  });
});

describe('zip', () => {
  it('uniqueName appends a counter before the extension', () => {
    const used = new Set<string>();
    expect(uniqueName('a.png', used)).toBe('a.png');
    expect(uniqueName('a.png', used)).toBe('a (2).png');
    expect(uniqueName('a.png', used)).toBe('a (3).png');
    expect(uniqueName('README', used)).toBe('README');
  });

  it('packs blobs and bytes into a zip that can be read back', async () => {
    const blob = await buildZip([
      { name: 'a.png', data: new Blob([new Uint8Array([1, 2, 3])], { type: 'image/png' }) },
      { name: 'a.png', data: new Uint8Array([4, 5]) },
    ]);
    expect(blob.type).toBe('application/zip');
    const zip = await JSZip.loadAsync(await blob.arrayBuffer());
    expect(Object.keys(zip.files).sort()).toEqual(['a (2).png', 'a.png']);
    expect([...(await zip.file('a.png')!.async('uint8array'))]).toEqual([1, 2, 3]);
  });
});
```

- [ ] **Step 4: 執行測試確認失敗**

Run: `npx vitest run src/lib/compose/assets.test.ts src/lib/export`
Expected: FAIL，找不到 `./assets`、`./naming`、`./zip`

- [ ] **Step 5: 實作 `web/src/lib/compose/assets.ts`**

```ts
import type { Brand, Product } from '@/types/contract';
import { productArtSvg, svgDataUrl } from './art';
import { logoFor } from './scene';

/** 純函式：決定海報要用的商品圖與字型（預覽、匯出、商品庫縮圖共用） */

export interface ProductImageSource { src: string; blend: 'normal' | 'multiply' }

/** 示範商品用 SVG 素材；上傳照片優先用去背圖，沒有就以色彩增值（multiply）合成 */
export function productImage(product: Product, brand: Brand): ProductImageSource {
  if (product.photo.source === 'sample') {
    return { src: svgDataUrl(productArtSvg(product.photo.art, brand.palette, product.name, logoFor(brand).wordmark)), blend: 'normal' };
  }
  return product.cutout?.url ? { src: product.cutout.url, blend: 'normal' } : { src: product.photo.url, blend: 'multiply' };
}

/** 品牌字型（@fontsource-variable 註冊的名稱帶 Variable），找不到時退回系統字型 */
export function fontStacks(brand: Pick<Brand, 'fonts'>): { headline: string; body: string } {
  return {
    headline: `"${brand.fonts.headline} Variable", "${brand.fonts.headline}", "Noto Serif TC", serif`,
    body: `"${brand.fonts.body} Variable", "${brand.fonts.body}", "Noto Sans TC", "Microsoft JhengHei", sans-serif`,
  };
}
```

- [ ] **Step 6: 實作 `web/src/lib/export/naming.ts`**

```ts
const pad = (n: number) => String(n).padStart(2, '0');

/** 去掉空白與檔名不允許的字元 */
export const safeName = (s: string): string => s.replace(/[\\/:*?"<>|\s]+/g, '') || '未命名';

/** 本地日期 YYYYMMDD */
export const dateStamp = (d: Date): string => `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`;

export interface PosterNameParts { brandName: string; productName: string; channel: string; date: Date }

/** 「品牌_商品_通路_日期.png」 */
export const posterFileName = ({ brandName, productName, channel, date }: PosterNameParts): string =>
  `${safeName(brandName)}_${safeName(productName)}_${safeName(channel)}_${dateStamp(date)}.png`;

/** 「品牌_商品_日期.zip」 */
export const zipFileName = ({ brandName, productName, date }: Omit<PosterNameParts, 'channel'>): string =>
  `${safeName(brandName)}_${safeName(productName)}_${dateStamp(date)}.zip`;
```

- [ ] **Step 7: 實作 `web/src/lib/export/zip.ts`**

```ts
import JSZip from 'jszip';

export interface ZipEntry { name: string; data: Blob | Uint8Array }

/** 檔名重複時在副檔名前加上 (2)、(3)… */
export function uniqueName(name: string, used: Set<string>): string {
  const dot = name.lastIndexOf('.');
  const [base, ext] = dot > 0 ? [name.slice(0, dot), name.slice(dot)] : [name, ''];
  let candidate = name;
  for (let i = 2; used.has(candidate); i++) candidate = `${base} (${i})${ext}`;
  used.add(candidate);
  return candidate;
}

/** 打包成 zip。Blob 先轉成位元組（JSZip 讀 Blob 需要 FileReader，Node 測試環境沒有）。 */
export async function buildZip(entries: ZipEntry[]): Promise<Blob> {
  const zip = new JSZip();
  const used = new Set<string>();
  for (const e of entries) {
    const bytes = e.data instanceof Uint8Array ? e.data : new Uint8Array(await e.data.arrayBuffer());
    zip.file(uniqueName(e.name, used), bytes);
  }
  return zip.generateAsync({ type: 'blob', mimeType: 'application/zip' });
}
```

- [ ] **Step 8: 執行測試確認通過**

Run: `npx vitest run src/lib/compose/assets.test.ts src/lib/export`
Expected: 7 個測試 PASS

- [ ] **Step 9: 實作 `web/src/lib/compose/paint.ts`**（瀏覽器模組，下列四個檔案在 Task 11、12 的畫面中驗證）

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

type Ctx = CanvasRenderingContext2D;

function drawText(ctx: Ctx, op: TextOp, fonts: PaintAssets['fonts']) {
  ctx.save();
  ctx.font = `${op.weight} ${op.size}px ${op.role === 'headline' ? fonts.headline : fonts.body}`;
  ctx.fillStyle = op.color;
  ctx.globalAlpha = op.alpha;
  ctx.textAlign = op.align;
  ctx.textBaseline = 'middle';
  ctx.letterSpacing = `${op.letterSpacing}px`;
  // 版型以估算字寬排版；實際字型較寬時用 maxWidth 壓縮，保證不超出 BBox
  const maxWidth = textBounds(op).w * 1.04;
  ctx.fillText(op.text, op.x, op.y, maxWidth);
  if (op.strike) {
    const w = Math.min(ctx.measureText(op.text).width, maxWidth);
    const x0 = op.align === 'center' ? op.x - w / 2 : op.x;
    ctx.fillRect(x0, op.y - op.size * 0.04, w, Math.max(1, op.size * 0.07));
  }
  ctx.restore();
}

function drawPill(ctx: Ctx, op: PillOp) {
  const { x, y, w, h } = op.rect;
  ctx.save();
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, h / 2);
  ctx.globalAlpha = op.fillAlpha;
  ctx.fillStyle = op.fill;
  ctx.fill();
  if (op.stroke) {
    ctx.globalAlpha = op.strokeAlpha;
    ctx.strokeStyle = op.stroke;
    ctx.lineWidth = op.lineWidth;
    ctx.stroke();
  }
  ctx.restore();
}

function drawBadge(ctx: Ctx, op: BadgeOp, fonts: PaintAssets['fonts']) {
  const { cx, cy, r } = op;
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate((op.rotate * Math.PI) / 180);
  ctx.translate(-cx, -cy);
  ctx.save();
  ctx.shadowColor = `${op.shadow}38`;
  ctx.shadowBlur = r * 0.12;
  ctx.shadowOffsetY = r * 0.04;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fillStyle = op.fill;
  ctx.fill();
  ctx.restore();
  ctx.beginPath();
  ctx.arc(cx, cy, r * 0.86, 0, Math.PI * 2);
  ctx.setLineDash([r * 0.05, r * 0.035]);
  ctx.lineWidth = r * 0.018;
  ctx.strokeStyle = op.ring;
  ctx.stroke();
  ctx.setLineDash([]);
  for (const t of op.texts) drawText(ctx, t, fonts);
  ctx.restore();
}

function drawLogo(ctx: Ctx, op: LogoOp, fonts: PaintAssets['fonts']) {
  const { x, y, h: s } = op.rect;
  ctx.save();
  ctx.fillStyle = op.color;
  if (op.mark === 'crescent') {
    const r = s * 0.42;
    const cx = x + r;
    const cy = y + s / 2;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.clip();
    ctx.beginPath();
    ctx.rect(cx - r, cy - r, r * 2, r * 2);
    ctx.arc(cx + r * 0.45, cy - r * 0.28, r * 0.82, 0, Math.PI * 2);
    ctx.fill('evenodd');
  } else if (op.mark === 'isle') {
    ctx.beginPath();
    ctx.moveTo(x + s * 0.04, y + s * 0.78);
    ctx.lineTo(x + s * 0.36, y + s * 0.22);
    ctx.lineTo(x + s * 0.58, y + s * 0.6);
    ctx.lineTo(x + s * 0.7, y + s * 0.42);
    ctx.lineTo(x + s * 0.96, y + s * 0.78);
    ctx.closePath();
    ctx.fill();
    ctx.lineWidth = s * 0.05;
    ctx.strokeStyle = op.color;
    ctx.beginPath();
    ctx.moveTo(x + s * 0.08, y + s * 0.9);
    ctx.quadraticCurveTo(x + s * 0.3, y + s * 0.82, x + s * 0.5, y + s * 0.9);
    ctx.quadraticCurveTo(x + s * 0.7, y + s * 0.98, x + s * 0.92, y + s * 0.9);
    ctx.stroke();
  } else {
    ctx.beginPath();
    ctx.arc(x + s / 2, y + s / 2, s * 0.45, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.font = `700 ${s * 0.5}px ${fonts.headline}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText([...(op.wordmark?.text ?? '?')][0], x + s / 2, y + s / 2);
  }
  ctx.restore();
  if (op.wordmark) drawText(ctx, op.wordmark, fonts);
}

/** 等比縮放放進框內，底部對齊（商品站在桌面上） */
function containBottom(rect: Rect, w: number, h: number): Rect {
  const s = Math.min(rect.w / w, rect.h / h);
  const dw = w * s;
  const dh = h * s;
  return { x: rect.x + (rect.w - dw) / 2, y: rect.y + rect.h - dh, w: dw, h: dh };
}

function drawProduct(ctx: Ctx, op: ProductOp, product: PaintAssets['product']) {
  if (!product) return;
  const d = containBottom(op.rect, product.width, product.height);
  ctx.save();
  if (product.blend === 'multiply') {
    // 接觸陰影（示範素材本身已含陰影）
    ctx.save();
    ctx.filter = `blur(${Math.max(2, d.w * 0.03)}px)`;
    ctx.globalAlpha = 0.18;
    ctx.fillStyle = op.shadow;
    ctx.beginPath();
    ctx.ellipse(d.x + d.w / 2, d.y + d.h * 0.98, d.w * 0.42, d.h * 0.035, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    ctx.globalCompositeOperation = 'multiply';
  }
  ctx.drawImage(product.image, d.x, d.y, d.w, d.h);
  ctx.restore();
}

/** 依 composePoster 的指令畫到 Canvas（座標是輸出圖的像素；呼叫端自行 scale） */
export function paintScene(ctx: Ctx, scene: PosterScene, assets: PaintAssets): void {
  for (const op of scene.ops) {
    switch (op.kind) {
      case 'background':
        ctx.drawImage(assets.background, 0, 0, scene.width, scene.height);
        break;
      case 'product':
        drawProduct(ctx, op, assets.product);
        break;
      case 'logo':
        drawLogo(ctx, op, assets.fonts);
        break;
      case 'text':
        drawText(ctx, op, assets.fonts);
        break;
      case 'pill':
        drawPill(ctx, op);
        break;
      case 'badge':
        drawBadge(ctx, op, assets.fonts);
        break;
    }
  }
}
```

- [ ] **Step 10: 實作 `web/src/lib/compose/render.ts`**

```ts
import type { Brand, Copy, Product, Render } from '@/types/contract';
import { backgroundSvg, svgDataUrl } from './art';
import { fontStacks, productImage } from './assets';
import { boxMap } from './layout';
import { paintScene, type PaintAssets } from './paint';
import { composePoster, type PosterScene, type TextOp } from './scene';

/**
 * 瀏覽器端：準備圖片與字型後把海報畫到 Canvas。預覽與匯出共用。
 * 只能在 client component 的 effect 或事件處理中呼叫（需要 document、Image、Canvas）。
 */

export interface PosterInput {
  render: Render;
  /** 使用者編輯後的文案；不改文案時傳 render.spec.copy */
  copy: Copy;
  /** 商品已刪除時為 null（只畫背景與文字） */
  product: Product | null;
  brand: Brand;
}

export interface PreparedPoster { scene: PosterScene; assets: PaintAssets }

const imageCache = new Map<string, Promise<HTMLImageElement>>();

export function loadImage(src: string): Promise<HTMLImageElement> {
  const hit = imageCache.get(src);
  if (hit) return hit;
  const p = new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image();
    img.decoding = 'async';
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('圖片載入失敗'));
    img.src = src;
  });
  p.catch(() => imageCache.delete(src));
  imageCache.set(src, p);
  // 只保留最近 80 張，避免 data URL 佔滿記憶體
  if (imageCache.size > 80) imageCache.delete(imageCache.keys().next().value!);
  return p;
}

async function ensureFonts(scene: PosterScene, fonts: PaintAssets['fonts']) {
  if (typeof document === 'undefined' || !document.fonts) return;
  const texts = scene.ops.flatMap((op): TextOp[] =>
    op.kind === 'text' ? [op] : op.kind === 'badge' ? op.texts : op.kind === 'logo' && op.wordmark ? [op.wordmark] : [],
  );
  const sample = (role: 'headline' | 'body') => texts.filter((t) => t.role === role).map((t) => t.text).join('') || 'A';
  await Promise.all([
    document.fonts.load(`900 40px ${fonts.headline}`, sample('headline')),
    document.fonts.load(`500 40px ${fonts.body}`, sample('body')),
  ]).catch(() => undefined);
}

export async function preparePoster({ render, copy, product, brand }: PosterInput): Promise<PreparedPoster> {
  const spec = render.spec;
  const scene = composePoster({ canvas: spec.canvas, layout: spec.layout, palette: spec.palette, copy, brand });
  const bg = render.background;
  const bgSrc = bg.kind === 'procedural'
    ? svgDataUrl(backgroundSvg({
      width: spec.canvas.width, height: spec.canvas.height, palette: bg.palette, seed: bg.seed, style: bg.style,
      focus: boxMap(spec.layout).product,
    }))
    : bg.url;
  const prod = product ? productImage(product, brand) : null;
  const fonts = fontStacks(brand);
  const [background, productImg] = await Promise.all([
    loadImage(bgSrc),
    prod ? loadImage(prod.src).catch(() => null) : Promise.resolve(null),
    ensureFonts(scene, fonts),
  ]);
  return {
    scene,
    assets: {
      background,
      product: productImg && prod
        ? { image: productImg, width: productImg.naturalWidth || 500, height: productImg.naturalHeight || 800, blend: prod.blend }
        : null,
      fonts,
    },
  };
}

/** 畫到指定寬度（像素）的 Canvas；高度依模板比例 */
export function paintPoster(canvas: HTMLCanvasElement, { scene, assets }: PreparedPoster, pixelWidth: number): void {
  const scale = pixelWidth / scene.width;
  canvas.width = Math.round(pixelWidth);
  canvas.height = Math.round(scene.height * scale);
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  ctx.clearRect(0, 0, scene.width, scene.height);
  paintScene(ctx, scene, assets);
}

/** 匯出：以模板原始尺寸輸出 PNG */
export async function posterBlob(input: PosterInput): Promise<Blob> {
  const prepared = await preparePoster(input);
  const canvas = document.createElement('canvas');
  paintPoster(canvas, prepared, prepared.scene.width);
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('PNG 輸出失敗'))), 'image/png'),
  );
}
```

- [ ] **Step 11: 實作 `web/src/lib/export/download.ts`**

```ts
/** 瀏覽器端：觸發下載。只能在事件處理中呼叫。 */
export function downloadBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
```

- [ ] **Step 12: 實作 `web/src/lib/export/posters.ts`**

```ts
import type { Brand, Copy, Product, Render } from '@/types/contract';
import { posterBlob } from '@/lib/compose/render';
import { getTemplate } from '@/lib/compose/templates';
import { downloadBlob } from './download';
import { posterFileName, zipFileName } from './naming';
import { buildZip } from './zip';

/** 瀏覽器端匯出（新任務、批次佇列、歷史紀錄共用）。只能在事件處理中呼叫。 */

export interface PosterItem { render: Render; copy: Copy }

const productNameOf = (product: Product | null, items: PosterItem[]) => product?.name ?? items[0]?.copy.productName ?? '商品';

/** 每個模板一張原尺寸 PNG，打包成「品牌_商品_日期.zip」 */
export async function exportPosterZip(brand: Brand, product: Product | null, items: PosterItem[], date = new Date()): Promise<void> {
  const productName = productNameOf(product, items);
  const entries = await Promise.all(items.map(async ({ render, copy }) => ({
    name: posterFileName({ brandName: brand.name, productName, channel: getTemplate(render.templateId).label, date }),
    data: await posterBlob({ render, copy, product, brand }),
  })));
  downloadBlob(await buildZip(entries), zipFileName({ brandName: brand.name, productName, date }));
}

/** 單張 PNG：「品牌_商品_通路_日期.png」 */
export async function exportPosterPng(brand: Brand, product: Product | null, item: PosterItem, date = new Date()): Promise<void> {
  const name = posterFileName({ brandName: brand.name, productName: productNameOf(product, [item]), channel: getTemplate(item.render.templateId).label, date });
  downloadBlob(await posterBlob({ ...item, product, brand }), name);
}
```

- [ ] **Step 13: 執行全部測試、型別檢查與 lint**

Run: `npm run test && npm run typecheck && npm run lint`
Expected: 26 個測試檔、204 個測試 PASS；typecheck 與 lint 無錯誤

- [ ] **Step 14: Commit**

```bash
git add web/package.json web/package-lock.json web/src/lib/compose web/src/lib/export
git commit -m "feat: add canvas painter, poster rendering and zip export" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: 本機商品資料夾 API（`assets/products/`）

**Files:**
- Create: `web/src/lib/server/local-products.ts`、`web/src/app/api/local-products/route.ts`、`web/src/app/api/local-products/[file]/route.ts`
- Test: `web/src/lib/server/local-products.test.ts`

**Interfaces:**
- Produces：
  - `IMAGE_TYPES`。
  - `LOCAL_PRODUCTS_DIR`：`process.cwd()` 是 `web/`，所以指向上一層的 `assets/products`。
  - `interface LocalPhoto { file; name; url; size }`。
  - `localPhotoUrl(file)`。
  - `listLocalPhotos(dir)`：只列圖片並依檔名排序，資料夾不存在時回傳 `[]`。
  - `resolveLocalPhoto(dir, file)`：拒絕斜線、反斜線、`.` 開頭的檔名與非圖片。
  - `GET /api/local-products` 回傳 `{ photos: LocalPhoto[] }`；`GET /api/local-products/[file]` 回傳圖片。兩者在 `NODE_ENV !== 'development'` 時都回傳 404。

- [ ] **Step 1: 寫失敗測試 `web/src/lib/server/local-products.test.ts`**

```ts
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { listLocalPhotos, localPhotoUrl, resolveLocalPhoto } from './local-products';

let dir = '';

beforeAll(async () => {
  dir = await mkdtemp(path.join(tmpdir(), 'local-products-'));
  await writeFile(path.join(dir, 'night_mask-50ml.PNG'), new Uint8Array([1, 2, 3]));
  await writeFile(path.join(dir, 'a-serum.jpg'), new Uint8Array([4]));
  await writeFile(path.join(dir, '.gitkeep'), '');
  await writeFile(path.join(dir, 'notes.txt'), 'x');
  await mkdir(path.join(dir, 'folder.png'));
});
afterAll(() => rm(dir, { recursive: true, force: true }));

describe('listLocalPhotos', () => {
  it('lists image files only, sorted, with names derived from the file name', async () => {
    expect(await listLocalPhotos(dir)).toEqual([
      { file: 'a-serum.jpg', name: 'a serum', url: '/api/local-products/a-serum.jpg', size: 1 },
      { file: 'night_mask-50ml.PNG', name: 'night mask 50ml', url: '/api/local-products/night_mask-50ml.PNG', size: 3 },
    ]);
  });

  it('returns an empty list when the folder does not exist', async () => {
    expect(await listLocalPhotos(path.join(dir, 'missing'))).toEqual([]);
  });

  it('encodes file names in URLs', () => {
    expect(localPhotoUrl('晚安 面膜.png')).toBe('/api/local-products/%E6%99%9A%E5%AE%89%20%E9%9D%A2%E8%86%9C.png');
  });
});

describe('resolveLocalPhoto', () => {
  it('resolves image files inside the folder', () => {
    expect(resolveLocalPhoto(dir, 'a-serum.jpg')).toEqual({ path: path.join(dir, 'a-serum.jpg'), type: 'image/jpeg' });
  });

  it('rejects traversal, sub-paths, hidden and non-image files', () => {
    for (const bad of ['../secret.png', '..\\secret.png', 'sub/x.png', '.hidden.png', 'notes.txt', '']) {
      expect(resolveLocalPhoto(dir, bad), bad).toBeNull();
    }
  });
});
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `npx vitest run src/lib/server`
Expected: FAIL，找不到 `./local-products`

- [ ] **Step 3: 實作 `web/src/lib/server/local-products.ts`**

```ts
import { readdir, stat } from 'node:fs/promises';
import path from 'node:path';

/** 只在伺服器端（Route Handler）使用：讀取 repo 根目錄 assets/products/ 的商品照 */

export const IMAGE_TYPES: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
};

/** next dev 的工作目錄是 web/，商品照放在上一層的 assets/products/ */
export const LOCAL_PRODUCTS_DIR = path.resolve(process.cwd(), '..', 'assets', 'products');

export interface LocalPhoto {
  file: string;
  /** 檔名去掉副檔名，底線與連字號換成空白 */
  name: string;
  url: string;
  size: number;
}

export const localPhotoUrl = (file: string) => `/api/local-products/${encodeURIComponent(file)}`;

/** 列出資料夾內的圖片（依檔名排序）；資料夾不存在時回傳空陣列 */
export async function listLocalPhotos(dir: string): Promise<LocalPhoto[]> {
  let files: string[];
  try {
    files = await readdir(dir);
  } catch {
    return [];
  }
  const photos: LocalPhoto[] = [];
  for (const file of files.sort()) {
    const ext = path.extname(file).toLowerCase();
    if (!IMAGE_TYPES[ext]) continue;
    const info = await stat(path.join(dir, file));
    if (!info.isFile()) continue;
    photos.push({ file, name: path.basename(file, path.extname(file)).replace(/[_-]+/g, ' ').trim(), url: localPhotoUrl(file), size: info.size });
  }
  return photos;
}

/** 檔名 → 絕對路徑與 MIME。拒絕子目錄、路徑穿越與非圖片檔。 */
export function resolveLocalPhoto(dir: string, file: string): { path: string; type: string } | null {
  if (!file || /[\\/]/.test(file) || file.startsWith('.')) return null;
  const type = IMAGE_TYPES[path.extname(file).toLowerCase()];
  if (!type) return null;
  const full = path.resolve(dir, file);
  return path.dirname(full) === path.resolve(dir) ? { path: full, type } : null;
}
```

- [ ] **Step 4: 執行測試確認通過**

Run: `npx vitest run src/lib/server`
Expected: 5 個測試 PASS

- [ ] **Step 5: 建立 `web/src/app/api/local-products/route.ts`**

```ts
import { LOCAL_PRODUCTS_DIR, listLocalPhotos } from '@/lib/server/local-products';

/** 開發用：列出 assets/products/ 的商品照。正式環境回傳 404。 */
export async function GET() {
  if (process.env.NODE_ENV !== 'development') return new Response('Not found', { status: 404 });
  return Response.json({ photos: await listLocalPhotos(LOCAL_PRODUCTS_DIR) });
}
```

- [ ] **Step 6: 建立 `web/src/app/api/local-products/[file]/route.ts`**

Next 16 的動態參數是 Promise；`RouteContext` 由 `next typegen` 產生，不需要 import。

```ts
import { readFile } from 'node:fs/promises';
import type { NextRequest } from 'next/server';
import { LOCAL_PRODUCTS_DIR, resolveLocalPhoto } from '@/lib/server/local-products';

/** 開發用：讀取 assets/products/ 的單張商品照。正式環境回傳 404。 */
export async function GET(_req: NextRequest, ctx: RouteContext<'/api/local-products/[file]'>) {
  if (process.env.NODE_ENV !== 'development') return new Response('Not found', { status: 404 });
  const { file } = await ctx.params;
  const hit = resolveLocalPhoto(LOCAL_PRODUCTS_DIR, file);
  if (!hit) return new Response('Not found', { status: 404 });
  try {
    const bytes = await readFile(hit.path);
    return new Response(new Uint8Array(bytes), { headers: { 'Content-Type': hit.type, 'Cache-Control': 'no-store' } });
  } catch {
    return new Response('Not found', { status: 404 });
  }
}
```

- [ ] **Step 7: 型別檢查**

Run: `npm run typecheck`
Expected: 無錯誤（route 實際行為在 Task 13 從商品庫頁驗證）

- [ ] **Step 8: Commit**

```bash
git add web/src/lib/server web/src/app/api
git commit -m "feat: serve local product photos in development" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: UI 基礎：shadcn/ui、字型、App Shell、Demo 控制台

**Files:**
- Create（CLI 產生）：`web/components.json`、`web/src/lib/utils.ts`、`web/src/components/ui/*`
- Create：`web/src/lib/store/app.ts`、`web/src/components/layout/{nav.ts,connection-badge.tsx,brand-switcher.tsx,demo-console.tsx,top-bar.tsx,side-nav.tsx,app-shell.tsx}`、`web/src/components/common/{page-header.tsx,empty-state.tsx}`、`web/src/components/agent/agent-preview.tsx`、`web/src/app/{studio,products,queue,history,brands,agent,dashboard}/page.tsx`
- Modify：`web/src/app/globals.css`、`web/src/app/layout.tsx`、`web/src/app/page.tsx`

**Interfaces:**
- Consumes：`getApiClient`、`API_MODE`（Task 3）；`emptyJobView`、`reduceJob`、`jobProgress`、`STAGE_LABEL`（Task 4）
- Produces：
  - `useAppStore`：狀態 `brandId`、`brands`、`setBrandId`、`loadBrands`；`brandId` 存在 localStorage，key 為 `genai-agent:app`，使用 `skipHydration`。
  - `useCurrentBrand()`：AppShell 在品牌載入前不 render 頁面，所以一定有值。
  - `NAV`、`modeOf(pathname)`、`isActive(pathname, href)`。
  - 元件：`PageHeader`、`EmptyState`、`AppShell`、`DemoConsole`。

- [ ] **Step 1: 初始化 shadcn/ui 並加入元件**

```bash
npx -y shadcn@4.21.3 init -t next -b radix -p nova --no-monorepo --no-rtl -y
npx -y shadcn@4.21.3 add badge card checkbox dialog input label select separator switch tabs textarea tooltip progress sonner toggle-group alert popover -y
```

Expected：
- 產生 `components.json`、`src/lib/utils.ts`（re-export `cn` 套件）與 `src/components/ui/` 下 19 個元件（含相依的 `button`、`toggle`）。
- `package.json` 加入 `radix-ui`、`class-variance-authority`、`cn`、`lucide-react`、`sonner`、`next-themes`、`shadcn`、`tw-animate-css`。
- `src/app/globals.css` 被改寫，下一步會整份取代。

- [ ] **Step 2: 安裝 Zustand 與字型**

```bash
npm i zustand@^5.0.15 @fontsource-variable/noto-sans-tc@^5.3.0 @fontsource-variable/noto-serif-tc@^5.3.0
```

- [ ] **Step 3: 取代 `web/src/app/globals.css`**

```css
@import "tailwindcss";
@import "tw-animate-css";
@import "shadcn/tailwind.css";

@custom-variant dark (&:is(.dark *));

/* 淺色 SaaS 風格（沿用 prototype/index.html 的色彩） */
@theme inline {
  --font-sans: "Noto Sans TC Variable", "Noto Sans TC", "Microsoft JhengHei", "PingFang TC", system-ui, sans-serif;
  --font-serif: "Noto Serif TC Variable", "Noto Serif TC", serif;
  --font-mono: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
  --font-heading: var(--font-sans);
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-success: var(--success);
  --color-warning: var(--warning);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --color-chart-1: var(--chart-1);
  --color-chart-2: var(--chart-2);
  --color-chart-3: var(--chart-3);
  --color-chart-4: var(--chart-4);
  --color-chart-5: var(--chart-5);
  --color-sidebar: var(--sidebar);
  --color-sidebar-foreground: var(--sidebar-foreground);
  --color-sidebar-primary: var(--sidebar-primary);
  --color-sidebar-primary-foreground: var(--sidebar-primary-foreground);
  --color-sidebar-accent: var(--sidebar-accent);
  --color-sidebar-accent-foreground: var(--sidebar-accent-foreground);
  --color-sidebar-border: var(--sidebar-border);
  --color-sidebar-ring: var(--sidebar-ring);
  --radius-sm: calc(var(--radius) * 0.6);
  --radius-md: calc(var(--radius) * 0.8);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) * 1.4);
  --radius-2xl: calc(var(--radius) * 1.8);
  --radius-3xl: calc(var(--radius) * 2.2);
  --radius-4xl: calc(var(--radius) * 2.6);
}

:root {
  --radius: 0.75rem;
  --background: #f5f6fa;
  --foreground: #1c2030;
  --card: #ffffff;
  --card-foreground: #1c2030;
  --popover: #ffffff;
  --popover-foreground: #1c2030;
  --primary: #4f46e5;
  --primary-foreground: #ffffff;
  --secondary: #eef0ff;
  --secondary-foreground: #3730a3;
  --muted: #f1f3f8;
  --muted-foreground: #6b7189;
  --accent: #eef0ff;
  --accent-foreground: #4338ca;
  --destructive: #dc2626;
  --success: #16a34a;
  --warning: #d97706;
  --border: #e6e8f0;
  --input: #d3d7e3;
  --ring: #a5b4fc;
  --chart-1: #4f46e5;
  --chart-2: #0d9488;
  --chart-3: #d97706;
  --chart-4: #db2777;
  --chart-5: #64748b;
  --sidebar: #ffffff;
  --sidebar-foreground: #4b5168;
  --sidebar-primary: #4f46e5;
  --sidebar-primary-foreground: #ffffff;
  --sidebar-accent: #eef0ff;
  --sidebar-accent-foreground: #4338ca;
  --sidebar-border: #e6e8f0;
  --sidebar-ring: #a5b4fc;
}

@layer base {
  * {
    @apply border-border outline-ring/50;
  }
  html {
    @apply font-sans;
  }
  body {
    @apply bg-background text-foreground antialiased;
  }
}

/* 去背預覽用的透明格紋 */
.bg-checker {
  background-color: #ffffff;
  background-image:
    linear-gradient(45deg, #e9ebf2 25%, transparent 25%), linear-gradient(-45deg, #e9ebf2 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #e9ebf2 75%), linear-gradient(-45deg, transparent 75%, #e9ebf2 75%);
  background-size: 16px 16px;
  background-position: 0 0, 0 8px, 8px -8px, -8px 0;
}
```

- [ ] **Step 4: 建立 `web/src/lib/store/app.ts`**

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
export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      brandId: 'selune',
      brands: [],
      setBrandId: (brandId) => set({ brandId }),
      loadBrands: async () => {
        set({ brands: await getApiClient().listBrands() });
      },
    }),
    // skipHydration：伺服器 render 用預設值，等 AppShell 掛載後才讀 localStorage，避免 hydration 不一致
    { name: 'genai-agent:app', partialize: (s) => ({ brandId: s.brandId }), skipHydration: true },
  ),
);

/** 目前品牌；AppShell 在品牌載入前不會 render 頁面，所以頁面內可視為一定有值 */
export function useCurrentBrand(): Brand {
  return useAppStore((s) => s.brands.find((b) => b.id === s.brandId) ?? s.brands[0]);
}
```

- [ ] **Step 5: 建立 `web/src/components/layout/nav.ts`**

```ts
import type { LucideIcon } from 'lucide-react';
import { BookOpen, ChartColumn, Clock, ListOrdered, Network, Package, WandSparkles } from 'lucide-react';

export type AppMode = 'workbench' | 'agent';
export interface NavItem { href: string; label: string; icon: LucideIcon }

export const NAV: Record<AppMode, NavItem[]> = {
  workbench: [
    { href: '/studio', label: '新任務', icon: WandSparkles },
    { href: '/products', label: '商品庫', icon: Package },
    { href: '/queue', label: '批次佇列', icon: ListOrdered },
    { href: '/history', label: '歷史紀錄', icon: Clock },
    { href: '/brands', label: '品牌知識庫', icon: BookOpen },
  ],
  agent: [
    { href: '/agent', label: '任務透視', icon: Network },
    { href: '/dashboard', label: '成效儀表板', icon: ChartColumn },
  ],
};

export const modeOf = (pathname: string): AppMode =>
  NAV.agent.some((item) => pathname.startsWith(item.href)) ? 'agent' : 'workbench';

export const isActive = (pathname: string, href: string) => pathname === href || pathname.startsWith(`${href}/`);
```

- [ ] **Step 6: 建立 `web/src/components/layout/connection-badge.tsx`**

```tsx
'use client';

import { useSyncExternalStore } from 'react';
import type { ConnectionState } from '@/types/contract';
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

export function ConnectionBadge() {
  const state = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return (
    <span
      className="inline-flex h-7 items-center gap-2 rounded-full border bg-card px-2.5 text-xs text-muted-foreground sm:px-3"
      title={state.error ?? undefined}
    >
      <span className={cn('size-1.5 rounded-full', DOT[state.status])} />
      <span className="hidden sm:inline">{LABEL[state.status]}</span>
      <span className="hidden font-mono text-[11px] opacity-70 sm:inline">{state.transport}</span>
    </span>
  );
}
```

- [ ] **Step 7: 建立 `web/src/components/layout/brand-switcher.tsx`**

```tsx
'use client';

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useAppStore } from '@/lib/store/app';

export function BrandSwitcher() {
  const brands = useAppStore((s) => s.brands);
  const brandId = useAppStore((s) => s.brandId);
  const setBrandId = useAppStore((s) => s.setBrandId);
  return (
    <Select value={brands.length ? brandId : ''} onValueChange={setBrandId} disabled={!brands.length}>
      <SelectTrigger size="sm" className="w-36 bg-card sm:w-52" aria-label="切換品牌">
        <SelectValue placeholder="載入品牌…" />
      </SelectTrigger>
      <SelectContent align="end">
        {brands.map((b) => (
          <SelectItem key={b.id} value={b.id}>
            <span className="size-2.5 rounded-full" style={{ background: b.palette.primary }} />
            {b.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
```

- [ ] **Step 8: 建立 `web/src/components/layout/demo-console.tsx`**

```tsx
'use client';

import { useState } from 'react';
import { FlaskConical } from 'lucide-react';
import type { DemoOptions } from '@/types/contract';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Switch } from '@/components/ui/switch';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { API_MODE, getApiClient } from '@/lib/api';

const SPEEDS = [1, 2, 4] as const;

/** 畫面右下角的 Demo 控制台（只有 mock 模式） */
export function DemoConsole() {
  const [options, setOptions] = useState<DemoOptions | null>(null);
  if (API_MODE !== 'mock') return null;

  const update = (patch: Partial<DemoOptions>) => {
    const demo = getApiClient().demo;
    if (!demo) return;
    demo.set(patch);
    setOptions(demo.get());
  };

  return (
    <Popover onOpenChange={(open) => open && setOptions(getApiClient().demo?.get() ?? null)}>
      <PopoverTrigger asChild>
        <Button size="lg" className="fixed right-4 bottom-4 z-40 rounded-full shadow-lg" aria-label="開啟 Demo 控制台">
          <FlaskConical />
          Demo
        </Button>
      </PopoverTrigger>
      <PopoverContent side="top" align="end" className="w-80">
        <div className="space-y-4">
          <div>
            <p className="font-semibold">Demo 控制台</p>
            <p className="text-xs text-muted-foreground">瀏覽器內模擬整條 Agent 流程，事件格式與 FastAPI WebSocket 相同。</p>
          </div>
          <div className="space-y-2">
            <Label>播放速度（立即生效）</Label>
            <ToggleGroup
              type="single"
              variant="outline"
              spacing={0}
              value={String(options?.speed ?? 1)}
              onValueChange={(v) => v && update({ speed: Number(v) as DemoOptions['speed'] })}
            >
              {SPEEDS.map((s) => (
                <ToggleGroupItem key={s} value={String(s)} className="w-14">
                  {s}×
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
          <div className="flex items-center justify-between gap-3">
            <Label htmlFor="demo-first-fail" className="flex-col items-start gap-0.5">
              強制首輪失敗
              <span className="text-xs font-normal text-muted-foreground">展示 Query Rewriting 與重試</span>
            </Label>
            <Switch
              id="demo-first-fail"
              checked={options?.firstRoundFail ?? true}
              onCheckedChange={(v) => update({ firstRoundFail: v })}
            />
          </div>
          <div className="flex items-center justify-between gap-3">
            <Label htmlFor="demo-all-fail" className="flex-col items-start gap-0.5">
              強制全部失敗
              <span className="text-xs font-normal text-muted-foreground">展示「需人工審核」</span>
            </Label>
            <Switch id="demo-all-fail" checked={options?.forceAllFail ?? false} onCheckedChange={(v) => update({ forceAllFail: v })} />
          </div>
          <p className="text-xs text-muted-foreground">失敗設定從下一個任務開始生效。</p>
        </div>
      </PopoverContent>
    </Popover>
  );
}
```

- [ ] **Step 9: 建立 `web/src/components/layout/top-bar.tsx`**

```tsx
'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { LayoutGrid, Network, Sparkles } from 'lucide-react';
import { API_MODE } from '@/lib/api';
import { cn } from '@/lib/utils';
import { BrandSwitcher } from './brand-switcher';
import { ConnectionBadge } from './connection-badge';
import { modeOf } from './nav';

const MODES = [
  { mode: 'workbench', href: '/studio', label: '工作台', icon: LayoutGrid },
  { mode: 'agent', href: '/agent', label: 'Agent 透視', icon: Network },
] as const;

export function TopBar() {
  const pathname = usePathname();
  const current = modeOf(pathname);
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-card/90 px-3 backdrop-blur sm:gap-3 md:px-6">
      <Link href="/studio" className="flex items-center gap-2.5">
        <span className="grid size-8 place-items-center rounded-[10px] bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500 text-white shadow-md shadow-indigo-500/30">
          <Sparkles className="size-4" />
        </span>
        <span className="hidden leading-tight lg:block">
          <span className="block text-sm font-bold">虛實整合 GenAI Agent</span>
          <span className="block text-xs text-muted-foreground">真實商品照 × AI 背景 × 品牌合規</span>
        </span>
      </Link>

      <nav className="flex rounded-[10px] border bg-muted p-0.5 sm:ml-2" aria-label="模式切換">
        {MODES.map(({ mode, href, label, icon: Icon }) => (
          <Link
            key={mode}
            href={href}
            aria-current={current === mode ? 'page' : undefined}
            className={cn(
              'flex items-center gap-1.5 rounded-lg px-3 py-1 text-sm text-muted-foreground transition-colors',
              current === mode && 'bg-card font-semibold text-primary shadow-sm',
            )}
          >
            <Icon className="size-4" />
            <span className="hidden sm:inline">{label}</span>
          </Link>
        ))}
      </nav>

      <div className="ml-auto flex items-center gap-2">
        <BrandSwitcher />
        {API_MODE === 'mock' && (
          <span className="hidden h-7 items-center rounded-full border border-amber-200 bg-amber-50 px-3 text-xs font-medium text-amber-800 md:inline-flex">
            Demo 模式
          </span>
        )}
        <ConnectionBadge />
      </div>
    </header>
  );
}
```

- [ ] **Step 10: 建立 `web/src/components/layout/side-nav.tsx`**

```tsx
'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import { isActive, modeOf, NAV } from './nav';

/** 桌面版是左側選單；手機版是頂列下方可橫向捲動的分頁 */
export function SideNav() {
  const pathname = usePathname();
  const items = NAV[modeOf(pathname)];
  return (
    <nav
      aria-label="頁面"
      className="flex gap-1 overflow-x-auto border-b bg-card px-3 py-2 md:sticky md:top-14 md:h-[calc(100vh-3.5rem)] md:w-52 md:shrink-0 md:flex-col md:border-r md:border-b-0 md:px-3 md:py-4"
    >
      {items.map(({ href, label, icon: Icon }) => {
        const active = isActive(pathname, href);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-sidebar-foreground transition-colors hover:bg-muted',
              active && 'bg-sidebar-accent font-semibold text-sidebar-accent-foreground hover:bg-sidebar-accent',
            )}
          >
            <Icon className="size-4" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
```

- [ ] **Step 11: 建立 `web/src/components/layout/app-shell.tsx`**

```tsx
'use client';

import { useEffect } from 'react';
import { LoaderCircle } from 'lucide-react';
import { useAppStore } from '@/lib/store/app';
import { DemoConsole } from './demo-console';
import { SideNav } from './side-nav';
import { TopBar } from './top-bar';

export function AppShell({ children }: { children: React.ReactNode }) {
  const ready = useAppStore((s) => s.brands.length > 0);

  useEffect(() => {
    void useAppStore.persist.rehydrate();
    void useAppStore.getState().loadBrands();
  }, []);

  return (
    <div className="min-h-screen">
      <TopBar />
      <div className="mx-auto flex max-w-[1680px] flex-col md:flex-row">
        <SideNav />
        <main className="min-w-0 flex-1 px-4 pt-5 pb-24 md:px-6">
          {ready ? (
            children
          ) : (
            <div className="grid h-64 place-items-center text-muted-foreground">
              <LoaderCircle className="size-6 animate-spin" aria-label="載入中" />
            </div>
          )}
        </main>
      </div>
      <DemoConsole />
    </div>
  );
}
```

- [ ] **Step 12: 建立 `web/src/components/common/page-header.tsx`**

```tsx
export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-bold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
```

- [ ] **Step 13: 建立 `web/src/components/common/empty-state.tsx`**

```tsx
import type { LucideIcon } from 'lucide-react';

export function EmptyState({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed bg-card px-6 py-12 text-center">
      <Icon className="size-8 text-muted-foreground/60" />
      <p className="font-semibold">{title}</p>
      {children && <div className="max-w-md text-sm text-muted-foreground">{children}</div>}
    </div>
  );
}
```

- [ ] **Step 14: 取代 `web/src/app/layout.tsx`**

```tsx
import type { Metadata } from 'next';
import '@fontsource-variable/noto-sans-tc';
import '@fontsource-variable/noto-serif-tc';
import './globals.css';
import { AppShell } from '@/components/layout/app-shell';
import { Toaster } from '@/components/ui/sonner';
import { TooltipProvider } from '@/components/ui/tooltip';

export const metadata: Metadata = {
  title: '虛實整合 GenAI Agent',
  description: '保留真實商品照，AI 生成背景、排版引擎疊字、RAG 品牌合規審查，一次輸出多通路尺寸。',
};

export default function RootLayout({ children }: LayoutProps<'/'>) {
  return (
    <html lang="zh-Hant">
      <body>
        <TooltipProvider>
          <AppShell>{children}</AppShell>
        </TooltipProvider>
        <Toaster theme="light" position="top-center" richColors />
      </body>
    </html>
  );
}
```

- [ ] **Step 15: 取代 `web/src/app/page.tsx`**

```tsx
import { redirect } from 'next/navigation';

export default function Home() {
  redirect('/studio');
}
```

- [ ] **Step 16: 建立 `web/src/app/studio/page.tsx`**（暫時頁面，Task 10 取代）

```tsx
import { PageHeader } from '@/components/common/page-header';

export default function Page() {
  return <PageHeader title="新任務" description="建置中" />;
}
```

- [ ] **Step 17: 建立 `web/src/app/products/page.tsx`**（暫時頁面，Task 13 取代）

```tsx
import { PageHeader } from '@/components/common/page-header';

export default function Page() {
  return <PageHeader title="商品庫" description="建置中" />;
}
```

- [ ] **Step 18: 建立 `web/src/app/queue/page.tsx`**（暫時頁面，Task 14 取代）

```tsx
import { PageHeader } from '@/components/common/page-header';

export default function Page() {
  return <PageHeader title="批次佇列" description="建置中" />;
}
```

- [ ] **Step 19: 建立 `web/src/app/history/page.tsx`**（暫時頁面，Task 15 取代）

```tsx
import { PageHeader } from '@/components/common/page-header';

export default function Page() {
  return <PageHeader title="歷史紀錄" description="建置中" />;
}
```

- [ ] **Step 20: 建立 `web/src/app/brands/page.tsx`**（暫時頁面，Task 16 取代）

```tsx
import { PageHeader } from '@/components/common/page-header';

export default function Page() {
  return <PageHeader title="品牌知識庫" description="建置中" />;
}
```

- [ ] **Step 21: 建立 `web/src/components/agent/agent-preview.tsx`**（`/agent` 簡易版：選任務、看事件 Log）

```tsx
'use client';

import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Network } from 'lucide-react';
import type { JobSummary } from '@/types/contract';
import { EmptyState } from '@/components/common/empty-state';
import { PageHeader } from '@/components/common/page-header';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { getApiClient } from '@/lib/api';
import { emptyJobView, jobProgress, reduceJob, STAGE_LABEL } from '@/lib/jobs/view';
import { cn } from '@/lib/utils';

const LEVEL_COLOR = { info: 'text-slate-300', ok: 'text-emerald-300', warn: 'text-amber-300', error: 'text-red-300' } as const;

function JobLog({ jobId }: { jobId: string }) {
  const [view, setView] = useState(() => emptyJobView(jobId));
  useEffect(() => getApiClient().subscribe(jobId, (e) => setView((v) => reduceJob(v, e))), [jobId]);
  return (
    <Card>
      <CardHeader className="flex flex-row items-center gap-3">
        <CardTitle className="font-mono text-sm">{jobId}</CardTitle>
        <Badge variant="secondary">{view.stage ? STAGE_LABEL[view.stage] : '等待中'}</Badge>
        {view.round > 0 && <span className="text-xs text-muted-foreground">第 {view.round} 輪</span>}
      </CardHeader>
      <CardContent className="space-y-3">
        <Progress value={jobProgress(view) * 100} />
        <div className="max-h-[60vh] overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-xs leading-relaxed">
          {view.logs.map((l, i) => (
            <div key={i} className={LEVEL_COLOR[l.level]}>
              <span className="mr-2 text-slate-500">[{l.source.toUpperCase()}]</span>
              {l.message}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

/** Plan 2 的簡易版：選任務、看事件 Log。完整的任務透視在 Plan 3。 */
export function AgentPreview() {
  const router = useRouter();
  const params = useSearchParams();
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  useEffect(() => {
    void getApiClient().listJobs().then(setJobs);
  }, []);
  const jobId = params.get('job') ?? jobs?.[0]?.id ?? null;

  return (
    <>
      <PageHeader
        title="任務透視"
        description="流程節點圖、JSON Prompt、注入參數、RAG Rerank、BBox 疊圖與重試 diff 將在 Plan 3 完成；目前先顯示事件 Log。"
        actions={
          jobs && jobs.length > 0 ? (
            <Select value={jobId ?? ''} onValueChange={(id) => router.replace(`/agent?job=${encodeURIComponent(id)}`)}>
              <SelectTrigger className="w-72 bg-card">
                <SelectValue placeholder="選擇任務" />
              </SelectTrigger>
              <SelectContent>
                {jobs.map((j) => (
                  <SelectItem key={j.id} value={j.id}>
                    <span className="font-mono text-xs">{j.id}</span>
                    <span className={cn('text-xs', j.finished ? 'text-muted-foreground' : 'text-primary')}>{STAGE_LABEL[j.stage]}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : null
        }
      />
      {jobId ? (
        <JobLog key={jobId} jobId={jobId} />
      ) : (
        <EmptyState icon={Network} title="還沒有任務">到「新任務」開始生成後，這裡會顯示 Agent 的每一步。</EmptyState>
      )}
    </>
  );
}
```

- [ ] **Step 22: 建立 `web/src/app/agent/page.tsx`**

```tsx
import { Suspense } from 'react';
import { AgentPreview } from '@/components/agent/agent-preview';

export default function AgentPage() {
  // useSearchParams 需要 Suspense，否則 next build 會失敗
  return (
    <Suspense>
      <AgentPreview />
    </Suspense>
  );
}
```

- [ ] **Step 23: 建立 `web/src/app/dashboard/page.tsx`**

```tsx
import { ChartColumn } from 'lucide-react';
import { EmptyState } from '@/components/common/empty-state';
import { PageHeader } from '@/components/common/page-header';

export default function DashboardPage() {
  return (
    <>
      <PageHeader title="成效儀表板" description="通過率、平均重試次數、平均耗時、每張成本與各檢查項失敗分布。" />
      <EmptyState icon={ChartColumn} title="Plan 3 實作">儀表板會依歷史任務的事件統計，並比較有無 Rerank 的命中率。</EmptyState>
    </>
  );
}
```

- [ ] **Step 24: 型別檢查、lint 與建置**

Run: `npm run typecheck && npm run lint && npm run build`
Expected：
- 三者都沒有錯誤。
- 建置的路由表包含 `/`、`/agent`、`/brands`、`/dashboard`、`/history`、`/products`、`/queue`、`/studio`（○ 靜態），以及 `/api/local-products`、`/api/local-products/[file]`（ƒ 動態）。

- [ ] **Step 25: 手動確認**

Run: `npm run dev`，開啟 http://localhost:3000

Expected：
- 自動導向 `/studio`。
- 頂列有標誌、「工作台／Agent 透視」切換、品牌選單（SÉLUNE 晞月、霧嶼咖啡 MISTY ISLE）、「Demo 模式」與「WebSocket 已連線 mock」。
- 左側選單可切換五個工作台頁面；切到 Agent 透視時選單換成「任務透視、成效儀表板」。
- 右下角「Demo」打開後可切換 1×／2×／4× 與兩個開關。
- 重新整理後仍記得上次選的品牌。
- 寬度 375px 時頁面沒有水平捲軸。
- Console 沒有 hydration 錯誤。

- [ ] **Step 26: Commit**

```bash
git add web
git commit -m "feat: add app shell with mode switch, brand switcher and demo console" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: 新任務 ①：商品與任務 store、需求表單

**Files:**
- Create: `web/src/lib/store/products.ts`、`web/src/lib/store/studio.ts`、`web/src/components/product/product-image.tsx`、`web/src/components/studio/brief-panel.tsx`
- Modify: `web/src/app/studio/page.tsx`（取代暫時頁面）
- Test: `web/src/lib/store/studio.test.ts`

**Interfaces:**
- Consumes：`getApiClient`（Task 3）；`reduceJob`、`emptyJobView`、`defaultSelection`（Task 4）；`productImage`（Task 7）；`CHANNEL_TEMPLATES`（Plan 1）
- Produces：
  - `useProductsStore`：狀態 `brandId`、`products`、`loading`、`cutting`；方法 `load(brandId)`、`save(draft)`、`remove(id)`、`cutout(id)`。
  - `useStudioStore`：
    - 表單欄位 `brief`、`productId`、`parsed`、`templateIds`、`variants`、`llm`、`engine`、`vlm`、`maxRetries`。
    - 任務狀態 `brandId`、`parsing`、`starting`、`input`、`view`、`selection`、`copy`、`saved`、`error`。
    - 動作：
      - `setForm`、`patchParsed`、`toggleTemplate`、`resetForBrand(brandId)`、`prefill(input)`。
      - `parse()`、`start()`、`cancel()`、`select(templateId, renderId)`、`setCopy(copy)`。
      - `saveSelection()`：回傳新寫入歷史的筆數。
    - 任務結束時自動設定 `selection` 與 `copy`。
  - 常數 `LLM_OPTIONS`、`VLM_OPTIONS`、`ENGINE_LABEL`、`TONE_LABEL`、`DEMO_BRIEFS`。
  - 元件 `ProductImage`、`BriefPanel`。

- [ ] **Step 1: 建立 `web/src/lib/store/products.ts`**

```ts
import { create } from 'zustand';
import type { Product } from '@/types/contract';
import { getApiClient, type ProductDraft } from '@/lib/api';

interface ProductsState {
  brandId: string | null;
  products: Product[];
  loading: boolean;
  load: (brandId: string) => Promise<void>;
  save: (draft: ProductDraft) => Promise<Product>;
  remove: (id: string) => Promise<void>;
  /** 去背進行中的商品 id */
  cutting: string[];
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

- [ ] **Step 2: 寫失敗測試 `web/src/lib/store/studio.test.ts`**

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getApiClient } from '@/lib/api';
import { DEMO_BRIEFS, useStudioStore } from './studio';

const store = () => useStudioStore.getState();

beforeEach(() => {
  vi.useFakeTimers();
  getApiClient().demo?.set({ speed: 1, firstRoundFail: true, forceAllFail: false });
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
    await store().parse();
    expect(store().parsed).toMatchObject({ campaign: '週年慶', offer: '買一送一', tone: 'gentle' });
    store().patchParsed({ audience: '25–35 歲上班族' });
    expect(store().parsed!.audience).toBe('25–35 歲上班族');
  });

  it('runs a job, then selects the best render and loads its copy into the editor', async () => {
    await store().start();
    expect(store().view!.outcome).toBe('running');
    expect(store().input!.templateIds).toEqual(['ig-post']);
    await vi.advanceTimersByTimeAsync(14_500);
    const { view, selection, copy } = store();
    expect(view!.outcome).toBe('done');
    expect(selection['ig-post']).toBe(view!.bestRenderIds['ig-post']);
    expect(copy).toEqual(view!.renders[selection['ig-post']!].spec.copy);
    expect(Object.isFrozen(copy)).toBe(false);
  });

  it('writes the selection to history once per copy version', async () => {
    store().setForm({ templateIds: ['ig-post', 'story'] });
    await store().start();
    await vi.advanceTimersByTimeAsync(14_500);
    const before = (await getApiClient().listHistory('selune')).length;
    expect(await store().saveSelection()).toBe(2);
    expect(await store().saveSelection()).toBe(0);
    store().setCopy({ ...store().copy!, subhead: '改過的副標' });
    expect(await store().saveSelection()).toBe(2);
    const history = await getApiClient().listHistory('selune');
    expect(history.length - before).toBe(4);
    expect(history[0].copy.subhead).toBe('改過的副標');
  });

  it('validates the form before starting', async () => {
    store().setForm({ templateIds: [] });
    await store().start();
    expect(store().error).toBe('至少要選一個通路模板');
    expect(store().view).toBeNull();
  });

  it('cancels a running job', async () => {
    await store().start();
    await vi.advanceTimersByTimeAsync(2_000);
    await store().cancel();
    expect(store().view!.outcome).toBe('cancelled');
  });

  it('stops listening to the old job when the brand changes', async () => {
    await store().start();
    store().resetForBrand('misty-isle');
    await vi.advanceTimersByTimeAsync(14_500);
    expect(store().view).toBeNull();
    expect(store().brief).toBe(DEMO_BRIEFS['misty-isle']);
  });

  it('prefills the form from a previous job input', async () => {
    await store().parse();
    const input = {
      brandId: 'selune', productId: 'prod_selune_serum', brief: '再做一次', parsedBrief: store().parsed!,
      templateIds: ['story' as const], variantsPerTemplate: 2, llm: 'Gemini 3.7 Flash', engine: 'ideogram' as const,
      vlm: 'Gemini 3.7 Vision', maxRetries: 1,
    };
    store().prefill(input);
    expect(store()).toMatchObject({ brief: '再做一次', templateIds: ['story'], variants: 2, engine: 'ideogram', maxRetries: 1, view: null });
  });
});
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `npx vitest run src/lib/store`
Expected: FAIL，找不到 `./studio`

- [ ] **Step 4: 實作 `web/src/lib/store/studio.ts`**

```ts
import { create } from 'zustand';
import type { Copy, Engine, JobInput, ParsedBrief, TemplateId, Tone } from '@/types/contract';
import { getApiClient } from '@/lib/api';
import { defaultSelection, emptyJobView, reduceJob, type JobView } from '@/lib/jobs/view';

export const LLM_OPTIONS = ['Gemini 3.7 Flash', 'Llama 3.2 Vision（Unsloth 微調）'];
export const VLM_OPTIONS = ['Gemini 3.7 Vision', 'Llama 3.2 Vision（Unsloth 微調）'];
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

const DEFAULT_FORM: Omit<StudioForm, 'brief'> = {
  productId: null, parsed: null, templateIds: ['ecom-main', 'ig-post'], variants: 4,
  llm: LLM_OPTIONS[0], engine: 'comfyui', vlm: VLM_OPTIONS[0], maxRetries: 2,
};

/** 事件訂閱放在 store 外：換頁再回來，生成仍在進行 */
let stopListening: (() => void) | null = null;
const stop = () => {
  stopListening?.();
  stopListening = null;
};

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

export const useStudioStore = create<StudioState>()((set, get) => ({
  ...DEFAULT_FORM,
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
      ...DEFAULT_FORM, brandId, brief: DEMO_BRIEFS[brandId] ?? '', parsing: false, starting: false,
      input: null, view: null, selection: {}, copy: null, saved: {}, error: null,
    });
  },

  prefill: (input) => {
    stop();
    set({
      brandId: input.brandId, brief: input.brief, productId: input.productId, parsed: structuredClone(input.parsedBrief),
      templateIds: [...input.templateIds], variants: input.variantsPerTemplate, llm: input.llm, engine: input.engine,
      vlm: input.vlm, maxRetries: input.maxRetries, input: null, view: null, selection: {}, copy: null, saved: {}, error: null,
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
      set({ parsed, input, view: emptyJobView(jobId), selection: {}, copy: null, saved: {} });
      stopListening = api.subscribe(
        jobId,
        (e) =>
          set((st) => {
            if (!st.view || st.view.jobId !== jobId) return {};
            const view = reduceJob(st.view, e);
            // 任務結束（完成或需人工審核）時：預設選最佳候選，文案編輯器帶入它的文案
            if (st.view.outcome === 'running' && (view.outcome === 'done' || view.outcome === 'needs_review')) {
              const selection = defaultSelection(view);
              const first = Object.values(selection)[0];
              return { view, selection, copy: first ? structuredClone(view.renders[first].spec.copy) : null };
            }
            return { view };
          }),
        (err) => set({ error: message(err) }),
      );
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
}));
```

- [ ] **Step 5: 執行測試確認通過**

Run: `npx vitest run src/lib/store`
Expected: 8 個測試 PASS

- [ ] **Step 6: 建立 `web/src/components/product/product-image.tsx`**

```tsx
import Image from 'next/image';
import type { Brand, Product } from '@/types/contract';
import { productImage } from '@/lib/compose/assets';
import { cn } from '@/lib/utils';

/**
 * 商品縮圖。cutoutPreview 時以透明格紋當底；尚未真正去背的照片用色彩增值讓白底「消失」（示意）。
 * 圖片都是 data URL 或本機 API，所以用 unoptimized。
 */
export function ProductImage({
  product, brand, cutoutPreview = false, className,
}: { product: Product; brand: Brand; cutoutPreview?: boolean; className?: string }) {
  const { src, blend } = productImage(product, brand);
  return (
    <div className={cn('relative overflow-hidden', cutoutPreview ? 'bg-checker' : 'bg-muted', className)}>
      <Image
        src={src}
        alt={product.name}
        fill
        unoptimized
        sizes="320px"
        className={cn('object-contain p-1', cutoutPreview && blend === 'multiply' && 'mix-blend-multiply')}
      />
    </div>
  );
}
```

- [ ] **Step 7: 建立 `web/src/components/studio/brief-panel.tsx`**

```tsx
'use client';

import { useState } from 'react';
import { LoaderCircle, Play, Square, WandSparkles } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';
import { TONES, type Brand, type Engine, type ParsedBrief, type Tone } from '@/types/contract';
import { ProductImage } from '@/components/product/product-image';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { CHANNEL_TEMPLATES } from '@/lib/compose/templates';
import { useProductsStore } from '@/lib/store/products';
import { DEMO_BRIEFS, ENGINE_LABEL, LLM_OPTIONS, TONE_LABEL, useStudioStore, VLM_OPTIONS } from '@/lib/store/studio';

const splitList = (s: string) => s.split(/[,，、]/).map((x) => x.trim()).filter(Boolean);

/** 以分隔符號輸入清單：打字時保留原文，離開欄位才拆成陣列（否則打到「、」就會被吃掉） */
function ListInput({ id, value, separator, disabled, onCommit }: {
  id: string; value: string[]; separator: string; disabled: boolean; onCommit: (list: string[]) => void;
}) {
  const [text, setText] = useState(value.join(separator));
  return (
    <Input id={id} disabled={disabled} value={text} onChange={(e) => setText(e.target.value)} onBlur={() => onCommit(splitList(text))} />
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <span className="rounded-full bg-secondary px-2 py-0.5 text-[11px] font-semibold text-primary">STEP {n}</span>
        {title}
      </h3>
      {children}
    </section>
  );
}

function ParsedFields({ parsed, disabled }: { parsed: ParsedBrief; disabled: boolean }) {
  const patch = useStudioStore((s) => s.patchParsed);
  return (
    <div className="grid grid-cols-2 gap-3 rounded-lg border bg-muted/40 p-3">
      <div className="col-span-2 space-y-1.5">
        <Label htmlFor="pb-points">賣點（以頓號或逗號分隔）</Label>
        {/* key：重新拆解後清單改變時重設輸入框 */}
        <ListInput key={parsed.sellingPoints.join('|')} id="pb-points" separator="、" disabled={disabled} value={parsed.sellingPoints} onCommit={(sellingPoints) => patch({ sellingPoints })} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="pb-audience">客群</Label>
        <Input id="pb-audience" disabled={disabled} value={parsed.audience} onChange={(e) => patch({ audience: e.target.value })} />
      </div>
      <div className="space-y-1.5">
        <Label>語氣</Label>
        <Select disabled={disabled} value={parsed.tone} onValueChange={(v) => patch({ tone: v as Tone })}>
          <SelectTrigger className="w-full bg-card"><SelectValue /></SelectTrigger>
          <SelectContent>
            {TONES.map((t) => <SelectItem key={t} value={t}>{TONE_LABEL[t]}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="pb-campaign">檔期</Label>
        <Input id="pb-campaign" disabled={disabled} placeholder="無" value={parsed.campaign ?? ''} onChange={(e) => patch({ campaign: e.target.value.trim() || null })} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="pb-offer">優惠</Label>
        <Input id="pb-offer" disabled={disabled} placeholder="無" value={parsed.offer ?? ''} onChange={(e) => patch({ offer: e.target.value.trim() || null })} />
      </div>
      <div className="col-span-2 space-y-1.5">
        <Label htmlFor="pb-style">風格標籤（英文，進 Prompt）</Label>
        <ListInput key={parsed.style.join('|')} id="pb-style" separator=", " disabled={disabled} value={parsed.style} onCommit={(style) => patch({ style })} />
      </div>
    </div>
  );
}

export function BriefPanel({ brand }: { brand: Brand }) {
  // 只訂閱表單需要的欄位；生成中的事件（view）不會讓表單重繪
  const s = useStudioStore(useShallow((st) => ({
    brief: st.brief, productId: st.productId, parsed: st.parsed, templateIds: st.templateIds, variants: st.variants,
    llm: st.llm, engine: st.engine, vlm: st.vlm, maxRetries: st.maxRetries, parsing: st.parsing, starting: st.starting,
    error: st.error, jobRunning: st.view?.outcome === 'running',
    setForm: st.setForm, toggleTemplate: st.toggleTemplate, parse: st.parse, start: st.start, cancel: st.cancel,
  })));
  const products = useProductsStore((p) => p.products);
  const running = s.jobRunning || s.starting;

  const chooseProduct = (id: string) => {
    s.setForm({ productId: id });
    // 換商品後賣點與商品名稱會變，重新拆解
    if (s.parsed) void s.parse();
  };

  return (
    <Card className="lg:sticky lg:top-20">
      <CardHeader>
        <CardTitle>新任務</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <Step n={1} title="一句話需求">
          <Textarea
            aria-label="一句話需求"
            rows={3}
            disabled={running}
            value={s.brief}
            onChange={(e) => s.setForm({ brief: e.target.value })}
            placeholder={DEMO_BRIEFS[brand.id] ?? '例如：幫我做週年慶海報，主打買一送一'}
          />
          <div className="space-y-1.5">
            <Label htmlFor="studio-product">商品</Label>
            <Select disabled={running || !products.length} value={s.productId ?? ''} onValueChange={chooseProduct}>
              <SelectTrigger id="studio-product" className="h-11 w-full">
                <SelectValue placeholder="先到商品庫新增商品" />
              </SelectTrigger>
              <SelectContent>
                {products.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    <ProductImage product={p} brand={brand} className="size-7 rounded" />
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button variant="secondary" className="w-full" disabled={running || s.parsing || !s.brief.trim()} onClick={() => void s.parse()}>
            {s.parsing ? <LoaderCircle className="animate-spin" /> : <WandSparkles />}
            Agent 拆解需求
          </Button>
          {s.parsed && <ParsedFields parsed={s.parsed} disabled={running} />}
        </Step>

        <Step n={2} title="通路模板">
          <div className="grid gap-2">
            {CHANNEL_TEMPLATES.map((t) => (
              <label key={t.id} className="flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 text-sm has-[button[data-state=checked]]:border-primary has-[button[data-state=checked]]:bg-secondary/60">
                <Checkbox aria-label={t.label} disabled={running} checked={s.templateIds.includes(t.id)} onCheckedChange={() => s.toggleTemplate(t.id)} />
                <span className="font-medium">{t.label}</span>
                <span className="ml-auto font-mono text-xs text-muted-foreground">{t.ratio} · {t.width}×{t.height}</span>
              </label>
            ))}
          </div>
        </Step>

        <Step n={3} title="生成設定">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>每個模板候選張數</Label>
              <Select disabled={running} value={String(s.variants)} onValueChange={(v) => s.setForm({ variants: Number(v) })}>
                <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => <SelectItem key={n} value={String(n)}>{n} 張</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>最大重試次數</Label>
              <Select disabled={running} value={String(s.maxRetries)} onValueChange={(v) => s.setForm({ maxRetries: Number(v) })}>
                <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {[0, 1, 2, 3].map((n) => <SelectItem key={n} value={String(n)}>{n} 次</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          <details className="rounded-lg border px-3 py-2 text-sm">
            <summary className="cursor-pointer font-medium text-muted-foreground">模型與引擎</summary>
            <div className="mt-3 space-y-3">
              <div className="space-y-1.5">
                <Label>LLM（需求拆解、文案、Prompt）</Label>
                <Select disabled={running} value={s.llm} onValueChange={(v) => s.setForm({ llm: v })}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>{LLM_OPTIONS.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>生圖引擎</Label>
                <Select disabled={running} value={s.engine} onValueChange={(v) => s.setForm({ engine: v as Engine })}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {(Object.keys(ENGINE_LABEL) as Engine[]).map((e) => <SelectItem key={e} value={e}>{ENGINE_LABEL[e]}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>VLM（合規審查）</Label>
                <Select disabled={running} value={s.vlm} onValueChange={(v) => s.setForm({ vlm: v })}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>{VLM_OPTIONS.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            </div>
          </details>
        </Step>
        {s.error && <p className="text-sm text-destructive">{s.error}</p>}
      </CardContent>
      <CardFooter className="gap-2">
        {s.jobRunning ? (
          <Button variant="outline" className="w-full" onClick={() => void s.cancel()}>
            <Square />
            取消任務
          </Button>
        ) : (
          <Button size="lg" className="w-full" disabled={running} onClick={() => void s.start()}>
            {s.starting ? <LoaderCircle className="animate-spin" /> : <Play />}
            開始生成（{s.templateIds.length} 個模板 × {s.variants} 張）
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}
```

- [ ] **Step 8: 取代 `web/src/app/studio/page.tsx`**

```tsx
'use client';

import { useEffect } from 'react';
import { WandSparkles } from 'lucide-react';
import { EmptyState } from '@/components/common/empty-state';
import { PageHeader } from '@/components/common/page-header';
import { BriefPanel } from '@/components/studio/brief-panel';
import { useCurrentBrand } from '@/lib/store/app';
import { useProductsStore } from '@/lib/store/products';
import { useStudioStore } from '@/lib/store/studio';

function Results() {
  const view = useStudioStore((s) => s.view);
  if (!view) {
    return (
      <EmptyState icon={WandSparkles} title="輸入一句話需求，開始生成">
        Agent 會拆解需求、檢索品牌規範、產生 Prompt 與版面，生成後自動做合規審查；未通過會改寫後重試。
      </EmptyState>
    );
  }
  // 進度與結果牆在 Task 11 加入
  return <p className="text-sm text-muted-foreground">任務 {view.jobId} 已送出。</p>;
}

export default function StudioPage() {
  const brand = useCurrentBrand();
  const loadProducts = useProductsStore((s) => s.load);
  const products = useProductsStore((s) => s.products);
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
    const own = products.filter((p) => p.brandId === brand.id);
    if (own.length && !own.some((p) => p.id === productId)) setForm({ productId: own[0].id });
  }, [products, productId, brand.id, setForm]);

  return (
    <>
      <PageHeader title="新任務" description="一句話需求 → Agent 拆解 → 多通路生成 → 合規審查與自動重試 → 挑圖改字 → 匯出" />
      <div className="grid items-start gap-5 lg:grid-cols-[380px_minmax(0,1fr)]">
        <BriefPanel brand={brand} />
        <div className="min-w-0 space-y-5">
          <Results />
        </div>
      </div>
    </>
  );
}
```

- [ ] **Step 9: 驗證**

Run: `npm run test && npm run typecheck && npm run lint`，再 `npm run dev` 開啟 `/studio`

Expected：
- 指令：28 個測試檔、217 個測試 PASS，無型別與 lint 錯誤。
- 畫面：
  - 需求欄預填品牌示範句，商品預設選第一個。
  - 按「Agent 拆解需求」後出現賣點、客群、語氣、檔期、優惠、風格欄位。賣點欄打到「、」不會被吃掉，離開欄位才拆成清單。
  - 「開始生成」後右側顯示任務 id，表單變成唯讀，按鈕變成「取消任務」。
  - 切換品牌時，表單重設為該品牌的示範句。

- [ ] **Step 10: Commit**

```bash
git add web/src/lib/store web/src/components/product web/src/components/studio web/src/app/studio
git commit -m "feat: add studio brief form with product and job stores" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: 新任務 ②：海報預覽、精簡進度與結果牆

**Files:**
- Create: `web/src/components/poster/{poster-canvas.tsx,score-badge.tsx,check-list.tsx}`、`web/src/components/studio/{run-status.tsx,result-wall.tsx}`
- Modify: `web/src/app/studio/page.tsx`

**Interfaces:**
- Consumes：`preparePoster`、`paintPoster`（Task 7）；`finalCandidates`、`jobProgress`、`STAGE_LABEL`（Task 4）；`useStudioStore`（Task 10）
- Produces：
  - `PosterCanvas`：props 為 `PosterInput & { pixelWidth?; className? }`。較晚開始的繪製才算數。
  - `ScoreBadge`。
  - `CheckList`：`compact` 只顯示名稱與結果。
  - `RunStatus`：含「在 Agent 透視查看細節」連結 `/agent?job=…`。
  - `ResultWall`：依模板分組，只顯示最後一輪；點卡片打開單張審查細節；任務結束後才能選用。

- [ ] **Step 1: 建立 `web/src/components/poster/poster-canvas.tsx`**

```tsx
'use client';

import { useEffect, useRef } from 'react';
import { paintPoster, preparePoster, type PosterInput } from '@/lib/compose/render';
import { cn } from '@/lib/utils';

/** 海報預覽：與匯出共用同一套 Canvas 繪製。文案改變時只重畫文字，不重新產圖。 */
export function PosterCanvas({
  render, copy, product, brand, pixelWidth = 480, className,
}: PosterInput & { pixelWidth?: number; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;
    preparePoster({ render, copy, product, brand })
      .then((prepared) => {
        // 較晚開始的繪製才算數，避免快速輸入時舊畫面蓋掉新畫面
        if (!cancelled && ref.current) paintPoster(ref.current, prepared, pixelWidth);
      })
      .catch((err: unknown) => console.error('[PosterCanvas]', err));
    return () => {
      cancelled = true;
    };
  }, [render, copy, product, brand, pixelWidth]);

  const { width, height } = render.spec.canvas;
  return (
    <canvas
      ref={ref}
      role="img"
      aria-label={`${copy.headline.join(' ')} 海報預覽`}
      className={cn('block h-auto w-full bg-muted', className)}
      style={{ aspectRatio: `${width} / ${height}` }}
    />
  );
}
```

- [ ] **Step 2: 建立 `web/src/components/poster/score-badge.tsx`**

```tsx
import { LoaderCircle } from 'lucide-react';
import type { Render } from '@/types/contract';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

/** 合規分數徽章：綠＝通過、黃＝通過但有警告、紅＝未通過 */
export function ScoreBadge({ render, className }: { render: Pick<Render, 'score' | 'passed' | 'checks'>; className?: string }) {
  if (render.score === null) {
    return (
      <Badge variant="outline" className={className}>
        <LoaderCircle className="animate-spin" />
        審查中
      </Badge>
    );
  }
  const warn = render.checks.some((c) => c.status === 'warn');
  const tone = !render.passed
    ? 'border-red-200 bg-red-50 text-red-700'
    : warn
      ? 'border-amber-200 bg-amber-50 text-amber-800'
      : 'border-emerald-200 bg-emerald-50 text-emerald-700';
  return (
    <Badge variant="outline" className={cn(tone, className)}>
      {render.score} 分{render.passed ? '' : '・未通過'}
    </Badge>
  );
}
```

- [ ] **Step 3: 建立 `web/src/components/poster/check-list.tsx`**

```tsx
import { CircleCheck, CircleX, TriangleAlert } from 'lucide-react';
import type { CheckStatus, ReviewCheck } from '@/types/contract';
import { cn } from '@/lib/utils';

const ICON: Record<CheckStatus, React.ReactNode> = {
  pass: <CircleCheck className="size-4 text-success" />,
  warn: <TriangleAlert className="size-4 text-warning" />,
  fail: <CircleX className="size-4 text-destructive" />,
};

/** 審查項目清單（單張審查細節、文字編輯器的即時檢查共用）；compact 只顯示名稱與結果 */
export function CheckList({ checks, compact = false, className }: { checks: ReviewCheck[]; compact?: boolean; className?: string }) {
  if (compact) {
    return (
      <ul className={cn('space-y-1 text-xs', className)}>
        {checks.map((c) => (
          <li key={c.id} className="flex items-start gap-1.5">
            <span className="mt-px [&_svg]:size-3.5">{ICON[c.status]}</span>
            <span>
              <span className="font-medium">{c.name}</span>
              <span className="text-muted-foreground">：{c.value}</span>
            </span>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <ul className={cn('divide-y rounded-lg border', className)}>
      {checks.map((c) => (
        <li key={c.id} className="flex gap-2.5 px-3 py-2">
          <span className="mt-0.5">{ICON[c.status]}</span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">{c.name}</span>
              <span className="rounded bg-muted px-1.5 text-[10px] font-semibold text-muted-foreground">{c.kind === 'rule' ? '規則' : 'VLM'}</span>
              <span className={cn('ml-auto text-xs', c.status === 'pass' ? 'text-muted-foreground' : c.status === 'warn' ? 'text-warning' : 'text-destructive')}>
                {c.value}
              </span>
            </div>
            <p className="text-xs text-muted-foreground">
              {c.rule}
              {c.ragRef && <span className="ml-2 font-mono text-[11px]">RAG: {c.ragRef}</span>}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 4: 建立 `web/src/components/studio/run-status.tsx`**

```tsx
'use client';

import Link from 'next/link';
import { CircleCheck, Network, TriangleAlert } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { getTemplate } from '@/lib/compose/templates';
import { jobProgress, STAGE_LABEL, type JobView } from '@/lib/jobs/view';

/** 生成中的精簡進度；細節一鍵切到 Agent 透視 */
export function RunStatus({ view }: { view: JobView }) {
  const pct = Math.round(jobProgress(view) * 100);
  const lastLog = view.logs.at(-1);
  const retried = [...new Set(view.rewrites.map((r) => r.templateId))];
  const fixes = [...new Set(view.rewrites.flatMap((r) => r.fixes.map((f) => f.title)))];

  return (
    <Card>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          {view.outcome === 'done' && <CircleCheck className="size-5 text-success" />}
          {view.outcome === 'needs_review' && <TriangleAlert className="size-5 text-warning" />}
          <span className="font-semibold">{view.stage ? STAGE_LABEL[view.stage] : '排隊中'}</span>
          {view.round > 0 && <Badge variant="secondary">第 {view.round} 輪</Badge>}
          <span className="font-mono text-xs text-muted-foreground">{view.jobId}</span>
          <Link href={`/agent?job=${encodeURIComponent(view.jobId ?? '')}`} className="ml-auto inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline">
            <Network className="size-4" />
            在 Agent 透視查看細節
          </Link>
        </div>
        <Progress value={pct} className="h-2" />
        {view.outcome === 'running' && lastLog && <p className="truncate text-xs text-muted-foreground">{lastLog.message}</p>}
        {retried.length > 0 && (
          <p className="text-sm text-muted-foreground">
            {retried.map((t) => getTemplate(t).label).join('、')} 第 1 輪未通過審查，Query Rewriting 後重試：
            {fixes.map((f) => <Badge key={f} variant="outline" className="ml-1">{f}</Badge>)}
          </p>
        )}
        {view.outcome === 'needs_review' && (
          <p className="text-sm text-warning">{view.needsReviewReason}。可以檢視候選後手動選用，匯出前請人工確認。</p>
        )}
        {view.outcome === 'cancelled' && <p className="text-sm text-muted-foreground">任務已取消。</p>}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 5: 建立 `web/src/components/studio/result-wall.tsx`**

```tsx
'use client';

import { useState } from 'react';
import type { Brand, Product, Render, TemplateId } from '@/types/contract';
import { CheckList } from '@/components/poster/check-list';
import { PosterCanvas } from '@/components/poster/poster-canvas';
import { ScoreBadge } from '@/components/poster/score-badge';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { getTemplate } from '@/lib/compose/templates';
import { finalCandidates } from '@/lib/jobs/view';
import { useStudioStore } from '@/lib/store/studio';
import { cn } from '@/lib/utils';

interface CardProps {
  render: Render;
  brand: Brand;
  product: Product | null;
  best: boolean;
  selected: boolean;
  selectable: boolean;
  onOpen: () => void;
  onSelect: () => void;
}

function RenderCard({ render, brand, product, best, selected, selectable, onOpen, onSelect }: CardProps) {
  return (
    <div className={cn('overflow-hidden rounded-xl border bg-card transition-shadow hover:shadow-md', selected && 'ring-2 ring-primary')}>
      <button type="button" className="block w-full cursor-zoom-in" onClick={onOpen} aria-label={`檢視候選 ${render.variant + 1} 的審查細節`}>
        <PosterCanvas render={render} copy={render.spec.copy} product={product} brand={brand} pixelWidth={360} />
      </button>
      <div className="flex items-center gap-1.5 p-2">
        <ScoreBadge render={render} />
        {best && <Badge>推薦</Badge>}
        <span className="text-xs text-muted-foreground">#{render.variant + 1}</span>
        <Button size="xs" variant={selected ? 'default' : 'outline'} className="ml-auto" disabled={!selectable} onClick={onSelect}>
          {selected ? '已選用' : '選用'}
        </Button>
      </div>
    </div>
  );
}

/** 結果牆：依模板分組，只顯示每個模板最後一輪的候選 */
export function ResultWall({ brand, product }: { brand: Brand; product: Product | null }) {
  const view = useStudioStore((s) => s.view);
  const input = useStudioStore((s) => s.input);
  const selection = useStudioStore((s) => s.selection);
  const select = useStudioStore((s) => s.select);
  const [openId, setOpenId] = useState<string | null>(null);
  if (!view || !input) return null;

  const candidates = finalCandidates(view);
  const selectable = view.outcome === 'done' || view.outcome === 'needs_review';
  const open = openId ? view.renders[openId] : null;

  return (
    <div className="space-y-6">
      {input.templateIds.map((templateId: TemplateId) => {
        const t = getTemplate(templateId);
        const list = candidates[templateId] ?? [];
        const wide = t.width / t.height >= 1.3;
        const retried = view.rewrites.some((r) => r.templateId === templateId);
        return (
          <section key={templateId} className="space-y-3">
            <div className="flex items-center gap-2">
              <h3 className="font-semibold">{t.label}</h3>
              <span className="font-mono text-xs text-muted-foreground">{t.ratio} · {t.width}×{t.height}</span>
              {retried && <Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-800">已重試</Badge>}
              {list[0] && <span className="text-xs text-muted-foreground">第 {list[0].round} 輪</span>}
            </div>
            <div className={cn('grid gap-3', wide ? 'grid-cols-1 sm:grid-cols-2' : 'grid-cols-2 xl:grid-cols-4')}>
              {list.length
                ? list.map((r) => (
                  <RenderCard
                    key={r.id}
                    render={r}
                    brand={brand}
                    product={product}
                    best={view.bestRenderIds[templateId] === r.id}
                    selected={selection[templateId] === r.id}
                    selectable={selectable}
                    onOpen={() => setOpenId(r.id)}
                    onSelect={() => select(templateId, r.id)}
                  />
                ))
                : Array.from({ length: input.variantsPerTemplate }, (_, i) => (
                  <div key={i} className="grid animate-pulse place-items-center rounded-xl border bg-muted text-xs text-muted-foreground" style={{ aspectRatio: `${t.width} / ${t.height}` }}>
                    生成中…
                  </div>
                ))}
            </div>
          </section>
        );
      })}

      <Dialog open={open !== null} onOpenChange={(o) => !o && setOpenId(null)}>
        {open && (
          <DialogContent className="max-h-[90vh] overflow-auto sm:max-w-4xl">
            <DialogHeader>
              <DialogTitle>{getTemplate(open.templateId).label} · 候選 #{open.variant + 1}</DialogTitle>
              <DialogDescription>
                第 {open.round} 輪・seed {open.background.kind === 'procedural' ? open.background.seed : '—'}
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="overflow-hidden rounded-lg border">
                <PosterCanvas render={open} copy={open.spec.copy} product={product} brand={brand} pixelWidth={720} />
              </div>
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <ScoreBadge render={open} />
                  <span className="text-sm text-muted-foreground">規則 7 項 + VLM 3 項</span>
                </div>
                <CheckList checks={open.checks} />
              </div>
            </div>
            <DialogFooter>
              <Button
                disabled={!selectable}
                onClick={() => {
                  select(open.templateId, open.id);
                  setOpenId(null);
                }}
              >
                選用此張
              </Button>
            </DialogFooter>
          </DialogContent>
        )}
      </Dialog>
    </div>
  );
}
```

- [ ] **Step 6: 修改 `web/src/app/studio/page.tsx`**

找到（1／3）：

```tsx
import { BriefPanel } from '@/components/studio/brief-panel';
import { useCurrentBrand } from '@/lib/store/app';
```

改成：

```tsx
import { BriefPanel } from '@/components/studio/brief-panel';
import { ResultWall } from '@/components/studio/result-wall';
import { RunStatus } from '@/components/studio/run-status';
import { useCurrentBrand } from '@/lib/store/app';
```

找到（2／3）：

```tsx
function Results() {
  const view = useStudioStore((s) => s.view);
  if (!view) {
```

改成：

```tsx
function Results() {
  const brand = useCurrentBrand();
  const view = useStudioStore((s) => s.view);
  const productId = useStudioStore((s) => s.input?.productId);
  const product = useProductsStore((s) => s.products.find((p) => p.id === productId) ?? null);
  if (!view) {
```

找到（3／3）：

```tsx
  }
  // 進度與結果牆在 Task 11 加入
  return <p className="text-sm text-muted-foreground">任務 {view.jobId} 已送出。</p>;
}
```

改成：

```tsx
  }
  return (
    <>
      <RunStatus view={view} />
      <ResultWall brand={brand} product={product} />
    </>
  );
}
```

- [ ] **Step 7: 驗證**

Run: `npm run typecheck && npm run lint`，再 `npm run dev` 用預設設定開始生成（SÉLUNE、電商主圖 + IG 貼文、各 4 張）

Expected：
- 進度條依階段前進，下方顯示最新一行 Log。
- 約 6 秒後出現第 1 輪候選，徽章是紅色「未通過」，背景偏桃紅。
- 接著出現「已重試」標籤與修正策略（文案改寫、色彩修正、版面修正、補充註記）。
- 約 14.5 秒時顯示「完成・第 2 輪」，每個模板有 4 張分數不同的候選，其中一張是「推薦」並預設「已選用」。
- 點卡片打開審查細節，可看到 7 項規則與 3 項 VLM，各附 RAG 來源。
- 切到霧嶼咖啡再生成：背景變成晨霧與桌面，Logo 是山形標誌。

- [ ] **Step 8: Commit**

```bash
git add web/src/components/poster web/src/components/studio web/src/app/studio
git commit -m "feat: add poster preview, run status and result wall" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: 新任務 ③：文字編輯器、即時合規檢查與匯出

**Files:**
- Create: `web/src/lib/review/recheck.ts`、`web/src/components/studio/copy-editor.tsx`
- Modify: `web/src/app/studio/page.tsx`
- Test: `web/src/lib/review/recheck.test.ts`

**Interfaces:**
- Consumes：`runRuleChecks`（Plan 1）；`exportPosterZip`、`exportPosterPng`（Task 7）；`saveSelection`（Task 10）；`CheckList`、`PosterCanvas`（Task 11）
- Produces：`recheckCopy(render, brand, copy): ReviewCheck[]`；`copyBlockers(checks)`（目前只擋禁用詞）；元件 `CopyEditor`

- [ ] **Step 1: 寫失敗測試 `web/src/lib/review/recheck.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import type { Render } from '@/types/contract';
import { SELUNE } from '@/lib/api/mock/data';
import { applyFlaws } from '@/lib/api/mock/flaws';
import { cleanSpec } from '@/test/fixtures';
import { copyBlockers, recheckCopy } from './recheck';

const renderOf = (spec = cleanSpec()): Render => ({
  id: 'r1', jobId: 'job_t', round: 2, templateId: spec.templateId, variant: 0,
  background: { kind: 'procedural', seed: 1, palette: spec.palette, style: 'selune' }, spec, score: 96, passed: true, checks: [],
});

describe('recheckCopy', () => {
  it('passes the original copy of a clean render', () => {
    const r = renderOf();
    const checks = recheckCopy(r, SELUNE, r.spec.copy);
    expect(checks.map((c) => c.status)).toEqual(['pass', 'pass', 'pass', 'pass', 'pass', 'pass', 'pass']);
    expect(copyBlockers(checks)).toEqual([]);
  });

  it('blocks export when the edited copy contains a banned word', () => {
    const r = renderOf();
    const checks = recheckCopy(r, SELUNE, { ...r.spec.copy, subhead: '7天根治暗沉' });
    expect(copyBlockers(checks).map((c) => c.target)).toEqual(['subhead']);
  });

  it('warns but does not block when the disclaimer is removed', () => {
    const r = renderOf();
    const checks = recheckCopy(r, SELUNE, { ...r.spec.copy, disclaimer: '' });
    expect(checks.find((c) => c.id === 'disclaimer')!.status).toBe('warn');
    expect(copyBlockers(checks)).toEqual([]);
  });

  it('keeps the color result of an off-brand render', () => {
    const r = renderOf(applyFlaws(cleanSpec(), ['offPalette']));
    expect(recheckCopy(r, SELUNE, r.spec.copy).find((c) => c.id === 'color_delta')!.status).toBe('fail');
  });
});
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `npx vitest run src/lib/review/recheck.test.ts`
Expected: FAIL，找不到 `./recheck`

- [ ] **Step 3: 實作 `web/src/lib/review/recheck.ts`**

```ts
import type { Brand, Copy, ReviewCheck, Render } from '@/types/contract';
import { runRuleChecks } from './rules';

/**
 * 文字編輯器改了文案後重新跑規則型審查（VLM 不重跑，沿用生成時的結果）。
 * 偵測主色沿用該張背景的主色，所以色差結果與生成時一致。
 */
export function recheckCopy(render: Render, brand: Brand, copy: Copy): ReviewCheck[] {
  return runRuleChecks({ brand, spec: { ...render.spec, copy }, measuredPrimary: render.spec.palette.primary });
}

/** 由文案造成、匯出前必須修正的問題（目前只有禁用詞） */
export const copyBlockers = (checks: ReviewCheck[]): ReviewCheck[] =>
  checks.filter((c) => c.id === 'banned_words' && c.status === 'fail');
```

- [ ] **Step 4: 執行測試確認通過**

Run: `npx vitest run src/lib/review`
Expected: `recheck.test.ts` 4 個測試 PASS，其他 review 測試仍 PASS

- [ ] **Step 5: 建立 `web/src/components/studio/copy-editor.tsx`**

```tsx
'use client';

import { useState } from 'react';
import { CircleCheck, Download, FileDown, LoaderCircle, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import type { Brand, Copy, Product, Render } from '@/types/contract';
import { CheckList } from '@/components/poster/check-list';
import { PosterCanvas } from '@/components/poster/poster-canvas';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { getTemplate } from '@/lib/compose/templates';
import { exportPosterPng, exportPosterZip } from '@/lib/export/posters';
import { copyBlockers, recheckCopy } from '@/lib/review/recheck';
import { useStudioStore } from '@/lib/store/studio';

function Field({ id, label, value, onChange }: { id: string; label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function CopyForm({ copy, onChange }: { copy: Copy; onChange: (c: Copy) => void }) {
  const set = (patch: Partial<Copy>) => onChange({ ...copy, ...patch });
  const features = [0, 1, 2].map((i) => copy.features[i] ?? '');
  const num = (v: string) => Math.max(0, Math.round(Number(v) || 0));
  return (
    <div className="space-y-3">
      <Field id="c-h1" label="標題第一行" value={copy.headline[0]} onChange={(v) => set({ headline: [v, copy.headline[1]] })} />
      <Field id="c-h2" label="標題第二行（主色強調）" value={copy.headline[1]} onChange={(v) => set({ headline: [copy.headline[0], v] })} />
      <Field id="c-sub" label="副標" value={copy.subhead} onChange={(v) => set({ subhead: v })} />
      <div className="space-y-1.5">
        <Label>賣點</Label>
        <div className="grid grid-cols-3 gap-2">
          {features.map((f, i) => (
            <Input
              key={i}
              aria-label={`賣點 ${i + 1}`}
              value={f}
              // 保留空字串讓欄位位置不變；排版引擎會略過空的賣點
              onChange={(e) => set({ features: features.map((x, j) => (j === i ? e.target.value : x)) })}
            />
          ))}
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Field id="c-bt" label="徽章上排" value={copy.badge.top} onChange={(v) => set({ badge: { ...copy.badge, top: v } })} />
        <Field id="c-bm" label="徽章主字" value={copy.badge.main} onChange={(v) => set({ badge: { ...copy.badge, main: v } })} />
        <Field id="c-bs" label="徽章英文" value={copy.badge.sub} onChange={(v) => set({ badge: { ...copy.badge, sub: v } })} />
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Field id="c-pl" label="價格標籤" value={copy.price.label} onChange={(v) => set({ price: { ...copy.price, label: v } })} />
        <div className="space-y-1.5">
          <Label htmlFor="c-ps">特價</Label>
          <Input id="c-ps" type="number" min={0} value={copy.price.sale} onChange={(e) => set({ price: { ...copy.price, sale: num(e.target.value) } })} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="c-po">原價</Label>
          <Input id="c-po" type="number" min={0} value={copy.price.original} onChange={(e) => set({ price: { ...copy.price, original: num(e.target.value) } })} />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="c-disc">頁尾註記</Label>
        <Textarea id="c-disc" rows={2} value={copy.disclaimer} onChange={(e) => set({ disclaimer: e.target.value })} />
      </div>
    </div>
  );
}

/** 選定候選後：改文案即時重繪、即時重跑規則審查、匯出 zip 並寫入歷史紀錄 */
export function CopyEditor({ brand, product }: { brand: Brand; product: Product | null }) {
  const view = useStudioStore((s) => s.view);
  const input = useStudioStore((s) => s.input);
  const selection = useStudioStore((s) => s.selection);
  const copy = useStudioStore((s) => s.copy);
  const setCopy = useStudioStore((s) => s.setCopy);
  const saveSelection = useStudioStore((s) => s.saveSelection);
  const [exporting, setExporting] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  if (!view || !input || !copy || (view.outcome !== 'done' && view.outcome !== 'needs_review')) return null;

  const selected = input.templateIds
    .map((t) => (selection[t] ? view.renders[selection[t]!] : undefined))
    .filter((r): r is Render => r !== undefined);
  const checks = selected.map((r) => ({ render: r, checks: recheckCopy(r, brand, copy) }));
  const blockers = checks.flatMap((x) => copyBlockers(x.checks));
  const needsConfirm = view.outcome === 'needs_review' || selected.some((r) => !r.passed);

  const exportAll = async () => {
    setExporting(true);
    try {
      await exportPosterZip(brand, product, selected.map((render) => ({ render, copy })));
      const written = await saveSelection();
      toast.success(`已匯出 ${selected.length} 張海報`, {
        description: written ? `${written} 張寫入歷史紀錄，並標記「已回寫 RAG（歷史優秀案例）」。` : '這些圖與文案先前已寫入歷史紀錄。',
      });
    } catch (err) {
      toast.error('匯出失敗', { description: err instanceof Error ? err.message : String(err) });
    } finally {
      setExporting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>文字編輯器</CardTitle>
        <CardDescription>修改文案、價格與徽章，所有選定的模板即時重繪，不重新產圖；規則型審查同步重跑。</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="space-y-3">
          <CopyForm copy={copy} onChange={setCopy} />
          <Button
            variant="ghost"
            size="sm"
            onClick={() => selected[0] && setCopy(structuredClone(selected[0].spec.copy))}
          >
            <RotateCcw />
            還原 AI 文案
          </Button>
        </div>
        <div className="min-w-0 space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {checks.map(({ render: r, checks: cs }) => {
              const issues = cs.filter((c) => c.status !== 'pass');
              return (
                <div key={r.id} className="space-y-2">
                  <div className="flex items-center gap-2 text-sm">
                    <span className="font-semibold">{getTemplate(r.templateId).label}</span>
                    <Button size="xs" variant="ghost" className="ml-auto" onClick={() => void exportPosterPng(brand, product, { render: r, copy })}>
                      <Download />
                      PNG
                    </Button>
                  </div>
                  <div className="overflow-hidden rounded-lg border">
                    <PosterCanvas render={r} copy={copy} product={product} brand={brand} pixelWidth={520} />
                  </div>
                  {issues.length ? (
                    <CheckList compact checks={issues} />
                  ) : (
                    <p className="flex items-center gap-1.5 text-xs text-success">
                      <CircleCheck className="size-4" />
                      規則型審查全部通過（VLM 結果沿用生成時）
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </CardContent>
      <CardFooter className="flex-wrap gap-3">
        {blockers.length > 0 && <p className="text-sm text-destructive">文案含禁用詞，請先修改：{blockers[0].value}</p>}
        {needsConfirm && (
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={confirmed} onCheckedChange={(v) => setConfirmed(v === true)} />
            部分候選未通過審查，我已人工確認可以使用
          </label>
        )}
        <Button
          size="lg"
          className="ml-auto"
          disabled={exporting || !selected.length || blockers.length > 0 || (needsConfirm && !confirmed)}
          onClick={() => void exportAll()}
        >
          {exporting ? <LoaderCircle className="animate-spin" /> : <FileDown />}
          匯出 zip 並寫入歷史（{selected.length} 張）
        </Button>
      </CardFooter>
    </Card>
  );
}
```

- [ ] **Step 6: 修改 `web/src/app/studio/page.tsx`**

找到（1／2）：

```tsx
import { BriefPanel } from '@/components/studio/brief-panel';
import { ResultWall } from '@/components/studio/result-wall';
```

改成：

```tsx
import { BriefPanel } from '@/components/studio/brief-panel';
import { CopyEditor } from '@/components/studio/copy-editor';
import { ResultWall } from '@/components/studio/result-wall';
```

找到（2／2）：

```tsx
      <ResultWall brand={brand} product={product} />
    </>
```

改成：

```tsx
      <ResultWall brand={brand} product={product} />
      <CopyEditor brand={brand} product={product} />
    </>
```

- [ ] **Step 7: 驗證**

Run: `npm run test && npm run typecheck && npm run lint`，再 `npm run dev` 完成一次生成

Expected：
- 指令：29 個測試檔、221 個測試 PASS。
- 畫面：
  - 結果牆下方出現「文字編輯器」。
  - 改特價後，所有選定模板的預覽即時重繪，不重新產圖。
  - 副標輸入「7天根治暗沉」時，出現「禁用詞檢查：禁用詞「根治」」，匯出按鈕停用；按「還原 AI 文案」後恢復。
  - 按「匯出 zip 並寫入歷史」：
    - 下載 `SÉLUNE晞月_極光玻尿酸修護精華30ml_YYYYMMDD.zip`。
    - zip 內含每個模板一張原尺寸 PNG，例如 `…_IG貼文_YYYYMMDD.png` 為 1440×1800。
    - 出現提示「已匯出 2 張海報」。
    - 再按一次會提示先前已寫入。
  - Demo 控制台開「強制全部失敗」後生成：
    - 顯示「需人工審核」，仍可選圖。
    - 必須勾選「我已人工確認」才能匯出。

- [ ] **Step 8: Commit**

```bash
git add web/src/lib/review web/src/components/studio web/src/app/studio
git commit -m "feat: add copy editor with live compliance check and zip export" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: 商品庫 `/products`

**Files:**
- Create: `web/src/lib/image/downscale.ts`、`web/src/components/product/{product-edit-dialog.tsx,product-card.tsx,cutout-dialog.tsx,local-folder.tsx,upload-zone.tsx}`
- Modify: `web/src/app/products/page.tsx`（取代暫時頁面）

**Interfaces:**
- Consumes：`useProductsStore`、`ProductImage`（Task 10）；`uploadProductPhoto`、`requestCutout`（Task 2）；`LocalPhoto`（Task 8，僅型別）；`formatPrice`（Task 5）
- Produces：
  - `downscaleImage(file, maxSide = 1600)`：PNG 保留透明，其他格式轉 JPEG。
  - `nameFromFile(fileName)`。
  - 元件 `ProductEditDialog`、`ProductCard`、`CutoutDialog`、`LocalFolder`、`UploadZone`。

- [ ] **Step 1: 建立 `web/src/lib/image/downscale.ts`**

```ts
/** 瀏覽器端：上傳前把商品照縮到最長邊 maxSide，減少 IndexedDB 與海報繪製的負擔 */
export async function downscaleImage(file: Blob, maxSide = 1600): Promise<Blob> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
  if (scale === 1 && file.size <= 1_500_000) {
    bitmap.close();
    return file;
  }
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext('2d')?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  // PNG 保留透明背景；其他格式轉 JPEG
  const type = file.type === 'image/png' ? 'image/png' : 'image/jpeg';
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('圖片壓縮失敗'))), type, 0.9),
  );
}

/** 「night_mask-50ml.png」→「night mask 50ml」 */
export const nameFromFile = (fileName: string) => fileName.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim() || '未命名商品';
```

- [ ] **Step 2: 建立 `web/src/components/product/product-edit-dialog.tsx`**

```tsx
'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import type { Product } from '@/types/contract';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useProductsStore } from '@/lib/store/products';

const splitList = (s: string) => s.split(/[,，、]/).map((x) => x.trim()).filter(Boolean);

function EditForm({ product, onDone }: { product: Product; onDone: () => void }) {
  const save = useProductsStore((s) => s.save);
  const [name, setName] = useState(product.name);
  const [features, setFeatures] = useState(product.features.join('、'));
  const [sale, setSale] = useState(String(product.price.sale));
  const [original, setOriginal] = useState(String(product.price.original));
  const [saving, setSaving] = useState(false);
  const saleN = Number(sale);
  const originalN = Number(original);
  const error = !name.trim()
    ? '請輸入商品名稱'
    : !Number.isFinite(saleN) || saleN < 0 || !Number.isFinite(originalN) || originalN < 0
      ? '價格需為 0 以上的數字'
      : null;

  const submit = async () => {
    if (error) return;
    setSaving(true);
    try {
      await save({
        ...product, name: name.trim(), features: splitList(features).slice(0, 6),
        price: { sale: Math.round(saleN), original: Math.round(originalN) },
      });
      toast.success('已儲存商品');
      onDone();
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="p-name">商品名稱</Label>
          <Input id="p-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="p-features">特徵／賣點（以頓號分隔，最多 6 個）</Label>
          <Input id="p-features" value={features} onChange={(e) => setFeatures(e.target.value)} placeholder="例如：5重玻尿酸、無香精" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="p-sale">特價（NT$）</Label>
            <Input id="p-sale" type="number" min={0} value={sale} onChange={(e) => setSale(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="p-original">原價（NT$）</Label>
            <Input id="p-original" type="number" min={0} value={original} onChange={(e) => setOriginal(e.target.value)} />
          </div>
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onDone}>取消</Button>
        <Button disabled={!!error || saving} onClick={() => void submit()}>儲存</Button>
      </DialogFooter>
    </>
  );
}

export function ProductEditDialog({ product, onClose }: { product: Product | null; onClose: () => void }) {
  return (
    <Dialog open={product !== null} onOpenChange={(o) => !o && onClose()}>
      {product && (
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>編輯商品</DialogTitle>
            <DialogDescription>名稱、特徵與價格會帶入新任務的需求拆解與海報文案。</DialogDescription>
          </DialogHeader>
          {/* key：換商品時重設表單 */}
          <EditForm key={product.id} product={product} onDone={onClose} />
        </DialogContent>
      )}
    </Dialog>
  );
}
```

- [ ] **Step 3: 建立 `web/src/components/product/product-card.tsx`**

```tsx
'use client';

import { LoaderCircle, Pencil, Scissors, Trash } from 'lucide-react';
import type { Brand, Product } from '@/types/contract';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { formatPrice } from '@/lib/compose/scene';
import { useProductsStore } from '@/lib/store/products';
import { ProductImage } from './product-image';

const SOURCE_LABEL = { sample: '示範素材', upload: '上傳', local: '本機資料夾' } as const;

export function ProductCard({ product, brand, onEdit, onCutout, onDelete }: {
  product: Product;
  brand: Brand;
  onEdit: () => void;
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
        <p className="text-sm">
          <span className="font-semibold text-primary">NT${formatPrice(product.price.sale)}</span>
          {product.price.original > product.price.sale && (
            <span className="ml-2 text-xs text-muted-foreground line-through">NT${formatPrice(product.price.original)}</span>
          )}
        </p>
        <div className="flex flex-wrap gap-1">
          {product.features.map((f) => (
            <span key={f} className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">{f}</span>
          ))}
        </div>
        <div className="mt-auto flex gap-1 pt-2">
          <Button size="sm" variant="outline" onClick={onEdit}>
            <Pencil />
            編輯
          </Button>
          {isPhoto && (
            <Button size="sm" variant="outline" disabled={cutting} onClick={onCutout}>
              {cutting ? <LoaderCircle className="animate-spin" /> : <Scissors />}
              {cutting ? '去背中…' : '去背預覽'}
            </Button>
          )}
          <Button size="icon-sm" variant="ghost" className="ml-auto text-muted-foreground hover:text-destructive" aria-label={`刪除 ${product.name}`} onClick={onDelete}>
            <Trash />
          </Button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 建立 `web/src/components/product/cutout-dialog.tsx`**

```tsx
'use client';

import type { Brand, Product } from '@/types/contract';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { ProductImage } from './product-image';

/** 去背預覽：左邊原圖、右邊透明格紋上的去背結果（mock 以色彩增值示意） */
export function CutoutDialog({ product, brand, onClose }: { product: Product | null; brand: Brand; onClose: () => void }) {
  return (
    <Dialog open={product !== null} onOpenChange={(o) => !o && onClose()}>
      {product && (
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>去背預覽：{product.name}</DialogTitle>
            <DialogDescription>
              模型 {product.cutout?.model ?? 'BiRefNet-general'}。第一階段為示意：白底以「色彩增值」融入背景；第二階段由 ComfyUI 的 BiRefNet 產生透明 PNG。
            </DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-4">
            <figure className="space-y-2">
              <ProductImage product={{ ...product, cutout: null }} brand={brand} className="aspect-[4/5] rounded-lg border" />
              <figcaption className="text-center text-xs text-muted-foreground">原圖</figcaption>
            </figure>
            <figure className="space-y-2">
              <ProductImage product={product} brand={brand} cutoutPreview className="aspect-[4/5] rounded-lg border" />
              <figcaption className="text-center text-xs text-muted-foreground">去背（示意）</figcaption>
            </figure>
          </div>
        </DialogContent>
      )}
    </Dialog>
  );
}
```

- [ ] **Step 5: 建立 `web/src/components/product/local-folder.tsx`**

```tsx
'use client';

import { useEffect, useState } from 'react';
import Image from 'next/image';
import { FolderOpen } from 'lucide-react';
import { toast } from 'sonner';
import type { Brand } from '@/types/contract';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import type { LocalPhoto } from '@/lib/server/local-products';
import { useProductsStore } from '@/lib/store/products';

type FolderState = { status: 'loading' } | { status: 'unavailable' } | { status: 'ready'; photos: LocalPhoto[] };

/** 開發模式：列出 assets/products/ 的照片，一鍵匯入成商品（檔名當商品名稱） */
export function LocalFolder({ brand }: { brand: Brand }) {
  const [state, setState] = useState<FolderState>({ status: 'loading' });
  const products = useProductsStore((s) => s.products);
  const save = useProductsStore((s) => s.save);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/local-products')
      .then((res) => (res.ok ? (res.json() as Promise<{ photos: LocalPhoto[] }>) : Promise.reject(new Error(String(res.status)))))
      .then((data) => !cancelled && setState({ status: 'ready', photos: data.photos }))
      .catch(() => !cancelled && setState({ status: 'unavailable' }));
    return () => {
      cancelled = true;
    };
  }, []);

  const imported = new Set(products.flatMap((p) => (p.photo.source === 'local' ? [p.photo.url] : [])));
  const importPhoto = async (photo: LocalPhoto) => {
    await save({
      brandId: brand.id, name: photo.name, features: [], price: { sale: 0, original: 0 },
      photo: { source: 'local', url: photo.url }, cutout: null,
    });
    toast.success(`已匯入「${photo.name}」`, { description: '請到卡片上補上價格與特徵。' });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FolderOpen className="size-4" />
          本機資料夾 assets/products/
        </CardTitle>
        <CardDescription>把自己的商品照放進 repo 根目錄的 assets/products/（不會上傳 GitHub），開發模式下可直接匯入。</CardDescription>
      </CardHeader>
      <CardContent>
        {state.status === 'loading' && <p className="text-sm text-muted-foreground">讀取中…</p>}
        {state.status === 'unavailable' && <p className="text-sm text-muted-foreground">只有 `npm run dev` 開發模式可以讀取本機資料夾。</p>}
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
                <Button size="xs" variant="outline" className="w-full" disabled={imported.has(photo.url)} onClick={() => void importPhoto(photo)}>
                  {imported.has(photo.url) ? '已匯入' : '匯入'}
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

- [ ] **Step 6: 建立 `web/src/components/product/upload-zone.tsx`**

```tsx
'use client';

import { useRef, useState } from 'react';
import { ImagePlus, LoaderCircle } from 'lucide-react';
import { toast } from 'sonner';
import type { Brand } from '@/types/contract';
import { Button } from '@/components/ui/button';
import { getApiClient } from '@/lib/api';
import { downscaleImage, nameFromFile } from '@/lib/image/downscale';
import { useProductsStore } from '@/lib/store/products';
import { cn } from '@/lib/utils';

/** 上傳／拖放商品照：縮圖後交給 ApiClient 保存，再建立商品（價格與特徵之後再補） */
export function UploadZone({ brand }: { brand: Brand }) {
  const input = useRef<HTMLInputElement>(null);
  const save = useProductsStore((s) => s.save);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);

  const upload = async (files: File[]) => {
    const images = files.filter((f) => f.type.startsWith('image/'));
    if (!images.length) {
      toast.error('只能上傳圖片檔');
      return;
    }
    setBusy(true);
    try {
      const api = getApiClient();
      for (const file of images) {
        const photo = await api.uploadProductPhoto(await downscaleImage(file));
        await save({ brandId: brand.id, name: nameFromFile(file.name), features: [], price: { sale: 0, original: 0 }, photo, cutout: null });
      }
      toast.success(`已新增 ${images.length} 個商品`, { description: '照片存在這台電腦的瀏覽器（IndexedDB）。請補上價格與特徵。' });
    } catch (err) {
      toast.error('上傳失敗', { description: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        void upload([...e.dataTransfer.files]);
      }}
      className={cn(
        'flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed bg-card px-6 py-8 text-center transition-colors',
        over && 'border-primary bg-secondary',
      )}
    >
      {busy ? <LoaderCircle className="size-7 animate-spin text-primary" /> : <ImagePlus className="size-7 text-muted-foreground" />}
      <p className="font-medium">拖放商品照到這裡，或</p>
      <Button size="sm" disabled={busy} onClick={() => input.current?.click()}>
        選擇照片
      </Button>
      <p className="text-xs text-muted-foreground">白底商品照效果最好；最長邊會縮到 1600px。</p>
      <input
        ref={input}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        multiple
        hidden
        onChange={(e) => {
          void upload([...(e.target.files ?? [])]);
          e.target.value = '';
        }}
      />
    </div>
  );
}
```

- [ ] **Step 7: 取代 `web/src/app/products/page.tsx`**

```tsx
'use client';

import { useEffect, useState } from 'react';
import { Package } from 'lucide-react';
import { toast } from 'sonner';
import type { Product } from '@/types/contract';
import { EmptyState } from '@/components/common/empty-state';
import { PageHeader } from '@/components/common/page-header';
import { CutoutDialog } from '@/components/product/cutout-dialog';
import { LocalFolder } from '@/components/product/local-folder';
import { ProductCard } from '@/components/product/product-card';
import { ProductEditDialog } from '@/components/product/product-edit-dialog';
import { UploadZone } from '@/components/product/upload-zone';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { useCurrentBrand } from '@/lib/store/app';
import { useProductsStore } from '@/lib/store/products';

export default function ProductsPage() {
  const brand = useCurrentBrand();
  const { products, loading, load, remove, cutout } = useProductsStore();
  const [editing, setEditing] = useState<Product | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Product | null>(null);
  const preview = products.find((p) => p.id === previewId) ?? null;

  useEffect(() => {
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
    <>
      <PageHeader title="商品庫" description={`${brand.name} 的商品。海報會保留真實商品照，AI 只生成背景與情境。`} />
      <div className="space-y-5">
        <UploadZone brand={brand} />
        {products.length ? (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
            {products.map((p) => (
              <ProductCard
                key={p.id}
                product={p}
                brand={brand}
                onEdit={() => setEditing(p)}
                onCutout={() => void startCutout(p)}
                onDelete={() => setDeleting(p)}
              />
            ))}
          </div>
        ) : (
          !loading && <EmptyState icon={Package} title="還沒有商品">上傳商品照，或從本機資料夾匯入。</EmptyState>
        )}
        <LocalFolder brand={brand} />
      </div>

      <ProductEditDialog product={editing} onClose={() => setEditing(null)} />
      <CutoutDialog product={preview} brand={brand} onClose={() => setPreviewId(null)} />
      <Dialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)}>
        {deleting && (
          <DialogContent className="sm:max-w-sm">
            <DialogHeader>
              <DialogTitle>刪除「{deleting.name}」？</DialogTitle>
              <DialogDescription>商品會從商品庫移除；已存在的歷史紀錄不受影響。</DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeleting(null)}>取消</Button>
              <Button
                variant="destructive"
                onClick={() => {
                  void remove(deleting.id);
                  setDeleting(null);
                }}
              >
                刪除
              </Button>
            </DialogFooter>
          </DialogContent>
        )}
      </Dialog>
    </>
  );
}
```

- [ ] **Step 8: 驗證**

Run: `npm run typecheck && npm run lint`。在 repo 根目錄的 `assets/products/` 放一張白底商品照，例如 `night_mask-50ml.png`，再執行 `npm run dev` 開啟 `/products`

Expected：
- 上傳／拖放：
  - 照片成為「上傳」商品，名稱取自檔名，卡片顯示「請補上價格」。最長邊超過 1600px 的照片會先縮小，例如 2400×3000 會變成 1280×1600。
  - 重新整理後商品仍在（IndexedDB）。
- 「本機資料夾」區塊列出 `night mask 50ml`；按「匯入」後變成「已匯入」，商品出現在列表。
- 「去背預覽」約 1.2 秒後打開對照視窗，右側格紋上看不到白底，卡片標示「已去背（示意）」。
- 「編輯」可改名稱、特徵與價格，價格不是數字時無法儲存。
- 「刪除」需要確認。
- 回到 `/studio` 選這個商品生成：海報上的照片白底融入背景。
- `npm run build && npm run start` 時，`/api/local-products` 回傳 404，頁面顯示「只有 `npm run dev` 開發模式可以讀取本機資料夾」。

- [ ] **Step 9: Commit**

```bash
git add web/src/lib/image web/src/components/product web/src/app/products
git commit -m "feat: add product library with upload, cutout preview and local folder import" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: 批次佇列 `/queue`

**Files:**
- Create: `web/src/lib/store/queue.ts`、`web/src/components/queue/{batch-form.tsx,queue-list.tsx}`
- Modify: `web/src/app/queue/page.tsx`（取代暫時頁面）
- Test: `web/src/lib/store/queue.test.ts`

**Interfaces:**
- Consumes：`getApiClient`（Task 3）；`reduceJob`、`emptyJobView`、`defaultSelection`、`jobProgress`（Task 4）；`exportPosterZip`（Task 7）；`LLM_OPTIONS`、`VLM_OPTIONS`、`DEMO_BRIEFS`（Task 10）
- Produces：
  - `type QueueStatus`、`interface QueueItem`、`interface BatchRequest`、`isFinished(status)`。
  - `useQueueStore`：
    - 狀態 `items`、`paused`。
    - 方法 `enqueue(batch)`、`togglePause()`、`hold(id)`、`release(id)`、`cancel(id)`、`clearFinished()`、`pump()`。
    - 一次一筆；建立任務失敗時該筆為 `error`，然後繼續下一筆。
  - 元件 `BatchForm`、`QueueList`。

- [ ] **Step 1: 寫失敗測試 `web/src/lib/store/queue.test.ts`**

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getApiClient } from '@/lib/api';
import { useQueueStore } from './queue';

const q = () => useQueueStore.getState();
const statuses = () => q().items.map((i) => i.status);
const BATCH = {
  brandId: 'selune', brief: '週年慶主打買一送一', templateIds: ['ig-post' as const], variants: 2,
  products: [{ id: 'prod_selune_serum', name: '精華液' }, { id: 'prod_selune_serum', name: '精華液（第二筆）' }],
};

beforeEach(() => {
  vi.useFakeTimers();
  // 4× 速度：含一次重試的任務約 3.6 秒
  getApiClient().demo?.set({ speed: 4, firstRoundFail: true, forceAllFail: false });
  useQueueStore.setState({ items: [], paused: false });
});
afterEach(() => vi.useRealTimers());

describe('queue store', () => {
  it('runs one item at a time, in order', async () => {
    q().enqueue(BATCH);
    await vi.advanceTimersByTimeAsync(100);
    expect(statuses()).toEqual(['running', 'pending']);
    await vi.advanceTimersByTimeAsync(3_700);
    expect(statuses()).toEqual(['done', 'running']);
    await vi.advanceTimersByTimeAsync(3_700);
    expect(statuses()).toEqual(['done', 'done']);
    expect(q().items[0].view!.bestRenderIds['ig-post']).toBeDefined();
  });

  it('pausing lets the running item finish but does not start the next', async () => {
    q().enqueue(BATCH);
    await vi.advanceTimersByTimeAsync(100);
    q().togglePause();
    await vi.advanceTimersByTimeAsync(8_000);
    expect(statuses()).toEqual(['done', 'pending']);
    q().togglePause();
    await vi.advanceTimersByTimeAsync(3_800);
    expect(statuses()).toEqual(['done', 'done']);
  });

  it('skips held items until they are released', async () => {
    q().enqueue(BATCH);
    q().hold(q().items[1].id);
    await vi.advanceTimersByTimeAsync(8_000);
    expect(statuses()).toEqual(['done', 'held']);
    q().release(q().items[1].id);
    await vi.advanceTimersByTimeAsync(3_800);
    expect(statuses()).toEqual(['done', 'done']);
  });

  it('cancels running and waiting items, then clears finished ones', async () => {
    q().enqueue(BATCH);
    await vi.advanceTimersByTimeAsync(500);
    await q().cancel(q().items[1].id);
    await q().cancel(q().items[0].id);
    await vi.advanceTimersByTimeAsync(100);
    expect(statuses()).toEqual(['cancelled', 'cancelled']);
    q().clearFinished();
    expect(q().items).toEqual([]);
  });

  it('marks an item as failed when the job cannot be created', async () => {
    q().enqueue({ ...BATCH, products: [{ id: 'nope', name: '不存在' }] });
    await vi.advanceTimersByTimeAsync(100);
    expect(statuses()).toEqual(['error']);
    expect(q().items[0].error).toContain('Unknown product');
  });
});
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `npx vitest run src/lib/store/queue.test.ts`
Expected: FAIL，找不到 `./queue`

- [ ] **Step 3: 實作 `web/src/lib/store/queue.ts`**

```ts
import { create } from 'zustand';
import type { TemplateId } from '@/types/contract';
import { getApiClient } from '@/lib/api';
import { emptyJobView, reduceJob, type JobView } from '@/lib/jobs/view';
import { LLM_OPTIONS, VLM_OPTIONS } from './studio';

/** pending 等待中、held 此筆暫停（輪到也不啟動） */
export type QueueStatus = 'pending' | 'held' | 'running' | 'done' | 'needs_review' | 'cancelled' | 'error';

export interface QueueItem {
  id: string;
  brandId: string;
  productId: string;
  productName: string;
  brief: string;
  templateIds: TemplateId[];
  variants: number;
  status: QueueStatus;
  jobId: string | null;
  view: JobView | null;
  error: string | null;
}

export interface BatchRequest {
  brandId: string;
  brief: string;
  products: { id: string; name: string }[];
  templateIds: TemplateId[];
  variants: number;
}

interface QueueState {
  items: QueueItem[];
  /** 整個佇列暫停：執行中的這筆會跑完，但不再啟動下一筆 */
  paused: boolean;
  enqueue: (batch: BatchRequest) => void;
  togglePause: () => void;
  hold: (id: string) => void;
  release: (id: string) => void;
  cancel: (id: string) => Promise<void>;
  clearFinished: () => void;
  /** 沒有執行中的項目且未暫停時，啟動下一筆 */
  pump: () => Promise<void>;
}

const FINISHED: QueueStatus[] = ['done', 'needs_review', 'cancelled', 'error'];
export const isFinished = (s: QueueStatus) => FINISHED.includes(s);

let seq = 0;
const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

/** 批次佇列：多商品 × 多模板，一次執行一筆（每筆是一個商品的任務） */
export const useQueueStore = create<QueueState>()((set, get) => {
  const update = (id: string, patch: Partial<QueueItem>) =>
    set({ items: get().items.map((i) => (i.id === id ? { ...i, ...patch } : i)) });

  return {
    items: [],
    paused: false,

    enqueue: ({ brandId, brief, products, templateIds, variants }) => {
      const added: QueueItem[] = products.map((p) => ({
        id: `q${++seq}`, brandId, productId: p.id, productName: p.name, brief, templateIds: [...templateIds], variants,
        status: 'pending', jobId: null, view: null, error: null,
      }));
      set({ items: [...get().items, ...added] });
      void get().pump();
    },

    togglePause: () => {
      set({ paused: !get().paused });
      void get().pump();
    },
    hold: (id) => {
      if (get().items.find((i) => i.id === id)?.status === 'pending') update(id, { status: 'held' });
    },
    release: (id) => {
      if (get().items.find((i) => i.id === id)?.status === 'held') update(id, { status: 'pending' });
      void get().pump();
    },
    cancel: async (id) => {
      const item = get().items.find((i) => i.id === id);
      if (!item) return;
      if (item.status === 'running' && item.jobId) await getApiClient().cancelJob(item.jobId);
      else if (item.status === 'pending' || item.status === 'held') update(id, { status: 'cancelled' });
    },
    clearFinished: () => set({ items: get().items.filter((i) => !isFinished(i.status)) }),

    pump: async () => {
      const { paused, items } = get();
      if (paused || items.some((i) => i.status === 'running')) return;
      const next = items.find((i) => i.status === 'pending');
      if (!next) return;
      update(next.id, { status: 'running', error: null });
      const api = getApiClient();
      const fail = (err: unknown) => {
        update(next.id, { status: 'error', error: message(err) });
        void get().pump();
      };
      try {
        const parsedBrief = await api.parseBrief(next.brandId, next.brief, next.productId);
        const { jobId } = await api.createJob({
          brandId: next.brandId, productId: next.productId, brief: next.brief, parsedBrief, templateIds: next.templateIds,
          variantsPerTemplate: next.variants, llm: LLM_OPTIONS[0], engine: 'comfyui', vlm: VLM_OPTIONS[0], maxRetries: 2,
        });
        update(next.id, { jobId, view: emptyJobView(jobId) });
        let finished = false;
        let unsubscribe: (() => void) | null = null;
        unsubscribe = api.subscribe(
          jobId,
          (e) => {
            const item = get().items.find((i) => i.id === next.id);
            if (!item?.view) return;
            const view = reduceJob(item.view, e);
            const status: QueueStatus = view.outcome === 'running' ? 'running' : view.outcome;
            update(next.id, { view, status });
            if (status !== 'running' && !finished) {
              finished = true;
              unsubscribe?.();
              void get().pump();
            }
          },
          fail,
        );
        if (finished) unsubscribe();
      } catch (err) {
        fail(err);
      }
    },
  };
});
```

- [ ] **Step 4: 執行測試確認通過**

Run: `npx vitest run src/lib/store`
Expected: `queue.test.ts` 5 個測試、`studio.test.ts` 8 個測試 PASS

- [ ] **Step 5: 建立 `web/src/components/queue/batch-form.tsx`**

```tsx
'use client';

import { useState } from 'react';
import { ListOrdered } from 'lucide-react';
import type { Brand, TemplateId } from '@/types/contract';
import { ProductImage } from '@/components/product/product-image';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { CHANNEL_TEMPLATES } from '@/lib/compose/templates';
import { useProductsStore } from '@/lib/store/products';
import { useQueueStore } from '@/lib/store/queue';
import { DEMO_BRIEFS } from '@/lib/store/studio';

const toggle = <T,>(list: T[], x: T) => (list.includes(x) ? list.filter((y) => y !== x) : [...list, x]);

/** 新增批次：同一句需求 × 多個商品 × 多個模板，每個商品排成一筆任務 */
export function BatchForm({ brand }: { brand: Brand }) {
  const products = useProductsStore((s) => s.products);
  const enqueue = useQueueStore((s) => s.enqueue);
  const [brief, setBrief] = useState(DEMO_BRIEFS[brand.id] ?? '');
  const [productIds, setProductIds] = useState<string[]>([]);
  const [templateIds, setTemplateIds] = useState<TemplateId[]>(['ecom-main', 'ig-post', 'story']);
  const [variants, setVariants] = useState(2);
  const chosen = products.filter((p) => productIds.includes(p.id));
  const ready = brief.trim() !== '' && chosen.length > 0 && templateIds.length > 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>新增批次</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="batch-brief">一句話需求（所有商品共用）</Label>
          <Textarea id="batch-brief" rows={2} value={brief} onChange={(e) => setBrief(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label>商品（{chosen.length}／{products.length}）</Label>
          <div className="grid max-h-64 gap-1.5 overflow-auto">
            {products.map((p) => (
              <label key={p.id} className="flex cursor-pointer items-center gap-2.5 rounded-lg border px-2 py-1.5 text-sm">
                <Checkbox aria-label={p.name} checked={productIds.includes(p.id)} onCheckedChange={() => setProductIds(toggle(productIds, p.id))} />
                <ProductImage product={p} brand={brand} className="size-8 rounded" />
                <span className="truncate">{p.name}</span>
              </label>
            ))}
          </div>
        </div>
        <div className="space-y-1.5">
          <Label>通路模板</Label>
          <div className="flex flex-wrap gap-1.5">
            {CHANNEL_TEMPLATES.map((t) => (
              <label key={t.id} className="flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs">
                <Checkbox aria-label={t.label} checked={templateIds.includes(t.id)} onCheckedChange={() => setTemplateIds(toggle(templateIds, t.id))} />
                {t.label}
              </label>
            ))}
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="batch-variants">每個模板候選張數</Label>
          <Select value={String(variants)} onValueChange={(v) => setVariants(Number(v))}>
            <SelectTrigger id="batch-variants" className="w-32"><SelectValue /></SelectTrigger>
            <SelectContent>
              {[1, 2, 3, 4].map((n) => <SelectItem key={n} value={String(n)}>{n} 張</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </CardContent>
      <CardFooter>
        <Button
          className="w-full"
          disabled={!ready}
          onClick={() => {
            enqueue({ brandId: brand.id, brief, products: chosen.map((p) => ({ id: p.id, name: p.name })), templateIds, variants });
            setProductIds([]);
          }}
        >
          <ListOrdered />
          加入佇列（{chosen.length} 筆任務 × {templateIds.length} 個模板）
        </Button>
      </CardFooter>
    </Card>
  );
}
```

- [ ] **Step 6: 建立 `web/src/components/queue/queue-list.tsx`**

```tsx
'use client';

import { useState } from 'react';
import Link from 'next/link';
import { FileDown, ListOrdered, LoaderCircle, Network, Pause, Play, X } from 'lucide-react';
import { toast } from 'sonner';
import type { Render } from '@/types/contract';
import { EmptyState } from '@/components/common/empty-state';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { getApiClient } from '@/lib/api';
import { getTemplate } from '@/lib/compose/templates';
import { exportPosterZip } from '@/lib/export/posters';
import { defaultSelection, jobProgress, STAGE_LABEL } from '@/lib/jobs/view';
import { useAppStore } from '@/lib/store/app';
import { isFinished, useQueueStore, type QueueItem, type QueueStatus } from '@/lib/store/queue';
import { cn } from '@/lib/utils';

const STATUS: Record<QueueStatus, { label: string; className: string }> = {
  pending: { label: '等待中', className: 'bg-muted text-muted-foreground' },
  held: { label: '已暫停', className: 'bg-amber-50 text-amber-800' },
  running: { label: '執行中', className: 'bg-secondary text-primary' },
  done: { label: '完成', className: 'bg-emerald-50 text-emerald-700' },
  needs_review: { label: '需人工審核', className: 'bg-amber-50 text-amber-800' },
  cancelled: { label: '已取消', className: 'bg-muted text-muted-foreground' },
  error: { label: '失敗', className: 'bg-red-50 text-red-700' },
};

function QueueRow({ item }: { item: QueueItem }) {
  const { hold, release, cancel } = useQueueStore();
  const brand = useAppStore((s) => s.brands.find((b) => b.id === item.brandId));
  const [exporting, setExporting] = useState(false);
  const view = item.view;
  const progress = item.status === 'running' && view ? jobProgress(view) : isFinished(item.status) && item.status !== 'error' && item.status !== 'cancelled' ? 1 : 0;

  // 匯出每個模板的最佳候選（沿用 AI 文案），並寫入歷史紀錄
  const exportBest = async () => {
    if (!view?.jobId || !brand) return;
    setExporting(true);
    try {
      const api = getApiClient();
      const product = (await api.listProducts(item.brandId)).find((p) => p.id === item.productId) ?? null;
      const renders = Object.values(defaultSelection(view)).map((id) => view.renders[id!]).filter((r): r is Render => !!r);
      await exportPosterZip(brand, product, renders.map((render) => ({ render, copy: render.spec.copy })));
      for (const r of renders) await api.selectRender(view.jobId, r.id, r.spec.copy);
      toast.success(`已匯出「${item.productName}」${renders.length} 張海報`, { description: '已寫入歷史紀錄並標記已回寫 RAG。' });
    } catch (err) {
      toast.error('匯出失敗', { description: err instanceof Error ? err.message : String(err) });
    } finally {
      setExporting(false);
    }
  };

  return (
    <li className="space-y-2 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{item.productName}</span>
        <span className={cn('rounded-full px-2 py-0.5 text-xs font-medium', STATUS[item.status].className)}>{STATUS[item.status].label}</span>
        {item.status === 'running' && view?.stage && (
          <span className="text-xs text-muted-foreground">
            {STAGE_LABEL[view.stage]}
            {view.round > 0 && `・第 ${view.round} 輪`}
          </span>
        )}
        <div className="ml-auto flex gap-1">
          {item.status === 'pending' && <Button size="xs" variant="ghost" onClick={() => hold(item.id)}><Pause />暫停此筆</Button>}
          {item.status === 'held' && <Button size="xs" variant="ghost" onClick={() => release(item.id)}><Play />繼續</Button>}
          {(item.status === 'pending' || item.status === 'held' || item.status === 'running') && (
            <Button size="xs" variant="ghost" className="text-muted-foreground hover:text-destructive" onClick={() => void cancel(item.id)}>
              <X />
              取消
            </Button>
          )}
          {item.jobId && (
            <Button size="xs" variant="ghost" asChild>
              <Link href={`/agent?job=${encodeURIComponent(item.jobId)}`}><Network />透視</Link>
            </Button>
          )}
          {(item.status === 'done' || item.status === 'needs_review') && (
            <Button size="xs" variant="outline" disabled={exporting} onClick={() => void exportBest()}>
              {exporting ? <LoaderCircle className="animate-spin" /> : <FileDown />}
              匯出最佳
            </Button>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-1">
        {item.templateIds.map((t) => <Badge key={t} variant="outline">{getTemplate(t).label}</Badge>)}
        <span className="text-xs text-muted-foreground">× {item.variants} 張</span>
      </div>
      <Progress value={progress * 100} className="h-1.5" />
      {item.error && <p className="text-xs text-destructive">{item.error}</p>}
    </li>
  );
}

export function QueueList() {
  const { items, paused, togglePause, clearFinished } = useQueueStore();
  const done = items.filter((i) => isFinished(i.status)).length;
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center gap-2">
        <CardTitle>佇列</CardTitle>
        <span className="text-sm text-muted-foreground">{done}／{items.length} 筆已結束</span>
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant="outline" disabled={!items.length} onClick={togglePause}>
            {paused ? <Play /> : <Pause />}
            {paused ? '繼續佇列' : '暫停佇列'}
          </Button>
          <Button size="sm" variant="ghost" disabled={!done} onClick={clearFinished}>清除已結束</Button>
        </div>
      </CardHeader>
      <CardContent className="px-0">
        {paused && <p className="mx-4 mb-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">佇列已暫停：執行中的這筆會跑完，之後不會再啟動新的任務。</p>}
        {items.length ? (
          <ul className="divide-y border-t">{items.map((i) => <QueueRow key={i.id} item={i} />)}</ul>
        ) : (
          <div className="px-4">
            <EmptyState icon={ListOrdered} title="佇列是空的">選擇商品與模板後加入佇列，任務會一筆一筆執行。</EmptyState>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 7: 取代 `web/src/app/queue/page.tsx`**

```tsx
'use client';

import { useEffect } from 'react';
import { PageHeader } from '@/components/common/page-header';
import { BatchForm } from '@/components/queue/batch-form';
import { QueueList } from '@/components/queue/queue-list';
import { useCurrentBrand } from '@/lib/store/app';
import { useProductsStore } from '@/lib/store/products';

export default function QueuePage() {
  const brand = useCurrentBrand();
  const load = useProductsStore((s) => s.load);
  useEffect(() => {
    void load(brand.id);
  }, [brand.id, load]);

  return (
    <>
      <PageHeader title="批次佇列" description="多商品 × 多模板排程，逐筆顯示進度；可暫停整個佇列、暫停或取消單筆。" />
      <div className="grid items-start gap-5 lg:grid-cols-[380px_minmax(0,1fr)]">
        {/* key：切換品牌時重設表單 */}
        <BatchForm key={brand.id} brand={brand} />
        <QueueList />
      </div>
    </>
  );
}
```

- [ ] **Step 8: 驗證**

Run: `npm run test && npm run typecheck && npm run lint`，再 `npm run dev` 開啟 `/queue`，勾兩個商品與三個模板後加入佇列

Expected：
- 指令：30 個測試檔、226 個測試 PASS。
- 畫面：
  - 第一筆「執行中」並顯示階段與輪次，第二筆「等待中」。第一筆完成後第二筆自動開始。
  - 「暫停佇列」後，正在執行的那筆跑完，下一筆不會啟動；「繼續佇列」後恢復。
  - 等待中的項目可「暫停此筆」或「取消」。
  - 完成的項目可「匯出最佳」：下載 zip，並寫入歷史紀錄。

- [ ] **Step 9: Commit**

```bash
git add web/src/lib/store web/src/components/queue web/src/app/queue
git commit -m "feat: add batch queue with pause, hold and cancel" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: 歷史紀錄 `/history`

**Files:**
- Create: `web/src/lib/history/filter.ts`、`web/src/components/history/history-card.tsx`
- Modify: `web/src/app/history/page.tsx`（取代暫時頁面）
- Test: `web/src/lib/history/filter.test.ts`

**Interfaces:**
- Consumes：`listHistory`、`setFavorite`、`listProducts`（Task 1、2）；`prefill`（Task 10）；`exportPosterPng`（Task 7）；`PosterCanvas`、`ScoreBadge`（Task 11）
- Produces：
  - `interface HistoryFilters { brandId; templateId; from; to; favoritesOnly }`。
  - `localDate(iso)`。
  - `filterHistory(entries, filters)`：最新的在前，日期區間包含首尾兩天，以本地時間計算。
  - 元件 `HistoryCard`。

- [ ] **Step 1: 寫失敗測試 `web/src/lib/history/filter.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import type { HistoryEntry, TemplateId } from '@/types/contract';
import { filterHistory, localDate, type HistoryFilters } from './filter';

const at = (y: number, m: number, d: number, h = 12) => new Date(y, m - 1, d, h).toISOString();
const entry = (id: string, brandId: string, templateId: TemplateId, selectedAt: string, favorite = false) =>
  ({ id, brandId, templateId, selectedAt, favorite }) as HistoryEntry;

const ENTRIES = [
  entry('a', 'selune', 'ig-post', at(2026, 10, 1)),
  entry('b', 'selune', 'story', at(2026, 10, 3), true),
  entry('c', 'misty-isle', 'ig-post', at(2026, 10, 5)),
];
const ALL: HistoryFilters = { brandId: 'all', templateId: 'all', from: null, to: null, favoritesOnly: false };
const ids = (f: Partial<HistoryFilters>) => filterHistory(ENTRIES, { ...ALL, ...f }).map((e) => e.id);

describe('filterHistory', () => {
  it('returns everything newest first without filters', () => {
    expect(ids({})).toEqual(['c', 'b', 'a']);
  });

  it('filters by brand, channel and favorites', () => {
    expect(ids({ brandId: 'selune' })).toEqual(['b', 'a']);
    expect(ids({ templateId: 'ig-post' })).toEqual(['c', 'a']);
    expect(ids({ favoritesOnly: true })).toEqual(['b']);
  });

  it('filters by an inclusive local date range', () => {
    expect(ids({ from: '2026-10-03' })).toEqual(['c', 'b']);
    expect(ids({ to: '2026-10-03' })).toEqual(['b', 'a']);
    expect(ids({ from: '2026-10-02', to: '2026-10-04' })).toEqual(['b']);
  });

  it('localDate uses the local calendar day', () => {
    expect(localDate(new Date(2026, 9, 6, 23, 30).toISOString())).toBe('2026-10-06');
  });
});
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `npx vitest run src/lib/history`
Expected: FAIL，找不到 `./filter`

- [ ] **Step 3: 實作 `web/src/lib/history/filter.ts`**

```ts
import type { HistoryEntry, TemplateId } from '@/types/contract';

export interface HistoryFilters {
  brandId: string | 'all';
  templateId: TemplateId | 'all';
  /** YYYY-MM-DD（本地時間，含當天）；null 代表不限 */
  from: string | null;
  to: string | null;
  favoritesOnly: boolean;
}

const pad = (n: number) => String(n).padStart(2, '0');

/** ISO 時間 → 本地日期 YYYY-MM-DD */
export function localDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** 歷史紀錄篩選（品牌、通路、日期、收藏），最新的在前 */
export function filterHistory(entries: HistoryEntry[], f: HistoryFilters): HistoryEntry[] {
  return entries
    .filter((e) => f.brandId === 'all' || e.brandId === f.brandId)
    .filter((e) => f.templateId === 'all' || e.templateId === f.templateId)
    .filter((e) => !f.favoritesOnly || e.favorite)
    .filter((e) => {
      const day = localDate(e.selectedAt);
      return (!f.from || day >= f.from) && (!f.to || day <= f.to);
    })
    .sort((a, b) => b.selectedAt.localeCompare(a.selectedAt));
}
```

- [ ] **Step 4: 執行測試確認通過**

Run: `npx vitest run src/lib/history`
Expected: 4 個測試 PASS

- [ ] **Step 5: 建立 `web/src/components/history/history-card.tsx`**

```tsx
'use client';

import { Download, RotateCcw, Star } from 'lucide-react';
import type { Brand, HistoryEntry, Product } from '@/types/contract';
import { PosterCanvas } from '@/components/poster/poster-canvas';
import { ScoreBadge } from '@/components/poster/score-badge';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { getTemplate } from '@/lib/compose/templates';
import { cn } from '@/lib/utils';

export function HistoryCard({ entry, brand, product, onFavorite, onDownload, onRedo }: {
  entry: HistoryEntry;
  brand: Brand;
  product: Product | null;
  onFavorite: () => void;
  onDownload: () => void;
  onRedo: () => void;
}) {
  return (
    <div className="flex flex-col overflow-hidden rounded-xl border bg-card">
      <PosterCanvas render={entry.render} copy={entry.copy} product={product} brand={brand} pixelWidth={400} />
      <div className="flex flex-1 flex-col gap-2 p-3">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <p className="truncate font-semibold">{entry.copy.productName}</p>
            <p className="text-xs text-muted-foreground">
              {getTemplate(entry.templateId).label}・{new Date(entry.selectedAt).toLocaleString('zh-TW', { dateStyle: 'medium', timeStyle: 'short' })}
            </p>
          </div>
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label={entry.favorite ? '取消收藏' : '收藏'}
            aria-pressed={entry.favorite}
            onClick={onFavorite}
          >
            <Star className={cn(entry.favorite && 'fill-amber-400 text-amber-500')} />
          </Button>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <ScoreBadge render={entry.render} />
          {entry.writtenToRag && <Badge variant="outline" className="border-indigo-200 bg-indigo-50 text-indigo-700">已回寫 RAG</Badge>}
          {!product && <Badge variant="outline">商品已刪除</Badge>}
        </div>
        <div className="mt-auto flex gap-1 pt-1">
          <Button size="sm" variant="outline" onClick={onDownload}>
            <Download />
            PNG
          </Button>
          <Button size="sm" variant="ghost" onClick={onRedo}>
            <RotateCcw />
            以相同設定重做
          </Button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: 取代 `web/src/app/history/page.tsx`**

```tsx
'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Clock } from 'lucide-react';
import { toast } from 'sonner';
import type { HistoryEntry, Product, TemplateId } from '@/types/contract';
import { EmptyState } from '@/components/common/empty-state';
import { PageHeader } from '@/components/common/page-header';
import { HistoryCard } from '@/components/history/history-card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { getApiClient } from '@/lib/api';
import { CHANNEL_TEMPLATES } from '@/lib/compose/templates';
import { exportPosterPng } from '@/lib/export/posters';
import { filterHistory, type HistoryFilters } from '@/lib/history/filter';
import { useAppStore } from '@/lib/store/app';
import { useStudioStore } from '@/lib/store/studio';

export default function HistoryPage() {
  const router = useRouter();
  const brands = useAppStore((s) => s.brands);
  const currentBrandId = useAppStore((s) => s.brandId);
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [filters, setFilters] = useState<HistoryFilters>({ brandId: currentBrandId, templateId: 'all', from: null, to: null, favoritesOnly: false });

  useEffect(() => {
    const api = getApiClient();
    void api.listHistory().then(setEntries);
    // 縮圖需要商品照：讀取所有品牌的商品
    void Promise.all(brands.map((b) => api.listProducts(b.id))).then((lists) => setProducts(lists.flat()));
  }, [brands]);

  const patch = (p: Partial<HistoryFilters>) => setFilters({ ...filters, ...p });
  const visible = entries ? filterHistory(entries, filters) : [];

  const toggleFavorite = async (entry: HistoryEntry) => {
    const updated = await getApiClient().setFavorite(entry.id, !entry.favorite);
    setEntries((list) => list?.map((e) => (e.id === updated.id ? updated : e)) ?? null);
  };

  const redo = (entry: HistoryEntry) => {
    useAppStore.getState().setBrandId(entry.brandId);
    useStudioStore.getState().prefill(entry.input);
    router.push('/studio');
    toast.info('已帶入當時的需求與設定', { description: '確認後按「開始生成」。' });
  };

  return (
    <>
      <PageHeader title="歷史紀錄" description="選定並匯出的海報。每一張都已回寫 RAG，成為之後檢索的歷史優秀案例。" />
      <div className="mb-5 flex flex-wrap items-end gap-3 rounded-xl border bg-card p-3">
        <div className="space-y-1.5">
          <Label htmlFor="h-brand">品牌</Label>
          <Select value={filters.brandId} onValueChange={(v) => patch({ brandId: v })}>
            <SelectTrigger id="h-brand" className="w-48"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部品牌</SelectItem>
              {brands.map((b) => <SelectItem key={b.id} value={b.id}>{b.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="h-channel">通路</Label>
          <Select value={filters.templateId} onValueChange={(v) => patch({ templateId: v as TemplateId | 'all' })}>
            <SelectTrigger id="h-channel" className="w-36"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部通路</SelectItem>
              {CHANNEL_TEMPLATES.map((t) => <SelectItem key={t.id} value={t.id}>{t.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="h-from">起日</Label>
          <Input id="h-from" type="date" className="w-40" value={filters.from ?? ''} onChange={(e) => patch({ from: e.target.value || null })} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="h-to">迄日</Label>
          <Input id="h-to" type="date" className="w-40" value={filters.to ?? ''} onChange={(e) => patch({ to: e.target.value || null })} />
        </div>
        <label className="flex h-8 items-center gap-2 text-sm">
          <Switch checked={filters.favoritesOnly} onCheckedChange={(v) => patch({ favoritesOnly: v })} />
          只看收藏
        </label>
        <span className="ml-auto text-sm text-muted-foreground">{visible.length} 張</span>
      </div>

      {entries && !visible.length ? (
        <EmptyState icon={Clock} title={entries.length ? '沒有符合條件的紀錄' : '還沒有歷史紀錄'}>
          在「新任務」選圖後按「匯出 zip 並寫入歷史」，紀錄就會出現在這裡。
        </EmptyState>
      ) : (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
          {visible.map((entry) => {
            const brand = brands.find((b) => b.id === entry.brandId);
            if (!brand) return null;
            const product = products.find((p) => p.id === entry.productId) ?? null;
            return (
              <HistoryCard
                key={entry.id}
                entry={entry}
                brand={brand}
                product={product}
                onFavorite={() => void toggleFavorite(entry)}
                onDownload={() => void exportPosterPng(brand, product, { render: entry.render, copy: entry.copy })}
                onRedo={() => redo(entry)}
              />
            );
          })}
        </div>
      )}
    </>
  );
}
```

- [ ] **Step 7: 驗證**

Run: `npm run test && npm run typecheck && npm run lint`，再 `npm run dev` 開啟 `/history`

Expected：
- 指令：31 個測試檔、230 個測試 PASS。
- 畫面：
  - Task 12、14 匯出的海報出現在這裡，套用使用者編輯後的文案，並標示「已回寫 RAG」。
  - 可依品牌（預設目前品牌，可選全部）、通路、起訖日期篩選。
  - 星號切換收藏，「只看收藏」生效，重新整理後仍保留。
  - 「PNG」下載單張。
  - 「以相同設定重做」：切換到該品牌，帶入需求、拆解欄位、模板、張數與模型設定，然後回到 `/studio`。
  - 商品已刪除時，卡片標示「商品已刪除」，只畫背景與文字。

- [ ] **Step 8: Commit**

```bash
git add web/src/lib/history web/src/components/history web/src/app/history
git commit -m "feat: add history page with filters, favorites and redo" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 16: 品牌知識庫 `/brands`

**Files:**
- Create: `web/src/components/brands/{brand-overview.tsx,chunk-list.tsx,doc-ingest.tsx,case-studies.tsx}`
- Modify: `web/src/app/brands/page.tsx`（取代暫時頁面）

**Interfaces:**
- Consumes：`ingestBrandDocument`、`listBrands`（Task 2）；`useAppStore.loadBrands`（Task 9）；`PosterCanvas`（Task 11）
- Produces：`TAG_LABEL: Record<RagTag, string>`；元件 `BrandOverview`、`ChunkList`、`DocIngest`、`CaseStudies`

- [ ] **Step 1: 建立 `web/src/components/brands/brand-overview.tsx`**

```tsx
import type { Brand, Palette } from '@/types/contract';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

const ROLE: Record<keyof Palette, string> = { primary: '主色', secondary: '輔助色', accent: '點綴色', ink: '文字' };
const pct = (v: number) => `${Math.round(v * 100)}%`;

/** 品牌 CI：色票、字型、版面規則、禁用詞與合規替代用語 */
export function BrandOverview({ brand }: { brand: Brand }) {
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>{brand.name}</CardTitle>
          <CardDescription>{brand.category}・品牌 CI {brand.ciVersion}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-4 gap-2">
            {(Object.keys(ROLE) as (keyof Palette)[]).map((role) => (
              <div key={role} className="overflow-hidden rounded-lg border text-xs">
                <div className="h-10 border-b" style={{ background: brand.palette[role] }} />
                <div className="px-2 py-1.5">
                  <p className="font-medium">{ROLE[role]}</p>
                  <p className="font-mono text-muted-foreground">{brand.palette[role].toUpperCase()}</p>
                </div>
              </div>
            ))}
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">標題字型</dt>
            <dd style={{ fontFamily: 'var(--font-serif)' }}>{brand.fonts.headline}</dd>
            <dt className="text-muted-foreground">內文字型</dt>
            <dd>{brand.fonts.body}</dd>
            <dt className="text-muted-foreground">主色色差上限</dt>
            <dd>ΔE2000 ≤ {brand.rules.maxDeltaE}</dd>
            <dt className="text-muted-foreground">留白比例</dt>
            <dd>≥ {pct(brand.rules.minWhitespace)}</dd>
            <dt className="text-muted-foreground">商品主體佔比</dt>
            <dd>{pct(brand.rules.productRatio[0])} – {pct(brand.rules.productRatio[1])}</dd>
          </dl>
          <p className="rounded-lg bg-muted px-3 py-2 font-mono text-xs leading-relaxed text-muted-foreground">{brand.visualStyle}</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>禁用詞與合規替代用語</CardTitle>
          <CardDescription>
            規則型審查比對禁用詞；第一輪失敗時，Query Rewriting 依替代用語改寫文案。
            {brand.disclaimerPhrase && `效果宣稱需加註「${brand.disclaimerPhrase}」。`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="py-1.5 font-medium">禁用詞</th>
                <th className="py-1.5 font-medium">替代用語</th>
              </tr>
            </thead>
            <tbody>
              {brand.bannedWords.map((w) => (
                <tr key={w} className="border-b last:border-0">
                  <td className="py-1.5">
                    <Badge variant="outline" className="border-red-200 bg-red-50 text-red-700">{w}</Badge>
                  </td>
                  <td className="py-1.5">{brand.replacements[w] ? brand.replacements[w] : <span className="text-muted-foreground">刪除</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: 建立 `web/src/components/brands/chunk-list.tsx`**

```tsx
'use client';

import { useState } from 'react';
import type { RagChunk, RagTag } from '@/types/contract';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

export const TAG_LABEL: Record<RagTag, string> = {
  color: '色彩', logo: 'Logo', law: '法規', layout: '版型', font: '字型', history: '歷史成效', general: '其他',
};

/** CI 手冊切塊（Chroma 中的向量片段），可依標籤篩選 */
export function ChunkList({ chunks }: { chunks: RagChunk[] }) {
  const [tag, setTag] = useState<RagTag | 'all'>('all');
  const tags = [...new Set(chunks.map((c) => c.tag))];
  const visible = tag === 'all' ? chunks : chunks.filter((c) => c.tag === tag);
  return (
    <Card>
      <CardHeader>
        <CardTitle>CI 手冊切塊（{chunks.length}）</CardTitle>
        <CardDescription>RAG 檢索的來源：Chroma 向量召回後，再由 BGE Reranker 重新排序。</CardDescription>
        <div className="flex flex-wrap gap-1.5 pt-1">
          {(['all', ...tags] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTag(t)}
              className={cn('rounded-full border px-2.5 py-0.5 text-xs', tag === t ? 'border-primary bg-secondary font-semibold text-primary' : 'text-muted-foreground')}
            >
              {t === 'all' ? '全部' : TAG_LABEL[t]}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent>
        <ul className="divide-y rounded-lg border">
          {visible.map((c) => (
            <li key={c.id} className="space-y-1 px-3 py-2.5">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <Badge variant="secondary">{TAG_LABEL[c.tag]}</Badge>
                <span className="font-medium">{c.section}</span>
                <span className="text-muted-foreground">{c.source}</span>
                {c.id.includes('#doc-') && <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-emerald-700">新上傳</Badge>}
                {c.id.endsWith('-alt') && <Badge variant="outline">Query Rewriting 專用</Badge>}
                <span className="ml-auto font-mono text-[11px] text-muted-foreground">{c.id}</span>
              </div>
              <p className="text-sm leading-relaxed">{c.text}</p>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 3: 建立 `web/src/components/brands/doc-ingest.tsx`**

```tsx
'use client';

import { useRef, useState } from 'react';
import { CircleCheck, Database, FileText, LoaderCircle, Upload } from 'lucide-react';
import type { Brand, IngestEvent, RagChunk } from '@/types/contract';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { getApiClient } from '@/lib/api';
import { useAppStore } from '@/lib/store/app';
import { cn } from '@/lib/utils';
import { TAG_LABEL } from './chunk-list';

interface Ingest {
  status: 'running' | 'done' | 'error';
  source: string;
  chunks: RagChunk[];
  embedded: { chunkId: string; dims: number; preview: number[] }[];
  stored: { collection: string; count: number } | null;
  error: string | null;
}

function reduce(s: Ingest, e: IngestEvent): Ingest {
  switch (e.type) {
    case 'ingest.chunked':
      return { ...s, chunks: e.chunks };
    case 'ingest.embedded':
      return { ...s, embedded: [...s.embedded, { chunkId: e.chunkId, dims: e.dims, preview: e.preview }] };
    case 'ingest.stored':
      return { ...s, stored: { collection: e.collection, count: e.count } };
  }
}

function StepRow({ n, title, active, done, children }: { n: number; title: string; active: boolean; done: boolean; children?: React.ReactNode }) {
  return (
    <div className={cn('rounded-lg border p-3', active && 'border-primary bg-secondary/40')}>
      <p className="flex items-center gap-2 text-sm font-semibold">
        {done ? <CircleCheck className="size-4 text-success" /> : active ? <LoaderCircle className="size-4 animate-spin text-primary" /> : <span className="grid size-4 place-items-center rounded-full border text-[10px]">{n}</span>}
        {title}
      </p>
      {children && <div className="mt-2">{children}</div>}
    </div>
  );
}

/** 上傳品牌文件（.md／.txt），展示 chunking → embedding → 寫入 Chroma 的過程 */
export function DocIngest({ brand }: { brand: Brand }) {
  const input = useRef<HTMLInputElement>(null);
  const loadBrands = useAppStore((s) => s.loadBrands);
  const [ingest, setIngest] = useState<Ingest | null>(null);

  const run = async (file: File) => {
    const text = await file.text();
    setIngest({ status: 'running', source: file.name, chunks: [], embedded: [], stored: null, error: null });
    try {
      await getApiClient().ingestBrandDocument(brand.id, { name: file.name, text }, (e) => setIngest((s) => (s ? reduce(s, e) : s)));
      setIngest((s) => (s ? { ...s, status: 'done' } : s));
      await loadBrands();
    } catch (err) {
      setIngest((s) => (s ? { ...s, status: 'error', error: err instanceof Error ? err.message : String(err) } : s));
    }
  };

  const total = ingest?.chunks.length ?? 0;
  const embedded = ingest?.embedded.length ?? 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>上傳品牌文件</CardTitle>
        <CardDescription>支援 .md 與 .txt。Markdown 的 # 標題會成為切塊的段落名稱；同名文件重新上傳會取代舊的切塊。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Button variant="outline" disabled={ingest?.status === 'running'} onClick={() => input.current?.click()}>
          <Upload />
          選擇文件
        </Button>
        <input
          ref={input}
          type="file"
          accept=".md,.txt,text/plain,text/markdown"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void run(file);
            e.target.value = '';
          }}
        />
        {ingest && (
          <div className="space-y-2">
            <p className="flex items-center gap-1.5 text-sm text-muted-foreground"><FileText className="size-4" />{ingest.source}</p>
            <StepRow n={1} title={`切塊 Chunking${total ? `：${total} 塊` : ''}`} active={ingest.status === 'running' && !total} done={total > 0}>
              {total > 0 && (
                <ul className="space-y-1 text-xs">
                  {ingest.chunks.map((c) => (
                    <li key={c.id} className="truncate"><span className="mr-1.5 rounded bg-muted px-1">{TAG_LABEL[c.tag]}</span>{c.section}｜{c.text}</li>
                  ))}
                </ul>
              )}
            </StepRow>
            <StepRow n={2} title={`向量化 Embedding（bge-m3）${total ? `：${embedded}/${total}` : ''}`} active={total > 0 && embedded < total} done={total > 0 && embedded === total}>
              {total > 0 && (
                <div className="space-y-1.5">
                  <Progress value={(embedded / total) * 100} />
                  {ingest.embedded.at(-1) && (
                    <p className="truncate font-mono text-[11px] text-muted-foreground">
                      [{ingest.embedded.at(-1)!.preview.join(', ')}, …] · {ingest.embedded.at(-1)!.dims} 維
                    </p>
                  )}
                </div>
              )}
            </StepRow>
            <StepRow n={3} title="寫入 Chroma" active={total > 0 && embedded === total && !ingest.stored} done={ingest.stored !== null}>
              {ingest.stored && (
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Database className="size-3.5" />
                  collection「{ingest.stored.collection}」新增 {ingest.stored.count} 筆
                </p>
              )}
            </StepRow>
            {ingest.error && <p className="text-sm text-destructive">{ingest.error}</p>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 4: 建立 `web/src/components/brands/case-studies.tsx`**

```tsx
'use client';

import { useEffect, useState } from 'react';
import type { Brand, HistoryEntry, Product } from '@/types/contract';
import { PosterCanvas } from '@/components/poster/poster-canvas';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { getApiClient } from '@/lib/api';
import { getTemplate } from '@/lib/compose/templates';

/** 歷史優秀案例：品牌資料內建的案例 + 使用者挑中並回寫 RAG 的圖 */
export function CaseStudies({ brand }: { brand: Brand }) {
  const [picked, setPicked] = useState<HistoryEntry[]>([]);
  const [products, setProducts] = useState<Product[]>([]);

  useEffect(() => {
    const api = getApiClient();
    void api.listHistory(brand.id).then((h) => setPicked(h.filter((e) => e.writtenToRag).slice(0, 8)));
    void api.listProducts(brand.id).then(setProducts);
  }, [brand.id]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>歷史優秀案例</CardTitle>
        <CardDescription>RAG 會檢索這些案例的風格與成效；使用者在新任務選定的圖也會回寫到這裡。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ul className="grid gap-2 sm:grid-cols-2">
          {brand.caseStudies.map((c) => (
            <li key={c.id} className="rounded-lg border p-3 text-sm">
              <div className="flex items-center gap-2">
                <span className="font-semibold">{c.title}</span>
                <span className="ml-auto rounded-full bg-secondary px-2 py-0.5 text-xs font-semibold text-primary">CTR {c.ctr}%</span>
              </div>
              <p className="text-xs text-muted-foreground">{c.channel}・{c.notes}</p>
            </li>
          ))}
        </ul>
        <div className="space-y-2">
          <p className="text-sm font-medium">使用者挑中的圖（{picked.length}）</p>
          {picked.length ? (
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-8">
              {picked.map((e) => (
                <figure key={e.id} className="space-y-1">
                  <div className="overflow-hidden rounded-md border">
                    <PosterCanvas render={e.render} copy={e.copy} product={products.find((p) => p.id === e.productId) ?? null} brand={brand} pixelWidth={200} />
                  </div>
                  <figcaption className="truncate text-[11px] text-muted-foreground">{getTemplate(e.templateId).label}</figcaption>
                </figure>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">還沒有。在新任務選圖並匯出後會出現在這裡。</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 5: 取代 `web/src/app/brands/page.tsx`**

```tsx
'use client';

import { PageHeader } from '@/components/common/page-header';
import { BrandOverview } from '@/components/brands/brand-overview';
import { CaseStudies } from '@/components/brands/case-studies';
import { ChunkList } from '@/components/brands/chunk-list';
import { DocIngest } from '@/components/brands/doc-ingest';
import { useCurrentBrand } from '@/lib/store/app';

export default function BrandsPage() {
  const brand = useCurrentBrand();
  return (
    <>
      <PageHeader title="品牌知識庫" description="品牌 CI、禁用詞、CI 手冊切塊與歷史案例；這些內容是 RAG 檢索與合規審查的依據。" />
      <div className="space-y-5">
        <BrandOverview brand={brand} />
        <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
          <ChunkList chunks={brand.guidelineChunks} />
          {/* key：切換品牌時清掉上一個品牌的上傳進度 */}
          <DocIngest key={brand.id} brand={brand} />
        </div>
        <CaseStudies brand={brand} />
      </div>
    </>
  );
}
```

- [ ] **Step 6: 驗證**

Run: `npm run typecheck && npm run lint`，再 `npm run dev` 開啟 `/brands`，上傳下列內容的 `ci_update.md`：

```markdown
# 色彩更新
主色維持 #2F4A44，新增輔助色「晨霧藍」#DCE6E4。

# Logo
- 深色背景使用反白 Logo
- Logo 淨空區至少 0.5 倍高度

2026 春季素材 CTR 3.9%，霧面桌面效果最好。
```

Expected：
- 頁面內容：
  - 色票（主色／輔助色／點綴色／文字）、字型、版面規則。
  - 禁用詞與替代用語對照表。
  - CI 手冊切塊 7 塊，可依標籤篩選，`-alt` 切塊標示「Query Rewriting 專用」。
  - 歷史案例，包含使用者挑中的圖。
- 上傳後依序顯示：
  1. 切塊：3 塊，標籤為色彩、Logo、歷史成效。
  2. 向量化 3/3：顯示向量前幾維與「1024 維」。
  3. 寫入 Chroma：collection「misty-isle_ci」或「selune_ci」新增 3 筆。
- 完成後切塊列表變成 10 塊，新的 3 塊標示「新上傳」。重新上傳同名檔案會取代這 3 塊，不會累加。

- [ ] **Step 7: Commit**

```bash
git add web/src/components/brands web/src/app/brands
git commit -m "feat: add brand knowledge base with document ingest" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 17: README 與全套驗收

**Files:**
- Modify: `web/README.md`（取代 create-next-app 的預設內容）

- [ ] **Step 1: 取代 `web/README.md`**

````markdown
# 虛實整合 GenAI Agent — 前端（第一階段）

Next.js 16（App Router）+ TypeScript + Tailwind CSS v4 + shadcn/ui + Zustand。第一階段由瀏覽器內的 `MockApiClient` 模擬整條 Agent 流程，送出的事件與第二階段 FastAPI WebSocket 相同，所以不需要後端。

## 需求

- Node.js 24、npm 11

## 開始

```bash
npm ci
npm run dev
```

開啟 http://localhost:3000（會導向「新任務」）。預設就是 mock 模式；要明確設定時複製 `.env.example` 成 `.env.local`。

## 指令

| 指令 | 用途 |
|---|---|
| `npm run dev` | 開發伺服器 |
| `npm run test` | Vitest 單元測試 |
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
| Agent 透視 | `/agent`、`/dashboard` | Plan 3 實作（目前為事件 Log 與預留頁） |

## 資料保存

- 商品、歷史紀錄與上傳的品牌文件存在瀏覽器的 IndexedDB（資料庫 `genai-poster-agent`）；清除網站資料就會重置。
- 自己的商品照可放在 repo 根目錄的 `assets/products/`（已在 `.gitignore`，不會上傳 GitHub），開發模式下到「商品庫」一鍵匯入，檔名即商品名稱。
- 字型使用 `@fontsource-variable` 自帶的 Noto Sans／Serif TC，執行時不連外部網路。

## Demo 控制台

畫面右下角「Demo」：播放速度 1×／2×／4×、強制首輪失敗（展示 Query Rewriting 與重試）、強制全部失敗（展示「需人工審核」）。

## 目錄

```
src/
├─ app/                 路由與 api/local-products（開發用）
├─ components/          ui（shadcn）、layout、studio、product、queue、history、brands、poster、agent
├─ lib/
│  ├─ api/              ApiClient 介面、mock/（MockApiClient、劇本、示範資料、IndexedDB）
│  ├─ agent/            Prompt 構建、修正策略、版本差異
│  ├─ compose/          版型、排版引擎（scene）、程序化素材（art）、Canvas 繪製（paint／render）
│  ├─ review/           規則型合規審查、ΔE2000、文案重新檢查
│  ├─ jobs/             事件 → 畫面狀態（reducer）
│  ├─ export/           檔名、zip、下載
│  ├─ store/            Zustand stores
│  └─ server/           只在伺服器端執行的工具
└─ types/contract.ts    前後端資料約定
```
````

- [ ] **Step 2: 全套驗證**

Run: `npm run test && npm run typecheck && npm run lint && npm run build`
Expected：
- 31 個測試檔、230 個測試 PASS。
- typecheck 與 lint 無錯誤。
- 建置成功，路由表與 Task 9 Step 24 相同。
- lint 有錯時修正後重跑，不得用 `eslint-disable` 繞過。

- [ ] **Step 3: 依規格第 4 節手動走一次主流程**

用全新的瀏覽器設定檔（或先清除 localhost 的網站資料）執行 `npm run dev`：

1. `/studio`：SÉLUNE，按「Agent 拆解需求」，勾電商主圖、IG 貼文、限時動態，每個模板 4 張，開始生成。
2. 確認第 1 輪未通過 → Query Rewriting → 第 2 輪通過。以 1× 速度約 14.5 秒；Demo 控制台切 4× 約 3.6 秒。
3. 在結果牆換選另一張候選，修改特價為 999，匯出 zip。確認 zip 內 3 張 PNG 的檔名與尺寸，並確認價格是 999。
4. `/history` 出現 3 筆並標示「已回寫 RAG」。`/brands` 的「使用者挑中的圖」出現同樣的圖。
5. 切換到霧嶼咖啡，重複步驟 1–3，背景、Logo 與文案風格都應換成該品牌。
6. 寬度 375px 時，每一頁都沒有水平捲軸；瀏覽器 Console 沒有錯誤。

- [ ] **Step 4: Commit**

```bash
git add web/README.md
git commit -m "docs: describe the workbench UI in the web README" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 本計畫範圍外（留給 Plan 3）

| 規格項目 | 歸屬 |
|---|---|
| `/agent` 完整版：流程節點圖、WebSocket 事件串流、JSON Prompt、`workflow_api.json` 注入參數對照、RAG 召回與 Rerank 前後分數、合規報告與 BBox 疊圖、重試 diff（`diffSpecs`） | Plan 3（取代本計畫的 `AgentPreview`） |
| `/dashboard` 成效儀表板與 `ApiClient` 統計方法（Recharts） | Plan 3 |
| 事件時間戳與序號（事件串流顯示、第二階段重新連線） | Plan 3 |
| Playwright E2E：主流程（輸入 → 生成 → 第一輪失敗並重試 → 選圖 → 改價格 → 匯出 zip）與 Agent 透視的重試 diff | Plan 3（可直接使用本計畫加上的 `aria-label`：模板 checkbox、商品選單、需求輸入框） |
