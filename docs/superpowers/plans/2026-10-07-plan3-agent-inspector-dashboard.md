# Plan 3：Agent 透視、成效儀表板與 E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成「Agent 透視」模式，以及第一階段剩下的規格項目：
- `/agent` 任務透視：流程節點、WebSocket 事件串流、JSON Prompt、`workflow_api.json` 注入參數對照、RAG 召回與 Rerank、合規報告與 BBox 疊圖、重試 diff。
- `/dashboard` 成效儀表板：通過率、平均重試次數、平均耗時、每張成本、各檢查項失敗分布、Rerank 對命中率的影響。
- 事件加上序號與時間戳。
- Playwright E2E。

**Architecture:**
- 事件訊息改為 `JobMessage`（`JobEvent` 加上 `seq` 與 `ts`），由 mock 在送出時加上。既有的 reducer 與訂閱者不用改。
- mock 把已結束的任務（含完整訊息）存進 IndexedDB，所以重新整理後 Agent 透視與儀表板仍有資料。
- Agent 透視只讀事件：訊息由 `useJobStream` 累積成 `JobView`。下列純函式負責整理畫面要的資料，都有 Vitest 測試：
  - `lib/agent/flow.ts`：流程節點的狀態與耗時。
  - `lib/agent/events.ts`：事件分類與摘要。
  - `lib/agent/inspect.ts`：Prompt、注入參數、Rerank、BBox 疊圖、重試 diff。
- 儀表板統計是純函式 `lib/stats/dashboard.ts`，透過 `ApiClient.getDashboardStats` 提供。第二階段改由後端計算，回傳同樣的 `DashboardStats`。

**Tech Stack:** 沿用 Plan 2（Next.js 16.3、React 19.2、TypeScript strict、Tailwind CSS v4、shadcn/ui 4.21、Zustand 5、idb-keyval、Vitest），新增：
- Recharts 3.8：由 shadcn 的 `chart` 元件安裝。
- Playwright 1.63（`@playwright/test`，Chromium）。

**Spec:** `docs/superpowers/specs/2026-10-05-genai-poster-agent-frontend-design.md`

**Plan series:** 本文件是 3 份計畫中的第 3 份，完成後第一階段前端全部結束。第二階段的 FastAPI、Chroma、ComfyUI 與 VLM 串接另寫規格。

## Plan 2 驗收結果（2026-10-07）

撰寫本計畫前重新驗證了 Plan 2：

- PR kayla162/genai-agent-studio#1 已合併到 `main`（merge commit `900e003`）。合併後的檔案與推上去驗證過的分支完全相同。
- 在 `main` 上：`npm run test` 31 個測試檔、230 個測試全部通過；`npm run typecheck`、`npm run lint`、`npm run build` 都沒有錯誤。
- 規格對照：
  - 工作台五個頁面（`/studio`、`/products`、`/queue`、`/history`、`/brands`）都已完成。
  - Plan 2「本計畫範圍外」的四項由本計畫處理，對照見下方「介面與設計決策」。
- 結論：Plan 2 正確完成，可以開始 Plan 3。

## 本計畫的驗證方式

本計畫的程式碼已在獨立副本上逐 Task 實作並驗證：
- 從 `main`（Plan 2 合併後）開始，只依本文件的步驟重建。
- 每個 Task 結束時都通過型別檢查，測試數量與各 Task 的 Expected 相符。
- 最後的 `npm run test`、`npm run typecheck`、`npm run lint`、`npm run build`、`npm run e2e` 全部通過。
- 每個頁面都用瀏覽器實際操作過，包括執行中的任務與重新整理後的任務。

執行時若結果與 Expected 不同，先檢查是否漏了步驟，不要修改測試來配合。

## Global Constraints

沿用 Plan 2 的 Global Constraints：
- 指令在 `web/` 執行。
- `lib/**` 分純函式、瀏覽器、伺服器三類。
- `getApiClient()` 只能在 client 端呼叫。
- 事件與示範資料是凍結的物件。
- React Compiler 規則不得用 `eslint-disable` 繞過。
- `useSearchParams` 要包在 `<Suspense>` 裡。
- shadcn 元件由 CLI 產生，不手動修改 `src/components/ui/*`。
- UI 用繁體中文。
- 每個 Task 結束都要 commit，訊息最後一行加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。

本計畫另外約定：
- 新的純函式模組：`lib/agent/flow.ts`、`lib/agent/events.ts`、`lib/agent/inspect.ts`、`lib/stats/dashboard.ts`、`lib/api/mock/samples.ts`。都要有 Vitest 測試。
- 測試用的任務訊息一律由 `src/test/fixtures.ts` 的 `makeJobSnapshot()` 依 mock 劇本產生，不要手寫事件。
- Playwright 測試放在 `web/e2e/`，檔名 `*.spec.ts`。Vitest 只收 `src/**/*.test.ts`，兩者不會互相執行到。
- E2E 先建置正式版，再用 3100 埠啟動，不影響開發用的 3000 埠。
- shadcn 的分頁（Tabs）在本專案的淺色主題下，預設樣式的 `background` 與 `muted` 顏色太接近，看不出目前分頁，所以改用 `variant="line"`。

## 介面與設計決策

Plan 2「本計畫範圍外」的處理方式：

| 規格項目 | 本計畫的處理 |
|---|---|
| 事件時間戳與序號 | Task 1。`JobMessage = JobEvent & { seq, ts }`：<br>- 欄位直接加在事件物件上，不另外包一層，所以既有的 `(e: JobEvent) => …` 訂閱者與 `reduceJob` 都不用改。<br>- `seq` 在同一任務內從 1 連續遞增，`ts` 是送出時間。<br>- 第二階段重新連線時用 `seq` 補齊漏掉的事件。本計畫的 `useJobStream` 已經用 `seq` 略過重播的重複事件（開發模式 StrictMode 會訂閱兩次）。 |
| `/dashboard` 與 `ApiClient` 統計方法 | Task 3 新增 `getDashboardStats(brandId?)` 與純函式 `dashboardStats()`；Task 9 用 Recharts 畫圖。 |
| `/agent` 完整版 | Task 4、5 寫純函式，Task 6–8 做畫面，取代 Plan 2 的 `AgentPreview`。 |
| Playwright E2E | Task 10：主流程（含匯出 zip 的內容與 PNG 尺寸）、Agent 透視的重試 diff、儀表板、手機寬度。 |

本計畫的其他決策：

- **任務紀錄保存**：
  - mock 在任務結束（完成、需人工審核、取消）時，把 `JobSnapshot`（摘要與完整訊息）存進 IndexedDB 的 `jobs`，新到舊，最多 40 筆。
  - `listJobs`、`getJob`、`subscribe`、`selectRender`、`cancelJob` 在記憶體找不到任務時，會從本機紀錄還原。
  - 執行中的任務仍只在記憶體，重新整理就會中斷，與 Plan 2 相同。
- **示範任務**：`DemoControls.seedJobs(count)`（只有 mock 模式）。
  - 直接算出完整時間軸並寫入任務紀錄，不播放；時間戳以 1× 速度計。
  - 兩個品牌輪流；每 5 筆有 1 筆全部失敗（需人工審核），每 3 筆有 1 筆首輪就通過，其餘首輪失敗後重試通過。
  - 因為週期都是奇數，兩個品牌都會分到三種結果。
- **儀表板的統計定義**（只算完成與需人工審核的任務，不含取消）：
  - 通過率：完成 ÷（完成 + 需人工審核）。
  - 首輪通過率：第一輪就有候選通過審查的模板比例。
  - 平均重試次數：每個任務（輪數 − 1）的平均。
  - 平均耗時：第一則到最後一則訊息的 `ts` 差。
  - 每張成本：所有任務的估算成本 ÷ 交付張數（各模板的最佳候選）。單價見 `UNIT_COST_USD`，第二階段改用後端回報的實際用量。
  - Rerank 對命中率的影響：前 k 筆檢索結果涵蓋了多少「審查未通過項目所引用的規範」（`ReviewCheck.ragRef`）。分別以向量召回順序與 Rerank 後順序計算，取各任務平均。
- **Agent 透視的資料來源**：
  - 只用事件串流，與 live 模式相同；任務的輸入來自 `listJobs()` 的摘要。
  - 合規報告的海報預覽需要商品照，用 `listProducts(brandId)` 取得；商品已刪除時只畫背景與文字。
- **注入參數對照**：與同模板上一輪比較，標出改寫後變動的參數。
  - 長的文字（prompt、版面座標）只標出改變的片段（`inlineDiff`）。
  - 短的值（seed 等）顯示「舊 → 新」。

## File Structure

| 檔案 | 責任 |
|---|---|
| `web/src/types/contract.ts`（修改） | `EventMeta`、`JobMessage`；儀表板型別 `CheckFailureStat`、`RerankHitStat`、`JobStat`、`DashboardStats` |
| `web/src/lib/api/client.ts`（修改） | `subscribe` 送出 `JobMessage`、`JobSnapshot.events: JobMessage[]`、`DemoControls.seedJobs`、`getDashboardStats` |
| `web/src/lib/api/mock/client.ts`（修改） | 加上 seq／ts；已結束任務的保存與還原；示範任務；儀表板統計 |
| `web/src/lib/api/mock/samples.ts` | 示範任務的設定（品牌、需求、模板、Demo 選項、建立時間） |
| `web/src/lib/stats/dashboard.ts` | 儀表板統計與成本估算 |
| `web/src/test/fixtures.ts`（修改） | `makeJobSnapshot()`：依 mock 劇本產生任務訊息 |
| `web/src/lib/agent/flow.ts` | 流程節點的狀態、進入次數與耗時 |
| `web/src/lib/agent/events.ts` | 事件分類、摘要、時間格式 |
| `web/src/lib/agent/inspect.ts` | Prompt 選項、注入參數對照、Rerank 排名、BBox 疊圖、重試 diff |
| `web/src/lib/agent/diff.ts`（修改） | `inlineDiff` |
| `web/src/components/agent/use-job-stream.ts` | 訂閱事件，累積成 `JobView`（依 seq 去除重複） |
| `web/src/components/agent/{agent-inspector,flow-graph,event-stream}.tsx` | `/agent` 頁面、流程節點、事件串流 |
| `web/src/components/agent/{prompt-panel,rag-panel,review-panel,retry-panel}.tsx` | JSON Prompt 與注入參數、RAG Rerank、合規報告與 BBox 疊圖、重試 diff |
| `web/src/components/agent/agent-preview.tsx`（刪除） | 由 `agent-inspector.tsx` 取代 |
| `web/src/components/dashboard/{kpi-cards,check-failure-chart,rerank-chart,recent-jobs}.tsx` | 儀表板元件 |
| `web/src/app/agent/page.tsx`、`web/src/app/dashboard/page.tsx`（修改） | 路由頁面 |
| `web/src/components/ui/{table,chart}.tsx` | shadcn 產生 |
| `web/playwright.config.ts`、`web/e2e/{studio,dashboard}.spec.ts` | Playwright E2E |
| `web/.gitignore`、`web/package.json`、`web/README.md`（修改） | Playwright 輸出、`e2e` 指令、文件 |

---

### Task 1: 事件序號與時間戳（`JobMessage`）

**Files:**
- Modify: `web/src/types/contract.ts`、`web/src/lib/api/client.ts`、`web/src/lib/api/mock/client.ts`
- Test: `web/src/lib/api/mock/client.test.ts`（修改）

**Interfaces:**
- Consumes：Plan 2 的 `ApiClient`、`MockApiClient`
- Produces：
  - `interface EventMeta { seq: number; ts: string }`、`type JobMessage = JobEvent & EventMeta`
  - `ApiClient.subscribe(jobId, onEvent: (event: JobMessage) => void, onError?)`
  - `JobSnapshot.events: JobMessage[]`
  - mock 在送出事件時加上 `seq`（每個任務從 1 開始）與 `ts`（`now()` 的 ISO 字串），訊息是凍結的物件

- [ ] **Step 1: 修改 `web/src/types/contract.ts`**

找到（1／2）：

```ts
 * 前後端資料約定。第二階段 FastAPI 以 Pydantic 照此定義，
 * WebSocket `/ws/jobs/{jobId}` 送出的事件即 `JobEvent`。
 */
```

改成：

```ts
 * 前後端資料約定。第二階段 FastAPI 以 Pydantic 照此定義，
 * WebSocket `/ws/jobs/{jobId}` 送出的訊息是 `JobMessage`（`JobEvent` 加上序號與時間戳）。
 */
```

找到（2／2）：

```ts

/* ---------- 歷史紀錄與 Demo ---------- */
```

改成：

```ts

/**
 * 每則事件訊息附帶的序號與時間戳。
 * seq：同一任務內從 1 開始連續遞增，重新連線時用來補齊漏掉的事件；ts：後端送出時間（ISO 8601）。
 */
export interface EventMeta { seq: number; ts: string }
export type JobMessage = JobEvent & EventMeta;

/* ---------- 歷史紀錄與 Demo ---------- */
```

- [ ] **Step 2: 修改 `web/src/lib/api/mock/client.test.ts`**（先寫失敗測試）

「can be cancelled」改用 `toMatchObject`，因為訊息多了 `seq` 與 `ts`。

找到（1／3）：

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobEvent, JobInput } from '@/types/contract';
import { getApiClient } from '../index';
```

改成：

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobEvent, JobInput, JobMessage } from '@/types/contract';
import { getApiClient } from '../index';
```

找到（2／3）：

```ts

  it('respects the demo speed', async () => {
```

改成：

```ts

  it('stamps every event with a consecutive sequence number and the time it was sent', async () => {
    const api = new MockApiClient();
    const { jobId } = await startJob(api);
    const messages: JobMessage[] = [];
    api.subscribe(jobId, (m) => messages.push(m));
    await vi.advanceTimersByTimeAsync(14_500);
    expect(messages.map((m) => m.seq)).toEqual(messages.map((_, i) => i + 1));
    expect(messages[0].ts).toBe(NOW.toISOString());
    expect(Date.parse(messages.at(-1)!.ts) - NOW.getTime()).toBe(14_500);
    const times = messages.map((m) => Date.parse(m.ts));
    expect(times).toEqual([...times].sort((a, b) => a - b));
    expect(Object.isFrozen(messages[0])).toBe(true);
  });

  it('respects the demo speed', async () => {
```

找到（3／3）：

```ts
    await vi.advanceTimersByTimeAsync(20_000);
    expect(events.at(-1)).toEqual({ type: 'job.status', stage: 'cancelled', round: 0 });
    expect(events.some((e) => e.type === 'job.completed')).toBe(false);
```

改成：

```ts
    await vi.advanceTimersByTimeAsync(20_000);
    expect(events.at(-1)).toMatchObject({ type: 'job.status', stage: 'cancelled', round: 0 });
    expect(events.some((e) => e.type === 'job.completed')).toBe(false);
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `npx vitest run src/lib/api/mock/client.test.ts`
Expected: FAIL，1 個測試失敗：「stamps every event with a consecutive sequence number…」，`expected [ undefined, undefined, … ] to deeply equal [ 1, 2, 3, … ]`。

- [ ] **Step 4: 修改 `web/src/lib/api/client.ts`**

找到（1／3）：

```ts
import type {
  Brand, BrandDocument, ChannelTemplate, ConnectionState, Copy, DemoOptions, HistoryEntry, IngestEvent, JobEvent, JobInput,
  JobSummary, ParsedBrief, Product, ProductPhoto, RagChunk,
```

改成：

```ts
import type {
  Brand, BrandDocument, ChannelTemplate, ConnectionState, Copy, DemoOptions, HistoryEntry, IngestEvent, JobInput, JobMessage,
  JobSummary, ParsedBrief, Product, ProductPhoto, RagChunk,
```

找到（2／3）：

```ts

export interface JobSnapshot { summary: JobSummary; events: JobEvent[] }
```

改成：

```ts

export interface JobSnapshot { summary: JobSummary; events: JobMessage[] }
```

找到（3／3）：

```ts
  /**
   * 先重播已發生的事件，再接收即時事件；回傳取消訂閱的函式。
   * 任務不存在或連線中斷時以 onError 非同步回報，不丟出例外（與 WebSocket 的行為一致）。
   */
  subscribe(jobId: string, onEvent: (event: JobEvent) => void, onError?: (error: Error) => void): () => void;
  cancelJob(jobId: string): Promise<void>;
```

改成：

```ts
  /**
   * 先重播已發生的事件，再接收即時事件；回傳取消訂閱的函式。事件附帶序號（seq）與時間戳（ts）。
   * 任務不存在或連線中斷時以 onError 非同步回報，不丟出例外（與 WebSocket 的行為一致）。
   */
  subscribe(jobId: string, onEvent: (event: JobMessage) => void, onError?: (error: Error) => void): () => void;
  cancelJob(jobId: string): Promise<void>;
```

- [ ] **Step 5: 修改 `web/src/lib/api/mock/client.ts`**

找到（1／5）：

```ts
import type {
  BrandDocument, ConnectionState, Copy, DemoOptions, HistoryEntry, IngestEvent, JobEvent, JobInput, JobStage, JobSummary,
  Product, ProductPhoto, RagChunk, Render, TemplateId,
} from '@/types/contract';
```

改成：

```ts
import type {
  BrandDocument, ConnectionState, Copy, DemoOptions, HistoryEntry, IngestEvent, JobEvent, JobInput, JobMessage, JobStage,
  JobSummary, Product, ProductPhoto, RagChunk, Render, TemplateId,
} from '@/types/contract';
```

找到（2／5）：

```ts
  createdAt: string;
  events: JobEvent[];
  listeners: Set<(e: JobEvent) => void>;
  renders: Map<string, Render>;
```

改成：

```ts
  createdAt: string;
  events: JobMessage[];
  listeners: Set<(e: JobMessage) => void>;
  renders: Map<string, Render>;
```

找到（3／5）：

```ts

  /** 更新任務狀態（給 selectRender 用），再轉發給訂閱者 */
  private dispatch(rec: JobRecord, e: JobEvent) {
```

改成：

```ts

  /** 更新任務狀態（給 selectRender 用），加上序號與時間戳後轉發給訂閱者 */
  private dispatch(rec: JobRecord, e: JobEvent) {
```

找到（4／5）：

```ts
    }
    rec.events.push(e);
    for (const listener of rec.listeners) this.deliver(listener, e);
  }
```

改成：

```ts
    }
    const message: JobMessage = Object.freeze({ ...e, seq: rec.events.length + 1, ts: this.now().toISOString() });
    rec.events.push(message);
    for (const listener of rec.listeners) this.deliver(listener, message);
  }
