# Plan 1：基礎與核心邏輯 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 Next.js 專案骨架，並完成前端所需的全部核心邏輯（資料約定、ΔE2000、版型引擎、合規規則、示範資料、模擬 Agent 流程與 `MockApiClient`），全部以 Vitest 驗證。

**Architecture:** 所有邏輯都是 `web/src/lib/**` 下的純 TypeScript 函式（不依賴 React／DOM）。`types/contract.ts` 是前後端唯一的資料約定。模擬流程先由 `buildTimeline` 產生「帶時間戳的事件清單」，再由 `playTimeline` 依播放速度送出；`MockApiClient` 實作 `ApiClient` 介面，UI（Plan 2）只依賴這個介面。

**Tech Stack:** Next.js（App Router）、TypeScript strict、Vitest、vite-tsconfig-paths

**Spec:** `docs/superpowers/specs/2026-10-05-genai-poster-agent-frontend-design.md`

**Plan series:** 本文件是 3 份計畫中的第 1 份。Plan 2（工作台 UI）與 Plan 3（Agent 透視、儀表板、E2E）在本計畫完成後撰寫。

## Global Constraints

- 前端程式碼全部在 `web/`；除非另外註明，指令都在 `web/` 目錄執行
- 環境：Node 24、npm 11、Windows + Git Bash
- TypeScript strict；路徑別名 `@/*` → `web/src/*`
- 資料型別只定義在 `web/src/types/contract.ts`，其他檔案一律 import，不得重複定義
- `web/src/lib/**` 在本計畫內必須是純 TypeScript：不 import React、不使用 `window`／`document`
- 不得建立 `web/src/lib/utils/` 資料夾（shadcn/ui 會在 Plan 2 建立 `web/src/lib/utils.ts`）；共用工具放 `web/src/lib/core/`
- 不發出任何網路請求；`NEXT_PUBLIC_API_MODE` 預設 `mock`
- UI 文字與使用者可見字串用繁體中文；程式識別字用英文
- 示範品牌皆為虛構：SÉLUNE 晞月（美妝）、霧嶼咖啡 MISTY ISLE（冷萃咖啡）
- 模擬時間軸（1× 速度）：含一次重試總長 **14,500 ms**；不重試 **8,200 ms**
- 每個 Task 結束都要 commit，訊息最後一行加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

## File Structure

| 檔案 | 責任 |
|---|---|
| `web/vitest.config.mts` | Vitest 設定（node 環境、路徑別名） |
| `web/.env.example` | `NEXT_PUBLIC_API_MODE=mock` |
| `web/src/lib/core/num.ts` | `round1`、`clamp`、`mulberry32`、`hashString` |
| `web/src/lib/core/text.ts` | `visLen`（估算字寬）、`truncate` |
| `web/src/lib/core/geometry.ts` | BBox 交集、重疊比例、面積比例、垂直間距 |
| `web/src/types/contract.ts` | 前後端資料約定（型別 + 常數陣列） |
| `web/src/lib/review/color.ts` | hex↔RGB、sRGB→Lab、ΔE2000、混色 |
| `web/src/lib/compose/templates.ts` | 5 個通路模板 |
| `web/src/lib/compose/layout.ts` | 各模板版型預設、`computeLayout`、`fitFontSize` |
| `web/src/lib/api/mock/data/brands.ts` | 兩個示範品牌（CI、禁用詞、RAG 切塊、文案預設） |
| `web/src/lib/api/mock/data/products.ts` | 示範商品 |
| `web/src/lib/api/mock/data/index.ts` | `BRANDS`、`getBrandById` |
| `web/src/lib/review/rules.ts` | 規則型審查（禁用詞、ΔE、Logo 淨空區、註記、佔比、留白、OCR）與計分 |
| `web/src/test/fixtures.ts` | 測試用 `makeSpec` |
| `web/src/lib/api/mock/brief.ts` | 模擬 Agent 需求拆解 `parseBrief` |
| `web/src/lib/agent/prompt.ts` | `buildCopy`、`makeBadge`、`buildPromptSpec`（含 ComfyUI 注入參數） |
| `web/src/lib/agent/fixes.ts` | `planFixes`：審查失敗 → 修正策略 |
| `web/src/lib/agent/diff.ts` | `diffSpecs`：兩版 Prompt 的差異 |
| `web/src/lib/api/mock/flaws.ts` | 第一輪「故意失誤」`applyFlaws` |
| `web/src/lib/api/mock/vlm.ts` | 模擬 VLM 檢查 |
| `web/src/lib/api/mock/review.ts` | `reviewRender`：規則 + VLM + 計分 |
| `web/src/lib/api/mock/scenario.ts` | `buildTimeline`：產生整個任務的事件時間軸 |
| `web/src/lib/api/mock/player.ts` | `playTimeline`：依速度播放事件 |
| `web/src/lib/api/client.ts` | `ApiClient`、`DemoControls` 介面 |
| `web/src/lib/api/mock/store.ts` | `KeyValueStore` 介面與 `MemoryStore` |
| `web/src/lib/api/mock/client.ts` | `MockApiClient` |
| `web/src/lib/api/index.ts` | `getApiClient()`（依環境變數選擇實作） |

測試檔與被測檔放在同一資料夾，命名 `*.test.ts`。

---

### Task 1: Next.js 專案骨架 + Vitest + 核心工具

**Files:**
- Create: `web/`（create-next-app 產生）
- Create: `web/vitest.config.mts`、`web/.env.example`
- Create: `web/src/lib/core/num.ts`、`web/src/lib/core/text.ts`
- Test: `web/src/lib/core/num.test.ts`、`web/src/lib/core/text.test.ts`

**Interfaces:**
- Produces: `round1(v: number): number`、`clamp(v: number, min: number, max: number): number`、`mulberry32(seed: number): () => number`、`hashString(s: string): number`、`visLen(s: string): number`、`truncate(s: string, n: number): string`；npm scripts `test`、`test:watch`、`typecheck`

- [ ] **Step 1: 產生 Next.js 專案**（在 repo 根目錄執行）

```bash
npx create-next-app@latest web --ts --tailwind --eslint --app --src-dir --import-alias "@/*" --use-npm --yes
```

Expected: 建立 `web/`，包含 `web/src/app/page.tsx`、`web/package.json`。因為 repo 根目錄已經是 git repo，create-next-app 不會再建立新的 git repo；若 `web/.git` 存在，執行 `rm -rf web/.git`。

- [ ] **Step 2: 安裝 Vitest 並加入 scripts**（在 `web/` 執行）

```bash
npm i -D vitest vite-tsconfig-paths
npm pkg set scripts.test="vitest run" scripts.test:watch="vitest" scripts.typecheck="tsc --noEmit"
```

- [ ] **Step 3: 建立 `web/vitest.config.mts`**

```ts
import { defineConfig } from 'vitest/config';
import tsconfigPaths from 'vite-tsconfig-paths';

export default defineConfig({
  plugins: [tsconfigPaths()],
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
```

- [ ] **Step 4: 建立 `web/.env.example`**

```bash
# mock：前端模擬資料（第一階段）；live：連線 FastAPI（第二階段）
NEXT_PUBLIC_API_MODE=mock
```

- [ ] **Step 5: 寫失敗測試 `web/src/lib/core/num.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import { round1, clamp, mulberry32, hashString } from './num';

describe('num utils', () => {
  it('round1 rounds to one decimal place', () => {
    expect(round1(1.26)).toBe(1.3);
    expect(round1(2.04)).toBe(2);
  });

  it('clamp keeps values within bounds', () => {
    expect(clamp(5, 0, 3)).toBe(3);
    expect(clamp(-1, 0, 3)).toBe(0);
    expect(clamp(2, 0, 3)).toBe(2);
  });

  it('mulberry32 is deterministic and returns values in [0, 1)', () => {
    const a = mulberry32(42);
    const b = mulberry32(42);
    const xs = Array.from({ length: 5 }, () => a());
    expect(Array.from({ length: 5 }, () => b())).toEqual(xs);
    for (const x of xs) {
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThan(1);
    }
  });

  it('hashString is stable and differs between inputs', () => {
    expect(hashString('job_1')).toBe(hashString('job_1'));
    expect(hashString('job_1')).not.toBe(hashString('job_2'));
    expect(hashString('job_1')).toBeGreaterThanOrEqual(0);
  });
});
```

- [ ] **Step 6: 寫失敗測試 `web/src/lib/core/text.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import { visLen, truncate } from './text';

describe('text utils', () => {
  it('visLen counts CJK as 1em, spaces as 0.3em, others as 0.58em', () => {
    expect(visLen('一夜')).toBe(2);
    expect(visLen('72H')).toBeCloseTo(1.74);
    expect(visLen('a b')).toBeCloseTo(1.46);
  });

  it('truncate adds an ellipsis only when the text is longer than n', () => {
    expect(truncate('冷萃咖啡宣傳海報', 4)).toBe('冷萃咖啡…');
    expect(truncate('冷萃', 4)).toBe('冷萃');
  });
});
```

- [ ] **Step 7: 執行測試確認失敗**

Run: `npx vitest run src/lib/core`
Expected: FAIL，錯誤為找不到 `./num`、`./text` 模組

- [ ] **Step 8: 實作 `web/src/lib/core/num.ts`**

```ts
export const round1 = (v: number): number => Math.round(v * 10) / 10;

export const clamp = (v: number, min: number, max: number): number => Math.min(max, Math.max(min, v));

/** 可重現的偽隨機數產生器（同一 seed 產生同一序列） */
export function mulberry32(seed: number): () => number {
  let a = seed | 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** FNV-1a 32-bit 字串雜湊，回傳非負整數 */
export function hashString(s: string): number {
  let h = 2166136261;
  for (const ch of s) {
    h ^= ch.codePointAt(0) ?? 0;
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}
```

- [ ] **Step 9: 實作 `web/src/lib/core/text.ts`**

```ts
/** 估算字串的視覺寬度（以 em 為單位）：中日文全形 1、空白 0.3、其他半形 0.58 */
export function visLen(s: string): number {
  let n = 0;
  for (const ch of s) {
    const code = ch.codePointAt(0) ?? 0;
    n += code > 0x2e80 ? 1 : ch === ' ' ? 0.3 : 0.58;
  }
  return n;
}

export function truncate(s: string, n: number): string {
  const chars = [...s];
  return chars.length > n ? chars.slice(0, n).join('') + '…' : s;
}
```

- [ ] **Step 10: 執行測試與型別檢查確認通過**

Run: `npx vitest run src/lib/core && npm run typecheck`
Expected: 2 個測試檔、6 個測試 PASS；typecheck 無錯誤

- [ ] **Step 11: Commit**（在 repo 根目錄執行）

```bash
git add web
git commit -m "chore: scaffold Next.js app with Vitest and core utils" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: 資料約定 `contract.ts`

**Files:**
- Create: `web/src/types/contract.ts`
- Test: `web/src/types/contract.test.ts`

**Interfaces:**
- Produces（後續所有 Task 都會 import）：常數 `TEMPLATE_IDS`、`LAYOUT_ELEMENT_IDS`、`CHECK_IDS`、`TONES`；型別 `Hex`、`Palette`、`Tone`、`Engine`、`TemplateId`、`LayoutElementId`、`BBox`、`LayoutBox`、`RagTag`、`RagChunk`、`CaseStudy`、`BrandRules`、`Brand`、`ProductPhoto`、`Product`、`ChannelTemplate`、`ParsedBrief`、`JobInput`、`Copy`、`ComfyParam`、`ComfyInjection`、`PromptSpec`、`CheckStatus`、`CheckId`、`ReviewCheck`、`RenderBackground`、`Render`、`RagHit`、`Fix`、`JobStage`、`RenderNode`、`LogSource`、`LogLevel`、`JobEvent`、`HistoryEntry`、`DemoOptions`

- [ ] **Step 1: 寫失敗測試 `web/src/types/contract.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import { TEMPLATE_IDS, LAYOUT_ELEMENT_IDS, CHECK_IDS, TONES } from './contract';

const unique = (xs: readonly string[]) => new Set(xs).size === xs.length;

describe('contract constants', () => {
  it('lists the 5 channel templates from the spec', () => {
    expect(TEMPLATE_IDS).toEqual(['ecom-main', 'scene', 'ig-post', 'story', 'banner']);
  });

  it('has 8 layout elements, 10 checks and 4 tones, all unique', () => {
    expect(LAYOUT_ELEMENT_IDS).toHaveLength(8);
    expect(CHECK_IDS).toHaveLength(10);
    expect(TONES).toHaveLength(4);
    expect(unique(LAYOUT_ELEMENT_IDS) && unique(CHECK_IDS) && unique(TONES)).toBe(true);
  });
});
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `npx vitest run src/types`
Expected: FAIL，找不到 `./contract`

- [ ] **Step 3: 實作 `web/src/types/contract.ts`**

```ts
/**
 * 前後端資料約定。第二階段 FastAPI 以 Pydantic 照此定義，
 * WebSocket `/ws/jobs/{jobId}` 送出的事件即 `JobEvent`。
 */

export const TEMPLATE_IDS = ['ecom-main', 'scene', 'ig-post', 'story', 'banner'] as const;
export type TemplateId = (typeof TEMPLATE_IDS)[number];

export const LAYOUT_ELEMENT_IDS = ['logo', 'headline', 'subhead', 'features', 'product', 'badge', 'price', 'disclaimer'] as const;
export type LayoutElementId = (typeof LAYOUT_ELEMENT_IDS)[number];

export const CHECK_IDS = [
  'banned_words', 'color_delta', 'logo_clearance', 'disclaimer', 'product_ratio', 'whitespace', 'ocr_typo',
  'vlm_exaggeration', 'vlm_occlusion', 'vlm_quality',
] as const;
export type CheckId = (typeof CHECK_IDS)[number];

export const TONES = ['gentle', 'science', 'playful', 'minimal'] as const;
export type Tone = (typeof TONES)[number];

export type Hex = `#${string}`;
export interface Palette { primary: Hex; secondary: Hex; accent: Hex; ink: Hex }
export type Engine = 'comfyui' | 'ideogram';

/** [x, y, w, h]，單位為輸出圖的像素 */
export type BBox = [x: number, y: number, w: number, h: number];
export interface LayoutBox { id: LayoutElementId; bbox: BBox; z: number }

/* ---------- 品牌與 RAG ---------- */
export type RagTag = 'color' | 'logo' | 'law' | 'layout' | 'font' | 'history';
export interface RagChunk { id: string; source: string; section: string; tag: RagTag; text: string }
export interface CaseStudy { id: string; title: string; channel: string; ctr: number; notes: string }
export interface BrandRules { maxDeltaE: number; minWhitespace: number; productRatio: [min: number, max: number] }

export interface Brand {
  id: string;
  name: string;
  category: string;
  ciVersion: string;
  palette: Palette;
  fonts: { headline: string; body: string };
  /** 生圖時的品牌視覺風格描述（英文，直接進 positive prompt） */
  visualStyle: string;
  defaultTone: Tone;
  rules: BrandRules;
  /** 禁用詞（法規與品牌規範） */
  bannedWords: string[];
  /** 合規替代用語：禁用詞 → 替代詞（空字串代表刪除） */
  replacements: Record<string, string>;
  /** 出現這些詞視為效果宣稱 */
  claimWords: string[];
  /** 效果宣稱時頁尾必須包含的註記；空字串代表此品牌不需要 */
  disclaimerPhrase: string;
  guidelineChunks: RagChunk[];
  caseStudies: CaseStudy[];
  copyPresets: Record<Tone, { headline: [string, string]; subhead: string }>;
}

/* ---------- 商品與模板 ---------- */
export type ProductPhoto =
  | { source: 'sample'; art: 'serum' | 'coldbrew' }
  | { source: 'upload' | 'local'; url: string };

export interface Product {
  id: string;
  brandId: string;
  name: string;
  features: string[];
  price: { sale: number; original: number };
  photo: ProductPhoto;
  createdAt: string;
}

export interface ChannelTemplate { id: TemplateId; label: string; ratio: string; width: number; height: number }

/* ---------- 任務輸入 ---------- */
export interface ParsedBrief {
  productName: string | null;
  sellingPoints: string[];
  audience: string;
  tone: Tone;
  campaign: string | null;
  offer: string | null;
  /** 英文風格標籤，例如 minimal、premium */
  style: string[];
}

export interface JobInput {
  brandId: string;
  productId: string;
  brief: string;
  parsedBrief: ParsedBrief;
  templateIds: TemplateId[];
  variantsPerTemplate: number;
  llm: string;
  engine: Engine;
  vlm: string;
  maxRetries: number;
}

/* ---------- Agent 輸出 ---------- */
export interface Copy {
  headline: [string, string];
  subhead: string;
  features: string[];
  badge: { top: string; main: string; sub: string };
  price: { label: string; sale: number; original: number };
  productName: string;
  disclaimer: string;
}

export interface ComfyParam { nodeId: string; input: string; label: string; value: string | number }
export interface ComfyInjection { engine: Engine; workflowFile: string; params: ComfyParam[] }

export interface PromptSpec {
  jobId: string;
  round: number;
  templateId: TemplateId;
  brandId: string;
  canvas: { width: number; height: number; ratio: string };
  palette: Palette;
  copy: Copy;
  layout: LayoutBox[];
  positivePrompt: string;
  negativePrompt: string;
  injection: ComfyInjection;
  ragRefs: string[];
}

/* ---------- 審查與產出 ---------- */
export type CheckStatus = 'pass' | 'warn' | 'fail';
export interface ReviewCheck {
  id: CheckId;
  name: string;
  kind: 'rule' | 'vlm';
  rule: string;
  value: string;
  status: CheckStatus;
  /** 對應版面元素；'canvas' 代表整張圖；null 代表無特定位置 */
  target: LayoutElementId | 'canvas' | null;
  ragRef: string | null;
}

export type RenderBackground =
  | { kind: 'procedural'; seed: number; palette: Palette; style: string }
  | { kind: 'url'; url: string };

export interface Render {
  id: string;
  jobId: string;
  round: number;
  templateId: TemplateId;
  variant: number;
  background: RenderBackground;
  spec: PromptSpec;
  score: number | null;
  passed: boolean | null;
  checks: ReviewCheck[];
}

export interface RagHit {
  chunkId: string;
  source: string;
  section: string;
  tag: RagTag;
  text: string;
  vectorScore: number;
  rerankScore?: number;
}

export interface Fix { checkId: CheckId; title: string; desc: string }

/* ---------- WebSocket 事件 ---------- */
export type JobStage =
  | 'parsing' | 'retrieving' | 'prompting' | 'rendering' | 'composing' | 'reviewing'
  | 'rewriting' | 'saving' | 'done' | 'needs_review' | 'cancelled';
