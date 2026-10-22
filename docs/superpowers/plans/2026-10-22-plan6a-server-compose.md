# Plan 6A：伺服器端排版與規則審查 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** composer 在伺服器端畫出與瀏覽器相同的海報並存成審查用海報，從實際像素量出主色、算真實的 ΔE2000，並新增不加隨機分數的 `/review`；任務透視可以切換顯示審查用海報。

**Architecture:**
- **composer 負責繪圖**：用 @napi-rs/canvas，直接沿用前端的 `scene.ts`（版面）與 `paint.ts`（繪製），新增 `/render`（回傳 PNG 與量到的主色）與 `/review`（7 項規則加 3 項依內容判斷的 VLM 檢查）。
- **worker 負責讀圖與存檔**：以既有的 `resolve_file` 讀商品圖與 Logo，連同請求傳給 composer；拿回的 PNG 存到 `data/jobs/{jobId}/{renderId}.png`。
- **主色量測**：量標題、售價、徽章區塊內的品牌色元素，取最接近品牌主色的色塊。
- **模式切換**：`REVIEW_MODE=composer|sim`。模擬模式（測試、作品集 Demo）完全不變。

**Tech Stack:** @napi-rs/canvas 1.0.13、Noto Sans TC／Noto Serif TC 可變字重 TTF（Google Fonts，OFL）、Node 24、Vitest、FastAPI、SAQ、Pillow、Next.js 16、Playwright、Docker Compose。

**Spec:** `docs/superpowers/specs/2026-10-22-plan6a-server-compose-design.md`；背景見 `docs/superpowers/specs/2026-10-07-phase2-backend-design.md` §5.6。

## 開始前

**分支與工具**
- 在 `main` 上的分支 `feature/plan6a-server-compose` 執行；規格已在這個分支上。
- 需要的工具：
  - Docker Desktop：映像檔取自 AWS 的官方鏡像；字型由 `raw.githubusercontent.com` 下載。
  - uv 0.12 以上。
  - Node.js 24、npm 11。

**測試需要的服務與字型**
- 後端測試需要 postgres、redis 與 chroma（`docker compose up -d --wait postgres redis chroma`）。
- **字型**：Task 1 會下載到 `web/composer/fonts/`。從 Task 5 起 composer 沒有字型就無法啟動，所以後端測試也需要字型。

**不要動到使用者正在用的服務**
- `docker-compose.yml` 設定了 `name: genai-agent`，在 worktree 執行 `docker compose up` 會取代使用者正在用的服務。
- 本計畫只用 `docker compose config --quiet` 與 `npm run e2e:live`（獨立專案 `genai-agent-e2e`）。
- Task 5 的映像檔建置測試使用獨立的映像檔名稱，測完刪除。

**Windows 注意事項**
- 一律用 `127.0.0.1`，不要用 `localhost`。
- 這台 Windows 有另一版系統 Noto Sans TC，字型高度不同。composer 會先清空系統字型再註冊自己的檔案，所以測試結果與 Docker 一致。
- `npm run fixtures` 在 Windows 會以 LF 寫出 fixture，內容與 CRLF 的版本相同；只有換行不同的檔案用 `git checkout -- <檔案>` 還原。

## 本計畫的驗證方式

本計畫的程式碼已在草稿分支 `plan6a-draft2` 上逐 Task 實作並驗證：
- 每段程式碼都直接取自驗證過的版本。
- 每個 Task 都確認過：
  - 「先寫測試」的步驟確實失敗，失敗方式與 Expected 相同；
  - 結束時全部通過，測試數量與 Expected 相同；
  - ruff、`ruff format --check`、mypy（strict）、tsc 與 ESLint 都沒有錯誤。

最後的結果：

| 項目 | 結果 |
|---|---|
| 後端 | 274 passed、3 skipped（沒有模型檔時略過真模型測試）；真模型測試在有模型檔時也通過 |
| 前端 | 51 個測試檔、424 個測試 |
| E2E | mock 5 個、live 6 個（live 使用 `REVIEW_MODE=composer`） |
| Docker 實機驗收（獨立專案 `plan6a-accept`） | 三個品牌第一輪偏色都不通過、說明文字是實際用錯的顏色；重試後 ΔE 0–0.4 通過；分數沒有隨機成分；每張候選一個 PNG；伺服器與瀏覽器的海報一致（規格第 12 節） |

執行時若結果與 Expected 不同，先檢查是否漏了步驟，不要修改測試來配合。

## Global Constraints

- **指令位置**：前端在 `web/`，後端在 `backend/`，`docker compose` 在 repo 根目錄。
- **後端檢查**：
  - Python 3.13、uv。
  - `uv run ruff check .`、`uv run ruff format --check .`（單引號、行寬 120；ruff 把中文字算成兩格寬）與 `uv run mypy`（strict）都必須通過。
- **前端檢查**：
  - `npm run test`、`npm run typecheck`、`npm run lint` 都必須通過。
  - 不用 `eslint-disable` 繞過規則。
  - 不手動修改 `src/components/ui/*`。
  - `getApiClient()` 只在 client 端呼叫。
- **前後端資料約定**：`backend/app/contract.py` 與 `web/src/types/contract.ts` 的欄位名稱、型別、選填規則完全一致；JSON 一律 camelCase。
- **連線**：本機一律 `127.0.0.1`，所有連接埠只綁定 `127.0.0.1`。
- **文字與錯誤**：
  - UI 文字、錯誤訊息、註解都用繁體中文。
  - API 錯誤一律回傳 `{ error: { code, message } }`。
- **繪圖**：
  - @napi-rs/canvas 固定為 `1.0.13`（不加 `^`）。
  - 字型只用 `fonts.lock.json` 列出的檔案。
  - composer 不寫入任何資料，所有寫入都由 worker 負責。
- **模擬模式不變**：
  - `backend/tests/test_parity.py` 不得修改。
  - 模擬版的事件與 mock 劇本相同，只多 `review.completed.image: null`。
- **字型檔不進 git**：`web/composer/fonts/` 列在 `.gitignore` 與 `.dockerignore`。
- **Commit**：每個 Task 結束都要 commit，訊息最後一行加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。

## 實作時決定的細節

草稿實作時確定的細節都已寫進規格。最容易忽略的有：

- **主色量測的位置**：量的是標題、售價、徽章區塊內的品牌色元素，不量背景。原本規格的量法實測 0/30 通過（規格 §2.2）。
- **字重**：@napi-rs/canvas 1.0.12 起，`ctx.font` 的字重才會對應可變字型；1.0.10、1.0.11 會畫成細體加假粗體。
- **圖片處理**：
  - worker 送圖前把長邊大於 2048 像素、或 EXIF 方向不是 1 的圖片轉正縮小；
  - 商品圖的 `blend` 與前端 `productImage` 的選擇相同（去背完成用 `normal`，否則用 `multiply`）。
- **Dockerfile 字型階段**：用 `ADD --checksum` 下載。檔案預設權限是 0600，所以要先 `mkdir -p` 再 `COPY --chmod=0644`；有測試確認網址與 SHA 和清單一致。
- **E2E 選擇器**：單選的 Radix ToggleGroup 角色是 `radiogroup`。

## File Structure

| 檔案 | 責任 |
|---|---|
| `web/composer/fonts.lock.json`、`web/scripts/fetch-fonts.mjs` | 字型清單（網址、位元組數、SHA-256）與下載核對（`npm run fonts`） |
| `web/composer/fonts.ts` | `registerPosterFonts`：清空系統字型後註冊海報字型；`resolveFontsDir` |
| `web/src/lib/review/measure.ts` | `measurePrimary`：從像素量出品牌主色（純函式） |
| `web/src/lib/review/vlm.ts` | `contentVlmChecks`：6B 之前依內容判斷的三項 VLM 檢查 |
| `web/src/lib/review/rules.ts` | `measuredPrimary` 可為 `null`；`bannedWordHits`；`measuredPrimaryOf` |
| `web/composer/app.ts`、`handlers.ts` | 非同步處理、圖檔回應、本文上限；`/review`、`/render` |
| `web/composer/poster.ts` | `renderPoster`：伺服器端繪製並量主色 |
| `web/composer/server.ts` | 啟動時註冊字型，失敗就結束 |
| `backend/app/pipeline/review.py` | `ComposerPosters`（讀圖、縮圖、`/render`、存檔）、`ComposerReviewer`（`/review`）、`fit_image` |
| `backend/app/pipeline/ports.py` | `PosterComposer`、`ComposedPoster`；`Reviewer.review` 多 `poster` 參數 |
| `backend/app/files.py` | `resolve_url`、`poster_file` |
| `web/src/components/agent/review-panel.tsx` | 「預覽／審查用海報」切換 |
| `web/Dockerfile` | 字型下載階段；`POSTER_FONTS_DIR` |

---


### Task 1：海報字型與 @napi-rs/canvas

**Files:**
- Create: `web/composer/fonts.lock.json`、`web/composer/fonts.ts`、`web/scripts/fetch-fonts.mjs`
- Modify: `web/package.json`、`web/package-lock.json`（由 `npm install` 修改）、`web/.gitignore`、`web/.dockerignore`
- Test: `web/composer/fonts.test.ts`、`web/composer/fetch-fonts.test.ts`

**Interfaces:**
- Produces：
  - `web/composer/fonts.ts`：
    - `POSTER_FONTS`（`Noto Sans TC` → `NotoSansTC-VF.ttf`、`Noto Serif TC` → `NotoSerifTC-VF.ttf`）、`FONTS_HINT`、`interface PosterFont { family; path }`；
    - `resolveFontsDir(env = process.env): string`：`POSTER_FONTS_DIR` 優先，否則為 `web/composer/fonts`；
    - `missingPosterFonts(dir): string[]`；
    - `registerPosterFonts(dir): PosterFont[]`：先確認檔案都在，再 `GlobalFonts.removeAll()` 並註冊；失敗丟出中文錯誤。
  - `web/scripts/fetch-fonts.mjs`：`readFontLock`、`verifyFont`、`fetchFonts({ dir, files, fetchImpl?, log?, timeoutMs? })`；以 `npm run fonts [-- 資料夾]` 執行。
  - `web/composer/fonts.lock.json`：`{ files: [{ file, url, bytes, sha256 }] }`（兩個字型、兩份 OFL）。

需要字型的測試在字型不存在時略過，並提示執行 `npm run fonts`。

- [ ] **Step 1: 建立 `web/composer/fonts.lock.json`**

```json
{
  "files": [
    {
      "file": "NotoSansTC-VF.ttf",
      "url": "https://raw.githubusercontent.com/google/fonts/45e3d5269e4a17d823f6d84470bc084dc5ae46f6/ofl/notosanstc/NotoSansTC%5Bwght%5D.ttf",
      "bytes": 11941968,
      "sha256": "864727d210d54f2537bbe23b3a839436c3992af72de9322af5270897246bd44f"
    },
    {
      "file": "NotoSerifTC-VF.ttf",
      "url": "https://raw.githubusercontent.com/google/fonts/45e3d5269e4a17d823f6d84470bc084dc5ae46f6/ofl/notoseriftc/NotoSerifTC%5Bwght%5D.ttf",
      "bytes": 16851596,
      "sha256": "0077e18f57c6908f4a000969880940bdb0dad057c0e8d98b49dc364c3d1b09c6"
    },
    {
      "file": "OFL-NotoSansTC.txt",
      "url": "https://raw.githubusercontent.com/google/fonts/45e3d5269e4a17d823f6d84470bc084dc5ae46f6/ofl/notosanstc/OFL.txt",
      "bytes": 4388,
      "sha256": "1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9"
    },
    {
      "file": "OFL-NotoSerifTC.txt",
      "url": "https://raw.githubusercontent.com/google/fonts/45e3d5269e4a17d823f6d84470bc084dc5ae46f6/ofl/notoseriftc/OFL.txt",
      "bytes": 4350,
      "sha256": "5e0da210fb04058a8c0087985d2d456b931c2579811a49655721d3cf0c36b6d6"
    }
  ]
}
```

- [ ] **Step 2: 建立 `web/composer/fetch-fonts.test.ts`（先寫測試）**

```ts
import { createHash } from 'node:crypto';
import { mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { DEFAULT_FONTS_DIR, fetchFonts, readFontLock, verifyFont } from '../scripts/fetch-fonts.mjs';

const body = (text: string) => Buffer.from(text, 'utf8');
const entry = (file: string, text: string) => ({
  file, url: `https://fonts.test/${file}`, bytes: body(text).length,
  sha256: createHash('sha256').update(body(text)).digest('hex'),
});
const FILES = [entry('A.ttf', 'font A'), entry('OFL.txt', 'licence')];

/** 假的 fetch：依網址回傳內容，記錄被呼叫的網址 */
function fakeFetch(contents: Record<string, string | number>) {
  const calls: string[] = [];
  const impl = async (url: string | URL | Request) => {
    const key = String(url);
    calls.push(key);
    const v = contents[key];
    return typeof v === 'number' ? new Response('nope', { status: v }) : new Response(body(v));
  };
  return { calls, impl: impl as typeof fetch };
}
const good = () => fakeFetch(Object.fromEntries(FILES.map((f) => [f.url, f.file === 'A.ttf' ? 'font A' : 'licence'])));

let dir = '';
beforeEach(() => {
  dir = path.join(mkdtempSync(path.join(tmpdir(), 'fetch-fonts-')), 'fonts');
});
afterEach(() => rmSync(path.dirname(dir), { recursive: true, force: true }));

describe('fetchFonts', () => {
  it('downloads every file, verifies it and skips verified files on the next run', async () => {
    const first = good();
    expect(await fetchFonts({ dir, files: FILES, fetchImpl: first.impl, log: () => {} })).toEqual({
      downloaded: ['A.ttf', 'OFL.txt'], skipped: [],
    });
    expect(readFileSync(path.join(dir, 'A.ttf'), 'utf8')).toBe('font A');
    expect(readdirSync(dir).sort()).toEqual(['A.ttf', 'OFL.txt']);

    const second = good();
    expect(await fetchFonts({ dir, files: FILES, fetchImpl: second.impl, log: () => {} })).toEqual({
      downloaded: [], skipped: ['A.ttf', 'OFL.txt'],
    });
    expect(second.calls).toEqual([]);
  });

  it('re-downloads a local file that no longer matches the lock', async () => {
    await fetchFonts({ dir, files: FILES, fetchImpl: good().impl, log: () => {} });
    writeFileSync(path.join(dir, 'A.ttf'), 'font B');
    const again = good();
    const lines: string[] = [];
    expect((await fetchFonts({ dir, files: FILES, fetchImpl: again.impl, log: (l) => lines.push(l) })).downloaded).toEqual(['A.ttf']);
    expect(again.calls).toEqual(['https://fonts.test/A.ttf']);
    expect(lines).toEqual(['檔案與清單不符，重新下載：A.ttf（6 B）', '已存在，略過：OFL.txt']);
    expect(readFileSync(path.join(dir, 'A.ttf'), 'utf8')).toBe('font A');
  });

  it('rejects a download whose checksum differs and leaves nothing behind', async () => {
    const tampered = fakeFetch({ [FILES[0].url]: 'font X', [FILES[1].url]: 'licence' });
    await expect(fetchFonts({ dir, files: FILES, fetchImpl: tampered.impl, log: () => {} }))
      .rejects.toThrow(`A.ttf 的 SHA-256 不符：預期 ${FILES[0].sha256}`);
    expect(readdirSync(dir)).toEqual([]);
  });

  it('reports HTTP and network errors in Chinese', async () => {
    await expect(fetchFonts({ dir, files: FILES, fetchImpl: fakeFetch({ [FILES[0].url]: 404 }).impl, log: () => {} }))
      .rejects.toThrow('無法下載 A.ttf：HTTP 404（https://fonts.test/A.ttf）');
    const offline = (async () => {
      throw new TypeError('fetch failed');
    }) as typeof fetch;
    await expect(fetchFonts({ dir, files: FILES, fetchImpl: offline, log: () => {} }))
      .rejects.toThrow('無法下載 A.ttf：fetch failed（請確認可以連到 raw.githubusercontent.com）');
  });
});

describe('verifyFont', () => {
  it('checks the byte count before the checksum', () => {
    expect(() => verifyFont(FILES[0], body('font'))).toThrow('A.ttf 大小不符：預期 6 位元組，實際 4 位元組');
    expect(() => verifyFont(FILES[0], body('font A'))).not.toThrow();
  });
});

describe('the real lock file', () => {
  it('is read from composer/fonts.lock.json and downloads into composer/fonts by default', async () => {
    expect((await readFontLock()).map((f: { file: string }) => f.file)).toContain('NotoSansTC-VF.ttf');
    expect(DEFAULT_FONTS_DIR).toBe(path.join(path.dirname(fileURLToPath(import.meta.url)), 'fonts'));
  });
});
```

- [ ] **Step 3: 建立 `web/composer/fonts.test.ts`（先寫測試）**

```ts
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createCanvas, GlobalFonts } from '@napi-rs/canvas';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { SELUNE } from '@/lib/api/mock/data';
import { fontStacks } from '@/lib/compose/assets';
import lock from './fonts.lock.json';
import { FONTS_HINT, missingPosterFonts, POSTER_FONTS, registerPosterFonts, resolveFontsDir } from './fonts';

const FONTS_DIR = resolveFontsDir();
const MISSING = missingPosterFonts(FONTS_DIR);
if (MISSING.length) console.warn(`略過需要字型的測試：找不到 ${MISSING.join('、')}。${FONTS_HINT}`);

const PINNED = 'https://raw.githubusercontent.com/google/fonts/45e3d5269e4a17d823f6d84470bc084dc5ae46f6/ofl/';