```

找到（5／5）：

```ts

  subscribe(jobId: string, onEvent: (event: JobEvent) => void, onError?: (error: Error) => void): () => void {
    const rec = this.jobs.get(jobId);
```

改成：

```ts

  subscribe(jobId: string, onEvent: (event: JobMessage) => void, onError?: (error: Error) => void): () => void {
    const rec = this.jobs.get(jobId);
```

- [ ] **Step 6: 執行測試與型別檢查確認通過**

Run: `npm run test && npm run typecheck`
Expected：
- `client.test.ts` 26 個測試 PASS。
- 全部 31 個測試檔、231 個測試 PASS。
- typecheck 無錯誤。既有的 `subscribe` 呼叫端（studio、queue store、`AgentPreview`）不用修改。

- [ ] **Step 7: Commit**

```bash
git add web/src/types/contract.ts web/src/lib/api
git commit -m "feat: stamp job events with sequence numbers and timestamps" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: 保存已結束的任務與示範任務

**Files:**
- Create: `web/src/lib/api/mock/samples.ts`
- Modify: `web/src/lib/api/client.ts`、`web/src/lib/api/mock/client.ts`
- Test: `web/src/lib/api/mock/samples.test.ts`、`web/src/lib/api/mock/client.test.ts`（修改）

**Interfaces:**
- Consumes：`JobMessage`（Task 1）；Plan 1 的 `buildTimeline`、`parseBrief`、示範資料
- Produces：
  - `SAMPLE_BRIEFS`、`interface SampleJob { input; demo; createdAt }`、`sampleJobs(count, now, seed = 7): SampleJob[]`（最舊的在前）
  - `DemoControls.seedJobs(count): Promise<number>`
  - `MAX_STORED_JOBS = 40`
  - mock 的保存與還原：
    - 已結束的任務以 `JobSnapshot[]` 存在 key `jobs`。
    - `listJobs` 合併記憶體與本機紀錄，依建立時間由新到舊。
    - `getJob`、`subscribe`、`selectRender`、`cancelJob` 都能使用本機紀錄的任務。
    - 本機紀錄的任務，`subscribe` 以非同步方式重播。
    - `cancelJob` 會等保存完成才 resolve。

- [ ] **Step 1: 建立 `web/src/lib/api/mock/samples.test.ts`**（先寫失敗測試）

```ts
import { describe, expect, it } from 'vitest';
import { getBrandById, SAMPLE_PRODUCTS } from './data';
import { SAMPLE_BRIEFS, sampleJobs } from './samples';

const NOW = new Date(2026, 9, 5, 9, 30);

describe('sampleJobs', () => {
  it('is deterministic for the same seed', () => {
    expect(sampleJobs(8, NOW)).toEqual(sampleJobs(8, NOW));
  });

  it('alternates brands with their sample product and parsed brief', () => {
    const jobs = sampleJobs(6, NOW);
    expect(jobs.map((j) => j.input.brandId)).toEqual(['selune', 'misty-isle', 'selune', 'misty-isle', 'selune', 'misty-isle']);
    for (const { input } of jobs) {
      const product = SAMPLE_PRODUCTS.find((p) => p.id === input.productId)!;
      expect(product.brandId).toBe(input.brandId);
      expect(SAMPLE_BRIEFS[input.brandId]).toContain(input.brief);
      expect(input.parsedBrief.productName).toBe(product.name);
      expect(getBrandById(input.brandId).id).toBe(input.brandId);
    }
  });

  it('picks at least one template, in the standard order, without duplicates', () => {
    for (const { input } of sampleJobs(20, NOW)) {
      expect(input.templateIds.length).toBeGreaterThan(0);
      expect(new Set(input.templateIds).size).toBe(input.templateIds.length);
    }
  });

  it('gives both brands retries, first-round passes and forced failures', () => {
    const jobs = sampleJobs(12, NOW);
    for (const brandId of ['selune', 'misty-isle']) {
      const demos = jobs.filter((j) => j.input.brandId === brandId).map((j) => j.demo);
      expect(demos.filter((d) => d.forceAllFail)).toHaveLength(1);
      expect(demos.filter((d) => !d.firstRoundFail)).toHaveLength(2);
      expect(demos.filter((d) => d.firstRoundFail && !d.forceAllFail)).toHaveLength(3);
    }
    expect(jobs.every((j) => j.demo.speed === 1)).toBe(true);
  });

  it('spreads creation times over the past, oldest first', () => {
    const times = sampleJobs(10, NOW).map((j) => j.createdAt.getTime());
    expect(times).toEqual([...times].sort((a, b) => a - b));
    expect(new Set(times).size).toBe(10);
    expect(times.at(-1)!).toBeLessThan(NOW.getTime());
  });
});
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `npx vitest run src/lib/api/mock/samples.test.ts`
Expected: FAIL，`Cannot find module './samples'`

- [ ] **Step 3: 建立 `web/src/lib/api/mock/samples.ts`**

```ts
import type { DemoOptions, JobInput, TemplateId } from '@/types/contract';
import { TEMPLATE_IDS } from '@/types/contract';
import { mulberry32 } from '@/lib/core/num';
import { parseBrief } from './brief';
import { BRANDS, SAMPLE_PRODUCTS } from './data';

/** 示範任務使用的需求（各品牌輪流） */
export const SAMPLE_BRIEFS: Record<string, string[]> = {
  selune: [
    '幫我做週年慶的精華液海報，主打買一送一，要溫柔療癒的感覺',
    '雙11精華液限時85折，要專業科研感',
    '秋冬保濕主打修護，簡約高級感',
  ],
  'misty-isle': [
    '幫我設計一款簡約風格的冷萃咖啡宣傳海報',
    '冷萃咖啡新品上市，第二件6折，活潑年輕',
    '夏季早午餐配冷萃，清新療癒的感覺',
  ],
};

export interface SampleJob { input: JobInput; demo: DemoOptions; createdAt: Date }

const HOUR = 3_600_000;

/**
 * 產生 count 筆示範任務的設定（最舊的在前），讓成效儀表板一開始就有資料。
 * 兩個品牌輪流；大部分首輪失敗後重試通過，每 5 筆有 1 筆全部失敗（需人工審核），每 3 筆有 1 筆首輪就通過。
 * 5 與 3 都是奇數，兩個品牌都會分到這三種結果。
 */
export function sampleJobs(count: number, now: Date, seed = 7): SampleJob[] {
  const rng = mulberry32(seed);
  return Array.from({ length: count }, (_, i): SampleJob => {
    const brand = BRANDS[i % BRANDS.length];
    const product = SAMPLE_PRODUCTS.find((p) => p.brandId === brand.id);
    if (!product) throw new Error(`Brand ${brand.id} has no sample product`);
    const briefs = SAMPLE_BRIEFS[brand.id];
    const brief = briefs[Math.floor(i / BRANDS.length) % briefs.length];
    const picked = TEMPLATE_IDS.filter(() => rng() < 0.45);
    const templateIds: TemplateId[] = picked.length ? picked : ['ecom-main'];
    const forceAllFail = i % 5 === 3;
    return {
      input: {
        brandId: brand.id,
        productId: product.id,
        brief,
        parsedBrief: parseBrief(brief, brand, product),
        templateIds,
        variantsPerTemplate: [4, 4, 2, 3][i % 4],
        llm: i % 3 === 2 ? 'Llama 3.2 Vision（Unsloth 微調）' : 'Gemini 3.7 Flash',
        engine: i % 5 === 4 ? 'ideogram' : 'comfyui',
        vlm: 'Gemini 3.7 Vision',
        maxRetries: 2,
      },
      demo: { speed: 1, firstRoundFail: forceAllFail || i % 3 !== 1, forceAllFail },
      createdAt: new Date(now.getTime() - (count - i) * 11 * HOUR - Math.floor(rng() * 3 * HOUR)),
    };
  });
}
```

- [ ] **Step 4: 執行測試確認通過**

Run: `npx vitest run src/lib/api/mock/samples.test.ts`
Expected: 5 個測試 PASS

- [ ] **Step 5: 修改 `web/src/lib/api/mock/client.test.ts`**（先寫失敗測試）

找到（1／2）：

```ts
import { getApiClient } from '../index';
import { MockApiClient, makeJobId } from './client';
```

改成：

```ts
import { getApiClient } from '../index';
import { MAX_STORED_JOBS, MockApiClient, makeJobId } from './client';
import { MemoryStore } from './store';
```

找到（2／2）：

```ts

describe('getApiClient', () => {
```

改成：

```ts

describe('stored jobs', () => {
  it('keeps finished and cancelled jobs so a reloaded client can list, replay and select from them', async () => {
    const store = new MemoryStore();
    const api = new MockApiClient(store);
    const { jobId, events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(14_500);
    const cancelled = await startJob(api, { templateIds: ['story'] });
    await api.cancelJob(cancelled.jobId);

    const reloaded = new MockApiClient(store);
    const jobs = await reloaded.listJobs();
    expect(jobs.map((j) => j.id)).toEqual([cancelled.jobId, jobId]);
    expect(jobs[0]).toMatchObject({ stage: 'cancelled', finished: true });
    expect(jobs[1]).toMatchObject({ stage: 'done', round: 2, finished: true });
    expect((await reloaded.getJob(jobId)).events).toEqual(events);

    const replayed: JobMessage[] = [];
    reloaded.subscribe(jobId, (m) => replayed.push(m));
    await vi.waitFor(() => expect(replayed).toEqual(events));

    const done = events.find((e) => e.type === 'job.completed');
    if (done?.type !== 'job.completed') throw new Error('job did not complete');
    const prompt = events.find((e) => e.type === 'prompt.generated' && e.round === 2);
    if (prompt?.type !== 'prompt.generated') throw new Error('missing round 2 prompt');
    const entry = await reloaded.selectRender(jobId, done.bestRenderIds['ig-post']!, prompt.spec.copy);
    expect(entry.render).toMatchObject({ passed: true, round: 2 });
    expect(entry.render.checks).toHaveLength(10);
  });

  it('seeds finished sample jobs with 1× timestamps and keeps only the newest ones', async () => {
    const api = new MockApiClient();
    expect(await api.demo.seedJobs(6)).toBe(6);
    const jobs = await api.listJobs();
    expect(jobs).toHaveLength(6);
    expect(jobs.every((j) => j.finished)).toBe(true);
    expect(jobs.map((j) => j.stage).sort()).toEqual(['done', 'done', 'done', 'done', 'done', 'needs_review']);
    const created = jobs.map((j) => j.createdAt);
    expect(created).toEqual([...created].sort().reverse());

    // 「強制全部失敗」的那一筆：3 輪後需人工審核，1× 共 20.8 秒
    const failed = jobs.find((j) => j.stage === 'needs_review')!;
    const snap = await api.getJob(failed.id);
    expect(snap.summary.round).toBe(3);
    expect(snap.events[0].ts).toBe(failed.createdAt);
    expect(snap.events.map((m) => m.seq)).toEqual(snap.events.map((_, i) => i + 1));
    expect(Date.parse(snap.events.at(-1)!.ts) - Date.parse(snap.events[0].ts)).toBe(20_800);

    await api.demo.seedJobs(MAX_STORED_JOBS);
    expect(await api.listJobs()).toHaveLength(MAX_STORED_JOBS);
  });
});

describe('getApiClient', () => {
```

- [ ] **Step 6: 執行測試確認失敗**

Run: `npx vitest run src/lib/api/mock/client.test.ts`
Expected: FAIL，2 個測試失敗：
- 「keeps finished and cancelled jobs…」：新的 client 讀不到任務，`expected [] to deeply equal [ 'job_…', … ]`。
- 「seeds finished sample jobs…」：`api.demo.seedJobs is not a function`。

- [ ] **Step 7: 修改 `web/src/lib/api/client.ts`**

找到：

```ts
  set(patch: Partial<DemoOptions>): void;
}
```

改成：

```ts
  set(patch: Partial<DemoOptions>): void;
  /** 直接產生 count 筆已結束的示範任務（不播放），讓成效儀表板有資料；回傳新增筆數 */
  seedJobs(count: number): Promise<number>;
}
```

- [ ] **Step 8: 修改 `web/src/lib/api/mock/client.ts`**

- 事件處理拆成兩個模組函式：`apply`（更新任務狀態）、`record`（加上 seq／ts 後保存）。
- 示範任務不經過播放器，直接用 `record` 寫入。

找到（1／12）：

```ts
import { playTimeline, type PlayerHandle } from './player';
import { buildTimeline } from './scenario';
```

改成：

```ts
import { playTimeline, type PlayerHandle } from './player';
import { sampleJobs } from './samples';
import { buildTimeline } from './scenario';
```

找到（2／12）：

```ts

const KEYS = { products: 'products', deleted: 'deletedSampleIds', history: 'history', docChunks: 'docChunks' } as const;
```

改成：

```ts

const KEYS = {
  products: 'products', deleted: 'deletedSampleIds', history: 'history', docChunks: 'docChunks', jobs: 'jobs',
} as const;

/** 本機保留的已結束任務數（Agent 透視與成效儀表板使用），超過時刪掉最舊的 */
export const MAX_STORED_JOBS = 40;

function newRecord(id: string, input: JobInput, createdAt: string): JobRecord {
  return {
    id, input: structuredClone(input), createdAt, events: [], listeners: new Set(), renders: new Map(),
    stage: 'parsing', round: 0, bestRenderIds: {}, finished: false, player: null,
  };
}

/** 依事件更新任務狀態（任務列表與 selectRender 使用） */
function apply(rec: JobRecord, e: JobEvent) {
  switch (e.type) {
    case 'job.status':
      rec.stage = e.stage;
      rec.round = e.round;
      break;
    case 'job.completed':
      rec.bestRenderIds = { ...e.bestRenderIds };
      break;
    case 'render.completed':
      for (const r of e.renders) rec.renders.set(r.id, structuredClone(r));
      break;
    case 'review.check':
      rec.renders.get(e.renderId)?.checks.push(e.check);
      break;
    case 'review.completed': {
      const r = rec.renders.get(e.renderId);
      if (r) { r.score = e.score; r.passed = e.passed; }
      break;
    }
  }
}

/** 套用事件，加上序號與時間戳後保存；回傳凍結的訊息 */
function record(rec: JobRecord, e: JobEvent, ts: string): JobMessage {
  apply(rec, e);
  const message: JobMessage = Object.freeze({ ...e, seq: rec.events.length + 1, ts });
  rec.events.push(message);
  return message;
}
```

找到（3／12）：

```ts
      set: (patch) => { this.options = { ...this.options, ...patch }; },
    };
```

改成：

```ts
      set: (patch) => { this.options = { ...this.options, ...patch }; },
      seedJobs: (count) => this.seedJobs(count),
    };
```

找到（4／12）：

```ts
    const jobId = makeJobId(now);
    const rec: JobRecord = {
      id: jobId, input: structuredClone(input), createdAt: now.toISOString(), events: [], listeners: new Set(),
      renders: new Map(), stage: 'parsing', round: 0, bestRenderIds: {}, finished: false, player: null,
    };
    this.jobs.set(jobId, rec);
```

改成：

```ts
    const jobId = makeJobId(now);
    const rec = newRecord(jobId, input, now.toISOString());
    this.jobs.set(jobId, rec);
```

找到（5／12）：

```ts
      onEvent: (e) => this.dispatch(rec, e),
      onDone: () => { rec.finished = true; },
    });
```

改成：

```ts
      onEvent: (e) => this.dispatch(rec, e),
      onDone: () => {
        rec.finished = true;
        void this.persist(rec);
      },
    });
```

找到（6／12）：

```ts

  /** 更新任務狀態（給 selectRender 用），加上序號與時間戳後轉發給訂閱者 */
  private dispatch(rec: JobRecord, e: JobEvent) {
    switch (e.type) {
      case 'job.status':
        rec.stage = e.stage;
        rec.round = e.round;
        break;
      case 'job.completed':
        rec.bestRenderIds = { ...e.bestRenderIds };
        break;
      case 'render.completed':
        for (const r of e.renders) rec.renders.set(r.id, structuredClone(r));
        break;
      case 'review.check':
        rec.renders.get(e.renderId)?.checks.push(e.check);
        break;
      case 'review.completed': {
        const r = rec.renders.get(e.renderId);
        if (r) { r.score = e.score; r.passed = e.passed; }
        break;
      }
    }
    const message: JobMessage = Object.freeze({ ...e, seq: rec.events.length + 1, ts: this.now().toISOString() });
    rec.events.push(message);
    for (const listener of rec.listeners) this.deliver(listener, message);
  }
```

改成：

```ts

  /** 示範任務：直接算出完整時間軸（時間戳以 1× 速度計），寫入已結束的任務紀錄 */
  private async seedJobs(count: number): Promise<number> {
    const snaps = sampleJobs(count, this.now()).map(({ input, demo, createdAt }) => {
      const brand = getBrandById(input.brandId);
      const product = SAMPLE_PRODUCTS.find((p) => p.id === input.productId);
      if (!product) throw new Error(`Unknown product: ${input.productId}`);
      const jobId = makeJobId(createdAt);
      const rec = newRecord(jobId, input, createdAt.toISOString());
      const templates = input.templateIds.map((id) => getTemplate(id));
      for (const { at, event } of buildTimeline({ jobId, input, brand, product, templates, demo, seed: hashString(jobId) })) {
        record(rec, event, new Date(createdAt.getTime() + at).toISOString());
      }
      rec.finished = true;
      return this.snapshot(rec);
    });
    await this.saveJobs(snaps);
    return snaps.length;
  }

  /** 即時事件：保存後轉發給訂閱者 */
  private dispatch(rec: JobRecord, e: JobEvent) {
    const message = record(rec, e, this.now().toISOString());
    for (const listener of rec.listeners) this.deliver(listener, message);
  }

  /** 任務結束時保存到本機：重新整理後，Agent 透視與成效儀表板仍看得到 */
  private persist(rec: JobRecord): Promise<void> {
    return this.saveJobs([this.snapshot(rec)]).catch((err: unknown) => console.error('[MockApiClient] failed to save job', err));
  }

  private async storedJobs(): Promise<JobSnapshot[]> {
    return (await this.store.get<JobSnapshot[]>(KEYS.jobs)) ?? [];
  }

  /** 取代同 id 的舊紀錄；依建立時間由新到舊，只保留 MAX_STORED_JOBS 筆 */
  private saveJobs(snaps: JobSnapshot[]): Promise<void> {
    return this.serial(async () => {
      const ids = new Set(snaps.map((s) => s.summary.id));
      const kept = (await this.storedJobs()).filter((s) => !ids.has(s.summary.id));
      const all = [...snaps, ...kept].sort((a, b) => b.summary.createdAt.localeCompare(a.summary.createdAt));
      await this.store.set(KEYS.jobs, all.slice(0, MAX_STORED_JOBS));
    });
  }

  /** 記憶體中的任務；不在記憶體時從本機紀錄還原（已結束的任務） */
  private async loadJob(jobId: string): Promise<JobRecord | null> {
    const live = this.jobs.get(jobId);
    if (live) return live;
    const snap = (await this.storedJobs()).find((s) => s.summary.id === jobId);
    if (!snap) return null;
    // 讀取期間可能已被另一個呼叫還原
    const loaded = this.jobs.get(jobId);
    if (loaded) return loaded;
    const rec = newRecord(jobId, snap.summary.input, snap.summary.createdAt);
    for (const m of snap.events) {
      apply(rec, m);
      rec.events.push(Object.freeze(m));
    }
    rec.finished = true;
    this.jobs.set(jobId, rec);
    return rec;
  }

  private async requireJob(jobId: string): Promise<JobRecord> {
    const rec = await this.loadJob(jobId);
    if (!rec) throw new Error(`Unknown job: ${jobId}`);
    return rec;
  }
```

找到（7／12）：

```ts

  private requireJob(jobId: string): JobRecord {
    const rec = this.jobs.get(jobId);
    if (!rec) throw new Error(`Unknown job: ${jobId}`);
    return rec;
  }

  subscribe(jobId: string, onEvent: (event: JobMessage) => void, onError?: (error: Error) => void): () => void {
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
    rec.listeners.add(onEvent);
    return () => { rec.listeners.delete(onEvent); };
  }
```

改成：

```ts

  subscribe(jobId: string, onEvent: (event: JobMessage) => void, onError?: (error: Error) => void): () => void {
    let active = true;
    const attach = (rec: JobRecord) => {
      for (const e of rec.events) this.deliver(onEvent, e);
      rec.listeners.add(onEvent);
    };
    const fail = (error: Error) => {
      if (onError) onError(error);
      else console.error('[MockApiClient]', error.message);
    };
    const live = this.jobs.get(jobId);
    if (live) attach(live);
    else {
      // 不在記憶體時從本機紀錄還原；找不到時與 WebSocket 一樣非同步回報
      void this.loadJob(jobId).then(
        (rec) => {
          if (!active) return;
          if (rec) attach(rec);
          else fail(new Error(`Unknown job: ${jobId}`));
        },
        (err: unknown) => {
          if (active) fail(err instanceof Error ? err : new Error(String(err)));
        },
      );
    }
    return () => {
      active = false;
      this.jobs.get(jobId)?.listeners.delete(onEvent);
    };
  }
```

找到（8／12）：

```ts

  async listJobs(): Promise<JobSummary[]> {
    return [...this.jobs.values()].reverse().map((rec) => this.summary(rec));
  }
```

改成：

```ts

  private snapshot(rec: JobRecord): JobSnapshot {
    return { summary: this.summary(rec), events: [...rec.events] };
  }

  /** 記憶體中的任務 + 本機保存的已結束任務 */
  async listJobs(): Promise<JobSummary[]> {
    const live = [...this.jobs.values()].reverse().map((rec) => this.summary(rec));
    const ids = new Set(live.map((j) => j.id));
    const stored = (await this.storedJobs()).filter((s) => !ids.has(s.summary.id)).map((s) => s.summary);
    // 穩定排序：同一時間建立的任務維持原本的先後
    return [...live, ...stored].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  }
```

找到（9／12）：

```ts
  async getJob(jobId: string): Promise<JobSnapshot> {
    const rec = this.requireJob(jobId);
    return { summary: this.summary(rec), events: [...rec.events] };
  }
```

改成：

```ts
  async getJob(jobId: string): Promise<JobSnapshot> {
    return this.snapshot(await this.requireJob(jobId));
  }
```

找到（10／12）：

```ts
  async cancelJob(jobId: string): Promise<void> {
    const rec = this.requireJob(jobId);
    if (rec.finished) return;
```

改成：

```ts
  async cancelJob(jobId: string): Promise<void> {
    // 執行中的任務一定在記憶體：同步取消，在事件處理函式內呼叫時會立刻停止後續事件
    const rec = this.jobs.get(jobId) ?? (await this.requireJob(jobId));
    if (rec.finished) return;
```

找到（11／12）：

```ts
    this.dispatch(rec, { type: 'job.status', stage: 'cancelled', round: rec.round });
  }
```

改成：

```ts
    this.dispatch(rec, { type: 'job.status', stage: 'cancelled', round: rec.round });
    await this.persist(rec);
  }