export type RenderNode = 'cutout' | 'generate' | 'relight' | 'upscale';
export type LogSource = 'ws' | 'api' | 'agent' | 'rag' | 'comfy' | 'compose' | 'vlm' | 'db';
export type LogLevel = 'info' | 'ok' | 'warn' | 'error';

export type JobEvent =
  | { type: 'job.accepted'; jobId: string }
  | { type: 'job.status'; stage: JobStage; round: number }
  | { type: 'brief.parsed'; parsedBrief: ParsedBrief }
  | { type: 'rag.retrieved'; query: string; hits: RagHit[] }
  | { type: 'rag.reranked'; hits: RagHit[] }
  | { type: 'prompt.generated'; round: number; templateId: TemplateId; spec: PromptSpec }
  | { type: 'comfy.queued'; round: number; templateId: TemplateId; promptId: string; injection: ComfyInjection }
  | { type: 'render.progress'; round: number; node: RenderNode; step: number; maxStep: number }
  | { type: 'render.completed'; round: number; renders: Render[] }
  | { type: 'review.check'; round: number; renderId: string; check: ReviewCheck }
  | { type: 'review.completed'; round: number; renderId: string; score: number; passed: boolean }
  | { type: 'rewrite.started'; round: number; templateId: TemplateId; reasons: CheckId[]; fixes: Fix[]; requery: boolean }
  | { type: 'job.completed'; jobId: string; bestRenderIds: Partial<Record<TemplateId, string>> }
  | { type: 'job.needs_review'; jobId: string; reason: string }
  | { type: 'log'; source: LogSource; level: LogLevel; message: string };

/* ---------- 歷史紀錄與 Demo ---------- */
export interface HistoryEntry {
  id: string;
  jobId: string;
  brandId: string;
  productId: string;
  templateId: TemplateId;
  render: Render;
  copy: Copy;
  selectedAt: string;
  favorite: boolean;
  writtenToRag: boolean;
}

export interface DemoOptions { speed: 1 | 2 | 4; firstRoundFail: boolean; forceAllFail: boolean }
```

- [ ] **Step 4: 執行測試與型別檢查確認通過**

Run: `npx vitest run src/types && npm run typecheck`
Expected: 2 個測試 PASS；typecheck 無錯誤

- [ ] **Step 5: Commit**

```bash
git add web/src/types
git commit -m "feat: add frontend/backend data contract types" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: 色彩工具與 ΔE2000

**Files:**
- Create: `web/src/lib/review/color.ts`
- Test: `web/src/lib/review/color.test.ts`

**Interfaces:**
- Consumes: `Hex`（Task 2）
- Produces: `interface Lab { L: number; a: number; b: number }`、`hexToRgb(hex: string): [number, number, number]`（格式錯誤時 throw）、`rgbToHex(rgb: [number, number, number]): Hex`、`mixHex(a: string, b: string, t: number): Hex`、`rgbToLab(rgb: [number, number, number]): Lab`、`deltaE2000(x: Lab, y: Lab): number`、`deltaEHex(a: string, b: string): number`

- [ ] **Step 1: 寫失敗測試 `web/src/lib/review/color.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import { hexToRgb, rgbToHex, mixHex, rgbToLab, deltaE2000, deltaEHex } from './color';

describe('hex conversion', () => {
  it('parses and formats hex colors', () => {
    expect(hexToRgb('#B76E79')).toEqual([183, 110, 121]);
    expect(rgbToHex([183, 110, 121])).toBe('#b76e79');
  });

  it('throws on invalid hex', () => {
    expect(() => hexToRgb('#12345')).toThrow('Invalid hex color');
  });

  it('mixes two colors', () => {
    expect(mixHex('#000000', '#ffffff', 0.5)).toBe('#808080');
    expect(mixHex('#B76E79', '#ffffff', 0)).toBe('#b76e79');
  });
});

describe('rgbToLab (D65)', () => {
  it('converts white, black and pure red', () => {
    const white = rgbToLab([255, 255, 255]);
    expect(white.L).toBeCloseTo(100, 1);
    expect(white.a).toBeCloseTo(0, 1);
    expect(white.b).toBeCloseTo(0, 1);
    expect(rgbToLab([0, 0, 0]).L).toBeCloseTo(0, 1);
    const red = rgbToLab([255, 0, 0]);
    expect(red.L).toBeCloseTo(53.24, 1);
    expect(red.a).toBeCloseTo(80.09, 1);
    expect(red.b).toBeCloseTo(67.2, 1);
  });
});

describe('deltaE2000', () => {
  // Sharma, Wu & Dalal (2005) CIEDE2000 測試資料
  it.each([
    [{ L: 50, a: 2.6772, b: -79.7751 }, { L: 50, a: 0, b: -82.7485 }, 2.0425],
    [{ L: 50, a: 3.1571, b: -77.2803 }, { L: 50, a: 0, b: -82.7485 }, 2.8615],
    [{ L: 50, a: 0, b: 0 }, { L: 50, a: -1, b: 2 }, 2.3669],
    [{ L: 50, a: 2.5, b: 0 }, { L: 73, a: 25, b: -18 }, 27.1492],
  ])('matches reference pair %#', (x, y, expected) => {
    expect(deltaE2000(x, y)).toBeCloseTo(expected, 3);
  });

  it('is zero for identical colors and symmetric', () => {
    const c = { L: 62, a: 24, b: 3 };
    expect(deltaE2000(c, c)).toBe(0);
    const d = { L: 40, a: -10, b: 30 };
    expect(deltaE2000(c, d)).toBeCloseTo(deltaE2000(d, c), 10);
  });

  it('deltaEHex flags an off-brand pink as far from the brand rose', () => {
    expect(deltaEHex('#B76E79', '#B76E79')).toBe(0);
    expect(deltaEHex('#E0458A', '#B76E79')).toBeGreaterThan(5);
    expect(deltaEHex(mixHex('#B76E79', '#ffffff', 0.03), '#B76E79')).toBeLessThan(5);
  });
});
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `npx vitest run src/lib/review/color.test.ts`
Expected: FAIL，找不到 `./color`

- [ ] **Step 3: 實作 `web/src/lib/review/color.ts`**

```ts
import type { Hex } from '@/types/contract';

export interface Lab { L: number; a: number; b: number }

export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '');
  if (!/^[0-9a-fA-F]{6}$/.test(h)) throw new Error(`Invalid hex color: ${hex}`);
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
}

export function rgbToHex(rgb: [number, number, number]): Hex {
  return ('#' + rgb.map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('')) as Hex;
}

export function mixHex(a: string, b: string, t: number): Hex {
  const A = hexToRgb(a);
  const B = hexToRgb(b);
  return rgbToHex([0, 1, 2].map((i) => A[i] + (B[i] - A[i]) * t) as [number, number, number]);
}

const toLinear = (c: number) => {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
};

/** sRGB → CIE Lab（D65 白點） */
export function rgbToLab([r8, g8, b8]: [number, number, number]): Lab {
  const r = toLinear(r8), g = toLinear(g8), b = toLinear(b8);
  const x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) * 100;
  const y = (0.2126729 * r + 0.7151522 * g + 0.072175 * b) * 100;
  const z = (0.0193339 * r + 0.119192 * g + 0.9503041 * b) * 100;
  const f = (t: number) => (t > 216 / 24389 ? Math.cbrt(t) : ((24389 / 27) * t + 16) / 116);
  const fx = f(x / 95.047), fy = f(y / 100), fz = f(z / 108.883);
  return { L: 116 * fy - 16, a: 500 * (fx - fy), b: 200 * (fy - fz) };
}

/** CIEDE2000 色差（kL = kC = kH = 1） */
export function deltaE2000(x: Lab, y: Lab): number {
  const rad = Math.PI / 180;
  const deg = 180 / Math.PI;
  const C1 = Math.hypot(x.a, x.b);
  const C2 = Math.hypot(y.a, y.b);
  const Cbar = (C1 + C2) / 2;
  const G = 0.5 * (1 - Math.sqrt(Cbar ** 7 / (Cbar ** 7 + 25 ** 7)));
  const a1p = (1 + G) * x.a;
  const a2p = (1 + G) * y.a;
  const C1p = Math.hypot(a1p, x.b);
  const C2p = Math.hypot(a2p, y.b);
  const hue = (bb: number, ap: number) => {
    if (bb === 0 && ap === 0) return 0;
    const v = Math.atan2(bb, ap) * deg;
    return v >= 0 ? v : v + 360;
  };
  const h1p = hue(x.b, a1p);
  const h2p = hue(y.b, a2p);

  const dLp = y.L - x.L;
  const dCp = C2p - C1p;
  let dhp = 0;
  if (C1p * C2p !== 0) {
    dhp = h2p - h1p;
    if (dhp > 180) dhp -= 360;
    else if (dhp < -180) dhp += 360;
  }
  const dHp = 2 * Math.sqrt(C1p * C2p) * Math.sin((dhp / 2) * rad);

  const Lbarp = (x.L + y.L) / 2;
  const Cbarp = (C1p + C2p) / 2;
  let hbarp = h1p + h2p;
  if (C1p * C2p !== 0) {
    if (Math.abs(h1p - h2p) <= 180) hbarp = (h1p + h2p) / 2;
    else hbarp = h1p + h2p < 360 ? (h1p + h2p + 360) / 2 : (h1p + h2p - 360) / 2;
  }

  const T =
    1 -
    0.17 * Math.cos((hbarp - 30) * rad) +
    0.24 * Math.cos(2 * hbarp * rad) +
    0.32 * Math.cos((3 * hbarp + 6) * rad) -
    0.2 * Math.cos((4 * hbarp - 63) * rad);
  const dTheta = 30 * Math.exp(-(((hbarp - 275) / 25) ** 2));
  const Rc = 2 * Math.sqrt(Cbarp ** 7 / (Cbarp ** 7 + 25 ** 7));
  const Sl = 1 + (0.015 * (Lbarp - 50) ** 2) / Math.sqrt(20 + (Lbarp - 50) ** 2);
  const Sc = 1 + 0.045 * Cbarp;
  const Sh = 1 + 0.015 * Cbarp * T;
  const Rt = -Math.sin(2 * dTheta * rad) * Rc;

  return Math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh));
}

export function deltaEHex(a: string, b: string): number {
  return deltaE2000(rgbToLab(hexToRgb(a)), rgbToLab(hexToRgb(b)));
}
```

- [ ] **Step 4: 執行測試確認通過**

Run: `npx vitest run src/lib/review/color.test.ts`
Expected: 全部 PASS（含 4 組 Sharma 參考值）

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/review/color.ts web/src/lib/review/color.test.ts
git commit -m "feat: add color utils with CIEDE2000 delta E" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: 幾何工具、通路模板與版型引擎

**Files:**
- Create: `web/src/lib/core/geometry.ts`、`web/src/lib/compose/templates.ts`、`web/src/lib/compose/layout.ts`
- Test: `web/src/lib/core/geometry.test.ts`、`web/src/lib/compose/layout.test.ts`

**Interfaces:**
- Consumes: `ChannelTemplate`、`TemplateId`、`LayoutBox`、`LayoutElementId`、`LAYOUT_ELEMENT_IDS`、`BBox`（Task 2）；`visLen`（Task 1）
- Produces:
  - `interface Rect { x: number; y: number; w: number; h: number }`、`toRect(b: BBox): Rect`、`intersectionArea(a: Rect, b: Rect): number`、`overlapRatio(a: Rect, b: Rect): number`、`areaRatio(r: Rect, W: number, H: number): number`、`verticalGap(above: Rect, below: Rect): number`、`isInside(r: Rect, W: number, H: number): boolean`
  - `CHANNEL_TEMPLATES: ChannelTemplate[]`、`getTemplate(id: TemplateId): ChannelTemplate`
  - `LAYOUT_PRESETS`、`computeLayout(t: ChannelTemplate): LayoutBox[]`、`boxMap(layout: LayoutBox[]): Record<LayoutElementId, Rect>`、`fitFontSize(lines: string[], box: { w: number; h: number }, lineHeight?: number): number`

- [ ] **Step 1: 寫失敗測試 `web/src/lib/core/geometry.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import { toRect, intersectionArea, overlapRatio, areaRatio, verticalGap, isInside } from './geometry';

const a = { x: 0, y: 0, w: 10, h: 10 };

describe('geometry', () => {
  it('computes intersection area; touching edges do not intersect', () => {
    expect(intersectionArea(a, { x: 5, y: 5, w: 10, h: 10 })).toBe(25);
    expect(intersectionArea(a, { x: 10, y: 0, w: 5, h: 5 })).toBe(0);
    expect(intersectionArea(a, { x: 20, y: 20, w: 5, h: 5 })).toBe(0);
  });

  it('overlapRatio is intersection over the smaller area', () => {
    expect(overlapRatio(a, { x: 5, y: 5, w: 10, h: 10 })).toBe(0.25);
    expect(overlapRatio(a, { x: 2, y: 2, w: 2, h: 2 })).toBe(1);
  });

  it('areaRatio, verticalGap, isInside, toRect', () => {
    expect(areaRatio(a, 20, 20)).toBe(0.25);
    expect(verticalGap(a, { x: 0, y: 14, w: 5, h: 5 })).toBe(4);
    expect(verticalGap(a, { x: 0, y: 6, w: 5, h: 5 })).toBe(-4);
    expect(isInside(a, 10, 10)).toBe(true);
    expect(isInside({ x: 5, y: 0, w: 10, h: 5 }, 10, 10)).toBe(false);
    expect(toRect([1, 2, 3, 4])).toEqual({ x: 1, y: 2, w: 3, h: 4 });
  });
});
```

- [ ] **Step 2: 寫失敗測試 `web/src/lib/compose/layout.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import { CHANNEL_TEMPLATES, getTemplate } from './templates';
import { computeLayout, boxMap, fitFontSize } from './layout';
import { intersectionArea, isInside, areaRatio, verticalGap, toRect } from '@/lib/core/geometry';

describe('channel templates', () => {
  it('has the 5 templates from the spec with exact output sizes', () => {
    expect(CHANNEL_TEMPLATES.map((t) => [t.id, t.width, t.height])).toEqual([
      ['ecom-main', 1600, 1600],
      ['scene', 2048, 1536],
      ['ig-post', 1440, 1800],
      ['story', 1152, 2048],
      ['banner', 2048, 1152],
    ]);
    expect(getTemplate('story').ratio).toBe('9:16');
    expect(() => getTemplate('nope' as never)).toThrow('Unknown template');
  });
});

describe.each(CHANNEL_TEMPLATES)('computeLayout($id)', (t) => {
  const layout = computeLayout(t);
  const B = boxMap(layout);

  it('returns 8 boxes inside the canvas', () => {
    expect(layout).toHaveLength(8);
    for (const b of layout) expect(isInside(toRect(b.bbox), t.width, t.height)).toBe(true);
  });

  it('has no overlapping boxes', () => {
    for (let i = 0; i < layout.length; i++)
      for (let j = i + 1; j < layout.length; j++)
        expect(intersectionArea(toRect(layout[i].bbox), toRect(layout[j].bbox)), `${layout[i].id} vs ${layout[j].id}`).toBe(0);
  });

  it('keeps the logo clear of the headline by at least half the logo height', () => {
    expect(verticalGap(B.logo, B.headline)).toBeGreaterThanOrEqual(Math.round(B.logo.h * 0.5));
  });

  it('draws the badge as a near-square and keeps product/whitespace ratios valid', () => {
    expect(Math.abs(B.badge.w - B.badge.h)).toBeLessThanOrEqual(2);
    const prod = areaRatio(B.product, t.width, t.height);
    expect(prod).toBeGreaterThanOrEqual(0.2);
    expect(prod).toBeLessThanOrEqual(0.5);
    const used = Object.values(B).reduce((s, r) => s + areaRatio(r, t.width, t.height), 0);
    expect(1 - used).toBeGreaterThanOrEqual(0.4);
  });
});

describe('fitFontSize', () => {
  it('is limited by height for two lines and by width for long lines', () => {
    expect(fitFontSize(['一夜溫柔修護', '醒來透亮發光'], { w: 900, h: 300 })).toBe(125);
    expect(fitFontSize(['一二三四五六七八九十'], { w: 500, h: 300 })).toBe(50);
  });
});
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `npx vitest run src/lib/core/geometry.test.ts src/lib/compose`
Expected: FAIL，找不到 `./geometry`、`./templates`、`./layout`

- [ ] **Step 4: 實作 `web/src/lib/core/geometry.ts`**

```ts
import type { BBox } from '@/types/contract';

export interface Rect { x: number; y: number; w: number; h: number }

export const toRect = ([x, y, w, h]: BBox): Rect => ({ x, y, w, h });

export function intersectionArea(a: Rect, b: Rect): number {
  const w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  return w > 0 && h > 0 ? w * h : 0;
}

/** 交集面積 ÷ 較小的那個框的面積 */
export function overlapRatio(a: Rect, b: Rect): number {
  const smaller = Math.min(a.w * a.h, b.w * b.h);
  return smaller > 0 ? intersectionArea(a, b) / smaller : 0;
}

export const areaRatio = (r: Rect, W: number, H: number): number => (r.w * r.h) / (W * H);

/** below 的上緣到 above 的下緣之距離；負值代表重疊 */
export const verticalGap = (above: Rect, below: Rect): number => below.y - (above.y + above.h);

export const isInside = (r: Rect, W: number, H: number): boolean =>
  r.x >= 0 && r.y >= 0 && r.x + r.w <= W && r.y + r.h <= H;
```

- [ ] **Step 5: 實作 `web/src/lib/compose/templates.ts`**

```ts
import type { ChannelTemplate, TemplateId } from '@/types/contract';

export const CHANNEL_TEMPLATES: ChannelTemplate[] = [
  { id: 'ecom-main', label: '電商主圖', ratio: '1:1', width: 1600, height: 1600 },
  { id: 'scene', label: '情境圖', ratio: '4:3', width: 2048, height: 1536 },
  { id: 'ig-post', label: 'IG 貼文', ratio: '4:5', width: 1440, height: 1800 },
  { id: 'story', label: '限時動態', ratio: '9:16', width: 1152, height: 2048 },
  { id: 'banner', label: '促銷 Banner', ratio: '16:9', width: 2048, height: 1152 },
];

export function getTemplate(id: TemplateId): ChannelTemplate {
  const t = CHANNEL_TEMPLATES.find((x) => x.id === id);
  if (!t) throw new Error(`Unknown template: ${id}`);
  return t;
}
```

- [ ] **Step 6: 實作 `web/src/lib/compose/layout.ts`**