describe('fonts.lock.json', () => {
  it('pins both poster fonts and their licences to one google/fonts commit', () => {
    expect(lock.files.map((f) => f.file)).toEqual([
      'NotoSansTC-VF.ttf', 'NotoSerifTC-VF.ttf', 'OFL-NotoSansTC.txt', 'OFL-NotoSerifTC.txt',
    ]);
    for (const f of POSTER_FONTS) expect(lock.files.map((e) => e.file)).toContain(f.file);
    for (const f of lock.files) {
      expect(f.url.startsWith(PINNED)).toBe(true);
      expect(f.sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(f.bytes).toBeGreaterThan(0);
    }
  });
});

describe('resolveFontsDir', () => {
  it('defaults to web/composer/fonts and honours POSTER_FONTS_DIR', () => {
    const here = path.dirname(fileURLToPath(import.meta.url));
    expect(resolveFontsDir({})).toBe(path.join(here, 'fonts'));
    expect(resolveFontsDir({ POSTER_FONTS_DIR: 'some/fonts' })).toBe(path.resolve('some/fonts'));
  });
});

describe('registerPosterFonts failures', () => {
  const tmp = mkdtempSync(path.join(tmpdir(), 'poster-fonts-'));
  afterAll(() => rmSync(tmp, { recursive: true, force: true }));

  it('names the missing files, points at npm run fonts and keeps the current fonts', () => {
    const before = GlobalFonts.families.length;
    expect(() => registerPosterFonts(tmp)).toThrow(/找不到字型檔：.*NotoSansTC-VF\.ttf.*NotoSerifTC-VF\.ttf.*npm run fonts/);
    expect(GlobalFonts.families.length).toBe(before);
  });

  it('throws when a font file cannot be registered', () => {
    for (const f of POSTER_FONTS) writeFileSync(path.join(tmp, f.file), 'not a font');
    expect(() => registerPosterFonts(tmp)).toThrow(/字型註冊失敗：.*NotoSansTC-VF\.ttf（Noto Sans TC）/);
  });
});

describe.skipIf(MISSING.length > 0)(`registerPosterFonts with the pinned fonts（沒有字型時略過：${FONTS_HINT}）`, () => {
  const ctx = createCanvas(16, 16).getContext('2d');
  const stacks = fontStacks(SELUNE);
  const width = (font: string, text: string) => {
    ctx.font = font;
    return ctx.measureText(text).width;
  };

  beforeAll(() => {
    expect(registerPosterFonts(FONTS_DIR)).toEqual(
      POSTER_FONTS.map((f) => ({ family: f.family, path: path.join(FONTS_DIR, f.file) })),
    );
  });

  it('replaces every other font, including system fonts, with the two poster fonts', () => {
    expect(GlobalFonts.families.map((f) => f.family).sort()).toEqual(['Noto Sans TC', 'Noto Serif TC']);
    expect(GlobalFonts.has('Noto Sans TC')).toBe(true);
    expect(GlobalFonts.has('Noto Serif TC')).toBe(true);
  });

  it('gives CJK text one em per character at every weight the posters use', () => {
    const text = '溫柔呵護每一天';
    for (const w of [400, 500, 700]) expect(width(`${w} 100px ${stacks.body}`, text)).toBeCloseTo(700, 1);
    for (const w of [700, 900]) expect(width(`${w} 100px ${stacks.headline}`, text)).toBeCloseTo(700, 1);
  });

  it('drives the variable weight axis through ctx.font (Latin widths grow with weight)', () => {
    // 寬度在 Windows 與 Alpine 相同；系統內建的另一版 Noto Sans TC 量起來是 805，這裡量到的一定是我們的字型
    const text = 'Hamburgefonstiv 123';
    expect(width(`400 100px ${stacks.body}`, text)).toBeCloseTo(994.25, 0);
    expect(width(`500 100px ${stacks.body}`, text)).toBeCloseTo(1020.42, 0);
    expect(width(`700 100px ${stacks.body}`, text)).toBeCloseTo(1054.21, 0);
    expect(width(`700 100px ${stacks.headline}`, text)).toBeCloseTo(1082.73, 0);
    expect(width(`900 100px ${stacks.headline}`, text)).toBeCloseTo(1105.9, 0);
  });
});
```

- [ ] **Step 4: 確認測試失敗**

Run（在 `web/`）：`npx vitest run composer/fetch-fonts.test.ts composer/fonts.test.ts`
Expected：2 個測試檔載入失敗：找不到 `../scripts/fetch-fonts.mjs` 與 `./fonts.lock.json`。

- [ ] **Step 5: 加入 @napi-rs/canvas**

版本固定為 1.0.13：1.0.12 起，`ctx.font` 的字重才會對應可變字型。lockfile 會列出各平台的預編譯檔，Docker 的 Alpine 映像檔也用得到。在 `web/` 執行：

```bash
npm install --save-exact @napi-rs/canvas@1.0.13
```

- [ ] **Step 6: 修改 `web/package.json` 的 scripts**

找到：

```json
    "composer": "tsx composer/server.ts"
```

改成：

```json
    "composer": "tsx composer/server.ts",
    "fonts": "node scripts/fetch-fonts.mjs"
```

- [ ] **Step 7: 建立 `web/scripts/fetch-fonts.mjs`**

```js
// 下載 composer 伺服器端繪圖用的字型（Noto Sans／Serif TC 可變字重與 OFL 授權文字），核對位元組數與 SHA-256：
//   npm run fonts                 → 下載到 POSTER_FONTS_DIR，沒有設定時為 composer/fonts/（不進 git）
//   npm run fonts -- <資料夾>      → 下載到指定資料夾
// 清單在 composer/fonts.lock.json，Dockerfile 使用同一組網址與 SHA-256。已存在且核對無誤的檔案會略過，可重複執行。
import { createHash } from 'node:crypto';
import { mkdir, readFile, rename, rm, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const WEB_DIR = path.resolve(import.meta.dirname, '..');
export const LOCK_PATH = path.join(WEB_DIR, 'composer', 'fonts.lock.json');
export const DEFAULT_FONTS_DIR = path.join(WEB_DIR, 'composer', 'fonts');

/** @typedef {{ file: string; url: string; bytes: number; sha256: string }} FontLockEntry */

const sha256 = (buf) => createHash('sha256').update(buf).digest('hex');
const size = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n >= 1e3 ? `${(n / 1e3).toFixed(1)} KB` : `${n} B`);

/** 讀取字型清單（composer/fonts.lock.json） */
export async function readFontLock(lockPath = LOCK_PATH) {
  /** @type {{ files: FontLockEntry[] }} */
  const lock = JSON.parse(await readFile(lockPath, 'utf8'));
  return lock.files;
}

/**
 * 核對檔案內容與清單相符，不符時丟出中文錯誤。
 * @param {FontLockEntry} entry
 * @param {Buffer} buf
 */
export function verifyFont(entry, buf) {
  if (buf.length !== entry.bytes) {
    throw new Error(`${entry.file} 大小不符：預期 ${entry.bytes} 位元組，實際 ${buf.length} 位元組`);
  }
  const actual = sha256(buf);
  if (actual !== entry.sha256) throw new Error(`${entry.file} 的 SHA-256 不符：預期 ${entry.sha256}，實際 ${actual}`);
}

/** @returns {Promise<'valid' | 'invalid' | 'missing'>} */
async function localState(target, entry) {
  try {
    if (!(await stat(target)).isFile()) return 'invalid';
    verifyFont(entry, await readFile(target));
    return 'valid';
  } catch (err) {
    return err && err.code === 'ENOENT' ? 'missing' : 'invalid';
  }
}

/**
 * @param {FontLockEntry} entry
 * @param {typeof fetch} fetchImpl
 * @param {number} timeoutMs
 */
async function download(entry, fetchImpl, timeoutMs) {
  let res;
  let buf;
  try {
    res = await fetchImpl(entry.url, { signal: AbortSignal.timeout(timeoutMs) });
    if (res.ok) buf = Buffer.from(await res.arrayBuffer());
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    throw new Error(`無法下載 ${entry.file}：${reason}（請確認可以連到 raw.githubusercontent.com）`, { cause: err });
  }
  if (!res.ok) throw new Error(`無法下載 ${entry.file}：HTTP ${res.status}（${entry.url}）`);
  return buf;
}

/**
 * 下載清單上的檔案到 dir 並逐一核對。先寫成 .part，核對通過才改名，中斷時不會留下不完整的字型檔。
 * @param {{ dir: string; files: FontLockEntry[]; fetchImpl?: typeof fetch; log?: (line: string) => void; timeoutMs?: number }} options
 * @returns {Promise<{ downloaded: string[]; skipped: string[] }>}
 */
export async function fetchFonts({ dir, files, fetchImpl = fetch, log = console.log, timeoutMs = 300_000 }) {
  await mkdir(dir, { recursive: true });
  const downloaded = [];
  const skipped = [];
  for (const entry of files) {
    const target = path.join(dir, entry.file);
    const state = await localState(target, entry);
    if (state === 'valid') {
      log(`已存在，略過：${entry.file}`);
      skipped.push(entry.file);
      continue;
    }
    log(`${state === 'invalid' ? '檔案與清單不符，重新下載' : '下載'}：${entry.file}（${size(entry.bytes)}）`);
    const buf = await download(entry, fetchImpl, timeoutMs);
    verifyFont(entry, buf);
    const part = `${target}.part`;
    try {
      await writeFile(part, buf);
      await rename(part, target);
    } catch (err) {
      await rm(part, { force: true });
      throw err;
    }
    downloaded.push(entry.file);
  }
  return { downloaded, skipped };
}

async function main() {
  const dir = path.resolve(process.argv[2] ?? process.env.POSTER_FONTS_DIR ?? DEFAULT_FONTS_DIR);
  try {
    const { downloaded, skipped } = await fetchFonts({ dir, files: await readFontLock() });
    console.log(`字型已就緒：${dir}（下載 ${downloaded.length} 個，已存在 ${skipped.length} 個）`);
  } catch (err) {
    console.error(`字型下載失敗：${err instanceof Error ? err.message : String(err)}`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) await main();
```

- [ ] **Step 8: 建立 `web/composer/fonts.ts`**

```ts
// composer 伺服器端繪圖用的字型：清空所有字型後，只註冊固定版本的 Noto Sans／Serif TC（npm run fonts 下載）。
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { GlobalFonts } from '@napi-rs/canvas';

/** 前端 `fontStacks` 用到的字型名稱與 fonts.lock.json 中的檔案。一個可變字重檔涵蓋所有字重。 */
export const POSTER_FONTS = [
  { family: 'Noto Sans TC', file: 'NotoSansTC-VF.ttf' },
  { family: 'Noto Serif TC', file: 'NotoSerifTC-VF.ttf' },
] as const;

export const FONTS_HINT = '請在 web/ 執行 npm run fonts 下載字型';

export interface PosterFont { family: string; path: string }

/** 字型資料夾：環境變數 POSTER_FONTS_DIR，沒有設定時為 web/composer/fonts */
export function resolveFontsDir(env: Record<string, string | undefined> = process.env): string {
  return path.resolve(env.POSTER_FONTS_DIR || fileURLToPath(new URL('fonts', import.meta.url)));
}

/** dir 中缺少的字型檔（完整路徑） */
export function missingPosterFonts(dir: string): string[] {
  return POSTER_FONTS.map((f) => path.join(dir, f.file)).filter((p) => !existsSync(p));
}

/**
 * 先清空所有字型（含系統字型），再註冊兩個海報字型。
 * 系統可能裝了另一版 Noto Sans TC（字高不同），不清空的話，繪圖結果會依機器而異。
 * 任一檔案不存在或註冊失敗就丟出錯誤；檔案不存在時不會清空既有字型。
 */
export function registerPosterFonts(dir: string): PosterFont[] {
  const missing = missingPosterFonts(dir);
  if (missing.length) throw new Error(`找不到字型檔：${missing.join('、')}。${FONTS_HINT}`);
  GlobalFonts.removeAll();
  return POSTER_FONTS.map(({ family, file }) => {
    const fontPath = path.join(dir, file);
    if (!GlobalFonts.registerFromPath(fontPath, family)) {
      throw new Error(`字型註冊失敗：${fontPath}（${family}），檔案可能已損毀。${FONTS_HINT}`);
    }
    return { family, path: fontPath };
  });
}
```

- [ ] **Step 9: 修改 `web/.gitignore`**

找到：

```text
# production
/build

# misc
.DS_Store
*.pem
```

改成：

```text
# production
/build

# composer 伺服器端繪圖用的字型（npm run fonts 下載，約 29 MB）
/composer/fonts/

# misc
.DS_Store
*.pem
```

- [ ] **Step 10: 修改 `web/.dockerignore`**

字型由 Dockerfile 的字型階段提供（Task 5），本機的檔案不進映像檔。

找到：

```text
*.tsbuildinfo
.env
.env.*
```

改成：

```text
*.tsbuildinfo
.env
.env.*
composer/fonts
```

- [ ] **Step 11: 下載字型**

Run（在 `web/`）：`npm run fonts`
Expected：下載並核對 4 個檔案（約 29 MB）到 `web/composer/fonts/`；再執行一次時 4 個都略過。`git status` 不會出現這些檔案。

- [ ] **Step 12: 確認全部通過**

Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint`
Expected：46 個測試檔、360 個測試通過；沒有錯誤。

Run（在 `backend/`）：`uv run pytest -q`
Expected：259 passed、3 skipped（沒有模型檔時略過真模型測試）。

- [ ] **Step 13: Commit**

```bash
git add \
  web/.dockerignore \
  web/.gitignore \
  web/composer/fetch-fonts.test.ts \
  web/composer/fonts.lock.json \
  web/composer/fonts.test.ts \
  web/composer/fonts.ts \
  web/package-lock.json \
  web/package.json \
  web/scripts/fetch-fonts.mjs
git commit -m "feat: add the poster fonts and the @napi-rs/canvas setup" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2：從像素量出品牌主色

**Files:**
- Create: `web/src/lib/review/measure.ts`
- Modify: `web/src/lib/review/color.ts`
- Test: `web/src/lib/review/measure.test.ts`、`web/src/lib/review/color.test.ts`

**Interfaces:**
- Produces：
  - `web/src/lib/review/color.ts`：`labToHex(lab: Lab): Hex`。
  - `web/src/lib/review/measure.ts`：
    - `type RGBA = Uint8ClampedArray | Uint8Array`；
    - `interface MeasuredPrimary { hex: string | null; share: number; deltaE: number | null }`；
    - `PRIMARY_MEASURE`（`block: 4`、`chromaCap: 10`、`chromaRatio: 0.5`、`bin: 3`、`minShare: 0.02`）、`PRIMARY_ROLE_IDS`；
    - `measurePrimary(pixels, width, height, layout: LayoutBox[], brandPrimary: string, maxDeltaE = 5): MeasuredPrimary`。`hex` 為小寫；沒有候選時回傳 `{ hex: null, share: 0, deltaE: null }`。

演算法見規格 §4.2。量的是標題、售價、徽章區塊內的品牌色元素，不量背景。

- [ ] **Step 1: 修改 `web/src/lib/review/color.test.ts`（先寫測試）**

找到（1／2）：

```ts
import { describe, it, expect } from 'vitest';
import { hexToRgb, rgbToHex, mixHex, rgbToLab, deltaE2000, deltaEHex } from './color';

describe('hex conversion', () => {
  it('parses and formats hex colors', () => {
```

改成：

```ts
import { describe, it, expect } from 'vitest';
import { mulberry32 } from '@/lib/core/num';
import { hexToRgb, rgbToHex, mixHex, rgbToLab, labToHex, deltaE2000, deltaEHex } from './color';

describe('hex conversion', () => {
  it('parses and formats hex colors', () => {
```

找到（2／2）：

```ts
  });
});

describe('deltaE2000', () => {
  // Sharma, Wu & Dalal (2005) CIEDE2000 測試資料
  it.each([
```

改成：

```ts
  });
});

describe('labToHex', () => {
  it('inverts rgbToLab for every 8-bit grey and a deterministic sample of colours', () => {
    const colours: [number, number, number][] = [[0, 0, 0], [255, 255, 255], [183, 110, 121], [30, 136, 229]];
    for (let v = 0; v < 256; v++) colours.push([v, v, v]);
    const rng = mulberry32(7);
    for (let i = 0; i < 2000; i++) colours.push([0, 1, 2].map(() => Math.floor(rng() * 256)) as [number, number, number]);
    for (const rgb of colours) expect(labToHex(rgbToLab(rgb))).toBe(rgbToHex(rgb));
  });

  it('clamps colours outside the sRGB gamut', () => {
    expect(labToHex({ L: 50, a: 127, b: -127 })).toMatch(/^#[0-9a-f]{6}$/);
    expect(labToHex({ L: 120, a: 0, b: 0 })).toBe('#ffffff');
  });
});

describe('deltaE2000', () => {
  // Sharma, Wu & Dalal (2005) CIEDE2000 測試資料
  it.each([
```

- [ ] **Step 2: 建立 `web/src/lib/review/measure.test.ts`（先寫測試）**

以合成的 RGBA 資料測試各種情況，不需要字型或 canvas。

```ts
import { describe, it, expect } from 'vitest';
import type { BBox, LayoutBox } from '@/types/contract';
import { computeLayout } from '@/lib/compose/layout';
import { getTemplate } from '@/lib/compose/templates';
import { mulberry32 } from '@/lib/core/num';
import { deltaEHex, hexToRgb, mixHex, rgbToLab } from './color';
import { measurePrimary, PRIMARY_MEASURE } from './measure';

const ROSE = '#B76E79';
const PINK = '#E0458A';
const BLUE = '#1E88E5';
const LAVENDER = '#B8A5D6';

// 240×200 的合成海報。量測範圍：標題 400 格 + 售價 400 格 + 徽章未被商品蓋住的 200 格 = 1000 個 4×4 格。
const W = 240;
const H = 200;
const HEADLINE: BBox = [0, 0, 160, 40];
const PRICE: BBox = [0, 160, 160, 40];
const BADGE: BBox = [160, 0, 80, 80];
const PRODUCT: BBox = [160, 40, 80, 160];
/** 標題與售價之間、量測範圍外的區域 */
const MIDDLE: BBox = [0, 40, 160, 120];
const LAYOUT: LayoutBox[] = [
  { id: 'logo', bbox: [0, 44, 60, 16], z: 2 },
  { id: 'headline', bbox: HEADLINE, z: 2 },
  { id: 'subhead', bbox: [0, 64, 160, 16], z: 2 },
  { id: 'features', bbox: [0, 84, 160, 16], z: 2 },
  { id: 'product', bbox: PRODUCT, z: 1 },
  { id: 'badge', bbox: BADGE, z: 3 },
  { id: 'price', bbox: PRICE, z: 2 },
  { id: 'disclaimer', bbox: [0, 104, 160, 16], z: 2 },
];

class Picture {
  readonly data: Uint8ClampedArray;
  constructor(readonly width: number, readonly height: number, background = '#FFFFFF') {
    this.data = new Uint8ClampedArray(width * height * 4);
    this.fill([0, 0, width, height], background);
  }

  fill([x0, y0, w, h]: BBox, hex: string, keep: (x: number, y: number) => boolean = () => true): this {
    const rgba = [...hexToRgb(hex), 255];
    for (let y = y0; y < y0 + h; y++) {
      for (let x = x0; x < x0 + w; x++) {
        if (keep(x, y)) this.data.set(rgba, (y * this.width + x) * 4);
      }
    }
    return this;
  }

  /** 像文字一樣的橫條：每 period 像素畫 thickness 像素高 */
  stripes(box: BBox, hex: string, period = 8, thickness = 4): this {
    return this.fill(box, hex, (_, y) => (y - box[1]) % period < thickness);
  }

  /** 每個 RGB 分量加上 ±amp 的均勻雜訊（固定 seed） */
  noise(amp: number, seed = 1): this {
    const rng = mulberry32(seed);
    for (let i = 0; i < this.data.length; i += 4) {
      for (let j = 0; j < 3; j++) this.data[i + j] = this.data[i + j] + Math.round((rng() * 2 - 1) * amp);
    }
    return this;
  }
}

const poster = (background = '#FFFFFF') => new Picture(W, H, background);
const measure = (p: Picture, primary = ROSE, maxDeltaE?: number) =>
  measurePrimary(p.data, p.width, p.height, LAYOUT, primary, maxDeltaE);

describe('measurePrimary', () => {
  it('measures the brand primary drawn in the headline, price and badge', () => {
    // 每個區塊一半的格子是主色：標題 200 + 售價 200 + 徽章 100 = 500 / 1000
    const p = poster().stripes(HEADLINE, ROSE).stripes(PRICE, ROSE).stripes(BADGE, ROSE);
    expect(measure(p)).toEqual({ hex: '#b76e79', share: 0.5, deltaE: 0 });
  });

  it('tolerates noise and anti-aliased edges', () => {
    // 6 像素高的橫條不對齊 4×4 格，邊緣的格子是混色；再加上 ±12 的雜訊
    const p = poster('#F6EFE9').stripes(HEADLINE, ROSE, 10, 6).stripes(PRICE, ROSE, 10, 6).noise(12);
    const r = measure(p);
    expect(r.hex).not.toBeNull();
    expect(r.deltaE).toBeLessThan(1.5);
    expect(r.share).toBeGreaterThan(0.2);
    expect(r.deltaE).toBe(deltaEHex(r.hex!, ROSE));
  });

  it('ignores colours outside the headline, price and badge boxes', () => {
    const p = poster().stripes(HEADLINE, ROSE).fill(MIDDLE, BLUE).fill(PRODUCT, BLUE);
    expect(measure(p)).toEqual({ hex: '#b76e79', share: 0.2, deltaE: 0 });
  });

  it('needs at least 2% of the region before a colour counts', () => {
    expect(PRIMARY_MEASURE.minShare).toBe(0.02);
    expect(measure(poster().fill([0, 0, 4 * 19, 4], ROSE))).toEqual({ hex: null, share: 0, deltaE: null });
    expect(measure(poster().fill([0, 0, 4 * 20, 4], ROSE))).toEqual({ hex: '#b76e79', share: 0.02, deltaE: 0 });
  });

  it('returns null when nothing in the region is chromatic', () => {
    const p = poster().stripes(HEADLINE, '#000000').stripes(PRICE, '#808080').fill(BADGE, '#F0F0F0').fill(MIDDLE, BLUE);
    expect(measure(p)).toEqual({ hex: null, share: 0, deltaE: null });
    expect(measure(poster())).toEqual({ hex: null, share: 0, deltaE: null });
  });

  it('measures a neutral primary without a chroma floor', () => {
    const p = poster().stripes(HEADLINE, '#222222').stripes(PRICE, '#222222').stripes(BADGE, '#222222');
    expect(measure(p, '#222222')).toEqual({ hex: '#222222', share: 0.5, deltaE: 0 });
  });

  it('measures a pale pastel primary on a cream background', () => {
    const p = poster('#FFF8F0').stripes(HEADLINE, '#F2C4CE').stripes(PRICE, '#F2C4CE');
    expect(measure(p, '#F2C4CE')).toEqual({ hex: '#f2c4ce', share: 0.4, deltaE: 0 });
  });

  it('keeps the nearest colour when it passes, even next to a more vivid one', () => {
    const p = poster().stripes(HEADLINE, ROSE).fill(BADGE, PINK);
    expect(measure(p)).toEqual({ hex: '#b76e79', share: 0.2, deltaE: 0 });
  });

  it('shows the most vivid candidate when even the nearest one is off-brand', () => {
    // 偏色海報：淺藍底（離品牌淡紫較近）上的鮮藍字。判定一樣不通過，但說明要顯示實際用錯的鮮藍
    const LIGHT_BLUE = '#CFE7FA';
    expect(deltaEHex(LIGHT_BLUE, LAVENDER)).toBeLessThan(deltaEHex(BLUE, LAVENDER));
    expect(deltaEHex(LIGHT_BLUE, LAVENDER)).toBeGreaterThan(5);
    const p = poster().fill(HEADLINE, LIGHT_BLUE).fill(PRICE, LIGHT_BLUE).fill(BADGE, LIGHT_BLUE).stripes(HEADLINE, BLUE);

    expect(measure(p, LAVENDER)).toEqual({ hex: '#1e88e5', share: 0.2, deltaE: deltaEHex('#1e88e5', LAVENDER) });
    // 門檻放寬到最近的顏色也算通過時，回報最近的顏色
    expect(measure(p, LAVENDER, 30)).toEqual({ hex: '#cfe7fa', share: 0.8, deltaE: deltaEHex('#cfe7fa', LAVENDER) });
  });

  it('excludes the product box even where it overlaps a role box', () => {
    // 商品（品牌色）蓋在徽章上；排除後只剩標題的偏色，分母也不含商品的格子
    const p = poster().fill(PRODUCT, ROSE).stripes(HEADLINE, PINK);
    expect(measure(p)).toEqual({ hex: '#e0458a', share: 0.2, deltaE: deltaEHex('#e0458a', ROSE) });
  });

  it('samples whole 4×4 blocks whose centre lies in the region', () => {
    // 10×8 的畫布、標題框 x 0–6：只有 x 0–3 那一欄格子的中心（x = 2）在框內；x 8–9 湊不滿一格
    const layout: LayoutBox[] = [
      { id: 'headline', bbox: [0, 0, 6, 8], z: 2 },
      ...(['price', 'badge', 'product'] as const).map((id) => ({ id, bbox: [0, 0, 0, 0] as BBox, z: 2 })),
    ];
    const tiny = (left: string, right: string) => new Picture(10, 8).fill([0, 0, 4, 8], left).fill([4, 0, 6, 8], right);
    const run = (p: Picture) => measurePrimary(p.data, 10, 8, layout, ROSE);
    expect(run(tiny(ROSE, BLUE))).toEqual({ hex: '#b76e79', share: 1, deltaE: 0 });
    expect(run(tiny(BLUE, ROSE))).toMatchObject({ hex: '#1e88e5', share: 1 });
  });

  it('averages the 16 pixels of each block', () => {
    const half = poster().fill(HEADLINE, ROSE, (x, y) => (x + y) % 2 === 0).fill(PRICE, ROSE, (x, y) => (x + y) % 2 === 0);
    const mix = mixHex(ROSE, '#FFFFFF', 0.5);
    expect(measure(half, mix)).toEqual({ hex: mix, share: 0.8, deltaE: 0 });
  });

  it('merges neighbouring Lab bins into one candidate', () => {
    const bin = (hex: string) => {
      const { L, a, b } = rgbToLab(hexToRgb(hex));
      return [L, a, b].map((v) => Math.floor(v / PRIMARY_MEASURE.bin));
    };
    const [l0, a0, b0] = bin(ROSE);
    const shade = Array.from({ length: 40 }, (_, i) => mixHex(ROSE, '#000000', (i + 1) / 400)).find((hex) => {
      const [l, a, b] = bin(hex);
      return (l !== l0 || a !== a0 || b !== b0) && Math.max(Math.abs(l - l0), Math.abs(a - a0), Math.abs(b - b0)) === 1;
    });
    expect(shade).toBeDefined();
    // 主色 200 格、相鄰格的深一點的主色 120 格：合併成一個佔 32% 的候選
    const p = poster().stripes(HEADLINE, ROSE).stripes(PRICE, shade!, 40, 12);
    const r = measure(p);
    expect(r.share).toBeCloseTo(0.32, 10);
    expect(r.deltaE).toBeLessThan(1);
  });

  it('works on a real template layout and leaves the pixels untouched', () => {
    const t = getTemplate('ig-post');
    const layout = computeLayout(t);
    const p = new Picture(t.width, t.height, '#F6EFE9');
    for (const box of layout) if (box.id === 'headline' || box.id === 'price' || box.id === 'badge') p.stripes(box.bbox, ROSE, 12, 8);
    p.fill(layout.find((b) => b.id === 'product')!.bbox, BLUE);
    const before = p.data.slice();
    const r = measurePrimary(p.data, t.width, t.height, layout, ROSE);
    expect(r).toMatchObject({ hex: '#b76e79', deltaE: 0 });
    expect(r.share).toBeGreaterThan(0.5);
    expect(Buffer.from(p.data).equals(Buffer.from(before))).toBe(true);
    expect(measurePrimary(p.data, t.width, t.height, layout, ROSE)).toEqual(r);
  });
});
```

- [ ] **Step 3: 確認測試失敗**

Run（在 `web/`）：`npx vitest run src/lib/review/color.test.ts src/lib/review/measure.test.ts`
Expected：2 個測試檔失敗（2 failed、10 passed）：`measure.test.ts` 找不到 `./measure`；`color.test.ts` 的 2 個測試為 `labToHex is not a function`。

- [ ] **Step 4: 修改 `web/src/lib/review/color.ts`**

找到：

```ts
  const f = (t: number) => (t > 216 / 24389 ? Math.cbrt(t) : ((24389 / 27) * t + 16) / 116);
  const fx = f(x / 95.047), fy = f(y / 100), fz = f(z / 108.883);
  return { L: 116 * fy - 16, a: 500 * (fx - fy), b: 200 * (fy - fz) };
}

/** CIEDE2000 色差（kL = kC = kH = 1） */
```

改成：

```ts
  const f = (t: number) => (t > 216 / 24389 ? Math.cbrt(t) : ((24389 / 27) * t + 16) / 116);
  const fx = f(x / 95.047), fy = f(y / 100), fz = f(z / 108.883);
  return { L: 116 * fy - 16, a: 500 * (fx - fy), b: 200 * (fy - fz) };
}

/** CIE Lab（D65 白點）→ sRGB hex，rgbToLab 的反函數；超出 sRGB 色域的分量截斷到 0–255 */
export function labToHex({ L, a, b }: Lab): Hex {
  const fy = (L + 16) / 116;
  const inv = (t: number) => (t ** 3 > 216 / 24389 ? t ** 3 : (116 * t - 16) / (24389 / 27));
  const x = inv(fy + a / 500) * 0.95047;
  const y = inv(fy);
  const z = inv(fy - b / 200) * 1.08883;
  const gamma = (c: number) => 255 * (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
  return rgbToHex([
    gamma(3.2404542 * x - 1.5371385 * y - 0.4985314 * z),
    gamma(-0.969266 * x + 1.8760108 * y + 0.041556 * z),
    gamma(0.0556434 * x - 0.2040259 * y + 1.0572252 * z),
  ]);
}

/** CIEDE2000 色差（kL = kC = kH = 1） */
```

- [ ] **Step 5: 建立 `web/src/lib/review/measure.ts`**

```ts
import type { LayoutBox } from '@/types/contract';
import { boxMap } from '@/lib/compose/layout';
import type { Rect } from '@/lib/core/geometry';
import { deltaEHex, hexToRgb, labToHex, rgbToLab, type Lab } from './color';

/** 非預乘的 RGBA 像素，逐列排列（canvas `getImageData().data`）。只讀 RGB，假設像素不透明。 */
export type RGBA = Uint8ClampedArray | Uint8Array;

export interface MeasuredPrimary {
  /** 量到的主色；量測範圍內沒有佔比 ≥ 2% 的彩色時為 null */
  hex: string | null;
  /** 這個顏色（峰值周圍 3×3×3 格）的取樣數 ÷ 量測範圍的取樣數，0–1；hex 為 null 時為 0 */
  share: number;
  /** hex 與品牌主色的 ΔE2000；hex 為 null 時為 null */
  deltaE: number | null;
}

/** 主色量測的參數（設計規格 Plan 6A §4.2） */
export const PRIMARY_MEASURE = {
  /** 取樣格的邊長（像素） */
  block: 4,
  /** 彩度門檻 T = min(chromaCap, chromaRatio × 品牌主色的 C*) */
  chromaCap: 10,
  chromaRatio: 0.5,
  /** Lab 直方圖每格的寬度 */
  bin: 3,
  /** 候選峰值的最低佔比 */
  minShare: 0.02,
} as const;

/** 一定以 palette.primary 繪製的區塊；量測範圍是它們的聯集扣掉商品區塊 */
export const PRIMARY_ROLE_IDS = ['headline', 'price', 'badge'] as const;

// 直方圖的格以整數索引表示：((l + OFF) × SPAN + (a + OFF)) × SPAN + (b + OFF)。
// L、a、b 的格號都在 ±43 以內，索引的大小順序就是 (l, a, b) 的字典序；「索引較小者」即字典序較小的格。
const OFF = 64;
const SPAN = 128;
const binIndex = (l: number, a: number, b: number) => ((l + OFF) * SPAN + (a + OFF)) * SPAN + (b + OFF);
/** 3×3×3 鄰域的索引差（含自己），以及去掉自己的 26 個相鄰格 */
const CUBE: number[] = [];
for (let dl = -1; dl <= 1; dl++) {
  for (let da = -1; da <= 1; da++) for (let db = -1; db <= 1; db++) CUBE.push((dl * SPAN + da) * SPAN + db);
}
const NEIGHBOURS = CUBE.filter((d) => d !== 0);

interface Bin { n: number; L: number; a: number; b: number }
interface Candidate { index: number; n: number; hex: string; deltaE: number; chroma: number }

/** ΔE 小者優先；同分時佔比大者，再取索引小者 */
const byDeltaE = (p: Candidate, q: Candidate) => p.deltaE - q.deltaE || q.n - p.n || p.index - q.index;
/** 彩度高者優先；同分時佔比大者，再取索引小者 */
const byChroma = (p: Candidate, q: Candidate) => q.chroma - p.chroma || q.n - p.n || p.index - q.index;
const first = (list: Candidate[], order: (p: Candidate, q: Candidate) => number) =>
  list.reduce((best, c) => (order(c, best) < 0 ? c : best));

const inRect = (x: number, y: number, r: Rect) => x >= r.x && x < r.x + r.w && y >= r.y && y < r.y + r.h;

/**
 * 從繪製好的海報量出品牌主色（設計規格 §4.2）：
 * 1. 範圍：標題、售價、徽章區塊的聯集，扣掉商品區塊。
 * 2. 取樣：完整的 4×4 格，格子中心落在範圍內才採用，取 16 個像素的 sRGB 平均（四捨五入到整數）。
 * 3–4. 轉成 Lab（與 rgbToLab 相同），只保留 C* ≥ T 的取樣。
 * 5. Lab 直方圖（每格 3 單位）：原始計數 ≥ 全部 26 個相鄰格的格為峰值，同分時取索引較小者；
 *    峰值顏色是周圍 3×3×3 格內所有取樣的 Lab 平均，佔比是這些取樣數 ÷ 範圍內的總取樣數。
 * 6–7. 佔比 ≥ 2% 的峰值為候選，取與品牌主色 ΔE2000 最小者；同分時取佔比大者，再取索引小者。
 * 8. 最小 ΔE 超過 maxDeltaE 時（判定一定不通過），改為回報彩度最高的候選，讓說明文字顯示實際用錯的顏色。
 * 9. 沒有候選時 hex 為 null。
 */
export function measurePrimary(
  pixels: RGBA, width: number, height: number, layout: LayoutBox[], brandPrimary: string, maxDeltaE = 5,
): MeasuredPrimary {
  const { block: S, bin: Q } = PRIMARY_MEASURE;
  const boxes = boxMap(layout);
  const include = PRIMARY_ROLE_IDS.map((id) => boxes[id]);
  const product = boxes.product;
  const target = rgbToLab(hexToRgb(brandPrimary));
  const T = Math.min(PRIMARY_MEASURE.chromaCap, PRIMARY_MEASURE.chromaRatio * Math.hypot(target.a, target.b));

  const bins = new Map<number, Bin>();
  let total = 0;
  for (let y0 = 0; y0 + S <= height; y0 += S) {
    for (let x0 = 0; x0 + S <= width; x0 += S) {
      const cx = x0 + S / 2;
      const cy = y0 + S / 2;
      if (inRect(cx, cy, product) || !include.some((r) => inRect(cx, cy, r))) continue;
      let r = 0, g = 0, b = 0;
      for (let y = y0; y < y0 + S; y++) {
        for (let x = x0; x < x0 + S; x++) {
          const i = (y * width + x) * 4;
          r += pixels[i];
          g += pixels[i + 1];
          b += pixels[i + 2];
        }
      }
      total++;
      const lab = rgbToLab([Math.round(r / (S * S)), Math.round(g / (S * S)), Math.round(b / (S * S))]);
      if (Math.hypot(lab.a, lab.b) < T) continue;
      const k = binIndex(Math.floor(lab.L / Q), Math.floor(lab.a / Q), Math.floor(lab.b / Q));
      const bin = bins.get(k);
      if (bin) {
        bin.n++;
        bin.L += lab.L;
        bin.a += lab.a;
        bin.b += lab.b;
      } else {
        bins.set(k, { n: 1, L: lab.L, a: lab.a, b: lab.b });
      }
    }
  }

  const candidates: Candidate[] = [];
  for (const [k, bin] of bins) {
    // 每個相鄰格的計數都較少，或同分但索引較大（d > 0），這格才是峰值
    const isPeak = NEIGHBOURS.every((d) => {
      const nb = bins.get(k + d);
      return !nb || nb.n < bin.n || (nb.n === bin.n && d > 0);
    });
    if (!isPeak) continue;
    const sum = { n: 0, L: 0, a: 0, b: 0 };
    for (const d of CUBE) {
      const nb = bins.get(k + d);
      if (!nb) continue;
      sum.n += nb.n;
      sum.L += nb.L;
      sum.a += nb.a;
      sum.b += nb.b;
    }
    if (sum.n / total < PRIMARY_MEASURE.minShare) continue;
    const lab: Lab = { L: sum.L / sum.n, a: sum.a / sum.n, b: sum.b / sum.n };
    const hex = labToHex(lab);
    candidates.push({ index: k, n: sum.n, hex, deltaE: deltaEHex(hex, brandPrimary), chroma: Math.hypot(lab.a, lab.b) });
  }
  if (!candidates.length) return { hex: null, share: 0, deltaE: null };

  const nearest = first(candidates, byDeltaE);
  const shown = nearest.deltaE <= maxDeltaE ? nearest : first(candidates, byChroma);
  return { hex: shown.hex, share: shown.n / total, deltaE: shown.deltaE };
}
```

- [ ] **Step 6: 確認全部通過**

Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint`
Expected：47 個測試檔、376 個測試通過；沒有錯誤。

- [ ] **Step 7: Commit**

```bash
git add \
  web/src/lib/review/color.test.ts \
  web/src/lib/review/color.ts \
  web/src/lib/review/measure.test.ts \
  web/src/lib/review/measure.ts
git commit -m "feat: measure the brand primary from rendered pixels" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3：量不到主色時的規則，以及依內容判斷的 VLM 檢查

**Files:**
- Create: `web/src/lib/review/vlm.ts`
- Modify: `web/src/lib/review/rules.ts`
- Test: `web/src/lib/review/rules.test.ts`、`web/src/lib/review/vlm.test.ts`

**Interfaces:**
- Consumes：無。
- Produces：
  - `web/src/lib/review/rules.ts`：
    - `RuleContext.measuredPrimary: string | null`；
    - `NO_PRIMARY_MESSAGE` 為「未偵測到主色（主色區塊 < 2%）」；
    - `bannedWordHits(spec, brand): { words: string[]; target: LayoutElementId | null }`（禁用詞規則與 VLM 檢查共用）。
  - `web/src/lib/review/vlm.ts`：`SIMULATED_VLM_NOTE` 為「（模擬，Plan 6B 改用 Gemini）」；`contentVlmChecks(spec: PromptSpec, brand: Brand): ReviewCheck[]`。

mock 的 `mockVlmChecks` 與 `reviewRender` 不變，golden fixture 也不變。

- [ ] **Step 1: 修改 `web/src/lib/review/rules.test.ts`（先寫測試）**

找到（1／3）：

```ts
import type { ReviewCheck } from '@/types/contract';
import { SELUNE, MISTY_ISLE } from '@/lib/api/mock/data';
import { makeSpec } from '@/test/fixtures';
import { findBannedWords, hasClaim, ragRefFor, runRuleChecks, scoreChecks } from './rules';

const byId = (checks: ReviewCheck[], id: ReviewCheck['id']) => checks.find((c) => c.id === id)!;
```

改成：

```ts
import type { ReviewCheck } from '@/types/contract';
import { SELUNE, MISTY_ISLE } from '@/lib/api/mock/data';
import { makeSpec } from '@/test/fixtures';
import {
  bannedWordHits, findBannedWords, hasClaim, NO_PRIMARY_MESSAGE, ragRefFor, runRuleChecks, scoreChecks,
} from './rules';

const byId = (checks: ReviewCheck[], id: ReviewCheck['id']) => checks.find((c) => c.id === id)!;
```

找到（2／3）：

```ts
  it('detects effect claims', () => {
    expect(hasClaim(['醒來透亮發光'], SELUNE.claimWords)).toBe(true);
    expect(hasClaim(['一口清醒'], MISTY_ISLE.claimWords)).toBe(false);
  });

  it('ragRefFor skips the law-alt chunk', () => {
```

改成：

```ts
  it('detects effect claims', () => {
    expect(hasClaim(['醒來透亮發光'], SELUNE.claimWords)).toBe(true);
    expect(hasClaim(['一口清醒'], MISTY_ISLE.claimWords)).toBe(false);
  });

  it('bannedWordHits returns the banned words and the first block that contains one', () => {
    const spec = makeSpec();
    expect(bannedWordHits(spec, SELUNE)).toEqual({ words: [], target: null });
    spec.copy.features = ['醫療級配方'];
    spec.copy.disclaimer = '永久有效';
    expect(bannedWordHits(spec, SELUNE)).toEqual({ words: ['醫療級', '永久'], target: 'features' });
  });

  it('ragRefFor skips the law-alt chunk', () => {
```

找到（3／3）：

```ts
    const c = byId(runRuleChecks({ brand: SELUNE, spec: makeSpec(), measuredPrimary: '#E0458A' }), 'color_delta');
    expect(c.status).toBe('fail');
    expect(c.value).toContain('#E0458A');
  });

  it('fails logo clearance when the logo is pushed into the headline', () => {
```

改成：

```ts
    const c = byId(runRuleChecks({ brand: SELUNE, spec: makeSpec(), measuredPrimary: '#E0458A' }), 'color_delta');
    expect(c.status).toBe('fail');
    expect(c.value).toContain('#E0458A');
  });

  it('fails the color check when no primary could be measured, leaving the other rules alone', () => {
    const spec = makeSpec();
    const none = runRuleChecks({ brand: SELUNE, spec, measuredPrimary: null });
    expect(byId(none, 'color_delta')).toEqual({
      id: 'color_delta', name: '品牌主色色差', kind: 'rule', rule: 'ΔE2000 ≤ 5',
      value: '未偵測到主色（主色區塊 < 2%）', status: 'fail', target: 'canvas', ragRef: 'selune#color',
    });
    expect(NO_PRIMARY_MESSAGE).toBe('未偵測到主色（主色區塊 < 2%）');
    const measured = runRuleChecks({ brand: SELUNE, spec, measuredPrimary: '#B76E79' });
    expect(none.filter((c) => c.id !== 'color_delta')).toEqual(measured.filter((c) => c.id !== 'color_delta'));
  });

  it('reports the measured primary in upper case with its ΔE', () => {
    const c = byId(runRuleChecks({ brand: SELUNE, spec: makeSpec(), measuredPrimary: '#b76f7a' }), 'color_delta');
    expect(c).toMatchObject({ status: 'pass', value: 'ΔE 0.3 · 偵測主色 #B76F7A' });
  });

  it('fails logo clearance when the logo is pushed into the headline', () => {
```

- [ ] **Step 2: 建立 `web/src/lib/review/vlm.test.ts`（先寫測試）**

```ts
import { describe, it, expect } from 'vitest';
import type { PromptSpec, ReviewCheck } from '@/types/contract';
import { MISTY_ISLE, SAMPLE_PRODUCTS, SELUNE } from '@/lib/api/mock/data';
import { applyFlaws, FLAWS } from '@/lib/api/mock/flaws';
import { mockVlmChecks } from '@/lib/api/mock/vlm';
import { CHANNEL_TEMPLATES } from '@/lib/compose/templates';
import { cleanSpec } from '@/test/fixtures';
import { runRuleChecks } from './rules';
import { contentVlmChecks, SIMULATED_VLM_NOTE } from './vlm';

const byId = (checks: ReviewCheck[], id: ReviewCheck['id']) => checks.find((c) => c.id === id)!;
const box = (spec: PromptSpec, id: 'logo' | 'headline') => spec.layout.find((b) => b.id === id)!;

describe('contentVlmChecks', () => {
  it('passes clean specs on every template and marks every result as simulated', () => {
    for (const t of CHANNEL_TEMPLATES) {
      const checks = contentVlmChecks(cleanSpec(SELUNE, undefined, t.id), SELUNE);
      expect(checks.map((c) => [c.id, c.kind, c.status])).toEqual([
        ['vlm_exaggeration', 'vlm', 'pass'], ['vlm_occlusion', 'vlm', 'pass'], ['vlm_quality', 'vlm', 'pass'],
      ]);
      expect(checks.every((c) => c.value.endsWith(SIMULATED_VLM_NOTE))).toBe(true);
    }
    expect(contentVlmChecks(cleanSpec(), SELUNE)).toEqual([
      {
        id: 'vlm_exaggeration', name: '誇大／療效用語', kind: 'vlm', rule: 'VLM 判讀海報文字語意',
        value: '未發現誇大用語（模擬，Plan 6B 改用 Gemini）', status: 'pass', target: null, ragRef: 'selune#law',
      },
      {
        id: 'vlm_occlusion', name: '物件與文字遮擋', kind: 'vlm', rule: 'VLM 判讀元素是否重疊',
        value: '無重疊遮擋（模擬，Plan 6B 改用 Gemini）', status: 'pass', target: null, ragRef: 'selune#logo',
      },
      {
        id: 'vlm_quality', name: '整體畫質', kind: 'vlm', rule: 'VLM 判讀構圖、光線與瑕疵',
        value: '構圖與畫質良好（模擬，Plan 6B 改用 Gemini）', status: 'pass', target: null, ragRef: null,
      },
    ]);
  });

  it('flags the same banned words and block as the banned_words rule', () => {
    const subhead = applyFlaws(cleanSpec(), ['bannedCopy'], SELUNE);
    const features = cleanSpec();
    features.copy.features = ['根治暗沉'];
    const coldbrew = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_misty_coldbrew')!;
    const price = cleanSpec(MISTY_ISLE, coldbrew, 'banner');
    price.copy.price.label = '保證提神價';
    for (const [spec, brand] of [[subhead, SELUNE], [features, SELUNE], [price, MISTY_ISLE]] as const) {
      const vlm = byId(contentVlmChecks(spec, brand), 'vlm_exaggeration');
      const rule = byId(runRuleChecks({ brand, spec, measuredPrimary: brand.palette.primary }), 'banned_words');
      expect(vlm.status).toBe('fail');
      expect(rule.status).toBe('fail');
      expect(vlm.target).toBe(rule.target);
      expect(vlm.value).toBe(`${rule.value.replace('禁用詞', '偵測到')}${SIMULATED_VLM_NOTE}`);
    }
    expect(byId(contentVlmChecks(subhead, SELUNE), 'vlm_exaggeration')).toMatchObject({
      value: '偵測到「根治」「醫療級」（模擬，Plan 6B 改用 Gemini）', target: 'subhead',
    });
  });

  it('fails occlusion when the logo box overlaps the headline box', () => {
    const spec = applyFlaws(cleanSpec(), ['logoCrowding'], SELUNE);
    expect(byId(contentVlmChecks(spec, SELUNE), 'vlm_occlusion')).toMatchObject({
      status: 'fail', value: 'Logo 與標題重疊（模擬，Plan 6B 改用 Gemini）', target: 'logo',
    });
  });

  it('passes occlusion when the logo sits beside the headline without overlapping it', () => {
    const spec = cleanSpec();
    const head = box(spec, 'headline');
    const logo = box(spec, 'logo');
    logo.bbox = [head.bbox[0] + head.bbox[2] + 8, head.bbox[1], logo.bbox[2], logo.bbox[3]];
    // 規則的淨空區只看上下距離，所以不通過；遮擋要框真的重疊才算
    expect(byId(runRuleChecks({ brand: SELUNE, spec, measuredPrimary: '#B76E79' }), 'logo_clearance').status).toBe('fail');
    expect(byId(contentVlmChecks(spec, SELUNE), 'vlm_occlusion').status).toBe('pass');
  });

  it('never warns: quality always passes and there are no candidate-scripted warnings', () => {
    const flawed = applyFlaws(cleanSpec(), FLAWS, SELUNE);
    expect(contentVlmChecks(flawed, SELUNE).map((c) => c.status)).toEqual(['fail', 'fail', 'pass']);
    // mock 依候選編號出現警告（variant 1、2），content 版沒有候選編號
    expect(mockVlmChecks(cleanSpec(), SELUNE, 1).some((c) => c.status === 'warn')).toBe(true);
    expect(mockVlmChecks(cleanSpec(), SELUNE, 2).some((c) => c.status === 'warn')).toBe(true);
    expect(contentVlmChecks(cleanSpec(), SELUNE).some((c) => c.status === 'warn')).toBe(false);
  });
});
```

- [ ] **Step 3: 確認測試失敗**

Run（在 `web/`）：`npx vitest run src/lib/review/rules.test.ts src/lib/review/vlm.test.ts`
Expected：2 個測試檔失敗（2 failed、13 passed）：`vlm.test.ts` 找不到 `./vlm`；`rules.test.ts` 的 `bannedWordHits is not a function`，以及主色為 `null` 時 `Cannot read properties of null`。

- [ ] **Step 4: 修改 `web/src/lib/review/rules.ts`**

找到（1／4）：

```ts
import { areaRatio, verticalGap } from '@/lib/core/geometry';
import { clamp, round1 } from '@/lib/core/num';
import { deltaEHex } from './color';

export function findBannedWords(texts: string[], banned: string[]): string[] {
  const joined = texts.join('\n');
```

改成：

```ts
import { areaRatio, verticalGap } from '@/lib/core/geometry';
import { clamp, round1 } from '@/lib/core/num';
import { deltaEHex } from './color';
import { PRIMARY_MEASURE } from './measure';

export function findBannedWords(texts: string[], banned: string[]): string[] {
  const joined = texts.join('\n');
```

找到（2／4）：

```ts
  return [copy.headline.join(''), copy.subhead, copy.features.join('、'), [copy.badge.top, copy.badge.main].join('｜')];
}

export interface RuleContext {
  brand: Brand;
  spec: PromptSpec;
  /** 從生成圖中偵測到的主色（第二階段由影像分析取得） */
  measuredPrimary: string;
  /** OCR 結果與文案的差異字數 */
  ocrDiffs?: number;
}
```

改成：

```ts
  return [copy.headline.join(''), copy.subhead, copy.features.join('、'), [copy.badge.top, copy.badge.main].join('｜')];
}

/** 文案中出現的禁用詞（依詞庫順序），以及第一個含禁用詞的版面區塊；禁用詞檢查與 VLM 誇大用語共用 */
export function bannedWordHits(spec: PromptSpec, brand: Brand): { words: string[]; target: LayoutElementId | null } {
  const texts = copyTexts(spec);
  const words = findBannedWords(texts.map((t) => t.text), brand.bannedWords);
  return { words, target: texts.find((t) => words.some((w) => t.text.includes(w)))?.id ?? null };
}

/** 量測範圍內沒有佔比夠大的彩色時，主色檢查的說明 */
export const NO_PRIMARY_MESSAGE = `未偵測到主色（主色區塊 < ${PRIMARY_MEASURE.minShare * 100}%）`;

export interface RuleContext {
  brand: Brand;
  spec: PromptSpec;
  /** 從海報量到的主色（measurePrimary）；量不到時為 null，主色檢查判定不通過 */
  measuredPrimary: string | null;
  /** OCR 結果與文案的差異字數 */
  ocrDiffs?: number;
}
```

找到（3／4）：

```ts
  const { width: W, height: H } = spec.canvas;
  const pct = (v: number) => `${round1(v * 100)}%`;

  const texts = copyTexts(spec);
  const banned = findBannedWords(texts.map((t) => t.text), brand.bannedWords);
  const bannedTarget = texts.find((t) => banned.some((w) => t.text.includes(w)))?.id ?? null;

  const dE = deltaEHex(measuredPrimary, brand.palette.primary);

  const gap = verticalGap(B.logo, B.headline);
  const need = Math.round(B.logo.h * 0.5);
```

改成：

```ts
  const { width: W, height: H } = spec.canvas;
  const pct = (v: number) => `${round1(v * 100)}%`;

  const { words: banned, target: bannedTarget } = bannedWordHits(spec, brand);

  const color = measuredPrimary === null
    ? null
    : { hex: measuredPrimary.toUpperCase(), dE: deltaEHex(measuredPrimary, brand.palette.primary) };

  const gap = verticalGap(B.logo, B.headline);
  const need = Math.round(B.logo.h * 0.5);
```

找到（4／4）：

```ts
    },
    {
      id: 'color_delta', name: '品牌主色色差', kind: 'rule', rule: `ΔE2000 ≤ ${brand.rules.maxDeltaE}`,
      value: `ΔE ${round1(dE)} · 偵測主色 ${measuredPrimary.toUpperCase()}`,
      status: dE <= brand.rules.maxDeltaE ? 'pass' : 'fail', target: 'canvas', ragRef: ragRefFor(brand, 'color'),
    },
    {
      id: 'logo_clearance', name: 'Logo 淨空區', kind: 'rule', rule: `間距 ≥ 0.5 × Logo 高（${need}px）`,
```

改成：

```ts
    },
    {
      id: 'color_delta', name: '品牌主色色差', kind: 'rule', rule: `ΔE2000 ≤ ${brand.rules.maxDeltaE}`,
      value: color ? `ΔE ${round1(color.dE)} · 偵測主色 ${color.hex}` : NO_PRIMARY_MESSAGE,
      status: color && color.dE <= brand.rules.maxDeltaE ? 'pass' : 'fail', target: 'canvas', ragRef: ragRefFor(brand, 'color'),
    },
    {
      id: 'logo_clearance', name: 'Logo 淨空區', kind: 'rule', rule: `間距 ≥ 0.5 × Logo 高（${need}px）`,
```

- [ ] **Step 5: 建立 `web/src/lib/review/vlm.ts`**

```ts
import type { Brand, PromptSpec, ReviewCheck } from '@/types/contract';
import { boxMap } from '@/lib/compose/layout';
import { intersectionArea } from '@/lib/core/geometry';
import { bannedWordHits, ragRefFor } from './rules';

/** Plan 6B 接上 Gemini 之前，VLM 三項說明文字的標示 */
export const SIMULATED_VLM_NOTE = '（模擬，Plan 6B 改用 Gemini）';

/**
 * live 模式在 Plan 6B 之前的 VLM 三項：依文案與版面判斷，不依候選編號出現劇本式警告
 * （模擬模式仍用 mock 的 mockVlmChecks）。
 * - 誇大／療效用語：與禁用詞檢查相同的偵測；
 * - 物件與文字遮擋：Logo 框與標題框重疊時不通過，其他情況通過；
 * - 整體畫質：一律通過。
 */
export function contentVlmChecks(spec: PromptSpec, brand: Brand): ReviewCheck[] {
  const { words, target } = bannedWordHits(spec, brand);
  const B = boxMap(spec.layout);
  const occluded = intersectionArea(B.logo, B.headline) > 0;
  const note = (value: string) => `${value}${SIMULATED_VLM_NOTE}`;

  return [
    {
      id: 'vlm_exaggeration', name: '誇大／療效用語', kind: 'vlm', rule: 'VLM 判讀海報文字語意',
      value: note(words.length ? `偵測到${words.map((w) => `「${w}」`).join('')}` : '未發現誇大用語'),
      status: words.length ? 'fail' : 'pass', target, ragRef: ragRefFor(brand, 'law'),
    },
    {
      id: 'vlm_occlusion', name: '物件與文字遮擋', kind: 'vlm', rule: 'VLM 判讀元素是否重疊',
      value: note(occluded ? 'Logo 與標題重疊' : '無重疊遮擋'),
      status: occluded ? 'fail' : 'pass', target: occluded ? 'logo' : null, ragRef: ragRefFor(brand, 'logo'),
    },
    {
      id: 'vlm_quality', name: '整體畫質', kind: 'vlm', rule: 'VLM 判讀構圖、光線與瑕疵',
      value: note('構圖與畫質良好'), status: 'pass', target: null, ragRef: null,
    },
  ];
}
```

- [ ] **Step 6: 確認全部通過**

`npm run fixtures` 之後，`git status contracts/` 不應有任何內容變更。

Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint`
Expected：48 個測試檔、384 個測試通過；沒有錯誤。

- [ ] **Step 7: Commit**

```bash
git add \
  web/src/lib/review/rules.test.ts \
  web/src/lib/review/rules.ts \
  web/src/lib/review/vlm.test.ts \
  web/src/lib/review/vlm.ts
git commit -m "feat: review with a measured or missing primary and content-based VLM checks" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4：composer 支援非同步、圖檔回應，並新增 `/review`

**Files:**
- Modify: `web/composer/app.ts`、`web/composer/handlers.ts`
- Test: `web/composer/app.test.ts`、`web/composer/handlers.test.ts`

**Interfaces:**
- Consumes：Task 3 的 `contentVlmChecks`、`RuleContext.measuredPrimary: string | null`。
- Produces：
  - `web/composer/app.ts`：
    - `MAX_BODY_BYTES = 30 * 1024 * 1024`、`class BodyTooLarge extends Error`；
    - `interface ComposerOptions { handle?; fonts? }`；`createComposerServer({ handle, fonts }: ComposerOptions = {}): Server`；
    - 錯誤：404 `not_found`、400 `too_large`「請求本文超過 30 MB 上限」，其他為 400 `invalid`。
  - `web/composer/handlers.ts`：
    - `class BinaryResponse(body: Buffer, contentType: string, headers = {})`；
    - `handle(path, body)` 可以回傳 Promise。
  - `POST /review`：
    - 輸入 `{ spec, brand, measuredPrimary: string | null }`；
    - 輸出 `{ checks, score, passed }`（`runRuleChecks` 加 `contentVlmChecks`，`scoreChecks(checks, 0)`）；
    - `measuredPrimary` 不是 `#RRGGBB` 也不是 `null` 時回 400。

- [ ] **Step 1: 修改 `web/composer/app.test.ts`（先寫測試）**

找到：

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

改成：

```ts
import type { Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { ReviewCheck } from '@/types/contract';
import { SELUNE } from '@/lib/api/mock/data';
import { cleanSpec } from '@/test/fixtures';
import { createComposerServer, MAX_BODY_BYTES } from './app';
import { BinaryResponse } from './handlers';

/** 在隨機埠啟動伺服器，回傳網址與關閉函式 */
async function start(server: Server): Promise<{ base: string; close: () => Promise<void> }> {
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  return {
    base: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
    close: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}

const post = (base: string, path: string, body: string) =>
  fetch(`${base}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body });

/** 長度剛好 bytes 的 /layout 請求本文（以 pad 欄位補足） */
const layoutBody = (bytes: number) => {
  const head = '{"templateId":"ig-post","pad":"';
  return `${head}${'x'.repeat(bytes - head.length - 2)}"}`;
};

describe('composer server', () => {
  let base = '';
  let close: () => Promise<void>;
  beforeAll(async () => ({ base, close } = await start(createComposerServer({ fonts: ['Noto Sans TC', 'Noto Serif TC'] }))));
  afterAll(() => close());

  it('answers health checks with the registered poster fonts', async () => {
    const res = await fetch(`${base}/health`);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: 'ok', fonts: ['Noto Sans TC', 'Noto Serif TC'] });
  });

  it('runs a handler on POSTed JSON', async () => {
    const res = await post(base, '/layout', JSON.stringify({ templateId: 'ig-post' }));
    expect(res.status).toBe(200);
    expect(await res.json()).toHaveLength(8);
  });

  it('reviews a spec with the measured primary', async () => {
    const res = await post(base, '/review', JSON.stringify({ spec: cleanSpec(), brand: SELUNE, measuredPrimary: '#b76e79' }));
    expect(res.status).toBe(200);
    const body = (await res.json()) as { checks: ReviewCheck[]; score: number; passed: boolean };
    expect(body.checks).toHaveLength(10);
    expect(body).toMatchObject({ score: 100, passed: true });
  });

  it('reports bad requests as JSON errors', async () => {
    const unknown = await post(base, '/nope', '{}');
    expect(unknown.status).toBe(404);
    expect(await unknown.json()).toEqual({ error: { code: 'not_found', message: 'Unknown route: /nope' } });
    const broken = await post(base, '/layout', '{');
    expect(broken.status).toBe(400);
    expect((await broken.json()).error.code).toBe('invalid');
    const review = await post(base, '/review', JSON.stringify({ spec: cleanSpec(), brand: SELUNE, measuredPrimary: 'pink' }));
    expect(review.status).toBe(400);
    expect((await review.json()).error).toEqual({ code: 'invalid', message: 'measuredPrimary 必須是 #RRGGBB 或 null："pink"' });
  });

  it(`accepts a body of exactly ${MAX_BODY_BYTES} bytes and rejects one byte more with a Chinese message`, async () => {
    const ok = await post(base, '/layout', layoutBody(MAX_BODY_BYTES));
    expect(ok.status).toBe(200);
    expect(await ok.json()).toHaveLength(8);
    const big = await post(base, '/layout', layoutBody(MAX_BODY_BYTES + 1));
    expect(big.status).toBe(400);
    expect(await big.json()).toEqual({ error: { code: 'too_large', message: '請求本文超過 30 MB 上限' } });
    // 超過上限後同一個伺服器照常服務
    expect((await post(base, '/layout', JSON.stringify({ templateId: 'story' }))).status).toBe(200);
  });
});

describe('composer server with async and binary handlers', () => {
  let base = '';
  let close: () => Promise<void>;
  beforeAll(async () => ({ base, close } = await start(createComposerServer({
    handle: async (path, body) => {
      await new Promise((resolve) => setTimeout(resolve, 5));
      if (path === '/echo') return { echoed: body };
      if (path === '/bytes') return new BinaryResponse(Buffer.from([0, 1, 2, 255]), 'image/png', { 'X-Extra': 'yes', 'X-Empty': '' });
      throw new Error('非同步的 handler 失敗');
    },
  }))));
  afterAll(() => close());

  it('awaits async handlers before answering', async () => {
    const res = await post(base, '/echo', JSON.stringify({ a: 1 }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ echoed: { a: 1 } });
  });

  it('sends binary responses with their content type and custom headers', async () => {
    const res = await post(base, '/bytes', '{}');
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toBe('image/png');
    expect(res.headers.get('content-length')).toBe('4');
    expect(res.headers.get('x-extra')).toBe('yes');
    expect(res.headers.get('x-empty')).toBe('');
    expect([...new Uint8Array(await res.arrayBuffer())]).toEqual([0, 1, 2, 255]);
  });

  it('turns rejected promises into JSON errors', async () => {
    const res = await post(base, '/fail', '{}');
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: { code: 'invalid', message: '非同步的 handler 失敗' } });
  });

  it('defaults /health to no fonts', async () => {
    expect(await (await fetch(`${base}/health`)).json()).toEqual({ status: 'ok', fonts: [] });
  });
});
```

- [ ] **Step 2: 修改 `web/composer/handlers.test.ts`（先寫測試）**

找到（1／2）：

```ts
import { reviewRender } from '@/lib/api/mock/review';
import { computeLayout } from '@/lib/compose/layout';
import { getTemplate } from '@/lib/compose/templates';
import { handle } from './handlers';

const serum = SAMPLE_PRODUCTS[0] as Product;
```

改成：

```ts
import { reviewRender } from '@/lib/api/mock/review';
import { computeLayout } from '@/lib/compose/layout';
import { getTemplate } from '@/lib/compose/templates';
import { NO_PRIMARY_MESSAGE, runRuleChecks } from '@/lib/review/rules';
import { contentVlmChecks } from '@/lib/review/vlm';
import { cleanSpec } from '@/test/fixtures';
import { handle } from './handlers';

const serum = SAMPLE_PRODUCTS[0] as Product;
```

找到（2／2）：

```ts
    expect(handle('/sim/fixes', { checks: review.checks, brand: SELUNE, spec })).toEqual(planFixes(review.checks, SELUNE, spec));
  });

  it('rejects unknown routes', () => {
    expect(() => handle('/nope', {})).toThrow('Unknown route: /nope');
  });
```

改成：

```ts
    expect(handle('/sim/fixes', { checks: review.checks, brand: SELUNE, spec })).toEqual(planFixes(review.checks, SELUNE, spec));
  });

  it('reviews a poster with 7 rules and 3 content checks, without score jitter', () => {
    const spec = cleanSpec();
    const review = handle('/review', { spec, brand: SELUNE, measuredPrimary: '#b76e79' }) as {
      checks: ReviewCheck[]; score: number; passed: boolean;
    };
    expect(review.checks).toEqual([
      ...runRuleChecks({ brand: SELUNE, spec, measuredPrimary: '#b76e79' }), ...contentVlmChecks(spec, SELUNE),
    ]);
    expect(review.checks.map((c) => c.status).every((s) => s === 'pass')).toBe(true);
    expect(review).toMatchObject({ score: 100, passed: true });
  });

  it('fails the flawed first round with the measured off-brand primary, with the score of scoreChecks(checks, 0)', () => {
    const spec = handle('/sim/prompt', promptBody(true)) as PromptSpec;
    const review = handle('/review', { spec, brand: SELUNE, measuredPrimary: '#e0458a' }) as {
      checks: ReviewCheck[]; score: number; passed: boolean;
    };
    const failed = review.checks.filter((c) => c.status === 'fail').map((c) => c.id);
    expect(failed).toEqual(['banned_words', 'color_delta', 'logo_clearance', 'vlm_exaggeration', 'vlm_occlusion']);
    expect(review.checks.find((c) => c.id === 'color_delta')!.value).toBe('ΔE 12.5 · 偵測主色 #E0458A');
    const warned = review.checks.filter((c) => c.status === 'warn').length;
    expect(review).toMatchObject({ score: 100 - 14 * failed.length - 6 * warned, passed: false });
  });

  it('fails color_delta when no primary was measured', () => {
    const review = handle('/review', { spec: cleanSpec(), brand: SELUNE, measuredPrimary: null }) as {
      checks: ReviewCheck[]; score: number; passed: boolean;
    };
    const color = review.checks.find((c) => c.id === 'color_delta')!;
    expect(color).toMatchObject({ status: 'fail', value: NO_PRIMARY_MESSAGE });
    expect(review).toMatchObject({ score: 86, passed: false });
  });

  it('rejects a measured primary that is not a hex colour or null', () => {
    for (const measuredPrimary of [undefined, 'pink', '#b76e7', 42]) {
      expect(() => handle('/review', { spec: cleanSpec(), brand: SELUNE, measuredPrimary })).toThrow(/measuredPrimary 必須是 #RRGGBB 或 null/);
    }
  });

  it('rejects unknown routes', () => {
    expect(() => handle('/nope', {})).toThrow('Unknown route: /nope');
  });
```

- [ ] **Step 3: 確認測試失敗**

Run（在 `web/`）：`npx vitest run composer/app.test.ts composer/handlers.test.ts`
Expected：2 個測試檔失敗（12 failed、6 passed）：`Unknown route: /review`、`/health` 沒有字型清單、非同步處理與圖檔回應的測試都失敗。

- [ ] **Step 4: 修改 `web/composer/handlers.ts`**

找到（1／2）：

```ts
import { reviewRender } from '@/lib/api/mock/review';
import { computeLayout } from '@/lib/compose/layout';
import { getTemplate } from '@/lib/compose/templates';

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
```

改成：

```ts
import { reviewRender } from '@/lib/api/mock/review';
import { computeLayout } from '@/lib/compose/layout';
import { getTemplate } from '@/lib/compose/templates';
import { runRuleChecks, scoreChecks } from '@/lib/review/rules';
import { contentVlmChecks } from '@/lib/review/vlm';

/** 找不到路徑（伺服器回 404） */
export class UnknownRoute extends Error {}

/** handler 回傳這個型別時，伺服器直接送出位元組與標頭（其他回傳值一律轉成 JSON） */
export class BinaryResponse {
  constructor(
    readonly body: Buffer,
    readonly contentType: string,
    readonly headers: Record<string, string> = {},
  ) {}
}

/** 可以是同步或非同步（回傳 Promise）的函式 */
type Handler = (body: never) => unknown;

const HEX = /^#[0-9a-f]{6}$/i;

/** live 模式的審查：7 項規則加 3 項依內容判斷的 VLM 檢查，分數不加隨機抖動 */
function reviewPoster({ spec, brand, measuredPrimary }: {
  spec: PromptSpec; brand: Brand; measuredPrimary: string | null;
}): { checks: ReviewCheck[]; score: number; passed: boolean } {
  if (measuredPrimary !== null && !(typeof measuredPrimary === 'string' && HEX.test(measuredPrimary))) {
    throw new Error(`measuredPrimary 必須是 #RRGGBB 或 null：${JSON.stringify(measuredPrimary)}`);
  }
  const checks = [...runRuleChecks({ brand, spec, measuredPrimary }), ...contentVlmChecks(spec, brand)];
  return { checks, ...scoreChecks(checks, 0) };
}

/**
 * 後端呼叫的 TypeScript 邏輯：版型、live 模式的審查，以及模擬模式沿用的 mock 行為（/sim/*）。
 * 輸入與輸出都是合約的 JSON。
 */
const HANDLERS: Record<string, Handler> = {
  '/layout': ({ templateId }: { templateId: TemplateId }) => computeLayout(getTemplate(templateId)),

  '/review': reviewPoster,

  '/sim/brief': ({ brand, product, text }: { brand: Brand; product: Product | null; text: string }) =>
    parseBrief(text, brand, product),
```

找到（2／2）：

```ts
    planFixes(checks, brand, spec),
};

export function handle(path: string, body: unknown): unknown {
  const handler = HANDLERS[path];
  if (!handler) throw new UnknownRoute(`Unknown route: ${path}`);
```

改成：

```ts
    planFixes(checks, brand, spec),
};

/** 執行路徑對應的 handler；回傳值可能是 Promise，由伺服器 await */
export function handle(path: string, body: unknown): unknown {
  const handler = HANDLERS[path];
  if (!handler) throw new UnknownRoute(`Unknown route: ${path}`);
```

- [ ] **Step 5: 修改 `web/composer/app.ts`**

找到：

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

改成：

```ts
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import { BinaryResponse, handle as handleRoute, UnknownRoute } from './handlers';

/** 請求本文的上限（位元組）：/render 帶 base64 的商品圖與 Logo */
export const MAX_BODY_BYTES = 30 * 1024 * 1024;

/** 請求本文超過 MAX_BODY_BYTES（伺服器回 400） */
export class BodyTooLarge extends Error {
  constructor() {
    super(`請求本文超過 ${MAX_BODY_BYTES / 1024 / 1024} MB 上限`);
  }
}

export interface ComposerOptions {
  /** 路由；預設為 handlers.ts 的 handle。可以回傳 Promise，也可以回傳 BinaryResponse */
  handle?: (path: string, body: unknown) => unknown;
  /** 已註冊的海報字型名稱，/health 回報 */
  fonts?: string[];
}

function sendJson(res: ServerResponse, status: number, body: unknown, headers: Record<string, string> = {}) {
  res.writeHead(status, { ...headers, 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}

function send(res: ServerResponse, result: unknown) {
  if (!(result instanceof BinaryResponse)) return sendJson(res, 200, result);
  res.writeHead(200, { ...result.headers, 'Content-Type': result.contentType, 'Content-Length': result.body.length });
  res.end(result.body);
}

/**
 * 讀完整個請求本文。超過上限時不再保留內容，但照樣讀到結束才回應：
 * 用戶端（例如 httpx）先送完本文才讀回應，中途關閉連線的話它只會看到連線中斷，看不到 400。
 */
function readBody(req: IncomingMessage): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const parts: Buffer[] = [];
    let size = 0;
    req.on('data', (part: Buffer) => {
      size += part.length;
      if (size <= MAX_BODY_BYTES) parts.push(part);
      else parts.length = 0;
    });
    req.on('end', () => (size > MAX_BODY_BYTES ? reject(new BodyTooLarge()) : resolve(Buffer.concat(parts))));
    req.on('error', reject);
  });
}

/**
 * composer 的 HTTP 介面：GET /health；其他都是 POST JSON。
 * handler 的回傳值轉成 JSON 送出，BinaryResponse 則直接送出位元組（例如 /render 的 PNG）。
 * 錯誤回 { error: { code, message } }：找不到路徑 404，其他 400。
 */
export function createComposerServer({ handle = handleRoute, fonts = [] }: ComposerOptions = {}): Server {
  return createServer(async (req, res) => {
    const path = new URL(req.url ?? '/', 'http://composer').pathname;
    if (req.method === 'GET' && path === '/health') return sendJson(res, 200, { status: 'ok', fonts });
    try {
      const raw = await readBody(req);
      send(res, await handle(path, JSON.parse(raw.toString('utf8') || 'null')));
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (err instanceof UnknownRoute) sendJson(res, 404, { error: { code: 'not_found', message } });
      else if (err instanceof BodyTooLarge) sendJson(res, 400, { error: { code: 'too_large', message } });
      else sendJson(res, 400, { error: { code: 'invalid', message } });
    }
  });
}
```

- [ ] **Step 6: 確認全部通過**

Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint`
Expected：48 個測試檔、394 個測試通過；沒有錯誤。

Run（在 `backend/`）：`uv run pytest -q`
Expected：259 passed、3 skipped（沒有模型檔時略過真模型測試）。

- [ ] **Step 7: Commit**

```bash
git add \
  web/composer/app.test.ts \
  web/composer/app.ts \
  web/composer/handlers.test.ts \
  web/composer/handlers.ts
git commit -m "feat: await async composer handlers, send binary responses and add /review" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5：伺服器端繪製審查用海報，並新增 `/render`

**Files:**
- Create: `web/composer/poster.ts`
- Modify: `web/composer/handlers.ts`、`web/composer/server.ts`、`web/Dockerfile`、`backend/tests/conftest.py`
- Test: `web/composer/poster.test.ts`、`web/composer/server.test.ts`、`web/composer/dockerfile.test.ts`

**Interfaces:**
- Consumes：
  - Task 1 的 `registerPosterFonts`、`resolveFontsDir`；
  - Task 2 的 `measurePrimary`；
  - Task 4 的 `BinaryResponse`、`createComposerServer({ fonts })`。
- Produces：
  - `web/composer/poster.ts`：
    - `interface PosterImages { product: { base64; blend: 'normal' | 'multiply' } | null; logo: { base64 } | null; background?: { base64 } | null }`；
    - `interface RenderPosterInput { render; product; brand; images }`；
    - `renderPoster(input): Promise<{ png: Buffer; measured: MeasuredPrimary }>`。
  - `POST /render`：
    - 輸入 `RenderPosterInput`；
    - 輸出 `image/png`，標頭 `X-Measured-Primary`（小寫 hex，量不到時為空字串）、`X-Primary-Share`（0–1）。
    - 非範例商品缺圖、或圖片無法解碼時回 400（中文訊息）。
  - `server.ts`：啟動時註冊字型，失敗就以結束代碼 1 結束並提示 `npm run fonts`；`/health` 回傳 `{ status, fonts }`。
  - `web/Dockerfile`：`FROM scratch AS fonts` 階段；composer 階段的 `POSTER_FONTS_DIR=/usr/local/share/poster-fonts`。
  - `backend/tests/conftest.py`：composer 啟動失敗時立即報錯，不再等 30 秒。

從這個 Task 起，composer 沒有字型就無法啟動，所以 Dockerfile 的字型階段放在同一個 Task，每個 commit 都能部署。

- [ ] **Step 1: 建立 `web/composer/poster.test.ts`（先寫測試）**

包含 3 個品牌 × 5 個模板的完整矩陣：正確配色必須通過 `color_delta`，偏色必須不通過，而且回報實際用錯的顏色。

```ts
import type { AddressInfo } from 'node:net';
import { createCanvas, loadImage } from '@napi-rs/canvas';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { Brand, Product, PromptSpec, Render, ReviewCheck, TemplateId } from '@/types/contract';
import { TEMPLATE_IDS } from '@/types/contract';
import { seedOf } from '@/lib/agent/prompt';
import { MISTY_ISLE, SAMPLE_PRODUCTS, SELUNE } from '@/lib/api/mock/data';
import { applyFlaws, FLAWS } from '@/lib/api/mock/flaws';
import { boxMap } from '@/lib/compose/layout';
import { fitLogoImage } from '@/lib/compose/scene';
import { getTemplate } from '@/lib/compose/templates';
import { deltaEHex } from '@/lib/review/color';
import { runRuleChecks } from '@/lib/review/rules';
import { cleanSpec } from '@/test/fixtures';
import { createComposerServer } from './app';
import { FONTS_HINT, missingPosterFonts, registerPosterFonts, resolveFontsDir } from './fonts';
import { renderPoster, type PosterImages, type RenderedPoster } from './poster';

const FONTS_DIR = resolveFontsDir();
const MISSING = missingPosterFonts(FONTS_DIR);
if (MISSING.length) console.warn(`略過需要字型的海報測試：找不到 ${MISSING.join('、')}。${FONTS_HINT}`);

/** 第三個品牌：仿 brands/my-brand-01.yaml（淡紫主色、背景風格退回 plain），只用於測試 */
const KAYLA: Brand = {
  id: 'my-brand-01',
  name: 'Kayla 精緻少女',
  category: '美妝保養',
  ciVersion: 'v1.0',
  palette: { primary: '#B8A5D6', secondary: '#F9F4E8', accent: '#C9A96E', ink: '#3A3335' },
  fonts: { headline: 'Noto Serif TC', body: 'Noto Sans TC' },
  visualStyle: 'warm minimal product photography, natural linen texture, soft morning light',
  defaultTone: 'science',
  rules: { maxDeltaE: 5, minWhitespace: 0.3, productRatio: [0.3, 0.5] },
  bannedWords: ['根治', '治療', '保證有效'],
  replacements: { 根治: '', 治療: '', 保證有效: '' },
  claimWords: ['修護', '改善'],
  disclaimerPhrase: '效果因個人膚況而異',
  guidelineChunks: [],
  caseStudies: [],
  copyPresets: {
    gentle: { headline: ['溫柔呵護', '每一天'], subhead: '天然成分・溫和配方' },
    science: { headline: ['科學配方', '看得見的改變'], subhead: '專利成分・臨床測試' },
    playful: { headline: ['今天也要', '閃閃發光！'], subhead: '限時優惠，手刀搶購' },
    minimal: { headline: ['簡單', '就是美'], subhead: '純粹成分・無多餘添加' },
  },
  logo: null,
};
const KAYLA_SERUM: Product = {
  id: 'prod_my_brand_serum', brandId: 'my-brand-01', name: '薰衣草舒緩精華 30ml',
  features: ['溫和配方', '天然成分', '保濕鎖水', '敏感肌適用'],
  price: { sale: 980, original: 1280 }, photo: { source: 'sample', art: 'serum' },
  cutout: null, createdAt: '2026-10-01T09:00:00.000Z',
};
const SERUM = SAMPLE_PRODUCTS.find((p) => p.brandId === 'selune')!;
const CASES = [
  { brand: SELUNE, product: SERUM },
  { brand: MISTY_ISLE, product: SAMPLE_PRODUCTS.find((p) => p.brandId === 'misty-isle')! },
  { brand: KAYLA, product: KAYLA_SERUM },
];

const NO_IMAGES: PosterImages = { product: null, logo: null };
/** 一張海報約 0.1–0.6 秒（PNG 編碼佔大半），測試同時執行時會更慢 */
const SLOW = 20_000;

/** 與 mock 劇本相同的候選：程式產生的背景，配色取自 spec */
const renderOf = (spec: PromptSpec, brand: Brand): Render => ({
  id: `${spec.jobId}_r${spec.round}_${spec.templateId}_v0`, jobId: spec.jobId, round: spec.round, templateId: spec.templateId,
  variant: 0, background: { kind: 'procedural', seed: seedOf(spec), palette: spec.palette, style: brand.id },
  spec, score: null, passed: null, checks: [],
});

/** PNG 的尺寸（IHDR），順便確認檔頭 */
function pngSize(png: Buffer): { width: number; height: number } {
  expect([...png.subarray(0, 8)]).toEqual([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  return { width: png.readUInt32BE(16), height: png.readUInt32BE(20) };
}

/** 解碼 PNG，回傳讀取某個像素 RGB 的函式 */
async function pixelsOf(png: Buffer): Promise<(x: number, y: number) => number[]> {
  const img = await loadImage(png);
  const ctx = createCanvas(img.width, img.height).getContext('2d');
  ctx.drawImage(img, 0, 0);
  const { data, width } = ctx.getImageData(0, 0, img.width, img.height);
  return (x, y) => {
    const i = (Math.floor(y) * width + Math.floor(x)) * 4;
    return [data[i], data[i + 1], data[i + 2]];
  };
}

/** 單色 PNG 的 base64 */
async function solidPng(width: number, height: number, color: string): Promise<string> {
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, width, height);
  return (await canvas.encode('png')).toString('base64');
}

const colorDelta = (brand: Brand, spec: PromptSpec, { measured }: RenderedPoster): ReviewCheck =>
  runRuleChecks({ brand, spec, measuredPrimary: measured.hex }).find((c) => c.id === 'color_delta')!;

describe('renderPoster input errors', () => {
  const spec = cleanSpec();
  const upload: Product = { ...SERUM, photo: { source: 'upload', url: '/files/products/serum.png' } };

  it('requires the uploaded product image and a valid blend', async () => {
    await expect(renderPoster({ render: renderOf(spec, SELUNE), product: upload, brand: SELUNE, images: NO_IMAGES }))
      .rejects.toThrow('缺少商品圖（images.product，base64）');
    const images = { product: { base64: await solidPng(4, 4, '#ffffff'), blend: 'screen' }, logo: null } as unknown as PosterImages;
    await expect(renderPoster({ render: renderOf(spec, SELUNE), product: upload, brand: SELUNE, images }))
      .rejects.toThrow('images.product.blend 必須是 normal 或 multiply："screen"');
  });

  it('names the image that cannot be decoded', async () => {
    const images: PosterImages = { product: { base64: Buffer.from('不是圖片').toString('base64'), blend: 'normal' }, logo: null };
    await expect(renderPoster({ render: renderOf(spec, SELUNE), product: upload, brand: SELUNE, images }))
      .rejects.toThrow(/^商品圖無法解碼：/);
  });

  it('requires the background image of a url background', async () => {
    const render: Render = { ...renderOf(spec, SELUNE), background: { kind: 'url', url: '/files/bg.png', includesProduct: false } };
    await expect(renderPoster({ render, product: SERUM, brand: SELUNE, images: NO_IMAGES }))
      .rejects.toThrow('缺少背景圖（images.background，base64）');
  });
});

describe.skipIf(MISSING.length > 0)(`renderPoster with the poster fonts（沒有字型時略過：${FONTS_HINT}）`, () => {
  beforeAll(() => {
    registerPosterFonts(FONTS_DIR);
  });

  // 設計規格 §7：3 個品牌 × 5 個模板，正確配色全部通過、偏色全部不通過
  describe.each(CASES)('$brand.id', ({ brand, product }) => {
    it.each(TEMPLATE_IDS)('%s: native size, the clean spec passes color_delta, the flawed one fails with its wrong colour', async (id: TemplateId) => {
      const clean = cleanSpec(brand, product, id);
      const flawed = applyFlaws(clean, FLAWS, brand);
      const ok = await renderPoster({ render: renderOf(clean, brand), product, brand, images: NO_IMAGES });
      const bad = await renderPoster({ render: renderOf(flawed, brand), product, brand, images: NO_IMAGES });
      const { width, height } = getTemplate(id);
      expect(pngSize(ok.png)).toEqual({ width, height });
      expect(pngSize(bad.png)).toEqual({ width, height });

      expect(ok.measured.hex).not.toBeNull();
      expect(ok.measured.deltaE).toBeLessThanOrEqual(brand.rules.maxDeltaE);
      expect(colorDelta(brand, clean, ok).status).toBe('pass');

      expect(bad.measured.deltaE).toBeGreaterThan(brand.rules.maxDeltaE);
      expect(colorDelta(brand, flawed, bad).status).toBe('fail');
      // 說明文字顯示實際用錯的顏色：量到的是偏色 spec 的主色
      expect(deltaEHex(bad.measured.hex!, flawed.palette.primary)).toBeLessThanOrEqual(brand.rules.maxDeltaE);
    }, SLOW);
  });

  it('draws the uploaded product, the logo file and a url background from base64', async () => {
    const brand: Brand = { ...SELUNE, logo: { url: '/files/brands/selune/logo.svg' } };
    const upload: Product = {
      ...SERUM, photo: { source: 'upload', url: '/files/products/serum.jpg' },
      cutout: { model: 'birefnet', status: 'done', url: '/files/products/serum.png', error: null },
    };
    const spec = cleanSpec(SELUNE, SERUM, 'ig-post');
    const render: Render = { ...renderOf(spec, brand), background: { kind: 'url', url: '/files/bg.png', includesProduct: false } };
    const logoSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="100"><rect width="300" height="100" fill="#ff0000"/></svg>';
    const images = async (blend: 'normal' | 'multiply'): Promise<PosterImages> => ({
      product: { base64: await solidPng(100, 100, '#00ff00'), blend },
      logo: { base64: Buffer.from(logoSvg).toString('base64') },
      background: { base64: await solidPng(64, 64, '#0000ff') },
    });

    const B = boxMap(spec.layout);
    // 100×100 的商品圖等比縮放進商品框、底部對齊；量中心點
    const side = Math.min(B.product.w, B.product.h);
    const productCentre = [B.product.x + B.product.w / 2, B.product.y + B.product.h - side / 2] as const;
    const logo = fitLogoImage(B.logo, 300, 100);

    const normal = await renderPoster({ render, product: upload, brand, images: await images('normal') });
    const px = await pixelsOf(normal.png);
    expect(px(2, 2)).toEqual([0, 0, 255]);
    expect(px(...productCentre)).toEqual([0, 255, 0]);
    expect(px(logo.x + logo.w / 2, logo.y + logo.h / 2)).toEqual([255, 0, 0]);
    expect(colorDelta(brand, spec, normal).status).toBe('pass');

    // 色彩增值：綠 × 藍 = 黑
    const multiply = await renderPoster({ render, product: upload, brand, images: await images('multiply') });
    expect((await pixelsOf(multiply.png))(...productCentre)).toEqual([0, 0, 0]);
  }, SLOW);

  it('draws the vector logo when the brand has a logo file but none was sent', async () => {
    const brand: Brand = { ...SELUNE, logo: { url: '/files/brands/selune/logo.svg' } };
    const spec = cleanSpec();
    const out = await renderPoster({ render: renderOf(spec, brand), product: SERUM, brand, images: NO_IMAGES });
    expect(pngSize(out.png)).toEqual({ width: spec.canvas.width, height: spec.canvas.height });
  });
});

describe.skipIf(MISSING.length > 0)(`POST /render（沒有字型時略過：${FONTS_HINT}）`, () => {
  const server = createComposerServer({ fonts: ['Noto Sans TC', 'Noto Serif TC'] });
  let base = '';
  beforeAll(async () => {
    registerPosterFonts(FONTS_DIR);
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
    base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  });
  afterAll(() => new Promise<void>((resolve) => server.close(() => resolve())));

  const post = (path: string, body: unknown) =>
    fetch(`${base}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

  it('returns the PNG with the measured primary and its share, which /review accepts', async () => {
    const spec = cleanSpec(SELUNE, SERUM, 'story');
    const input = { render: renderOf(spec, SELUNE), product: SERUM, brand: SELUNE, images: NO_IMAGES };
    const res = await post('/render', input);
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toBe('image/png');
    const png = Buffer.from(await res.arrayBuffer());
    expect(pngSize(png)).toEqual({ width: getTemplate('story').width, height: getTemplate('story').height });

    const { measured } = await renderPoster(input);
    const primary = res.headers.get('x-measured-primary');
    expect(primary).toBe(measured.hex);
    expect(Number(res.headers.get('x-primary-share'))).toBeCloseTo(measured.share, 4);

    const review = await post('/review', { spec, brand: SELUNE, measuredPrimary: primary });
    const body = (await review.json()) as { checks: ReviewCheck[]; score: number; passed: boolean };
    expect(body.checks.find((c) => c.id === 'color_delta')!.status).toBe('pass');
    expect(body).toMatchObject({ score: 100, passed: true });
  }, SLOW);

  it('sends an empty X-Measured-Primary when the poster has no colour to measure', async () => {
    // 全部改成灰階：範圍內沒有彩色，量不到主色
    const spec: PromptSpec = { ...cleanSpec(), palette: { primary: '#777777', secondary: '#EEEEEE', accent: '#999999', ink: '#222222' } };
    const res = await post('/render', { render: renderOf(spec, SELUNE), product: null, brand: SELUNE, images: NO_IMAGES });
    expect(res.status).toBe(200);
    expect(res.headers.get('x-measured-primary')).toBe('');
    expect(res.headers.get('x-primary-share')).toBe('0');
  });

  it('answers 400 with a Chinese message when an image is missing', async () => {
    const upload: Product = { ...SERUM, photo: { source: 'upload', url: '/files/products/serum.png' } };
    const res = await post('/render', { render: renderOf(cleanSpec(), SELUNE), product: upload, brand: SELUNE, images: NO_IMAGES });
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: { code: 'invalid', message: '缺少商品圖（images.product，base64）' } });
  });
});
```

- [ ] **Step 2: 建立 `web/composer/server.test.ts`（先寫測試）**

```ts
import { spawn, type ChildProcess } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, afterEach, describe, expect, it } from 'vitest';
import { FONTS_HINT, missingPosterFonts, resolveFontsDir } from './fonts';

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const MISSING = missingPosterFonts(resolveFontsDir());

const children: ChildProcess[] = [];
afterEach(() => {
  for (const child of children.splice(0)) child.kill();
});

/** 以 npm run composer 相同的方式啟動伺服器（隨機埠） */
function startComposer(env: Record<string, string>) {
  const child = spawn(process.execPath, ['--import', 'tsx', 'composer/server.ts'], {
    cwd: WEB, env: { ...process.env, PORT: '0', ...env }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  children.push(child);
  let stdout = '';
  let stderr = '';
  child.stdout!.on('data', (d: Buffer) => (stdout += d.toString('utf8')));
  child.stderr!.on('data', (d: Buffer) => (stderr += d.toString('utf8')));
  const exited = new Promise<number | null>((resolve) => child.once('exit', (code) => resolve(code)));
  const listening = new Promise<string>((resolve, reject) => {
    child.stdout!.on('data', () => {
      const url = /composer listening on (http:\/\/\S+?:\d+)/.exec(stdout)?.[1];
      if (url) resolve(url);
    });
    void exited.then((code) => reject(new Error(`composer 結束（代碼 ${code}）：${stderr}`)));
  });
  return { exited, listening, output: () => ({ stdout, stderr }) };
}

describe('composer server start-up', () => {
  const empty = mkdtempSync(path.join(tmpdir(), 'poster-fonts-empty-'));
  afterAll(() => rmSync(empty, { recursive: true, force: true }));

  it('exits with code 1 and the npm run fonts hint when the fonts are missing', async () => {
    const composer = startComposer({ POSTER_FONTS_DIR: empty });
    composer.listening.catch(() => undefined);
    expect(await composer.exited).toBe(1);
    const { stdout, stderr } = composer.output();
    expect(stdout).not.toContain('listening');
    expect(stderr).toContain('composer 無法啟動：找不到字型檔：');
    expect(stderr).toContain(FONTS_HINT);
  }, 30_000);

  it.skipIf(MISSING.length > 0)(`registers the fonts before listening and reports them on /health（沒有字型時略過：${FONTS_HINT}）`, async () => {
    const composer = startComposer({});
    const url = await composer.listening;
    expect(composer.output().stdout).toContain('字型：Noto Sans TC、Noto Serif TC');
    const health = await fetch(`${url}/health`);
    expect(await health.json()).toEqual({ status: 'ok', fonts: ['Noto Sans TC', 'Noto Serif TC'] });
  }, 30_000);
});
```

- [ ] **Step 3: 建立 `web/composer/dockerfile.test.ts`（先寫測試）**

確認 Dockerfile 下載的網址、SHA-256 與 `fonts.lock.json` 完全一致。

```ts
// web/Dockerfile 的字型階段必須和 fonts.lock.json 一致：本機（npm run fonts）與 Docker 下載同一份檔案。
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import lock from './fonts.lock.json';

const DOCKERFILE = readFileSync(new URL('../Dockerfile', import.meta.url), 'utf8');

/** Dockerfile 的指令：合併以反斜線續行的行，去掉註解與空行 */
function instructions(text: string): string[] {
  return text
    .replace(/\\\r?\n/g, ' ')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#'))
    .map((line) => line.replace(/\s+/g, ' '));
}

/** 各階段（FROM … AS name）的指令 */
function stages(text: string): Map<string, string[]> {
  const result = new Map<string, string[]>();
  let current: string[] = [];
  for (const line of instructions(text)) {
    const from = /^FROM \S+ AS (\S+)$/i.exec(line);
    if (from) result.set(from[1], (current = []));
    else current.push(line);
  }
  return result;
}

const STAGES = stages(DOCKERFILE);
const FONTS_STAGE = STAGES.get('fonts') ?? [];
const COMPOSER_STAGE = STAGES.get('composer') ?? [];
const FONTS_DIR = '/usr/local/share/poster-fonts';

describe('web/Dockerfile fonts stage', () => {
  it('starts from scratch', () => {
    expect(DOCKERFILE).toMatch(/^FROM scratch AS fonts$/m);
  });

  it('downloads exactly the files in fonts.lock.json, with the same URLs and SHA-256', () => {
    const adds = FONTS_STAGE.map((line) => {
      const m = /^ADD --checksum=sha256:([0-9a-f]{64}) "([^"]+)" \/([^/\s]+)$/.exec(line);
      expect(m, `無法解析的指令：${line}`).not.toBeNull();
      const [, sha256, url, file] = m!;
      return { file, url, sha256 };
    });
    expect(adds).toEqual(lock.files.map(({ file, url, sha256 }) => ({ file, url, sha256 })));
  });
});

describe('web/Dockerfile composer stage', () => {
  it('creates the fonts dir, copies every locked file into it as 0644 and points POSTER_FONTS_DIR at it', () => {
    const mkdir = COMPOSER_STAGE.indexOf(`RUN mkdir -p ${FONTS_DIR}`);
    const copy = COMPOSER_STAGE.findIndex((line) => line.startsWith('COPY --chmod=0644 --from=fonts '));
    expect(mkdir).toBeGreaterThanOrEqual(0);
    expect(copy).toBeGreaterThan(mkdir);

    const [, , , ...args] = COMPOSER_STAGE[copy].split(' ');
    expect(args.at(-1)).toBe(`${FONTS_DIR}/`);
    expect(args.slice(0, -1)).toEqual(lock.files.map((f) => `/${f.file}`));
    expect(COMPOSER_STAGE).toContain(`ENV POSTER_FONTS_DIR=${FONTS_DIR}`);
  });
});
```

- [ ] **Step 4: 確認測試失敗**

Run（在 `web/`）：`npx vitest run composer/poster.test.ts composer/server.test.ts composer/dockerfile.test.ts`
Expected：3 個測試檔失敗（5 failed）：`poster.test.ts` 找不到 `./poster`；`dockerfile.test.ts` 找不到字型階段；`server.test.ts` 啟動時沒有註冊字型（沒有字型時也不會以結束代碼 1 結束）。

- [ ] **Step 5: 建立 `web/composer/poster.ts`**

```ts
// composer 在伺服器端繪製審查用海報：流程與瀏覽器的 render.ts（preparePoster → paintPoster）相同，
// 版面與繪製直接沿用 scene.ts 與 paint.ts，只把載圖與 Canvas 換成 @napi-rs/canvas。
import { createCanvas, loadImage, type Image, type SKRSContext2D } from '@napi-rs/canvas';
import type { Brand, Product, Render } from '@/types/contract';
import { backgroundSvg } from '@/lib/compose/art';
import { fontStacks, productImage } from '@/lib/compose/assets';
import { boxMap } from '@/lib/compose/layout';
import { paintScene, type PaintAssets } from '@/lib/compose/paint';
import { composePoster } from '@/lib/compose/scene';
import { measurePrimary, type MeasuredPrimary } from '@/lib/review/measure';

/** worker 讀好的圖檔（base64）。composer 不讀任何資料夾 */
export interface PosterImages {
  /** 上傳商品的去背圖或原圖，blend 規則與前端 productImage 相同；示範商品（向量素材）與沒有商品時為 null */
  product: { base64: string; blend: 'normal' | 'multiply' } | null;
  /** 品牌的 Logo 圖檔；null 時畫向量標誌與字標（與前端相同） */
  logo: { base64: string } | null;
  /** 背景為 url 時的圖檔；程式產生的背景（procedural）不需要 */
  background?: { base64: string } | null;
}

export interface RenderPosterInput {
  render: Render;
  /** 商品已刪除時為 null（只畫背景與文字） */
  product: Product | null;
  brand: Brand;
  images: PosterImages;
}

export interface RenderedPoster {
  /** 模板原始尺寸的 PNG */
  png: Buffer;
  /** 從繪製結果量到的品牌主色（measurePrimary，門檻為 brand.rules.maxDeltaE） */
  measured: MeasuredPrimary;
}

/*
 * paint.ts 以 DOM 的型別撰寫，瀏覽器與 composer 共用同一份繪圖程式。@napi-rs/canvas 的 context 與 Image 在執行期
 * 提供 paint.ts 用到的所有 API（drawImage、fillText、measureText、letterSpacing、filter、shadowBlur、roundRect、
 * globalCompositeOperation…），但型別宣告是它自己的一套（例如 drawImage 只接受它的 Image），TypeScript 不認得兩者相容。
 * 只在這兩個函式轉型；poster.test.ts 實際畫出全部模板，驗證繪製結果。
 */
const domContext = (ctx: SKRSContext2D) => ctx as unknown as CanvasRenderingContext2D;
const domImage = (image: Image) => image as unknown as CanvasImageSource;

async function decode(label: string, data: Buffer): Promise<Image> {
  try {
    return await loadImage(data);
  } catch (err) {
    throw new Error(`${label}無法解碼：${err instanceof Error ? err.message : String(err)}`);
  }
}

const MISSING = (label: string, field: string) => `缺少${label}（${field}，base64）`;

function fromBase64(label: string, field: string, image: { base64: string } | null | undefined): Promise<Image> {
  if (typeof image?.base64 !== 'string' || image.base64 === '') return Promise.reject(new Error(MISSING(label, field)));
  return decode(label, Buffer.from(image.base64, 'base64'));
}

/** SVG 的 data URL（svgDataUrl 產生的 `data:image/svg+xml;charset=utf-8,…`）轉成 Buffer，交給 loadImage */
const svgBuffer = (dataUrl: string) => Buffer.from(decodeURIComponent(dataUrl.slice(dataUrl.indexOf(',') + 1)), 'utf8');

/** 示範商品依 productImage 產生 SVG；上傳商品用 worker 傳來的圖檔與 blend */
async function loadProduct(
  product: Product | null, brand: Brand, upload: PosterImages['product'] | undefined,
): Promise<{ image: Image; blend: 'normal' | 'multiply' } | null> {
  if (!product) return null;
  if (product.photo.source === 'sample') {
    const { src, blend } = productImage(product, brand);
    return { image: await decode('商品圖', svgBuffer(src)), blend };
  }
  if (!upload) throw new Error(MISSING('商品圖', 'images.product'));
  if (upload.blend !== 'normal' && upload.blend !== 'multiply') {
    throw new Error(`images.product.blend 必須是 normal 或 multiply：${JSON.stringify(upload.blend)}`);
  }
  return { image: await fromBase64('商品圖', 'images.product', upload), blend: upload.blend };
}

async function loadAssets({ render, product, brand, images = { product: null, logo: null } }: RenderPosterInput): Promise<PaintAssets> {
  const spec = render.spec;
  const bg = render.background;
  const [background, prod, logo] = await Promise.all([
    bg.kind === 'procedural'
      ? decode('背景圖', Buffer.from(backgroundSvg({
        width: spec.canvas.width, height: spec.canvas.height, palette: bg.palette, seed: bg.seed, style: bg.style,
        focus: boxMap(spec.layout).product,
      }), 'utf8'))
      : fromBase64('背景圖', 'images.background', images.background),
    loadProduct(product, brand, images.product),
    // 與前端相同：品牌有 Logo 圖檔才使用，否則畫向量標誌與字標
    brand.logo && images.logo ? fromBase64('Logo 圖檔', 'images.logo', images.logo) : null,
  ]);
  return {
    background: domImage(background),
    // 沒有固有尺寸的圖以前端相同的預設尺寸計算
    product: prod
      ? { image: domImage(prod.image), width: prod.image.naturalWidth || 500, height: prod.image.naturalHeight || 800, blend: prod.blend }
      : null,
    logo: logo ? { image: domImage(logo), width: logo.naturalWidth || 300, height: logo.naturalHeight || 100 } : null,
    fonts: fontStacks(brand),
  };
}

/**
 * 以模板原始尺寸繪製海報（spec 的文案、版面與配色），量出品牌主色，輸出 PNG。
 * 字型要先以 registerPosterFonts 註冊；圖檔缺少或無法解碼時丟出中文錯誤。
 */
export async function renderPoster(input: RenderPosterInput): Promise<RenderedPoster> {
  const { render, brand } = input;
  const spec = render.spec;
  const scene = composePoster({ canvas: spec.canvas, layout: spec.layout, palette: spec.palette, copy: spec.copy, brand });
  const assets = await loadAssets(input);

  const width = Math.round(scene.width);
  const height = Math.round(scene.height);
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');
  paintScene(domContext(ctx), scene, assets);

  const pixels = ctx.getImageData(0, 0, width, height).data;
  const measured = measurePrimary(pixels, width, height, spec.layout, brand.palette.primary, brand.rules.maxDeltaE);
  return { png: await canvas.encode('png'), measured };
}
```

- [ ] **Step 6: 修改 `web/composer/handlers.ts`**

找到（1／2）：

```ts
import { getTemplate } from '@/lib/compose/templates';
import { runRuleChecks, scoreChecks } from '@/lib/review/rules';
import { contentVlmChecks } from '@/lib/review/vlm';

/** 找不到路徑（伺服器回 404） */
export class UnknownRoute extends Error {}
```

改成：

```ts
import { getTemplate } from '@/lib/compose/templates';
import { runRuleChecks, scoreChecks } from '@/lib/review/rules';
import { contentVlmChecks } from '@/lib/review/vlm';
import { renderPoster, type RenderPosterInput } from './poster';

/** 找不到路徑（伺服器回 404） */
export class UnknownRoute extends Error {}
```

找到（2／2）：

```ts
}

/**
 * 後端呼叫的 TypeScript 邏輯：版型、live 模式的審查，以及模擬模式沿用的 mock 行為（/sim/*）。
 * 輸入與輸出都是合約的 JSON。
 */
const HANDLERS: Record<string, Handler> = {
  '/layout': ({ templateId }: { templateId: TemplateId }) => computeLayout(getTemplate(templateId)),

  '/review': reviewPoster,
```

改成：

```ts
}

/**
 * 後端呼叫的 TypeScript 邏輯：版型、live 模式的繪製與審查，以及模擬模式沿用的 mock 行為（/sim/*）。
 * 輸入與輸出都是合約的 JSON。
 */
const HANDLERS: Record<string, Handler> = {
  '/layout': ({ templateId }: { templateId: TemplateId }) => computeLayout(getTemplate(templateId)),

  /** 審查用海報：PNG，標頭帶量到的主色（量不到時為空字串）與它的佔比（0–1） */
  '/render': async (input: RenderPosterInput) => {
    const { png, measured } = await renderPoster(input);
    return new BinaryResponse(png, 'image/png', {
      'X-Measured-Primary': measured.hex ?? '',
      'X-Primary-Share': String(Number(measured.share.toFixed(4))),
    });
  },

  '/review': reviewPoster,
```

- [ ] **Step 7: 修改 `web/composer/server.ts`**

找到：

```ts
// composer：npm run composer（預設 3900 埠，可用 PORT 變更）
import { createComposerServer } from './app';

const port = Number(process.env.PORT ?? 3900);
const host = process.env.HOST ?? '127.0.0.1';
const server = createComposerServer();
server.listen(port, host, () => console.log(`composer listening on http://${host}:${port}`));

/**
 * 在容器裡 node 是 PID 1，SIGTERM 沒有預設動作，不處理的話 docker stop 要等到逾時再 SIGKILL（結束代碼 137）。
 * 收到訊號就關閉伺服器並以 0 結束；還有連線沒關的話，3 秒後照樣結束。
 */
function shutdown() {
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 3_000).unref();
}
process.once('SIGTERM', shutdown);
process.once('SIGINT', shutdown);
```

改成：

```ts
// composer：npm run composer（預設 3900 埠，可用 PORT 變更；字型資料夾可用 POSTER_FONTS_DIR 變更）
import type { AddressInfo } from 'node:net';
import { createComposerServer } from './app';
import { registerPosterFonts, resolveFontsDir } from './fonts';

function main() {
  // 啟動時就註冊海報字型；缺少或無法註冊時印出原因並以代碼 1 結束，不帶著畫不出正確海報的狀態啟動。
  // 不呼叫 process.exit：POSIX 上寫到 pipe 是非同步的，直接結束可能來不及寫出錯誤訊息。
  let fonts: string[];
  try {
    fonts = registerPosterFonts(resolveFontsDir()).map((f) => f.family);
  } catch (err) {
    console.error(`composer 無法啟動：${err instanceof Error ? err.message : String(err)}`);
    process.exitCode = 1;
    return;
  }

  const port = Number(process.env.PORT ?? 3900);
  const host = process.env.HOST ?? '127.0.0.1';
  const server = createComposerServer({ fonts });
  server.listen(port, host, () => {
    const { port: actual } = server.address() as AddressInfo;
    console.log(`composer listening on http://${host}:${actual}（字型：${fonts.join('、')}）`);
  });

  /**
   * 在容器裡 node 是 PID 1，SIGTERM 沒有預設動作，不處理的話 docker stop 要等到逾時再 SIGKILL（結束代碼 137）。
   * 收到訊號就關閉伺服器並以 0 結束；還有連線沒關的話，3 秒後照樣結束。
   */
  function shutdown() {
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 3_000).unref();
  }
  process.once('SIGTERM', shutdown);
  process.once('SIGINT', shutdown);
}

main();
```

- [ ] **Step 8: 修改 `web/Dockerfile`**

`ADD <網址>` 下載的檔案權限是 0600；`COPY --chmod` 複製到不存在的資料夾時，會把資料夾設成無法進入。所以要先 `mkdir -p`，再 `COPY --chmod=0644`。

找到（1／2）：

```dockerfile
# 兩個映像檔：
# - web：nginx 提供 live 版的靜態輸出，並把 /api、/files、/ws、/docs 轉給 api
# - composer：Node 服務，直接執行 src/lib 的 TypeScript（版型與模擬邏輯）
FROM public.ecr.aws/docker/library/node:24-alpine AS source
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app/web
```

改成：

```dockerfile
# 兩個映像檔：
# - web：nginx 提供 live 版的靜態輸出，並把 /api、/files、/ws、/docs 轉給 api
# - composer：Node 服務，直接執行 src/lib 的 TypeScript（版型、伺服器端繪圖、審查與模擬邏輯）
FROM public.ecr.aws/docker/library/node:24-alpine AS source
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app/web
```

找到（2／2）：

```dockerfile
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/web/out /usr/share/nginx/html

FROM source AS composer
ENV HOST=0.0.0.0 PORT=3900
EXPOSE 3900
CMD ["node", "--import", "tsx", "composer/server.ts"]
```

改成：

```dockerfile
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/web/out /usr/share/nginx/html

# 海報字型與授權文字：網址與 SHA-256 必須和 composer/fonts.lock.json 相同（composer/dockerfile.test.ts 會檢查）。
# 下載內容與 checksum 不符時建置失敗；只有建置 composer 時才會下載。
FROM scratch AS fonts
ADD --checksum=sha256:864727d210d54f2537bbe23b3a839436c3992af72de9322af5270897246bd44f \
    "https://raw.githubusercontent.com/google/fonts/45e3d5269e4a17d823f6d84470bc084dc5ae46f6/ofl/notosanstc/NotoSansTC%5Bwght%5D.ttf" \
    /NotoSansTC-VF.ttf
ADD --checksum=sha256:0077e18f57c6908f4a000969880940bdb0dad057c0e8d98b49dc364c3d1b09c6 \
    "https://raw.githubusercontent.com/google/fonts/45e3d5269e4a17d823f6d84470bc084dc5ae46f6/ofl/notoseriftc/NotoSerifTC%5Bwght%5D.ttf" \
    /NotoSerifTC-VF.ttf
ADD --checksum=sha256:1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9 \
    "https://raw.githubusercontent.com/google/fonts/45e3d5269e4a17d823f6d84470bc084dc5ae46f6/ofl/notosanstc/OFL.txt" \
    /OFL-NotoSansTC.txt
ADD --checksum=sha256:5e0da210fb04058a8c0087985d2d456b931c2579811a49655721d3cf0c36b6d6 \
    "https://raw.githubusercontent.com/google/fonts/45e3d5269e4a17d823f6d84470bc084dc5ae46f6/ofl/notoseriftc/OFL.txt" \
    /OFL-NotoSerifTC.txt

FROM source AS composer
# ADD 下載的檔案權限是 0600：先建立資料夾（0755），再以 0644 複製檔案，任何使用者都讀得到。
# 不先建立資料夾的話，--chmod 也會套用到 COPY 自動建立的資料夾，變成無法進入。授權文字（OFL）和字型放在一起。
RUN mkdir -p /usr/local/share/poster-fonts
COPY --chmod=0644 --from=fonts \
    /NotoSansTC-VF.ttf /NotoSerifTC-VF.ttf /OFL-NotoSansTC.txt /OFL-NotoSerifTC.txt \
    /usr/local/share/poster-fonts/
ENV POSTER_FONTS_DIR=/usr/local/share/poster-fonts
ENV HOST=0.0.0.0 PORT=3900
EXPOSE 3900
CMD ["node", "--import", "tsx", "composer/server.ts"]
```

- [ ] **Step 9: 修改 `backend/tests/conftest.py`**

找到（1／2）：

```python

@pytest.fixture(scope='session')
def composer_url() -> Iterator[str]:
    """在 3902 埠啟動 composer（需要 web/ 已 npm install）。"""
    port = 3902
    url = f'http://127.0.0.1:{port}'
    proc = subprocess.Popen(
```

改成：

```python

@pytest.fixture(scope='session')
def composer_url() -> Iterator[str]:
    """在 3902 埠啟動 composer（需要 web/ 已 npm install 與 npm run fonts；字型資料夾沿用 POSTER_FONTS_DIR）。"""
    port = 3902
    url = f'http://127.0.0.1:{port}'
    proc = subprocess.Popen(
```

找到（2／2）：

```python
                if httpx.get(f'{url}/health').status_code == 200:
                    break
            except httpx.HTTPError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)
```

改成：

```python
                if httpx.get(f'{url}/health').status_code == 200:
                    break
            except httpx.HTTPError:
                # composer 啟動時就註冊字型，缺少字型會直接結束；不必等到逾時
                if proc.poll() is not None:
                    raise RuntimeError(
                        f'composer 啟動失敗（結束代碼 {proc.returncode}）；缺少字型時請在 web/ 執行 npm run fonts'
                    ) from None
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)
```

- [ ] **Step 10: 確認全部通過**

Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint`
Expected：51 個測試檔、422 個測試通過；沒有錯誤。

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected：沒有錯誤；259 passed、3 skipped（沒有模型檔時略過真模型測試）。

- [ ] **Step 11: 確認 Docker 映像檔可以啟動 composer**

使用獨立的映像檔名稱，不經過 docker compose。在 repo 根目錄執行：

```bash
docker build -f web/Dockerfile --target composer -t plan6a-composer-check web
docker run --rm -d -p 127.0.0.1:3920:3900 --name plan6a-composer-check plan6a-composer-check
curl -s http://127.0.0.1:3920/health
docker stop plan6a-composer-check
docker rmi plan6a-composer-check
```

Expected：`/health` 回傳 `{"status":"ok","fonts":["Noto Sans TC","Noto Serif TC"]}`；結束後容器與映像檔都已移除。

- [ ] **Step 12: Commit**

```bash
git add \
  backend/tests/conftest.py \
  web/Dockerfile \
  web/composer/dockerfile.test.ts \
  web/composer/handlers.ts \
  web/composer/poster.test.ts \
  web/composer/poster.ts \
  web/composer/server.test.ts \
  web/composer/server.ts
git commit -m "feat: render the review poster on the server and add /render" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6：`review.completed` 加上審查用海報的網址

**Files:**
- Modify:
  - 後端：`backend/app/contract.py`、`backend/app/pipeline/runner.py`
  - 前端：`web/src/types/contract.ts`、`web/src/lib/api/mock/scenario.ts`、`web/src/lib/jobs/view.ts`、`web/src/components/queue/queue-list.tsx`、`web/src/components/studio/copy-editor.tsx`
  - fixture（由 `npm run fixtures` 產生）：`contracts/fixtures/stats.json`、`contracts/fixtures/timelines/*.json`
- Test: `web/src/lib/api/mock/scenario.test.ts`、`web/src/lib/jobs/view.test.ts`

**Interfaces:**
- Produces：
  - Python 的 `ReviewCompletedEvent.image: str | None`（必填，沒有預設值）。
  - TS 的 `{ type: 'review.completed'; round; renderId; score; passed; image: string | null }`。
  - 模擬版與 mock 一律為 `null`。
  - `web/src/lib/jobs/view.ts`：
    - `interface Candidate extends Render { reviewImage: string | null }`；
    - `JobView.renders: Record<string, Candidate>`；
    - `finalCandidates(v)` 回傳 `Candidate`。

- [ ] **Step 1: 修改 `web/src/lib/jobs/view.test.ts`（先寫測試）**

找到：

```ts
      expect(v.renders[id].score).not.toBeNull();
    }
    expect(v.specs[specKey(2, 'story')].round).toBe(2);
  });

  it('shows only the final round as candidates and selects the best render', () => {
```

改成：

```ts
      expect(v.renders[id].score).not.toBeNull();
    }
    expect(v.specs[specKey(2, 'story')].round).toBe(2);
  });

  it('stores the review poster of review.completed on the candidate', () => {
    // mock 與模擬模式沒有審查用海報
    expect(v.renderIds.every((id) => v.renders[id].reviewImage === null)).toBe(true);
    const id = v.renderIds[0];
    const image = `/files/jobs/job_v/${id}.png`;
    const next = reduceJob(v, { type: 'review.completed', round: 1, renderId: id, score: 88, passed: true, image });
    expect(next.renders[id]).toMatchObject({ score: 88, passed: true, reviewImage: image });
    expect(v.renders[id].reviewImage).toBeNull();
    // 加上 image 欄位之前存下的事件沒有這個欄位
    const legacy = { type: 'review.completed', round: 1, renderId: id, score: 70, passed: false } as unknown as JobEvent;
    expect(reduceJob(next, legacy).renders[id]).toMatchObject({ score: 70, reviewImage: null });
  });

  it('shows only the final round as candidates and selects the best render', () => {
```

- [ ] **Step 2: 修改 `web/src/lib/api/mock/scenario.test.ts`（先寫測試）**

找到：

```ts
    const reviews = ofType(tl, 'review.completed');
    expect(reviews.filter((e) => e.round === 1).every((e) => !e.passed)).toBe(true);
    expect(reviews.filter((e) => e.round === 2).some((e) => e.passed)).toBe(true);
    expect(ofType(tl, 'rewrite.started')).toHaveLength(1);
    expect(ofType(tl, 'job.completed')).toHaveLength(1);
  });
```

改成：

```ts
    const reviews = ofType(tl, 'review.completed');
    expect(reviews.filter((e) => e.round === 1).every((e) => !e.passed)).toBe(true);
    expect(reviews.filter((e) => e.round === 2).some((e) => e.passed)).toBe(true);
    // mock 不在伺服器端繪製，沒有審查用海報
    expect(reviews.every((e) => e.image === null)).toBe(true);
    expect(ofType(tl, 'rewrite.started')).toHaveLength(1);
    expect(ofType(tl, 'job.completed')).toHaveLength(1);
  });
```

- [ ] **Step 3: 確認測試失敗**

Run（在 `web/`）：`npx vitest run src/lib/jobs/view.test.ts src/lib/api/mock/scenario.test.ts`
Expected：2 failed、28 passed：`stores the review poster of review.completed on the candidate`，以及 mock 劇本的 `review.completed` 沒有 `image`。

- [ ] **Step 4: 修改 `web/src/types/contract.ts`**

找到：

```ts
  | { type: 'render.progress'; round: number; node: RenderNode; step: number; maxStep: number }
  | { type: 'render.completed'; round: number; renders: Render[] }
  | { type: 'review.check'; round: number; renderId: string; check: ReviewCheck }
  | { type: 'review.completed'; round: number; renderId: string; score: number; passed: boolean }
  | { type: 'rewrite.started'; round: number; templateId: TemplateId; reasons: CheckId[]; fixes: Fix[]; requery: boolean }
  | { type: 'job.completed'; jobId: string; bestRenderIds: Partial<Record<TemplateId, string>> }
  | { type: 'job.needs_review'; jobId: string; reason: string }
```

改成：

```ts
  | { type: 'render.progress'; round: number; node: RenderNode; step: number; maxStep: number }
  | { type: 'render.completed'; round: number; renders: Render[] }
  | { type: 'review.check'; round: number; renderId: string; check: ReviewCheck }
  /** image：審查用海報的網址（/files/jobs/{jobId}/{renderId}.png）；模擬模式與 mock 沒有繪製，為 null */
  | { type: 'review.completed'; round: number; renderId: string; score: number; passed: boolean; image: string | null }
  | { type: 'rewrite.started'; round: number; templateId: TemplateId; reasons: CheckId[]; fixes: Fix[]; requery: boolean }
  | { type: 'job.completed'; jobId: string; bestRenderIds: Partial<Record<TemplateId, string>> }
  | { type: 'job.needs_review'; jobId: string; reason: string }
```

- [ ] **Step 5: 修改 `web/src/lib/api/mock/scenario.ts`**

找到：

```ts
    let k = 0;
    for (const { render, result } of results) {
      for (const check of result.checks) emit(t + ++k * dt, { type: 'review.check', round, renderId: render.id, check });
      emit(t + k * dt, { type: 'review.completed', round, renderId: render.id, score: result.score, passed: result.passed });
    }
    t += PHASE_MS.review;
```

改成：

```ts
    let k = 0;
    for (const { render, result } of results) {
      for (const check of result.checks) emit(t + ++k * dt, { type: 'review.check', round, renderId: render.id, check });
      emit(t + k * dt, {
        type: 'review.completed', round, renderId: render.id, score: result.score, passed: result.passed, image: null,
      });
    }
    t += PHASE_MS.review;
```

- [ ] **Step 6: 修改 `web/src/lib/jobs/view.ts`**

找到（1／6）：

```ts
export interface RewriteInfo { round: number; templateId: TemplateId; reasons: CheckId[]; fixes: Fix[]; requery: boolean }
export interface LogLine { source: LogSource; level: LogLevel; message: string }
export interface RenderProgress { round: number; node: RenderNode; step: number; maxStep: number }

/** 由事件串流累積出來的任務畫面狀態。mock 與 live 共用（UI 只看事件，不看實作）。 */
export interface JobView {
```

改成：

```ts
export interface RewriteInfo { round: number; templateId: TemplateId; reasons: CheckId[]; fixes: Fix[]; requery: boolean }
export interface LogLine { source: LogSource; level: LogLevel; message: string }
export interface RenderProgress { round: number; node: RenderNode; step: number; maxStep: number }

/**
 * 候選圖：合約的 Render 加上 review.completed 帶來的審查用海報網址。
 * 審查完成前、模擬模式與 mock 為 null（伺服器端沒有繪製）。
 */
export interface Candidate extends Render { reviewImage: string | null }

/** 由事件串流累積出來的任務畫面狀態。mock 與 live 共用（UI 只看事件，不看實作）。 */
export interface JobView {
```

找到（2／6）：

```ts
  requeryHits: RagHit[];
  /** key 為 specKey(round, templateId) */
  specs: Record<string, PromptSpec>;
  renders: Record<string, Render>;
  /** 依收到的順序 */
  renderIds: string[];
  progress: RenderProgress | null;
```

改成：

```ts
  requeryHits: RagHit[];
  /** key 為 specKey(round, templateId) */
  specs: Record<string, PromptSpec>;
  renders: Record<string, Candidate>;
  /** 依收到的順序 */
  renderIds: string[];
  progress: RenderProgress | null;
```

找到（3／6）：

```ts
      return { ...v, progress: { round: e.round, node: e.node, step: e.step, maxStep: e.maxStep } };
    case 'render.completed': {
      const renders = { ...v.renders };
      for (const r of e.renders) renders[r.id] = r;
      return { ...v, renders, renderIds: [...v.renderIds, ...e.renders.map((r) => r.id).filter((id) => !v.renders[id])] };
    }
    case 'review.check': {
```

改成：

```ts
      return { ...v, progress: { round: e.round, node: e.node, step: e.step, maxStep: e.maxStep } };
    case 'render.completed': {
      const renders = { ...v.renders };
      for (const r of e.renders) renders[r.id] = { ...r, reviewImage: null };
      return { ...v, renders, renderIds: [...v.renderIds, ...e.renders.map((r) => r.id).filter((id) => !v.renders[id])] };
    }
    case 'review.check': {
```

找到（4／6）：

```ts
    }
    case 'review.completed': {
      const r = v.renders[e.renderId];
      return r ? { ...v, renders: { ...v.renders, [r.id]: { ...r, score: e.score, passed: e.passed } } } : v;
    }
    case 'rewrite.started':
      return {
```

改成：

```ts
    }
    case 'review.completed': {
      const r = v.renders[e.renderId];
      // 加上 image 欄位之前存下的事件沒有這個欄位（undefined），視為沒有審查用海報
      const reviewImage = e.image ?? null;
      return r ? { ...v, renders: { ...v.renders, [r.id]: { ...r, score: e.score, passed: e.passed, reviewImage } } } : v;
    }
    case 'rewrite.started':
      return {
```

找到（5／6）：

```ts
  events.reduce(reduceJob, emptyJobView(jobId));

/** 每個模板最後一輪的候選（依 variant 排序）；結果牆只顯示這些 */
export function finalCandidates(v: JobView): Partial<Record<TemplateId, Render[]>> {
  const out: Partial<Record<TemplateId, Render[]>> = {};
  for (const id of v.renderIds) {
    const r = v.renders[id];
    const list = out[r.templateId];
```

改成：

```ts
  events.reduce(reduceJob, emptyJobView(jobId));

/** 每個模板最後一輪的候選（依 variant 排序）；結果牆只顯示這些 */
export function finalCandidates(v: JobView): Partial<Record<TemplateId, Candidate[]>> {
  const out: Partial<Record<TemplateId, Candidate[]>> = {};
  for (const id of v.renderIds) {
    const r = v.renders[id];
    const list = out[r.templateId];
```

找到（6／6）：

```ts
/** 預設選擇：任務的最佳候選優先；需人工審核時取最後一輪分數最高的 */
export function defaultSelection(v: JobView): Partial<Record<TemplateId, string>> {
  const out: Partial<Record<TemplateId, string>> = {};
  for (const [templateId, list] of Object.entries(finalCandidates(v)) as [TemplateId, Render[]][]) {
    const best = v.bestRenderIds[templateId];
    out[templateId] = best ?? [...list].sort((a, b) => (b.score ?? -1) - (a.score ?? -1))[0].id;
  }
```

改成：

```ts
/** 預設選擇：任務的最佳候選優先；需人工審核時取最後一輪分數最高的 */
export function defaultSelection(v: JobView): Partial<Record<TemplateId, string>> {
  const out: Partial<Record<TemplateId, string>> = {};
  for (const [templateId, list] of Object.entries(finalCandidates(v)) as [TemplateId, Candidate[]][]) {
    const best = v.bestRenderIds[templateId];
    out[templateId] = best ?? [...list].sort((a, b) => (b.score ?? -1) - (a.score ?? -1))[0].id;
  }
```

- [ ] **Step 7: 修改 `web/src/components/queue/queue-list.tsx`**

找到（1／3）：

```tsx
import Link from 'next/link';
import { FileDown, ListOrdered, LoaderCircle, Network, Pause, Play, X } from 'lucide-react';
import { toast } from 'sonner';
import type { Render } from '@/types/contract';
import { EmptyState } from '@/components/common/empty-state';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
```

改成：

```tsx
import Link from 'next/link';
import { FileDown, ListOrdered, LoaderCircle, Network, Pause, Play, X } from 'lucide-react';
import { toast } from 'sonner';
import { EmptyState } from '@/components/common/empty-state';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
```

找到（2／3）：

```tsx
import { getApiClient } from '@/lib/api';
import { getTemplate } from '@/lib/compose/templates';
import { exportPosterZip } from '@/lib/export/posters';
import { defaultSelection, jobProgress, STAGE_LABEL } from '@/lib/jobs/view';
import { useAppStore } from '@/lib/store/app';
import { isFinished, useQueueStore, type QueueItem, type QueueStatus } from '@/lib/store/queue';
import { cn } from '@/lib/utils';
```

改成：

```tsx
import { getApiClient } from '@/lib/api';
import { getTemplate } from '@/lib/compose/templates';
import { exportPosterZip } from '@/lib/export/posters';
import { defaultSelection, jobProgress, STAGE_LABEL, type Candidate } from '@/lib/jobs/view';
import { useAppStore } from '@/lib/store/app';
import { isFinished, useQueueStore, type QueueItem, type QueueStatus } from '@/lib/store/queue';
import { cn } from '@/lib/utils';
```

找到（3／3）：

```tsx
    try {
      const api = getApiClient();
      const product = (await api.listProducts(item.brandId)).find((p) => p.id === item.productId) ?? null;
      const renders = Object.values(defaultSelection(view)).map((id) => view.renders[id!]).filter((r): r is Render => !!r);
      await exportPosterZip(brand, product, renders.map((render) => ({ render, copy: render.spec.copy })));
      for (const r of renders) await api.selectRender(view.jobId, r.id, r.spec.copy);
      toast.success(`已匯出「${item.productName}」${renders.length} 張海報`, { description: '已寫入歷史紀錄並標記已回寫 RAG。' });
```

改成：

```tsx
    try {
      const api = getApiClient();
      const product = (await api.listProducts(item.brandId)).find((p) => p.id === item.productId) ?? null;
      const renders = Object.values(defaultSelection(view)).map((id) => view.renders[id!]).filter((r): r is Candidate => !!r);
      await exportPosterZip(brand, product, renders.map((render) => ({ render, copy: render.spec.copy })));
      for (const r of renders) await api.selectRender(view.jobId, r.id, r.spec.copy);
      toast.success(`已匯出「${item.productName}」${renders.length} 張海報`, { description: '已寫入歷史紀錄並標記已回寫 RAG。' });
```

- [ ] **Step 8: 修改 `web/src/components/studio/copy-editor.tsx`**

找到（1／3）：

```tsx
import { useState } from 'react';
import { CircleCheck, Download, FileDown, LoaderCircle, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import type { Brand, Copy, Product, Render } from '@/types/contract';
import { CheckList } from '@/components/poster/check-list';
import { PosterCanvas } from '@/components/poster/poster-canvas';
import { Button } from '@/components/ui/button';
```

改成：

```tsx
import { useState } from 'react';
import { CircleCheck, Download, FileDown, LoaderCircle, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import type { Brand, Copy, Product } from '@/types/contract';
import { CheckList } from '@/components/poster/check-list';
import { PosterCanvas } from '@/components/poster/poster-canvas';
import { Button } from '@/components/ui/button';
```

找到（2／3）：

```tsx
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { getTemplate } from '@/lib/compose/templates';
import { exportPosterPng, exportPosterZip } from '@/lib/export/posters';
import { copyBlockers, recheckCopy } from '@/lib/review/recheck';
import { useStudioStore } from '@/lib/store/studio';
```

改成：

```tsx
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { getTemplate } from '@/lib/compose/templates';
import type { Candidate } from '@/lib/jobs/view';
import { exportPosterPng, exportPosterZip } from '@/lib/export/posters';
import { copyBlockers, recheckCopy } from '@/lib/review/recheck';
import { useStudioStore } from '@/lib/store/studio';
```

找到（3／3）：

```tsx

  const selected = input.templateIds
    .map((t) => (selection[t] ? view.renders[selection[t]!] : undefined))
    .filter((r): r is Render => r !== undefined);
  const checks = selected.map((r) => ({ render: r, checks: recheckCopy(r, brand, copy) }));
  const blockers = checks.flatMap((x) => copyBlockers(x.checks));
  const needsConfirm = view.outcome === 'needs_review' || selected.some((r) => !r.passed);
```

改成：

```tsx

  const selected = input.templateIds
    .map((t) => (selection[t] ? view.renders[selection[t]!] : undefined))
    .filter((r): r is Candidate => r !== undefined);
  const checks = selected.map((r) => ({ render: r, checks: recheckCopy(r, brand, copy) }));
  const blockers = checks.flatMap((x) => copyBlockers(x.checks));
  const needsConfirm = view.outcome === 'needs_review' || selected.some((r) => !r.passed);
```

- [ ] **Step 9: 修改 `backend/app/contract.py`**

找到：

```python
    render_id: str
    score: int
    passed: bool


class RewriteStartedEvent(Model):
```

改成：

```python
    render_id: str
    score: int
    passed: bool
    #: 審查用海報的網址（/files/jobs/{jobId}/{renderId}.png）；模擬模式與 mock 沒有繪製，為 None
    image: str | None


class RewriteStartedEvent(Model):
```

- [ ] **Step 10: 修改 `backend/app/pipeline/runner.py`**

找到：

```python
                    render_id=x.render.id,
                    score=x.result.score,
                    passed=x.result.passed,
                )
            )
```

改成：

```python
                    render_id=x.render.id,
                    score=x.result.score,
                    passed=x.result.passed,
                    image=None,
                )
            )
```

- [ ] **Step 11: 重新產生 fixture**

Run（在 `web/`）：`npm run fixtures`，接著執行 `git diff --stat ../contracts/fixtures`
Expected：4 個檔案各只改一行：每個 `review.completed` 事件在 `"passed"` 後面多了 `"image":null`（共 98 個事件）。只有換行不同的其他檔案用 `git checkout --` 還原。

- [ ] **Step 12: 確認全部通過**

`test_parity.py` 不得修改，也必須通過。

Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint`
Expected：51 個測試檔、423 個測試通過；沒有錯誤。

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected：沒有錯誤；259 passed、3 skipped（沒有模型檔時略過真模型測試）。

- [ ] **Step 13: Commit**

```bash
git add \
  backend/app/contract.py \
  backend/app/pipeline/runner.py \
  contracts/fixtures/stats.json \
  contracts/fixtures/timelines/misty-first-pass.json \
  contracts/fixtures/timelines/selune-needs-review.json \
  contracts/fixtures/timelines/selune-retry.json \
  web/src/components/queue/queue-list.tsx \
  web/src/components/studio/copy-editor.tsx \
  web/src/lib/api/mock/scenario.test.ts \
  web/src/lib/api/mock/scenario.ts \
  web/src/lib/jobs/view.test.ts \
  web/src/lib/jobs/view.ts \
  web/src/types/contract.ts
git commit -m "feat: add the review poster image to review.completed" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7：worker 在伺服器端排版並審查

**Files:**
- Create: `backend/app/pipeline/review.py`
- Modify: `backend/app/adapters/composer.py`、`backend/app/files.py`、`backend/app/pipeline/ports.py`、`backend/app/pipeline/runner.py`、`backend/app/pipeline/sim.py`、`backend/app/settings.py`、`backend/app/worker.py`
- Test: `backend/tests/test_review.py`、`backend/tests/test_pipeline.py`、`backend/tests/test_worker.py`

**Interfaces:**
- Consumes：Task 5 的 `/render`、Task 4 的 `/review`、Task 6 的 `ReviewCompletedEvent.image`。
- Produces：
  - `backend/app/pipeline/ports.py`：
    - `@dataclass(frozen=True) ComposedPoster(url: str, measured_primary: str | None)`；
    - `PosterComposer.compose(job_id, render, product, brand) -> ComposedPoster | None`；
    - `Reviewer.review(brand, render, seed, poster: ComposedPoster | None) -> ReviewResult`；
    - `Ports(retriever, agent, image, posters, reviewer)`。
  - `backend/app/adapters/composer.py`：
    - `ProductImage(data, blend)`、`PosterImages(product=None, logo=None, background=None)`（`.to_json()` 轉 base64）、`RenderedPoster(png, measured_primary, primary_share)`；
    - `ComposerClient.render(render, product, brand, images) -> RenderedPoster`；
    - `ComposerClient.review(spec, brand, measured_primary) -> ReviewResult`。
  - `backend/app/pipeline/review.py`：
    - `MAX_IMAGE_SIDE = 2048`、`fit_image(path) -> bytes`；
    - `ComposerPosters(composer, settings)`、`ComposerReviewer(composer)`。
  - `backend/app/pipeline/sim.py`：`SimPosters.compose(...) -> None`；`SimReviewer` 忽略 `poster`。
  - `backend/app/files.py`：`resolve_url(settings, url) -> Path | None`、`poster_file(settings, job_id, render_id) -> tuple[Path, str]`。
  - `backend/app/settings.py`：`ReviewMode = Literal['composer', 'sim']`、`Settings.review_mode = 'composer'`。

- [ ] **Step 1: 建立 `backend/tests/test_review.py`（先寫測試）**

使用測試啟動的 composer（埠 3902）。

```python
"""REVIEW_MODE=composer：composer 繪製審查用海報（存到 data/jobs/，經 /files 讀取）、量主色、規則審查，
worker 送出的圖檔（去背圖或原圖、Logo、url 背景，大圖先縮小），以及 composer 失敗時任務失敗。

使用測試啟動的 composer（3902 埠，需要 npm run fonts 下載的字型）。
"""

import io
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from redis.asyncio import Redis

from app.adapters.composer import ComposerClient, PosterImages, ProductImage, RenderedPoster
from app.brands import load_brands
from app.contract import (
    Brand,
    BrandLogo,
    FilePhoto,
    JobAcceptedEvent,
    JobInput,
    JobStatusEvent,
    Product,
    ProductCutout,
    Render,
    UrlBackground,
)
from app.db.session import Database
from app.errors import AppError
from app.events import EventStore
from app.pipeline.review import MAX_IMAGE_SIDE, ComposerPosters, ComposerReviewer, fit_image
from app.pipeline.runner import run_job
from app.pipeline.sim import sim_ports
from app.repo import catalog, jobs
from app.settings import Settings
from tests.conftest import LiveApi
from tests.fixtures import BRANDS_DIR, load_fixture

NOW = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)
TIMELINE = load_fixture('timelines/selune-retry.json')
JOB_ID: str = TIMELINE['jobId']
RENDERS = {
    r['id']: Render.model_validate(r)
    for item in TIMELINE['events']
    if item['event']['type'] == 'render.completed'
    for r in item['event']['renders']
}
#: 第 1 輪刻意失誤（applyFlaws：主色換成別的顏色、禁用詞…）；第 2 輪修正後的版本
FLAWED = RENDERS[f'{JOB_ID}_r1_ig-post_v0']
CLEAN = RENDERS[f'{JOB_ID}_r2_ig-post_v0']
CATALOG = load_fixture('brands.json')
SELUNE = Brand.model_validate(next(b for b in CATALOG['brands'] if b['id'] == 'selune'))
SERUM = Product.model_validate(next(p for p in CATALOG['products'] if p['id'] == 'prod_selune_serum'))


class RecordingComposer(ComposerClient):
    """照常呼叫 composer，同時記下 worker 送出的圖檔。"""

    def __init__(self, base_url: str) -> None:
        super().__init__(base_url)
        self.sent: list[PosterImages] = []

    async def render(
        self, render: Render, product: Product | None, brand: Brand, images: PosterImages
    ) -> RenderedPoster:
        self.sent.append(images)
        return await super().render(render, product, brand, images)


@pytest.fixture
async def composer(composer_url: str) -> AsyncIterator[RecordingComposer]:
    client = RecordingComposer(composer_url)
    yield client
    await client.aclose()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None, data_dir=tmp_path / 'data', local_photos_dir=tmp_path / 'local', brands_dir=tmp_path / 'brands'
    )


def image_bytes(size: tuple[int, int], mode: str = 'RGB', fmt: str = 'JPEG', **save: Any) -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, (90, 140, 200, 255)[: len(mode)]).save(out, fmt, **save)
    return out.getvalue()


def save_file(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def opened(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


async def test_the_review_poster_is_written_under_the_job_and_served_through_files(
    api: LiveApi, composer: RecordingComposer
) -> None:
    settings = api.services.settings
    poster = await ComposerPosters(composer, settings).compose(JOB_ID, CLEAN, SERUM, SELUNE)
    assert poster.url == f'/files/jobs/{JOB_ID}/{CLEAN.id}.png'
    path = settings.data_dir / 'jobs' / JOB_ID / f'{CLEAN.id}.png'
    with Image.open(path) as img:
        assert (img.format, img.size) == ('PNG', (CLEAN.spec.canvas.width, CLEAN.spec.canvas.height))
    res = await api.http.get(poster.url)
    assert (res.status_code, res.headers['content-type']) == (200, 'image/png')
    assert res.content == path.read_bytes()
    # 示範商品由 composer 依 productImage 自己產生 SVG；品牌沒有 Logo 圖檔
    assert composer.sent == [PosterImages()]


async def test_a_clean_spec_measures_the_brand_primary_and_passes_color_delta(
    composer: RecordingComposer, settings: Settings
) -> None:
    posters, reviewer = ComposerPosters(composer, settings), ComposerReviewer(composer)
    clean = await posters.compose(JOB_ID, CLEAN, SERUM, SELUNE)
    assert clean.measured_primary == SELUNE.palette.primary.lower()
    result = await reviewer.review(SELUNE, CLEAN, 1, clean)
    assert len(result.checks) == 10
    assert next(c for c in result.checks if c.id == 'color_delta').status == 'pass'
    assert result.passed
    # 分數不加隨機抖動：seed 不同，結果相同
    assert await reviewer.review(SELUNE, CLEAN, 2, clean) == result

    flawed = await posters.compose(JOB_ID, FLAWED, SERUM, SELUNE)
    assert flawed.measured_primary is not None
    color = next(c for c in (await reviewer.review(SELUNE, FLAWED, 1, flawed)).checks if c.id == 'color_delta')
    # 說明文字顯示實際用錯的顏色
    assert color.status == 'fail'
    assert f'偵測主色 {flawed.measured_primary.upper()}' in color.value


async def test_uploaded_products_send_the_cutout_or_the_photo_and_large_photos_are_downscaled(
    composer: RecordingComposer, settings: Settings
) -> None:
    posters = ComposerPosters(composer, settings)
    big = save_file(settings.data_dir / 'uploads' / 'big.jpg', image_bytes((3000, 2000)))
    cut = save_file(settings.data_dir / 'products' / 'prod_up' / 'cutout-1.png', image_bytes((400, 600), 'RGBA', 'PNG'))
    photo = FilePhoto(source='upload', url='/files/uploads/big.jpg')
    done = ProductCutout(model='sim', status='done', url='/files/products/prod_up/cutout-1.png', error=None)
    pending = ProductCutout(model='sim', status='pending', url=None, error=None)

    for cutout in (None, pending, done):
        product = SERUM.model_copy(update={'id': 'prod_up', 'photo': photo, 'cutout': cutout})
        poster = await posters.compose(JOB_ID, CLEAN, product, SELUNE)
        # 商品框不在主色的量測範圍內，換了商品圖仍量得到主色
        assert poster.measured_primary == SELUNE.palette.primary.lower()

    sent = [images.product for images in composer.sent]
    assert all(p is not None for p in sent)
    original, while_pending, cutout_image = (p for p in sent if p is not None)
    # 沒有去背、去背中：原圖以色彩增值合成；20 MB 的照片 base64 後會超過 composer 的上限，先把長邊縮到 2048
    for p in (original, while_pending):
        assert p.blend == 'multiply'
        sent_photo = opened(p.data)
        assert (sent_photo.format, sent_photo.size) == ('JPEG', (MAX_IMAGE_SIDE, round(2000 * MAX_IMAGE_SIDE / 3000)))
    assert opened(big.read_bytes()).size == (3000, 2000)
    # 去背完成：透明 PNG，尺寸夠小時原樣傳送
    assert cutout_image == ProductImage(cut.read_bytes(), 'normal')


async def test_the_logo_and_a_url_background_are_read_for_the_composer(
    composer: RecordingComposer, settings: Settings
) -> None:
    posters = ComposerPosters(composer, settings)
    logo = save_file(settings.brands_dir / 'assets' / 'logo.png', image_bytes((300, 100), 'RGBA', 'PNG'))
    background = save_file(settings.data_dir / 'uploads' / 'bg.jpg', image_bytes((1080, 1080)))
    brand = SELUNE.model_copy(update={'logo': BrandLogo(url='/files/brands/assets/logo.png')})
    render = CLEAN.model_copy(
        update={'background': UrlBackground(kind='url', url='/files/uploads/bg.jpg', includes_product=False)}
    )
    await posters.compose(JOB_ID, render, SERUM, brand)
    assert composer.sent[-1] == PosterImages(logo=logo.read_bytes(), background=background.read_bytes())

    # 與瀏覽器相同：Logo 圖檔不見時改畫向量標誌，海報照樣畫得出來
    logo.unlink()
    await posters.compose(JOB_ID, render, SERUM, brand)
    assert composer.sent[-1].logo is None


async def test_unusable_product_images_fail_with_a_chinese_reason(
    composer: RecordingComposer, settings: Settings
) -> None:
    posters = ComposerPosters(composer, settings)

    def uploaded(name: str) -> Product:
        return SERUM.model_copy(update={'photo': FilePhoto(source='upload', url=f'/files/uploads/{name}')})

    # worker 讀不到或 Pillow 無法解碼：不呼叫 composer
    with pytest.raises(AppError, match=r'^無法繪製審查用海報：找不到商品圖（/files/uploads/gone\.png）$'):
        await posters.compose(JOB_ID, CLEAN, uploaded('gone.png'), SELUNE)
    save_file(settings.data_dir / 'uploads' / 'broken.png', b'not an image')
    with pytest.raises(AppError, match=r'^無法繪製審查用海報：商品圖無法讀取（/files/uploads/broken\.png）：'):
        await posters.compose(JOB_ID, CLEAN, uploaded('broken.png'), SELUNE)
    assert composer.sent == []
    # Pillow 讀得懂、composer 解不開的格式（TIFF）：composer 回 400，原因帶著 composer 的訊息
    save_file(settings.data_dir / 'uploads' / 'scan.png', image_bytes((64, 64), fmt='TIFF'))
    with pytest.raises(AppError, match=r'^排版服務（composer）無法繪製海報：composer /render 失敗：商品圖無法解碼'):
        await posters.compose(JOB_ID, CLEAN, uploaded('scan.png'), SELUNE)
    assert not (settings.data_dir / 'jobs').exists()


def test_fit_image_keeps_small_files_and_downscales_or_rotates_the_rest(tmp_path: Path) -> None:
    small = save_file(tmp_path / 'small.png', image_bytes((800, 600), 'RGBA', 'PNG'))
    assert fit_image(small) == small.read_bytes()
    svg = save_file(tmp_path / 'logo.svg', b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
    assert fit_image(svg) == svg.read_bytes()

    # 透明的大圖縮小後仍是 PNG（保留透明度）；不透明的照片改存 JPEG
    wide = opened(fit_image(save_file(tmp_path / 'wide.png', image_bytes((4096, 1024), 'RGBA', 'PNG'))))
    assert (wide.format, wide.mode, wide.size) == ('PNG', 'RGBA', (2048, 512))
    tall = opened(fit_image(save_file(tmp_path / 'tall.webp', image_bytes((1000, 5000), fmt='WEBP'))))
    assert (tall.format, tall.size) == ('JPEG', (410, 2048))

    # 手機照片的 EXIF 方向（6：順時針轉 90 度）：尺寸不大也要轉正，瀏覽器顯示的就是轉正後的樣子
    exif = Image.Exif()
    exif[0x0112] = 6
    rotated = opened(fit_image(save_file(tmp_path / 'phone.jpg', image_bytes((600, 400), exif=exif))))
    assert rotated.size == (400, 600)
    assert rotated.getexif().get(0x0112, 1) == 1


async def queue_selune_job(db: Database, redis: Redis) -> EventStore:
    async with db.session() as s:
        await catalog.sync_brands(s, load_brands(BRANDS_DIR)[0], NOW)
        await jobs.create_job(s, JOB_ID, JobInput.model_validate(TIMELINE['input']), NOW)
    store = EventStore(db, redis)
    await store.append(JOB_ID, JobAcceptedEvent(type='job.accepted', job_id=JOB_ID))
    await store.append(JOB_ID, JobStatusEvent(type='job.status', stage='queued', round=0))
    return store


async def job_events(db: Database) -> list[dict[str, Any]]:
    async with db.session() as s:
        snap = await jobs.get_job(s, JOB_ID)
    assert snap is not None
    return snap.events


async def test_a_composer_job_fails_the_first_round_on_colour_and_passes_after_rewriting(
    db: Database, redis: Redis, composer_url: str, settings: Settings
) -> None:
    store = await queue_selune_job(db, redis)
    composer = ComposerClient(composer_url)
    try:
        ports = replace(
            sim_ports(composer, first_round_fail=True, force_all_fail=False),
            posters=ComposerPosters(composer, settings),
            reviewer=ComposerReviewer(composer),
        )
        await run_job(JOB_ID, db, store, ports, speed=0)
    finally:
        await composer.aclose()
    events = await job_events(db)
    assert events[-1] == {**events[-1], 'type': 'job.status', 'stage': 'done', 'round': 2}
    completed = [m for m in events if m['type'] == 'review.completed']
    assert [(m['round'], m['passed']) for m in completed] == [(1, False)] * 4 + [(2, True)] * 4
    for m in completed:
        assert m['image'] == f'/files/jobs/{JOB_ID}/{m["renderId"]}.png'
        assert (settings.data_dir / 'jobs' / JOB_ID / f'{m["renderId"]}.png').is_file()
    checks = [m for m in events if m['type'] == 'review.check']
    colour = [(m['round'], m['check']['status']) for m in checks if m['check']['id'] == 'color_delta']
    assert colour == [(1, 'fail')] * 4 + [(2, 'pass')] * 4
    logs = [m['message'] for m in events if m['type'] == 'log' and m['source'] == 'compose']
    assert logs.count('✓ 伺服器端排版 4 張') == 2
    await db.truncate_all()


async def test_the_job_fails_with_a_chinese_reason_when_the_composer_cannot_draw(
    db: Database, redis: Redis, composer_url: str, settings: Settings
) -> None:
    store = await queue_selune_job(db, redis)
    composer, unreachable = ComposerClient(composer_url), ComposerClient('http://127.0.0.1:9')
    try:
        ports = replace(
            sim_ports(composer, first_round_fail=True, force_all_fail=False),
            posters=ComposerPosters(unreachable, settings),
            reviewer=ComposerReviewer(composer),
        )
        await run_job(JOB_ID, db, store, ports, speed=0)
    finally:
        await composer.aclose()
        await unreachable.aclose()
    events = await job_events(db)
    (failed,) = [m for m in events if m['type'] == 'job.failed']
    assert failed['reason'].startswith('排版服務（composer）無法繪製海報：composer 沒有回應（http://127.0.0.1:9）：')
    stages = [m['stage'] for m in events if m['type'] == 'job.status']
    assert stages[-2:] == ['composing', 'failed']
    assert not any(m['type'] == 'review.check' for m in events)
    await db.truncate_all()
```

- [ ] **Step 2: 修改 `backend/tests/test_pipeline.py`（先寫測試）**

找到（1／5）：

```python
"""任務流程的行為：重試只針對未通過的模板、需人工審核、取消、失敗、已不在排隊時不執行、Prompt 只用前 5 筆切塊、
RAG（模型或 Chroma）無法使用時任務失敗。

外部服務用測試替身（不需要 composer）。
"""
```

改成：

```python
"""任務流程的行為：重試只針對未通過的模板、需人工審核、取消、失敗、已不在排隊時不執行、Prompt 只用前 5 筆切塊、
RAG（模型或 Chroma）無法使用時任務失敗、審查用海報傳給審查並放進 review.completed。

外部服務用測試替身（不需要 composer）。
"""
```

找到（2／5）：

```python
)
from app.db.session import Database
from app.events import EventStore
from app.pipeline.ports import Ports, Retriever, ReviewResult, Rewrite, RunContext, SpecRequest
from app.pipeline.runner import PROMPT_REFS, run_job
from app.pipeline.sim import SimRetriever
from app.rag.encoder import Encoder
from app.rag.engine import RagEngine
from app.rag.retriever import BgeRetriever
```

改成：

```python
)
from app.db.session import Database
from app.events import EventStore
from app.pipeline.ports import (
    ComposedPoster,
    Ports,
    PosterComposer,
    Retriever,
    ReviewResult,
    Rewrite,
    RunContext,
    SpecRequest,
)
from app.pipeline.runner import PROMPT_REFS, run_job
from app.pipeline.sim import SimPosters, SimRetriever
from app.rag.encoder import Encoder
from app.rag.engine import RagEngine
from app.rag.retriever import BgeRetriever
```

找到（3／5）：

```python


class FakeReviewer:
    """passing：每一輪會通過的模板。"""

    def __init__(self, passing: dict[int, set[str]]) -> None:
        self.passing = passing

    async def review(self, brand: Brand, render: Render, seed: int) -> ReviewResult:
        ok = render.template_id in self.passing.get(render.round, set())
        return ReviewResult(checks=[] if ok else [CHECK], score=90 - render.variant if ok else 40, passed=ok)


class EmptyRetriever(SimRetriever):
```

改成：

```python


class FakeReviewer:
    """passing：每一輪會通過的模板。posters：收到的審查用海報（依候選 id）。"""

    def __init__(self, passing: dict[int, set[str]]) -> None:
        self.passing = passing
        self.posters: dict[str, ComposedPoster | None] = {}

    async def review(self, brand: Brand, render: Render, seed: int, poster: ComposedPoster | None) -> ReviewResult:
        self.posters[render.id] = poster
        ok = render.template_id in self.passing.get(render.round, set())
        return ReviewResult(checks=[] if ok else [CHECK], score=90 - render.variant if ok else 40, passed=ok)


class FakePosters:
    """每張候選都「畫」一張審查用海報（不呼叫 composer）。"""

    async def compose(self, job_id: str, render: Render, product: Product, brand: Brand) -> ComposedPoster:
        return ComposedPoster(url=f'/files/jobs/{job_id}/{render.id}.png', measured_primary=brand.palette.primary)


class EmptyRetriever(SimRetriever):
```

找到（4／5）：

```python


def ports(
    agent: FakeAgent, reviewer: FakeReviewer, image: FakeImage | None = None, retriever: Retriever | None = None
) -> Ports:
    return Ports(retriever=retriever or EmptyRetriever(), agent=agent, image=image or FakeImage(), reviewer=reviewer)


async def test_retries_only_the_templates_that_failed(store: EventStore, db: Database) -> None:
```

改成：

```python


def ports(
    agent: FakeAgent,
    reviewer: FakeReviewer,
    image: FakeImage | None = None,
    retriever: Retriever | None = None,
    posters: PosterComposer | None = None,
) -> Ports:
    return Ports(
        retriever=retriever or EmptyRetriever(),
        agent=agent,
        image=image or FakeImage(),
        posters=posters or SimPosters(),
        reviewer=reviewer,
    )


async def test_retries_only_the_templates_that_failed(store: EventStore, db: Database) -> None:
```

找到（5／5）：

```python
    completed = next(m for m in events if m['type'] == 'job.completed')
    assert completed['bestRenderIds'] == {'ig-post': f'{JOB}_r1_ig-post_v0', 'story': f'{JOB}_r2_story_v0'}
    assert events[-1] == {**events[-1], 'type': 'job.status', 'stage': 'done', 'round': 2}


async def test_asks_for_manual_review_after_the_last_retry(store: EventStore, db: Database) -> None:
```

改成：

```python
    completed = next(m for m in events if m['type'] == 'job.completed')
    assert completed['bestRenderIds'] == {'ig-post': f'{JOB}_r1_ig-post_v0', 'story': f'{JOB}_r2_story_v0'}
    assert events[-1] == {**events[-1], 'type': 'job.status', 'stage': 'done', 'round': 2}


async def compose_logs(db: Database) -> list[str]:
    async with db.session() as s:
        snap = await jobs.get_job(s, JOB)
    assert snap is not None
    return [m['message'] for m in snap.events if m['type'] == 'log' and m['source'] == 'compose']


async def test_review_posters_go_to_the_review_and_into_review_completed(store: EventStore, db: Database) -> None:
    reviewer = FakeReviewer({1: {'ig-post'}, 2: {'story'}})
    await run_job(JOB, db, store, ports(FakeAgent(), reviewer, posters=FakePosters()), speed=0)
    events = await messages(db)
    completed = [m for m in events if m['type'] == 'review.completed']
    # 第 1 輪 2 個模板 × 2 張，第 2 輪重試 story 的 2 張
    assert len(completed) == 6
    for m in completed:
        url = f'/files/jobs/{JOB}/{m["renderId"]}.png'
        assert m['image'] == url
        assert reviewer.posters[m['renderId']] == ComposedPoster(url=url, measured_primary='#B76E79')
    assert await compose_logs(db) == [
        '排版引擎疊加文字圖層（4 張）',
        '✓ 伺服器端排版 4 張',
        '排版引擎疊加文字圖層（2 張）',
        '✓ 伺服器端排版 2 張',
    ]


async def test_simulated_posters_add_nothing_to_the_events(store: EventStore, db: Database) -> None:
    reviewer = FakeReviewer({1: {'ig-post', 'story'}})
    await run_job(JOB, db, store, ports(FakeAgent(), reviewer), speed=0)
    completed = [m for m in await messages(db) if m['type'] == 'review.completed']
    assert [m['image'] for m in completed] == [None] * 4
    assert set(reviewer.posters.values()) == {None}
    assert await compose_logs(db) == ['排版引擎疊加文字圖層（4 張）']


async def test_asks_for_manual_review_after_the_last_retry(store: EventStore, db: Database) -> None:
```

- [ ] **Step 3: 修改 `backend/tests/test_worker.py`（先寫測試）**

找到（1／3）：

```python
from app.db.session import Database
from app.errors import Unavailable
from app.events import EventStore
from app.pipeline.sim import SimRetriever, sim_ports
from app.queues import Queues, TaskFailed, cutout_key, ingest_channel
from app.rag.chunking import EMBED_DIMS, chunk_document, embed_preview, vector_preview
from app.rag.engine import RagEngine
```

改成：

```python
from app.db.session import Database
from app.errors import Unavailable
from app.events import EventStore
from app.pipeline.review import ComposerPosters, ComposerReviewer
from app.pipeline.sim import SimPosters, SimRetriever, SimReviewer, sim_ports
from app.queues import Queues, TaskFailed, cutout_key, ingest_channel
from app.rag.chunking import EMBED_DIMS, chunk_document, embed_preview, vector_preview
from app.rag.engine import RagEngine
```

找到（2／3）：

```python
from app.rag.store import VectorStore
from app.rag.sync import SyncResult, chunk_metadata, index_text, sync_brand
from app.repo import catalog, history, jobs
from app.settings import Settings
from app.worker import (
    RESTART_REASON,
    Services,
```

改成：

```python
from app.rag.store import VectorStore
from app.rag.sync import SyncResult, chunk_metadata, index_text, sync_brand
from app.repo import catalog, history, jobs
from app.settings import ReviewMode, Settings
from app.worker import (
    RESTART_REASON,
    Services,
```

找到（3／3）：

```python
        await built.db.dispose()


class StateRecorder:
    def __init__(self) -> None:
        self.states: list[object] = []
```

改成：

```python
        await built.db.dispose()


@pytest.mark.parametrize(
    ('mode', 'posters', 'reviewer'),
    [('composer', ComposerPosters, ComposerReviewer), ('sim', SimPosters, SimReviewer)],
)
async def test_build_services_picks_the_posters_and_the_reviewer_by_review_mode(
    mode: ReviewMode, posters: type, reviewer: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr('app.worker.settings', Settings(_env_file=None, brands_dir=BRANDS_DIR, review_mode=mode))
    built = build_services()
    try:
        assert isinstance(built.ports.posters, posters)
        assert isinstance(built.ports.reviewer, reviewer)
        if isinstance(built.ports.posters, ComposerPosters):
            # 審查用海報寫到 worker 設定的 data/，與 /files 讀取的是同一個資料夾
            assert built.ports.posters.composer is built.composer
            assert built.ports.posters.settings is built.settings
    finally:
        await built.composer.aclose()
        await built.redis.aclose()
        await built.db.dispose()


def test_review_mode_defaults_to_the_composer() -> None:
    assert Settings(_env_file=None).review_mode == 'composer'


class StateRecorder:
    def __init__(self) -> None:
        self.states: list[object] = []
```

- [ ] **Step 4: 確認測試失敗**

Run（在 `backend/`）：`uv run pytest -q tests/test_review.py tests/test_pipeline.py tests/test_worker.py`
Expected：FAIL，3 個測試檔收集時出錯：`ImportError: cannot import name 'PosterImages' from 'app.adapters.composer'`、`ModuleNotFoundError: No module named 'app.pipeline.review'`。

- [ ] **Step 5: 修改 `backend/app/settings.py`**

找到（1／2）：

```python
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.rag.state import RagMode

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]
```

改成：

```python
"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.rag.state import RagMode

#: 審查：composer（伺服器端繪製審查用海報、量主色、規則審查）或 sim（不畫圖，沿用 mock 的審查；測試與作品集 Demo）
ReviewMode = Literal['composer', 'sim']

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]
```

找到（2／2）：

```python
    #: 向量庫（Docker 內為 http://chroma:8000）
    chroma_url: str = 'http://127.0.0.1:8001'

    #: 模擬模式的播放速度（1 為 1× 時間軸，約 15 秒一個任務；0 為不等待）
    sim_speed: float = 1.0
    #: 模擬模式：第一輪刻意失誤（觸發 Query Rewriting）
```

改成：

```python
    #: 向量庫（Docker 內為 http://chroma:8000）
    chroma_url: str = 'http://127.0.0.1:8001'

    #: 審查：composer（預設；composer 繪製審查用海報存到 data/jobs/，量出主色後審查，分數不加抖動）
    #: 或 sim（不畫圖，審查結果與前端 mock 相同）
    review_mode: ReviewMode = 'composer'

    #: 模擬模式的播放速度（1 為 1× 時間軸，約 15 秒一個任務；0 為不等待）
    sim_speed: float = 1.0
    #: 模擬模式：第一輪刻意失誤（觸發 Query Rewriting）
```

- [ ] **Step 6: 修改 `backend/app/files.py`**

找到（1／4）：

```python
"""/files/... 網址與檔案的對應（api 提供檔案、worker 讀取商品照共用）：

- /files/uploads/…、/files/products/{id}/…（去背圖）→ data/
- /files/local/{檔名} → 本機資料夾 assets/products/
- /files/brands/… → 品牌設定檔資料夾（Logo 等圖檔）
"""
```

改成：

```python
"""/files/... 網址與檔案的對應（api 提供檔案、worker 讀取商品照與寫入審查用海報共用）：

- /files/uploads/…、/files/products/{id}/…（去背圖）、/files/jobs/{jobId}/{renderId}.png（審查用海報）→ data/
- /files/local/{檔名} → 本機資料夾 assets/products/
- /files/brands/… → 品牌設定檔資料夾（Logo 等圖檔）
"""
```

找到（2／4）：

```python
PREFIX = '/files/'
#: 商品 id 要能直接當資料夾名稱：不含路徑分隔字元，也不能是 . 或 ..
PRODUCT_ID = re.compile(r'[A-Za-z0-9_-]{1,64}')


def resolve_file(settings: Settings, path: str) -> Path | None:
```

改成：

```python
PREFIX = '/files/'
#: 商品 id 要能直接當資料夾名稱：不含路徑分隔字元，也不能是 . 或 ..
PRODUCT_ID = re.compile(r'[A-Za-z0-9_-]{1,64}')
#: 任務 id 與候選 id（{jobId}_r{round}_{templateId}_v{variant}）同樣直接當資料夾與檔案名稱
JOB_FILE_ID = re.compile(r'[A-Za-z0-9_-]{1,128}')


def resolve_file(settings: Settings, path: str) -> Path | None:
```

找到（3／4）：

```python
    return target


def photo_path(settings: Settings, url: str) -> Path:
    """商品照的網址（/files/uploads/…、/files/local/…，檔名經過 URL 編碼）→ 檔案。"""
    target = resolve_file(settings, unquote(url.removeprefix(PREFIX))) if url.startswith(PREFIX) else None
    if target is None:
        raise NotFound(f'找不到商品照：{unquote(url)}')
    return target
```

改成：

```python
    return target


def resolve_url(settings: Settings, url: str) -> Path | None:
    """/files/... 網址（檔名經過 URL 編碼）→ 檔案；不是 /files/ 網址或找不到檔案時為 None。"""
    return resolve_file(settings, unquote(url.removeprefix(PREFIX))) if url.startswith(PREFIX) else None


def photo_path(settings: Settings, url: str) -> Path:
    """商品照的網址（/files/uploads/…、/files/local/…，檔名經過 URL 編碼）→ 檔案。"""
    target = resolve_url(settings, url)
    if target is None:
        raise NotFound(f'找不到商品照：{unquote(url)}')
    return target
```

找到（4／4）：

```python
    if not PRODUCT_ID.fullmatch(product_id):
        raise Invalid(f'商品 id 格式錯誤：{product_id}')
    return settings.data_dir / 'products' / product_id
```

改成：

```python
    if not PRODUCT_ID.fullmatch(product_id):
        raise Invalid(f'商品 id 格式錯誤：{product_id}')
    return settings.data_dir / 'products' / product_id


def poster_file(settings: Settings, job_id: str, render_id: str) -> tuple[Path, str]:
    """審查用海報的檔案與網址：data/jobs/{jobId}/{renderId}.png 與 /files/jobs/{jobId}/{renderId}.png。
    id 格式不對時不給路徑，避免寫到 data/jobs 之外。"""
    for value in (job_id, render_id):
        if not JOB_FILE_ID.fullmatch(value):
            raise Invalid(f'任務或候選 id 格式錯誤：{value}')
    return settings.data_dir / 'jobs' / job_id / f'{render_id}.png', f'{PREFIX}jobs/{job_id}/{render_id}.png'
```

- [ ] **Step 7: 修改 `backend/app/pipeline/ports.py`**

找到（1／2）：

```python
    ) -> dict[tuple[TemplateId, int], RenderBackground]: ...


class Reviewer(Protocol):
    async def review(self, brand: Brand, render: Render, seed: int) -> ReviewResult: ...


@dataclass(frozen=True)
```

改成：

```python
    ) -> dict[tuple[TemplateId, int], RenderBackground]: ...


@dataclass(frozen=True)
class ComposedPoster:
    """伺服器端繪製的審查用海報。"""

    #: 審查用海報的網址（/files/jobs/{jobId}/{renderId}.png）
    url: str
    #: 從海報像素量到的品牌主色（小寫 #rrggbb）；量不到時為 None
    measured_primary: str | None


class PosterComposer(Protocol):
    async def compose(self, job_id: str, render: Render, product: Product, brand: Brand) -> ComposedPoster | None:
        """繪製一張候選的審查用海報並存檔；模擬版不畫圖，回傳 None。"""
        ...


class Reviewer(Protocol):
    async def review(self, brand: Brand, render: Render, seed: int, poster: ComposedPoster | None) -> ReviewResult:
        """poster 是排版階段繪製的審查用海報（模擬版為 None）。"""
        ...


@dataclass(frozen=True)
```

找到（2／2）：

```python
    retriever: Retriever
    agent: Agent
    image: ImageEngine
    reviewer: Reviewer
```

改成：

```python
    retriever: Retriever
    agent: Agent
    image: ImageEngine
    posters: PosterComposer
    reviewer: Reviewer
```

- [ ] **Step 8: 修改 `backend/app/adapters/composer.py`**

找到（1／3）：

```python
"""composer（web/composer）的用戶端：版型，以及模擬模式沿用的前端 mock 邏輯（/sim/*）。"""

from typing import Any

import httpx

from app.contract import Brand, Fix, LayoutBox, ParsedBrief, Product, PromptSpec, ReviewCheck, TemplateId
from app.pipeline.ports import ReviewResult, SpecRequest


class ComposerError(Exception):
    pass


class ComposerClient:
```

改成：

```python
"""composer（web/composer）的用戶端：版型、審查用海報的繪製與審查（REVIEW_MODE=composer），
以及模擬模式沿用的前端 mock 邏輯（/sim/*）。"""

import base64
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.contract import Brand, Fix, LayoutBox, ParsedBrief, Product, PromptSpec, Render, ReviewCheck, TemplateId
from app.pipeline.ports import ReviewResult, SpecRequest


class ComposerError(Exception):
    pass


@dataclass(frozen=True)
class ProductImage:
    data: bytes
    #: 去背圖為 normal；原圖以色彩增值（multiply）合成（與前端 productImage 相同）
    blend: Literal['normal', 'multiply']


@dataclass(frozen=True)
class PosterImages:
    """worker 讀好的圖檔（送出時轉成 base64）；composer 不讀任何資料夾。"""

    #: 上傳商品的去背圖或原圖；示範商品由 composer 自己產生 SVG，為 None
    product: ProductImage | None = None
    #: 品牌的 Logo 圖檔；None 時畫向量標誌與字標
    logo: bytes | None = None
    #: 背景為 url 時的圖檔；程式產生的背景為 None
    background: bytes | None = None

    def to_json(self) -> dict[str, Any]:
        def encoded(data: bytes) -> str:
            return base64.b64encode(data).decode('ascii')

        return {
            'product': {'base64': encoded(self.product.data), 'blend': self.product.blend} if self.product else None,
            'logo': {'base64': encoded(self.logo)} if self.logo is not None else None,
            'background': {'base64': encoded(self.background)} if self.background is not None else None,
        }


@dataclass(frozen=True)
class RenderedPoster:
    png: bytes
    #: 量到的品牌主色（小寫 #rrggbb）；量不到時為 None
    measured_primary: str | None
    #: 主色色塊佔量測範圍的比例（0–1）
    primary_share: float


def _error_message(res: httpx.Response) -> str:
    """composer 的錯誤回應是 { error: { code, message } }；不是時（例如經過代理）改用狀態碼與內文開頭。"""
    try:
        return str(res.json()['error']['message'])
    except (ValueError, KeyError, TypeError):
        return f'HTTP {res.status_code} {res.text[:200]}'


def _review_result(data: Any) -> ReviewResult:
    checks = [ReviewCheck.model_validate(c) for c in data['checks']]
    return ReviewResult(checks=checks, score=data['score'], passed=data['passed'])


class ComposerClient:
```

找到（2／3）：

```python
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
```

改成：

```python
    async def aclose(self) -> None:
        await self._client.aclose()

    async def _send(self, path: str, body: dict[str, Any]) -> httpx.Response:
        try:
            res = await self._client.post(path, json=body)
        except httpx.HTTPError as e:
            raise ComposerError(f'composer 沒有回應（{self.base_url}）：{e!r}') from e
        if res.status_code != 200:
            raise ComposerError(f'composer {path} 失敗：{_error_message(res)}')
        return res

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        return (await self._send(path, body)).json()

    async def health(self) -> bool:
        try:
```

找到（3／3）：

```python
        }
        return PromptSpec.model_validate(await self._post('/sim/prompt', body))

    async def sim_review(self, spec: PromptSpec, brand: Brand, variant: int, seed: int) -> ReviewResult:
        body = {'spec': spec.to_json(), 'brand': brand.to_json(), 'variant': variant, 'seed': seed}
        data = await self._post('/sim/review', body)
        checks = [ReviewCheck.model_validate(c) for c in data['checks']]
        return ReviewResult(checks=checks, score=data['score'], passed=data['passed'])

    async def sim_fixes(self, checks: list[ReviewCheck], brand: Brand, spec: PromptSpec) -> list[Fix]:
        body = {'checks': [c.to_json() for c in checks], 'brand': brand.to_json(), 'spec': spec.to_json()}
```

改成：

```python
        }
        return PromptSpec.model_validate(await self._post('/sim/prompt', body))

    async def render(
        self, render: Render, product: Product | None, brand: Brand, images: PosterImages
    ) -> RenderedPoster:
        """在伺服器端繪製審查用海報（/render）：模板原始尺寸的 PNG，以及從像素量到的品牌主色。"""
        body = {
            'render': render.to_json(),
            'product': product.to_json() if product else None,
            'brand': brand.to_json(),
            'images': images.to_json(),
        }
        res = await self._send('/render', body)
        if res.headers.get('Content-Type') != 'image/png':
            raise ComposerError(f'composer /render 沒有回傳 PNG：{res.headers.get("Content-Type")}')
        return RenderedPoster(
            png=res.content,
            measured_primary=res.headers.get('X-Measured-Primary') or None,
            primary_share=float(res.headers.get('X-Primary-Share') or 0),
        )

    async def review(self, spec: PromptSpec, brand: Brand, measured_primary: str | None) -> ReviewResult:
        """live 模式的審查（/review）：7 項規則加 3 項依內容判斷的 VLM 檢查，分數不加隨機抖動。"""
        body = {'spec': spec.to_json(), 'brand': brand.to_json(), 'measuredPrimary': measured_primary}
        return _review_result(await self._post('/review', body))

    async def sim_review(self, spec: PromptSpec, brand: Brand, variant: int, seed: int) -> ReviewResult:
        body = {'spec': spec.to_json(), 'brand': brand.to_json(), 'variant': variant, 'seed': seed}
        return _review_result(await self._post('/sim/review', body))

    async def sim_fixes(self, checks: list[ReviewCheck], brand: Brand, spec: PromptSpec) -> list[Fix]:
        body = {'checks': [c.to_json() for c in checks], 'brand': brand.to_json(), 'spec': spec.to_json()}
```

- [ ] **Step 9: 建立 `backend/app/pipeline/review.py`**

```python
"""真實版的排版與審查（REVIEW_MODE=composer）：

- ComposerPosters：worker 以 resolve_file 讀商品圖與 Logo，composer 在伺服器端繪製審查用海報（與瀏覽器相同的
  scene.ts 與 paint.ts）並從像素量出品牌主色，worker 把 PNG 存到 data/jobs/{jobId}/{renderId}.png。
- ComposerReviewer：以量到的主色呼叫 composer 的 /review（7 項規則加 3 項依內容判斷的 VLM 檢查，分數不加抖動）。

composer 沒有回應或回傳錯誤時任務失敗，原因為中文。
"""

import asyncio
import io
import logging
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app.adapters.composer import ComposerClient, ComposerError, PosterImages, ProductImage
from app.contract import Brand, FilePhoto, Product, Render, UrlBackground
from app.errors import AppError
from app.files import poster_file, resolve_url
from app.pipeline.ports import ComposedPoster, ReviewResult
from app.settings import Settings

logger = logging.getLogger(__name__)

#: 傳給 composer 的商品圖與 Logo 的長邊上限（像素）：上傳的照片最大 20 MB，base64 後約 26.7 MB，
#: 加上其他欄位可能超過 composer 的請求上限（30 MB）；海報上的商品圖也用不到更大的尺寸
MAX_IMAGE_SIDE = 2048
#: EXIF 的拍攝方向（1 為正向）
EXIF_ORIENTATION = 0x0112

#: 任務失敗的原因開頭：composer 沒有回應或回傳錯誤，以及 worker 讀不到海報要用的圖檔
COMPOSE_FAILED = '排版服務（composer）無法繪製海報：'
REVIEW_FAILED = '排版服務（composer）無法審查海報：'
MISSING_IMAGE = '無法繪製審查用海報：'


def fit_image(path: Path) -> bytes:
    """讀取商品圖或 Logo，準備傳給 composer。

    長邊超過 MAX_IMAGE_SIDE，或 EXIF 記錄了旋轉方向（手機照片）時，以 Pillow 轉正、縮小後重新編碼：
    有透明度用 PNG，否則用 JPEG。其他情況原樣傳送，與瀏覽器載入的檔案相同。SVG 不經過 Pillow。
    讀不到或無法解碼時丟出 OSError 或 Pillow 的例外，由呼叫端決定如何處理。
    """
    data = path.read_bytes()
    if path.suffix.lower() == '.svg':
        return data
    with Image.open(io.BytesIO(data)) as img:
        rotated = img.getexif().get(EXIF_ORIENTATION, 1) != 1
        if max(img.size) <= MAX_IMAGE_SIDE and not rotated:
            return data
        fitted = ImageOps.exif_transpose(img)
    fitted.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    if fitted.mode in ('RGBA', 'LA', 'PA') or 'transparency' in fitted.info:
        fitted.convert('RGBA').save(out, 'PNG')
    else:
        fitted.convert('RGB').save(out, 'JPEG', quality=90)
    return out.getvalue()


#: 圖檔讀取或解碼失敗時 Pillow 與檔案系統可能丟出的例外
IMAGE_ERRORS = (OSError, UnidentifiedImageError, Image.DecompressionBombError, ValueError, SyntaxError)


class ComposerPosters:
    """真實版的排版：composer 繪製審查用海報並量主色，worker 存檔。"""

    def __init__(self, composer: ComposerClient, settings: Settings) -> None:
        self.composer = composer
        self.settings = settings

    async def compose(self, job_id: str, render: Render, product: Product, brand: Brand) -> ComposedPoster:
        target, url = poster_file(self.settings, job_id, render.id)
        images = await asyncio.to_thread(self._images, render, product, brand)
        try:
            poster = await self.composer.render(render, product, brand, images)
        except ComposerError as error:
            raise AppError(f'{COMPOSE_FAILED}{error}') from error
        await asyncio.to_thread(_write, target, poster.png)
        return ComposedPoster(url=url, measured_primary=poster.measured_primary)

    def _images(self, render: Render, product: Product, brand: Brand) -> PosterImages:
        """在執行緒裡讀圖與縮圖（大張照片解碼約需數百毫秒）。"""
        return PosterImages(
            product=self._product(product),
            logo=self._logo(brand),
            background=self._required(render.background.url, '背景圖')
            if isinstance(render.background, UrlBackground)
            else None,
        )

    def _product(self, product: Product) -> ProductImage | None:
        """與前端 productImage 相同：去背完成用去背圖（normal），否則用原圖並以色彩增值（multiply）合成。
        示範商品由 composer 依 productImage 產生 SVG。"""
        if not isinstance(product.photo, FilePhoto):
            return None
        cut = product.cutout
        if cut is not None and cut.status == 'done' and cut.url:
            return ProductImage(self._required(cut.url, '商品去背圖'), 'normal')
        return ProductImage(self._required(product.photo.url, '商品圖'), 'multiply')

    def _logo(self, brand: Brand) -> bytes | None:
        """與前端相同：Logo 圖檔找不到或無法讀取時改畫向量標誌與字標。"""
        if brand.logo is None:
            return None
        path = resolve_url(self.settings, brand.logo.url)
        if path is None:
            logger.warning('找不到品牌 Logo 圖檔，審查用海報改畫向量標誌：%s', brand.logo.url)
            return None
        try:
            return fit_image(path)
        except IMAGE_ERRORS:
            logger.warning('品牌 Logo 圖檔無法讀取，審查用海報改畫向量標誌：%s', brand.logo.url, exc_info=True)
            return None

    def _required(self, url: str, label: str) -> bytes:
        """審查用海報是紀錄，不像瀏覽器預覽那樣略過讀不到的圖：找不到或無法讀取時任務失敗。"""
        path = resolve_url(self.settings, url)
        if path is None:
            raise AppError(f'{MISSING_IMAGE}找不到{label}（{url}）')
        try:
            return fit_image(path)
        except IMAGE_ERRORS as error:
            raise AppError(f'{MISSING_IMAGE}{label}無法讀取（{url}）：{error}') from error


def _write(target: Path, png: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(png)


class ComposerReviewer:
    """真實版的審查：以審查用海報量到的主色呼叫 /review，分數不加隨機抖動（seed 不使用）。"""

    def __init__(self, composer: ComposerClient) -> None:
        self.composer = composer

    async def review(self, brand: Brand, render: Render, seed: int, poster: ComposedPoster | None) -> ReviewResult:
        if poster is None:
            raise AppError('審查需要伺服器端繪製的審查用海報（REVIEW_MODE=composer 時由 ComposerPosters 繪製）')
        try:
            return await self.composer.review(render.spec, brand, poster.measured_primary)
        except ComposerError as error:
            raise AppError(f'{REVIEW_FAILED}{error}') from error
```

- [ ] **Step 10: 修改 `backend/app/pipeline/sim.py`**

找到（1／4）：

```python
"""模擬版的外部服務：行為與前端 mock 劇本相同（web/src/lib/api/mock/scenario.ts）。

檢索與生圖在這裡實作；Agent 與審查透過 composer 沿用前端的 TypeScript
（buildPromptSpec、applyFlaws、reviewRender、planFixes）。
"""

from app.adapters.composer import ComposerClient
```

改成：

```python
"""模擬版的外部服務：行為與前端 mock 劇本相同（web/src/lib/api/mock/scenario.ts）。

檢索與生圖在這裡實作；Agent 與審查透過 composer 沿用前端的 TypeScript
（buildPromptSpec、applyFlaws、reviewRender、planFixes）。排版不在伺服器端畫圖（前端依 spec 繪製）。
"""

from app.adapters.composer import ComposerClient
```

找到（2／4）：

```python
    ReviewCheck,
    TemplateId,
)
from app.pipeline.ports import Ports, ReviewResult, Rewrite, RunContext, SpecRequest

#: 向量召回順序與 Rerank 後順序刻意不同，用來展示 BGE Reranker 的效果
VECTOR_ORDER: list[RagTag] = ['layout', 'color', 'history', 'logo', 'law']
```

改成：

```python
    ReviewCheck,
    TemplateId,
)
from app.pipeline.ports import ComposedPoster, Ports, ReviewResult, Rewrite, RunContext, SpecRequest

#: 向量召回順序與 Rerank 後順序刻意不同，用來展示 BGE Reranker 的效果
VECTOR_ORDER: list[RagTag] = ['layout', 'color', 'history', 'logo', 'law']
```

找到（3／4）：

```python
        }


class SimReviewer:
    def __init__(self, composer: ComposerClient) -> None:
        self.composer = composer

    async def review(self, brand: Brand, render: Render, seed: int) -> ReviewResult:
        return await self.composer.sim_review(render.spec, brand, render.variant, seed)
```

改成：

```python
        }


class SimPosters:
    """不畫審查用海報：模擬模式的事件與 mock 完全相同（review.completed 的 image 為 null）。"""

    async def compose(self, job_id: str, render: Render, product: Product, brand: Brand) -> None:
        return None


class SimReviewer:
    """與 mock 相同的審查（reviewRender：假的主色量測與劇本式的 VLM 警告，分數依 seed 抖動）；忽略 poster。"""

    def __init__(self, composer: ComposerClient) -> None:
        self.composer = composer

    async def review(self, brand: Brand, render: Render, seed: int, poster: ComposedPoster | None) -> ReviewResult:
        return await self.composer.sim_review(render.spec, brand, render.variant, seed)
```

找到（4／4）：

```python
        retriever=SimRetriever(),
        agent=SimAgent(composer, first_round_fail=first_round_fail, force_all_fail=force_all_fail),
        image=SimImageEngine(),
        reviewer=SimReviewer(composer),
    )
```

改成：

```python
        retriever=SimRetriever(),
        agent=SimAgent(composer, first_round_fail=first_round_fail, force_all_fail=force_all_fail),
        image=SimImageEngine(),
        posters=SimPosters(),
        reviewer=SimReviewer(composer),
    )
```

- [ ] **Step 11: 修改 `backend/app/pipeline/runner.py`**

找到（1／4）：

```python
from app.db.session import Database
from app.errors import AppError
from app.events import EventStore
from app.pipeline.ports import Ports, ReviewResult, SpecRequest
from app.repo import catalog, jobs
from app.templates import get_template
```

改成：

```python
from app.db.session import Database
from app.errors import AppError
from app.events import EventStore
from app.pipeline.ports import ComposedPoster, Ports, ReviewResult, SpecRequest
from app.repo import catalog, jobs
from app.templates import get_template
```

找到（2／4）：

```python
class Reviewed:
    render: Render
    result: ReviewResult


async def run_job(job_id: str, db: Database, store: EventStore, ports: Ports, *, speed: float) -> None:
```

改成：

```python
class Reviewed:
    render: Render
    result: ReviewResult
    #: 排版階段繪製的審查用海報；模擬模式為 None
    poster: ComposedPoster | None


async def run_job(job_id: str, db: Database, store: EventStore, ports: Ports, *, speed: float) -> None:
```

找到（3／4）：

```python
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
```

改成：

```python
        ]
        await run.emit(RenderCompletedEvent(type='render.completed', round=round, renders=renders))

        # 5. 文字排版合成：真實版在伺服器端繪製審查用海報並量主色；模擬版不畫圖（事件與 mock 相同）
        await run.status('composing', round)
        await run.log('compose', f'排版引擎疊加文字圖層（{len(renders)} 張）')
        posters: list[ComposedPoster | None] = []
        for r in renders:
            await run.checkpoint()
            posters.append(await ports.posters.compose(job_id, r, product, brand))
        composed = sum(p is not None for p in posters)
        if composed:
            await run.log('compose', f'✓ 伺服器端排版 {composed} 張', 'ok')
        await run.pace(PHASE_MS['compose'])

        # 6. 合規審查（規則 + VLM）
        await run.status('reviewing', round)
        await run.log('vlm', f'{inp.vlm}：審查 {len(renders)} 張 × 10 項')
        reviewed = [
            Reviewed(r, await ports.reviewer.review(brand, r, hash_string(r.id) ^ job_seed, poster), poster)
            for r, poster in zip(renders, posters, strict=True)
        ]
        dt = PHASE_MS['review'] / max(1, sum(len(x.result.checks) for x in reviewed))
        for x in reviewed:
            for check in x.result.checks:
```

找到（4／4）：

```python
                    render_id=x.render.id,
                    score=x.result.score,
                    passed=x.result.passed,
                    image=None,
                )
            )
```

改成：

```python
                    render_id=x.render.id,
                    score=x.result.score,
                    passed=x.result.passed,
                    image=x.poster.url if x.poster else None,
                )
            )
```

- [ ] **Step 12: 修改 `backend/app/worker.py`**

找到（1／3）：

```python
from app.events import EventStore
from app.files import photo_path, product_folder
from app.pipeline.ports import Ports
from app.pipeline.runner import failure_reason, run_job
from app.pipeline.sim import sim_ports
from app.queues import TASK_TIMEOUT, Queues, ingest_channel
```

改成：

```python
from app.events import EventStore
from app.files import photo_path, product_folder
from app.pipeline.ports import Ports
from app.pipeline.review import ComposerPosters, ComposerReviewer
from app.pipeline.runner import failure_reason, run_job
from app.pipeline.sim import sim_ports
from app.queues import TASK_TIMEOUT, Queues, ingest_channel
```

找到（2／3）：

```python


def build_services() -> Services:
    """RAG_MODE=bge 時檢索換成 BgeRetriever；Agent、生圖與審查仍是模擬版（Plan 6、7 換成真實版）。"""
    db = Database(settings.database_url)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    composer = ComposerClient(settings.composer_url)
```

改成：

```python


def build_services() -> Services:
    """RAG_MODE=bge 時檢索換成 BgeRetriever；REVIEW_MODE=composer 時排版與審查換成 ComposerPosters 與
    ComposerReviewer（伺服器端繪製審查用海報、量主色、規則審查）。Agent 與生圖仍是模擬版（Plan 6B、7 換成真實版）。"""
    db = Database(settings.database_url)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    composer = ComposerClient(settings.composer_url)
```

找到（3／3）：

```python
    )
    if settings.rag_mode == 'bge':
        ports = replace(ports, retriever=BgeRetriever(db, vectors, rag, locks))
    cutouts = CutoutEngine(settings.cutout_model, settings.models_dir, redis)
    store = EventStore(db, redis)
    return Services(db, redis, store, composer, ports, settings.sim_speed, settings, cutouts, rag, vectors, locks)
```

改成：

```python
    )
    if settings.rag_mode == 'bge':
        ports = replace(ports, retriever=BgeRetriever(db, vectors, rag, locks))
    if settings.review_mode == 'composer':
        ports = replace(ports, posters=ComposerPosters(composer, settings), reviewer=ComposerReviewer(composer))
    cutouts = CutoutEngine(settings.cutout_model, settings.models_dir, redis)
    store = EventStore(db, redis)
    return Services(db, redis, store, composer, ports, settings.sim_speed, settings, cutouts, rag, vectors, locks)
```

- [ ] **Step 13: 確認全部通過**

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected：沒有錯誤；272 passed、3 skipped（沒有模型檔時略過真模型測試）。

- [ ] **Step 14: Commit**

```bash
git add \
  backend/app/adapters/composer.py \
  backend/app/files.py \
  backend/app/pipeline/ports.py \
  backend/app/pipeline/review.py \
  backend/app/pipeline/runner.py \
  backend/app/pipeline/sim.py \
  backend/app/settings.py \
  backend/app/worker.py \
  backend/tests/test_pipeline.py \
  backend/tests/test_review.py \
  backend/tests/test_worker.py
git commit -m "feat: compose and review the posters on the server in the worker" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8：後端測試不讀取 `.env`

**Files:**
- Modify: `backend/tests/conftest.py`、`backend/tests/test_api_catalog.py`、`backend/tests/test_cutout_model.py`、`backend/tests/test_rag_model.py`、`backend/tests/test_worker.py`

**Interfaces:**
- Produces：`tests/conftest.py` 的 `BASE_SETTINGS = Settings(_env_file=None)`。測試裡所有的 `Settings(...)` 都加上 `_env_file=None`。

Plan 6B 會在 `.env` 放入 Gemini API key，測試不能讀到它；`.env` 裡的 `RAG_MODE`、`REVIEW_MODE` 也不能改變測試結果。

- [ ] **Step 1: 確認 `Settings()` 會讀到 `.env`（先證明問題）**

在 repo 根目錄建立暫時的 `.env`，內容如下：

```text
RAG_MODE=sim
REVIEW_MODE=sim
```

Run（在 `backend/`）：`uv run python -c "from app.settings import Settings; s = Settings(); print(s.rag_mode, s.review_mode); t = Settings(_env_file=None); print(t.rag_mode, t.review_mode)"`
Expected：第一行 `sim sim`（讀到了 `.env`），第二行 `bge composer`（不讀 `.env`）。這就是測試要全部改用 `_env_file=None` 的原因。接著刪除這個暫時的 `.env`。

- [ ] **Step 2: 修改 `backend/tests/conftest.py`**

找到（1／5）：

```python

每次測試開始時重建 genai_test 資料庫並跑 migration；每個測試結束後清空所有資料表。
Chroma 使用另一個 database genai_test；每個測試結束後刪除所有 collection。
"""

import asyncio
```

改成：

```python

每次測試開始時重建 genai_test 資料庫並跑 migration；每個測試結束後清空所有資料表。
Chroma 使用另一個 database genai_test；每個測試結束後刪除所有 collection。
測試的 Settings 一律以 _env_file=None 建立：不讀 repo 的 .env（只用預設值與環境變數）。
"""

import asyncio
```

找到（2／5）：

```python
from app.queues import Queues
from app.rag.engine import RagEngine
from app.rag.store import VectorStore
from app.settings import REPO_ROOT, Settings, settings
from app.worker import Services as WorkerServices
from app.worker import build_workers
from tests.fixtures import BRANDS_DIR

TEST_DATABASE = 'genai_test'
#: 測試使用 Redis 的第 15 個資料庫，開始時清空
TEST_REDIS_URL = settings.redis_url.rsplit('/', 1)[0] + '/15'
#: 測試使用 Chroma 的另一個 database（default_tenant 之下）
TEST_CHROMA_DATABASE = 'genai_test'


@pytest.fixture(scope='session')
async def db() -> AsyncIterator[Database]:
    url = make_url(settings.database_url)
    admin = await asyncpg.connect(
        user=url.username, password=url.password, host=url.host, port=url.port, database='postgres'
    )
```

改成：

```python
from app.queues import Queues
from app.rag.engine import RagEngine
from app.rag.store import VectorStore
from app.settings import REPO_ROOT, Settings
from app.worker import Services as WorkerServices
from app.worker import build_workers
from tests.fixtures import BRANDS_DIR

#: 預設值加上環境變數，不讀 .env：開發用的 RAG_MODE=sim、REVIEW_MODE 或之後的 API key 都不會影響測試
BASE_SETTINGS = Settings(_env_file=None)
TEST_DATABASE = 'genai_test'
#: 測試使用 Redis 的第 15 個資料庫，開始時清空
TEST_REDIS_URL = BASE_SETTINGS.redis_url.rsplit('/', 1)[0] + '/15'
#: 測試使用 Chroma 的另一個 database（default_tenant 之下）
TEST_CHROMA_DATABASE = 'genai_test'


@pytest.fixture(scope='session')
async def db() -> AsyncIterator[Database]:
    url = make_url(BASE_SETTINGS.database_url)
    admin = await asyncpg.connect(
        user=url.username, password=url.password, host=url.host, port=url.port, database='postgres'
    )
```

找到（3／5）：

```python
@pytest.fixture(scope='session')
async def chroma_store() -> AsyncIterator[VectorStore]:
    """建立 Chroma 的 genai_test database（已經有時沿用），並刪除上次留下的 collection。"""
    async with httpx.AsyncClient(base_url=settings.chroma_url) as http:
        res = await http.post('/api/v2/tenants/default_tenant/databases', json={'name': TEST_CHROMA_DATABASE})
        # 409：database 已經存在
        if res.status_code != 409:
            res.raise_for_status()
    store = VectorStore(settings.chroma_url, database=TEST_CHROMA_DATABASE)
    for brand_id in await store.brands():
        await store.drop(brand_id)
    yield store
```

改成：

```python
@pytest.fixture(scope='session')
async def chroma_store() -> AsyncIterator[VectorStore]:
    """建立 Chroma 的 genai_test database（已經有時沿用），並刪除上次留下的 collection。"""
    async with httpx.AsyncClient(base_url=BASE_SETTINGS.chroma_url) as http:
        res = await http.post('/api/v2/tenants/default_tenant/databases', json={'name': TEST_CHROMA_DATABASE})
        # 409：database 已經存在
        if res.status_code != 409:
            res.raise_for_status()
    store = VectorStore(BASE_SETTINGS.chroma_url, database=TEST_CHROMA_DATABASE)
    for brand_id in await store.brands():
        await store.drop(brand_id)
    yield store
```

找到（4／5）：

```python
        ports = sim_ports(composer, first_round_fail=True, force_all_fail=False)
        cutouts = CutoutEngine('sim', s.settings.data_dir / 'models', s.redis)
        rag = RagEngine('sim', s.settings.data_dir / 'models', s.redis)
        vectors = VectorStore(settings.chroma_url, database=TEST_CHROMA_DATABASE)
        worker_services = WorkerServices(
            s.db, s.redis, s.store, composer, ports, speed, s.settings, cutouts, rag, vectors
        )
```

改成：

```python
        ports = sim_ports(composer, first_round_fail=True, force_all_fail=False)
        cutouts = CutoutEngine('sim', s.settings.data_dir / 'models', s.redis)
        rag = RagEngine('sim', s.settings.data_dir / 'models', s.redis)
        vectors = VectorStore(BASE_SETTINGS.chroma_url, database=TEST_CHROMA_DATABASE)
        worker_services = WorkerServices(
            s.db, s.redis, s.store, composer, ports, speed, s.settings, cutouts, rag, vectors
        )
```

找到（5／5）：

```python
@pytest.fixture
async def api(db: Database, redis: Redis, composer_url: str, tmp_path: Path) -> AsyncIterator[LiveApi]:
    """data/ 與本機資料夾指向 tmp_path；品牌設定檔使用只含示範品牌的 BRANDS_DIR（不讀 repo 的 brands/）。
    RAG_MODE 固定為 bge：repo 的 .env 設了 RAG_MODE=sim（README 建議的開發方式）時，系統狀態的測試才不會失敗。"""
    await redis.flushdb()
    queues = Queues(TEST_REDIS_URL)
    await queues.connect()
    composer = ComposerClient(composer_url)
    agent = SimAgent(composer, first_round_fail=True, force_all_fail=False)
    test_settings = Settings(
        data_dir=tmp_path / 'data', local_photos_dir=tmp_path / 'local', brands_dir=BRANDS_DIR, rag_mode='bge'
    )
    services = ApiServices(test_settings, db, redis, EventStore(db, redis), queues, composer, agent)
    await services.sync_brands()
```

改成：

```python
@pytest.fixture
async def api(db: Database, redis: Redis, composer_url: str, tmp_path: Path) -> AsyncIterator[LiveApi]:
    """data/ 與本機資料夾指向 tmp_path；品牌設定檔使用只含示範品牌的 BRANDS_DIR（不讀 repo 的 brands/）。
    不讀 .env；RAG_MODE 仍固定為 bge：環境變數設了 RAG_MODE=sim 時，系統狀態的測試才不會失敗。"""
    await redis.flushdb()
    queues = Queues(TEST_REDIS_URL)
    await queues.connect()
    composer = ComposerClient(composer_url)
    agent = SimAgent(composer, first_round_fail=True, force_all_fail=False)
    test_settings = Settings(
        _env_file=None,
        data_dir=tmp_path / 'data',
        local_photos_dir=tmp_path / 'local',
        brands_dir=BRANDS_DIR,
        rag_mode='bge',
    )
    services = ApiServices(test_settings, db, redis, EventStore(db, redis), queues, composer, agent)
    await services.sync_brands()
```

- [ ] **Step 3: 修改 `backend/tests/test_api_catalog.py`**

找到：

```python


def test_files_stay_inside_their_folders(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / 'data', local_photos_dir=tmp_path / 'local', brands_dir=tmp_path / 'brands')
    files = ['secret.png', 'data/uploads/a.png', 'local/b.jpg', 'brands/assets/logo.svg', 'brands/selune.yaml']
    for name in files:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
```

改成：

```python


def test_files_stay_inside_their_folders(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None, data_dir=tmp_path / 'data', local_photos_dir=tmp_path / 'local', brands_dir=tmp_path / 'brands'
    )
    files = ['secret.png', 'data/uploads/a.png', 'local/b.jpg', 'brands/assets/logo.svg', 'brands/selune.yaml']
    for name in files:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: 修改 `backend/tests/test_worker.py`**

找到（1／2）：

```python
    ports = sim_ports(composer, first_round_fail=True, force_all_fail=False)
    async with db.session() as s:
        await catalog.sync_brands(s, load_brands(BRANDS_DIR)[0], NOW)
    settings = Settings(data_dir=tmp_path / 'data', local_photos_dir=tmp_path / 'local', brands_dir=BRANDS_DIR)
    cutouts = CutoutEngine('sim', tmp_path / 'models', redis)
    rag = RagEngine('sim', tmp_path / 'models', redis)
    vectors = VectorStore(settings.chroma_url, database=TEST_CHROMA_DATABASE)
```

改成：

```python
    ports = sim_ports(composer, first_round_fail=True, force_all_fail=False)
    async with db.session() as s:
        await catalog.sync_brands(s, load_brands(BRANDS_DIR)[0], NOW)
    settings = Settings(
        _env_file=None, data_dir=tmp_path / 'data', local_photos_dir=tmp_path / 'local', brands_dir=BRANDS_DIR
    )
    cutouts = CutoutEngine('sim', tmp_path / 'models', redis)
    rag = RagEngine('sim', tmp_path / 'models', redis)
    vectors = VectorStore(settings.chroma_url, database=TEST_CHROMA_DATABASE)
```

找到（2／2）：

```python
async def test_build_services_picks_the_retriever_by_rag_mode(
    mode: RagMode, retriever: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr('app.worker.settings', Settings(brands_dir=BRANDS_DIR, rag_mode=mode))
    built = build_services()
    try:
        assert isinstance(built.ports.retriever, retriever)
```

改成：

```python
async def test_build_services_picks_the_retriever_by_rag_mode(
    mode: RagMode, retriever: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr('app.worker.settings', Settings(_env_file=None, brands_dir=BRANDS_DIR, rag_mode=mode))
    built = build_services()
    try:
        assert isinstance(built.ports.retriever, retriever)
```

- [ ] **Step 5: 修改 `backend/tests/test_cutout_model.py`**

找到：

```python

from app.cutout.models import MODELS
from app.cutout.segmenter import OnnxSegmenter
from app.settings import settings

MODEL = MODELS.get(settings.cutout_model, MODELS['birefnet-general'])
PATH = settings.models_dir / MODEL.filename
PHOTO = os.environ.get('CUTOUT_TEST_PHOTO')

pytestmark = [
```

改成：

```python

from app.cutout.models import MODELS
from app.cutout.segmenter import OnnxSegmenter
from app.settings import Settings

#: 不讀 .env（測試一律如此）；要測另一個模型時以環境變數指定，例如 CUTOUT_MODEL=birefnet-general-lite
SETTINGS = Settings(_env_file=None)
MODEL = MODELS.get(SETTINGS.cutout_model, MODELS['birefnet-general'])
PATH = SETTINGS.models_dir / MODEL.filename
PHOTO = os.environ.get('CUTOUT_TEST_PHOTO')

pytestmark = [
```

- [ ] **Step 6: 修改 `backend/tests/test_rag_model.py`**

找到（1／2）：

```python
from app.rag.chunking import EMBED_DIMS
from app.rag.encoder import OnnxEncoder
from app.rag.models import MODELS
from app.settings import settings

QUERY = 'SÉLUNE｜玻尿酸修護精華｜秋季保濕主打｜長效保濕'
#: 品牌色彩、保濕合規、咖啡產地（與查詢無關）、秋季主視覺
```

改成：

```python
from app.rag.chunking import EMBED_DIMS
from app.rag.encoder import OnnxEncoder
from app.rag.models import MODELS
from app.settings import Settings

QUERY = 'SÉLUNE｜玻尿酸修護精華｜秋季保濕主打｜長效保濕'
#: 品牌色彩、保濕合規、咖啡產地（與查詢無關）、秋季主視覺
```

找到（2／2）：

```python
    '秋季檔期主視覺以暖色調與柔和光線呈現。',
]
COFFEE = 2

pytestmark = [
    pytest.mark.model,
    pytest.mark.skipif(
        not all((settings.models_dir / m.filename).is_file() for m in MODELS), reason='需要 models/ 的 RAG 模型檔'
    ),
]


@pytest.fixture(scope='module')
def encoder() -> OnnxEncoder:
    return OnnxEncoder(settings.models_dir)


def test_embeddings_are_normalized_1024_dims_and_repeatable(encoder: OnnxEncoder) -> None:
```

改成：

```python
    '秋季檔期主視覺以暖色調與柔和光線呈現。',
]
COFFEE = 2
#: 不讀 .env（測試一律如此）；模型資料夾可用環境變數 MODELS_DIR 指定
SETTINGS = Settings(_env_file=None)

pytestmark = [
    pytest.mark.model,
    pytest.mark.skipif(
        not all((SETTINGS.models_dir / m.filename).is_file() for m in MODELS), reason='需要 models/ 的 RAG 模型檔'
    ),
]


@pytest.fixture(scope='module')
def encoder() -> OnnxEncoder:
    return OnnxEncoder(SETTINGS.models_dir)


def test_embeddings_are_normalized_1024_dims_and_repeatable(encoder: OnnxEncoder) -> None:
```

- [ ] **Step 7: 確認全部通過，也不受 `.env` 影響**

先在沒有 `.env` 時執行一次；再放回 Step 1 的暫時 `.env` 執行一次（也試 `REVIEW_MODE=composer`），最後刪除 `.env`。

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected：三次都沒有錯誤，都是 272 passed、3 skipped（沒有模型檔時略過真模型測試）。

- [ ] **Step 8: Commit**

```bash
git add \
  backend/tests/conftest.py \
  backend/tests/test_api_catalog.py \
  backend/tests/test_cutout_model.py \
  backend/tests/test_rag_model.py \
  backend/tests/test_worker.py
git commit -m "test: keep the backend tests away from the repo .env" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9：審查面板切換審查用海報，系統狀態顯示 `REVIEW_MODE`

**Files:**
- Modify:
  - 前端：`web/src/components/agent/review-panel.tsx`、`web/src/components/poster/check-list.tsx`、`web/src/lib/review/rules.ts`
  - 後端：`backend/app/adapters/composer.py`、`backend/app/api/catalog.py`
- Test: `web/src/lib/review/rules.test.ts`、`web/e2e/studio.spec.ts`、`backend/tests/test_api_catalog.py`

**Interfaces:**
- Consumes：Task 6 的 `Candidate.reviewImage`、Task 5 的 `/health` 字型清單。
- Produces：
  - `web/src/lib/review/rules.ts`：`measuredPrimaryOf(check: ReviewCheck): string | null`，從 `color_delta` 的說明文字讀回 hex（「偵測主色」標籤改為共用常數）。
  - 審查面板：
    - 候選有 `reviewImage` 時，顯示「預覽／審查用海報」切換（單選 ToggleGroup，角色為 `radiogroup`），預設為預覽；
    - 審查用海報以畫布尺寸顯示，框線標示照常疊加。
  - 檢查清單：`color_delta` 旁顯示量到的主色色塊（完整清單才顯示）。
  - `ComposerClient.health() -> ComposerHealth | None`（`ComposerHealth(fonts)`）。
  - 系統狀態的 composer 元件：
    - 名稱為「composer（排版、繪製與規則審查）」；
    - 說明為 `REVIEW_MODE=composer・字型：…（網址）`；
    - `REVIEW_MODE=sim` 時為「模擬」；沒有回報字型時為「異常」。

- [ ] **Step 1: 修改 `web/src/lib/review/rules.test.ts`（先寫測試）**

找到（1／2）：

```ts
import { SELUNE, MISTY_ISLE } from '@/lib/api/mock/data';
import { makeSpec } from '@/test/fixtures';
import {
  bannedWordHits, findBannedWords, hasClaim, NO_PRIMARY_MESSAGE, ragRefFor, runRuleChecks, scoreChecks,
} from './rules';

const byId = (checks: ReviewCheck[], id: ReviewCheck['id']) => checks.find((c) => c.id === id)!;
```

改成：

```ts
import { SELUNE, MISTY_ISLE } from '@/lib/api/mock/data';
import { makeSpec } from '@/test/fixtures';
import {
  bannedWordHits, findBannedWords, hasClaim, measuredPrimaryOf, NO_PRIMARY_MESSAGE, ragRefFor, runRuleChecks, scoreChecks,
} from './rules';

const byId = (checks: ReviewCheck[], id: ReviewCheck['id']) => checks.find((c) => c.id === id)!;
```

找到（2／2）：

```ts
    expect(c).toMatchObject({ status: 'pass', value: 'ΔE 0.3 · 偵測主色 #B76F7A' });
  });

  it('fails logo clearance when the logo is pushed into the headline', () => {
    const spec = makeSpec();
    const logo = spec.layout.find((b) => b.id === 'logo')!;
```

改成：

```ts
    expect(c).toMatchObject({ status: 'pass', value: 'ΔE 0.3 · 偵測主色 #B76F7A' });
  });

  it('measuredPrimaryOf reads the measured primary back from the colour check, for the swatch', () => {
    const checks = runRuleChecks({ brand: SELUNE, spec: makeSpec(), measuredPrimary: '#e0458a' });
    expect(measuredPrimaryOf(byId(checks, 'color_delta'))).toBe('#E0458A');
    expect(byId(checks, 'color_delta').status).toBe('fail');
    // 量不到主色、其他檢查的說明，都沒有色塊
    const none = runRuleChecks({ brand: SELUNE, spec: makeSpec(), measuredPrimary: null });
    expect(measuredPrimaryOf(byId(none, 'color_delta'))).toBeNull();
    expect(checks.filter((c) => c.id !== 'color_delta').map(measuredPrimaryOf)).toEqual(Array(checks.length - 1).fill(null));
    expect(measuredPrimaryOf({ id: 'banned_words', value: '偵測主色 #B76F7A' })).toBeNull();
    expect(measuredPrimaryOf({ id: 'color_delta', value: 'ΔE 2 · 偵測主色 #B76F7' })).toBeNull();
  });

  it('fails logo clearance when the logo is pushed into the headline', () => {
    const spec = makeSpec();
    const logo = spec.layout.find((b) => b.id === 'logo')!;
```

- [ ] **Step 2: 修改 `backend/tests/test_api_catalog.py`（先寫測試）**

找到（1／4）：

```python
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from pypdf import PdfWriter
from saq.job import Status

from app.api import catalog as catalog_api
from app.brands import BrandLoadError
from app.contract import ProductCutout
```

改成：

```python
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image
from pypdf import PdfWriter
from saq.job import Status

from app.adapters.composer import ComposerClient, ComposerHealth
from app.api import catalog as catalog_api
from app.brands import BrandLoadError
from app.contract import ProductCutout
```

找到（2／4）：

```python
    return {c['id']: c for c in (await api.http.get('/api/status')).json()['components']}


async def test_status_reports_each_component(api: LiveApi) -> None:
    status = await status_of(api)
    assert [(k, c['status']) for k, c in status.items()] == [
```

改成：

```python
    return {c['id']: c for c in (await api.http.get('/api/status')).json()['components']}


COMPOSER_LABEL = 'composer（排版、繪製與規則審查）'


async def test_status_reports_each_component(api: LiveApi) -> None:
    status = await status_of(api)
    assert [(k, c['status']) for k, c in status.items()] == [
```

找到（3／4）：

```python
        ('cutout', 'error'),
    ]
    assert status['brands']['detail'] == '已載入 2 個品牌'
    # Chroma 正常時顯示網址；worker 還沒啟動，RAG 模型的狀態還沒有回報
    chroma_url = api.services.settings.chroma_url
    assert status['chroma'] == {'id': 'chroma', 'label': '向量庫（Chroma）', 'status': 'ok', 'detail': chroma_url}
```

改成：

```python
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
```

找到（4／4）：

```python
        'status': 'error',
        'detail': '已載入 2 個品牌；略過 broken.yaml：palette.primary：必填',
    }


async def ingest(api: LiveApi, brand_id: str, name: str, data: bytes) -> list[dict[str, Any]]:
```

改成：

```python
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
```

- [ ] **Step 3: 確認測試失敗**

Run（在 `web/`）：`npx vitest run src/lib/review/rules.test.ts`
Expected：1 failed、15 passed：`measuredPrimaryOf is not a function`。

Run（在 `backend/`）：`uv run pytest -q tests/test_api_catalog.py`
Expected：FAIL，收集時出錯：`ImportError: cannot import name 'ComposerHealth' from 'app.adapters.composer'`。

- [ ] **Step 4: 修改 `web/src/lib/review/rules.ts`**

找到（1／2）：

```ts
/** 量測範圍內沒有佔比夠大的彩色時，主色檢查的說明 */
export const NO_PRIMARY_MESSAGE = `未偵測到主色（主色區塊 < ${PRIMARY_MEASURE.minShare * 100}%）`;

export interface RuleContext {
  brand: Brand;
  spec: PromptSpec;
```

改成：

```ts
/** 量測範圍內沒有佔比夠大的彩色時，主色檢查的說明 */
export const NO_PRIMARY_MESSAGE = `未偵測到主色（主色區塊 < ${PRIMARY_MEASURE.minShare * 100}%）`;

/** 主色檢查說明中量到的顏色：`ΔE 0.3 · 偵測主色 #B76F7A`（hex 為大寫） */
const MEASURED_PRIMARY_LABEL = '偵測主色';
const MEASURED_PRIMARY_PATTERN = new RegExp(`${MEASURED_PRIMARY_LABEL} (#[0-9A-F]{6})$`);

/** 主色檢查（color_delta）說明文字裡量到的主色（#RRGGBB）；其他檢查或量不到主色時為 null。審查面板依此畫出色塊。 */
export function measuredPrimaryOf(check: Pick<ReviewCheck, 'id' | 'value'>): string | null {
  return check.id === 'color_delta' ? (MEASURED_PRIMARY_PATTERN.exec(check.value)?.[1] ?? null) : null;
}

export interface RuleContext {
  brand: Brand;
  spec: PromptSpec;
```

找到（2／2）：

```ts
    },
    {
      id: 'color_delta', name: '品牌主色色差', kind: 'rule', rule: `ΔE2000 ≤ ${brand.rules.maxDeltaE}`,
      value: color ? `ΔE ${round1(color.dE)} · 偵測主色 ${color.hex}` : NO_PRIMARY_MESSAGE,
      status: color && color.dE <= brand.rules.maxDeltaE ? 'pass' : 'fail', target: 'canvas', ragRef: ragRefFor(brand, 'color'),
    },
    {
```

改成：

```ts
    },
    {
      id: 'color_delta', name: '品牌主色色差', kind: 'rule', rule: `ΔE2000 ≤ ${brand.rules.maxDeltaE}`,
      value: color ? `ΔE ${round1(color.dE)} · ${MEASURED_PRIMARY_LABEL} ${color.hex}` : NO_PRIMARY_MESSAGE,
      status: color && color.dE <= brand.rules.maxDeltaE ? 'pass' : 'fail', target: 'canvas', ragRef: ragRefFor(brand, 'color'),
    },
    {
```

- [ ] **Step 5: 修改 `web/src/components/poster/check-list.tsx`**

找到（1／3）：

```tsx
import { CircleCheck, CircleX, TriangleAlert } from 'lucide-react';
import type { CheckStatus, ReviewCheck } from '@/types/contract';
import { cn } from '@/lib/utils';

const ICON: Record<CheckStatus, React.ReactNode> = {
```

改成：

```tsx
import { CircleCheck, CircleX, TriangleAlert } from 'lucide-react';
import type { CheckStatus, ReviewCheck } from '@/types/contract';
import { measuredPrimaryOf } from '@/lib/review/rules';
import { cn } from '@/lib/utils';

const ICON: Record<CheckStatus, React.ReactNode> = {
```

找到（2／3）：

```tsx
  fail: <CircleX className="size-4 text-destructive" />,
};

/** 審查項目清單（單張審查細節、文字編輯器的即時檢查共用）；compact 只顯示名稱與結果 */
export function CheckList({ checks, compact = false, className }: { checks: ReviewCheck[]; compact?: boolean; className?: string }) {
  if (compact) {
    return (
```

改成：

```tsx
  fail: <CircleX className="size-4 text-destructive" />,
};

/** 主色檢查說明旁的色塊：量到的主色（偏色時是實際用錯的顏色） */
function PrimarySwatch({ check }: { check: ReviewCheck }) {
  const hex = measuredPrimaryOf(check);
  if (!hex) return null;
  return (
    <span className="inline-block size-3 shrink-0 rounded-sm border" style={{ backgroundColor: hex }} title={`偵測主色 ${hex}`} aria-hidden />
  );
}

/** 審查項目清單（單張審查細節、文字編輯器的即時檢查共用）；compact 只顯示名稱與結果，完整清單在主色檢查旁顯示量到的主色色塊 */
export function CheckList({ checks, compact = false, className }: { checks: ReviewCheck[]; compact?: boolean; className?: string }) {
  if (compact) {
    return (
```

找到（3／3）：

```tsx
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">{c.name}</span>
              <span className="rounded bg-muted px-1.5 text-[10px] font-semibold text-muted-foreground">{c.kind === 'rule' ? '規則' : 'VLM'}</span>
              <span className={cn('ml-auto text-xs', c.status === 'pass' ? 'text-muted-foreground' : c.status === 'warn' ? 'text-warning' : 'text-destructive')}>
                {c.value}
              </span>
            </div>
```

改成：

```tsx
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">{c.name}</span>
              <span className="rounded bg-muted px-1.5 text-[10px] font-semibold text-muted-foreground">{c.kind === 'rule' ? '規則' : 'VLM'}</span>
              <span className={cn('ml-auto inline-flex items-center gap-1.5 text-xs', c.status === 'pass' ? 'text-muted-foreground' : c.status === 'warn' ? 'text-warning' : 'text-destructive')}>
                <PrimarySwatch check={c} />
                {c.value}
              </span>
            </div>
```

- [ ] **Step 6: 修改 `web/src/components/agent/review-panel.tsx`**

找到（1／6）：

```tsx
'use client';

import { useEffect, useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import type { CheckStatus, JobInput, Product, Render } from '@/types/contract';
import { EmptyState } from '@/components/common/empty-state';
```

改成：

```tsx
'use client';

import { useEffect, useState } from 'react';
import Image from 'next/image';
import { ShieldCheck } from 'lucide-react';
import type { CheckStatus, JobInput, Product, Render } from '@/types/contract';
import { EmptyState } from '@/components/common/empty-state';
```

找到（2／6）：

```tsx
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { getApiClient } from '@/lib/api';
import { overlayFor } from '@/lib/agent/inspect';
import { getTemplate } from '@/lib/compose/templates';
```

改成：

```tsx
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { getApiClient } from '@/lib/api';
import { overlayFor } from '@/lib/agent/inspect';
import { getTemplate } from '@/lib/compose/templates';
```

找到（3／6）：

```tsx

const STATUS_COLOR: Record<CheckStatus | 'none', string> = { fail: '#dc2626', warn: '#d97706', pass: '#059669', none: '#64748b' };
const LEGEND: [CheckStatus | 'none', string][] = [['fail', '未通過'], ['warn', '警告'], ['pass', '通過'], ['none', '無檢查']];

/** 海報上疊出版面 BBox，依指向該元素的檢查結果上色 */
function BBoxOverlay({ render }: { render: Render }) {
```

改成：

```tsx

const STATUS_COLOR: Record<CheckStatus | 'none', string> = { fail: '#dc2626', warn: '#d97706', pass: '#059669', none: '#64748b' };
const LEGEND: [CheckStatus | 'none', string][] = [['fail', '未通過'], ['warn', '警告'], ['pass', '通過'], ['none', '無檢查']];

/** 疊圖的底圖：瀏覽器即時繪製的預覽，或 worker 存下的審查用海報（伺服器端繪製，主色依它量測） */
type PosterSource = 'preview' | 'review';
const POSTER_SOURCES: { id: PosterSource; label: string }[] = [
  { id: 'preview', label: '預覽' },
  { id: 'review', label: '審查用海報' },
];

/** 海報上疊出版面 BBox，依指向該元素的檢查結果上色 */
function BBoxOverlay({ render }: { render: Render }) {
```

找到（4／6）：

```tsx
  const reviewed = view.renderIds.map((id) => view.renders[id]).filter((r) => r.score !== null);
  const [picked, setPicked] = useState<string | null>(null);
  const [showBoxes, setShowBoxes] = useState(true);
  const fallback = Object.values(view.bestRenderIds)[0] ?? reviewed.at(-1)?.id ?? null;
  const render = (picked && view.renders[picked]) || (fallback ? view.renders[fallback] : null);
  const brandId = render?.spec.brandId ?? input?.brandId ?? '';
```

改成：

```tsx
  const reviewed = view.renderIds.map((id) => view.renders[id]).filter((r) => r.score !== null);
  const [picked, setPicked] = useState<string | null>(null);
  const [showBoxes, setShowBoxes] = useState(true);
  const [source, setSource] = useState<PosterSource>('preview');
  const fallback = Object.values(view.bestRenderIds)[0] ?? reviewed.at(-1)?.id ?? null;
  const render = (picked && view.renders[picked]) || (fallback ? view.renders[fallback] : null);
  const brandId = render?.spec.brandId ?? input?.brandId ?? '';
```

找到（5／6）：

```tsx
    return <EmptyState icon={ShieldCheck} title="尚未審查">候選完成合規審查後，這裡會顯示 BBox 疊圖與每一項檢查。</EmptyState>;
  }
  const best = Object.values(view.bestRenderIds).includes(render.id);

  return (
    <div className="space-y-4">
```

改成：

```tsx
    return <EmptyState icon={ShieldCheck} title="尚未審查">候選完成合規審查後，這裡會顯示 BBox 疊圖與每一項檢查。</EmptyState>;
  }
  const best = Object.values(view.bestRenderIds).includes(render.id);
  // 模擬模式（REVIEW_MODE=sim、mock）沒有審查用海報：不顯示切換，一律用預覽
  const reviewImage = render.reviewImage;
  const showReview = source === 'review' && reviewImage !== null;
  const { width: W, height: H } = render.spec.canvas;

  return (
    <div className="space-y-4">
```

找到（6／6）：

```tsx
            <CardDescription>LLM 輸出的版面座標；顏色依指向該元素的檢查結果，外框代表整張圖的檢查（主色色差）。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="relative overflow-hidden rounded-lg border">
              <PosterCanvas render={render} copy={render.spec.copy} product={product} brand={brand} pixelWidth={720} />
              {showBoxes && <BBoxOverlay render={render} />}
            </div>
            <div className="flex flex-wrap items-center gap-3 text-xs">
```

改成：

```tsx
            <CardDescription>LLM 輸出的版面座標；顏色依指向該元素的檢查結果，外框代表整張圖的檢查（主色色差）。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {reviewImage && (
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <ToggleGroup
                  type="single"
                  variant="outline"
                  size="sm"
                  value={showReview ? 'review' : 'preview'}
                  onValueChange={(v) => v && setSource(v as PosterSource)}
                  aria-label="預覽／審查用海報"
                >
                  {POSTER_SOURCES.map((s) => (
                    <ToggleGroupItem key={s.id} value={s.id} className="px-3">{s.label}</ToggleGroupItem>
                  ))}
                </ToggleGroup>
                <p className="text-xs text-muted-foreground">
                  {showReview ? '伺服器端繪製並存檔的 PNG，主色色差依這張圖的像素量測。' : '瀏覽器即時繪製的預覽。'}
                </p>
              </div>
            )}
            <div className="relative overflow-hidden rounded-lg border">
              {showReview ? (
                <Image
                  src={reviewImage}
                  alt={`${render.spec.copy.headline.join(' ')} 審查用海報`}
                  width={W}
                  height={H}
                  unoptimized
                  className="block h-auto w-full bg-muted"
                />
              ) : (
                <PosterCanvas render={render} copy={render.spec.copy} product={product} brand={brand} pixelWidth={720} />
              )}
              {showBoxes && <BBoxOverlay render={render} />}
            </div>
            <div className="flex flex-wrap items-center gap-3 text-xs">
```

- [ ] **Step 7: 修改 `web/e2e/studio.spec.ts`**

mock 模式沒有審查用海報，切換按鈕應該隱藏。

找到（1／2）：

```ts
import { expect, test } from '@playwright/test';
import JSZip from 'jszip';

test('一句話需求 → 生成 → 第一輪失敗並重試 → 選圖 → 改價格 → 匯出 zip → Agent 透視看重試 diff', async ({ page }) => {
  await page.goto('/studio');

  // Demo 控制台：4× 播放（預設強制首輪失敗）
```

改成：

```ts
import { expect, test } from '@playwright/test';
import JSZip from 'jszip';

test('一句話需求 → 生成 → 第一輪失敗並重試 → 選圖 → 改價格 → 匯出 zip → Agent 透視看重試 diff 與合規報告', async ({ page }) => {
  await page.goto('/studio');

  // Demo 控制台：4× 播放（預設強制首輪失敗）
```

找到（2／2）：

```ts
  await expect(diff).toContainText('#E0458A');
  await expect(diff).toContainText('#B76E79');
  await expect(page.getByText('第 1 輪 → 第 2 輪・IG 貼文')).toBeVisible();
});
```

改成：

```ts
  await expect(diff).toContainText('#E0458A');
  await expect(diff).toContainText('#B76E79');
  await expect(page.getByText('第 1 輪 → 第 2 輪・IG 貼文')).toBeVisible();

  // 合規報告：mock 沒有審查用海報，不顯示「預覽／審查用海報」切換；主色檢查旁有量到的主色色塊
  await page.getByRole('tab', { name: '合規報告' }).click();
  await expect(page.getByText('BBox 疊圖')).toBeVisible();
  await expect(page.getByRole('radiogroup', { name: '預覽／審查用海報' })).toHaveCount(0);
  await expect(page.locator('[title^="偵測主色 #"]')).toBeVisible();
});
```

- [ ] **Step 8: 修改 `backend/app/adapters/composer.py`**

找到（1／2）：

```python
    primary_share: float


def _error_message(res: httpx.Response) -> str:
    """composer 的錯誤回應是 { error: { code, message } }；不是時（例如經過代理）改用狀態碼與內文開頭。"""
    try:
```

改成：

```python
    primary_share: float


@dataclass(frozen=True)
class ComposerHealth:
    #: composer 啟動時註冊的海報字型（字型家族名稱）；舊版 composer 沒有回報時為空
    fonts: list[str]


def _error_message(res: httpx.Response) -> str:
    """composer 的錯誤回應是 { error: { code, message } }；不是時（例如經過代理）改用狀態碼與內文開頭。"""
    try:
```

找到（2／2）：

```python
    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        return (await self._send(path, body)).json()

    async def health(self) -> bool:
        try:
            return (await self._client.get('/health')).status_code == 200
        except httpx.HTTPError:
            return False

    async def layout(self, template_id: TemplateId) -> list[LayoutBox]:
        return [LayoutBox.model_validate(b) for b in await self._post('/layout', {'templateId': template_id})]
```

改成：

```python
    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        return (await self._send(path, body)).json()

    async def health(self) -> ComposerHealth | None:
        """GET /health：{ status, fonts }。連不上或不是 200 時為 None。"""
        try:
            res = await self._client.get('/health')
        except httpx.HTTPError:
            return None
        if res.status_code != 200:
            return None
        try:
            fonts = res.json().get('fonts')
        except (ValueError, AttributeError):
            fonts = None
        return ComposerHealth(fonts=[str(f) for f in fonts] if isinstance(fonts, list) else [])

    async def layout(self, template_id: TemplateId) -> list[LayoutBox]:
        return [LayoutBox.model_validate(b) for b in await self._post('/layout', {'templateId': template_id})]
```

- [ ] **Step 9: 修改 `backend/app/api/catalog.py`**

找到（1／2）：

```python
    return f'{len(info["workers"])} 個 worker；排隊 {info["queued"]}、執行中 {info["active"]}'


async def _composer(services: ApiServices) -> str:
    if not await services.composer.health():
        raise Unavailable(f'連不上 composer（{services.composer.base_url}）')
    return services.composer.base_url


async def _brands(services: ApiServices) -> str:
```

改成：

```python
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


async def _brands(services: ApiServices) -> str:
```

找到（2／2）：

```python
        _probe('db', 'PostgreSQL', _db(services)),
        _probe('redis', 'Redis（佇列與事件推送）', _redis(services)),
        _probe('worker', 'worker（SAQ）', _workers(services)),
        _probe('composer', 'composer（排版與模擬邏輯）', _composer(services)),
        _probe('brands', '品牌設定檔', _brands(services)),
        _probe('chroma', '向量庫（Chroma）', _chroma(services)),
        _probe('rag', 'RAG 模型（BGE-M3＋Reranker）', _rag_model(services)),
```

改成：

```python
        _probe('db', 'PostgreSQL', _db(services)),
        _probe('redis', 'Redis（佇列與事件推送）', _redis(services)),
        _probe('worker', 'worker（SAQ）', _workers(services)),
        _probe('composer', 'composer（排版、繪製與規則審查）', _composer(services)),
        _probe('brands', '品牌設定檔', _brands(services)),
        _probe('chroma', '向量庫（Chroma）', _chroma(services)),
        _probe('rag', 'RAG 模型（BGE-M3＋Reranker）', _rag_model(services)),
```

- [ ] **Step 10: 確認全部通過**

Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint && npm run build && npm run e2e`
Expected：51 個測試檔、424 個測試通過；建置成功；mock E2E 5 passed。

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected：沒有錯誤；274 passed、3 skipped（沒有模型檔時略過真模型測試）。

- [ ] **Step 11: Commit**

```bash
git add \
  backend/app/adapters/composer.py \
  backend/app/api/catalog.py \
  backend/tests/test_api_catalog.py \
  web/e2e/studio.spec.ts \
  web/src/components/agent/review-panel.tsx \
  web/src/components/poster/check-list.tsx \
  web/src/lib/review/rules.test.ts \
  web/src/lib/review/rules.ts
git commit -m "feat: show the review poster and the measured primary, and REVIEW_MODE in the status" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10：Compose 啟用伺服器端審查，live E2E 驗證審查用海報

**Files:**
- Modify: `docker-compose.yml`、`docker-compose.e2e.yml`、`web/e2e-live/live.spec.ts`

**Interfaces:**
- Produces：
  - api 與 worker 共用的環境加上 `REVIEW_MODE: ${REVIEW_MODE:-composer}`；
  - e2e 固定為 `REVIEW_MODE: composer`；
  - live E2E 斷言：
    - 4 個 `review.completed` 的 `image` 網址；
    - 切換按鈕；
    - 審查用海報的原尺寸（1440 像素寬）；
    - PNG 回應；
    - 系統狀態列出字型。

- [ ] **Step 1: 修改 `web/e2e-live/live.spec.ts`（先寫測試）**

找到（1／2）：

```ts
const roundOne = (page: Page) => page.getByText('第 1 輪', { exact: true }).first();
const editor = (page: Page) => page.getByText('文字編輯器', { exact: true });

test('一句話需求 → 後端生成（第一輪失敗、重試後通過）→ 匯出並寫入歷史 → Agent 透視與儀表板', async ({ page }) => {
  const jobId = await startJob(page);
  await expect(page.getByText('第 1 輪未通過審查，Query Rewriting 後重試')).toBeVisible();
  await expect(editor(page)).toBeVisible();
```

改成：

```ts
const roundOne = (page: Page) => page.getByText('第 1 輪', { exact: true }).first();
const editor = (page: Page) => page.getByText('文字編輯器', { exact: true });

test('一句話需求 → 後端生成（第一輪失敗、重試後通過）→ 匯出並寫入歷史 → Agent 透視（審查用海報）與儀表板', async ({ page }) => {
  const jobId = await startJob(page);
  await expect(page.getByText('第 1 輪未通過審查，Query Rewriting 後重試')).toBeVisible();
  await expect(editor(page)).toBeVisible();
```

找到（2／2）：

```ts
  const { events } = await job(page, jobId);
  await page.goto(`/agent?job=${jobId}`);
  await expect(page.getByText(`${events.length} 則事件`)).toBeVisible();
  await page.goto('/dashboard');
  await expect(page.getByText(jobId)).toBeVisible();
});
```

改成：

```ts
  const { events } = await job(page, jobId);
  await page.goto(`/agent?job=${jobId}`);
  await expect(page.getByText(`${events.length} 則事件`)).toBeVisible();

  // REVIEW_MODE=composer：兩輪各 2 張候選都有伺服器端繪製的審查用海報（data/jobs/{jobId}/{renderId}.png）
  const images: (string | null)[] = events
    .filter((e: { type: string }) => e.type === 'review.completed')
    .map((e: { image: string | null }) => e.image);
  expect([...images].sort()).toEqual(
    ['r1_ig-post_v0', 'r1_ig-post_v1', 'r2_ig-post_v0', 'r2_ig-post_v1'].map((id) => `/files/jobs/${jobId}/${jobId}_${id}.png`),
  );
  await page.getByRole('tab', { name: '合規報告' }).click();
  const source = page.getByRole('radiogroup', { name: '預覽／審查用海報' });
  await expect(source).toBeVisible();
  await source.getByRole('radio', { name: '審查用海報' }).click();
  const poster = page.locator('img[src^="/files/jobs/"]');
  await expect.poll(() => poster.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBe(1440);
  const png = await page.request.get((await poster.getAttribute('src'))!);
  expect(png.headers()['content-type']).toBe('image/png');
  expect([...(await png.body()).subarray(0, 8)]).toEqual([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  // 系統狀態：composer 在 Docker 內載入了海報字型
  const status: { components: { id: string; detail: string }[] } = await (await page.request.get('/api/status')).json();
  expect(status.components.find((c) => c.id === 'composer')!.detail).toMatch(/^REVIEW_MODE=composer・字型：Noto Sans TC、Noto Serif TC/);
  await page.goto('/dashboard');
  await expect(page.getByText(jobId)).toBeVisible();
});
```

- [ ] **Step 2: 修改 `docker-compose.yml`**

找到（1／2）：

```yaml
    DATA_DIR: /app/data
    LOCAL_PHOTOS_DIR: /app/assets/products
    MODELS_DIR: /app/models
  volumes:
    - ./brands:/app/brands:ro
    - ./assets/products:/app/assets/products:ro
```

改成：

```yaml
    DATA_DIR: /app/data
    LOCAL_PHOTOS_DIR: /app/assets/products
    MODELS_DIR: /app/models
    # 審查：composer（預設，composer 繪製審查用海報存到 data/jobs/，量出主色後審查）或 sim（不畫圖，模擬審查）。
    # 可在 .env 或環境變數設定 REVIEW_MODE；api（系統狀態）與 worker 一定讀到同一個值
    REVIEW_MODE: ${REVIEW_MODE:-composer}
  volumes:
    - ./brands:/app/brands:ro
    - ./assets/products:/app/assets/products:ro
```

找到（2／2）：

```yaml
      retries: 30
    restart: unless-stopped

  # 版型與模擬邏輯（直接執行 web/src/lib 的 TypeScript）；只給 api 與 worker 使用，不對外開放
  composer:
    build:
      context: ./web
```

改成：

```yaml
      retries: 30
    restart: unless-stopped

  # 版型、審查用海報的繪製、規則審查與模擬邏輯（直接執行 web/src/lib 的 TypeScript）；只給 api 與 worker 使用，不對外開放。
  # 海報字型（Noto Sans／Serif TC，約 29 MB）在建置時下載並核對 SHA-256（web/Dockerfile 的 fonts 階段），不需要掛載資料夾
  composer:
    build:
      context: ./web
```

- [ ] **Step 3: 修改 `docker-compose.e2e.yml`**

找到：

```yaml
    CUTOUT_MODEL: sim
    # 模擬檢索：不下載約 1.2 GB 的 RAG 模型，也不寫入 Chroma
    RAG_MODE: sim
  volumes: !override
    - ./brands:/app/brands:ro
    - e2e-photos:/app/assets/products:ro
```

改成：

```yaml
    CUTOUT_MODEL: sim
    # 模擬檢索：不下載約 1.2 GB 的 RAG 模型，也不寫入 Chroma
    RAG_MODE: sim
    # 真正的審查：composer 繪製審查用海報（不受 .env 的 REVIEW_MODE 影響）
    REVIEW_MODE: composer
  volumes: !override
    - ./brands:/app/brands:ro
    - e2e-photos:/app/assets/products:ro
```

- [ ] **Step 4: 檢查 compose 設定**

Run（在 repo 根目錄）：
- `docker compose config --quiet`
- `docker compose -f docker-compose.yml -f docker-compose.e2e.yml config --quiet`

Expected：沒有輸出。

- [ ] **Step 5: 執行 live E2E**

這個指令以獨立專案 `genai-agent-e2e` 啟動整套服務（網頁在 3200），結束時自動清除。

Run（在 `web/`）：`npm run e2e:live`
Expected：6 passed；結束後沒有留下 `genai-agent-e2e` 的容器。

- [ ] **Step 6: Commit**

```bash
git add \
  docker-compose.e2e.yml \
  docker-compose.yml \
  web/e2e-live/live.spec.ts
git commit -m "feat: run the composer review in Compose and check it in the live E2E" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11：文件

**Files:**
- Modify: `README.md`、`backend/README.md`、`web/README.md`、`.env.example`

說明以下幾點：
- `REVIEW_MODE`；
- 字型：`npm run fonts`、Docker 建置時下載、OFL 授權、`POSTER_FONTS_DIR`；
- 審查用海報與存放位置；
- 主色檢查的做法與限制（背景色系檢查留到 Plan 7）；
- 測試需要字型、後端測試不讀 `.env`；
- 本機執行 worker 時需要一個有字型的 composer。

- [ ] **Step 1: 修改 `README.md`**

找到（1／6）：

```markdown
- **前端**：Next.js 16（靜態輸出）、TypeScript、Tailwind CSS v4、shadcn/ui、Zustand：[web/README.md](web/README.md)
- **後端**：FastAPI、SAQ worker、PostgreSQL（SQLAlchemy、Alembic）、Redis：[backend/README.md](backend/README.md)
- **RAG**：Chroma 向量庫、BGE-M3 向量化與 bge-reranker-v2-m3 Rerank（ONNX Runtime，CPU）：[RAG 設計規格](docs/superpowers/specs/2026-10-21-plan5-rag-design.md)
- **composer**：Node 服務，直接執行前端的 TypeScript（版型與模擬邏輯），讓前後端只有一份實作
- **規格**：[第二階段設計規格](docs/superpowers/specs/2026-10-07-phase2-backend-design.md)；各計畫在 [docs/superpowers/plans/](docs/superpowers/plans/)

## 進度
```

改成：

```markdown
- **前端**：Next.js 16（靜態輸出）、TypeScript、Tailwind CSS v4、shadcn/ui、Zustand：[web/README.md](web/README.md)
- **後端**：FastAPI、SAQ worker、PostgreSQL（SQLAlchemy、Alembic）、Redis：[backend/README.md](backend/README.md)
- **RAG**：Chroma 向量庫、BGE-M3 向量化與 bge-reranker-v2-m3 Rerank（ONNX Runtime，CPU）：[RAG 設計規格](docs/superpowers/specs/2026-10-21-plan5-rag-design.md)
- **composer**：Node 服務，直接執行前端的 TypeScript（版型、審查用海報的繪製、規則審查與模擬邏輯），讓前後端只有一份實作；以 `@napi-rs/canvas` 在伺服器端畫出與瀏覽器相同的海報：[伺服器端排版設計規格](docs/superpowers/specs/2026-10-22-plan6a-server-compose-design.md)
- **規格**：[第二階段設計規格](docs/superpowers/specs/2026-10-07-phase2-backend-design.md)；各計畫在 [docs/superpowers/plans/](docs/superpowers/plans/)

## 進度
```

找到（2／6）：

```markdown
| Plan 1–3 | 前端與瀏覽器內模擬（mock 模式）、Agent 透視、成效儀表板 | 完成 |
| Plan 4 | 後端骨架與即時串流：全部 API、WebSocket、worker、Docker | 完成（外部服務為模擬版） |
| Plan 5 | RAG：Chroma、BGE-M3 與 Reranker、PDF 手冊上傳、歷史回寫 | 完成（Agent、生圖與審查仍為模擬版） |
| Plan 6 | Gemini Agent、伺服器端排版與 VLM 審查 | |
| Plan 7 | ComfyUI 生圖 | |
| Plan 8 | 作品集 Demo（Cloudflare Pages＋Access） | |
```

改成：

```markdown
| Plan 1–3 | 前端與瀏覽器內模擬（mock 模式）、Agent 透視、成效儀表板 | 完成 |
| Plan 4 | 後端骨架與即時串流：全部 API、WebSocket、worker、Docker | 完成（外部服務為模擬版） |
| Plan 5 | RAG：Chroma、BGE-M3 與 Reranker、PDF 手冊上傳、歷史回寫 | 完成（Agent、生圖與審查仍為模擬版） |
| Plan 6A | 伺服器端排版與規則審查：審查用海報、從像素量測品牌主色 | 完成（Agent、生圖與 VLM 審查仍為模擬版） |
| Plan 6B | Gemini Agent、VLM 審查、用量與成本 | |
| Plan 7 | ComfyUI 生圖 | |
| Plan 8 | 作品集 Demo（Cloudflare Pages＋Access） | |
```

找到（3／6）：

````markdown
瀏覽器 ── 127.0.0.1:3000 ── web（nginx：前端靜態檔；/api、/ws、/files、/docs 轉給 api）
                              │
                            api（FastAPI）── postgres
                              │            └ data/（上傳的商品照；之後的生成圖）
                              │ SAQ 佇列＋事件推送
                            redis
                              │
                            worker（SAQ）── composer（Node：版型、模擬邏輯）
                              │          └ models/（去背與 RAG 的 ONNX 模型）
                            chroma（向量庫，127.0.0.1:8001）
```

- 每則任務事件都在同一個交易中取得序號（`seq`）並寫入資料庫，再經 Redis 推送到 WebSocket；斷線或重新整理後，前端以最後收到的 `seq` 接續。Redis 停止時，WebSocket 改為每秒從資料庫讀取新事件，連線不中斷。
- **RAG**：品牌設定檔、上傳的手冊與選定的海報都切成切塊，存在 PostgreSQL；worker 以 BGE-M3 向量化後寫入 Chroma（每個品牌一個 collection）。任務先向量召回 8 筆、再以 Reranker 重新排序，前 5 筆放進 Prompt。PostgreSQL 為準，Chroma 只是索引：worker 啟動時與每次檢索前都會比對並補齊，Chroma 的資料遺失時會自動重建。
- Gemini 與 ComfyUI 目前是模擬版，行為與 mock 模式的劇本相同（第一輪刻意失誤，Query Rewriting 後通過）。右上角的連線狀態可以展開各服務的狀態，模擬版會標示「模擬」。

## 用 Docker 執行（live 模式）
````

改成：

````markdown
瀏覽器 ── 127.0.0.1:3000 ── web（nginx：前端靜態檔；/api、/ws、/files、/docs 轉給 api）
                              │
                            api（FastAPI）── postgres
                              │            └ data/（上傳的商品照、去背圖、審查用海報；之後的生成圖）
                              │ SAQ 佇列＋事件推送
                            redis
                              │
                            worker（SAQ）── composer（Node：版型、繪製審查用海報、規則審查、模擬邏輯）
                              │          └ models/（去背與 RAG 的 ONNX 模型）
                            chroma（向量庫，127.0.0.1:8001）
```

- 每則任務事件都在同一個交易中取得序號（`seq`）並寫入資料庫，再經 Redis 推送到 WebSocket；斷線或重新整理後，前端以最後收到的 `seq` 接續。Redis 停止時，WebSocket 改為每秒從資料庫讀取新事件，連線不中斷。
- **RAG**：品牌設定檔、上傳的手冊與選定的海報都切成切塊，存在 PostgreSQL；worker 以 BGE-M3 向量化後寫入 Chroma（每個品牌一個 collection）。任務先向量召回 8 筆、再以 Reranker 重新排序，前 5 筆放進 Prompt。PostgreSQL 為準，Chroma 只是索引：worker 啟動時與每次檢索前都會比對並補齊，Chroma 的資料遺失時會自動重建。
- **合規審查**（`REVIEW_MODE=composer`，預設）：排版階段由 composer 在伺服器端畫出每張候選的審查用海報（與瀏覽器使用同一套 `scene.ts` 與 `paint.ts`），worker 存成 `data/jobs/{任務 id}/{候選 id}.png`（每張約 0.3–1 MB，不會自動清理）。審查依這張圖計算：7 項規則加 3 項 VLM，分數不加隨機抖動。VLM 三項在 Plan 6B 之前依內容判斷（誇大用語看禁用詞、遮擋看 Logo 是否與標題重疊、品質一律通過），說明標示「模擬，Plan 6B 改用 Gemini」。任務透視的「合規報告」可以切換「預覽／審查用海報」，兩者疊上相同的 BBox。
- **主色色差**：從審查用海報的像素量出品牌主色，計算與 CI 主色的 ΔE2000。量測範圍是標題、售價、徽章三個區塊（扣掉商品區塊），這些元素一定以主色繪製：取出佔比 2% 以上的色塊，以最接近主色的一個計算色差；超過門檻時，說明文字改為顯示實際用錯的顏色（例如 `#E0458A`），合規報告在旁邊畫出色塊；量不到時判定不通過（「未偵測到主色（主色區塊 < 2%）」）。限制：只檢查排版上的品牌色元素，不檢查背景。程式產生的背景依品牌色繪製，目前沒有問題；Plan 7 換成 AI 生成的照片背景時，再新增「背景色系」檢查（標準不能沿用 ΔE ≤ 5：正確的程式背景量起來也有 24–53）。
- Gemini 與 ComfyUI 目前是模擬版，行為與 mock 模式的劇本相同（第一輪刻意失誤，Query Rewriting 後通過）。右上角的連線狀態可以展開各服務的狀態，模擬版會標示「模擬」；composer 一項顯示目前的 `REVIEW_MODE` 與載入的海報字型。

## 用 Docker 執行（live 模式）
````

找到（4／6）：

```markdown
- 前端：http://127.0.0.1:3000
- API 文件：http://127.0.0.1:3000/docs
- 停止：`docker compose down`（資料保留在 volume；加上 `-v` 會清空資料庫與 `chroma` 向量庫，也會刪除 `models` volume，下次啟動要重新下載約 1 GB 的去背模型與約 1.2 GB 的 RAG 模型）
- 設定：複製 `.env.example` 成 `.env` 後修改（模擬速度、首輪是否刻意失誤、去背模型、RAG 模式等），再 `docker compose up -d`
- 商品照去背：worker 以 BiRefNet（ONNX Runtime）執行，新增商品時自動去背，每張約 13 秒（Docker 實測）。第一次啟動時下載模型（約 1 GB，存在 `models` volume），點開右上角的系統狀態，可看到模型是下載中、載入中或已載入。去背時 worker 約使用 8 GB 記憶體（Docker 實測尖峰約 7.6 GiB；平常約 2 GB）。兩個模型的 Docker 記憶體上限都要設到約 10 GB 以上（Docker Desktop 的 Settings → Resources，WSL2 則改 `.wslconfig`）。`CUTOUT_MODEL=birefnet-general-lite` 較快、下載量較小（約 224 MB），但尖峰只低約 0.75 GB（本機實測 5.75 GB 對 6.50 GB），改用它解決不了記憶體不足；16 GB 的電腦只用去背時請把上限調到約 10 GB（同時使用 RAG 見下面的「RAG 的記憶體」），WSL2 預設是一半的記憶體（16 GB 的電腦是 8 GB），不夠用。
- RAG（`RAG_MODE=bge`，預設）：worker 第一次啟動時下載 BGE-M3、bge-reranker-v2-m3 與共用的 tokenizer（int8 ONNX，合計約 1.2 GB，存在 `models` volume），核對後先不載入：worker 啟動時的同步發現索引有差異（例如第一次啟動或 Chroma 重建）時就會載入；沒有差異時，第一次檢索才載入。載入後常駐。系統狀態的「RAG 模型」依序顯示下載中、已就緒（第一次檢索時載入）、載入中、已載入。下載或載入期間送出的任務會在「檢索」階段等候。
- RAG 的記憶體：模型載入後 worker 約再多用 1.7 GB（Docker 實測 1.75 GB；沒有載入時約 0.1 GB，為去背用模擬版時的實測）。與去背的尖峰相加約 10 GB，Docker 的記憶體上限請比上面的建議再多留約 2 GB（例如 12 GB）。16 GB 的電腦同時使用去背與 RAG 時，Docker 上限請設約 12 GB；不夠時改用 `RAG_MODE=sim`，也就是模擬檢索（不下載模型、不寫入 Chroma）。
```

改成：

```markdown
- 前端：http://127.0.0.1:3000
- API 文件：http://127.0.0.1:3000/docs
- 停止：`docker compose down`（資料保留在 volume；加上 `-v` 會清空資料庫與 `chroma` 向量庫，也會刪除 `models` volume，下次啟動要重新下載約 1 GB 的去背模型與約 1.2 GB 的 RAG 模型）
- 設定：複製 `.env.example` 成 `.env` 後修改（模擬速度、首輪是否刻意失誤、去背模型、RAG 模式、審查模式等），再 `docker compose up -d`
- 海報字型：建置 composer 時從 GitHub 的 `google/fonts`（固定 commit）下載 Noto Sans TC 與 Noto Serif TC 的可變字重 TTF（約 29 MB）和兩份 OFL 1.1 授權文字，核對 SHA-256 後放在映像檔的 `/usr/local/share/poster-fonts`（`POSTER_FONTS_DIR`）。網址與 SHA-256 和 `web/composer/fonts.lock.json` 相同，不需要掛載資料夾。建置時要能連到 raw.githubusercontent.com。
- 審查模式：`REVIEW_MODE=composer`（預設）繪製審查用海報並依它審查；`REVIEW_MODE=sim` 不畫圖，審查結果與 mock 模式相同。api 與 worker 讀同一個值（`docker-compose.yml` 預設 `composer`，`.env` 或環境變數可以覆寫）。
- 商品照去背：worker 以 BiRefNet（ONNX Runtime）執行，新增商品時自動去背，每張約 13 秒（Docker 實測）。第一次啟動時下載模型（約 1 GB，存在 `models` volume），點開右上角的系統狀態，可看到模型是下載中、載入中或已載入。去背時 worker 約使用 8 GB 記憶體（Docker 實測尖峰約 7.6 GiB；平常約 2 GB）。兩個模型的 Docker 記憶體上限都要設到約 10 GB 以上（Docker Desktop 的 Settings → Resources，WSL2 則改 `.wslconfig`）。`CUTOUT_MODEL=birefnet-general-lite` 較快、下載量較小（約 224 MB），但尖峰只低約 0.75 GB（本機實測 5.75 GB 對 6.50 GB），改用它解決不了記憶體不足；16 GB 的電腦只用去背時請把上限調到約 10 GB（同時使用 RAG 見下面的「RAG 的記憶體」），WSL2 預設是一半的記憶體（16 GB 的電腦是 8 GB），不夠用。
- RAG（`RAG_MODE=bge`，預設）：worker 第一次啟動時下載 BGE-M3、bge-reranker-v2-m3 與共用的 tokenizer（int8 ONNX，合計約 1.2 GB，存在 `models` volume），核對後先不載入：worker 啟動時的同步發現索引有差異（例如第一次啟動或 Chroma 重建）時就會載入；沒有差異時，第一次檢索才載入。載入後常駐。系統狀態的「RAG 模型」依序顯示下載中、已就緒（第一次檢索時載入）、載入中、已載入。下載或載入期間送出的任務會在「檢索」階段等候。
- RAG 的記憶體：模型載入後 worker 約再多用 1.7 GB（Docker 實測 1.75 GB；沒有載入時約 0.1 GB，為去背用模擬版時的實測）。與去背的尖峰相加約 10 GB，Docker 的記憶體上限請比上面的建議再多留約 2 GB（例如 12 GB）。16 GB 的電腦同時使用去背與 RAG 時，Docker 上限請設約 12 GB；不夠時改用 `RAG_MODE=sim`，也就是模擬檢索（不下載模型、不寫入 Chroma）。
```

找到（5／6）：

```markdown
|---|---|---|
| `backend/` | `uv run uvicorn app.api.main:app --port 8000 --reload` | api |
| `backend/` | `uv run python -m app.worker` | worker |
| `web/` | `npm run composer` | composer（3900 埠） |
| `web/` | `NEXT_PUBLIC_API_MODE=live API_PROXY_URL=http://127.0.0.1:8000 npm run dev` | 前端（/api、/files、/ws 轉給 api） |

Windows PowerShell 不能在指令前加環境變數，前端改用：
```

改成：

```markdown
|---|---|---|
| `backend/` | `uv run uvicorn app.api.main:app --port 8000 --reload` | api |
| `backend/` | `uv run python -m app.worker` | worker |
| `web/` | `npm run composer` | composer（3900 埠；先執行一次 `npm run fonts`） |
| `web/` | `NEXT_PUBLIC_API_MODE=live API_PROXY_URL=http://127.0.0.1:8000 npm run dev` | 前端（/api、/files、/ws 轉給 api） |

Windows PowerShell 不能在指令前加環境變數，前端改用：
```

找到（6／6）：

```markdown

注意：`docker compose` 也讀同一個 `.env`。寫在 `.env` 的話，回到 Docker 版之前要先刪掉這一行，否則 Docker 的 api 與 worker 也會改用模擬檢索。

開啟 http://127.0.0.1:3000（前端）；API 文件在 http://127.0.0.1:8000/docs。開發結束後，停掉本機的服務，再 `docker compose up -d` 回到 Docker 版。

## 測試

| 目錄 | 指令 | 內容 |
|---|---|---|
| `backend/` | `uv run pytest` | 後端（需要 `docker compose up -d postgres redis chroma`；使用 PostgreSQL 與 Chroma 的 `genai_test` 資料庫、Redis 第 15 號資料庫，會自行啟動 composer）。`models/` 有 RAG 模型檔時，也會執行標記 `model` 的真模型測試 |
| `web/` | `npm run test` | 前端與 composer 的單元測試 |
| `web/` | `npm run e2e` | mock 模式 E2E |
| `web/` | `npm run e2e:live` | live 模式 E2E：以獨立的 compose 專案啟動整套服務，測完移除，不影響平常的資料 |
| `web/` | `npm run fixtures` | 重新產生 `contracts/fixtures/`（後端與前端一致性測試的固定測資） |
```

改成：

````markdown

注意：`docker compose` 也讀同一個 `.env`。寫在 `.env` 的話，回到 Docker 版之前要先刪掉這一行，否則 Docker 的 api 與 worker 也會改用模擬檢索。

本機的 worker 預設是 `REVIEW_MODE=composer`：每張候選都要由 composer 繪製審查用海報，所以本機的 composer 要有海報字型。第一次啟動 composer 之前，先在 `web/` 下載字型（約 29 MB，連同 OFL 授權文字存在不進 git 的 `web/composer/fonts/`；核對 SHA-256，已下載的檔案會略過，可以重複執行）：

```powershell
cd web
npm run fonts
```

缺少字型時 composer 會印出原因並結束，不會帶著畫不出正確海報的狀態啟動。字型放在別的資料夾的話，以 `POSTER_FONTS_DIR` 指定（`npm run fonts` 與 `npm run composer` 都讀這個變數）。不需要審查用海報時，api 與 worker 都改用模擬審查（`.env` 的 `REVIEW_MODE=sim`；回到 Docker 版之前同樣要刪掉）：

```powershell
$env:REVIEW_MODE='sim'; uv run python -m app.worker
```

開啟 http://127.0.0.1:3000（前端）；API 文件在 http://127.0.0.1:8000/docs。開發結束後，停掉本機的服務，再 `docker compose up -d` 回到 Docker 版。

## 測試

| 目錄 | 指令 | 內容 |
|---|---|---|
| `backend/` | `uv run pytest` | 後端（需要 `docker compose up -d postgres redis chroma`，以及在 `web/` 執行過 `npm run fonts`；使用 PostgreSQL 與 Chroma 的 `genai_test` 資料庫、Redis 第 15 號資料庫，會自行在 3902 埠啟動 composer，缺少字型時立即失敗並提示）。不讀 `.env`，開發用的 `RAG_MODE`、`REVIEW_MODE` 不影響測試。`models/` 有 RAG 模型檔時，也會執行標記 `model` 的真模型測試 |
| `web/` | `npm run test` | 前端與 composer 的單元測試；伺服器端繪製海報的測試需要字型（`npm run fonts`），沒有字型時略過並提示 |
| `web/` | `npm run e2e` | mock 模式 E2E |
| `web/` | `npm run e2e:live` | live 模式 E2E：以獨立的 compose 專案啟動整套服務（審查用 `REVIEW_MODE=composer`，RAG 與去背用模擬版），測完移除，不影響平常的資料 |
| `web/` | `npm run fixtures` | 重新產生 `contracts/fixtures/`（後端與前端一致性測試的固定測資） |
````

- [ ] **Step 2: 修改 `backend/README.md`**

找到（1／7）：

```markdown
|---|---|
| `uv run uvicorn app.api.main:app --port 8000 --reload` | api（啟動時執行 migration 並匯入 `brands/*.yaml`） |
| `uv run python -m app.worker` | worker（啟動時把中斷的任務標記失敗，排隊中的重新放回佇列；在背景準備去背與 RAG 模型，再把品牌同步到 Chroma） |
| `uv run pytest` | 測試：重建 PostgreSQL 的 `genai_test` 資料庫、使用 Redis 第 15 號資料庫與 Chroma 的 `genai_test` database（需要 `docker compose up -d postgres redis chroma`），並在 3902 埠啟動 composer（需要 `web/` 已 `npm ci`） |
| `uv run pytest -m model` | 只跑真模型的測試（標記 `model`）：repo 根目錄的 `models/` 有模型檔時才執行，否則略過。去背模型的測試另外需要以 `CUTOUT_TEST_PHOTO` 指定一張商品照（例如 `CUTOUT_TEST_PHOTO=../data/uploads/xxx.jpg uv run pytest -m model`） |
| `uv run ruff check . && uv run ruff format --check .` | lint 與格式 |
| `uv run mypy` | 型別檢查（strict） |
```

改成：

```markdown
|---|---|
| `uv run uvicorn app.api.main:app --port 8000 --reload` | api（啟動時執行 migration 並匯入 `brands/*.yaml`） |
| `uv run python -m app.worker` | worker（啟動時把中斷的任務標記失敗，排隊中的重新放回佇列；在背景準備去背與 RAG 模型，再把品牌同步到 Chroma） |
| `uv run pytest` | 測試：重建 PostgreSQL 的 `genai_test` 資料庫、使用 Redis 第 15 號資料庫與 Chroma 的 `genai_test` database（需要 `docker compose up -d postgres redis chroma`），並在 3902 埠啟動 composer（需要 `web/` 已 `npm ci` 與 `npm run fonts`；composer 缺少字型就結束，測試立即失敗並提示）。測試不讀 `.env`（設定一律以 `_env_file=None` 建立），環境變數仍然有效 |
| `uv run pytest -m model` | 只跑真模型的測試（標記 `model`）：repo 根目錄的 `models/` 有模型檔時才執行，否則略過。去背模型的測試另外需要以 `CUTOUT_TEST_PHOTO` 指定一張商品照（例如 `CUTOUT_TEST_PHOTO=../data/uploads/xxx.jpg uv run pytest -m model`） |
| `uv run ruff check . && uv run ruff format --check .` | lint 與格式 |
| `uv run mypy` | 型別檢查（strict） |
```

找到（2／7）：

```markdown
| 變數 | 預設 | 說明 |
|---|---|---|
| `RAG_MODE` | `bge` | `bge`：BGE-M3＋Reranker＋Chroma；`sim`：模擬檢索（固定的召回與 Rerank 順序，不下載模型、不連 Chroma；測試與 live E2E 使用） |
| `CHROMA_URL` | `http://127.0.0.1:8001` | Docker 內為 `http://chroma:8000` |
| `MODELS_DIR` | repo 根目錄的 `models/` | 去背與 RAG 的模型檔（Docker 為 `models` volume） |
```

改成：

```markdown
| 變數 | 預設 | 說明 |
|---|---|---|
| `RAG_MODE` | `bge` | `bge`：BGE-M3＋Reranker＋Chroma；`sim`：模擬檢索（固定的召回與 Rerank 順序，不下載模型、不連 Chroma；測試與 live E2E 使用） |
| `REVIEW_MODE` | `composer` | `composer`：composer 繪製審查用海報（存到 `data/jobs/`），量出主色後審查，分數不加抖動；`sim`：不畫圖，審查結果與前端 mock 相同（parity 測試與作品集 Demo）。live E2E 使用 `composer` |
| `COMPOSER_URL` | `http://127.0.0.1:3900` | Docker 內為 `http://composer:3900`。`REVIEW_MODE=composer` 時 composer 要有海報字型（在 `web/` 執行 `npm run fonts`） |
| `CHROMA_URL` | `http://127.0.0.1:8001` | Docker 內為 `http://chroma:8000` |
| `MODELS_DIR` | repo 根目錄的 `models/` | 去背與 RAG 的模型檔（Docker 為 `models` volume） |
```

找到（3／7）：

````markdown
$env:RAG_MODE='sim'; uv run python -m app.worker
```

## API

- 文件：http://127.0.0.1:8000/docs
````

改成：

````markdown
$env:RAG_MODE='sim'; uv run python -m app.worker
```

本機的 worker 預設是 `REVIEW_MODE=composer`，每張候選都會呼叫 composer 的 `/render`。先在 `web/` 執行 `npm run fonts` 與 `npm run composer`（缺少字型時 composer 會結束）；不需要審查用海報時改用模擬審查（api 也要設定同一個值，系統狀態才會一致）：

```powershell
$env:REVIEW_MODE='sim'; uv run python -m app.worker
```

## API

- 文件：http://127.0.0.1:8000/docs
````

找到（4／7）：

```markdown
- `WS /ws/jobs/{id}?after={seq}`：先補送 `seq` 大於 `after` 的事件，再轉送即時事件；任務結束且事件送完後以 1000 關閉，任務不存在時以 4404 關閉。Redis 停止或訂閱失敗時不中斷，改為每秒從資料庫讀取新事件，直到任務結束。
- `POST /api/brands/{id}/documents`：multipart，欄位 `file`（`.md`、`.markdown`、`.txt` 為 UTF-8；`.pdf` 以 pypdf 抽出文字層）。api 先檢查副檔名、大小（20 MB）、編碼、PDF 是否加密或沒有文字、文字長度（20 萬字），有錯直接回 400，不開始串流；之後以 NDJSON 串流回報切塊、向量化與寫入的進度。120 秒沒有任何進度時回報逾時（大份手冊只要持續有進度就不算逾時）。
- `POST /api/jobs/{id}/select`：寫入歷史紀錄後，由 worker 回寫成歷史切塊，最多等 10 秒；逾時、失敗或被中止時 `writtenToRag` 為 false（不回 500，歷史紀錄已經建立）。
- `GET /api/status`：各服務的狀態，每項最多等 3 秒。RAG 的兩項：

| 元件 | 狀態 |
|---|---|
| 向量庫（Chroma） | `GET {CHROMA_URL}/api/v2/heartbeat`：正常時顯示網址，連不上為「異常」；`RAG_MODE=sim` 時不檢查，顯示「模擬模式不使用向量庫」 |
| RAG 模型（BGE-M3＋Reranker） | 讀 Redis 的 `rag:model`（worker 回報）：模擬、下載中（約 1.2 GB）、已就緒（第一次檢索時載入）、載入中、已載入、失敗（原因）；worker 還沒回報時為「worker 尚未回報」 |
```

改成：

```markdown
- `WS /ws/jobs/{id}?after={seq}`：先補送 `seq` 大於 `after` 的事件，再轉送即時事件；任務結束且事件送完後以 1000 關閉，任務不存在時以 4404 關閉。Redis 停止或訂閱失敗時不中斷，改為每秒從資料庫讀取新事件，直到任務結束。
- `POST /api/brands/{id}/documents`：multipart，欄位 `file`（`.md`、`.markdown`、`.txt` 為 UTF-8；`.pdf` 以 pypdf 抽出文字層）。api 先檢查副檔名、大小（20 MB）、編碼、PDF 是否加密或沒有文字、文字長度（20 萬字），有錯直接回 400，不開始串流；之後以 NDJSON 串流回報切塊、向量化與寫入的進度。120 秒沒有任何進度時回報逾時（大份手冊只要持續有進度就不算逾時）。
- `POST /api/jobs/{id}/select`：寫入歷史紀錄後，由 worker 回寫成歷史切塊，最多等 10 秒；逾時、失敗或被中止時 `writtenToRag` 為 false（不回 500，歷史紀錄已經建立）。
- `GET /api/status`：各服務的狀態，每項最多等 3 秒。composer 與 RAG 的兩項：

| 元件 | 狀態 |
|---|---|
| composer（排版、繪製與規則審查） | `GET {COMPOSER_URL}/health`：`REVIEW_MODE=composer` 時顯示載入的海報字型與網址，composer 沒有回報字型（舊的映像檔）時為「異常」，提示重新建置；`REVIEW_MODE=sim` 時為「模擬」（模擬審查，不繪製審查用海報）；連不上為「異常」 |
| 向量庫（Chroma） | `GET {CHROMA_URL}/api/v2/heartbeat`：正常時顯示網址，連不上為「異常」；`RAG_MODE=sim` 時不檢查，顯示「模擬模式不使用向量庫」 |
| RAG 模型（BGE-M3＋Reranker） | 讀 Redis 的 `rag:model`（worker 回報）：模擬、下載中（約 1.2 GB）、已就緒（第一次檢索時載入）、載入中、已載入、失敗（原因）；worker 還沒回報時為「worker 尚未回報」 |
```

找到（5／7）：

```markdown
3. 每則事件在同一個交易中鎖定任務列並取得下一個 `seq`，commit 後發布到 Redis 頻道 `job:{id}`；結束任務的 `job.status` 一定是最後一則。
4. 取消：排隊中的直接取消；執行中的設定旗標，worker 在步驟之間停止。

外部服務都經過 `app/pipeline/ports.py` 的介面。檢索由 `app/rag/retriever.py` 的 `BgeRetriever` 實作（`RAG_MODE=sim` 時改用模擬版）；Agent、生圖與審查仍由 `app/pipeline/sim.py` 的模擬版實作（Agent 與審查透過 composer 沿用前端 mock 的 TypeScript），之後的計畫換成 Gemini 與 ComfyUI。

## RAG
```

改成：

```markdown
3. 每則事件在同一個交易中鎖定任務列並取得下一個 `seq`，commit 後發布到 Redis 頻道 `job:{id}`；結束任務的 `job.status` 一定是最後一則。
4. 取消：排隊中的直接取消；執行中的設定旗標，worker 在步驟之間停止。

外部服務都經過 `app/pipeline/ports.py` 的介面。檢索由 `app/rag/retriever.py` 的 `BgeRetriever` 實作（`RAG_MODE=sim` 時改用模擬版）；排版與審查由 `app/pipeline/review.py` 的 `ComposerPosters` 與 `ComposerReviewer` 實作（`REVIEW_MODE=sim` 時改用模擬版）；Agent 與生圖仍由 `app/pipeline/sim.py` 的模擬版實作（Agent 透過 composer 沿用前端 mock 的 TypeScript），Plan 6B 與 Plan 7 換成 Gemini 與 ComfyUI。

## 審查（REVIEW_MODE=composer）

- **排版**：`composing` 階段對每張候選呼叫 `PosterComposer.compose`。worker 以 `resolve_file` 讀商品圖（去背圖以 normal 合成，否則原圖以 multiply 合成，與前端的 `productImage` 相同）與 Logo，長邊超過 2048 px 或 EXIF 方向不是正向的圖先以 Pillow 轉正、縮小，再以 base64 送到 composer 的 `/render`（請求上限 30 MB）。composer 以前端的 `scene.ts` 與 `paint.ts` 在伺服器端繪製，回傳 PNG 與量到的主色；worker 把 PNG 存到 `data/jobs/{jobId}/{renderId}.png`（由 `/files/jobs/…` 提供，每張約 0.3–1 MB，不會自動清理），記錄「✓ 伺服器端排版 N 張」。示範商品不送圖檔，由 composer 自己畫；Logo 圖檔不存在或無法讀取時改畫向量標誌並記錄警告。
- **審查**：`ComposerReviewer` 以量到的主色呼叫 `/review`：7 項規則加 3 項 VLM，分數為 `scoreChecks(checks, 0)`，不加抖動。VLM 三項在 Plan 6B 之前依內容判斷（誇大用語看禁用詞、遮擋看 Logo 是否與標題重疊、品質一律通過），說明加上「（模擬，Plan 6B 改用 Gemini）」。`review.completed` 的 `image` 是審查用海報的網址（模擬版為 `null`）。
- **主色量測**（`web/src/lib/review/measure.ts`）：範圍是 `headline`、`price`、`badge` 三個區塊的聯集扣掉 `product`；4×4 像素一格取平均、轉 Lab，濾掉彩度低於門檻（10 與品牌主色 C* 的一半取小）的格子，以 Lab 直方圖找出佔比 2% 以上的色塊，取與品牌主色 ΔE2000 最小的一個。最小 ΔE 超過 `rules.maxDeltaE` 時，改回報彩度最高的色塊，說明文字顯示實際用錯的顏色；沒有色塊時判定不通過，說明為「未偵測到主色（主色區塊 < 2%）」。
- **限制**：主色檢查只確認排版上的品牌色元素，不檢查背景。程式產生的背景依品牌色繪製；Plan 7 換成 AI 生成的照片背景時，再新增「背景色系」檢查。
- **錯誤**：composer 無法連線或回傳錯誤時任務失敗，原因為「排版服務（composer）無法繪製海報：…」或「…無法審查海報：…」；找不到或讀不到上傳的商品圖時為「無法繪製審查用海報：找不到商品圖（網址）」或「…商品圖無法讀取（網址）：…」。
- **模擬版**（`REVIEW_MODE=sim`）：`SimPosters` 不畫圖，`SimReviewer` 呼叫 composer 的 `/sim/review`，事件與前端 mock 完全相同（parity 測試只多比對 `image: null`）。

## RAG
```

找到（6／7）：

````markdown
```
app/
├─ api/            FastAPI：main.py（入口與錯誤格式）、catalog、jobs、files、services
├─ pipeline/       任務流程（runner）、外部服務介面（ports）、模擬版（sim）
├─ adapters/       composer 用戶端
├─ cutout/         商品照去背：前後處理（processing）、BiRefNet 與模擬版（segmenter）、模型清單（models）、狀態鍵（state）、準備與狀態（engine）
├─ rag/            RAG：切塊（chunking）、抽字（extract：Markdown、純文字、PDF）、模型清單（models）、ONNX 推論（encoder）、
│                  準備與狀態（engine、state）、錯誤（errors）、Chroma 用戶端（store）、PostgreSQL → Chroma 同步（sync）、
````

改成：

````markdown
```
app/
├─ api/            FastAPI：main.py（入口與錯誤格式）、catalog、jobs、files、services
├─ pipeline/       任務流程（runner）、外部服務介面（ports）、審查用海報與審查（review）、模擬版（sim）
├─ adapters/       composer 用戶端（版型、/render、/review、/sim/*、/health）
├─ cutout/         商品照去背：前後處理（processing）、BiRefNet 與模擬版（segmenter）、模型清單（models）、狀態鍵（state）、準備與狀態（engine）
├─ rag/            RAG：切塊（chunking）、抽字（extract：Markdown、純文字、PDF）、模型清單（models）、ONNX 推論（encoder）、
│                  準備與狀態（engine、state）、錯誤（errors）、Chroma 用戶端（store）、PostgreSQL → Chroma 同步（sync）、
````

找到（7／7）：

```markdown
├─ errors.py       領域錯誤（AppError 與子類別）；api 轉成 { error: { code, message } }
├─ templates.py    通路模板（與 web/src/lib/compose/templates.ts 相同）
├─ events.py       事件保存與推送、WebSocket 串流
├─ files.py        /files/... 網址與資料夾的對應（api 提供檔案、worker 讀取商品照）
├─ queues.py       SAQ 佇列
├─ worker.py       worker 的任務、啟動時復原與模型準備
├─ modelfiles.py   模型檔的下載與核對（去背與 RAG 共用）
```

改成：

```markdown
├─ errors.py       領域錯誤（AppError 與子類別）；api 轉成 { error: { code, message } }
├─ templates.py    通路模板（與 web/src/lib/compose/templates.ts 相同）
├─ events.py       事件保存與推送、WebSocket 串流
├─ files.py        /files/... 網址與資料夾的對應（api 提供檔案、worker 讀取商品照與寫入審查用海報）
├─ queues.py       SAQ 佇列
├─ worker.py       worker 的任務、啟動時復原與模型準備
├─ modelfiles.py   模型檔的下載與核對（去背與 RAG 共用）
```

- [ ] **Step 3: 修改 `web/README.md`**

找到（1／6）：

```markdown
## 需求

- Node.js 24、npm 11

## 開始
```

改成：

```markdown
## 需求

- Node.js 24、npm 11
- composer 與伺服器端繪製海報的測試需要海報字型：執行一次 `npm run fonts`（見下方「海報字型」）

## 開始
```

找到（2／6）：

```markdown
|---|---|
| `npm run dev` | 開發伺服器 |
| `npm run build` | 靜態輸出到 `out/` |
| `npm run test` | Vitest 單元測試（含 composer） |
| `npm run e2e` | mock 模式 E2E（建置後在 3100 埠提供靜態輸出；第一次要先執行 `npx playwright install chromium`） |
| `npm run e2e:live` | live 模式 E2E（以 docker compose 啟動獨立的整套服務，3200 埠，測完移除；開始前先移除上次中斷留下的容器與資料。RAG 用模擬版，不下載模型） |
| `npm run composer` | composer（3900 埠）：後端使用的版型與模擬邏輯 |
| `npm run fixtures` | 產生 `../contracts/fixtures/`（後端的一致性測試使用） |
| `npm run typecheck` | 型別檢查（含路由型別） |
| `npm run lint` | ESLint |
```

改成：

```markdown
|---|---|
| `npm run dev` | 開發伺服器 |
| `npm run build` | 靜態輸出到 `out/` |
| `npm run test` | Vitest 單元測試（含 composer）；需要字型的測試（字型註冊、伺服器端繪製海報、3 個品牌 × 5 個模板的主色量測）在沒有字型時略過並提示 |
| `npm run e2e` | mock 模式 E2E（建置後在 3100 埠提供靜態輸出；第一次要先執行 `npx playwright install chromium`） |
| `npm run e2e:live` | live 模式 E2E（以 docker compose 啟動獨立的整套服務，3200 埠，測完移除；開始前先移除上次中斷留下的容器與資料。RAG 與去背用模擬版，不下載模型；審查用 `REVIEW_MODE=composer`，確認審查用海報） |
| `npm run composer` | composer（3900 埠）：後端使用的版型、審查用海報的繪製、規則審查與模擬邏輯；啟動時註冊海報字型，缺少時印出原因並結束 |
| `npm run fonts` | 下載海報字型到 `composer/fonts/`（或 `npm run fonts -- <資料夾>`、`POSTER_FONTS_DIR`），核對大小與 SHA-256；已存在且相符的檔案會略過 |
| `npm run fixtures` | 產生 `../contracts/fixtures/`（後端的一致性測試使用） |
| `npm run typecheck` | 型別檢查（含路由型別） |
| `npm run lint` | ESLint |
```

找到（3／6）：

```markdown
| 工作台 | `/queue` | 批次佇列：多商品 × 多模板 |
| 工作台 | `/history` | 歷史紀錄：篩選、收藏、以相同設定重做 |
| 工作台 | `/brands` | 品牌知識庫：CI、禁用詞、RAG 切塊（標示新上傳、歷史回寫、歷史案例、Query Rewriting 專用）、上傳文件（live：`.md`、`.txt`、`.pdf`；mock：`.md`、`.txt`） |
| Agent 透視 | `/agent` | 任務透視：流程節點、WebSocket 事件串流、JSON Prompt 與注入參數、RAG Rerank、合規報告與 BBox 疊圖、重試 diff |
| Agent 透視 | `/dashboard` | 成效儀表板：通過率、平均重試次數、平均耗時、每張成本、各檢查項失敗分布、Rerank 對命中率的影響 |

## 資料保存
```

改成：

```markdown
| 工作台 | `/queue` | 批次佇列：多商品 × 多模板 |
| 工作台 | `/history` | 歷史紀錄：篩選、收藏、以相同設定重做 |
| 工作台 | `/brands` | 品牌知識庫：CI、禁用詞、RAG 切塊（標示新上傳、歷史回寫、歷史案例、Query Rewriting 專用）、上傳文件（live：`.md`、`.txt`、`.pdf`；mock：`.md`、`.txt`） |
| Agent 透視 | `/agent` | 任務透視：流程節點、WebSocket 事件串流、JSON Prompt 與注入參數、RAG Rerank、合規報告與 BBox 疊圖（live 的 `REVIEW_MODE=composer` 可切換「預覽／審查用海報」；主色檢查旁顯示量到的主色色塊）、重試 diff |
| Agent 透視 | `/dashboard` | 成效儀表板：通過率、平均重試次數、平均耗時、每張成本、各檢查項失敗分布、Rerank 對命中率的影響 |

## 資料保存
```

找到（4／6）：

```markdown
- 每則事件都帶序號（`seq`）與時間戳（`ts`）。Agent 透視用來顯示事件串流與各節點耗時；儀表板依此統計耗時。
- 自己的商品照可放在 repo 根目錄的 `assets/products/`（已在 `.gitignore`，不會上傳 GitHub），live 模式下到「商品庫」一鍵匯入，檔名即商品名稱。
- 字型使用 `@fontsource-variable` 自帶的 Noto Sans／Serif TC，執行時不連外部網路。

## Demo 控制台（只有 mock 模式）
```

改成：

```markdown
- 每則事件都帶序號（`seq`）與時間戳（`ts`）。Agent 透視用來顯示事件串流與各節點耗時；儀表板依此統計耗時。
- 自己的商品照可放在 repo 根目錄的 `assets/products/`（已在 `.gitignore`，不會上傳 GitHub），live 模式下到「商品庫」一鍵匯入，檔名即商品名稱。
- 字型使用 `@fontsource-variable` 自帶的 Noto Sans／Serif TC，執行時不連外部網路。
- live 模式的審查用海報（`REVIEW_MODE=composer`）由 worker 存在 repo 根目錄的 `data/jobs/{任務 id}/{候選 id}.png`，事件 `review.completed` 的 `image` 是它的網址（`/files/jobs/…`）；mock 與 `REVIEW_MODE=sim` 為 `null`，合規報告不顯示切換。

## 海報字型（composer）

composer 以 `@napi-rs/canvas`（版本固定 `1.0.13`）在伺服器端繪製海報，字型與前端相同：Google Fonts 的 Noto Sans TC 與 Noto Serif TC 可變字重 TTF（一個檔案涵蓋所有字重），固定在 `google/fonts` 的一個 commit。授權為 SIL Open Font License 1.1，授權文字（`OFL-NotoSansTC.txt`、`OFL-NotoSerifTC.txt`）和字型放在一起。

- **本機**：`npm run fonts` 依 `composer/fonts.lock.json`（檔名、網址、位元組數、SHA-256）下載到 `composer/fonts/`（約 29 MB，已在 `.gitignore` 與 `.dockerignore`），核對不符時不留下檔案並以中文說明原因。
- **Docker**：`Dockerfile` 的 `fonts` 階段以 `ADD --checksum=sha256:…` 下載同一組檔案，composer 映像檔放在 `/usr/local/share/poster-fonts`，並設定 `POSTER_FONTS_DIR`。`composer/dockerfile.test.ts` 確認 Dockerfile 的網址與 SHA-256 和清單一致。
- **字型資料夾**：`POSTER_FONTS_DIR`，沒有設定時為 `composer/fonts/`。composer 啟動時先清空所有字型（包含系統字型：電腦上可能裝了字高不同的另一版 Noto Sans TC），再註冊這兩個檔案；`GET /health` 回報已註冊的字型。
- **涵蓋範圍**：Big5 常用字與次常用字、全形標點；不含簡體專用字與 emoji，這些字在審查用海報上會畫成方塊。

## Demo 控制台（只有 mock 模式）
```

找到（5／6）：

```markdown
│  ├─ api/              ApiClient 介面；mock/（MockApiClient、劇本、示範資料與示範任務、IndexedDB）；http/（HttpApiClient、WebSocket 重新連線）
│  ├─ agent/            Prompt 構建、修正策略、版本差異、流程節點狀態、事件摘要、透視用的資料整理
│  ├─ compose/          版型、排版引擎（scene）、程序化素材（art）、Canvas 繪製（paint／render）
│  ├─ review/           規則型合規審查、ΔE2000、文案重新檢查
│  ├─ jobs/             事件 → 畫面狀態（reducer）
│  ├─ stats/            成效儀表板統計與成本估算
│  ├─ export/           檔名、zip、下載
```

改成：

```markdown
│  ├─ api/              ApiClient 介面；mock/（MockApiClient、劇本、示範資料與示範任務、IndexedDB）；http/（HttpApiClient、WebSocket 重新連線）
│  ├─ agent/            Prompt 構建、修正策略、版本差異、流程節點狀態、事件摘要、透視用的資料整理
│  ├─ compose/          版型、排版引擎（scene）、程序化素材（art）、Canvas 繪製（paint／render）
│  ├─ review/           規則型合規審查（rules）、ΔE2000（color）、從像素量測品牌主色（measure）、依內容判斷的 VLM 檢查（vlm）、文案重新檢查（recheck）
│  ├─ jobs/             事件 → 畫面狀態（reducer）
│  ├─ stats/            成效儀表板統計與成本估算
│  ├─ export/           檔名、zip、下載
```

找到（6／6）：

````markdown
│  └─ store/            Zustand stores
├─ test/                測試共用的資料（fixtures）、golden fixtures 的產生（golden）與切塊的範例文件（chunk-samples）
└─ types/contract.ts    前後端資料約定
composer/               Node 服務：版型與模擬邏輯（/layout、/sim/brief、/sim/prompt、/sim/review、/sim/fixes），由後端呼叫
scripts/                產生 fixtures、提供靜態輸出（Playwright 使用）
e2e/                    Playwright（mock）：主流程（含匯出 zip）、Agent 透視重試 diff、儀表板、手機寬度
e2e-live/               Playwright（live）：主流程、重新整理後接續、API 重新啟動後重新連線、取消、文件（Markdown 與 PDF）與商品照上傳
Dockerfile、nginx.conf  live 版（nginx）與 composer 的映像檔
```
````

改成：

````markdown
│  └─ store/            Zustand stores
├─ test/                測試共用的資料（fixtures）、golden fixtures 的產生（golden）與切塊的範例文件（chunk-samples）
└─ types/contract.ts    前後端資料約定
composer/               Node 服務，由後端呼叫：版型（/layout）、審查用海報（/render，poster.ts）、規則審查（/review）、
                        模擬邏輯（/sim/brief、/sim/prompt、/sim/review、/sim/fixes）、狀態與字型（/health）；
                        字型註冊（fonts.ts）、字型清單（fonts.lock.json）、下載的字型（fonts/，不進 git）
scripts/                產生 fixtures、提供靜態輸出（Playwright 使用）、下載海報字型（fetch-fonts.mjs）
e2e/                    Playwright（mock）：主流程（含匯出 zip）、Agent 透視重試 diff 與合規報告、儀表板、手機寬度
e2e-live/               Playwright（live）：主流程（含審查用海報）、重新整理後接續、API 重新啟動後重新連線、取消、文件（Markdown 與 PDF）與商品照上傳
Dockerfile、nginx.conf  live 版（nginx）與 composer 的映像檔（建置時下載並核對海報字型）
```
````

- [ ] **Step 4: 修改 `.env.example`**

找到：

```text
# 向量庫（Chroma）的網址，只有在本機執行後端（uv run）時使用：預設連 docker compose 的 chroma（127.0.0.1:8001）。
# Docker 內的 api 與 worker 固定使用 http://chroma:8000（docker-compose.yml）。
# CHROMA_URL=http://127.0.0.1:8001

# 之後的計畫會加入：
# GEMINI_API_KEY=                                  Plan 6：Gemini（LLM 與 VLM）
# COMFYUI_URL=http://host.docker.internal:8188     Plan 7：ComfyUI 生圖
```

改成：

```text
# 向量庫（Chroma）的網址，只有在本機執行後端（uv run）時使用：預設連 docker compose 的 chroma（127.0.0.1:8001）。
# Docker 內的 api 與 worker 固定使用 http://chroma:8000（docker-compose.yml）。
# CHROMA_URL=http://127.0.0.1:8001
# 審查：composer（預設，composer 在伺服器端繪製審查用海報，存到 data/jobs/{任務 id}/{候選 id}.png，從像素量出品牌主色後審查，分數不加抖動），
# 或 sim（不畫圖，審查結果與 mock 模式相同）。api（系統狀態）與 worker 要用同一個值。
# 在本機執行 worker 時，composer 要有海報字型：先在 web/ 執行 npm run fonts（約 29 MB），再 npm run composer。
# 字型放在別的資料夾時，在執行 composer 的視窗設定環境變數 POSTER_FONTS_DIR（composer 不讀這個檔案；Docker 的字型在建置時下載）。
REVIEW_MODE=composer

# 之後的計畫會加入：
# GEMINI_API_KEY=                                  Plan 6B：Gemini（LLM 與 VLM）
# COMFYUI_URL=http://host.docker.internal:8188     Plan 7：ComfyUI 生圖
```

- [ ] **Step 5: 確認全部通過**

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected：沒有錯誤；274 passed、3 skipped（沒有模型檔時略過真模型測試）。

Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint && npm run build && npm run e2e && npm run e2e:live`
Expected：51 個測試檔、424 個測試通過；建置成功；mock E2E 5 passed；live E2E 6 passed。

- [ ] **Step 6: Commit**

```bash
git add \
  .env.example \
  README.md \
  backend/README.md \
  web/README.md
git commit -m "docs: document the review poster, the poster fonts and REVIEW_MODE" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 完成之後

- 合併到 `main` 後，在主工作目錄執行 `docker compose up -d --build`。composer 映像檔會在建置時下載約 29 MB 的字型；之後新的任務就會產生審查用海報。
- 本機開發要先在 `web/` 執行 `npm run fonts`。
- 草稿分支 `plan6a-draft`、`plan6a-draft2` 可以刪除。