```

找到（12／12）：

```ts
    return this.serial(async () => {
      const rec = this.requireJob(jobId);
      const render = rec.renders.get(renderId);
```

改成：

```ts
    return this.serial(async () => {
      const rec = await this.requireJob(jobId);
      const render = rec.renders.get(renderId);
```

- [ ] **Step 9: 執行測試與型別檢查確認通過**

Run: `npm run test && npm run typecheck`
Expected：
- `client.test.ts` 28 個、`samples.test.ts` 5 個測試 PASS。
- 全部 32 個測試檔、238 個測試 PASS。
- typecheck 無錯誤。

- [ ] **Step 10: Commit**

```bash
git add web/src/lib/api
git commit -m "feat: keep finished jobs and seed sample jobs in the mock" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: 儀表板統計與 `getDashboardStats`

**Files:**
- Create: `web/src/lib/stats/dashboard.ts`
- Modify: `web/src/types/contract.ts`、`web/src/test/fixtures.ts`、`web/src/lib/api/client.ts`、`web/src/lib/api/mock/client.ts`
- Test: `web/src/lib/stats/dashboard.test.ts`、`web/src/lib/api/mock/client.test.ts`（修改）

**Interfaces:**
- Consumes：`JobMessage`、`JobSnapshot`（Task 1）；已保存的任務（Task 2）
- Produces：
  - 型別 `CheckFailureStat`、`RerankHitStat`、`JobStat`、`DashboardStats`（定義見下方 Step 1）
  - `UNIT_COST_USD`、`jobCost(snap)`、`jobStat(snap): JobStat | null`、`rerankHitCurve(events)`、`dashboardStats(snaps): DashboardStats`
  - `ApiClient.getDashboardStats(brandId?): Promise<DashboardStats>`：統計已結束的任務，省略 brandId 時統計所有品牌
  - 測試輔助 `makeJobSnapshot(f?: JobFixture): JobSnapshot`：依 mock 劇本產生一個任務的完整訊息（時間戳以 1× 計，預設 SÉLUNE、IG 貼文、首輪失敗後第二輪通過）

- [ ] **Step 1: 修改 `web/src/types/contract.ts`**

找到：

```ts

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';
```

改成：

```ts

/* ---------- 成效儀表板 ---------- */
export interface CheckFailureStat { checkId: CheckId; name: string; kind: 'rule' | 'vlm'; fail: number; warn: number }

/**
 * Rerank 對命中率的影響：前 k 筆檢索結果涵蓋了多少「審查未通過項目所引用的規範」。
 * vector 為向量召回的順序，rerank 為 BGE Rerank 後的順序；值為 0–1，取各任務平均。
 */
export interface RerankHitStat { k: number; vector: number; rerank: number }

export interface JobStat {
  jobId: string;
  brandId: string;
  createdAt: string;
  outcome: 'done' | 'needs_review';
  templates: number;
  /** 共跑了幾輪（1 代表沒有重試） */
  rounds: number;
  /** 生成的候選張數（含重試） */
  renders: number;
  /** 交付張數（各模板的最佳候選） */
  delivered: number;
  durationMs: number;
  costUsd: number;
}

export interface DashboardStats {
  /** 已結束的任務數（不含取消） */
  jobs: number;
  /** 審查過的候選張數 */
  renders: number;
  /** 任務通過率：完成 ÷（完成 + 需人工審核） */
  passRate: number;
  /** 第一輪就通過審查的模板比例 */
  firstPassRate: number;
  /** 每個任務平均重試幾輪 */
  avgRetries: number;
  avgDurationMs: number;
  /** 每張交付圖的平均成本（美元，估算）；沒有交付任何圖時為 null */
  costPerImage: number | null;
  /** 依 CHECK_IDS 的順序 */
  checkFailures: CheckFailureStat[];
  /** k = 1 到檢索筆數 */
  rerankHits: RerankHitStat[];
  /** 最近的任務，新到舊，最多 8 筆 */
  recent: JobStat[];
}

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';
```

- [ ] **Step 2: 修改 `web/src/test/fixtures.ts`**

找到（1／2）：

```ts
import type { Brand, Product, PromptSpec, TemplateId } from '@/types/contract';
import { buildPromptSpec } from '@/lib/agent/prompt';
import { parseBrief } from '@/lib/api/mock/brief';
import { computeLayout } from '@/lib/compose/layout';
import { getTemplate } from '@/lib/compose/templates';
import { SAMPLE_PRODUCTS, SELUNE } from '@/lib/api/mock/data';
```

改成：

```ts
import type {
  Brand, DemoOptions, Engine, JobInput, JobMessage, JobStage, Product, PromptSpec, TemplateId,
} from '@/types/contract';
import type { JobSnapshot } from '@/lib/api/client';
import { buildPromptSpec } from '@/lib/agent/prompt';
import { parseBrief } from '@/lib/api/mock/brief';
import { buildTimeline } from '@/lib/api/mock/scenario';
import { computeLayout } from '@/lib/compose/layout';
import { getTemplate } from '@/lib/compose/templates';
import { getBrandById, SAMPLE_PRODUCTS, SELUNE } from '@/lib/api/mock/data';
```

找到（2／2）：

```ts
  });
}
```

改成：

```ts
  });
}

export interface JobFixture {
  brandId?: string;
  templateIds?: TemplateId[];
  variants?: number;
  engine?: Engine;
  maxRetries?: number;
  demo?: Partial<DemoOptions>;
  jobId?: string;
  createdAt?: string;
  /** 只取前 n 則訊息，模擬執行中的任務 */
  upTo?: number;
}

/** 依 mock 劇本產生一個任務的完整訊息（時間戳以 1× 計）；預設首輪失敗、第二輪通過 */
export function makeJobSnapshot(f: JobFixture = {}): JobSnapshot {
  const brand = getBrandById(f.brandId ?? 'selune');
  const product = SAMPLE_PRODUCTS.find((p) => p.brandId === brand.id)!;
  const jobId = f.jobId ?? 'job_fixture';
  const createdAt = f.createdAt ?? '2026-10-05T01:30:00.000Z';
  const brief = brand.id === 'selune' ? '週年慶主打買一送一，溫柔療癒' : '幫我設計一款簡約風格的冷萃咖啡宣傳海報';
  const input: JobInput = {
    brandId: brand.id, productId: product.id, brief, parsedBrief: parseBrief(brief, brand, product),
    templateIds: f.templateIds ?? ['ig-post'], variantsPerTemplate: f.variants ?? 4, llm: 'Gemini 3.7 Flash',
    engine: f.engine ?? 'comfyui', vlm: 'Gemini 3.7 Vision', maxRetries: f.maxRetries ?? 2,
  };
  const timeline = buildTimeline({
    jobId, input, brand, product, templates: input.templateIds.map((id) => getTemplate(id)),
    demo: { speed: 1, firstRoundFail: true, forceAllFail: false, ...f.demo }, seed: 1,
  });
  const t0 = Date.parse(createdAt);
  const events: JobMessage[] = timeline
    .slice(0, f.upTo ?? timeline.length)
    .map(({ at, event }, i) => ({ ...event, seq: i + 1, ts: new Date(t0 + at).toISOString() }));
  let stage: JobStage = 'parsing';
  let round = 0;
  let bestRenderIds: JobSnapshot['summary']['bestRenderIds'] = {};
  for (const e of events) {
    if (e.type === 'job.status') ({ stage, round } = e);
    if (e.type === 'job.completed') bestRenderIds = e.bestRenderIds;
  }
  const finished = stage === 'done' || stage === 'needs_review' || stage === 'cancelled';
  return { summary: { id: jobId, input, createdAt, stage, round, finished, bestRenderIds }, events };
}
```

- [ ] **Step 3: 建立 `web/src/lib/stats/dashboard.test.ts`**（先寫失敗測試）

```ts
import { describe, expect, it } from 'vitest';
import { makeJobSnapshot } from '@/test/fixtures';
import { dashboardStats, jobCost, jobStat, rerankHitCurve, UNIT_COST_USD } from './dashboard';

const retried = makeJobSnapshot({ jobId: 'job_a', createdAt: '2026-10-01T01:00:00.000Z' });
const firstPass = makeJobSnapshot({ jobId: 'job_b', createdAt: '2026-10-02T01:00:00.000Z', demo: { firstRoundFail: false } });
const failed = makeJobSnapshot({ jobId: 'job_c', createdAt: '2026-10-03T01:00:00.000Z', demo: { forceAllFail: true } });

describe('jobCost', () => {
  it('adds LLM calls, rerank, image generation and VLM review', () => {
    // 需求拆解 1 + Prompt 2 輪 + Query Rewriting 1 = 4 次 LLM；2 輪 × 4 張候選
    const expected = 4 * UNIT_COST_USD.llmCall + UNIT_COST_USD.rerank + 8 * UNIT_COST_USD.comfyImage + 8 * UNIT_COST_USD.vlmReview;
    expect(jobCost(retried)).toBeCloseTo(expected, 10);
  });

  it('prices Ideogram images by the API rate', () => {
    const ideogram = makeJobSnapshot({ engine: 'ideogram' });
    expect(jobCost(ideogram) - jobCost(retried)).toBeCloseTo(8 * (UNIT_COST_USD.ideogramImage - UNIT_COST_USD.comfyImage), 10);
  });
});

describe('jobStat', () => {
  it('summarises a finished job from its events', () => {
    expect(jobStat(retried)).toEqual({
      jobId: 'job_a', brandId: 'selune', createdAt: '2026-10-01T01:00:00.000Z', outcome: 'done', templates: 1, rounds: 2,
      renders: 8, delivered: 1, durationMs: 14_500, costUsd: jobCost(retried),
    });
    expect(jobStat(failed)).toMatchObject({ outcome: 'needs_review', rounds: 3, renders: 12, delivered: 0, durationMs: 20_800 });
  });

  it('skips running and cancelled jobs', () => {
    expect(jobStat(makeJobSnapshot({ upTo: 20 }))).toBeNull();
    const cancelled = makeJobSnapshot();
    cancelled.summary.stage = 'cancelled';
    expect(jobStat(cancelled)).toBeNull();
  });
});

describe('rerankHitCurve', () => {
  it('shows rerank bringing the cited guidelines to the top', () => {
    // 第一輪的問題引用了色彩、法規、Logo 三段規範：向量順序是 layout > color > history > logo > law
    expect(rerankHitCurve(retried.events)).toEqual({
      vector: [0, 1 / 3, 1 / 3, 2 / 3, 1],
      rerank: [1 / 3, 2 / 3, 1, 1, 1],
    });
  });

  it('returns null when no failed or warned check cites a retrieved guideline', () => {
    const passOnly = retried.events.filter((e) => e.type !== 'review.check' || e.check.status === 'pass');
    expect(rerankHitCurve(passOnly)).toBeNull();
  });
});

describe('dashboardStats', () => {
  const stats = dashboardStats([retried, firstPass, failed, makeJobSnapshot({ jobId: 'job_running', upTo: 30 })]);

  it('counts only finished jobs', () => {
    expect(stats.jobs).toBe(3);
    expect(stats.renders).toBe(8 + 4 + 12);
  });

  it('computes pass rate, first-round pass rate, retries and duration', () => {
    expect(stats.passRate).toBeCloseTo(2 / 3, 10);
    expect(stats.firstPassRate).toBeCloseTo(1 / 3, 10);
    expect(stats.avgRetries).toBe(1);
    expect(stats.avgDurationMs).toBe((14_500 + 8_200 + 20_800) / 3);
  });

  it('spreads the cost of every job over the delivered images', () => {
    const total = jobCost(retried) + jobCost(firstPass) + jobCost(failed);
    expect(stats.costPerImage).toBeCloseTo(total / 2, 10);
  });

  it('counts failures and warnings per check in the standard order', () => {
    expect(stats.checkFailures.map((c) => c.checkId)).toEqual([
      'banned_words', 'color_delta', 'logo_clearance', 'disclaimer', 'product_ratio', 'whitespace', 'ocr_typo',
      'vlm_exaggeration', 'vlm_occlusion', 'vlm_quality',
    ]);
    // 有瑕疵的輪次：retried 第 1 輪 4 張 + failed 3 輪 12 張
    expect(stats.checkFailures[0]).toEqual({ checkId: 'banned_words', name: '禁用詞檢查', kind: 'rule', fail: 16, warn: 0 });
    expect(stats.checkFailures.find((c) => c.checkId === 'disclaimer')).toMatchObject({ fail: 0, warn: 16 });
  });

  it('averages the rerank hit curves', () => {
    expect(stats.rerankHits).toHaveLength(5);
    const k3 = stats.rerankHits[2];
    expect(k3.k).toBe(3);
    expect(k3.rerank).toBe(1);
    expect(k3.vector).toBeLessThan(0.5);
  });

  it('lists recent jobs newest first', () => {
    expect(stats.recent.map((j) => j.jobId)).toEqual(['job_c', 'job_b', 'job_a']);
  });

  it('returns zeros for no data', () => {
    expect(dashboardStats([])).toEqual({
      jobs: 0, renders: 0, passRate: 0, firstPassRate: 0, avgRetries: 0, avgDurationMs: 0, costPerImage: null,
      checkFailures: [], rerankHits: [], recent: [],
    });
  });
});
```

- [ ] **Step 4: 執行測試確認失敗**

Run: `npx vitest run src/lib/stats/dashboard.test.ts`
Expected: FAIL，`Cannot find module './dashboard'`

- [ ] **Step 5: 建立 `web/src/lib/stats/dashboard.ts`**

```ts
import type { CheckFailureStat, CheckId, DashboardStats, JobMessage, JobStat, RerankHitStat } from '@/types/contract';
import { CHECK_IDS } from '@/types/contract';
import type { JobSnapshot } from '@/lib/api/client';

/** 估算單價（美元）。第二階段改由後端回報實際用量。 */
export const UNIT_COST_USD = {
  /** LLM 呼叫一次：需求拆解、每個模板每輪的 Prompt 構建、Query Rewriting（約 2k tokens） */
  llmCall: 0.0006,
  /** BGE Reranker 一次（自架 GPU） */
  rerank: 0.0002,
  /** ComfyUI 生成 1 張 2K 候選（雲端 GPU 約 4 秒） */
  comfyImage: 0.0042,
  /** Ideogram 4.0 API 生成 1 張 */
  ideogramImage: 0.06,
  /** VLM 審查 1 張 */
  vlmReview: 0.0011,
} as const;

const RECENT = 8;

const count = (events: JobMessage[], type: JobMessage['type']) => events.filter((e) => e.type === type).length;

function renderCount(events: JobMessage[]): number {
  return events.reduce((n, e) => n + (e.type === 'render.completed' ? e.renders.length : 0), 0);
}

/** 依事件估算一個任務的成本（美元） */
export function jobCost({ summary, events }: JobSnapshot): number {
  const image = summary.input.engine === 'ideogram' ? UNIT_COST_USD.ideogramImage : UNIT_COST_USD.comfyImage;
  const llmCalls = count(events, 'brief.parsed') + count(events, 'prompt.generated') + count(events, 'rewrite.started');
  return (
    UNIT_COST_USD.llmCall * llmCalls
    + UNIT_COST_USD.rerank * count(events, 'rag.reranked')
    + image * renderCount(events)
    + UNIT_COST_USD.vlmReview * count(events, 'review.completed')
  );
}

/** 已結束（完成或需人工審核）的任務才有統計；執行中與已取消的回傳 null */
export function jobStat(snap: JobSnapshot): JobStat | null {
  const { summary, events } = snap;
  if (!summary.finished || (summary.stage !== 'done' && summary.stage !== 'needs_review')) return null;
  const first = events[0];
  const last = events.at(-1);
  return {
    jobId: summary.id,
    brandId: summary.input.brandId,
    createdAt: summary.createdAt,
    outcome: summary.stage,
    templates: summary.input.templateIds.length,
    rounds: summary.round,
    renders: renderCount(events),
    delivered: Object.keys(summary.bestRenderIds).length,
    durationMs: first && last ? Date.parse(last.ts) - Date.parse(first.ts) : 0,
    costUsd: jobCost(snap),
  };
}

/** 第一輪就有候選通過審查的模板數 */
function firstRoundPassed(events: JobMessage[]): number {
  const templateOf = new Map<string, string>();
  const passed = new Set<string>();
  for (const e of events) {
    if (e.type === 'render.completed' && e.round === 1) for (const r of e.renders) templateOf.set(r.id, r.templateId);
    if (e.type === 'review.completed' && e.round === 1 && e.passed) {
      const t = templateOf.get(e.renderId);
      if (t) passed.add(t);
    }
  }
  return passed.size;
}

/** 前 k 筆（k = 1…n）涵蓋審查未通過項目所引用規範的比例；沒有可比較的引用時回傳 null */
export function rerankHitCurve(events: JobMessage[]): { vector: number[]; rerank: number[] } | null {
  const retrieved = events.find((e) => e.type === 'rag.retrieved');
  const reranked = events.find((e) => e.type === 'rag.reranked');
  if (retrieved?.type !== 'rag.retrieved' || reranked?.type !== 'rag.reranked') return null;
  const vectorOrder = [...retrieved.hits].sort((a, b) => b.vectorScore - a.vectorScore).map((h) => h.chunkId);
  const rerankOrder = reranked.hits.map((h) => h.chunkId);
  const cited = new Set(events.flatMap((e) =>
    e.type === 'review.check' && e.check.status !== 'pass' && e.check.ragRef ? [e.check.ragRef] : []));
  const relevant = vectorOrder.filter((id) => cited.has(id));
  if (!relevant.length) return null;
  const curve = (order: string[]) =>
    order.map((_, i) => relevant.filter((id) => order.slice(0, i + 1).includes(id)).length / relevant.length);
  return { vector: curve(vectorOrder), rerank: curve(rerankOrder) };
}

function checkFailures(snaps: JobSnapshot[]): CheckFailureStat[] {
  const stats = new Map<CheckId, CheckFailureStat>();
  for (const { events } of snaps) {
    for (const e of events) {
      if (e.type !== 'review.check') continue;
      const c = e.check;
      const s = stats.get(c.id) ?? { checkId: c.id, name: c.name, kind: c.kind, fail: 0, warn: 0 };
      if (c.status === 'fail') s.fail++;
      if (c.status === 'warn') s.warn++;
      stats.set(c.id, s);
    }
  }
  return CHECK_IDS.flatMap((id) => stats.get(id) ?? []);
}

function rerankHits(snaps: JobSnapshot[]): RerankHitStat[] {
  const curves = snaps.map((s) => rerankHitCurve(s.events)).filter((c) => c !== null);
  if (!curves.length) return [];
  const n = Math.min(...curves.map((c) => c.vector.length));
  const avg = (pick: (c: { vector: number[]; rerank: number[] }) => number) =>
    curves.reduce((sum, c) => sum + pick(c), 0) / curves.length;
  return Array.from({ length: n }, (_, i) => ({ k: i + 1, vector: avg((c) => c.vector[i]), rerank: avg((c) => c.rerank[i]) }));
}

const mean = (values: number[]) => (values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0);

/** 成效儀表板：只統計已結束（完成或需人工審核）的任務 */
export function dashboardStats(snaps: JobSnapshot[]): DashboardStats {
  const finished = snaps.flatMap((snap) => {
    const stat = jobStat(snap);
    return stat ? [{ snap, stat }] : [];
  });
  const stats = finished.map((x) => x.stat);
  const templates = stats.reduce((n, s) => n + s.templates, 0);
  const delivered = stats.reduce((n, s) => n + s.delivered, 0);
  const cost = stats.reduce((n, s) => n + s.costUsd, 0);
  const finishedSnaps = finished.map((x) => x.snap);
  return {
    jobs: stats.length,
    renders: stats.reduce((n, s) => n + s.renders, 0),
    passRate: stats.length ? stats.filter((s) => s.outcome === 'done').length / stats.length : 0,
    firstPassRate: templates ? finishedSnaps.reduce((n, s) => n + firstRoundPassed(s.events), 0) / templates : 0,
    avgRetries: mean(stats.map((s) => s.rounds - 1)),
    avgDurationMs: mean(stats.map((s) => s.durationMs)),
    costPerImage: delivered ? cost / delivered : null,
    checkFailures: checkFailures(finishedSnaps),
    rerankHits: rerankHits(finishedSnaps),
    recent: [...stats].sort((a, b) => b.createdAt.localeCompare(a.createdAt)).slice(0, RECENT),
  };
}
```

- [ ] **Step 6: 執行測試確認通過**

Run: `npx vitest run src/lib/stats/dashboard.test.ts`
Expected: 13 個測試 PASS

- [ ] **Step 7: 修改 `web/src/lib/api/mock/client.test.ts`**（先寫失敗測試）

找到：

```ts
    expect(await api.listJobs()).toHaveLength(MAX_STORED_JOBS);
  });
});
```

改成：

```ts
    expect(await api.listJobs()).toHaveLength(MAX_STORED_JOBS);
  });

  it('computes dashboard stats from finished jobs, per brand or overall', async () => {
    const api = new MockApiClient();
    expect((await api.getDashboardStats()).jobs).toBe(0);
    await api.demo.seedJobs(6);
    const { jobId } = await startJob(api);
    await vi.advanceTimersByTimeAsync(1_000);
    // 執行中的任務不列入
    expect((await api.getDashboardStats()).jobs).toBe(6);
    await vi.advanceTimersByTimeAsync(13_500);
    const all = await api.getDashboardStats();
    expect(all.jobs).toBe(7);
    expect(all.recent[0].jobId).toBe(jobId);
    expect(all.passRate).toBeCloseTo(6 / 7, 10);
    expect((await api.getDashboardStats('selune')).jobs).toBe(4);
    expect((await api.getDashboardStats('misty-isle')).jobs).toBe(3);
  });
});
```

- [ ] **Step 8: 執行測試確認失敗**

Run: `npx vitest run src/lib/api/mock/client.test.ts`
Expected: FAIL，「computes dashboard stats…」：`api.getDashboardStats is not a function`

- [ ] **Step 9: 修改 `web/src/lib/api/client.ts`**

找到（1／2）：

```ts
import type {
  Brand, BrandDocument, ChannelTemplate, ConnectionState, Copy, DemoOptions, HistoryEntry, IngestEvent, JobInput, JobMessage,
  JobSummary, ParsedBrief, Product, ProductPhoto, RagChunk,
} from '@/types/contract';
```

改成：

```ts
import type {
  Brand, BrandDocument, ChannelTemplate, ConnectionState, Copy, DashboardStats, DemoOptions, HistoryEntry, IngestEvent,
  JobInput, JobMessage, JobSummary, ParsedBrief, Product, ProductPhoto, RagChunk,
} from '@/types/contract';
```

找到（2／2）：

```ts
  setFavorite(historyId: string, favorite: boolean): Promise<HistoryEntry>;
}
```

改成：

```ts
  setFavorite(historyId: string, favorite: boolean): Promise<HistoryEntry>;
  /** 成效儀表板：統計已結束的任務；省略 brandId 時統計所有品牌 */
  getDashboardStats(brandId?: string): Promise<DashboardStats>;
}
```

- [ ] **Step 10: 修改 `web/src/lib/api/mock/client.ts`**

找到（1／3）：

```ts
import type {
  BrandDocument, ConnectionState, Copy, DemoOptions, HistoryEntry, IngestEvent, JobEvent, JobInput, JobMessage, JobStage,
  JobSummary, Product, ProductPhoto, RagChunk, Render, TemplateId,
} from '@/types/contract';
```

改成：

```ts
import type {
  BrandDocument, ConnectionState, Copy, DashboardStats, DemoOptions, HistoryEntry, IngestEvent, JobEvent, JobInput,
  JobMessage, JobStage, JobSummary, Product, ProductPhoto, RagChunk, Render, TemplateId,
} from '@/types/contract';
```

找到（2／3）：

```ts
import { chunkDocument, EMBED_DIMS, embedPreview } from '@/lib/rag/chunk';
import { BRANDS, getBrandById, SAMPLE_PRODUCTS } from './data';
```

改成：

```ts
import { chunkDocument, EMBED_DIMS, embedPreview } from '@/lib/rag/chunk';
import { dashboardStats } from '@/lib/stats/dashboard';
import { BRANDS, getBrandById, SAMPLE_PRODUCTS } from './data';
```

找到（3／3）：

```ts
    });
  }
}
```

改成：

```ts
    });
  }

  async getDashboardStats(brandId?: string): Promise<DashboardStats> {
    const live = [...this.jobs.values()].filter((rec) => rec.finished).map((rec) => this.snapshot(rec));
    const ids = new Set(live.map((s) => s.summary.id));
    const all = [...live, ...(await this.storedJobs()).filter((s) => !ids.has(s.summary.id))];
    return dashboardStats(brandId ? all.filter((s) => s.summary.input.brandId === brandId) : all);
  }
}
```

- [ ] **Step 11: 執行測試與型別檢查確認通過**

Run: `npm run test && npm run typecheck`
Expected：
- `client.test.ts` 29 個、`dashboard.test.ts` 13 個測試 PASS。
- 全部 33 個測試檔、252 個測試 PASS。
- typecheck 無錯誤。

- [ ] **Step 12: Commit**

```bash
git add web/src/types/contract.ts web/src/test/fixtures.ts web/src/lib/stats web/src/lib/api
git commit -m "feat: add dashboard stats with cost estimate and rerank hit rate" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: 流程節點狀態與事件摘要

**Files:**
- Create: `web/src/lib/agent/flow.ts`、`web/src/lib/agent/events.ts`
- Test: `web/src/lib/agent/flow.test.ts`、`web/src/lib/agent/events.test.ts`

**Interfaces:**
- Consumes：`JobMessage`（Task 1）；`makeJobSnapshot`（Task 3）；`STAGE_LABEL`（Plan 2）；`seedOf`（Plan 1）
- Produces：
  - `FLOW_NODES`：規格第 5 節的 8 個節點（id、step、label、tech）
  - `flowState(messages): FlowState`：
    - 每個節點的 `status`（idle／active／done／warn／error）、`visits`、`ms`。
    - `loop`：Query Rewriting 的次數、是否重新檢索、是否進行中、耗時。
    - `elapsedMs`：第一則到最後一則訊息的時間。
  - `EVENT_GROUPS`、`eventGroup(e)`、`describeEvent(e)`、`shortRenderId(id)`、`formatOffset(ms)`、`formatDuration(ms)`

狀態規則：
- 進入過的節點為 done，任務進行中的目前節點為 active。
- 有 Query Rewriting 時，合規審查為 warn；需人工審核時為 error。
- 取消時，當下執行中的節點與 Orchestrator 為 error。

- [ ] **Step 1: 建立 `web/src/lib/agent/flow.test.ts`**（先寫失敗測試）

```ts
import { describe, expect, it } from 'vitest';
import type { JobMessage } from '@/types/contract';
import { makeJobSnapshot } from '@/test/fixtures';
import { FLOW_NODES, flowState } from './flow';

const statuses = (messages: JobMessage[]) => {
  const { nodes } = flowState(messages);
  return Object.fromEntries(FLOW_NODES.map((n) => [n.id, nodes[n.id].status]));
};

describe('flowState', () => {
  it('lists the eight nodes from the spec in order', () => {
    expect(FLOW_NODES.map((n) => n.step)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  });

  it('marks every node done after a retried job, with the review node warned', () => {
    const { events } = makeJobSnapshot();
    expect(statuses(events)).toEqual({
      orchestrator: 'done', brief: 'done', rag: 'done', prompt: 'done', comfy: 'done', compose: 'done', review: 'warn', save: 'done',
    });
    const flow = flowState(events);
    expect(flow.loop).toEqual({ count: 1, requery: true, active: false, ms: 800 });
    expect(flow.elapsedMs).toBe(14_500);
  });

  it('counts visits and time spent in each node from the timestamps', () => {
    const { nodes } = flowState(makeJobSnapshot().events);
    expect(Object.fromEntries(FLOW_NODES.map((n) => [n.id, [nodes[n.id].visits, nodes[n.id].ms]]))).toEqual({
      orchestrator: [1, 14_500],
      brief: [1, 1_100],
      rag: [1, 1_200],
      prompt: [2, 1_600],
      comfy: [2, 6_400],
      compose: [2, 600],
      review: [2, 2_400],
      save: [1, 400],
    });
  });

  it('shows the current node as active while the job runs', () => {
    const { events } = makeJobSnapshot();
    const rendering = events.findIndex((e) => e.type === 'job.status' && e.stage === 'rendering');
    expect(statuses(events.slice(0, rendering + 3))).toEqual({
      orchestrator: 'active', brief: 'done', rag: 'done', prompt: 'done', comfy: 'active', compose: 'idle', review: 'idle', save: 'idle',
    });
    const rewriting = events.findIndex((e) => e.type === 'job.status' && e.stage === 'rewriting');
    expect(flowState(events.slice(0, rewriting + 1)).loop.active).toBe(true);
  });

  it('marks the review node as an error when the job needs manual review', () => {
    const { events } = makeJobSnapshot({ demo: { forceAllFail: true } });
    expect(statuses(events).review).toBe('error');
    expect(flowState(events).loop.count).toBe(2);
  });

  it('marks the node that was running when the job was cancelled', () => {
    const { events } = makeJobSnapshot();
    const rendering = events.findIndex((e) => e.type === 'job.status' && e.stage === 'rendering');
    const head = events.slice(0, rendering + 3);
    const cancelled: JobMessage = { type: 'job.status', stage: 'cancelled', round: 1, seq: head.length + 1, ts: head.at(-1)!.ts };
    const s = statuses([...head, cancelled]);
    expect(s.comfy).toBe('error');
    expect(s.orchestrator).toBe('error');
  });

  it('is idle without messages', () => {
    const flow = flowState([]);
    expect(Object.values(flow.nodes).every((n) => n.status === 'idle' && n.visits === 0)).toBe(true);
    expect(flow.elapsedMs).toBe(0);
  });
});
```

- [ ] **Step 2: 建立 `web/src/lib/agent/events.test.ts`**（先寫失敗測試）

```ts
import { describe, expect, it } from 'vitest';
import type { JobEvent } from '@/types/contract';
import { makeJobSnapshot } from '@/test/fixtures';
import { describeEvent, eventGroup, formatDuration, formatOffset, shortRenderId } from './events';

const { events } = makeJobSnapshot();
const pick = (pred: (e: JobEvent) => boolean): JobEvent => {
  const e = events.find(pred);
  if (!e) throw new Error('missing event');
  return e;
};

describe('eventGroup', () => {
  it('groups every event type of a job', () => {
    const groups = Object.fromEntries(events.map((e) => [e.type, eventGroup(e)]));
    expect(groups).toEqual({
      'job.accepted': 'job', 'job.status': 'job', 'job.completed': 'job', log: 'log', 'brief.parsed': 'agent',
      'rag.retrieved': 'rag', 'rag.reranked': 'rag', 'prompt.generated': 'agent', 'comfy.queued': 'comfy',
      'render.progress': 'comfy', 'render.completed': 'comfy', 'review.check': 'review', 'review.completed': 'review',
      'rewrite.started': 'agent',
    });
    expect(eventGroup({ type: 'job.needs_review', jobId: 'j', reason: 'x' })).toBe('job');
  });
});

describe('describeEvent', () => {
  it('summarises status, review and rewrite events', () => {
    expect(describeEvent({ type: 'job.status', stage: 'parsing', round: 0 })).toBe('需求拆解');
    expect(describeEvent({ type: 'job.status', stage: 'reviewing', round: 2 })).toBe('合規審查・第 2 輪');
    expect(describeEvent(pick((e) => e.type === 'review.check' && e.check.id === 'banned_words' && e.round === 1)))
      .toBe('r1_ig-post_v0・✗ 禁用詞檢查：禁用詞「根治」「醫療級」');
    expect(describeEvent(pick((e) => e.type === 'rewrite.started'))).toBe(
      'ig-post 未通過（banned_words, color_delta, logo_clearance, disclaimer, vlm_exaggeration, vlm_occlusion）→ 文案改寫、色彩修正、版面修正、補充註記、構圖修正・重新檢索',
    );
    expect(describeEvent(pick((e) => e.type === 'rag.reranked'))).toBe('color 0.97 > law 0.93 > logo 0.88 > layout 0.74 > history 0.61');
    expect(describeEvent({ type: 'log', source: 'vlm', level: 'warn', message: '第 1 輪：0/1 個模板通過' }))
      .toBe('[VLM] 第 1 輪：0/1 個模板通過');
  });
});

describe('formatting', () => {
  it('shortens render ids', () => {
    expect(shortRenderId('job_20261005_0930_7fff_r2_ecom-main_v3')).toBe('r2_ecom-main_v3');
    expect(shortRenderId('other')).toBe('other');
  });

  it('formats offsets and durations', () => {
    expect(formatOffset(1_250)).toBe('+1.25s');
    expect(formatDuration(850)).toBe('850 ms');
    expect(formatDuration(14_500)).toBe('14.5 秒');
    expect(formatDuration(125_000)).toBe('2 分 05 秒');
  });
});
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `npx vitest run src/lib/agent/flow.test.ts src/lib/agent/events.test.ts`
Expected: FAIL，`Cannot find module './flow'`、`Cannot find module './events'`

- [ ] **Step 4: 建立 `web/src/lib/agent/flow.ts`**

```ts
import type { JobMessage, JobStage } from '@/types/contract';

export type FlowNodeId = 'orchestrator' | 'brief' | 'rag' | 'prompt' | 'comfy' | 'compose' | 'review' | 'save';
/** warn：曾經未通過、重試後完成；error：需人工審核或在此節點取消 */
export type FlowStatus = 'idle' | 'active' | 'done' | 'warn' | 'error';

export interface FlowNodeDef { id: FlowNodeId; step: number; label: string; tech: string }

/** 規格第 5 節的流程節點 */
export const FLOW_NODES: FlowNodeDef[] = [
  { id: 'orchestrator', step: 1, label: 'Orchestrator', tech: 'FastAPI' },
  { id: 'brief', step: 2, label: '需求拆解 Agent', tech: 'LLM' },
  { id: 'rag', step: 3, label: 'RAG 檢索', tech: 'Chroma 召回 → BGE Rerank' },
  { id: 'prompt', step: 4, label: 'Prompt 構建', tech: 'JSON Prompt + BBox' },
  { id: 'comfy', step: 5, label: 'ComfyUI', tech: '去背 → 背景 → 打光 → 放大' },
  { id: 'compose', step: 6, label: '文字排版合成', tech: '排版引擎' },
  { id: 'review', step: 7, label: '合規審查', tech: '規則 + VLM' },
  { id: 'save', step: 8, label: '寫入 DB 與回傳', tech: 'DB + WebSocket' },
];

const STAGE_NODE: Partial<Record<JobStage, FlowNodeId>> = {
  parsing: 'brief', retrieving: 'rag', prompting: 'prompt', rendering: 'comfy', composing: 'compose',
  reviewing: 'review', saving: 'save',
};

export interface FlowNodeState {
  status: FlowStatus;
  /** 進入幾次（Prompt 構建等節點每輪一次） */
  visits: number;
  /** 停留的總時間（依事件時間戳） */
  ms: number;
}

export interface FlowLoop {
  /** Query Rewriting 次數 */
  count: number;
  /** 改寫時是否重新檢索合規用語 */
  requery: boolean;
  active: boolean;
  ms: number;
}

export interface FlowState {
  nodes: Record<FlowNodeId, FlowNodeState>;
  /** 審查未通過 → Query Rewriting → 回到 Prompt 構建（必要時重新檢索） */
  loop: FlowLoop;
  /** 第一則到最後一則訊息的時間 */
  elapsedMs: number;
}

/** 由事件訊息推算每個流程節點的狀態與耗時 */
export function flowState(messages: JobMessage[]): FlowState {
  const nodes = Object.fromEntries(
    FLOW_NODES.map((n): [FlowNodeId, FlowNodeState] => [n.id, { status: 'idle', visits: 0, ms: 0 }]),
  ) as Record<FlowNodeId, FlowNodeState>;
  const loop: FlowLoop = { count: 0, requery: false, active: false, ms: 0 };
  let open: { node: FlowNodeId | 'loop'; since: number } | null = null;
  let last: FlowNodeId | 'loop' | null = null;
  let stage: JobStage | null = null;

  const close = (until: number) => {
    if (!open) return;
    if (open.node === 'loop') loop.ms += until - open.since;
    else nodes[open.node].ms += until - open.since;
    open = null;
  };

  for (const m of messages) {
    if (m.type === 'job.accepted') nodes.orchestrator.visits = 1;
    if (m.type === 'rewrite.started' && m.requery) loop.requery = true;
    if (m.type !== 'job.status') continue;
    const at = Date.parse(m.ts);
    close(at);
    stage = m.stage;
    const node = m.stage === 'rewriting' ? 'loop' : STAGE_NODE[m.stage];
    if (!node) continue;
    if (node === 'loop') loop.count++;
    else nodes[node].visits++;
    open = { node, since: at };
    last = node;
  }

  const first = messages[0];
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
  return { nodes, loop, elapsedMs };
}
```

- [ ] **Step 5: 建立 `web/src/lib/agent/events.ts`**

```ts
import type { CheckStatus, JobEvent } from '@/types/contract';
import { truncate } from '@/lib/core/text';
import { STAGE_LABEL } from '@/lib/jobs/view';
import { seedOf } from './prompt';

/** 事件串流的分類（篩選用） */
export type EventGroup = 'job' | 'agent' | 'rag' | 'comfy' | 'review' | 'log';
export const EVENT_GROUPS: { id: EventGroup; label: string }[] = [
  { id: 'job', label: '任務' },
  { id: 'agent', label: 'Agent' },
  { id: 'rag', label: 'RAG' },
  { id: 'comfy', label: 'ComfyUI' },
  { id: 'review', label: '審查' },
  { id: 'log', label: 'Log' },
];

export function eventGroup(e: JobEvent): EventGroup {
  switch (e.type) {
    case 'job.accepted':
    case 'job.status':
    case 'job.completed':
    case 'job.needs_review':
      return 'job';
    case 'brief.parsed':
    case 'prompt.generated':
    case 'rewrite.started':
      return 'agent';
    case 'rag.retrieved':
    case 'rag.reranked':
      return 'rag';
    case 'comfy.queued':
    case 'render.progress':
    case 'render.completed':
      return 'comfy';
    case 'review.check':
    case 'review.completed':
      return 'review';
    case 'log':
      return 'log';
  }
}

/** render id 去掉任務 id：job_…_r1_ig-post_v0 → r1_ig-post_v0 */
export function shortRenderId(renderId: string): string {
  return renderId.match(/_(r\d+_[a-z-]+_v\d+)$/)?.[1] ?? renderId;
}

const MARK: Record<CheckStatus, string> = { pass: '✓', warn: '⚠', fail: '✗' };

/** 事件串流每一列的摘要（事件類型另外顯示） */
export function describeEvent(e: JobEvent): string {
  switch (e.type) {
    case 'job.accepted':
      return e.jobId;
    case 'job.status':
      return e.round ? `${STAGE_LABEL[e.stage]}・第 ${e.round} 輪` : STAGE_LABEL[e.stage];
    case 'brief.parsed': {
      const b = e.parsedBrief;
      return `語氣 ${b.tone}・賣點 ${b.sellingPoints.length} 項・檔期 ${b.campaign ?? '無'}・優惠 ${b.offer ?? '無'}`;
    }
    case 'rag.retrieved':
      return `召回 ${e.hits.length} 筆：${truncate(e.query, 36)}`;
    case 'rag.reranked':
      return e.hits.map((h) => `${h.tag} ${(h.rerankScore ?? 0).toFixed(2)}`).join(' > ');
    case 'prompt.generated':
      return `第 ${e.round} 輪 ${e.templateId}：${e.spec.layout.length} 個 BBox・seed ${seedOf(e.spec)}`;
    case 'comfy.queued':
      return `${e.injection.workflowFile}・注入 ${e.injection.params.length} 個參數`;
    case 'render.progress':
      return `${e.node} ${e.step}/${e.maxStep}`;
    case 'render.completed':
      return `第 ${e.round} 輪 ${e.renders.length} 張候選`;
    case 'review.check':
      return `${shortRenderId(e.renderId)}・${MARK[e.check.status]} ${e.check.name}：${e.check.value}`;
    case 'review.completed':
      return `${shortRenderId(e.renderId)}・${e.score} 分・${e.passed ? '通過' : '未通過'}`;
    case 'rewrite.started':
      return `${e.templateId} 未通過（${e.reasons.join(', ')}）→ ${e.fixes.map((f) => f.title).join('、')}${e.requery ? '・重新檢索' : ''}`;
    case 'job.completed':
      return `最佳候選 ${Object.keys(e.bestRenderIds).length} 張`;
    case 'job.needs_review':
      return e.reason;
    case 'log':
      return `[${e.source.toUpperCase()}] ${e.message}`;
  }
}

/** 相對於任務開始的時間：+1.25s */
export function formatOffset(ms: number): string {
  return `+${(ms / 1000).toFixed(2)}s`;
}

/** 耗時：850 ms、14.5 秒、2 分 05 秒 */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} 秒`;
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)} 分 ${String(s % 60).padStart(2, '0')} 秒`;
}
```

- [ ] **Step 6: 執行測試與型別檢查確認通過**

Run: `npm run test && npm run typecheck`
Expected：
- `flow.test.ts` 7 個、`events.test.ts` 4 個測試 PASS。
- 全部 35 個測試檔、263 個測試 PASS。
- typecheck 無錯誤。

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/agent
git commit -m "feat: derive agent flow state and event summaries" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Agent 透視的資料整理（Prompt、注入參數、Rerank、BBox、重試）

**Files:**
- Create: `web/src/lib/agent/inspect.ts`
- Test: `web/src/lib/agent/inspect.test.ts`

**Interfaces:**
- Consumes：`JobView`、`specKey`、`applyEvents`（Plan 2）；`diffSpecs`（Plan 1）；`makeJobSnapshot`（Task 3）
- Produces：
  - `specOptions(view): SpecOption[]`：依輪次、再依模板的標準順序
  - `injectionRows(view, key): InjectionRow[]`：每個參數附上同模板上一輪的值與 `changed`
  - `rerankRows(view): RerankRow[]`：向量排名、Rerank 排名、分數，以及引用這段規範且未通過的檢查（`citedBy`）
  - `overlayFor(render): Overlay`：每個版面 BBox 的最嚴重檢查結果與問題名稱；整張圖的檢查另外列出
  - `retryDiffs(view): RetryDiff[]`：每次 Query Rewriting 的原因、修正策略、改寫前後的 `diffSpecs`、改寫前後的最高分

- [ ] **Step 1: 建立 `web/src/lib/agent/inspect.test.ts`**（先寫失敗測試）

```ts
import { describe, expect, it } from 'vitest';
import { makeJobSnapshot } from '@/test/fixtures';
import { applyEvents } from '@/lib/jobs/view';
import { injectionRows, overlayFor, rerankRows, retryDiffs, specOptions } from './inspect';

const { events } = makeJobSnapshot();
const view = applyEvents(events);
const upTo = (type: string) => applyEvents(events.slice(0, events.findIndex((e) => e.type === type) + 1));

describe('specOptions', () => {
  it('orders prompts by round, then by the standard template order', () => {
    const two = applyEvents(makeJobSnapshot({ templateIds: ['story', 'ig-post'] }).events);
    expect(specOptions(two).map((o) => o.key)).toEqual(['1:ig-post', '1:story', '2:ig-post', '2:story']);
  });
});

describe('injectionRows', () => {
  it('has no previous values in the first round', () => {
    const rows = injectionRows(view, '1:ig-post');
    expect(rows).toHaveLength(15);
    expect(rows.every((r) => r.previous === null && !r.changed)).toBe(true);
  });

  it('marks the parameters the rewrite changed', () => {
    const rows = injectionRows(view, '2:ig-post');
    expect(rows.filter((r) => r.changed).map((r) => r.label)).toEqual(['positive_prompt', 'negative_prompt', 'seed', 'layout_boxes']);
    const negative = rows.find((r) => r.label === 'negative_prompt')!;
    expect(negative.previous).toBe('lowres, blurry, watermark, deformed product, extra objects, garbled text');
    expect(String(negative.value)).toContain('off-brand colors');
  });

  it('returns nothing for an unknown prompt', () => {
    expect(injectionRows(view, '9:ig-post')).toEqual([]);
  });
});

describe('rerankRows', () => {
  it('compares vector and rerank ranks and lists the failed checks citing each guideline', () => {
    expect(rerankRows(view).map((r) => [r.tag, r.vectorRank, r.rerankRank, r.citedBy])).toEqual([
      ['color', 2, 1, ['color_delta']],
      ['law', 5, 2, ['banned_words', 'disclaimer', 'vlm_exaggeration']],
      ['logo', 4, 3, ['logo_clearance', 'vlm_occlusion']],
      ['layout', 1, 4, []],
      ['history', 3, 5, []],
    ]);
  });

  it('uses the vector order before rerank arrives', () => {
    const rows = rerankRows(upTo('rag.retrieved'));
    expect(rows.map((r) => r.tag)).toEqual(['layout', 'color', 'history', 'logo', 'law']);
    expect(rows.every((r) => r.rerankRank === null && r.rerankScore === null)).toBe(true);
  });
});

describe('overlayFor', () => {
  it('colours each layout box by the worst check that targets it', () => {
    const first = view.renders[view.renderIds[0]];
    const overlay = overlayFor(first);
    expect(Object.fromEntries(overlay.boxes.map((b) => [b.id, b.status]))).toEqual({
      logo: 'fail', headline: 'pass', subhead: 'fail', features: null, product: 'pass', badge: null, price: null, disclaimer: 'warn',
    });
    expect(overlay.boxes.find((b) => b.id === 'logo')!.issues).toEqual(['Logo 淨空區', '物件與文字遮擋']);
    expect(overlay.canvas).toEqual({ status: 'fail', issues: ['品牌主色色差'] });
  });
});

describe('retryDiffs', () => {
  it('shows what the rewrite changed and how the score moved', () => {
    const [diff] = retryDiffs(view);
    expect(diff).toMatchObject({ round: 1, templateId: 'ig-post', requery: true });
    expect(diff.diffs.map((d) => d.path)).toEqual([
      'palette.primary', 'palette.secondary', 'layout[logo].bbox', 'copy.subhead', 'copy.disclaimer', 'negativePrompt',
    ]);
    expect(diff.scoreBefore).toBeLessThan(50);
    expect(diff.scoreAfter).toBeGreaterThan(90);
  });

  it('has no diff before the next round is generated', () => {
    const [diff] = retryDiffs(upTo('rewrite.started'));
    expect(diff.diffs).toEqual([]);
    expect(diff.scoreAfter).toBeNull();
  });
});
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `npx vitest run src/lib/agent/inspect.test.ts`
Expected: FAIL，`Cannot find module './inspect'`

- [ ] **Step 3: 建立 `web/src/lib/agent/inspect.ts`**

```ts
import type {
  BBox, CheckId, CheckStatus, ComfyParam, Fix, LayoutElementId, RagChunk, Render, TemplateId,
} from '@/types/contract';
import { TEMPLATE_IDS } from '@/types/contract';
import { specKey, type JobView } from '@/lib/jobs/view';
import { diffSpecs, type SpecDiff } from './diff';

/* ---------- JSON Prompt 與注入參數 ---------- */

export interface SpecOption { key: string; round: number; templateId: TemplateId }

/** 任務產生過的 Prompt：依輪次、再依模板的標準順序 */
export function specOptions(view: JobView): SpecOption[] {
  return Object.values(view.specs)
    .map((s) => ({ key: specKey(s.round, s.templateId), round: s.round, templateId: s.templateId }))
    .sort((a, b) => a.round - b.round || TEMPLATE_IDS.indexOf(a.templateId) - TEMPLATE_IDS.indexOf(b.templateId));
}

export interface InjectionRow extends ComfyParam {
  /** 同模板上一輪的值；第一輪為 null */
  previous: string | number | null;
  changed: boolean;
}

/** workflow_api.json 注入參數對照：與同模板上一輪相比，標出改變的值 */
export function injectionRows(view: JobView, key: string): InjectionRow[] {
  const spec = view.specs[key];
  if (!spec) return [];
  const prev = view.specs[specKey(spec.round - 1, spec.templateId)];
  return spec.injection.params.map((p) => {
    const before = prev?.injection.params.find((q) => q.nodeId === p.nodeId && q.input === p.input);
    return { ...p, previous: before ? before.value : null, changed: before !== undefined && before.value !== p.value };
  });
}

/* ---------- RAG 召回與 Rerank ---------- */

export interface RerankRow extends Pick<RagChunk, 'source' | 'section' | 'tag' | 'text'> {
  chunkId: string;
  vectorScore: number;
  vectorRank: number;
  rerankScore: number | null;
  rerankRank: number | null;
  /** 引用這段規範、且未通過（失敗或警告）的檢查項 */
  citedBy: CheckId[];
}

/** 第一次檢索的結果：Rerank 後依 Rerank 順序，否則依向量分數 */
export function rerankRows(view: JobView): RerankRow[] {
  const byVector = [...view.ragHits].sort((a, b) => b.vectorScore - a.vectorScore).map((h) => h.chunkId);
  const reranked = view.ragHits.some((h) => h.rerankScore !== undefined);
  const order = reranked ? view.ragHits : [...view.ragHits].sort((a, b) => b.vectorScore - a.vectorScore);
  const cited = new Map<string, Set<CheckId>>();
  for (const id of view.renderIds) {
    for (const c of view.renders[id].checks) {
      if (c.status === 'pass' || !c.ragRef) continue;
      cited.set(c.ragRef, (cited.get(c.ragRef) ?? new Set()).add(c.id));
    }
  }
  return order.map((h, i) => ({
    chunkId: h.chunkId, source: h.source, section: h.section, tag: h.tag, text: h.text,
    vectorScore: h.vectorScore,
    vectorRank: byVector.indexOf(h.chunkId) + 1,
    rerankScore: h.rerankScore ?? null,
    rerankRank: reranked ? i + 1 : null,
    citedBy: [...(cited.get(h.chunkId) ?? [])],
  }));
}

/* ---------- 合規報告與 BBox 疊圖 ---------- */

const SEVERITY: Record<CheckStatus, number> = { pass: 0, warn: 1, fail: 2 };
const worse = (a: CheckStatus | null, b: CheckStatus): CheckStatus => (a === null || SEVERITY[b] > SEVERITY[a] ? b : a);

export interface OverlayBox {
  id: LayoutElementId;
  bbox: BBox;
  /** 指向這個元素的檢查中最嚴重的結果；沒有檢查指向它時為 null */
  status: CheckStatus | null;
  /** 未通過的檢查名稱 */
  issues: string[];
}

export interface Overlay {
  boxes: OverlayBox[];
  /** 針對整張圖的檢查（例如主色色差） */
  canvas: { status: CheckStatus | null; issues: string[] };
}

export function overlayFor(render: Render): Overlay {
  const canvas: Overlay['canvas'] = { status: null, issues: [] };
  const boxes = render.spec.layout.map((b): OverlayBox => ({ id: b.id, bbox: b.bbox, status: null, issues: [] }));
  for (const c of render.checks) {
    const target = c.target === 'canvas' ? canvas : boxes.find((b) => b.id === c.target);
    if (!target) continue;
    target.status = worse(target.status, c.status);
    if (c.status !== 'pass') target.issues.push(c.name);
  }
  return { boxes, canvas };
}

/* ---------- 重試 diff ---------- */

export interface RetryDiff {
  round: number;
  templateId: TemplateId;
  reasons: CheckId[];
  fixes: Fix[];
  requery: boolean;
  /** 改寫前後 Prompt 的差異；下一輪的 Prompt 還沒產生時為空陣列 */
  diffs: SpecDiff[];
  /** 該模板在這一輪、下一輪的最高分；尚未審查時為 null */
  scoreBefore: number | null;
  scoreAfter: number | null;
}

function bestScore(view: JobView, round: number, templateId: TemplateId): number | null {
  const scores = view.renderIds
    .map((id) => view.renders[id])
    .filter((r) => r.round === round && r.templateId === templateId && r.score !== null)
    .map((r) => r.score as number);
  return scores.length ? Math.max(...scores) : null;
}

/** 每次 Query Rewriting：未通過的原因、修正策略，以及改寫前後的 Prompt 差異 */
export function retryDiffs(view: JobView): RetryDiff[] {
  return view.rewrites.map((r) => {
    const before = view.specs[specKey(r.round, r.templateId)];
    const after = view.specs[specKey(r.round + 1, r.templateId)];
    return {
      ...r,
      diffs: before && after ? diffSpecs(before, after) : [],
      scoreBefore: bestScore(view, r.round, r.templateId),
      scoreAfter: bestScore(view, r.round + 1, r.templateId),
    };
  });
}
```

- [ ] **Step 4: 執行測試與型別檢查確認通過**

Run: `npm run test && npm run typecheck`
Expected：
- `inspect.test.ts` 9 個測試 PASS。
- 全部 36 個測試檔、272 個測試 PASS。
- typecheck 無錯誤。

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/agent
git commit -m "feat: add agent inspection helpers for prompts, rerank, overlay and retries" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `/agent` ①：任務透視頁、流程節點、事件串流

**Files:**
- Create: `web/src/components/agent/{use-job-stream.ts,flow-graph.tsx,event-stream.tsx,agent-inspector.tsx}`
- Modify: `web/src/app/agent/page.tsx`
- Delete: `web/src/components/agent/agent-preview.tsx`

**Interfaces:**
- Consumes：`subscribe`、`listJobs`（Task 1、2）；`flowState`、`FLOW_NODES`、`EVENT_GROUPS`、`eventGroup`、`describeEvent`、`formatOffset`、`formatDuration`（Task 4）；`reduceJob`、`jobProgress`、`STAGE_LABEL`（Plan 2）
- Produces：
  - `useJobStream(jobId): { messages, view, error }`：依 `seq` 略過重播的重複事件。換任務時以 `key` 重新掛載元件。
  - 元件 `AgentInspector`（取代 `AgentPreview`）、`FlowGraph`、`EventStream`
  - 分頁先只有「事件串流」，Task 7、8 再加入其他分頁

- [ ] **Step 1: 建立 `web/src/components/agent/use-job-stream.ts`**

```ts
'use client';

import { useEffect, useState } from 'react';
import type { JobMessage } from '@/types/contract';
import { getApiClient } from '@/lib/api';
import { emptyJobView, reduceJob, type JobView } from '@/lib/jobs/view';

export interface JobStream {
  /** 原始訊息（含 seq、ts），事件串流與耗時使用 */
  messages: JobMessage[];
  view: JobView;
  error: string | null;
}

/** 訂閱任務事件：保留原始訊息，同時累積成 JobView。換任務時請以 key 重新掛載元件。 */
export function useJobStream(jobId: string): JobStream {
  const [state, setState] = useState<JobStream>(() => ({ messages: [], view: emptyJobView(jobId), error: null }));
  useEffect(
    () =>
      getApiClient().subscribe(
        jobId,
        (m) =>
          setState((s) =>
            // 重新訂閱時會重播已收到的事件（開發模式的 StrictMode 會執行兩次 effect）：依序號略過重複的
            m.seq <= (s.messages.at(-1)?.seq ?? 0) ? s : { ...s, messages: [...s.messages, m], view: reduceJob(s.view, m) },
          ),
        (err) => setState((s) => ({ ...s, error: err.message })),
      ),
    [jobId],
  );
  return state;
}
```

- [ ] **Step 2: 建立 `web/src/components/agent/flow-graph.tsx`**

```tsx
import { RotateCcw } from 'lucide-react';
import type { JobInput, RenderNode } from '@/types/contract';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { formatDuration } from '@/lib/agent/events';
import { FLOW_NODES, type FlowNodeId, type FlowState, type FlowStatus } from '@/lib/agent/flow';
import type { JobView } from '@/lib/jobs/view';
import { ENGINE_LABEL } from '@/lib/store/studio';
import { cn } from '@/lib/utils';

const STATUS_STYLE: Record<FlowStatus, string> = {
  idle: 'border-dashed bg-card text-muted-foreground',
  active: 'border-primary bg-primary/5 ring-2 ring-primary/25',
  done: 'border-emerald-200 bg-emerald-50/70',
  warn: 'border-amber-200 bg-amber-50/80',
  error: 'border-red-200 bg-red-50/80',
};

const STATUS_LABEL: Record<FlowStatus, string> = {
  idle: '未開始', active: '執行中', done: '完成', warn: '重試後通過', error: '未完成',
};

const STEP_STYLE: Record<FlowStatus, string> = {
  idle: 'bg-muted text-muted-foreground',
  active: 'bg-primary text-primary-foreground',
  done: 'bg-emerald-600 text-white',
  warn: 'bg-amber-500 text-white',
  error: 'bg-red-600 text-white',
};

const COMFY_STEP: Record<RenderNode, string> = { cutout: '去背', generate: '背景生成', relight: '打光融合', upscale: '放大' };

/** 節點說明：有任務設定時顯示實際使用的模型 */
function techOf(id: FlowNodeId, fallback: string, input: JobInput | null): string {
  if (!input) return fallback;
  if (id === 'brief') return input.llm;
  if (id === 'comfy') return ENGINE_LABEL[input.engine];
  if (id === 'review') return `規則 7 項 + ${input.vlm}`;
  return fallback;
}

/** Agent 流程節點圖：每個節點的狀態、進入次數與耗時；審查未通過時經 Query Rewriting 回到 Prompt 構建 */
export function FlowGraph({ flow, view, input }: { flow: FlowState; view: JobView; input: JobInput | null }) {
  const progress = view.progress && view.progress.round === view.round ? view.progress : null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>流程節點</CardTitle>
        <CardDescription>依 WebSocket 事件即時更新；時間為各節點的累計耗時。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
          {FLOW_NODES.map((n) => {
            const s = flow.nodes[n.id];
            return (
              <li key={n.id} className={cn('flex flex-col gap-1.5 rounded-lg border p-2.5 text-sm transition-colors', STATUS_STYLE[s.status])}>
                <div className="flex items-center gap-2">
                  <span className={cn('grid size-5 shrink-0 place-items-center rounded-full text-[11px] font-bold', STEP_STYLE[s.status])}>
                    {n.step}
                  </span>
                  <span className="font-semibold leading-tight text-foreground">{n.label}</span>
                </div>
                <p className="text-xs leading-snug text-muted-foreground">{techOf(n.id, n.tech, input)}</p>
                <div className="mt-auto flex flex-wrap items-center gap-x-2 text-xs">
                  <span className={cn('font-medium', s.status === 'idle' && 'text-muted-foreground')}>{STATUS_LABEL[s.status]}</span>
                  {s.visits > 1 && <span className="text-muted-foreground">× {s.visits}</span>}
                  {s.ms > 0 && <span className="ml-auto font-mono text-muted-foreground">{formatDuration(s.ms)}</span>}
                </div>
                {n.id === 'comfy' && s.status === 'active' && progress && (
                  <p className="font-mono text-xs text-primary">
                    {COMFY_STEP[progress.node]} {progress.step}/{progress.maxStep}
                  </p>
                )}
              </li>
            );
          })}
        </ol>
        <div
          className={cn(
            'flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-sm',
            flow.loop.active ? 'border-amber-300 bg-amber-50' : flow.loop.count ? 'border-amber-200' : 'border-dashed text-muted-foreground',
          )}
        >
          <RotateCcw className={cn('size-4', flow.loop.count > 0 && 'text-amber-600', flow.loop.active && 'animate-spin')} />
          <span className="font-medium">Query Rewriting</span>
          <span className="text-muted-foreground">
            審查未通過 → 回到 ④ Prompt 構建{flow.loop.requery ? '，並重新檢索 ③ 合規用語' : ''}
          </span>
          <span className="ml-auto text-xs">
            {flow.loop.count ? `${flow.loop.count} 次・${formatDuration(flow.loop.ms)}` : '未觸發'}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 3: 建立 `web/src/components/agent/event-stream.tsx`**

```tsx
'use client';

import { useEffect, useRef, useState } from 'react';
import type { JobMessage } from '@/types/contract';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { describeEvent, EVENT_GROUPS, eventGroup, formatOffset, type EventGroup } from '@/lib/agent/events';
import { cn } from '@/lib/utils';

const GROUP_COLOR: Record<EventGroup, string> = {
  job: 'text-sky-300',
  agent: 'text-violet-300',
  rag: 'text-emerald-300',
  comfy: 'text-amber-300',
  review: 'text-pink-300',
  log: 'text-slate-400',
};

const LEVEL_COLOR = { info: 'text-slate-300', ok: 'text-emerald-300', warn: 'text-amber-300', error: 'text-red-300' } as const;

/** WebSocket 事件串流：序號、相對時間、事件類型與摘要；可依分類篩選 */
export function EventStream({ messages }: { messages: JobMessage[] }) {
  const [groups, setGroups] = useState<string[]>(EVENT_GROUPS.map((g) => g.id));
  const [hideProgress, setHideProgress] = useState(true);
  const box = useRef<HTMLDivElement>(null);
  // 使用者捲到底部時，新事件進來會自動捲動；往上捲時保持位置
  const stick = useRef(true);

  const t0 = messages[0] ? Date.parse(messages[0].ts) : 0;
  const shown = messages.filter((m) => groups.includes(eventGroup(m)) && !(hideProgress && m.type === 'render.progress'));

  useEffect(() => {
    const el = box.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [shown.length]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>WebSocket 事件串流</CardTitle>
        <CardDescription>
          共 {messages.length} 則；每則都帶序號（seq）與時間戳（ts），第二階段重新連線時用來補齊漏掉的事件。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <ToggleGroup
            type="multiple"
            variant="outline"
            size="sm"
            spacing={1}
            className="flex-wrap"
            value={groups}
            onValueChange={setGroups}
            aria-label="事件分類"
          >
            {EVENT_GROUPS.map((g) => (
              <ToggleGroupItem key={g.id} value={g.id} className="px-3">
                {g.label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <div className="flex items-center gap-2">
            <Switch id="hide-progress" checked={hideProgress} onCheckedChange={setHideProgress} />
            <Label htmlFor="hide-progress" className="font-normal">隱藏 render.progress</Label>
          </div>
        </div>
        <div
          ref={box}
          onScroll={(e) => {
            const el = e.currentTarget;
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
          }}
          className="max-h-[60vh] overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-xs leading-relaxed"
          role="log"
          aria-label="事件串流"
        >
          {shown.length === 0 && <p className="text-slate-500">等待事件…</p>}
          {shown.map((m) => {
            const group = eventGroup(m);
            return (
              <div key={m.seq} className="flex gap-2" title={m.ts}>
                <span className="w-9 shrink-0 text-right text-slate-500">#{m.seq}</span>
                <span className="w-14 shrink-0 text-slate-500">{formatOffset(Date.parse(m.ts) - t0)}</span>
                <span className={cn('hidden w-36 shrink-0 sm:inline', GROUP_COLOR[group])}>{m.type}</span>
                <span className={cn('min-w-0 break-words', m.type === 'log' ? LEVEL_COLOR[m.level] : 'text-slate-200')}>
                  <span className={cn('mr-2 sm:hidden', GROUP_COLOR[group])}>{m.type}</span>
                  {describeEvent(m)}
                </span>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 4: 建立 `web/src/components/agent/agent-inspector.tsx`**

```tsx
'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Network } from 'lucide-react';
import type { JobInput, JobMessage, JobSummary } from '@/types/contract';
import { EmptyState } from '@/components/common/empty-state';
import { PageHeader } from '@/components/common/page-header';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { getApiClient } from '@/lib/api';
import { formatDuration } from '@/lib/agent/events';
import { flowState, type FlowState } from '@/lib/agent/flow';
import { getTemplate } from '@/lib/compose/templates';
import { jobProgress, STAGE_LABEL, type JobView } from '@/lib/jobs/view';
import { useAppStore } from '@/lib/store/app';
import { cn } from '@/lib/utils';
import { EventStream } from './event-stream';
import { FlowGraph } from './flow-graph';
import { useJobStream } from './use-job-stream';

function JobPicker({ jobs, value, onChange }: { jobs: JobSummary[]; value: string | null; onChange: (id: string) => void }) {
  return (
    <Select value={value ?? ''} onValueChange={onChange}>
      <SelectTrigger className="w-full bg-card sm:w-80" aria-label="選擇任務">
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
  );
}

function JobHeader({ view, flow, messages, input }: { view: JobView; flow: FlowState; messages: JobMessage[]; input: JobInput | null }) {
  const brand = useAppStore((s) => s.brands.find((b) => b.id === input?.brandId));
  return (
    <Card>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm font-semibold">{view.jobId}</span>
          <Badge variant="secondary">{view.stage ? STAGE_LABEL[view.stage] : '等待事件'}</Badge>
          {view.round > 0 && <Badge variant="outline">第 {view.round} 輪</Badge>}
          <span className="ml-auto text-xs text-muted-foreground">
            {messages.length} 則事件・{formatDuration(flow.elapsedMs)}
          </span>
        </div>
        {input && (
          <p className="text-sm text-muted-foreground">
            {brand?.name ?? input.brandId}・「{input.brief}」・{input.templateIds.map((t) => getTemplate(t).label).join('、')}
            ・每個模板 {input.variantsPerTemplate} 張・最多重試 {input.maxRetries} 次
          </p>
        )}
        <Progress value={jobProgress(view) * 100} className="h-2" />
      </CardContent>
    </Card>
  );
}

function JobInspector({ jobId, input }: { jobId: string; input: JobInput | null }) {
  const { messages, view, error } = useJobStream(jobId);
  if (error) {
    return (
      <Alert variant="destructive">
        <AlertTitle>無法載入任務</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }
  const flow = flowState(messages);
  return (
    <div className="space-y-5">
      <JobHeader view={view} flow={flow} messages={messages} input={input} />
      <FlowGraph flow={flow} view={view} input={input} />
      <Tabs defaultValue="events">
        <TabsList className="h-auto flex-wrap">
          <TabsTrigger value="events">事件串流</TabsTrigger>
        </TabsList>
        <TabsContent value="events">
          <EventStream messages={messages} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

/** Agent 透視：預設顯示最新的任務，可切換 */
export function AgentInspector() {
  const router = useRouter();
  const params = useSearchParams();
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  useEffect(() => {
    void getApiClient().listJobs().then(setJobs);
  }, []);
  const jobId = params.get('job') ?? jobs?.[0]?.id ?? null;
  const input = jobs?.find((j) => j.id === jobId)?.input ?? null;

  return (
    <>
      <PageHeader
        title="任務透視"
        description="Agent 每一步的輸入與輸出：流程節點、WebSocket 事件、JSON Prompt、注入參數、RAG Rerank、合規報告與重試 diff。"
        actions={
          jobs && jobs.length > 0 ? (
            <JobPicker jobs={jobs} value={jobId} onChange={(id) => router.replace(`/agent?job=${encodeURIComponent(id)}`)} />
          ) : null
        }
      />
      {jobId ? (
        <JobInspector key={jobId} jobId={jobId} input={input} />
      ) : (
        jobs && (
          <EmptyState icon={Network} title="還沒有任務">
            到<Link href="/studio" className="mx-1 font-medium text-primary hover:underline">新任務</Link>
            開始生成後，這裡會顯示 Agent 的每一步。
          </EmptyState>
        )
      )}
    </>
  );
}
```

- [ ] **Step 5: 修改 `web/src/app/agent/page.tsx`**

找到（1／2）：

```tsx
import { Suspense } from 'react';
import { AgentPreview } from '@/components/agent/agent-preview';
```

改成：

```tsx
import { Suspense } from 'react';
import { AgentInspector } from '@/components/agent/agent-inspector';
```

找到（2／2）：

```tsx
    <Suspense>
      <AgentPreview />
    </Suspense>
```

改成：

```tsx
    <Suspense>
      <AgentInspector />
    </Suspense>
```

- [ ] **Step 6: 刪除 `web/src/components/agent/agent-preview.tsx`**

```bash
git rm web/src/components/agent/agent-preview.tsx
```

- [ ] **Step 7: 驗證**

Run: `npm run typecheck && npm run lint`，再 `npm run dev`。到 `/studio` 開始生成，按「在 Agent 透視查看細節」。

Expected：
- typecheck 與 lint 無錯誤；測試仍是 36 個測試檔、272 個測試 PASS。
- 頁首顯示任務 id、目前階段、輪數、事件數與耗時，並有進度條。右上角可切換任務。
- 流程節點：
  - 8 個節點依序更新，執行中的節點有外框，ComfyUI 執行中時顯示「背景生成 12/28」之類的子步驟。
  - 重試的節點顯示「× 2」與累計耗時。
  - 合規審查標示「重試後通過」。
  - 下方 Query Rewriting 列顯示「1 次・… ms」與「並重新檢索 ③ 合規用語」。
- 事件串流：
  - 每列有序號、相對時間、事件類型與摘要，新事件進來時自動捲到底。
  - 可依分類篩選，預設隱藏 render.progress。
  - 2 個模板 × 4 張的任務共約 311 則；開發模式下也不會重複（Console 沒有 duplicate key 警告）。
- 重新整理頁面後，已結束的任務仍在任務選單中，內容相同。

- [ ] **Step 8: Commit**

```bash
git add web/src/components/agent web/src/app/agent
git commit -m "feat: replace agent preview with inspector, flow graph and event stream" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: `/agent` ②：JSON Prompt、注入參數、RAG Rerank

**Files:**
- Create（CLI 產生）：`web/src/components/ui/table.tsx`
- Create: `web/src/components/agent/{prompt-panel.tsx,rag-panel.tsx}`
- Modify: `web/src/lib/agent/diff.ts`、`web/src/components/agent/agent-inspector.tsx`
- Test: `web/src/lib/agent/diff.test.ts`（修改）

**Interfaces:**
- Consumes：`specOptions`、`injectionRows`、`rerankRows`（Task 5）
- Produces：
  - `inlineDiff(a, b): { prefix, removed, added, suffix }`：保留共同的前綴與後綴，只標出中間改變的部分
  - 元件 `PromptPanel`、`RagPanel`

- [ ] **Step 1: 加入 shadcn 的 table 元件**

```bash
npx -y shadcn@4.21.3 add table -y
```

Expected: 產生 `src/components/ui/table.tsx`，沒有新增套件

- [ ] **Step 2: 修改 `web/src/lib/agent/diff.test.ts`**（先寫失敗測試）

找到（1／2）：

```ts
import { makeSpec } from '@/test/fixtures';
import { diffSpecs } from './diff';
```

改成：

```ts
import { makeSpec } from '@/test/fixtures';
import { diffSpecs, inlineDiff } from './diff';
```

找到（2／2）：

```ts
  });
});
```

改成：

```ts
  });
});

describe('inlineDiff', () => {
  it('keeps the common prefix and suffix and isolates the change', () => {
    expect(inlineDiff('lowres, blurry', 'lowres, blurry, neon')).toEqual({ prefix: 'lowres, blurry', removed: '', added: ', neon', suffix: '' });
    expect(inlineDiff('[["logo",101,38,374]]', '[["logo",101,90,374]]')).toEqual({
      prefix: '[["logo",101,', removed: '38', added: '90', suffix: ',374]]',
    });
  });

  it('does not let the prefix and suffix overlap', () => {
    expect(inlineDiff('aa', 'aaa')).toEqual({ prefix: 'aa', removed: '', added: 'a', suffix: '' });
    expect(inlineDiff('same', 'same')).toEqual({ prefix: 'same', removed: '', added: '', suffix: '' });
  });
});
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `npx vitest run src/lib/agent/diff.test.ts`
Expected: FAIL，2 個 `inlineDiff` 測試失敗：`inlineDiff is not a function`

- [ ] **Step 4: 修改 `web/src/lib/agent/diff.ts`**

找到：

```ts
  return rows.filter(([, x, y]) => x !== y).map(([path, before, after]) => ({ path, before, after }));
}
```

改成：

```ts
  return rows.filter(([, x, y]) => x !== y).map(([path, before, after]) => ({ path, before, after }));
}

export interface InlineDiff { prefix: string; removed: string; added: string; suffix: string }

/** 兩段文字只標出中間改變的部分（共同的前綴與後綴原樣保留）；注入參數對照使用 */
export function inlineDiff(a: string, b: string): InlineDiff {
  let p = 0;
  while (p < a.length && p < b.length && a[p] === b[p]) p++;
  let s = 0;
  while (s < a.length - p && s < b.length - p && a[a.length - 1 - s] === b[b.length - 1 - s]) s++;
  return { prefix: a.slice(0, p), removed: a.slice(p, a.length - s), added: b.slice(p, b.length - s), suffix: a.slice(a.length - s) };
}
```

- [ ] **Step 5: 建立 `web/src/components/agent/prompt-panel.tsx`**

```tsx
'use client';

import { useState } from 'react';
import { Copy } from 'lucide-react';
import { toast } from 'sonner';
import { EmptyState } from '@/components/common/empty-state';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { inlineDiff } from '@/lib/agent/diff';
import { injectionRows, specOptions, type InjectionRow } from '@/lib/agent/inspect';
import { getTemplate } from '@/lib/compose/templates';
import type { JobView } from '@/lib/jobs/view';
import { cn } from '@/lib/utils';

const CONTEXT = 24;

/** 改寫後的值：短的值顯示「舊 → 新」，長的文字只標出改變的片段 */
function ChangedValue({ row }: { row: InjectionRow }) {
  const before = String(row.previous ?? '');
  const after = String(row.value);
  if (after.length <= 40) {
    return (
      <>
        <span className="text-muted-foreground line-through">{before}</span> → <span className="font-semibold text-emerald-700">{after}</span>
      </>
    );
  }
  const d = inlineDiff(before, after);
  return (
    <>
      <span className="text-muted-foreground">{d.prefix.length > CONTEXT ? `…${d.prefix.slice(-CONTEXT)}` : d.prefix}</span>
      {d.removed && <del className="bg-red-100 text-red-700">{d.removed}</del>}
      {d.added && <ins className="bg-emerald-100 text-emerald-800 no-underline">{d.added}</ins>}
      <span className="text-muted-foreground">{d.suffix.length > CONTEXT ? `${d.suffix.slice(0, CONTEXT)}…` : d.suffix}</span>
    </>
  );
}

/** JSON Prompt 與 workflow_api.json 注入參數；與同模板上一輪比較，標出改寫後變動的參數 */
export function PromptPanel({ view }: { view: JobView }) {
  const options = specOptions(view);
  const [picked, setPicked] = useState<string | null>(null);
  // 預設看最新一輪，重試時可直接看到改寫後的參數
  const key = picked && view.specs[picked] ? picked : (options.at(-1)?.key ?? null);
  if (!key) {
    return <EmptyState icon={Copy} title="尚未產生 Prompt">Prompt 構建完成後，這裡會顯示每個模板每一輪的 JSON Prompt。</EmptyState>;
  }
  const spec = view.specs[key];
  const rows = injectionRows(view, key);
  const json = JSON.stringify(spec, null, 2);
  const changed = rows.filter((r) => r.changed).length;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(json);
      toast.success('已複製 JSON Prompt');
    } catch {
      toast.error('無法存取剪貼簿');
    }
  };

  return (
    <div className="space-y-4">
      <Select value={key} onValueChange={setPicked}>
        <SelectTrigger className="w-full bg-card sm:w-72" aria-label="選擇 Prompt">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o.key} value={o.key}>
              第 {o.round} 輪・{getTemplate(o.templateId).label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <div className="grid items-start gap-4 xl:grid-cols-2">
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>JSON Prompt</CardTitle>
            <CardDescription>LLM 產生的完整規格：文案、色票、版面 BBox、正負向提示詞與 RAG 引用。</CardDescription>
            <CardAction>
              <Button size="sm" variant="outline" onClick={() => void copy()}>
                <Copy />
                複製
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent>
            <pre className="max-h-[60vh] overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-xs leading-relaxed text-slate-200">
              {json}
            </pre>
          </CardContent>
        </Card>
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>workflow_api.json 注入參數</CardTitle>
            <CardDescription>
              {spec.injection.workflowFile}・{rows.length} 個參數
              {spec.round > 1 && `・與第 ${spec.round - 1} 輪相比改了 ${changed} 個`}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>節點</TableHead>
                  <TableHead>參數</TableHead>
                  <TableHead>值</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={`${r.nodeId}.${r.input}`} className={cn(r.changed && 'bg-amber-50 hover:bg-amber-50')}>
                    <TableCell className="align-top font-mono text-xs text-muted-foreground">
                      {r.nodeId}.{r.input}
                    </TableCell>
                    <TableCell className="align-top">
                      <span className="font-mono text-xs">{r.label}</span>
                      {r.changed && <Badge variant="outline" className="ml-1.5 border-amber-300 text-amber-800">已改寫</Badge>}
                    </TableCell>
                    <TableCell className="max-w-[28rem] font-mono text-xs break-all whitespace-normal" title={String(r.value)}>
                      {r.changed ? <ChangedValue row={r} /> : <span className="line-clamp-3">{String(r.value)}</span>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: 建立 `web/src/components/agent/rag-panel.tsx`**

```tsx
import { ArrowDown, ArrowUp, Search } from 'lucide-react';
import type { JobMessage } from '@/types/contract';
import { EmptyState } from '@/components/common/empty-state';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { rerankRows } from '@/lib/agent/inspect';
import type { JobView } from '@/lib/jobs/view';

function ScoreBar({ value, className }: { value: number | null; className: string }) {
  if (value === null) return <span className="text-muted-foreground">—</span>;
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
        <div className={className} style={{ width: `${Math.round(value * 100)}%`, height: '100%' }} />
      </div>
      <span className="font-mono text-xs">{value.toFixed(3)}</span>
    </div>
  );
}

function RankShift({ from, to }: { from: number; to: number | null }) {
  if (to === null || to === from) return <span className="text-muted-foreground">—</span>;
  const up = to < from;
  return (
    <span className={up ? 'inline-flex items-center text-emerald-600' : 'inline-flex items-center text-muted-foreground'}>
      {up ? <ArrowUp className="size-3.5" /> : <ArrowDown className="size-3.5" />}
      {Math.abs(from - to)}
    </span>
  );
}

/** RAG 召回與 Rerank：向量分數與 Rerank 分數、排名變化，以及哪些未通過的檢查引用了這段規範 */
export function RagPanel({ view, messages }: { view: JobView; messages: JobMessage[] }) {
  const rows = rerankRows(view);
  const queries = messages.flatMap((m) => (m.type === 'rag.retrieved' ? [m.query] : []));
  const checkName = new Map(view.renderIds.flatMap((id) => view.renders[id].checks.map((c) => [c.id, c.name] as const)));
  if (!rows.length) {
    return <EmptyState icon={Search} title="尚未檢索">RAG 檢索完成後，這裡會比較向量召回與 Rerank 後的排序。</EmptyState>;
  }
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Chroma 召回 → BGE Rerank</CardTitle>
          <CardDescription>查詢：{queries[0]}</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Rerank</TableHead>
                <TableHead>向量排名</TableHead>
                <TableHead>規範</TableHead>
                <TableHead>向量分數</TableHead>
                <TableHead>Rerank 分數</TableHead>
                <TableHead>被未通過的檢查引用</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.chunkId}>
                  <TableCell className="font-mono font-semibold">{r.rerankRank ?? '—'}</TableCell>
                  <TableCell>
                    <span className="mr-1.5 font-mono">{r.vectorRank}</span>
                    <RankShift from={r.vectorRank} to={r.rerankRank} />
                  </TableCell>
                  <TableCell className="max-w-[22rem] whitespace-normal">
                    <div className="flex items-center gap-1.5">
                      <Badge variant="secondary">{r.tag}</Badge>
                      <span className="text-sm font-medium">{r.section}</span>
                    </div>
                    <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground" title={r.text}>
                      {r.source}・{r.text}
                    </p>
                  </TableCell>
                  <TableCell><ScoreBar value={r.vectorScore} className="bg-slate-400" /></TableCell>
                  <TableCell><ScoreBar value={r.rerankScore} className="bg-primary" /></TableCell>
                  <TableCell className="whitespace-normal">
                    <div className="flex flex-wrap gap-1">
                      {r.citedBy.length
                        ? r.citedBy.map((id) => <Badge key={id} variant="outline" className="border-red-200 text-red-700">{checkName.get(id) ?? id}</Badge>)
                        : <span className="text-muted-foreground">—</span>}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      {view.requeryHits.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Query Rewriting 重新檢索</CardTitle>
            <CardDescription>查詢：{queries.slice(1).join('；')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {view.requeryHits.map((h) => (
              <div key={h.chunkId} className="rounded-lg border p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="secondary">{h.tag}</Badge>
                  <span className="font-medium">{h.section}</span>
                  <span className="ml-auto font-mono text-xs text-muted-foreground">
                    向量 {h.vectorScore.toFixed(3)}・Rerank {(h.rerankScore ?? 0).toFixed(3)}
                  </span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{h.source}・{h.text}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
```

- [ ] **Step 7: 修改 `web/src/components/agent/agent-inspector.tsx`**

找到（1／3）：

```tsx
import { FlowGraph } from './flow-graph';
import { useJobStream } from './use-job-stream';
```

改成：

```tsx
import { FlowGraph } from './flow-graph';
import { PromptPanel } from './prompt-panel';
import { RagPanel } from './rag-panel';
import { useJobStream } from './use-job-stream';
```

找到（2／3）：

```tsx
          <TabsTrigger value="events">事件串流</TabsTrigger>
        </TabsList>
```

改成：

```tsx
          <TabsTrigger value="events">事件串流</TabsTrigger>
          <TabsTrigger value="prompt">Prompt 與注入參數</TabsTrigger>
          <TabsTrigger value="rag">RAG Rerank</TabsTrigger>
        </TabsList>
```

找到（3／3）：

```tsx
          <EventStream messages={messages} />
        </TabsContent>
```

改成：

```tsx
          <EventStream messages={messages} />
        </TabsContent>
        <TabsContent value="prompt">
          <PromptPanel view={view} />
        </TabsContent>
        <TabsContent value="rag">
          <RagPanel view={view} messages={messages} />
        </TabsContent>
```

- [ ] **Step 8: 驗證**

Run: `npm run test && npm run typecheck && npm run lint`，再 `npm run dev` 開啟一個重試過的任務。

Expected：
- `diff.test.ts` 5 個測試 PASS；全部 36 個測試檔、274 個測試 PASS；typecheck 與 lint 無錯誤。
- 「Prompt 與注入參數」分頁：
  - 預設顯示最新一輪，可切換「第 1 輪・IG 貼文」等選項。
  - 左邊是完整的 JSON Prompt，可複製。
  - 右邊是 `workflows/product_scene_v1.json` 的 15 個參數。第 2 輪標示「與第 1 輪相比改了 4 個」：
    - positive_prompt：刪掉「, vivid saturated colors」。
    - negative_prompt：加上「oversaturated, neon, off-brand colors…」。
    - seed：舊 → 新。
    - layout_boxes：只標出 Logo 的 y 座標。
- 「RAG Rerank」分頁：
  - 依 Rerank 順序列出 color、law、logo、layout、history，並顯示向量排名與升降箭頭（例如 law 從 5 升到 2）。
  - 每列有兩種分數的長條。
  - 「被未通過的檢查引用」欄：color 為品牌主色色差；law 為禁用詞檢查、效果宣稱註記、誇大／療效用語。
  - 下方是 Query Rewriting 重新檢索到的「合規替代用語對照」。

- [ ] **Step 9: Commit**

```bash
git add web/src/components/ui/table.tsx web/src/lib/agent web/src/components/agent
git commit -m "feat: add prompt, injection and rerank panels to the agent inspector" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: `/agent` ③：合規報告與 BBox 疊圖、重試 diff

**Files:**
- Create: `web/src/components/agent/{review-panel.tsx,retry-panel.tsx}`
- Modify: `web/src/components/agent/agent-inspector.tsx`

**Interfaces:**
- Consumes：`overlayFor`、`retryDiffs`（Task 5）；`PosterCanvas`、`CheckList`、`ScoreBadge`（Plan 2）；`listProducts`
- Produces：元件 `ReviewPanel`、`RetryPanel`；分頁「合規報告」「重試 diff（N）」

- [ ] **Step 1: 建立 `web/src/components/agent/review-panel.tsx`**

```tsx
'use client';

import { useEffect, useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import type { CheckStatus, JobInput, Product, Render } from '@/types/contract';
import { EmptyState } from '@/components/common/empty-state';
import { CheckList } from '@/components/poster/check-list';
import { PosterCanvas } from '@/components/poster/poster-canvas';
import { ScoreBadge } from '@/components/poster/score-badge';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { getApiClient } from '@/lib/api';
import { overlayFor } from '@/lib/agent/inspect';
import { getTemplate } from '@/lib/compose/templates';
import type { JobView } from '@/lib/jobs/view';
import { useAppStore } from '@/lib/store/app';

const STATUS_COLOR: Record<CheckStatus | 'none', string> = { fail: '#dc2626', warn: '#d97706', pass: '#059669', none: '#64748b' };
const LEGEND: [CheckStatus | 'none', string][] = [['fail', '未通過'], ['warn', '警告'], ['pass', '通過'], ['none', '無檢查']];

/** 海報上疊出版面 BBox，依指向該元素的檢查結果上色 */
function BBoxOverlay({ render }: { render: Render }) {
  const { width: W, height: H } = render.spec.canvas;
  const overlay = overlayFor(render);
  const canvasIssue = overlay.canvas.status === 'fail' || overlay.canvas.status === 'warn';
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="pointer-events-none absolute inset-0 size-full" aria-hidden>
      {canvasIssue && (
        <rect x={0} y={0} width={W} height={H} fill="none" stroke={STATUS_COLOR[overlay.canvas.status!]} strokeWidth={W * 0.012} />
      )}
      {overlay.boxes.map((b) => {
        const [x, y, w, h] = b.bbox;
        const color = STATUS_COLOR[b.status ?? 'none'];
        const bad = b.status === 'fail' || b.status === 'warn';
        const size = W * 0.022;
        return (
          <g key={b.id}>
            <rect
              x={x} y={y} width={w} height={h} fill={color} fillOpacity={bad ? 0.14 : 0} stroke={color} strokeWidth={W * 0.004}
              strokeDasharray={b.status ? undefined : `${W * 0.01} ${W * 0.008}`}
            />
            <text
              x={x + size * 0.3} y={y + size * 1.05} fontSize={size} fontWeight={700} fill={color}
              stroke="#fff" strokeWidth={size * 0.18} paintOrder="stroke"
            >
              {b.id}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** 依任務的品牌讀取商品（換品牌或商品已刪除時為 null） */
function useProduct(brandId: string, productId: string | null): Product | null {
  const [product, setProduct] = useState<Product | null>(null);
  useEffect(() => {
    if (!productId) return;
    let alive = true;
    void getApiClient().listProducts(brandId).then((list) => {
      if (alive) setProduct(list.find((p) => p.id === productId) ?? null);
    });
    return () => {
      alive = false;
    };
  }, [brandId, productId]);
  return product;
}

/** 合規報告：選一張候選，看 BBox 疊圖與 10 項檢查 */
export function ReviewPanel({ view, input }: { view: JobView; input: JobInput | null }) {
  const reviewed = view.renderIds.map((id) => view.renders[id]).filter((r) => r.score !== null);
  const [picked, setPicked] = useState<string | null>(null);
  const [showBoxes, setShowBoxes] = useState(true);
  const fallback = Object.values(view.bestRenderIds)[0] ?? reviewed.at(-1)?.id ?? null;
  const render = (picked && view.renders[picked]) || (fallback ? view.renders[fallback] : null);
  const brandId = render?.spec.brandId ?? input?.brandId ?? '';
  const brand = useAppStore((s) => s.brands.find((b) => b.id === brandId));
  const product = useProduct(brandId, input?.productId ?? null);

  if (!render || !brand) {
    return <EmptyState icon={ShieldCheck} title="尚未審查">候選完成合規審查後，這裡會顯示 BBox 疊圖與每一項檢查。</EmptyState>;
  }
  const best = Object.values(view.bestRenderIds).includes(render.id);

  return (
    <div className="space-y-4">
      <Select value={render.id} onValueChange={setPicked}>
        <SelectTrigger className="w-full bg-card sm:w-96" aria-label="選擇候選">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {reviewed.map((r) => (
            <SelectItem key={r.id} value={r.id}>
              第 {r.round} 輪・{getTemplate(r.templateId).label}・#{r.variant + 1}
              <span className={r.passed ? 'text-xs text-success' : 'text-xs text-destructive'}>{r.score} 分</span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>BBox 疊圖</CardTitle>
            <CardDescription>LLM 輸出的版面座標；顏色依指向該元素的檢查結果，外框代表整張圖的檢查（主色色差）。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="relative overflow-hidden rounded-lg border">
              <PosterCanvas render={render} copy={render.spec.copy} product={product} brand={brand} pixelWidth={720} />
              {showBoxes && <BBoxOverlay render={render} />}
            </div>
            <div className="flex flex-wrap items-center gap-3 text-xs">
              {LEGEND.map(([status, label]) => (
                <span key={status} className="inline-flex items-center gap-1.5">
                  <span className="size-3 rounded-sm border-2" style={{ borderColor: STATUS_COLOR[status] }} />
                  {label}
                </span>
              ))}
              <div className="ml-auto flex items-center gap-2">
                <Switch id="show-bbox" checked={showBoxes} onCheckedChange={setShowBoxes} />
                <Label htmlFor="show-bbox" className="font-normal">顯示 BBox</Label>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2">
              合規報告
              <ScoreBadge render={render} />
              {best && <Badge>最佳候選</Badge>}
            </CardTitle>
            <CardDescription>規則 7 項（禁用詞、ΔE2000、Logo 淨空區…）+ VLM 3 項；附上引用的 RAG 規範。</CardDescription>
          </CardHeader>
          <CardContent>
            <CheckList checks={render.checks} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 建立 `web/src/components/agent/retry-panel.tsx`**

```tsx
import { ArrowRight, GitCompareArrows } from 'lucide-react';
import { EmptyState } from '@/components/common/empty-state';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { retryDiffs } from '@/lib/agent/inspect';
import { getTemplate } from '@/lib/compose/templates';
import type { JobView } from '@/lib/jobs/view';

/** 重試 diff：每次 Query Rewriting 的原因、修正策略，以及改寫前後 Prompt 的差異 */
export function RetryPanel({ view }: { view: JobView }) {
  const diffs = retryDiffs(view);
  const checkName = new Map(view.renderIds.flatMap((id) => view.renders[id].checks.map((c) => [c.id, c.name] as const)));
  if (!diffs.length) {
    return (
      <EmptyState icon={GitCompareArrows} title={view.outcome === 'running' ? '尚未觸發重試' : '沒有重試'}>
        {view.outcome === 'running' ? '審查未通過時，這裡會顯示改寫前後的差異。' : '所有模板第一輪就通過了合規審查。'}
      </EmptyState>
    );
  }
  return (
    <div className="space-y-4">
      {diffs.map((d) => (
        <Card key={`${d.round}:${d.templateId}`}>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2">
              第 {d.round} 輪 → 第 {d.round + 1} 輪・{getTemplate(d.templateId).label}
              {d.scoreBefore !== null && (
                <Badge variant="outline" className="font-mono">
                  {d.scoreBefore} 分 <ArrowRight /> {d.scoreAfter ?? '…'} 分
                </Badge>
              )}
            </CardTitle>
            <CardDescription className="flex flex-wrap items-center gap-1">
              未通過：
              {d.reasons.map((id) => (
                <Badge key={id} variant="outline" className="border-red-200 text-red-700">{checkName.get(id) ?? id}</Badge>
              ))}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <ul className="grid gap-2 sm:grid-cols-2">
              {d.fixes.map((f) => (
                <li key={f.title} className="rounded-lg border bg-muted/40 p-3 text-sm">
                  <p className="font-semibold">{f.title}</p>
                  <p className="text-xs text-muted-foreground">{f.desc}</p>
                </li>
              ))}
            </ul>
            {d.requery && view.requeryHits.length > 0 && (
              <p className="text-sm text-muted-foreground">
                重新檢索：{view.requeryHits.map((h) => `${h.section}（${h.chunkId}）`).join('、')}
              </p>
            )}
            {d.diffs.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>欄位</TableHead>
                    <TableHead>改寫前</TableHead>
                    <TableHead>改寫後</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.diffs.map((x) => (
                    <TableRow key={x.path}>
                      <TableCell className="align-top font-mono text-xs">{x.path}</TableCell>
                      <TableCell className="max-w-[20rem] align-top text-xs break-all whitespace-normal text-red-700 line-through decoration-red-300">
                        {x.before}
                      </TableCell>
                      <TableCell className="max-w-[20rem] align-top text-xs break-all whitespace-normal text-emerald-700">{x.after}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className="text-sm text-muted-foreground">改寫中，下一輪的 Prompt 產生後會顯示差異。</p>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: 修改 `web/src/components/agent/agent-inspector.tsx`**

找到（1／4）：

```tsx
import { RagPanel } from './rag-panel';
import { useJobStream } from './use-job-stream';
```

改成：

```tsx
import { RagPanel } from './rag-panel';
import { RetryPanel } from './retry-panel';
import { ReviewPanel } from './review-panel';
import { useJobStream } from './use-job-stream';
```

找到（2／4）：

```tsx
      <Tabs defaultValue="events">
        <TabsList className="h-auto flex-wrap">
          <TabsTrigger value="events">事件串流</TabsTrigger>
```

改成：

```tsx
      <Tabs defaultValue="events">
        {/* line 樣式：主題的 background 與 muted 顏色接近，預設樣式看不出目前分頁 */}
        <TabsList variant="line" className="h-auto flex-wrap">
          <TabsTrigger value="events">事件串流</TabsTrigger>
```

找到（3／4）：

```tsx
          <TabsTrigger value="rag">RAG Rerank</TabsTrigger>
        </TabsList>
```

改成：

```tsx
          <TabsTrigger value="rag">RAG Rerank</TabsTrigger>
          <TabsTrigger value="review">合規報告</TabsTrigger>
          <TabsTrigger value="retry">重試 diff{view.rewrites.length > 0 && `（${view.rewrites.length}）`}</TabsTrigger>
        </TabsList>
```

找到（4／4）：

```tsx
          <RagPanel view={view} messages={messages} />
        </TabsContent>
```

改成：

```tsx
          <RagPanel view={view} messages={messages} />
        </TabsContent>
        <TabsContent value="review">
          <ReviewPanel view={view} input={input} />
        </TabsContent>
        <TabsContent value="retry">
          <RetryPanel view={view} />
        </TabsContent>
```

- [ ] **Step 4: 驗證**

Run: `npm run typecheck && npm run lint`，再 `npm run dev` 開啟一個 2 個模板的重試任務。

Expected：
- 「合規報告」分頁：
  - 預設顯示最佳候選，標示「最佳候選」。
  - 候選選單列出每一輪每一張的分數，第 1 輪約 20 分、第 2 輪 90 分以上。
  - 切到第 1 輪的候選時，BBox 疊圖與檢查結果一致：
    - 整張圖有紅色外框（主色色差）。
    - logo 框為紅色且與標題重疊（Logo 淨空區、物件與文字遮擋）。
    - subhead 為紅色（禁用詞）；disclaimer 為黃色（效果宣稱註記）。
    - 沒有檢查指向的元素為灰色虛線。
  - 右邊的 10 項檢查都附上引用的 RAG 規範。
  - 可關閉「顯示 BBox」。
- 「重試 diff（2）」分頁：每個模板一張卡片，例如「第 1 輪 → 第 2 輪・電商主圖　23 分 → 98 分」。
  - 未通過的檢查。
  - 修正策略：文案改寫、色彩修正、版面修正、補充註記、構圖修正。
  - 重新檢索的規範。
  - 差異表：palette.primary `#E0458A → #B76E79`、palette.secondary、layout[logo].bbox、copy.subhead、copy.disclaimer、negativePrompt。
- 第一輪就通過的任務顯示「沒有重試」。

- [ ] **Step 5: Commit**

```bash
git add web/src/components/agent
git commit -m "feat: add compliance overlay and retry diff panels" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: 成效儀表板 `/dashboard`

**Files:**
- Create（CLI 產生）：`web/src/components/ui/chart.tsx`
- Create: `web/src/components/dashboard/{kpi-cards.tsx,check-failure-chart.tsx,rerank-chart.tsx,recent-jobs.tsx}`
- Modify: `web/src/app/dashboard/page.tsx`（取代暫時頁面）

**Interfaces:**
- Consumes：`getDashboardStats`（Task 3）；`DemoControls.seedJobs`（Task 2）；`formatDuration`（Task 4）
- Produces：元件 `KpiCards`、`CheckFailureChart`、`RerankChart`、`RecentJobs`

- [ ] **Step 1: 加入 shadcn 的 chart 元件**

```bash
npx -y shadcn@4.21.3 add chart -y
```

Expected: 產生 `src/components/ui/chart.tsx`，`package.json` 加入 `recharts`（`^3.8.0`）

- [ ] **Step 2: 建立 `web/src/components/dashboard/kpi-cards.tsx`**

```tsx
import { CircleCheck, CircleDollarSign, RotateCcw, Timer } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { DashboardStats } from '@/types/contract';
import { Card, CardContent } from '@/components/ui/card';
import { formatDuration } from '@/lib/agent/events';

const pct = (v: number) => `${Math.round(v * 100)}%`;

function Kpi({ icon: Icon, label, value, note }: { icon: LucideIcon; label: string; value: string; note: string }) {
  return (
    <Card>
      <CardContent className="space-y-1">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Icon className="size-4" />
          {label}
        </div>
        <p className="text-2xl font-bold tracking-tight">{value}</p>
        <p className="text-xs text-muted-foreground">{note}</p>
      </CardContent>
    </Card>
  );
}

/** 通過率、平均重試次數、平均耗時、每張成本 */
export function KpiCards({ stats }: { stats: DashboardStats }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Kpi icon={CircleCheck} label="通過率" value={pct(stats.passRate)} note={`首輪就通過的模板 ${pct(stats.firstPassRate)}・共 ${stats.jobs} 個任務`} />
      <Kpi icon={RotateCcw} label="平均重試次數" value={`${stats.avgRetries.toFixed(1)} 輪`} note="審查未通過後 Query Rewriting 的輪數" />
      <Kpi icon={Timer} label="平均耗時" value={formatDuration(stats.avgDurationMs)} note={`從接收任務到回傳・共 ${stats.renders} 張候選`} />
      <Kpi
        icon={CircleDollarSign}
        label="每張成本"
        value={stats.costPerImage === null ? '—' : `US$ ${stats.costPerImage.toFixed(3)}`}
        note="估算：LLM、Rerank、生圖與 VLM 審查，攤到每張交付圖"
      />
    </div>
  );
}
```

- [ ] **Step 3: 建立 `web/src/components/dashboard/check-failure-chart.tsx`**

```tsx
'use client';

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts';
import type { CheckFailureStat } from '@/types/contract';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig } from '@/components/ui/chart';

const config = {
  fail: { label: '未通過', color: 'var(--destructive)' },
  warn: { label: '警告', color: 'var(--warning)' },
} satisfies ChartConfig;

/** 各檢查項的失敗分布（含所有輪次的候選） */
export function CheckFailureChart({ data }: { data: CheckFailureStat[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>各檢查項失敗分布</CardTitle>
        <CardDescription>所有輪次的候選；第一輪的問題會在 Query Rewriting 後修正。</CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={config} className="aspect-auto h-80 w-full">
          <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }}>
            <CartesianGrid horizontal={false} />
            <XAxis type="number" allowDecimals={false} tickLine={false} axisLine={false} />
            <YAxis type="category" dataKey="name" width={108} tickLine={false} axisLine={false} />
            <ChartTooltip cursor={false} content={<ChartTooltipContent />} />
            <ChartLegend content={<ChartLegendContent />} />
            <Bar dataKey="fail" stackId="n" fill="var(--color-fail)" radius={[0, 0, 0, 0]} />
            <Bar dataKey="warn" stackId="n" fill="var(--color-warn)" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 4: 建立 `web/src/components/dashboard/rerank-chart.tsx`**

```tsx
'use client';

import { CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts';
import type { RerankHitStat } from '@/types/contract';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig } from '@/components/ui/chart';

const config = {
  vector: { label: '向量召回', color: 'var(--chart-5)' },
  rerank: { label: 'BGE Rerank 後', color: 'var(--chart-1)' },
} satisfies ChartConfig;

const pct = (v: number) => `${Math.round(v * 100)}%`;

/** Rerank 對命中率的影響：前 k 筆檢索結果涵蓋「審查未通過項目所引用規範」的比例 */
export function RerankChart({ data }: { data: RerankHitStat[] }) {
  const k3 = data.find((d) => d.k === 3);
  const rows = data.map((d) => ({ k: `Top ${d.k}`, vector: Math.round(d.vector * 100), rerank: Math.round(d.rerank * 100) }));
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Rerank 對命中率的影響</CardTitle>
        <CardDescription>
          前 k 筆檢索結果涵蓋「審查未通過項目所引用規範」的比例
          {k3 && `；Top 3：${pct(k3.vector)} → ${pct(k3.rerank)}`}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={config} className="aspect-auto h-80 w-full">
          <LineChart data={rows} margin={{ left: 0, right: 16, top: 8 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="k" tickLine={false} axisLine={false} />
            <YAxis domain={[0, 100]} unit="%" width={44} tickLine={false} axisLine={false} />
            <ChartTooltip content={<ChartTooltipContent formatter={(v, name) => `${config[name as keyof typeof config]?.label ?? name}：${v}%`} />} />
            <ChartLegend content={<ChartLegendContent />} />
            <Line dataKey="vector" type="monotone" stroke="var(--color-vector)" strokeWidth={2} strokeDasharray="5 4" dot />
            <Line dataKey="rerank" type="monotone" stroke="var(--color-rerank)" strokeWidth={2.5} dot />
          </LineChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 5: 建立 `web/src/components/dashboard/recent-jobs.tsx`**

```tsx
import Link from 'next/link';
import type { JobStat } from '@/types/contract';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatDuration } from '@/lib/agent/events';
import { useAppStore } from '@/lib/store/app';

const time = (iso: string) =>
  new Date(iso).toLocaleString('zh-TW', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });

/** 最近的任務：每列可點進 Agent 透視 */
export function RecentJobs({ jobs }: { jobs: JobStat[] }) {
  const brands = useAppStore((s) => s.brands);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>最近的任務</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>任務</TableHead>
              <TableHead>品牌</TableHead>
              <TableHead>結果</TableHead>
              <TableHead className="text-right">輪數</TableHead>
              <TableHead className="text-right">交付／候選</TableHead>
              <TableHead className="text-right">耗時</TableHead>
              <TableHead className="text-right">成本</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {jobs.map((j) => (
              <TableRow key={j.jobId}>
                <TableCell>
                  <Link href={`/agent?job=${encodeURIComponent(j.jobId)}`} className="font-mono text-xs text-primary hover:underline">
                    {j.jobId}
                  </Link>
                  <div className="text-xs text-muted-foreground">{time(j.createdAt)}</div>
                </TableCell>
                <TableCell>{brands.find((b) => b.id === j.brandId)?.name ?? j.brandId}</TableCell>
                <TableCell>
                  {j.outcome === 'done'
                    ? <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-emerald-700">完成</Badge>
                    : <Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-800">需人工審核</Badge>}
                </TableCell>
                <TableCell className="text-right font-mono">{j.rounds}</TableCell>
                <TableCell className="text-right font-mono">{j.delivered}／{j.renders}</TableCell>
                <TableCell className="text-right font-mono">{formatDuration(j.durationMs)}</TableCell>
                <TableCell className="text-right font-mono">${j.costUsd.toFixed(3)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 6: 取代 `web/src/app/dashboard/page.tsx`**

```tsx
'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ChartColumn, FlaskConical, LoaderCircle } from 'lucide-react';
import type { DashboardStats } from '@/types/contract';
import { EmptyState } from '@/components/common/empty-state';
import { PageHeader } from '@/components/common/page-header';
import { CheckFailureChart } from '@/components/dashboard/check-failure-chart';
import { KpiCards } from '@/components/dashboard/kpi-cards';
import { RecentJobs } from '@/components/dashboard/recent-jobs';
import { RerankChart } from '@/components/dashboard/rerank-chart';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { API_MODE, getApiClient } from '@/lib/api';
import { useCurrentBrand } from '@/lib/store/app';

const SAMPLE_JOBS = 12;

export default function DashboardPage() {
  const brand = useCurrentBrand();
  const [scope, setScope] = useState<'brand' | 'all'>('brand');
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [seeding, setSeeding] = useState(false);
  // 產生示範任務後遞增，重新讀取統計
  const [version, setVersion] = useState(0);
  const brandId = scope === 'brand' ? brand.id : undefined;

  useEffect(() => {
    let alive = true;
    void getApiClient().getDashboardStats(brandId).then((s) => {
      if (alive) setStats(s);
    });
    return () => {
      alive = false;
    };
  }, [brandId, version]);

  const seed = async () => {
    const demo = getApiClient().demo;
    if (!demo) return;
    setSeeding(true);
    try {
      await demo.seedJobs(SAMPLE_JOBS);
      setVersion((v) => v + 1);
    } finally {
      setSeeding(false);
    }
  };

  const seedButton = API_MODE === 'mock' && (
    <Button variant="outline" disabled={seeding} onClick={() => void seed()}>
      {seeding ? <LoaderCircle className="animate-spin" /> : <FlaskConical />}
      產生 {SAMPLE_JOBS} 個示範任務
    </Button>
  );

  return (
    <>
      <PageHeader
        title="成效儀表板"
        description="依已結束任務的事件統計：通過率、平均重試次數、平均耗時、每張成本、各檢查項失敗分布，以及 Rerank 對命中率的影響。"
        actions={
          <>
            <Select value={scope} onValueChange={(v) => setScope(v as 'brand' | 'all')}>
              <SelectTrigger className="w-44 bg-card" aria-label="統計範圍">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="brand">{brand.name}</SelectItem>
                <SelectItem value="all">全部品牌</SelectItem>
              </SelectContent>
            </Select>
            {stats && stats.jobs > 0 && seedButton}
          </>
        }
      />
      {stats === null ? null : stats.jobs === 0 ? (
        <EmptyState icon={ChartColumn} title="還沒有已結束的任務">
          <p>
            到<Link href="/studio" className="mx-1 font-medium text-primary hover:underline">新任務</Link>或
            <Link href="/queue" className="mx-1 font-medium text-primary hover:underline">批次佇列</Link>
            執行幾個任務，或先產生示範任務（直接寫入任務紀錄，不播放）。
          </p>
          <div className="mt-4">{seedButton}</div>
        </EmptyState>
      ) : (
        <div className="space-y-5">
          <KpiCards stats={stats} />
          <div className="grid gap-5 xl:grid-cols-2">
            <CheckFailureChart data={stats.checkFailures} />
            <RerankChart data={stats.rerankHits} />
          </div>
          <RecentJobs jobs={stats.recent} />
        </div>
      )}
    </>
  );
}
```

- [ ] **Step 7: 驗證**

Run: `npm run typecheck && npm run lint && npm run build`，再 `npm run dev`，用清除過網站資料的瀏覽器開啟 `/dashboard`。

Expected：
- 三者都沒有錯誤；建置的路由表與 Plan 2 相同（`/dashboard` 仍是 ○ 靜態）。
- 沒有任務時，顯示「還沒有已結束的任務」與「產生 12 個示範任務」按鈕。
- 按下按鈕後 1 秒內出現資料（示範任務的結果固定，數字應與下列相同）。SÉLUNE 的資料：
  - KPI：通過率 83%（首輪就通過的模板 25%・共 6 個任務）、平均重試次數 0.8 輪、平均耗時 13.4 秒、每張成本 US$ 0.092。
  - 「各檢查項失敗分布」：橫向堆疊長條，禁用詞、主色色差、Logo 淨空區、誇大用語等為紅色（未通過），效果宣稱註記、遮擋、畫質為黃色（警告）。
  - 「Rerank 對命中率的影響」：兩條折線，Rerank 後的線在向量召回之上，說明文字為「Top 3：22% → 100%」。
  - 「最近的任務」：可點任務 id 進入 Agent 透視。
- 「統計範圍」切到「全部品牌」時，任務數變成 12，首輪通過率 31%、每張成本 US$ 0.130。
- 到 `/studio` 跑完一個任務後回到儀表板，任務數加 1。

- [ ] **Step 8: Commit**

```bash
git add web/package.json web/package-lock.json web/src/components/ui/chart.tsx web/src/components/dashboard web/src/app/dashboard
git commit -m "feat: add performance dashboard with recharts" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Playwright E2E

**Files:**
- Create: `web/playwright.config.ts`、`web/e2e/studio.spec.ts`、`web/e2e/dashboard.spec.ts`
- Modify: `web/package.json`（CLI）、`web/.gitignore`

**Interfaces:**
- Consumes：Plan 2 加上的 `aria-label`（一句話需求、模板 checkbox、Demo 控制台）；本計畫的 Agent 透視與儀表板
- Produces：`npm run e2e`

- [ ] **Step 1: 安裝 Playwright 與 Chromium，加入 `e2e` 指令**

```bash
npm i -D @playwright/test@^1.63.0
npm pkg set scripts.e2e="playwright test"
npx playwright install chromium
```

Expected: `package.json` 的 devDependencies 加入 `@playwright/test`，scripts 加入 `"e2e": "playwright test"`；瀏覽器下載到使用者目錄的 `ms-playwright`

- [ ] **Step 2: 修改 `web/.gitignore`**

找到：

```
/coverage
```

改成：

```
/coverage
/test-results/
/playwright-report/
/blob-report/
/playwright/.cache/
```

- [ ] **Step 3: 建立 `web/playwright.config.ts`**

```ts
import { defineConfig, devices } from '@playwright/test';

const PORT = 3100;

/**
 * E2E：先建置正式版，再在 3100 埠啟動（不佔用 next dev 的 3000 埠）。
 * 每個測試都是新的瀏覽器 context，IndexedDB 與 localStorage 從空的開始。
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  use: {
    baseURL: `http://localhost:${PORT}`,
    locale: 'zh-TW',
    timezoneId: 'Asia/Taipei',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npm run build && npm run start -- --port ${PORT}`,
    url: `http://localhost:${PORT}/studio`,
    reuseExistingServer: !process.env.CI,
    timeout: 240_000,
  },
});
```

- [ ] **Step 4: 建立 `web/e2e/studio.spec.ts`**

規格第 10 節的主流程：
1. 輸入一句話需求並生成。
2. 第一輪失敗並重試。
3. 選圖、修改價格。
4. 匯出 zip：檢查下載事件、zip 內的檔名與 PNG 尺寸。
5. 到 Agent 透視看重試 diff。

```ts
import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';
import JSZip from 'jszip';

test('一句話需求 → 生成 → 第一輪失敗並重試 → 選圖 → 改價格 → 匯出 zip → Agent 透視看重試 diff', async ({ page }) => {
  await page.goto('/studio');

  // Demo 控制台：4× 播放（預設強制首輪失敗）
  await page.getByRole('button', { name: '開啟 Demo 控制台' }).click();
  await page.getByRole('radio', { name: '4×' }).click();
  await page.keyboard.press('Escape');

  // 一句話需求 → Agent 拆解
  await page.getByLabel('一句話需求').fill('幫我做週年慶的精華液海報，主打買一送一，要溫柔療癒的感覺');
  await page.getByRole('button', { name: 'Agent 拆解需求' }).click();
  await expect(page.getByLabel('檔期')).toHaveValue('週年慶');
  await expect(page.getByLabel('優惠')).toHaveValue('買一送一');

  // 只留 IG 貼文
  await page.getByRole('checkbox', { name: '電商主圖' }).click();
  await expect(page.getByRole('checkbox', { name: 'IG 貼文' })).toBeChecked();
  await page.getByRole('button', { name: /開始生成（1 個模板/ }).click();

  // 第一輪未通過 → Query Rewriting → 第二輪通過
  await expect(page.getByText('第 1 輪未通過審查，Query Rewriting 後重試')).toBeVisible();
  await expect(page.getByText('文字編輯器', { exact: true })).toBeVisible();
  await expect(page.getByText('已重試')).toBeVisible();

  // 選另一張候選，再改價格
  await page.getByRole('button', { name: '選用', exact: true }).first().click();
  await page.getByLabel('特價').fill('999');
  await expect(page.getByLabel('特價')).toHaveValue('999');

  // 匯出 zip：檢查下載事件與 zip 內容
  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: /匯出 zip 並寫入歷史（1 張）/ }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toMatch(/^SÉLUNE晞月_極光玻尿酸修護精華30ml_\d{8}\.zip$/);
  const zip = await JSZip.loadAsync(await readFile(await download.path()));
  const names = Object.keys(zip.files);
  expect(names).toHaveLength(1);
  expect(names[0]).toMatch(/^SÉLUNE晞月_極光玻尿酸修護精華30ml_IG貼文_\d{8}\.png$/);
  const png = await zip.file(names[0])!.async('uint8array');
  // PNG 檔頭與 IHDR 中的寬高（IG 貼文 1440×1800）
  expect([...png.slice(1, 4)].map((c) => String.fromCharCode(c)).join('')).toBe('PNG');
  const view = new DataView(png.buffer, png.byteOffset);
  expect([view.getUint32(16), view.getUint32(20)]).toEqual([1440, 1800]);
  await expect(page.getByText('已匯出 1 張海報')).toBeVisible();

  // Agent 透視：重試 diff 顯示改寫前後的主色
  await page.getByRole('link', { name: '在 Agent 透視查看細節' }).click();
  await expect(page).toHaveURL(/\/agent\?job=job_/);
  await page.getByRole('tab', { name: /重試 diff/ }).click();
  const diff = page.getByRole('row', { name: /palette\.primary/ });
  await expect(diff).toContainText('#E0458A');
  await expect(diff).toContainText('#B76E79');
  await expect(page.getByText('第 1 輪 → 第 2 輪・IG 貼文')).toBeVisible();
});
```

- [ ] **Step 5: 建立 `web/e2e/dashboard.spec.ts`**

```ts
import { expect, test, type Page } from '@playwright/test';

async function seed(page: Page) {
  await page.goto('/dashboard');
  await expect(page.getByText('還沒有已結束的任務')).toBeVisible();
  await page.getByRole('button', { name: '產生 12 個示範任務' }).click();
  await expect(page.getByText('各檢查項失敗分布', { exact: true })).toBeVisible();
}

test('成效儀表板：示範任務的 KPI、圖表與最近任務，並可點進 Agent 透視', async ({ page }) => {
  await seed(page);
  await expect(page.getByText('共 6 個任務')).toBeVisible();
  await expect(page.getByText(/Top 3：\d+% → 100%/)).toBeVisible();
  await expect(page.locator('[data-chart] svg').first()).toBeVisible();

  await page.getByRole('combobox', { name: '統計範圍' }).click();
  await page.getByRole('option', { name: '全部品牌' }).click();
  await expect(page.getByText('共 12 個任務')).toBeVisible();
  await expect(page.getByText('需人工審核').first()).toBeVisible();

  await page.getByRole('link', { name: /^job_/ }).first().click();
  await expect(page).toHaveURL(/\/agent\?job=job_/);
  await expect(page.getByText('流程節點', { exact: true })).toBeVisible();
  await expect(page.getByText(/\d+ 則事件/)).toBeVisible();
});

test('手機寬度（375px）的 Agent 透視與儀表板沒有水平捲軸', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await seed(page);
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(await overflow()).toBeLessThanOrEqual(0);
  await page.goto('/agent');
  await expect(page.getByText('流程節點', { exact: true })).toBeVisible();
  expect(await overflow()).toBeLessThanOrEqual(0);
});
```

- [ ] **Step 6: 執行 E2E**

Run: `npm run e2e`
Expected：
- 先執行 `npm run build`，再在 3100 埠啟動正式版。
- 3 個測試 PASS（主流程約 7 秒，Demo 控制台設為 4×）。
- 結束後 3100 埠的伺服器自動關閉。
- 失敗時 `test-results/` 會留下 trace，可用 `npx playwright show-trace` 查看。

- [ ] **Step 7: 型別檢查與 lint**

Run: `npm run typecheck && npm run lint`
Expected: 無錯誤（`e2e/` 與 `playwright.config.ts` 也在檢查範圍內）

- [ ] **Step 8: Commit**

```bash
git add web/package.json web/package-lock.json web/.gitignore web/playwright.config.ts web/e2e
git commit -m "test: add playwright e2e for the main flow, agent inspector and dashboard" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: README 與全套驗收

**Files:**
- Modify: `web/README.md`

- [ ] **Step 1: 修改 `web/README.md`**

找到（1／7）：

```markdown
| `npm run test` | Vitest 單元測試 |
| `npm run typecheck` | 型別檢查（含路由型別） |
```

改成：

```markdown
| `npm run test` | Vitest 單元測試 |
| `npm run e2e` | Playwright E2E（自動建置並在 3100 埠啟動正式版；第一次要先執行 `npx playwright install chromium`） |
| `npm run typecheck` | 型別檢查（含路由型別） |
```

找到（2／7）：

```markdown
| 工作台 | `/brands` | 品牌知識庫：CI、禁用詞、RAG 切塊、上傳文件 |
| Agent 透視 | `/agent`、`/dashboard` | Plan 3 實作（目前為事件 Log 與預留頁） |
```

改成：

```markdown
| 工作台 | `/brands` | 品牌知識庫：CI、禁用詞、RAG 切塊、上傳文件 |
| Agent 透視 | `/agent` | 任務透視：流程節點、WebSocket 事件串流、JSON Prompt 與注入參數、RAG Rerank、合規報告與 BBox 疊圖、重試 diff |
| Agent 透視 | `/dashboard` | 成效儀表板：通過率、平均重試次數、平均耗時、每張成本、各檢查項失敗分布、Rerank 對命中率的影響 |
```

找到（3／7）：

```markdown

- 商品、歷史紀錄與上傳的品牌文件存在瀏覽器的 IndexedDB（資料庫 `genai-poster-agent`）；清除網站資料就會重置。
- 自己的商品照可放在 repo 根目錄的 `assets/products/`（已在 `.gitignore`，不會上傳 GitHub），開發模式下到「商品庫」一鍵匯入，檔名即商品名稱。
```

改成：

```markdown

- 商品、歷史紀錄、上傳的品牌文件，以及已結束的任務（最近 40 筆，含完整事件）存在瀏覽器的 IndexedDB（資料庫 `genai-poster-agent`）；清除網站資料就會重置。
- 每則事件都帶序號（`seq`）與時間戳（`ts`）。Agent 透視用來顯示事件串流與各節點耗時；儀表板依此統計耗時。
- 自己的商品照可放在 repo 根目錄的 `assets/products/`（已在 `.gitignore`，不會上傳 GitHub），開發模式下到「商品庫」一鍵匯入，檔名即商品名稱。
```

找到（4／7）：

```markdown

## 目錄
```

改成：

```markdown

成效儀表板可一鍵「產生 12 個示範任務」：直接算出完整事件（時間戳以 1× 計）並寫入任務紀錄，兩個品牌各有重試後通過、首輪通過與需人工審核的任務。每張成本是依 `lib/stats/dashboard.ts` 的單價估算。

## 目錄
```

找到（5／7）：

```markdown
├─ app/                 路由與 api/local-products（開發用）
├─ components/          ui（shadcn）、layout、studio、product、queue、history、brands、poster、agent
├─ lib/
│  ├─ api/              ApiClient 介面、mock/（MockApiClient、劇本、示範資料、IndexedDB）
│  ├─ agent/            Prompt 構建、修正策略、版本差異
│  ├─ compose/          版型、排版引擎（scene）、程序化素材（art）、Canvas 繪製（paint／render）
```

改成：

```markdown
├─ app/                 路由與 api/local-products（開發用）
├─ components/          ui（shadcn）、layout、studio、product、queue、history、brands、poster、agent、dashboard
├─ lib/
│  ├─ api/              ApiClient 介面、mock/（MockApiClient、劇本、示範資料與示範任務、IndexedDB）
│  ├─ agent/            Prompt 構建、修正策略、版本差異、流程節點狀態、事件摘要、透視用的資料整理
│  ├─ compose/          版型、排版引擎（scene）、程序化素材（art）、Canvas 繪製（paint／render）
```

找到（6／7）：

```markdown
│  ├─ jobs/             事件 → 畫面狀態（reducer）
│  ├─ export/           檔名、zip、下載
```

改成：

```markdown
│  ├─ jobs/             事件 → 畫面狀態（reducer）
│  ├─ stats/            成效儀表板統計與成本估算
│  ├─ export/           檔名、zip、下載
```

找到（7／7）：

````markdown
└─ types/contract.ts    前後端資料約定
```
````

改成：

````markdown
└─ types/contract.ts    前後端資料約定
e2e/                    Playwright：主流程（含匯出 zip）、Agent 透視重試 diff、儀表板、手機寬度
```
````

- [ ] **Step 2: 全套驗證**

Run: `npm run test && npm run typecheck && npm run lint && npm run build && npm run e2e`
Expected：
- 36 個測試檔、274 個測試 PASS。
- typecheck 與 lint 無錯誤。
- 建置成功。
- E2E 3 個測試 PASS。

- [ ] **Step 3: 依規格第 5 節手動走一次 Agent 透視**

用全新的瀏覽器設定檔（或先清除 localhost 的網站資料）執行 `npm run dev`：

1. `/studio`：SÉLUNE，勾電商主圖與 IG 貼文，開始生成，立刻按「在 Agent 透視查看細節」。
2. 確認流程節點與事件串流即時更新，第 1 輪審查後出現 Query Rewriting，再回到 Prompt 構建。
3. 依序檢查 Prompt 與注入參數、RAG Rerank、合規報告（切到第 1 輪的候選看 BBox 疊圖）、重試 diff 四個分頁。
4. 重新整理頁面，任務仍在，內容相同。
5. `/dashboard` 產生示範任務，切換統計範圍，點最近任務進入 Agent 透視。
6. 切換到霧嶼咖啡重複步驟 1–3，主色差異應為 `#1E88E5 → #2F4A44`。
7. 寬度 375px 時 `/agent` 與 `/dashboard` 沒有水平捲軸；瀏覽器 Console 沒有錯誤。

- [ ] **Step 4: Commit**

```bash
git add web/README.md
git commit -m "docs: describe the agent inspector, dashboard and e2e in the web README" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 第一階段完成後（留給第二階段）

本計畫完成後，規格第 2 節「本階段範圍」全部完成。以下留給第二階段：

| 項目 | 說明 |
|---|---|
| `HttpApiClient` 與 FastAPI | 實作同一個 `ApiClient` 介面，`NEXT_PUBLIC_API_MODE=live` 時使用 |
| WebSocket 重新連線 | 記住最後收到的 `seq`，重新連線後只補送之後的事件；`useJobStream` 已依 `seq` 去除重複 |
| 任務紀錄與統計 | 改存後端資料庫；執行中的任務重新整理後也能接續；`getDashboardStats` 由後端計算 |
| 實際成本 | 後端回報 LLM token、GPU 秒數與 API 用量，取代 `UNIT_COST_USD` 的估算 |
| Chroma、BGE Reranker、ComfyUI、VLM 真實串接與 Docker Compose | 規格第 1、2 節 |
| 規格第 11 節的待決事項 | GPU 規格、模型授權、正式品牌 CI 資料 |