```ts
import { LAYOUT_ELEMENT_IDS } from '@/types/contract';
import type { ChannelTemplate, LayoutBox, LayoutElementId, TemplateId } from '@/types/contract';
import type { Rect } from '@/lib/core/geometry';
import { visLen } from '@/lib/core/text';

type NormBox = [x: number, y: number, w: number, h: number];

/** 各模板版型，以畫布比例表示 [x, y, w, h]。直式文字在上、商品在下；橫式文字在左、商品在右。 */
export const LAYOUT_PRESETS: Record<TemplateId, Record<LayoutElementId, NormBox>> = {
  'ecom-main': {
    logo: [0.06, 0.06, 0.22, 0.045], headline: [0.06, 0.15, 0.48, 0.2], subhead: [0.06, 0.375, 0.46, 0.035],
    features: [0.06, 0.43, 0.46, 0.04], product: [0.55, 0.1, 0.4, 0.82], badge: [0.06, 0.53, 0.17, 0.17],
    price: [0.26, 0.555, 0.28, 0.12], disclaimer: [0.06, 0.94, 0.88, 0.025],
  },
  scene: {
    logo: [0.05, 0.07, 0.18, 0.055], headline: [0.05, 0.17, 0.45, 0.22], subhead: [0.05, 0.415, 0.45, 0.04],
    features: [0.05, 0.48, 0.45, 0.05], product: [0.55, 0.08, 0.4, 0.84], badge: [0.05, 0.58, 0.13, 0.173],
    price: [0.21, 0.6, 0.28, 0.14], disclaimer: [0.05, 0.93, 0.45, 0.03],
  },
  'ig-post': {
    logo: [0.07, 0.05, 0.26, 0.045], headline: [0.07, 0.12, 0.6, 0.16], subhead: [0.07, 0.295, 0.55, 0.035],
    features: [0.07, 0.345, 0.5, 0.04], product: [0.44, 0.4, 0.5, 0.51], badge: [0.07, 0.47, 0.24, 0.192],
    price: [0.07, 0.7, 0.36, 0.11], disclaimer: [0.07, 0.935, 0.86, 0.025],
  },
  story: {
    logo: [0.08, 0.04, 0.34, 0.04], headline: [0.08, 0.105, 0.84, 0.13], subhead: [0.08, 0.25, 0.84, 0.03],
    features: [0.08, 0.295, 0.84, 0.035], product: [0.12, 0.35, 0.52, 0.41], badge: [0.64, 0.4, 0.28, 0.1575],
    price: [0.08, 0.79, 0.84, 0.1], disclaimer: [0.08, 0.945, 0.84, 0.022],
  },
  banner: {
    logo: [0.04, 0.08, 0.15, 0.07], headline: [0.04, 0.21, 0.42, 0.26], subhead: [0.04, 0.5, 0.42, 0.05],
    features: [0.04, 0.58, 0.42, 0.06], product: [0.52, 0.06, 0.36, 0.88], badge: [0.04, 0.7, 0.09, 0.16],
    price: [0.15, 0.7, 0.3, 0.17], disclaimer: [0.04, 0.92, 0.44, 0.04],
  },
};

const Z_INDEX: Partial<Record<LayoutElementId, number>> = { product: 1, badge: 3 };

export function computeLayout(t: ChannelTemplate): LayoutBox[] {
  const preset = LAYOUT_PRESETS[t.id];
  return LAYOUT_ELEMENT_IDS.map((id): LayoutBox => {
    const [x, y, w, h] = preset[id];
    return {
      id,
      bbox: [Math.round(x * t.width), Math.round(y * t.height), Math.round(w * t.width), Math.round(h * t.height)],
      z: Z_INDEX[id] ?? 2,
    };
  });
}

export function boxMap(layout: LayoutBox[]): Record<LayoutElementId, Rect> {
  return Object.fromEntries(
    layout.map((b) => [b.id, { x: b.bbox[0], y: b.bbox[1], w: b.bbox[2], h: b.bbox[3] }]),
  ) as Record<LayoutElementId, Rect>;
}

/** 讓多行文字同時符合框的高度與寬度的最大字級（px） */
export function fitFontSize(lines: string[], box: { w: number; h: number }, lineHeight = 1.2): number {
  const widest = Math.max(...lines.map(visLen), 1e-6);
  return Math.min(box.h / (lines.length * lineHeight), box.w / widest);
}
```

- [ ] **Step 7: 執行測試確認通過**

Run: `npx vitest run src/lib/core/geometry.test.ts src/lib/compose`
Expected: 全部 PASS（5 個模板 × 4 項版型檢查 + 模板與字級測試）

- [ ] **Step 8: Commit**

```bash
git add web/src/lib/core/geometry.ts web/src/lib/core/geometry.test.ts web/src/lib/compose
git commit -m "feat: add channel templates and layout engine" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: 示範品牌與商品資料

**Files:**
- Create: `web/src/lib/api/mock/data/brands.ts`、`web/src/lib/api/mock/data/products.ts`、`web/src/lib/api/mock/data/index.ts`
- Test: `web/src/lib/api/mock/data/data.test.ts`

**Interfaces:**
- Consumes: `Brand`、`Product`、`TONES`（Task 2）；`hexToRgb`（Task 3）
- Produces: `SELUNE: Brand`、`MISTY_ISLE: Brand`、`BRANDS: Brand[]`、`getBrandById(id: string): Brand`（未知 id 時 throw）、`SAMPLE_PRODUCTS: Product[]`。慣例：每個品牌都有一個 id 為 `${brand.id}#law-alt` 的「合規替代用語」切塊，只在 Query Rewriting 重新檢索時使用

- [ ] **Step 1: 寫失敗測試 `web/src/lib/api/mock/data/data.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import { TONES } from '@/types/contract';
import { hexToRgb } from '@/lib/review/color';
import { BRANDS, getBrandById, SAMPLE_PRODUCTS } from './index';

describe.each(BRANDS)('brand $id', (brand) => {
  it('has a valid palette', () => {
    for (const hex of Object.values(brand.palette)) expect(() => hexToRgb(hex)).not.toThrow();
  });

  it('has one guideline chunk per tag plus a law-alt chunk, with unique ids', () => {
    const tags = brand.guidelineChunks.map((c) => c.tag);
    for (const tag of ['color', 'logo', 'law', 'layout', 'font', 'history'] as const) expect(tags).toContain(tag);
    const ids = brand.guidelineChunks.map((c) => c.id);
    expect(ids).toContain(`${brand.id}#law-alt`);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('has a two-line copy preset for every tone', () => {
    for (const tone of TONES) {
      expect(brand.copyPresets[tone].headline).toHaveLength(2);
      expect(brand.copyPresets[tone].subhead.length).toBeGreaterThan(0);
    }
  });

  it('only defines replacements for banned words, and presets contain no banned words', () => {
    for (const word of Object.keys(brand.replacements)) expect(brand.bannedWords).toContain(word);
    for (const tone of TONES) {
      const text = brand.copyPresets[tone].headline.join('') + brand.copyPresets[tone].subhead;
      for (const word of brand.bannedWords) expect(text).not.toContain(word);
    }
  });
});

describe('lookups', () => {
  it('finds brands by id and rejects unknown ids', () => {
    expect(getBrandById('selune').name).toBe('SÉLUNE 晞月');
    expect(() => getBrandById('nope')).toThrow('Unknown brand');
  });

  it('every sample product belongs to a known brand', () => {
    expect(SAMPLE_PRODUCTS.length).toBeGreaterThanOrEqual(2);
    for (const p of SAMPLE_PRODUCTS) expect(() => getBrandById(p.brandId)).not.toThrow();
  });
});
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `npx vitest run src/lib/api/mock/data`
Expected: FAIL，找不到 `./index`

- [ ] **Step 3: 實作 `web/src/lib/api/mock/data/brands.ts`**

```ts
import type { Brand } from '@/types/contract';

export const SELUNE: Brand = {
  id: 'selune',
  name: 'SÉLUNE 晞月',
  category: '美妝保養',
  ciVersion: 'v2.3',
  palette: { primary: '#B76E79', secondary: '#F6EFE9', accent: '#C9A96E', ink: '#3A3335' },
  fonts: { headline: 'Noto Serif TC', body: 'Noto Sans TC' },
  visualStyle: 'serene luxury skincare, crescent moon halo, aurora light ribbons, pearl-gold bokeh, soft diffused studio light',
  defaultTone: 'gentle',
  rules: { maxDeltaE: 5, minWhitespace: 0.3, productRatio: [0.2, 0.5] },
  bannedWords: ['根治', '治療', '醫療級', '消炎', '保證有效', '永久'],
  replacements: { 根治: '改善外觀', 治療: '保養', 醫療級: '專業配方', 消炎: '舒緩', 保證有效: '', 永久: '持久' },
  claimWords: ['感受', '透亮', '修護', '淡化', '改善', '鎖水'],
  disclaimerPhrase: '效果因個人膚況而異',
  guidelineChunks: [
    { id: 'selune#color', source: 'brand_guideline_v2.3.pdf', section: '§2.1 色彩系統', tag: 'color',
      text: '品牌主色「晞月玫瑰」#B76E79，輔助色「月光米白」#F6EFE9、點綴色「珍珠金」#C9A96E、文字「墨灰」#3A3335。主色色差需控制在 ΔE2000 ≤ 5，禁止使用高飽和桃紅與螢光色系。' },
    { id: 'selune#logo', source: 'brand_guideline_v2.3.pdf', section: '§3.4 Logo 使用規範', tag: 'logo',
      text: 'Logo 四周需保留至少 0.5 倍 Logo 高度之淨空區，不得與標題、商品或其他元素重疊；建議置於左上角網格起點。' },
    { id: 'selune#law', source: 'compliance_cosmetics_tw.md', section: '化粧品衛生安全管理法 §10', tag: 'law',
      text: '化粧品之標示、宣傳及廣告不得有虛偽或誇大之情事，且不得宣稱醫療效能。禁用詞例：根治、治療、醫療級、消炎、保證有效、永久。含效果宣稱時應加註「效果因個人膚況而異」。' },
    { id: 'selune#layout', source: 'layout_style_guide.pdf', section: '§1.2 海報版型', tag: 'layout',
      text: '標題靠左對齊 8 欄網格；商品主體佔畫面 20–50%；整體留白 ≥ 30%；促銷徽章置於商品左側。' },
    { id: 'selune#font', source: 'brand_guideline_v2.3.pdf', section: '§4.1 字型', tag: 'font',
      text: '標題使用 Noto Serif TC Bold，內文使用 Noto Sans TC；標題最多兩行，第二行可使用主色強調。' },
    { id: 'selune#history', source: 'campaign_history/2025_anniversary.json', section: '2025 週年慶素材成效', tag: 'history',
      text: '去年週年慶高互動素材特徵：柔光漸層背景、水波紋與珍珠金點綴，文案以「修護」「透亮」為主軸，平均 CTR 4.2%。' },
    { id: 'selune#law-alt', source: 'compliance_cosmetics_tw.md', section: '合規替代用語對照', tag: 'law',
      text: '「根治」→「改善外觀」；「醫療級」→「專業配方」；「治療」→「保養」；「保證有效」→ 刪除。效果宣稱句尾加註「*」，並於頁尾標示使用者感受說明。' },
  ],
  caseStudies: [
    { id: 'selune-case-1', title: '2025 週年慶 IG 貼文', channel: 'IG 貼文', ctr: 4.2, notes: '柔光漸層 + 水波紋，文案主打修護' },
    { id: 'selune-case-2', title: '夏季保濕電商主圖', channel: '電商主圖', ctr: 3.1, notes: '淺色背景 + 水珠，強調長效保濕' },
  ],
  copyPresets: {
    gentle: { headline: ['一夜溫柔修護', '醒來透亮發光'], subhead: '7天感受透亮光采・專業修護配方*' },
    science: { headline: ['5重玻尿酸', '72H 長效鎖水'], subhead: '神經醯胺 × 5重玻尿酸｜科學配比深層保濕*' },
    playful: { headline: ['熬夜也不怕', '肌膚喝飽水！'], subhead: '水潤透亮一起帶走，買一送一只到月底*' },
    minimal: { headline: ['少即是多', '純粹修護'], subhead: '5重玻尿酸・無香精・敏感肌適用*' },
  },
};

export const MISTY_ISLE: Brand = {
  id: 'misty-isle',
  name: '霧嶼咖啡 MISTY ISLE',
  category: '冷萃咖啡',
  ciVersion: 'v1.4',
  palette: { primary: '#2F4A44', secondary: '#EEF0EC', accent: '#C8A27A', ink: '#1F2624' },
  fonts: { headline: 'Noto Serif TC', body: 'Noto Sans TC' },
  visualStyle: 'minimal Japanese cafe aesthetic, morning mist, matte ceramic surface, soft window light, clean geometric shadows',
  defaultTone: 'minimal',
  rules: { maxDeltaE: 5, minWhitespace: 0.4, productRatio: [0.2, 0.5] },
  bannedWords: ['治療', '保證', '減肥', '瘦身', '降血壓', '醫療', '根治'],
  replacements: { 治療: '舒緩', 保證: '', 減肥: '輕盈', 瘦身: '輕盈', 降血壓: '', 醫療: '', 根治: '' },
  claimWords: [],
  disclaimerPhrase: '',
  guidelineChunks: [
    { id: 'misty-isle#color', source: 'misty_isle_ci_v1.4.pdf', section: '§2 色彩', tag: 'color',
      text: '品牌主色「霧林綠」#2F4A44，輔助色「晨霧白」#EEF0EC、點綴色「牛皮紙棕」#C8A27A。整體低飽和，主色色差 ΔE2000 ≤ 5，避免高彩度藍綠與螢光色。' },
    { id: 'misty-isle#logo', source: 'misty_isle_ci_v1.4.pdf', section: '§3 Logo', tag: 'logo',
      text: 'Logo 淨空區至少 0.5 倍 Logo 高度；深色背景使用反白 Logo。' },
    { id: 'misty-isle#law', source: 'compliance_food_tw.md', section: '食品安全衛生管理法 §28', tag: 'law',
      text: '食品之標示、宣傳或廣告不得有不實、誇張或易生誤解之情形，亦不得宣稱醫療效能。禁用詞例：治療、減肥、瘦身、降血壓、保證。' },
    { id: 'misty-isle#layout', source: 'misty_isle_ci_v1.4.pdf', section: '§5 簡約版型', tag: 'layout',
      text: '留白 ≥ 40%，畫面只用一個主色；標題最多兩行，商品置於視覺重心。' },
    { id: 'misty-isle#font', source: 'misty_isle_ci_v1.4.pdf', section: '§4 字型', tag: 'font',
      text: '標題 Noto Serif TC，字距略寬；內文 Noto Sans TC Regular。' },
    { id: 'misty-isle#history', source: 'campaign_history/2025_summer_coldbrew.json', section: '2025 夏季冷萃素材成效', tag: 'history',
      text: '霧面陶瓷桌面 + 晨光側光的素材互動最佳，平均 CTR 3.8%；簡約文案優於促銷導向文案。' },
    { id: 'misty-isle#law-alt', source: 'compliance_food_tw.md', section: '合規替代用語對照', tag: 'law',
      text: '「治療疲勞」→ 刪除；「保證提神」→「一口清醒」；「減肥」「瘦身」→「輕盈無負擔」。' },
  ],
  caseStudies: [
    { id: 'misty-case-1', title: '2025 夏季冷萃 IG 貼文', channel: 'IG 貼文', ctr: 3.8, notes: '霧面陶瓷 + 晨光側光' },
  ],
  copyPresets: {
    minimal: { headline: ['一口清醒', '慢萃十八小時'], subhead: '單一產區耶加雪菲・低溫冷萃 18 小時' },
    gentle: { headline: ['把早晨', '留給自己'], subhead: '低酸順口・冷藏即飲' },
    science: { headline: ['18H 低溫萃取', '每瓶 120mg 咖啡因'], subhead: '單一產區・無添加糖・冷鏈配送' },
    playful: { headline: ['冰冰的', '剛剛好！'], subhead: '買二送一，辦公室續命必備' },
  },
};
```

- [ ] **Step 4: 實作 `web/src/lib/api/mock/data/products.ts`**

```ts
import type { Product } from '@/types/contract';

export const SAMPLE_PRODUCTS: Product[] = [
  {
    id: 'prod_selune_serum', brandId: 'selune', name: '極光玻尿酸修護精華 30ml',
    features: ['5重玻尿酸', '神經醯胺', '無香精', '敏感肌適用'],
    price: { sale: 1280, original: 1680 }, photo: { source: 'sample', art: 'serum' },
    createdAt: '2026-10-01T09:00:00.000Z',
  },
  {
    id: 'prod_misty_coldbrew', brandId: 'misty-isle', name: '單一產區冷萃咖啡 330ml',
    features: ['18小時冷萃', '單一產區', '無添加糖', '低酸順口'],
    price: { sale: 120, original: 150 }, photo: { source: 'sample', art: 'coldbrew' },
    createdAt: '2026-10-01T09:00:00.000Z',
  },
];
```

- [ ] **Step 5: 實作 `web/src/lib/api/mock/data/index.ts`**

```ts
import type { Brand } from '@/types/contract';
import { SELUNE, MISTY_ISLE } from './brands';

export { SELUNE, MISTY_ISLE } from './brands';
export { SAMPLE_PRODUCTS } from './products';

export const BRANDS: Brand[] = [SELUNE, MISTY_ISLE];

export function getBrandById(id: string): Brand {
  const brand = BRANDS.find((b) => b.id === id);
  if (!brand) throw new Error(`Unknown brand: ${id}`);
  return brand;
}
```

- [ ] **Step 6: 執行測試確認通過**

Run: `npx vitest run src/lib/api/mock/data`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/api/mock/data
git commit -m "feat: add demo brands (SÉLUNE, MISTY ISLE) and sample products" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: 規則型合規審查與計分

**Files:**
- Create: `web/src/lib/review/rules.ts`、`web/src/test/fixtures.ts`
- Test: `web/src/lib/review/rules.test.ts`

**Interfaces:**
- Consumes: `boxMap`（Task 4）；`areaRatio`、`verticalGap`（Task 4）；`deltaEHex`（Task 3）；`round1`、`clamp`（Task 1）；`SELUNE`、`MISTY_ISLE`（Task 5）
- Produces:
  - `findBannedWords(texts: string[], banned: string[]): string[]`（依禁用詞清單順序回傳命中的詞）
  - `hasClaim(texts: string[], claimWords: string[]): boolean`
  - `ragRefFor(brand: Brand, tag: RagTag): string | null`（略過 `-alt` 切塊）
  - `copyTexts(spec: PromptSpec): { id: LayoutElementId; text: string }[]`
  - `interface RuleContext { brand: Brand; spec: PromptSpec; measuredPrimary: string; ocrDiffs?: number }`
  - `runRuleChecks(ctx: RuleContext): ReviewCheck[]`：依序回傳 `banned_words`、`color_delta`、`logo_clearance`、`disclaimer`、`product_ratio`、`whitespace`、`ocr_typo`
  - `scoreChecks(checks: ReviewCheck[], jitter?: number): { score: number; passed: boolean }`：分數 = 100 − 14×fail − 6×warn − jitter（0–100），`passed` = 沒有 fail
  - 測試輔助 `makeSpec(overrides?: Partial<PromptSpec>, templateId?: TemplateId): PromptSpec`（SÉLUNE、合規文案、`computeLayout` 版面）

- [ ] **Step 1: 建立測試輔助 `web/src/test/fixtures.ts`**

```ts
import type { PromptSpec, TemplateId } from '@/types/contract';
import { computeLayout } from '@/lib/compose/layout';
import { getTemplate } from '@/lib/compose/templates';
import { SELUNE } from '@/lib/api/mock/data';

/** 一份「合規」的 SÉLUNE PromptSpec，測試時再用 overrides 製造問題 */
export function makeSpec(overrides: Partial<PromptSpec> = {}, templateId: TemplateId = 'ig-post'): PromptSpec {
  const t = getTemplate(templateId);
  return {
    jobId: 'job_test',
    round: 1,
    templateId: t.id,
    brandId: SELUNE.id,
    canvas: { width: t.width, height: t.height, ratio: t.ratio },
    palette: { ...SELUNE.palette },
    copy: {
      headline: ['一夜溫柔修護', '醒來透亮發光'],
      subhead: '7天感受透亮光采・專業修護配方*',
      features: ['5重玻尿酸', '神經醯胺', '無香精'],
      badge: { top: '週年慶限定', main: '買一送一', sub: 'BUY 1 GET 1' },
      price: { label: '週年慶活動價', sale: 1280, original: 1680 },
      productName: '極光玻尿酸修護精華 30ml',
      disclaimer: '*使用者感受，效果因個人膚況而異｜活動期間 2026/10/15–11/15',
    },
    layout: computeLayout(t),
    positivePrompt: 'test prompt',
    negativePrompt: 'lowres',
    injection: { engine: 'comfyui', workflowFile: 'workflows/product_scene_v1.json', params: [] },
    ragRefs: [],
    ...overrides,
  };
}
```

- [ ] **Step 2: 寫失敗測試 `web/src/lib/review/rules.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import type { ReviewCheck } from '@/types/contract';
import { SELUNE, MISTY_ISLE } from '@/lib/api/mock/data';
import { makeSpec } from '@/test/fixtures';
import { findBannedWords, hasClaim, ragRefFor, runRuleChecks, scoreChecks } from './rules';

const byId = (checks: ReviewCheck[], id: ReviewCheck['id']) => checks.find((c) => c.id === id)!;

describe('text rules', () => {
  it('finds banned words in list order', () => {
    expect(findBannedWords(['7天根治暗沉・醫療級修護'], SELUNE.bannedWords)).toEqual(['根治', '醫療級']);
    expect(findBannedWords(['一夜溫柔修護'], SELUNE.bannedWords)).toEqual([]);
  });

  it('detects effect claims', () => {
    expect(hasClaim(['醒來透亮發光'], SELUNE.claimWords)).toBe(true);
    expect(hasClaim(['一口清醒'], MISTY_ISLE.claimWords)).toBe(false);
  });

  it('ragRefFor skips the law-alt chunk', () => {
    expect(ragRefFor(SELUNE, 'law')).toBe('selune#law');
  });
});

describe('runRuleChecks', () => {
  it('passes all 7 rule checks for a compliant spec', () => {
    const checks = runRuleChecks({ brand: SELUNE, spec: makeSpec(), measuredPrimary: '#B76E79' });
    expect(checks.map((c) => c.id)).toEqual([
      'banned_words', 'color_delta', 'logo_clearance', 'disclaimer', 'product_ratio', 'whitespace', 'ocr_typo',
    ]);
    expect(checks.every((c) => c.status === 'pass' && c.kind === 'rule')).toBe(true);
  });

  it('fails banned words and points at the subhead', () => {
    const spec = makeSpec();
    spec.copy.subhead = '7天根治暗沉・醫療級修護';
    const c = byId(runRuleChecks({ brand: SELUNE, spec, measuredPrimary: '#B76E79' }), 'banned_words');
    expect(c.status).toBe('fail');
    expect(c.target).toBe('subhead');
    expect(c.value).toBe('禁用詞「根治」「醫療級」');
  });

  it('fails the color check for an off-brand pink', () => {
    const c = byId(runRuleChecks({ brand: SELUNE, spec: makeSpec(), measuredPrimary: '#E0458A' }), 'color_delta');
    expect(c.status).toBe('fail');
    expect(c.value).toContain('#E0458A');
  });

  it('fails logo clearance when the logo is pushed into the headline', () => {
    const spec = makeSpec();
    const logo = spec.layout.find((b) => b.id === 'logo')!;
    const head = spec.layout.find((b) => b.id === 'headline')!;
    logo.bbox[1] = head.bbox[1] - Math.round(logo.bbox[3] * 0.55);
    const c = byId(runRuleChecks({ brand: SELUNE, spec, measuredPrimary: '#B76E79' }), 'logo_clearance');
    expect(c.status).toBe('fail');
    expect(c.value).toBe('與標題重疊 36px');
  });

  it('warns when an effect claim has no disclaimer; brands without claims pass', () => {
    const spec = makeSpec();
    spec.copy.disclaimer = '活動期間 2026/10/15–11/15';
    expect(byId(runRuleChecks({ brand: SELUNE, spec, measuredPrimary: '#B76E79' }), 'disclaimer').status).toBe('warn');

    const coffee = makeSpec({ brandId: MISTY_ISLE.id, palette: { ...MISTY_ISLE.palette } });
    coffee.copy.headline = ['一口清醒', '慢萃十八小時'];
    coffee.copy.subhead = '單一產區耶加雪菲・低溫冷萃 18 小時';
    coffee.copy.disclaimer = '圖片僅供參考';
    const checks = runRuleChecks({ brand: MISTY_ISLE, spec: coffee, measuredPrimary: '#2F4A44' });
    expect(byId(checks, 'disclaimer').value).toBe('無效果宣稱');
    expect(checks.every((c) => c.status === 'pass')).toBe(true);
  });

  it('fails OCR when diffs are reported', () => {
    const c = byId(runRuleChecks({ brand: SELUNE, spec: makeSpec(), measuredPrimary: '#B76E79', ocrDiffs: 2 }), 'ocr_typo');
    expect(c.status).toBe('fail');
  });
});

describe('scoreChecks', () => {
  const mk = (status: ReviewCheck['status']): ReviewCheck => ({
    id: 'banned_words', name: 'x', kind: 'rule', rule: 'x', value: 'x', status, target: null, ragRef: null,
  });

  it('subtracts 14 per fail, 6 per warn and the jitter', () => {
    expect(scoreChecks([mk('pass'), mk('pass')], 2)).toEqual({ score: 98, passed: true });
    expect(scoreChecks([mk('fail'), mk('fail'), mk('warn')])).toEqual({ score: 66, passed: false });
    expect(scoreChecks(Array.from({ length: 10 }, () => mk('fail'))).score).toBe(0);
  });
});
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `npx vitest run src/lib/review/rules.test.ts`
Expected: FAIL，找不到 `./rules`

- [ ] **Step 4: 實作 `web/src/lib/review/rules.ts`**

```ts
import type { Brand, LayoutElementId, PromptSpec, RagTag, ReviewCheck } from '@/types/contract';
import { boxMap } from '@/lib/compose/layout';
import { areaRatio, verticalGap } from '@/lib/core/geometry';
import { clamp, round1 } from '@/lib/core/num';
import { deltaEHex } from './color';

export function findBannedWords(texts: string[], banned: string[]): string[] {
  const joined = texts.join('\n');
  return banned.filter((w) => w !== '' && joined.includes(w));
}

export function hasClaim(texts: string[], claimWords: string[]): boolean {
  const joined = texts.join('\n');
  return claimWords.some((w) => joined.includes(w));
}

export function ragRefFor(brand: Brand, tag: RagTag): string | null {
  return brand.guidelineChunks.find((c) => c.tag === tag && !c.id.endsWith('-alt'))?.id ?? null;
}

/** 依版面元素拆出文案，讓禁用詞檢查能指出出現在哪個區塊 */
export function copyTexts(spec: PromptSpec): { id: LayoutElementId; text: string }[] {
  const c = spec.copy;
  return [
    { id: 'headline', text: c.headline.join('') },
    { id: 'subhead', text: c.subhead },
    { id: 'features', text: c.features.join('、') },
    { id: 'badge', text: `${c.badge.top}${c.badge.main}` },
    { id: 'disclaimer', text: c.disclaimer },
  ];
}

export interface RuleContext {
  brand: Brand;
  spec: PromptSpec;
  /** 從生成圖中偵測到的主色（第二階段由影像分析取得） */
  measuredPrimary: string;
  /** OCR 結果與文案的差異字數 */
  ocrDiffs?: number;
}

export function runRuleChecks({ brand, spec, measuredPrimary, ocrDiffs = 0 }: RuleContext): ReviewCheck[] {
  const B = boxMap(spec.layout);
  const { width: W, height: H } = spec.canvas;
  const pct = (v: number) => `${round1(v * 100)}%`;

  const texts = copyTexts(spec);
  const banned = findBannedWords(texts.map((t) => t.text), brand.bannedWords);
  const bannedTarget = texts.find((t) => banned.some((w) => t.text.includes(w)))?.id ?? null;

  const dE = deltaEHex(measuredPrimary, brand.palette.primary);

  const gap = verticalGap(B.logo, B.headline);
  const need = Math.round(B.logo.h * 0.5);

  const claim = hasClaim([spec.copy.headline.join(''), spec.copy.subhead], brand.claimWords);
  const hasNote = brand.disclaimerPhrase !== '' && spec.copy.disclaimer.includes(brand.disclaimerPhrase);

  const prod = areaRatio(B.product, W, H);
  const [lo, hi] = brand.rules.productRatio;
  const whitespace = 1 - Object.values(B).reduce((s, r) => s + areaRatio(r, W, H), 0);

  return [
    {
      id: 'banned_words', name: '禁用詞檢查', kind: 'rule', rule: '品牌禁用詞庫與法規用語',
      value: banned.length ? `禁用詞${banned.map((w) => `「${w}」`).join('')}` : '未偵測到禁用詞',
      status: banned.length ? 'fail' : 'pass', target: bannedTarget, ragRef: ragRefFor(brand, 'law'),
    },
    {
      id: 'color_delta', name: '品牌主色色差', kind: 'rule', rule: `ΔE2000 ≤ ${brand.rules.maxDeltaE}`,
      value: `ΔE ${round1(dE)} · 偵測主色 ${measuredPrimary.toUpperCase()}`,
      status: dE <= brand.rules.maxDeltaE ? 'pass' : 'fail', target: 'canvas', ragRef: ragRefFor(brand, 'color'),
    },
    {
      id: 'logo_clearance', name: 'Logo 淨空區', kind: 'rule', rule: `間距 ≥ 0.5 × Logo 高（${need}px）`,
      value: gap < 0 ? `與標題重疊 ${-gap}px` : `間距 ${gap}px`,
      status: gap >= need ? 'pass' : 'fail', target: 'logo', ragRef: ragRefFor(brand, 'logo'),
    },
    {
      id: 'disclaimer', name: '效果宣稱註記', kind: 'rule',
      rule: brand.disclaimerPhrase ? `效果宣稱需加註「${brand.disclaimerPhrase}」` : '效果宣稱需加註說明',
      value: !claim ? '無效果宣稱' : hasNote ? '已加註' : '含效果宣稱但缺少註記',
      status: !claim || hasNote ? 'pass' : 'warn', target: 'disclaimer', ragRef: ragRefFor(brand, 'law'),
    },
    {
      id: 'product_ratio', name: '商品主體佔比', kind: 'rule', rule: `${round1(lo * 100)}% – ${round1(hi * 100)}%`,
      value: pct(prod), status: prod >= lo && prod <= hi ? 'pass' : 'fail', target: 'product', ragRef: ragRefFor(brand, 'layout'),
    },
    {
      id: 'whitespace', name: '留白比例', kind: 'rule', rule: `≥ ${round1(brand.rules.minWhitespace * 100)}%`,
      value: pct(whitespace), status: whitespace >= brand.rules.minWhitespace ? 'pass' : 'fail', target: null,
      ragRef: ragRefFor(brand, 'layout'),
    },
    {
      id: 'ocr_typo', name: 'OCR 錯字比對', kind: 'rule', rule: '渲染文字與文案逐字比對',
      value: `${ocrDiffs} 處差異`, status: ocrDiffs === 0 ? 'pass' : 'fail', target: 'headline', ragRef: null,
    },
  ];
}

export function scoreChecks(checks: ReviewCheck[], jitter = 0): { score: number; passed: boolean } {
  const fails = checks.filter((c) => c.status === 'fail').length;
  const warns = checks.filter((c) => c.status === 'warn').length;
  return { score: clamp(Math.round(100 - fails * 14 - warns * 6 - jitter), 0, 100), passed: fails === 0 };
}
```

- [ ] **Step 5: 執行測試確認通過**

Run: `npx vitest run src/lib/review`
Expected: `color.test.ts` 與 `rules.test.ts` 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/review/rules.ts web/src/lib/review/rules.test.ts web/src/test/fixtures.ts
git commit -m "feat: add rule-based compliance checks and scoring" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: 模擬 Agent 需求拆解 `parseBrief`

**Files:**
- Create: `web/src/lib/api/mock/brief.ts`
- Test: `web/src/lib/api/mock/brief.test.ts`

**Interfaces:**
- Consumes: `Brand`、`Product`、`ParsedBrief`、`Tone`（Task 2）；`SELUNE`、`MISTY_ISLE`、`SAMPLE_PRODUCTS`（Task 5）
- Produces: `parseBrief(text: string, brand: Brand, product: Product | null): ParsedBrief`。這是以關鍵字規則模擬 LLM 的需求拆解，第二階段由後端 LLM 取代，輸出格式不變

- [ ] **Step 1: 寫失敗測試 `web/src/lib/api/mock/brief.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import { SELUNE, MISTY_ISLE, SAMPLE_PRODUCTS } from './data';
import { parseBrief } from './brief';

const serum = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_selune_serum')!;
const coldbrew = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_misty_coldbrew')!;

describe('parseBrief', () => {
  it('parses the spec demo sentence for cold brew', () => {
    expect(parseBrief('幫我設計一款簡約風格的冷萃咖啡宣傳海報', MISTY_ISLE, coldbrew)).toEqual({
      productName: '單一產區冷萃咖啡 330ml',
      sellingPoints: ['18小時冷萃', '單一產區', '無添加糖'],
      audience: '一般消費者',
      tone: 'minimal',
      campaign: null,
      offer: null,
      style: ['minimal'],
    });
  });

  it('extracts campaign, offer, tone and style for skincare', () => {
    const b = parseBrief('週年慶檔期主打買一送一，強調保濕與透亮，整體調性溫柔療癒、有高級感。', SELUNE, serum);
    expect(b.tone).toBe('gentle');
    expect(b.campaign).toBe('週年慶');
    expect(b.offer).toBe('買一送一');
    expect(b.style).toEqual(['premium', 'soft', 'healing']);
  });

  it('extracts audience, normalises offers and falls back to the brand tone', () => {
    const b = parseBrief('針對 25 歲上班族，中秋節第二件 6 折，清新一點', SELUNE, serum);
    expect(b.audience).toBe('25 歲上班族');
    expect(b.campaign).toBe('中秋');
    expect(b.offer).toBe('第二件6折');
    expect(b.style).toEqual(['fresh']);
    expect(b.tone).toBe(SELUNE.defaultTone);
  });

  it('puts features mentioned in the brief first', () => {
    expect(parseBrief('主打無香精', SELUNE, serum).sellingPoints).toEqual(['無香精', '5重玻尿酸', '神經醯胺']);
    expect(parseBrief('隨便', SELUNE, null)).toMatchObject({ productName: null, sellingPoints: [] });
  });
});
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `npx vitest run src/lib/api/mock/brief.test.ts`
Expected: FAIL，找不到 `./brief`

- [ ] **Step 3: 實作 `web/src/lib/api/mock/brief.ts`**

```ts
import type { Brand, ParsedBrief, Product, Tone } from '@/types/contract';

/** 依序比對，第一個命中的規則決定語氣 */
const TONE_RULES: [RegExp, Tone][] = [
  [/簡約|極簡|minimal/i, 'minimal'],
  [/溫柔|療癒|柔和/, 'gentle'],
  [/科研|專業|成分|科學/, 'science'],
  [/活潑|年輕|可愛|有趣/, 'playful'],
];

const STYLE_WORDS: [zh: string, en: string][] = [
  ['簡約', 'minimal'], ['高級感', 'premium'], ['溫柔', 'soft'], ['清新', 'fresh'],
  ['奢華', 'luxury'], ['復古', 'vintage'], ['療癒', 'healing'], ['科技感', 'futuristic'],
];

const CAMPAIGN_RE = /週年慶|雙\s*11|中秋|母親節|聖誕|新品上市|夏季|開學/;
const OFFER_RE = /買一送一|買二送一|第二件\s*\d+(?:\.\d+)?\s*折|\d+(?:\.\d+)?\s*折/;
const AUDIENCE_RE = /(?:給|針對|適合)([^，。,.！!]+)/;

/** 以關鍵字規則模擬 LLM 的需求拆解（第二階段改由後端 LLM 產生同格式結果） */
export function parseBrief(text: string, brand: Brand, product: Product | null): ParsedBrief {
  const tone = TONE_RULES.find(([re]) => re.test(text))?.[1] ?? brand.defaultTone;
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

- [ ] **Step 4: 執行測試確認通過**

Run: `npx vitest run src/lib/api/mock/brief.test.ts`
Expected: 4 個測試 PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/api/mock/brief.ts web/src/lib/api/mock/brief.test.ts
git commit -m "feat: add mock brief parser for one-sentence requests" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Prompt 構建、修正策略與版本差異

**Files:**
- Create: `web/src/lib/agent/prompt.ts`、`web/src/lib/agent/fixes.ts`、`web/src/lib/agent/diff.ts`
- Test: `web/src/lib/agent/prompt.test.ts`、`web/src/lib/agent/fixes.test.ts`、`web/src/lib/agent/diff.test.ts`

**Interfaces:**
- Consumes: `computeLayout`（Task 4）；`hasClaim`、`findBannedWords`、`copyTexts`、`runRuleChecks`（Task 6）；`parseBrief`（Task 7）；`makeSpec`（Task 6 fixture）
- Produces:
  - `CAMPAIGN_PERIOD: string`、`BASE_NEGATIVE: string`
  - `makeBadge(brief: ParsedBrief): Copy['badge']`、`buildCopy(brand: Brand, product: Product, brief: ParsedBrief): Copy`
  - `interface PromptBuildInput { jobId: string; round: number; brand: Brand; product: Product; brief: ParsedBrief; template: ChannelTemplate; engine: Engine; seed: number; ragRefs: string[]; fixes: CheckId[] }`
  - `buildPromptSpec(input: PromptBuildInput): PromptSpec`
  - `buildInjection(spec: Pick<PromptSpec, 'positivePrompt' | 'negativePrompt' | 'canvas' | 'layout'>, engine: Engine, productId: string, seed: number): ComfyInjection`
  - `setParam(injection: ComfyInjection, label: string, value: string | number): ComfyInjection`（回傳新物件）、`seedOf(spec: PromptSpec): number`
  - `planFixes(checks: ReviewCheck[], brand: Brand, spec: PromptSpec): Fix[]`（同標題只保留一筆）
  - `interface SpecDiff { path: string; before: string; after: string }`、`diffSpecs(a: PromptSpec, b: PromptSpec): SpecDiff[]`

- [ ] **Step 1: 寫失敗測試 `web/src/lib/agent/prompt.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import { SELUNE, MISTY_ISLE, SAMPLE_PRODUCTS } from '@/lib/api/mock/data';
import { parseBrief } from '@/lib/api/mock/brief';
import { getTemplate } from '@/lib/compose/templates';
import { BASE_NEGATIVE, buildPromptSpec, seedOf, setParam, type PromptBuildInput } from './prompt';

const serum = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_selune_serum')!;
const coldbrew = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_misty_coldbrew')!;

const input = (over: Partial<PromptBuildInput> = {}): PromptBuildInput => ({
  jobId: 'job_t', round: 1, brand: SELUNE, product: serum,
  brief: parseBrief('週年慶主打買一送一，溫柔療癒', SELUNE, serum),
  template: getTemplate('ig-post'), engine: 'comfyui', seed: 123456789, ragRefs: ['selune#color'], fixes: [],
  ...over,
});
const param = (spec: ReturnType<typeof buildPromptSpec>, label: string) =>
  spec.injection.params.find((p) => p.label === label)?.value;

describe('buildPromptSpec', () => {
  it('builds a compliant SÉLUNE spec from the brand CI and brief', () => {
    const spec = buildPromptSpec(input());
    expect(spec.palette).toEqual(SELUNE.palette);
    expect(spec.layout).toHaveLength(8);
    expect(spec.copy.headline).toEqual(['一夜溫柔修護', '醒來透亮發光']);
    expect(spec.copy.features).toEqual(['5重玻尿酸', '神經醯胺', '無香精']);
    expect(spec.copy.badge).toEqual({ top: '週年慶限定', main: '買一送一', sub: 'BUY 1 GET 1' });
    expect(spec.copy.price).toEqual({ label: '週年慶活動價', sale: 1280, original: 1680 });
    expect(spec.copy.disclaimer).toBe('*使用者感受，效果因個人膚況而異｜活動期間 2026/10/15–11/15｜數量有限，售完為止');
    expect(spec.negativePrompt).toBe(BASE_NEGATIVE);
    expect(spec.ragRefs).toEqual(['selune#color']);
  });

  it('injects prompt, seed, size and layout boxes into the ComfyUI workflow', () => {
    const spec = buildPromptSpec(input());
    expect(spec.injection.workflowFile).toBe('workflows/product_scene_v1.json');
    expect(param(spec, 'positive_prompt')).toBe(spec.positivePrompt);
    expect(param(spec, 'width')).toBe(1440);
    expect(param(spec, 'height')).toBe(1800);
    expect(seedOf(spec)).toBe(123456789);
    expect(JSON.parse(String(param(spec, 'layout_boxes')))).toHaveLength(8);
  });

  it('builds an Ideogram request body when engine is ideogram', () => {
    const spec = buildPromptSpec(input({ engine: 'ideogram' }));
    expect(spec.injection.workflowFile).toBe('ideogram/v4/generate');
    expect(param(spec, 'aspect_ratio')).toBe('4:5');
    expect(seedOf(spec)).toBe(123456789);
  });

  it('keeps the brand palette and strengthens the negative prompt after failures', () => {
    const spec = buildPromptSpec(input({ round: 2, fixes: ['color_delta', 'color_delta', 'vlm_occlusion'] }));
    expect(spec.palette).toEqual(SELUNE.palette);
    expect(spec.negativePrompt).toBe(
      `${BASE_NEGATIVE}, oversaturated, neon, off-brand colors, cluttered composition, overlapping elements`,
    );
    expect(param(spec, 'negative_prompt')).toBe(spec.negativePrompt);
  });

  it('builds minimal coffee copy with no claim note and a default badge', () => {
    const brief = parseBrief('幫我設計一款簡約風格的冷萃咖啡宣傳海報', MISTY_ISLE, coldbrew);
    const spec = buildPromptSpec(input({ brand: MISTY_ISLE, product: coldbrew, brief }));
    expect(spec.copy.headline).toEqual(['一口清醒', '慢萃十八小時']);
    expect(spec.copy.disclaimer).toBe('圖片僅供參考');
    expect(spec.copy.badge).toEqual({ top: '期間限定', main: '限時優惠', sub: 'LIMITED OFFER' });
    expect(spec.copy.price.label).toBe('限時活動價');
    expect(spec.positivePrompt).toContain('minimal');
  });

  it('setParam returns a new injection with the updated value', () => {
    const spec = buildPromptSpec(input());
    const next = setParam(spec.injection, 'seed', 7);
    expect(next.params.find((p) => p.label === 'seed')?.value).toBe(7);
    expect(seedOf(spec)).toBe(123456789);
  });
});
```

- [ ] **Step 2: 寫失敗測試 `web/src/lib/agent/fixes.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import type { ReviewCheck } from '@/types/contract';
import { SELUNE } from '@/lib/api/mock/data';
import { runRuleChecks } from '@/lib/review/rules';
import { makeSpec } from '@/test/fixtures';
import { planFixes } from './fixes';

const vlm = (id: ReviewCheck['id'], status: ReviewCheck['status']): ReviewCheck => ({
  id, name: id, kind: 'vlm', rule: '', value: '', status, target: null, ragRef: null,
});

describe('planFixes', () => {
  it('maps failed checks to fixes, using the brand replacement table for copy', () => {
    const spec = makeSpec();
    spec.copy.subhead = '7天根治暗沉・醫療級修護';
    const checks = runRuleChecks({ brand: SELUNE, spec, measuredPrimary: '#E0458A' });
    const fixes = planFixes(checks, SELUNE, spec);
    expect(fixes.map((f) => f.title)).toEqual(['文案改寫', '色彩修正']);
    expect(fixes[0]).toEqual({
      checkId: 'banned_words', title: '文案改寫',
      desc: '依合規替代用語改寫：「根治」→「改善外觀」、「醫療級」→「專業配方」',
    });
  });

  it('dedupes fixes with the same title and ignores passing checks', () => {
    const spec = makeSpec();
    spec.copy.subhead = '保證有效';
    const fixes = planFixes(
      [vlm('banned_words', 'fail'), vlm('vlm_exaggeration', 'fail'), vlm('vlm_quality', 'pass')],
      SELUNE, spec,
    );
    expect(fixes).toEqual([{ checkId: 'banned_words', title: '文案改寫', desc: '依合規替代用語改寫：「保證有效」→刪除' }]);
    expect(planFixes([vlm('vlm_quality', 'pass')], SELUNE, spec)).toEqual([]);
  });
});
```

- [ ] **Step 3: 寫失敗測試 `web/src/lib/agent/diff.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import { makeSpec } from '@/test/fixtures';
import { diffSpecs } from './diff';

describe('diffSpecs', () => {
  it('returns nothing for identical specs', () => {
    expect(diffSpecs(makeSpec(), makeSpec())).toEqual([]);
  });

  it('lists changed fields in a fixed order with readable values', () => {
    const b = makeSpec();
    b.palette = { ...b.palette, primary: '#E0458A' };
    b.copy.subhead = '7天根治暗沉・醫療級修護';
    b.layout.find((x) => x.id === 'logo')!.bbox[1] = 171;
    expect(diffSpecs(makeSpec(), b)).toEqual([
      { path: 'palette.primary', before: '#B76E79', after: '#E0458A' },
      { path: 'layout[logo].bbox', before: '[101, 90, 374, 81]', after: '[101, 171, 374, 81]' },
      { path: 'copy.subhead', before: '7天感受透亮光采・專業修護配方*', after: '7天根治暗沉・醫療級修護' },
    ]);
  });
});
```

- [ ] **Step 4: 執行測試確認失敗**

Run: `npx vitest run src/lib/agent`
Expected: FAIL，找不到 `./prompt`、`./fixes`、`./diff`

- [ ] **Step 5: 實作 `web/src/lib/agent/prompt.ts`**

```ts
import type {
  Brand, ChannelTemplate, CheckId, ComfyInjection, Copy, Engine, ParsedBrief, Product, PromptSpec,
} from '@/types/contract';
import { computeLayout } from '@/lib/compose/layout';
import { hasClaim } from '@/lib/review/rules';

export const CAMPAIGN_PERIOD = '活動期間 2026/10/15–11/15';
export const BASE_NEGATIVE = 'lowres, blurry, watermark, deformed product, extra objects, garbled text';

const OFFER_SUB: [RegExp, string][] = [
  [/買一送一/, 'BUY 1 GET 1'],
  [/買二送一/, 'BUY 2 GET 1'],
  [/折/, 'SPECIAL PRICE'],
];

/** 上一輪未通過的檢查 → 這一輪 negative prompt 要加強的詞 */
const NEGATIVE_BY_FIX: Partial<Record<CheckId, string>> = {
  color_delta: 'oversaturated, neon, off-brand colors',
  vlm_occlusion: 'cluttered composition, overlapping elements',
  vlm_quality: 'overexposed highlights',
};

export function makeBadge(brief: ParsedBrief): Copy['badge'] {
  const offer = brief.offer;
  return {
    top: brief.campaign ? `${brief.campaign}限定` : '期間限定',
    main: offer ?? '限時優惠',
    sub: (offer && OFFER_SUB.find(([re]) => re.test(offer))?.[1]) || 'LIMITED OFFER',
  };
}

export function buildCopy(brand: Brand, product: Product, brief: ParsedBrief): Copy {
  const preset = brand.copyPresets[brief.tone];
  const headline: [string, string] = [preset.headline[0], preset.headline[1]];
  const claim = hasClaim([headline.join(''), preset.subhead], brand.claimWords);
  const notes = [
    claim && brand.disclaimerPhrase ? `*使用者感受，${brand.disclaimerPhrase}` : null,
    brief.campaign ? CAMPAIGN_PERIOD : null,
    brief.offer ? '數量有限，售完為止' : null,
  ].filter((s): s is string => s !== null);

  return {
    headline,
    subhead: preset.subhead,
    features: (brief.sellingPoints.length ? brief.sellingPoints : product.features).slice(0, 3),
    badge: makeBadge(brief),
    price: { label: `${brief.campaign ?? '限時'}活動價`, sale: product.price.sale, original: product.price.original },
    productName: product.name,
    disclaimer: notes.length ? notes.join('｜') : '圖片僅供參考',
  };
}

export interface PromptBuildInput {
  jobId: string;
  round: number;
  brand: Brand;
  product: Product;
  brief: ParsedBrief;
  template: ChannelTemplate;
  engine: Engine;
  seed: number;
  ragRefs: string[];
  /** 上一輪未通過的檢查 id，用來加強 negative prompt */
  fixes: CheckId[];
}

export function buildInjection(
  spec: Pick<PromptSpec, 'positivePrompt' | 'negativePrompt' | 'canvas' | 'layout'>,
  engine: Engine,
  productId: string,
  seed: number,
): ComfyInjection {
  const { width, height, ratio } = spec.canvas;
  if (engine === 'ideogram') {
    return {
      engine,
      workflowFile: 'ideogram/v4/generate',
      params: [
        { nodeId: 'body', input: 'prompt', label: 'positive_prompt', value: spec.positivePrompt },
        { nodeId: 'body', input: 'negative_prompt', label: 'negative_prompt', value: spec.negativePrompt },
        { nodeId: 'body', input: 'aspect_ratio', label: 'aspect_ratio', value: ratio },
        { nodeId: 'body', input: 'style_type', label: 'style_type', value: 'DESIGN' },
        { nodeId: 'body', input: 'seed', label: 'seed', value: seed },
        { nodeId: 'body', input: 'image_reference', label: 'product_image', value: `${productId}.png` },
      ],
    };
  }
  return {
    engine,
    workflowFile: 'workflows/product_scene_v1.json',
    params: [
      { nodeId: '4', input: 'ckpt_name', label: 'checkpoint', value: 'sd_xl_base_1.0.safetensors' },
      { nodeId: '6', input: 'text', label: 'positive_prompt', value: spec.positivePrompt },
      { nodeId: '7', input: 'text', label: 'negative_prompt', value: spec.negativePrompt },
      { nodeId: '10', input: 'image', label: 'product_image', value: `${productId}.png` },
      { nodeId: '11', input: 'model', label: 'cutout_model', value: 'BiRefNet-general' },
      { nodeId: '14', input: 'strength', label: 'controlnet_depth', value: 0.65 },
      { nodeId: '15', input: 'weight', label: 'ip_adapter_style', value: 0.55 },
      { nodeId: '20', input: 'width', label: 'width', value: width },
      { nodeId: '20', input: 'height', label: 'height', value: height },
      { nodeId: '3', input: 'seed', label: 'seed', value: seed },
      { nodeId: '3', input: 'sampler_name', label: 'sampler', value: 'dpmpp_2m_sde' },
      { nodeId: '3', input: 'steps', label: 'steps', value: 28 },
      { nodeId: '3', input: 'cfg', label: 'cfg', value: 6 },
      { nodeId: '30', input: 'light_direction', label: 'ic_light', value: 'top-left' },
      { nodeId: '40', input: 'boxes', label: 'layout_boxes', value: JSON.stringify(spec.layout.map((b) => [b.id, ...b.bbox])) },
    ],
  };
}

export function setParam(injection: ComfyInjection, label: string, value: string | number): ComfyInjection {
  return { ...injection, params: injection.params.map((p) => (p.label === label ? { ...p, value } : p)) };
}

export const seedOf = (spec: PromptSpec): number =>
  Number(spec.injection.params.find((p) => p.label === 'seed')?.value ?? 0);

export function buildPromptSpec(input: PromptBuildInput): PromptSpec {
  const { brand, product, brief, template } = input;
  const palette = { ...brand.palette };
  const layout = computeLayout(template);
  const positivePrompt = [
    `${template.ratio} commercial product photography`,
    'the provided product photo on a styled surface',
    brand.visualStyle,
    `${palette.primary} and ${palette.secondary} color palette with ${palette.accent} accents`,
    ...brief.style,
    'clean negative space for typography',
    'high-end editorial lighting',
  ].join(', ');
  const extra = [...new Set(input.fixes)]
    .map((id) => NEGATIVE_BY_FIX[id])
    .filter((s): s is string => s !== undefined);
  const negativePrompt = [BASE_NEGATIVE, ...extra].join(', ');
  const canvas = { width: template.width, height: template.height, ratio: template.ratio };

  return {
    jobId: input.jobId,
    round: input.round,
    templateId: template.id,
    brandId: brand.id,
    canvas,
    palette,
    copy: buildCopy(brand, product, brief),
    layout,
    positivePrompt,
    negativePrompt,
    injection: buildInjection({ positivePrompt, negativePrompt, canvas, layout }, input.engine, product.id, input.seed),
    ragRefs: [...input.ragRefs],
  };
}
```

- [ ] **Step 6: 實作 `web/src/lib/agent/fixes.ts`**

```ts
import type { Brand, CheckId, Fix, PromptSpec, ReviewCheck } from '@/types/contract';
import { copyTexts, findBannedWords } from '@/lib/review/rules';

/** 審查未通過 → Query Rewriting 要採取的修正策略（同標題只保留第一筆） */
export function planFixes(checks: ReviewCheck[], brand: Brand, spec: PromptSpec): Fix[] {
  const fixes: Fix[] = [];
  const add = (checkId: CheckId, title: string, desc: string) => {
    if (!fixes.some((f) => f.title === title)) fixes.push({ checkId, title, desc });
  };

  for (const c of checks.filter((x) => x.status !== 'pass')) {
    switch (c.id) {
      case 'banned_words':
      case 'vlm_exaggeration': {
        const words = findBannedWords(copyTexts(spec).map((t) => t.text), brand.bannedWords);
        const pairs = words.map((w) => `「${w}」→${brand.replacements[w] ? `「${brand.replacements[w]}」` : '刪除'}`);
        add(c.id, '文案改寫', pairs.length ? `依合規替代用語改寫：${pairs.join('、')}` : '移除誇大用語，改為使用者感受描述');
        break;
      }
      case 'color_delta':
        add(c.id, '色彩修正', `鎖定品牌 CI 色票（primary ${brand.palette.primary}），negative_prompt 加入 oversaturated / neon / off-brand colors`);
        break;
      case 'logo_clearance':
        add(c.id, '版面修正', 'Logo 回到網格起點，與標題保留 ≥ 0.5 × Logo 高的淨空區');
        break;
      case 'disclaimer':
        add(c.id, '補充註記', `效果宣稱句尾加「*」，頁尾加註「${brand.disclaimerPhrase || '效果說明'}」`);
        break;
      case 'vlm_occlusion':
        add(c.id, '構圖修正', '拉開商品與文字區塊的距離，negative_prompt 加入 cluttered composition');
        break;
      case 'vlm_quality':
        add(c.id, '畫質修正', '降低高光強度，negative_prompt 加入 overexposed highlights');
        break;
      case 'product_ratio':
      case 'whitespace':
        add(c.id, '版面比例修正', '調整商品主體縮放，維持品牌規範的佔比與留白');
        break;
      case 'ocr_typo':
        add(c.id, '文字重繪', '改由排版引擎重新繪製文字圖層');
        break;
    }
  }
  return fixes;
}
```

- [ ] **Step 7: 實作 `web/src/lib/agent/diff.ts`**

```ts
import type { LayoutElementId, PromptSpec } from '@/types/contract';

export interface SpecDiff { path: string; before: string; after: string }

const fmtBox = (spec: PromptSpec, id: LayoutElementId) => {
  const b = spec.layout.find((x) => x.id === id);
  return b ? `[${b.bbox.join(', ')}]` : '(無)';
};

/** 兩版 Prompt 之間，重試紀錄要顯示的欄位差異（固定順序） */
export function diffSpecs(a: PromptSpec, b: PromptSpec): SpecDiff[] {
  const rows: [path: string, before: string, after: string][] = [
    ['palette.primary', a.palette.primary, b.palette.primary],
    ['palette.secondary', a.palette.secondary, b.palette.secondary],
    ['layout[logo].bbox', fmtBox(a, 'logo'), fmtBox(b, 'logo')],
    ['copy.subhead', a.copy.subhead, b.copy.subhead],
    ['copy.disclaimer', a.copy.disclaimer, b.copy.disclaimer],
    ['negativePrompt', a.negativePrompt, b.negativePrompt],
  ];
  return rows.filter(([, x, y]) => x !== y).map(([path, before, after]) => ({ path, before, after }));
}
```

- [ ] **Step 8: 執行測試確認通過**

Run: `npx vitest run src/lib/agent && npm run typecheck`
Expected: 3 個測試檔全部 PASS；typecheck 無錯誤

- [ ] **Step 9: Commit**

```bash
git add web/src/lib/agent
git commit -m "feat: add prompt builder, rewrite fixes and spec diff" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: 模擬失誤、模擬 VLM 與審查執行器

**Files:**
- Create: `web/src/lib/api/mock/flaws.ts`、`web/src/lib/api/mock/vlm.ts`、`web/src/lib/api/mock/review.ts`
- Modify: `web/src/test/fixtures.ts`（加入 `cleanSpec`）
- Test: `web/src/lib/api/mock/flaws.test.ts`、`web/src/lib/api/mock/review.test.ts`

**Interfaces:**
- Consumes: `setParam`、`buildPromptSpec`（Task 8）；`boxMap`（Task 4）；`verticalGap`（Task 4）；`copyTexts`、`findBannedWords`、`ragRefFor`、`runRuleChecks`、`scoreChecks`（Task 6）；`mixHex`（Task 3）；`mulberry32`（Task 1）
- Produces:
  - `FLAWS: readonly ['offPalette', 'bannedCopy', 'logoCrowding', 'missingDisclaimer']`、`type Flaw`
  - `FLAW_DATA: Record<string, { offPalette: Palette; bannedSubhead: string }>`
  - `applyFlaws(spec: PromptSpec, flaws: readonly Flaw[]): PromptSpec`（不修改輸入；未知品牌 throw）
  - `mockVlmChecks(spec: PromptSpec, brand: Brand, variant: number): ReviewCheck[]`：依序 `vlm_exaggeration`、`vlm_occlusion`、`vlm_quality`。乾淨的 spec：variant % 4 === 1 → 遮擋 warn；variant % 4 === 2 → 畫質 warn
  - `interface ReviewResult { checks: ReviewCheck[]; score: number; passed: boolean; measuredPrimary: string }`、`reviewRender(spec: PromptSpec, brand: Brand, variant: number, seed: number): ReviewResult`（7 項規則 + 3 項 VLM = 10 項）
  - 測試輔助 `cleanSpec(brand?: Brand, product?: Product, templateId?: TemplateId): PromptSpec`（由 `buildPromptSpec` 產生的合規 spec，預設 SÉLUNE 精華液、IG 貼文）

- [ ] **Step 1: 在 `web/src/test/fixtures.ts` 檔尾加入 `cleanSpec`**

把檔案開頭的 import 區改成：

```ts
import type { Brand, Product, PromptSpec, TemplateId } from '@/types/contract';
import { buildPromptSpec } from '@/lib/agent/prompt';
import { parseBrief } from '@/lib/api/mock/brief';
import { computeLayout } from '@/lib/compose/layout';
import { getTemplate } from '@/lib/compose/templates';
import { SAMPLE_PRODUCTS, SELUNE } from '@/lib/api/mock/data';
```

`makeSpec` 維持不變。在檔尾加入：

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

- [ ] **Step 2: 寫失敗測試 `web/src/lib/api/mock/flaws.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import { cleanSpec } from '@/test/fixtures';
import { SELUNE } from './data';
import { applyFlaws, FLAWS } from './flaws';

describe('applyFlaws', () => {
  it('applies every flaw without mutating the input', () => {
    const spec = cleanSpec();
    const bad = applyFlaws(spec, FLAWS);
    expect(spec.palette).toEqual(SELUNE.palette);
    expect(bad.palette.primary).toBe('#E0458A');
    expect(bad.copy.subhead).toBe('7天根治暗沉・醫療級修護');
    expect(bad.copy.disclaimer).toBe('活動期間 2026/10/15–11/15｜數量有限，售完為止');
    const logo = bad.layout.find((b) => b.id === 'logo')!;
    const head = bad.layout.find((b) => b.id === 'headline')!;
    expect(logo.bbox[1] + logo.bbox[3]).toBeGreaterThan(head.bbox[1]);
    expect(bad.injection.params.find((p) => p.label === 'positive_prompt')?.value).toContain('vivid saturated colors');
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

- [ ] **Step 3: 寫失敗測試 `web/src/lib/api/mock/review.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import { CHANNEL_TEMPLATES } from '@/lib/compose/templates';
import { cleanSpec } from '@/test/fixtures';
import { SELUNE, MISTY_ISLE, SAMPLE_PRODUCTS } from './data';
import { applyFlaws, FLAWS } from './flaws';
import { reviewRender } from './review';

const coldbrew = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_misty_coldbrew')!;
const status = (r: ReturnType<typeof reviewRender>, id: string) => r.checks.find((c) => c.id === id)?.status;

describe('reviewRender', () => {
  it('passes a clean spec with 10 checks and a high score', () => {
    const r = reviewRender(cleanSpec(), SELUNE, 0, 1);
    expect(r.checks).toHaveLength(10);
    expect(r.checks.filter((c) => c.kind === 'vlm')).toHaveLength(3);
    expect(r.passed).toBe(true);
    expect(r.score).toBeGreaterThanOrEqual(97);
  });

  it('adds VLM warnings for variants 1 and 2 but still passes', () => {
    const r1 = reviewRender(cleanSpec(), SELUNE, 1, 1);
    expect(status(r1, 'vlm_occlusion')).toBe('warn');
    expect(r1.passed).toBe(true);
    expect(r1.score).toBeLessThanOrEqual(94);
    expect(status(reviewRender(cleanSpec(), SELUNE, 2, 1), 'vlm_quality')).toBe('warn');
  });

  it('fails a fully flawed spec on both rules and VLM', () => {
    const r = reviewRender(applyFlaws(cleanSpec(), FLAWS), SELUNE, 0, 1);
    expect(r.passed).toBe(false);
    expect(r.checks.filter((c) => c.status === 'fail').map((c) => c.id)).toEqual([
      'banned_words', 'color_delta', 'logo_clearance', 'vlm_exaggeration', 'vlm_occlusion',
    ]);
    expect(status(r, 'disclaimer')).toBe('warn');
  });

  it.each(CHANNEL_TEMPLATES.map((t) => t.id))('passes clean cold brew specs for %s', (templateId) => {
    expect(reviewRender(cleanSpec(MISTY_ISLE, coldbrew, templateId), MISTY_ISLE, 0, 3).passed).toBe(true);
  });

  it('is deterministic for the same seed', () => {
    expect(reviewRender(cleanSpec(), SELUNE, 0, 9)).toEqual(reviewRender(cleanSpec(), SELUNE, 0, 9));
  });
});
```

- [ ] **Step 4: 執行測試確認失敗**

Run: `npx vitest run src/lib/api/mock/flaws.test.ts src/lib/api/mock/review.test.ts`
Expected: FAIL，找不到 `./flaws`、`./review`

- [ ] **Step 5: 實作 `web/src/lib/api/mock/flaws.ts`**

```ts
import type { Palette, PromptSpec } from '@/types/contract';
import { setParam } from '@/lib/agent/prompt';

export const FLAWS = ['offPalette', 'bannedCopy', 'logoCrowding', 'missingDisclaimer'] as const;
export type Flaw = (typeof FLAWS)[number];

export const FLAW_DATA: Record<string, { offPalette: Palette; bannedSubhead: string }> = {
  selune: {
    offPalette: { primary: '#E0458A', secondary: '#FFE3EF', accent: '#F49AC1', ink: '#3B1F2E' },
    bannedSubhead: '7天根治暗沉・醫療級修護',
  },
  'misty-isle': {
    offPalette: { primary: '#1E88E5', secondary: '#E3F2FD', accent: '#90CAF9', ink: '#0D2238' },
    bannedSubhead: '保證提神・治療疲勞',
  },
};

/** 模擬第一輪 LLM／生圖常見的失誤，讓審查與 Query Rewriting 有東西可以修 */
export function applyFlaws(spec: PromptSpec, flaws: readonly Flaw[]): PromptSpec {
  const data = FLAW_DATA[spec.brandId];
  if (!data) throw new Error(`No flaw data for brand: ${spec.brandId}`);
  const out = structuredClone(spec);

  if (flaws.includes('offPalette')) {
    out.palette = { ...data.offPalette };
    out.positivePrompt = `${out.positivePrompt}, vivid saturated colors`;
    out.injection = setParam(out.injection, 'positive_prompt', out.positivePrompt);
  }
  if (flaws.includes('bannedCopy')) {
    out.copy.subhead = data.bannedSubhead;
  }
  if (flaws.includes('logoCrowding')) {
    const logo = out.layout.find((b) => b.id === 'logo')!;
    const head = out.layout.find((b) => b.id === 'headline')!;
    logo.bbox[1] = head.bbox[1] - Math.round(logo.bbox[3] * 0.55);
    out.injection = setParam(out.injection, 'layout_boxes', JSON.stringify(out.layout.map((b) => [b.id, ...b.bbox])));
  }
  if (flaws.includes('missingDisclaimer')) {
    const parts = out.copy.disclaimer.split('｜').filter((p) => !p.startsWith('*'));
    out.copy.disclaimer = parts.length ? parts.join('｜') : '圖片僅供參考';
  }
  return out;
}
```

- [ ] **Step 6: 實作 `web/src/lib/api/mock/vlm.ts`**

```ts
import type { Brand, PromptSpec, ReviewCheck } from '@/types/contract';
import { boxMap } from '@/lib/compose/layout';
import { verticalGap } from '@/lib/core/geometry';
import { copyTexts, findBannedWords, ragRefFor } from '@/lib/review/rules';

type Verdict = Pick<ReviewCheck, 'status' | 'value'>;

/** 模擬 VLM 看圖後的判斷。第二階段改為呼叫 Gemini Vision 或微調的 Llama 3.2 Vision，輸出格式不變。 */
export function mockVlmChecks(spec: PromptSpec, brand: Brand, variant: number): ReviewCheck[] {
  const words = findBannedWords(copyTexts(spec).map((t) => t.text), brand.bannedWords);
  const B = boxMap(spec.layout);
  const crowded = verticalGap(B.logo, B.headline) < 0;

  const occlusion: Verdict = crowded
    ? { status: 'fail', value: 'Logo 與標題重疊' }
    : variant % 4 === 1
      ? { status: 'warn', value: '標題貼近商品主體' }
      : { status: 'pass', value: '無重疊遮擋' };
  const quality: Verdict =
    variant % 4 === 2 ? { status: 'warn', value: '背景高光略過曝' } : { status: 'pass', value: '構圖與畫質良好' };

  return [
    {
      id: 'vlm_exaggeration', name: '誇大／療效用語', kind: 'vlm', rule: 'VLM 判讀海報文字語意',
      value: words.length ? `偵測到${words.map((w) => `「${w}」`).join('')}` : '未發現誇大用語',
      status: words.length ? 'fail' : 'pass', target: words.length ? 'subhead' : null, ragRef: ragRefFor(brand, 'law'),
    },
    {
      id: 'vlm_occlusion', name: '物件與文字遮擋', kind: 'vlm', rule: 'VLM 判讀元素是否重疊', ...occlusion,
      target: crowded ? 'logo' : occlusion.status === 'warn' ? 'headline' : null, ragRef: ragRefFor(brand, 'logo'),
    },
    {
      id: 'vlm_quality', name: '整體畫質', kind: 'vlm', rule: 'VLM 判讀構圖、光線與瑕疵', ...quality,
      target: quality.status === 'warn' ? 'product' : null, ragRef: null,
    },
  ];
}
```

- [ ] **Step 7: 實作 `web/src/lib/api/mock/review.ts`**

```ts
import type { Brand, PromptSpec, ReviewCheck } from '@/types/contract';
import { mulberry32 } from '@/lib/core/num';
import { mixHex } from '@/lib/review/color';
import { runRuleChecks, scoreChecks } from '@/lib/review/rules';
import { mockVlmChecks } from './vlm';

export interface ReviewResult { checks: ReviewCheck[]; score: number; passed: boolean; measuredPrimary: string }

/** 規則型檢查 + 模擬 VLM，再計分。seed 決定「偵測主色」的微小偏移與分數抖動。 */
export function reviewRender(spec: PromptSpec, brand: Brand, variant: number, seed: number): ReviewResult {
  const rng = mulberry32(seed);
  const measuredPrimary = mixHex(spec.palette.primary, '#ffffff', 0.01 + rng() * 0.02);
  const checks = [...runRuleChecks({ brand, spec, measuredPrimary }), ...mockVlmChecks(spec, brand, variant)];
  const { score, passed } = scoreChecks(checks, Math.floor(rng() * 4));
  return { checks, score, passed, measuredPrimary };
}
```

- [ ] **Step 8: 執行測試確認通過**

Run: `npx vitest run src/lib/api/mock/flaws.test.ts src/lib/api/mock/review.test.ts`
Expected: 全部 PASS（含 5 個模板的冷萃咖啡檢查）

- [ ] **Step 9: Commit**

```bash
git add web/src/lib/api/mock/flaws.ts web/src/lib/api/mock/vlm.ts web/src/lib/api/mock/review.ts web/src/lib/api/mock/flaws.test.ts web/src/lib/api/mock/review.test.ts web/src/test/fixtures.ts
git commit -m "feat: add mock flaws, mock VLM checks and review runner" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: 任務事件時間軸 `buildTimeline`

**Files:**
- Create: `web/src/lib/api/mock/scenario.ts`
- Test: `web/src/lib/api/mock/scenario.test.ts`

**Interfaces:**
- Consumes: `buildPromptSpec`、`seedOf`（Task 8）；`planFixes`（Task 8）；`applyFlaws`、`FLAWS`、`reviewRender`（Task 9）；`hashString`、`mulberry32`（Task 1）；`truncate`（Task 1）
- Produces:
  - `interface TimedEvent { at: number; event: JobEvent }`（`at` 為 1× 速度下的毫秒）
  - `interface ScenarioContext { jobId: string; input: JobInput; brand: Brand; product: Product; templates: ChannelTemplate[]; demo: DemoOptions; seed: number }`
  - `PHASE_MS`、`RENDER_STEPS`（每輪 38 個 `render.progress`）
  - `buildTimeline(ctx: ScenarioContext): TimedEvent[]`：依 `at` 排序；同一 seed 結果相同。Render id 格式 `${jobId}_r${round}_${templateId}_v${variant}`

- [ ] **Step 1: 寫失敗測試 `web/src/lib/api/mock/scenario.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import type { JobEvent, JobInput } from '@/types/contract';
import { getTemplate } from '@/lib/compose/templates';
import { SELUNE, SAMPLE_PRODUCTS } from './data';
import { parseBrief } from './brief';
import { buildTimeline, type ScenarioContext, type TimedEvent } from './scenario';

const serum = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_selune_serum')!;
const BRIEF = '週年慶主打買一送一，溫柔療癒';

const ctx = (over: Partial<ScenarioContext> = {}, input: Partial<JobInput> = {}): ScenarioContext => ({
  jobId: 'job_test',
  seed: 7,
  brand: SELUNE,
  product: serum,
  templates: [getTemplate('ig-post')],
  demo: { speed: 1, firstRoundFail: true, forceAllFail: false },
  input: {
    brandId: 'selune', productId: serum.id, brief: BRIEF, parsedBrief: parseBrief(BRIEF, SELUNE, serum),
    templateIds: ['ig-post'], variantsPerTemplate: 4, llm: 'Gemini 3.7 Flash', engine: 'comfyui',
    vlm: 'Gemini 3.7 Vision', maxRetries: 2, ...input,
  },
  ...over,
});

function ofType<T extends JobEvent['type']>(tl: TimedEvent[], type: T): Extract<JobEvent, { type: T }>[] {
  return tl.map((x) => x.event).filter((e): e is Extract<JobEvent, { type: T }> => e.type === type);
}

describe('buildTimeline (default demo)', () => {
  const tl = buildTimeline(ctx());

  it('fails round 1, rewrites once, passes round 2 and ends at 14.5 s', () => {
    expect(tl[0].event).toEqual({ type: 'job.accepted', jobId: 'job_test' });
    expect(tl.at(-1)!.at).toBe(14_500);
    const reviews = ofType(tl, 'review.completed');
    expect(reviews.filter((e) => e.round === 1).every((e) => !e.passed)).toBe(true);
    expect(reviews.filter((e) => e.round === 2).some((e) => e.passed)).toBe(true);
    expect(ofType(tl, 'rewrite.started')).toHaveLength(1);
    expect(ofType(tl, 'job.completed')).toHaveLength(1);
  });

  it('emits stages in pipeline order', () => {
    expect(ofType(tl, 'job.status').map((e) => e.stage)).toEqual([
      'parsing', 'retrieving',
      'prompting', 'rendering', 'composing', 'reviewing', 'rewriting',
      'prompting', 'rendering', 'composing', 'reviewing',
      'saving', 'done',
    ]);
  });

  it('never goes back in time', () => {
    for (let i = 1; i < tl.length; i++) expect(tl[i].at).toBeGreaterThanOrEqual(tl[i - 1].at);
  });

  it('reranks RAG hits and re-queries compliant wording before the rewrite', () => {
    const [first, requery] = ofType(tl, 'rag.retrieved');
    const [reranked] = ofType(tl, 'rag.reranked');
    expect(first.hits.map((h) => h.tag)).toEqual(['layout', 'color', 'history', 'logo', 'law']);
    expect(reranked.hits.map((h) => h.tag)).toEqual(['color', 'law', 'logo', 'layout', 'history']);
    expect(requery.hits[0].chunkId).toBe('selune#law-alt');
    const round2 = ofType(tl, 'prompt.generated').find((e) => e.round === 2)!;
    expect(round2.spec.ragRefs).toContain('selune#law-alt');
    expect(round2.spec.negativePrompt).toContain('off-brand colors');
    expect(round2.spec.palette).toEqual(SELUNE.palette);
  });

  it('emits 38 render progress steps per round, ending with upscale', () => {
    const r1 = ofType(tl, 'render.progress').filter((e) => e.round === 1);
    expect(r1).toHaveLength(38);
    expect(r1.at(-1)).toMatchObject({ node: 'upscale', step: 2, maxStep: 2 });
  });

  it('is deterministic for the same seed', () => {
    expect(buildTimeline(ctx())).toEqual(tl);
  });
});

describe('buildTimeline (other demo options)', () => {
  it('finishes in 8.2 s with no rewrite when round 1 is clean', () => {
    const tl = buildTimeline(ctx({ demo: { speed: 1, firstRoundFail: false, forceAllFail: false } }));
    expect(tl.at(-1)!.at).toBe(8_200);
    expect(ofType(tl, 'rewrite.started')).toHaveLength(0);
    expect(ofType(tl, 'job.completed')).toHaveLength(1);
  });

  it('ends with needs_review after maxRetries when every round fails', () => {
    const tl = buildTimeline(ctx({ demo: { speed: 1, firstRoundFail: true, forceAllFail: true } }, { maxRetries: 1 }));
    expect(ofType(tl, 'job.needs_review')).toHaveLength(1);
    expect(ofType(tl, 'job.completed')).toHaveLength(0);
    expect(ofType(tl, 'rewrite.started')).toHaveLength(1);
    expect(ofType(tl, 'job.status').at(-1)).toEqual({ type: 'job.status', stage: 'needs_review', round: 2 });
  });

  it('picks the best passing render for each template', () => {
    const tl = buildTimeline(ctx({ templates: [getTemplate('ecom-main'), getTemplate('story')] }, { templateIds: ['ecom-main', 'story'] }));
    const [done] = ofType(tl, 'job.completed');
    expect(Object.keys(done.bestRenderIds).sort()).toEqual(['ecom-main', 'story']);
    expect(done.bestRenderIds['ecom-main']).toMatch(/^job_test_r2_ecom-main_v\d$/);
    expect(ofType(tl, 'render.completed').flatMap((e) => e.renders)).toHaveLength(16);
  });
});
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `npx vitest run src/lib/api/mock/scenario.test.ts`
Expected: FAIL，找不到 `./scenario`

- [ ] **Step 3: 實作 `web/src/lib/api/mock/scenario.ts`**

```ts
import type {
  Brand, ChannelTemplate, CheckId, DemoOptions, JobEvent, JobInput, LogLevel, LogSource, Product, RagHit, RagTag,
  Render, RenderNode, TemplateId,
} from '@/types/contract';
import { buildPromptSpec, seedOf } from '@/lib/agent/prompt';
import { planFixes } from '@/lib/agent/fixes';
import { hashString, mulberry32 } from '@/lib/core/num';
import { truncate } from '@/lib/core/text';
import { applyFlaws, FLAWS } from './flaws';
import { reviewRender } from './review';

export interface TimedEvent { at: number; event: JobEvent }

export interface ScenarioContext {
  jobId: string;
  input: JobInput;
  brand: Brand;
  product: Product;
  templates: ChannelTemplate[];
  demo: DemoOptions;
  seed: number;
}

/** 1× 速度下各階段的時間（毫秒）。含一次重試總長 14,500 ms。 */
export const PHASE_MS = {
  parse: 800, retrieveStart: 1100, retrieved: 1600, reranked: 2300,
  prompt: 800, compose: 300, review: 1200, rewrite: 800, save: 400,
} as const;

/** ComfyUI 各節點的步數與時間；每輪共 38 個 render.progress、3,200 ms */
export const RENDER_STEPS: Record<RenderNode, { steps: number; ms: number }> = {
  cutout: { steps: 4, ms: 400 },
  generate: { steps: 28, ms: 2000 },
  relight: { steps: 4, ms: 500 },
  upscale: { steps: 2, ms: 300 },
};

const NODE_LABEL: Record<RenderNode, string> = {
  cutout: '去背（BiRefNet）',
  generate: '背景生成（SDXL + ControlNet + IP-Adapter）',
  relight: '打光融合（IC-Light）',
  upscale: '放大至 2K',
};

/** 向量召回順序與 Rerank 後順序刻意不同，用來展示 BGE Reranker 的效果 */
const VECTOR_ORDER: RagTag[] = ['layout', 'color', 'history', 'logo', 'law'];
const VECTOR_SCORES = [0.86, 0.84, 0.83, 0.81, 0.79];
const RERANK_ORDER: RagTag[] = ['color', 'law', 'logo', 'layout', 'history'];
const RERANK_SCORES = [0.97, 0.93, 0.88, 0.74, 0.61];

function retrieve(brand: Brand): RagHit[] {
  return VECTOR_ORDER.map((tag, i) => {
    const c = brand.guidelineChunks.find((x) => x.tag === tag && !x.id.endsWith('-alt'));
    if (!c) throw new Error(`Brand ${brand.id} has no ${tag} chunk`);
    return { chunkId: c.id, source: c.source, section: c.section, tag: c.tag, text: c.text, vectorScore: VECTOR_SCORES[i] };
  });
}

function rerank(hits: RagHit[]): RagHit[] {
  return hits
    .map((h) => ({ ...h, rerankScore: RERANK_SCORES[RERANK_ORDER.indexOf(h.tag)] }))
    .sort((a, b) => (b.rerankScore ?? 0) - (a.rerankScore ?? 0));
}

function requeryHit(brand: Brand): RagHit {
  const c = brand.guidelineChunks.find((x) => x.id === `${brand.id}#law-alt`);
  if (!c) throw new Error(`Brand ${brand.id} has no law-alt chunk`);
  return { chunkId: c.id, source: c.source, section: c.section, tag: c.tag, text: c.text, vectorScore: 0.884, rerankScore: 0.95 };
}

export function buildTimeline(ctx: ScenarioContext): TimedEvent[] {
  const { jobId, input, brand, product, templates, demo } = ctx;
  const rng = mulberry32(ctx.seed);
  const out: TimedEvent[] = [];
  const emit = (at: number, event: JobEvent) => out.push({ at: Math.round(at), event });
  const log = (at: number, source: LogSource, message: string, level: LogLevel = 'info') =>
    emit(at, { type: 'log', source, level, message });

  // 1. 接收任務、拆解需求
  emit(0, { type: 'job.accepted', jobId });
  emit(0, { type: 'job.status', stage: 'parsing', round: 0 });
  log(0, 'ws', `→ job.create brand=${brand.id} product=${product.id} templates=${templates.map((t) => t.id).join(',')}`);
  log(300, 'agent', `${input.llm}：拆解需求「${truncate(input.brief, 24)}」`);
  emit(PHASE_MS.parse, { type: 'brief.parsed', parsedBrief: input.parsedBrief });
  const pb = input.parsedBrief;
  log(PHASE_MS.parse, 'agent', `✓ 語氣=${pb.tone}・檔期=${pb.campaign ?? '無'}・優惠=${pb.offer ?? '無'}`, 'ok');

  // 2. RAG：Chroma 召回 → BGE Rerank
  emit(PHASE_MS.retrieveStart, { type: 'job.status', stage: 'retrieving', round: 0 });
  log(PHASE_MS.retrieveStart, 'rag', `embed query（bge-m3）→ similarity_search(collection="${brand.id}_ci", top_k=5)`);
  const hits = retrieve(brand);
  emit(PHASE_MS.retrieved, { type: 'rag.retrieved', query: `${brand.name}｜${product.name}｜${input.brief}`, hits });
  log(PHASE_MS.retrieved, 'rag', `召回 ${hits.length} 筆品牌規範`);
  const ranked = rerank(hits);
  emit(PHASE_MS.reranked, { type: 'rag.reranked', hits: ranked });
  log(PHASE_MS.reranked, 'rag', `✓ BGE Reranker 重新排序：${ranked.map((h) => h.tag).join(' > ')}`, 'ok');
  const ragRefs = ranked.map((h) => h.chunkId);

  let t: number = PHASE_MS.reranked;
  let round = 1;
  let pending = [...templates];
  let fixesForNext: CheckId[] = [];
  const best: Partial<Record<TemplateId, string>> = {};
  let success = false;

  for (;;) {
    const flawed = demo.forceAllFail || (demo.firstRoundFail && round === 1);

    // 3. Prompt 構建（JSON Prompt + BBox）
    emit(t, { type: 'job.status', stage: 'prompting', round });
    const specs = pending.map((template) => {
      const spec = buildPromptSpec({
        jobId, round, brand, product, brief: input.parsedBrief, template, engine: input.engine,
        seed: 100_000_000 + Math.floor(rng() * 900_000_000), ragRefs, fixes: fixesForNext,
      });
      return flawed ? applyFlaws(spec, FLAWS) : spec;
    });
    specs.forEach((spec, i) =>
      emit(t + ((i + 1) * PHASE_MS.prompt) / specs.length, { type: 'prompt.generated', round, templateId: spec.templateId, spec }),
    );
    log(t + PHASE_MS.prompt, 'agent', `✓ 第 ${round} 輪 JSON Prompt：${specs.length} 個模板 × ${specs[0].layout.length} 個 BBox`, 'ok');
    t += PHASE_MS.prompt;

    // 4. ComfyUI：去背 → 背景生成 → 打光融合 → 放大
    emit(t, { type: 'job.status', stage: 'rendering', round });
    for (const spec of specs) {
      emit(t, { type: 'comfy.queued', round, templateId: spec.templateId, promptId: `${jobId}_r${round}_${spec.templateId}`, injection: spec.injection });
    }
    log(t, 'comfy', `ws → ComfyUI /prompt × ${specs.length}（${specs[0].injection.workflowFile}，batch=${input.variantsPerTemplate}）`);
    for (const node of ['cutout', 'generate', 'relight', 'upscale'] as const) {
      const { steps, ms } = RENDER_STEPS[node];
      for (let s = 1; s <= steps; s++) emit(t + (s * ms) / steps, { type: 'render.progress', round, node, step: s, maxStep: steps });
      t += ms;
      log(t, 'comfy', `✓ ${NODE_LABEL[node]} 完成`);
    }
    const renders: Render[] = specs.flatMap((spec) =>
      Array.from({ length: input.variantsPerTemplate }, (_, v): Render => ({
        id: `${jobId}_r${round}_${spec.templateId}_v${v}`, jobId, round, templateId: spec.templateId, variant: v,
        background: { kind: 'procedural', seed: seedOf(spec) + v, palette: spec.palette, style: brand.id },
        spec, score: null, passed: null, checks: [],
      })),
    );
    emit(t, { type: 'render.completed', round, renders });

    // 5. 文字排版合成
    emit(t, { type: 'job.status', stage: 'composing', round });
    log(t, 'compose', `排版引擎疊加文字圖層（${renders.length} 張）`);
    t += PHASE_MS.compose;

    // 6. 合規審查（規則 + VLM）
    emit(t, { type: 'job.status', stage: 'reviewing', round });
    log(t, 'vlm', `${input.vlm}：審查 ${renders.length} 張 × 10 項`);
    const results = renders.map((render) => ({
      render, result: reviewRender(render.spec, brand, render.variant, hashString(render.id) ^ ctx.seed),
    }));
    const dt = PHASE_MS.review / results.reduce((n, x) => n + x.result.checks.length, 0);
    let k = 0;
    for (const { render, result } of results) {
      for (const check of result.checks) emit(t + ++k * dt, { type: 'review.check', round, renderId: render.id, check });
      emit(t + k * dt, { type: 'review.completed', round, renderId: render.id, score: result.score, passed: result.passed });
    }
    t += PHASE_MS.review;

    const byScore = (id: TemplateId) =>
      results.filter((x) => x.render.templateId === id).sort((a, b) => b.result.score - a.result.score);
    const failed: ChannelTemplate[] = [];
    for (const template of pending) {
      const top = byScore(template.id).find((x) => x.result.passed);
      if (top) best[template.id] = top.render.id;
      else failed.push(template);
    }
    log(t, 'vlm', `第 ${round} 輪：${pending.length - failed.length}/${pending.length} 個模板通過`, failed.length ? 'warn' : 'ok');

    if (!failed.length) { success = true; break; }
    if (round > input.maxRetries) break;

    // 7. Query Rewriting（必要時重新檢索合規用語）
    emit(t, { type: 'job.status', stage: 'rewriting', round });
    const reasons = new Set<CheckId>();
    let requery = false;
    for (const template of failed) {
      const top = byScore(template.id)[0];
      const failing = top.result.checks.filter((c) => c.status !== 'pass').map((c) => c.id);
      failing.forEach((id) => reasons.add(id));
      const needRequery = failing.includes('banned_words') || failing.includes('vlm_exaggeration');
      requery ||= needRequery;
      emit(t, {
        type: 'rewrite.started', round, templateId: template.id, reasons: failing,
        fixes: planFixes(top.result.checks, brand, top.render.spec), requery: needRequery,
      });
    }
    log(t, 'api', `觸發 Query Rewriting（重試 ${round}/${input.maxRetries}）`, 'warn');
    const altId = `${brand.id}#law-alt`;
    if (requery && !ragRefs.includes(altId)) {
      const hit = requeryHit(brand);
      emit(t + PHASE_MS.rewrite / 2, { type: 'rag.retrieved', query: `${brand.category} 禁用詞 合規替代用語`, hits: [hit] });
      log(t + PHASE_MS.rewrite / 2, 'rag', `re-query → ${hit.chunkId}（${hit.vectorScore}）`, 'ok');
      ragRefs.push(altId);
    }
    fixesForNext = [...reasons];
    t += PHASE_MS.rewrite;
    pending = failed;
    round++;
  }

  // 8. 寫入 DB 並回傳
  emit(t, { type: 'job.status', stage: 'saving', round });
  log(t, 'db', `INSERT INTO renders（${Object.keys(best).length} 張最佳候選）`);
  t += PHASE_MS.save;
  if (success) {
    emit(t, { type: 'job.completed', jobId, bestRenderIds: best });
    emit(t, { type: 'job.status', stage: 'done', round });
    log(t, 'ws', '← job.completed', 'ok');
  } else {
    emit(t, { type: 'job.needs_review', jobId, reason: '已達最大重試次數，仍未通過合規審查' });
    emit(t, { type: 'job.status', stage: 'needs_review', round });
    log(t, 'ws', '← job.needs_review', 'warn');
  }
  // Array.prototype.sort 是穩定排序：同一時間點的事件維持加入順序
  return out.sort((a, b) => a.at - b.at);
}
```

- [ ] **Step 4: 執行測試確認通過**

Run: `npx vitest run src/lib/api/mock/scenario.test.ts`
Expected: 9 個測試 PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/api/mock/scenario.ts web/src/lib/api/mock/scenario.test.ts
git commit -m "feat: add mock job timeline with RAG rerank and query rewriting loop" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: 事件播放器、`ApiClient` 介面與 `MockApiClient`

**Files:**
- Create: `web/src/lib/api/mock/player.ts`、`web/src/lib/api/client.ts`、`web/src/lib/api/mock/store.ts`、`web/src/lib/api/mock/client.ts`、`web/src/lib/api/index.ts`
- Test: `web/src/lib/api/mock/player.test.ts`、`web/src/lib/api/mock/client.test.ts`

**Interfaces:**
- Consumes: `buildTimeline`、`TimedEvent`（Task 10）；`parseBrief`（Task 7）；`BRANDS`、`getBrandById`、`SAMPLE_PRODUCTS`（Task 5）；`CHANNEL_TEMPLATES`、`getTemplate`（Task 4）；`hashString`（Task 1）
- Produces（Plan 2 的 UI 只依賴這些）：
  - `interface PlayerHandle { cancel(): void }`、`playTimeline(events: TimedEvent[], opts: { getSpeed: () => number; onEvent: (e: JobEvent) => void; onDone: () => void }): PlayerHandle`（第一個事件也非同步送出）
  - `type ProductDraft = Omit<Product, 'id' | 'createdAt'> & { id?: string }`
  - `interface DemoControls { get(): DemoOptions; set(patch: Partial<DemoOptions>): void }`
  - `interface ApiClient`：`demo`、`listBrands`、`listTemplates`、`listProducts`、`saveProduct`、`deleteProduct`、`parseBrief`、`createJob`、`subscribe`、`cancelJob`、`selectRender`、`listHistory`（簽名見 Step 5）
  - `interface KeyValueStore { get<T>(key: string): Promise<T | undefined>; set<T>(key: string, value: T): Promise<void> }`、`class MemoryStore`（Plan 2 會加 IndexedDB 實作）
  - `makeJobId(now: Date, rand?: () => number): string`，格式 `job_YYYYMMDD_HHMM_xxxx`
  - `class MockApiClient implements ApiClient`，建構子 `(store?: KeyValueStore, now?: () => Date)`；Demo 預設 `{ speed: 1, firstRoundFail: true, forceAllFail: false }`
  - `getApiClient(): ApiClient`（單例；`NEXT_PUBLIC_API_MODE` 不是 `mock` 時 throw）

- [ ] **Step 1: 寫失敗測試 `web/src/lib/api/mock/player.test.ts`**

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobEvent } from '@/types/contract';
import { playTimeline } from './player';
import type { TimedEvent } from './scenario';

const ev = (n: number): JobEvent => ({ type: 'log', source: 'api', level: 'info', message: String(n) });
const TIMELINE: TimedEvent[] = [
  { at: 0, event: ev(0) }, { at: 100, event: ev(1) }, { at: 100, event: ev(2) }, { at: 300, event: ev(3) },
];

function collect(speed: number) {
  const got: string[] = [];
  const state = { done: false };
  const handle = playTimeline(TIMELINE, {
    getSpeed: () => speed,
    onEvent: (e) => got.push(e.type === 'log' ? e.message : e.type),
    onDone: () => { state.done = true; },
  });
  return { got, state, handle };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('playTimeline', () => {
  it('emits events at their timestamps, grouping events at the same time', async () => {
    const { got, state } = collect(1);
    expect(got).toEqual([]);
    await vi.advanceTimersByTimeAsync(0);
    expect(got).toEqual(['0']);
    await vi.advanceTimersByTimeAsync(100);
    expect(got).toEqual(['0', '1', '2']);
    await vi.advanceTimersByTimeAsync(199);
    expect(got).toHaveLength(3);
    await vi.advanceTimersByTimeAsync(1);
    expect(got).toEqual(['0', '1', '2', '3']);
    expect(state.done).toBe(true);
  });

  it('divides waiting time by the speed', async () => {
    const { got } = collect(2);
    await vi.advanceTimersByTimeAsync(150);
    expect(got).toEqual(['0', '1', '2', '3']);
  });

  it('stops after cancel', async () => {
    const { got, state, handle } = collect(1);
    await vi.advanceTimersByTimeAsync(0);
    handle.cancel();
    await vi.advanceTimersByTimeAsync(1000);
    expect(got).toEqual(['0']);
    expect(state.done).toBe(false);
  });
});
```

- [ ] **Step 2: 寫失敗測試 `web/src/lib/api/mock/client.test.ts`**

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobEvent, JobInput } from '@/types/contract';
import { getApiClient } from '../index';
import { MockApiClient, makeJobId } from './client';

const BRIEF = '週年慶主打買一送一，溫柔療癒';
const NOW = new Date(2026, 9, 5, 9, 30);

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});
afterEach(() => vi.useRealTimers());

async function startJob(api: MockApiClient, over: Partial<JobInput> = {}) {
  const parsedBrief = await api.parseBrief('selune', BRIEF, 'prod_selune_serum');
  const { jobId } = await api.createJob({
    brandId: 'selune', productId: 'prod_selune_serum', brief: BRIEF, parsedBrief, templateIds: ['ig-post'],
    variantsPerTemplate: 4, llm: 'Gemini 3.7 Flash', engine: 'comfyui', vlm: 'Gemini 3.7 Vision', maxRetries: 2,
    ...over,
  });
  const events: JobEvent[] = [];
  api.subscribe(jobId, (e) => events.push(e));
  return { jobId, events };
}

const statuses = (events: JobEvent[]) => events.flatMap((e) => (e.type === 'job.status' ? [e.stage] : []));

describe('makeJobId', () => {
  it('formats the local date, time and a 4-hex suffix', () => {
    expect(makeJobId(NOW, () => 0.5)).toBe('job_20261005_0930_7fff');
  });
});

describe('products', () => {
  it('lists samples per brand, saves and deletes custom products', async () => {
    const api = new MockApiClient();
    expect((await api.listProducts('selune')).map((p) => p.id)).toEqual(['prod_selune_serum']);
    const saved = await api.saveProduct({
      brandId: 'selune', name: '晚安面膜', features: ['保濕'], price: { sale: 680, original: 880 },
      photo: { source: 'upload', url: 'blob:test' },
    });
    expect(saved.id).toMatch(/^prod_/);
    expect(saved.createdAt).toBe(NOW.toISOString());
    expect((await api.listProducts('selune')).map((p) => p.name)).toEqual(['極光玻尿酸修護精華 30ml', '晚安面膜']);
    await api.deleteProduct(saved.id);
    await api.deleteProduct('prod_selune_serum');
    expect(await api.listProducts('selune')).toEqual([]);
    expect(await api.listProducts('misty-isle')).toHaveLength(1);
  });
});

describe('jobs', () => {
  it('runs the default demo to completion and replays events to late subscribers', async () => {
    const api = new MockApiClient();
    const { jobId, events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(14_500);
    expect(statuses(events).at(-1)).toBe('done');
    expect(events.some((e) => e.type === 'job.completed')).toBe(true);
    const late: JobEvent[] = [];
    api.subscribe(jobId, (e) => late.push(e));
    expect(late).toEqual(events);
  });

  it('respects the demo speed', async () => {
    const api = new MockApiClient();
    api.demo.set({ speed: 4 });
    const { events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(3_700);
    expect(events.some((e) => e.type === 'job.completed')).toBe(true);
  });

  it('can be cancelled', async () => {
    const api = new MockApiClient();
    const { jobId, events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(1_000);
    await api.cancelJob(jobId);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(events.at(-1)).toEqual({ type: 'job.status', stage: 'cancelled', round: 0 });
    expect(events.some((e) => e.type === 'job.completed')).toBe(false);
  });

  it('saves the selected render with edited copy to history', async () => {
    const api = new MockApiClient();
    const { jobId, events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(14_500);
    const done = events.find((e) => e.type === 'job.completed');
    if (done?.type !== 'job.completed') throw new Error('job did not complete');
    const prompt = events.find((e) => e.type === 'prompt.generated' && e.round === 2);
    if (prompt?.type !== 'prompt.generated') throw new Error('missing round 2 prompt');

    const copy = { ...prompt.spec.copy, price: { ...prompt.spec.copy.price, sale: 999 } };
    const entry = await api.selectRender(jobId, done.bestRenderIds['ig-post']!, copy);
    expect(entry).toMatchObject({ jobId, brandId: 'selune', templateId: 'ig-post', favorite: false, writtenToRag: true });
    expect(entry.render.passed).toBe(true);
    expect(entry.render.checks).toHaveLength(10);
    expect(entry.copy.price.sale).toBe(999);
    expect(await api.listHistory('selune')).toHaveLength(1);
    expect(await api.listHistory('misty-isle')).toHaveLength(0);
  });

  it('rejects unknown jobs and empty template lists', async () => {
    const api = new MockApiClient();
    expect(() => api.subscribe('nope', () => {})).toThrow('Unknown job');
    await expect(startJob(api, { templateIds: [] })).rejects.toThrow('至少要選一個通路模板');
  });
});

describe('getApiClient', () => {
  it('returns a singleton mock client with demo controls by default', () => {
    const api = getApiClient();
    expect(api).toBe(getApiClient());
    expect(api.demo?.get()).toEqual({ speed: 1, firstRoundFail: true, forceAllFail: false });
  });
});
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `npx vitest run src/lib/api/mock/player.test.ts src/lib/api/mock/client.test.ts`
Expected: FAIL，找不到 `./player`、`./client`、`../index`

- [ ] **Step 4: 實作 `web/src/lib/api/mock/player.ts`**

```ts
import type { JobEvent } from '@/types/contract';
import type { TimedEvent } from './scenario';

export interface PlayerHandle { cancel(): void }

/**
 * 依 `at`（1× 毫秒）播放事件。每段等待時間 ÷ getSpeed()，所以播放中改速度會立即生效。
 * 第一批事件也用 setTimeout 送出，讓呼叫端有機會先訂閱。
 */
export function playTimeline(
  events: TimedEvent[],
  opts: { getSpeed: () => number; onEvent: (e: JobEvent) => void; onDone: () => void },
): PlayerHandle {
  let i = 0;
  let now = 0;
  let cancelled = false;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const step = () => {
    if (cancelled) return;
    while (i < events.length && events[i].at <= now) opts.onEvent(events[i++].event);
    if (i >= events.length) {
      opts.onDone();
      return;
    }
    const next = events[i].at;
    timer = setTimeout(() => {
      now = next;
      step();
    }, (next - now) / opts.getSpeed());
  };

  timer = setTimeout(step, 0);
  return {
    cancel() {
      cancelled = true;
      if (timer) clearTimeout(timer);
    },
  };
}
```

- [ ] **Step 5: 實作 `web/src/lib/api/client.ts`**

```ts
import type {
  Brand, ChannelTemplate, Copy, DemoOptions, HistoryEntry, JobEvent, JobInput, ParsedBrief, Product,
} from '@/types/contract';

export type ProductDraft = Omit<Product, 'id' | 'createdAt'> & { id?: string };

export interface DemoControls {
  get(): DemoOptions;
  set(patch: Partial<DemoOptions>): void;
}

/** UI 只依賴這個介面：第一階段由 MockApiClient 實作，第二階段由連線 FastAPI 的 HttpApiClient 實作 */
export interface ApiClient {
  /** 只有 mock 模式有 Demo 控制台；live 模式為 null */
  readonly demo: DemoControls | null;
  listBrands(): Promise<Brand[]>;
  listTemplates(): Promise<ChannelTemplate[]>;
  listProducts(brandId: string): Promise<Product[]>;
  saveProduct(draft: ProductDraft): Promise<Product>;
  deleteProduct(id: string): Promise<void>;
  parseBrief(brandId: string, text: string, productId: string | null): Promise<ParsedBrief>;
  createJob(input: JobInput): Promise<{ jobId: string }>;
  /** 先重播已發生的事件，再接收即時事件；回傳取消訂閱的函式 */
  subscribe(jobId: string, onEvent: (event: JobEvent) => void): () => void;
  cancelJob(jobId: string): Promise<void>;
  selectRender(jobId: string, renderId: string, copy: Copy): Promise<HistoryEntry>;
  listHistory(brandId?: string): Promise<HistoryEntry[]>;
}
```

- [ ] **Step 6: 實作 `web/src/lib/api/mock/store.ts`**

```ts
export interface KeyValueStore {
  get<T>(key: string): Promise<T | undefined>;
  set<T>(key: string, value: T): Promise<void>;
}

/** 記憶體版本（測試與預設使用）；Plan 2 會加入 IndexedDB 版本 */
export class MemoryStore implements KeyValueStore {
  private readonly data = new Map<string, unknown>();

  async get<T>(key: string): Promise<T | undefined> {
    const v = this.data.get(key);
    return v === undefined ? undefined : (structuredClone(v) as T);
  }

  async set<T>(key: string, value: T): Promise<void> {
    this.data.set(key, structuredClone(value));
  }
}
```

- [ ] **Step 7: 實作 `web/src/lib/api/mock/client.ts`**

```ts
import type { Copy, DemoOptions, HistoryEntry, JobEvent, JobInput, Product, Render } from '@/types/contract';
import type { ApiClient, DemoControls, ProductDraft } from '../client';
import { CHANNEL_TEMPLATES, getTemplate } from '@/lib/compose/templates';
import { hashString } from '@/lib/core/num';
import { BRANDS, getBrandById, SAMPLE_PRODUCTS } from './data';
import { parseBrief } from './brief';
import { playTimeline, type PlayerHandle } from './player';
import { buildTimeline } from './scenario';
import { MemoryStore, type KeyValueStore } from './store';

interface JobRecord {
  id: string;
  input: JobInput;
  events: JobEvent[];
  listeners: Set<(e: JobEvent) => void>;
  renders: Map<string, Render>;
  round: number;
  finished: boolean;
  player: PlayerHandle | null;
}

const KEYS = { products: 'products', deleted: 'deletedSampleIds', history: 'history' } as const;
const pad = (n: number) => String(n).padStart(2, '0');

export function makeJobId(now: Date, rand: () => number = Math.random): string {
  const date = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
  const time = `${pad(now.getHours())}${pad(now.getMinutes())}`;
  return `job_${date}_${time}_${Math.floor(rand() * 0xffff).toString(16).padStart(4, '0')}`;
}

const makeId = (prefix: string) => `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;

export class MockApiClient implements ApiClient {
  readonly demo: DemoControls;
  private options: DemoOptions = { speed: 1, firstRoundFail: true, forceAllFail: false };
  private readonly jobs = new Map<string, JobRecord>();

  constructor(
    private readonly store: KeyValueStore = new MemoryStore(),
    private readonly now: () => Date = () => new Date(),
  ) {
    this.demo = {
      get: () => ({ ...this.options }),
      set: (patch) => { this.options = { ...this.options, ...patch }; },
    };
  }

  async listBrands() { return BRANDS; }

  async listTemplates() { return CHANNEL_TEMPLATES; }

  private async customProducts(): Promise<Product[]> {
    return (await this.store.get<Product[]>(KEYS.products)) ?? [];
  }

  async listProducts(brandId: string): Promise<Product[]> {
    const custom = await this.customProducts();
    const deleted = new Set((await this.store.get<string[]>(KEYS.deleted)) ?? []);
    const customIds = new Set(custom.map((p) => p.id));
    const samples = SAMPLE_PRODUCTS.filter((p) => !deleted.has(p.id) && !customIds.has(p.id));
    return [...samples, ...custom].filter((p) => p.brandId === brandId);
  }

  async saveProduct(draft: ProductDraft): Promise<Product> {
    getBrandById(draft.brandId);
    const custom = await this.customProducts();
    const existing = draft.id
      ? (custom.find((p) => p.id === draft.id) ?? SAMPLE_PRODUCTS.find((p) => p.id === draft.id))
      : undefined;
    const product: Product = { ...draft, id: draft.id ?? makeId('prod'), createdAt: existing?.createdAt ?? this.now().toISOString() };
    await this.store.set(KEYS.products, [...custom.filter((p) => p.id !== product.id), product]);
    return product;
  }

  async deleteProduct(id: string): Promise<void> {
    const custom = await this.customProducts();
    await this.store.set(KEYS.products, custom.filter((p) => p.id !== id));
    if (SAMPLE_PRODUCTS.some((p) => p.id === id)) {
      const deleted = (await this.store.get<string[]>(KEYS.deleted)) ?? [];
      await this.store.set(KEYS.deleted, [...new Set([...deleted, id])]);
    }
  }

  private async findProduct(id: string): Promise<Product> {
    const p = (await this.customProducts()).find((x) => x.id === id) ?? SAMPLE_PRODUCTS.find((x) => x.id === id);
    if (!p) throw new Error(`Unknown product: ${id}`);
    return p;
  }

  async parseBrief(brandId: string, text: string, productId: string | null) {
    const brand = getBrandById(brandId);
    const product = productId ? await this.findProduct(productId) : null;
    return parseBrief(text, brand, product);
  }

  async createJob(input: JobInput): Promise<{ jobId: string }> {
    const brand = getBrandById(input.brandId);
    const product = await this.findProduct(input.productId);
    if (!input.templateIds.length) throw new Error('至少要選一個通路模板');
    const templates = input.templateIds.map((id) => getTemplate(id));

    const jobId = makeJobId(this.now());
    const rec: JobRecord = {
      id: jobId, input, events: [], listeners: new Set(), renders: new Map(), round: 0, finished: false, player: null,
    };
    this.jobs.set(jobId, rec);

    const timeline = buildTimeline({ jobId, input, brand, product, templates, demo: this.demo.get(), seed: hashString(jobId) });
    rec.player = playTimeline(timeline, {
      getSpeed: () => this.options.speed,
      onEvent: (e) => this.dispatch(rec, e),
      onDone: () => { rec.finished = true; },
    });
    return { jobId };
  }

  /** 更新任務狀態（給 selectRender 用），再轉發給訂閱者 */
  private dispatch(rec: JobRecord, e: JobEvent) {
    switch (e.type) {
      case 'job.status':
        rec.round = e.round;
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
    rec.events.push(e);
    for (const listener of rec.listeners) listener(e);
  }

  private getJob(jobId: string): JobRecord {
    const rec = this.jobs.get(jobId);
    if (!rec) throw new Error(`Unknown job: ${jobId}`);
    return rec;
  }

  subscribe(jobId: string, onEvent: (event: JobEvent) => void): () => void {
    const rec = this.getJob(jobId);
    for (const e of rec.events) onEvent(e);
    rec.listeners.add(onEvent);
    return () => { rec.listeners.delete(onEvent); };
  }

  async cancelJob(jobId: string): Promise<void> {
    const rec = this.getJob(jobId);
    if (rec.finished) return;
    rec.player?.cancel();
    rec.finished = true;
    this.dispatch(rec, { type: 'job.status', stage: 'cancelled', round: rec.round });
  }

  async selectRender(jobId: string, renderId: string, copy: Copy): Promise<HistoryEntry> {
    const rec = this.getJob(jobId);
    const render = rec.renders.get(renderId);
    if (!render) throw new Error(`Unknown render: ${renderId}`);
    const entry: HistoryEntry = {
      id: makeId('hist'), jobId, brandId: rec.input.brandId, productId: rec.input.productId, templateId: render.templateId,
      render: structuredClone(render), copy: structuredClone(copy), selectedAt: this.now().toISOString(),
      favorite: false, writtenToRag: true,
    };
    const history = (await this.store.get<HistoryEntry[]>(KEYS.history)) ?? [];
    await this.store.set(KEYS.history, [entry, ...history]);
    return entry;
  }

  async listHistory(brandId?: string): Promise<HistoryEntry[]> {
    const history = (await this.store.get<HistoryEntry[]>(KEYS.history)) ?? [];
    return brandId ? history.filter((h) => h.brandId === brandId) : history;
  }
}
```

- [ ] **Step 8: 實作 `web/src/lib/api/index.ts`**

```ts
import type { ApiClient } from './client';
import { MockApiClient } from './mock/client';

export type { ApiClient, DemoControls, ProductDraft } from './client';

let instance: ApiClient | null = null;

/** 依 NEXT_PUBLIC_API_MODE 選擇實作（預設 mock）。第二階段加入 live → HttpApiClient。 */
export function getApiClient(): ApiClient {
  if (instance) return instance;
  const mode = process.env.NEXT_PUBLIC_API_MODE ?? 'mock';
  if (mode !== 'mock') throw new Error(`API 模式「${mode}」尚未實作：第二階段會加入連線 FastAPI 的 HttpApiClient`);
  instance = new MockApiClient();
  return instance;
}
```

- [ ] **Step 9: 執行測試確認通過**

Run: `npx vitest run src/lib/api`
Expected: `player.test.ts`、`client.test.ts` 與先前的 mock 測試全部 PASS

- [ ] **Step 10: 全套驗證**

Run: `npm run test && npm run typecheck && npm run lint`
Expected: 所有測試 PASS；typecheck 與 lint 無錯誤。若 lint 有錯，修正後重跑，不得用 `eslint-disable` 繞過

- [ ] **Step 11: Commit**

```bash
git add web/src/lib/api
git commit -m "feat: add timeline player, ApiClient interface and MockApiClient" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 本計畫範圍外（留給 Plan 2／Plan 3）

| 規格項目 | 歸屬 |
|---|---|
| App shell：頂列、模式切換、品牌切換、Demo 控制台 UI | Plan 2 |
| `/studio` 新任務流程、結果牆、文字編輯器 | Plan 2 |
| 排版引擎的 Canvas 繪製（預覽與匯出共用）、程序化背景、示意商品圖 | Plan 2 |
| PNG 與 zip 匯出（JSZip） | Plan 2 |
| `/products`（上傳、IndexedDB `KeyValueStore`）、`app/api/local-products` 讀取 `assets/products/` | Plan 2 |
| `/queue`、`/history`、`/brands` | Plan 2 |
| `/agent` 任務透視（流程節點、事件串流、JSON、注入參數、RAG rerank、BBox 疊圖、重試 diff） | Plan 3 |
| `/dashboard` 成效儀表板 | Plan 3 |
| Playwright E2E | Plan 3 |

