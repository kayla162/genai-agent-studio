# Plan 6B：Gemini Agent、VLM 審查、用量與成本 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gemini 負責需求拆解、Prompt 構建（文案、版面、生圖提示詞）與 Query Rewriting，由 composer 的程式護欄保證合規、畫得出來並符合品牌版面規則；Gemini VLM 讀審查用海報判斷三項 VLM 檢查並轉錄文字，由 `ocrDiffs` 比對錯字；每次呼叫寫入 `job_usage`、依單價表計費並套用單一任務與每月的上限；儀表板改用實際用量。

**Architecture:**
- **切換**：`AGENT_MODE=gemini|sim` 一起切換 LLM 與 VLM。`gemini` 需要 `REVIEW_MODE=composer`；模擬模式（測試、live E2E、作品集 Demo）完全不變。
- **worker／api（Python）**：`GeminiClient`（官方 `google-genai` 的 `client.aio`，自己包重試、逾時、取消、用量與上限）、`GeminiAgent`、`GeminiReviewer`；提示詞放在 `backend/app/pipeline/prompts/*.md`。
- **composer（TypeScript）**：`POST /spec`（`finalizeSpec` 護欄）、`POST /review` 加上 `vlm`（`geminiVlmChecks` 與 `ocrDiffs`）、`POST /fixes`、`POST /glyphs`。護欄與審查共用同一套文案與幾何函式。
- **用量**：`job_usage` 資料表、repo 根目錄的 `pricing.yaml`；呼叫前檢查上限，呼叫後寫入並送出 `log`。

**Tech Stack:** google-genai 2.33.0、respx 0.23.1、FastAPI、SAQ、SQLAlchemy／Alembic、Pydantic 2、Node 24、@napi-rs/canvas 1.0.13、Vitest、Next.js 16、Docker Compose。

**Spec:** `docs/superpowers/specs/2026-10-23-plan6b-gemini-vlm-design.md`；背景見 `docs/superpowers/specs/2026-10-07-phase2-backend-design.md` 與 `docs/superpowers/specs/2026-10-22-plan6a-server-compose-design.md`。

## 開始前

**分支**
- 在 `main`（含規格的 merge commit `922408e`）之上的分支執行。每個 Task 一個 commit，完成後推送分支並開 PR。

**API key 與費用**
- `GEMINI_API_KEY` 由使用者自己寫進 repo 根目錄的 `.env`（不進 git）。不要在對話、commit、log 或測試資料中出現 key。
- `Settings` 讀的是程式所在 repo 根目錄的 `.env`：在 worktree 執行實驗或 live 測試時，`.env` 要放在 worktree 的根目錄（或以 `--env-file` 指定主工作目錄的 `.env`）。
- 需要 key 的只有 Task 1（實驗）、Task 14 的錄製腳本與 `pytest -m live`。其他 Task 一律使用假的 client 或 respx 重播，不會呼叫真 API。
- Task 1 的實驗約呼叫 Gemini 110–220 次，以目前單價估計 US$1–3；執行前向使用者確認。

**Task 1 的時間點**
- 依規格，實驗是第一個 Task；但實驗腳本使用 Task 2–14 的程式（`GeminiClient`、`GeminiAgent`、`GeminiReviewer`、composer 的 `/spec` 與 `/review`），才能量到護欄通過率與 `ocrDiffs`。
- 所以：
  - **開始時已有 key**：先做 Task 1 的 Step 1（連線確認：模型 ID、結構化輸出、用量欄位、`models.get`），確認規格的前提成立再開始 Task 2；其餘步驟在 Task 14 之後執行。
  - **開始時沒有 key**：Task 1 整個延後到 Task 14 之後。標示「實驗決定」的常數先用規格的預設值，respx 的回應先依 Gemini REST 文件手寫，Task 1 再以錄製腳本換成真的回應。
- 實驗結果寫進規格 §12；常數若改變，在同一個 commit 修改程式與測試。

**這台開發機（Windows）的限制**
- Node 24 不在 PATH：每個指令前加 `export PATH="/c/Users/User/AppData/Local/Programs/node-v24.22.1-win-x64:$PATH"`（Git Bash）。
- 海報字型在主工作目錄的 `web/composer/fonts/`（不進 git）。在 worktree 執行需要字型的測試時設定 `POSTER_FONTS_DIR` 指向那個資料夾。
- 沒有 Docker：需要 postgres、redis、chroma 的後端測試、`npm run e2e:live` 與 `docker compose` 驗收不能在這台執行，回報時列出。
- 使用者自己的 PostgreSQL 服務在 5432。後端測試的預設是 5433（docker compose 的 postgres），不可以把 `DATABASE_URL` 指向 5432：fixture 會以 FORCE 刪除並重建 `genai_test`。
- 一律用 `127.0.0.1`，不要用 `localhost`。
- `npm run fixtures` 在 Windows 以 LF 寫出 fixture；只有換行不同的檔案用 `git checkout -- <檔案>` 還原。

## 本計畫的驗證方式

6A 的計畫是在草稿分支驗證後才寫成，所以每一步都附完整程式碼。6B 沒有草稿分支：
- 每個 Task 列出檔案、介面、要先寫的測試案例與執行指令；程式碼以每個 Task 的 commit 為準。
- 每個 Task 都要確認：
  - 「先寫測試」的步驟確實失敗（找不到模組、函式或斷言不符）；
  - 結束時全部通過，ruff、`ruff format --check`、mypy（strict）、tsc 與 ESLint 都沒有錯誤。
- 不能在這台機器執行的測試（資料庫、Redis、Chroma）照樣撰寫，並在回報中列為「未在本機執行」。為了降低風險：
  - 純邏輯盡量放在不需要資料庫的函式，以不需要資料庫的測試涵蓋；
  - Task 9 修改任務流程後，以暫存的腳本（不進 git）在記憶體中執行模擬模式的 `_pipeline`，確認事件與 golden timelines 相同。

執行時若結果與預期不同，先檢查是否漏了步驟，不要修改測試來配合。

## Global Constraints

- **指令位置**：前端在 `web/`，後端在 `backend/`，`docker compose` 在 repo 根目錄。
- **後端檢查**：Python 3.13、uv。`uv run ruff check .`、`uv run ruff format --check .`（單引號、行寬 120）與 `uv run mypy`（strict）都必須通過。
- **前端檢查**：`npm run test`、`npm run typecheck`、`npm run lint` 都必須通過；不用 `eslint-disable` 繞過規則；不手動修改 `src/components/ui/*`。
- **前後端資料約定**：
  - `backend/app/contract.py` 與 `web/src/types/contract.ts` 不變（規格 §4.10）。
  - `SpecDraft`、`VlmVerdict`、`GuardIssue` 在 `web/src/types/agent.ts` 與 `backend/app/pipeline/gemini_types.py` 各定義一次，以 golden fixture 確認一致；JSON 一律 camelCase。
- **模擬模式不變**：`backend/tests/test_parity.py` 與 golden timelines 不得修改；`SimAgent`、`SimReviewer`、`ComposerReviewer` 接受新參數但不使用。
- **key 的處理**：`GEMINI_API_KEY` 以 `SecretStr` 保存，只在建立 SDK client 時取值；錯誤訊息、log 與事件輸出前把 key 換成 `***`；系統狀態只顯示末 4 碼。
- **測試不呼叫真 API**：一般的 `pytest` 不執行 `live` 標記的測試（`addopts` 排除），測試的 `Settings` 一律以 `_env_file=None` 建立並明確設定 `agent_mode`。
- **文字與錯誤**：UI 文字、錯誤訊息、註解、提示詞都用繁體中文；API 錯誤一律回傳 `{ error: { code, message } }`。
- **Commit**：每個 Task 結束都要 commit，訊息為英文，最後一行加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。

## File Structure

| 檔案 | 責任 |
|---|---|
| `web/composer/cmap.ts` | 讀 TrueType 字型的 cmap（format 4、12），回傳涵蓋的字元 |
| `web/scripts/glyphs.ts`（`npm run glyphs`） | 從海報字型產生 `glyphs.json` |
| `web/src/lib/compose/glyphs.ts`、`glyphs.json` | 字型涵蓋表、`missingGlyphs`、`stripEmoji` |
| `web/src/lib/review/ocr.ts` | `expectedSegments`、`normalizeOcr`、`bestMatch`（semi-global alignment）、`ocrDiffs`、`ocrCheck` |
| `web/src/lib/review/rules.ts` | `runRuleChecks` 的 `ocr?: OcrResult`；抽出 `layoutRuleChecks`（版面三項規則，護欄共用） |
| `web/src/lib/review/vlm.ts` | `geminiVlmChecks`；`SIMULATED_VLM_NOTE` 改為「（模擬：AGENT_MODE=sim）」 |
| `web/src/types/agent.ts` | `SpecDraft`、`VlmVerdict`、`GuardIssue`、`GuardCode` |
| `web/src/lib/compose/layout.ts` | `ELEMENT_LABELS`（版面元素的中文名稱） |
| `web/src/lib/agent/guard.ts` | `finalizeSpec`：Prompt 構建的程式護欄 |
| `web/src/lib/agent/prompt.ts` | 匯出 `NEGATIVE_BY_FIX`；抽出 `buildDisclaimer`、`positivePromptOf` 供護欄共用 |
| `web/composer/handlers.ts` | `/spec`、`/review`（`vlm`）、`/fixes`、`/glyphs` |
| `web/scripts/fixtures.ts`、`contracts/fixtures/agent.json` | `SpecDraft`、`VlmVerdict`、`GuardIssue` 的範例 |
| `pricing.yaml` | Gemini 單價表（有生效日） |
| `backend/app/settings.py` | `AGENT_MODE`、`GEMINI_*`、`PRICING_FILE`；`gemini` 加 `REVIEW_MODE=sim` 為設定錯誤 |
| `backend/app/usage.py` | 單價表、費用計算、台北時間的月份、`UsageLedger`（寫入、加總、上限） |
| `backend/app/repo/usage.py`、`backend/app/db/models.py`、`backend/migrations/versions/0003_job_usage.py` | `job_usage` 資料表與查詢 |
| `backend/app/errors.py` | `BudgetExceeded`（429 `budget_exceeded`） |
| `backend/app/validation.py` | `describe_errors`：Pydantic 錯誤的中文說明（API 的 400 與 Gemini 格式錯誤共用） |
| `backend/app/adapters/gemini.py` | `GeminiClient`：呼叫、重試、逾時、取消、上限、用量、key 遮蔽；`models.get` 檢查 |
| `backend/app/adapters/composer.py` | `spec`、`fixes`、`glyphs`、`review(vlm=…)`；送給 composer 的品牌精簡切塊 |
| `backend/app/pipeline/ports.py` | `RunContext.job_id`、`wait()`；`PreviousRound`；`SpecRequest.text`、`hits`、`previous`；`run` 參數；`Ports.usage` |
| `backend/app/pipeline/runner.py` | 並行的 Prompt 構建與審查（事件依序送出）、`PreviousRound`、可取消的等待、時間軸開關、費用合計 |
| `backend/app/pipeline/gemini_types.py` | `BriefDraft`、`SpecDraft`、`RewriteDraft`、`VlmVerdict`、`GuardIssue`、`gemini_schema` |
| `backend/app/pipeline/prompts/*.md` | 四種呼叫的系統指示（繁體中文） |
| `backend/app/pipeline/gemini.py` | `GeminiAgent`、`GeminiReviewer`、需求拆解與改寫的護欄 |
| `backend/app/worker.py`、`backend/app/api/services.py` | 依 `AGENT_MODE` 選擇 Agent 與 Reviewer |
| `backend/app/api/jobs.py`、`backend/app/api/main.py` | 需求拆解的逾時與錯誤碼、建立任務的拒絕條件、驗證訊息中文化、`/api/stats` 的實際用量 |
| `backend/app/api/catalog.py` | 系統狀態的 Gemini 檢查、品牌設定檔的缺字警告、可用選項 |
| `backend/app/stats.py` | `dashboard_stats(snaps, usage_costs=None)` |
| `web/src/components/dashboard/kpi-cards.tsx` | 每張成本的標示依模式（實際用量／估算） |
| `backend/scripts/record_gemini.py`、`backend/scripts/gemini_experiment.py` | 錄製 respx 回應、規格 §2 的實驗 |
| `backend/tests/fake_gemini.py`、`backend/tests/data/gemini/*.json` | 假的 Gemini client、respx 重播的回應 |
| `docker-compose.yml`、`docker-compose.e2e.yml`、`.env.example` | 新變數、唯讀掛載 `pricing.yaml`；E2E 固定 `AGENT_MODE=sim` 且不帶 key |

---

### Task 1：Gemini 實測（需要 API key）

**Files:**
- Create: `backend/scripts/gemini_experiment.py`
- Modify: `docs/superpowers/specs/2026-10-23-plan6b-gemini-vlm-design.md`（§12；必要時 §4.7 的估算）、實驗決定的常數所在檔案（`backend/app/adapters/gemini.py` 的 `THINKING`、`backend/app/pipeline/gemini.py` 的 `VLM_MAX_SIDE`、`web/src/lib/review/ocr.ts` 的 `OCR_MIN_PX` 與判定門檻、`web/src/lib/agent/guard.ts` 的 `TEXT_MIN`）、`backend/tests/data/gemini/*.json`（以 Task 14 的錄製腳本重新錄製）

**Interfaces:**
- Consumes：Task 2–14 的全部程式；composer 以 `npm run composer` 在 3900 執行（需要字型）。
- Produces：`uv run python scripts/gemini_experiment.py <probe|spec|ocr|vlm|stability|all> [--thinking low|high] [--limit N]`；報告 JSON 寫到 `data/experiments/plan6b-<時間>.json`（`data/` 不進 git），並在終端機印出摘要表。

**實驗的品牌與商品**：SÉLUNE、misty-isle、Kayla 精緻少女（`brands/my-brand-01.yaml`）。Kayla 沒有示範商品，實驗腳本以 `serum` 向量素材建立一個暫時的示範商品（不寫入資料庫）。

- [ ] **Step 1: 連線確認（開始時有 key 就先做）**

`probe` 子命令只用官方 SDK，不依賴後續 Task：
- `models.get` 取得 `gemini-3.8-flash`，印出輸入與輸出 token 上限；
- 以一個小的 Pydantic 模型呼叫一次 `generate_content`（`response_mime_type=application/json`、`response_json_schema`、`seed`、`thinking_config.thinking_level=LOW`），印出 `usage_metadata` 的各欄位（`prompt_token_count`、`cached_content_token_count`、`candidates_token_count`、`thoughts_token_count`）。

Expected：模型存在；回應可以通過 Pydantic 驗證；`thoughts_token_count` 有值。任何一項不成立時停下來，回報使用者並修改規格。

- [ ] **Step 2: 結構化輸出**

`spec`：3 個品牌 × 5 個模板 × 2 次 Prompt 構建。記錄第一次就通過格式驗證的比例、不必重問就通過全部護欄的比例，以及每個護欄問題代碼的次數。
通過標準：格式 ≥ 95%、護欄 ≥ 70%。不通過時修改 `prompts/spec.md` 後重跑。

- [ ] **Step 3: 轉錄與錯字**

`ocr`：composer 以預設文案繪製 15 張正確的海報（`/render`），VLM 轉錄後以 `/review` 計算 `ocrDiffs`；再各繪製一張把標題換掉一個字、一張放入缺字（畫成方塊）的海報。
通過標準：正確海報 0 處差異 ≥ 90%、沒有任何一張 ≥ 2 處；30 張錯字與方塊海報全部有差異，有方塊的全部判定為不通過。不通過時調整 `VLM_MAX_SIDE`（送出圖片的長邊）或 `OCR_MIN_PX`。

- [ ] **Step 4: VLM 判讀**

`vlm`：每個品牌各 3 張：正確的海報、Logo 壓在標題上、副標含禁用詞以外的誇大說法（例如「三天見效」「全台第一」）。
通過標準：正確海報三項都通過 ≥ 90%；刻意製造的遮擋與誇大全部抓到。不通過時修改 `prompts/vlm.md`。

- [ ] **Step 5: 穩定性**

`stability`：Step 4 的 9 張海報各審查 3 次。記錄三項檢查狀態一致的比例；< 90% 時記錄為已知限制。

- [ ] **Step 6: 用量、時間與思考程度**

Step 2–4 以 `--thinking low` 與 `--thinking high` 各跑一次（`--limit` 縮小矩陣以控制費用），比較品質、tokens（含思考）與時間，決定 `THINKING` 每種呼叫的預設值；依實際 tokens 更新規格 §4.7 的估算，必要時調整預設上限。

- [ ] **Step 7: 錄製 respx 回應**

以 Task 14 的 `scripts/record_gemini.py` 重新錄製 `backend/tests/data/gemini/` 的回應，取代手寫的版本；確認 `uv run pytest tests/test_gemini_client.py` 仍通過。

- [ ] **Step 8: 記錄結果並確認全部通過**

把每一項的方法、數字、決定與已知限制寫進規格 §12。常數改變時同步修改測試的預期值。

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint`
Expected：沒有錯誤（需要資料庫的後端測試在這台機器上會因為連不到 postgres 而失敗，只確認其他測試）。

- [ ] **Step 9: Commit**

```bash
git add backend/scripts/gemini_experiment.py backend/tests/data/gemini docs/superpowers/specs/2026-10-23-plan6b-gemini-vlm-design.md
# 加上實驗後修改的常數與測試
git commit -m "docs: record the Plan 6B Gemini experiment and tune the thresholds" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2：字型涵蓋表與 emoji 移除

**Files:**
- Create: `web/composer/cmap.ts`、`web/scripts/glyphs.ts`、`web/src/lib/compose/glyphs.ts`、`web/src/lib/compose/glyphs.json`（由腳本產生）
- Modify: `web/package.json`（`"glyphs": "tsx scripts/glyphs.ts"`）
- Test: `web/composer/cmap.test.ts`、`web/src/lib/compose/glyphs.test.ts`

**Interfaces:**
- Produces：
  - `web/composer/cmap.ts`：`readCmap(font: Buffer): Set<number>`（支援 cmap format 4 與 12，優先 Windows Unicode（3,10）與（3,1））；格式不支援時丟出中文錯誤。
  - `web/scripts/glyphs.ts`：讀 `resolveFontsDir()` 的兩個海報字型，取交集（空白字元除外），壓縮成區段 `[[start, end], …]` 寫入 `glyphs.json`，並記錄字型檔的 SHA-256（與 `fonts.lock.json` 相同）。
  - `web/src/lib/compose/glyphs.ts`：
    - `GLYPH_RANGES`（讀 `glyphs.json`）；`hasGlyph(codePoint): boolean`（二分搜尋）；
    - `missingGlyphs(text): string[]`：不在表內的字，空白除外，依出現順序、不重複；
    - `stripEmoji(text): string`：移除 `\p{Extended_Pictographic}`、變體選擇符（U+FE00–FE0F）、ZWJ（U+200D）、keycap（U+20E3）、膚色修飾符（U+1F3FB–1F3FF）、區域指示符號（U+1F1E6–1F1FF）與 tag 字元（U+E0020–E007F），並把移除後連續的空白合併。

`glyphs.ts` 只給 composer 與護欄使用，不要被前端的頁面匯入（避免把涵蓋表放進瀏覽器的 bundle）。

- [ ] **Step 1: 建立 `web/composer/cmap.test.ts`（先寫測試）**

測試案例：
- 以程式組出最小的 TrueType（只有 `cmap` 表）：format 4 的兩個區段（含 `idDelta` 與 `idRangeOffset` 兩種寫法）、format 12 的兩個 group，`readCmap` 回傳的字元完全相同；
- 沒有 `cmap` 表時丟出「字型沒有 cmap 表」；
- 有字型時（`resolveFontsDir()` 存在 `NotoSansTC-VF.ttf`）：涵蓋「晞」「月」「A」、不涵蓋 U+1F600；沒有字型時略過並提示 `npm run fonts`。

- [ ] **Step 2: 建立 `web/src/lib/compose/glyphs.test.ts`（先寫測試）**

測試案例：
- `stripEmoji`：「醒來✨透亮💧」→「醒來透亮」；「1️⃣ 第一」→「1 第一」；「👩‍👩‍👧家庭」→「家庭」；「🇹🇼台灣」→「台灣」；「👍🏽讚」→「讚」；一般中文、英文、數字、全形標點不變。
- `missingGlyphs`：全部常用中文與英數回傳空陣列；含表外的字（實作時從 `glyphs.json` 找一個表外的簡體字或罕用字，例如 U+20000 區段的字）時回傳該字；空白不算；重複的字只列一次。
- 有字型時：以 `readCmap` 重新計算兩個字型的交集，與 `GLYPH_RANGES` 完全一致（字型以 SHA-256 固定，所以這份表不會變）；沒有字型時略過。

- [ ] **Step 3: 確認測試失敗**

Run（在 `web/`）：`npx vitest run composer/cmap.test.ts src/lib/compose/glyphs.test.ts`
Expected：FAIL，找不到 `./cmap` 與 `./glyphs`。

- [ ] **Step 4: 建立 `web/composer/cmap.ts`、`web/scripts/glyphs.ts`、`web/src/lib/compose/glyphs.ts`，修改 `web/package.json`**

- [ ] **Step 5: 產生涵蓋表**

Run（在 `web/`，`POSTER_FONTS_DIR` 指向字型資料夾）：`npm run glyphs`
Expected：寫出 `src/lib/compose/glyphs.json`，印出涵蓋的字數與區段數。

- [ ] **Step 6: 確認全部通過**

Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint`
Expected：沒有錯誤；新增的測試全部通過（有字型）。

- [ ] **Step 7: Commit**

```bash
git add web/composer/cmap.ts web/composer/cmap.test.ts web/scripts/glyphs.ts web/src/lib/compose/glyphs.ts web/src/lib/compose/glyphs.json web/src/lib/compose/glyphs.test.ts web/package.json
git commit -m "feat: add the poster font coverage table, missingGlyphs and stripEmoji" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3：OCR 錯字比對

**Files:**
- Create: `web/src/lib/review/ocr.ts`
- Modify: `web/src/lib/review/rules.ts`、`web/src/lib/compose/layout.ts`（`ELEMENT_LABELS`）
- Test: `web/src/lib/review/ocr.test.ts`、`web/src/lib/review/rules.test.ts`

**Interfaces:**
- Produces：
  - `web/src/lib/compose/layout.ts`：`ELEMENT_LABELS: Record<LayoutElementId, string>`（Logo、標題、副標、賣點、商品、徽章、價格、註記）。
  - `web/src/lib/review/ocr.ts`：
    - `OCR_MIN_PX = 14`（實驗決定）、`OCR_WARN_MAX = 1`（1 處為 warn，實驗決定）；
    - `interface OcrSegment { el: LayoutElementId; text: string; size: number }`；
    - `expectedSegments(scene: PosterScene, opts: { logoImage: boolean }): OcrSegment[]`：`composePoster` 的每個 `TextOp`（含徽章內的文字、價格的「NT$」、原價、按鈕文字）；有 Logo 圖檔時不含向量字標；
    - `normalizeOcr(text): string`：NFKC、移除空白與標點符號、符號（`\p{P}`、`\p{S}`，但保留「□」與「?」）、英文轉小寫；
    - `bestMatch(needle, haystack): { distance: number; read: string }`：semi-global alignment（needle 全部比對、haystack 可從任一位置開始與結束），回傳最小編輯距離與對到的子字串；
    - `interface OcrDiff { el; expected; read; distance }`；`interface OcrResult { diffs: number; boxes: boolean; worst: OcrDiff | null; compared: number; skipped: number }`；
    - `ocrDiffs(lines: string[], segments: OcrSegment[], scale: number, minPx = OCR_MIN_PX): OcrResult`：轉錄各行相連後正規化；字級乘以 `scale` 小於 `minPx` 的段落略過；
    - `ocrCheck(result?: OcrResult): Pick<ReviewCheck, 'value' | 'status' | 'target'>`：沒有結果時為「0 處差異」、pass、`headline`（與現在相同）。
  - `web/src/lib/review/rules.ts`：`RuleContext.ocrDiffs?: number` 改為 `ocr?: OcrResult`；`ocr_typo` 由 `ocrCheck` 產生。

**判定**：0 處 pass；1 處 warn；2 處以上或有方塊 fail。說明文字例如「0 處差異」「1 處差異（標題「醒來透亮發光」讀成「醒來透高發光」）」「畫面有無法顯示的字（方塊）」「3 處差異（副標…）・畫面有無法顯示的字（方塊）」。顯示的文字過長時截成 12 字。target 為差異最多的元素（相同時取先出現的），沒有差異但有方塊時為 `canvas`。

- [ ] **Step 1: 建立 `web/src/lib/review/ocr.test.ts`（先寫測試）**

測試案例：
- `normalizeOcr`：全形英數轉半形、「NT$ 1,280」→「nt1280」、保留「□」與「?」；
- `bestMatch`：完全相同為 0；在長字串中間找到子字串；一個字被替換為 1；漏一個字、多一個字各為 1；
- `expectedSegments`：`makeSpec()` 的場景包含標題兩行、副標、每個賣點、徽章三段、價格的「NT$」、售價、原價、按鈕文字（寬版型）、註記；`logoImage: true` 時不含字標；
- `ocrDiffs`：
  - 轉錄與預期完全相同 → 0 處、pass；
  - 標題換一個字 → 1 處、warn、target `headline`，說明含「標題」；
  - 兩個元素各錯一字 → 2 處、fail；
  - 轉錄含「□」→ `boxes`、fail，說明含「方塊」；
  - `scale` 0.5 時字級 < 28 的段落略過（`skipped` 增加，錯字不計）；
  - 轉錄的行序與換行位置不同、多出商品包裝上的字，仍為 0 處。
- `ocrCheck(undefined)` 與現在的 `ocr_typo` 相同。

- [ ] **Step 2: 修改 `web/src/lib/review/rules.test.ts`（先寫測試）**

把原本傳 `ocrDiffs` 的測試改成傳 `ocr`；新增：`ocr` 為 1 處差異時 `ocr_typo` 為 warn 且分數扣 6；有方塊時為 fail 且 `passed` 為 false。

- [ ] **Step 3: 確認測試失敗**

Run（在 `web/`）：`npx vitest run src/lib/review`
Expected：FAIL，找不到 `./ocr`，`ocr` 參數不存在。

- [ ] **Step 4: 建立 `ocr.ts`，修改 `rules.ts` 與 `layout.ts`**

`runRuleChecks` 沒有傳入 `ocr` 時結果與現在完全相同（mock 的 `reviewRender` 與 golden fixtures 不變）。

- [ ] **Step 5: 確認全部通過，fixture 不變**

Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint && npm run fixtures && git status --short contracts/`
Expected：沒有錯誤；`contracts/fixtures/` 沒有內容上的改變（只有換行不同時還原）。

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/review/ocr.ts web/src/lib/review/ocr.test.ts web/src/lib/review/rules.ts web/src/lib/review/rules.test.ts web/src/lib/compose/layout.ts
git commit -m "feat: compare the transcribed poster text with the drawn copy in ocrDiffs" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4：Agent 型別、Gemini 的 VLM 三項與版面規則共用函式

**Files:**
- Create: `web/src/types/agent.ts`
- Modify: `web/src/lib/review/vlm.ts`、`web/src/lib/review/rules.ts`
- Test: `web/src/lib/review/vlm.test.ts`、`web/src/lib/review/rules.test.ts`

**Interfaces:**
- Produces：
  - `web/src/types/agent.ts`：
    - `VlmStatus = 'pass' | 'warn' | 'fail'`；
    - `VlmVerdict { lines: string[]; exaggeration: { status; phrases: string[]; reason }; occlusion: { status; elements: LayoutElementId[]; reason }; quality: { status; issues: string[]; reason } }`；
    - `SpecDraft { headline: [string, string]; subhead; features: string[]; badge: { top; main; sub }; priceLabel; layout: { id: LayoutElementId; bbox: BBox }[]; scene; negativeExtra; rationale }`；
    - `GuardCode`（`emoji_removed`、`missing_glyph`、`banned_word`、`too_long`、`invented_offer`、`empty_field`、`product_glyph`、`layout_invalid`、`layout_rule`、`text_too_small`、`prompt_invalid`）；`GuardIssue { code; field: string; message: string; retry: boolean }`。
  - `web/src/lib/review/rules.ts`：`layoutRuleChecks(spec, brand): ReviewCheck[]`（`logo_clearance`、`product_ratio`、`whitespace`，由 `runRuleChecks` 抽出，順序與內容不變）。
  - `web/src/lib/review/vlm.ts`：
    - `SIMULATED_VLM_NOTE = '（模擬：AGENT_MODE=sim）'`；
    - `geminiVlmChecks(verdict: VlmVerdict, spec: PromptSpec, brand: Brand): ReviewCheck[]`（規格 §4.6 的表）：
      - `vlm_exaggeration`：通過「未發現誇大用語」；否則「偵測到「…」「…」：理由」（沒有片語時只有理由）；target 為文案含該片語的第一個元素（`copyTexts`），找不到為 `null`；ragRef `law`；
      - `vlm_occlusion`：通過「無重疊遮擋」；否則「元素中文名：理由」；target 為 `elements[0]`（沒有時 `null`）；`elements` 含 `logo` 時 ragRef 為 `logo`，否則為 `layout`；
      - `vlm_quality`：通過「構圖與畫質良好」；否則以「、」列出問題（沒有問題時用理由）；target、ragRef 為 `null`；
      - 名稱與 `rule` 與 `contentVlmChecks` 相同；理由超過 60 字時截斷。

- [ ] **Step 1: 修改 `web/src/lib/review/vlm.test.ts`（先寫測試）**

- 把預期的標示改為「（模擬：AGENT_MODE=sim）」；
- 新增 `geminiVlmChecks` 的案例：三項都通過；誇大片語出現在副標（target `subhead`、ragRef `selune#law`）；片語不在文案中（target `null`）；Logo 與標題遮擋（「Logo：…」、target `logo`、ragRef `selune#logo`）；商品與價格重疊（ragRef `selune#layout`）；畫質 warn 列出問題；說明文字都不含「模擬」。

- [ ] **Step 2: 修改 `web/src/lib/review/rules.test.ts`（先寫測試）**

`layoutRuleChecks(spec, brand)` 與 `runRuleChecks` 中的三項完全相同。

- [ ] **Step 3: 確認測試失敗**

Run（在 `web/`）：`npx vitest run src/lib/review`
Expected：FAIL。

- [ ] **Step 4: 建立 `agent.ts`，修改 `vlm.ts` 與 `rules.ts`**

- [ ] **Step 5: 確認全部通過**

Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint`
Expected：沒有錯誤。`grep -rn "Plan 6B 改用 Gemini" web/` 沒有結果。

- [ ] **Step 6: Commit**

```bash
git add web/src/types/agent.ts web/src/lib/review/vlm.ts web/src/lib/review/vlm.test.ts web/src/lib/review/rules.ts web/src/lib/review/rules.test.ts
git commit -m "feat: add the Gemini VLM checks and share the layout rule checks" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5：Prompt 構建的護欄 `finalizeSpec`

**Files:**
- Create: `web/src/lib/agent/guard.ts`
- Modify: `web/src/lib/agent/prompt.ts`
- Test: `web/src/lib/agent/guard.test.ts`、`web/src/lib/agent/prompt.test.ts`

**Interfaces:**
- Consumes：Task 2 的 `missingGlyphs`、`stripEmoji`；Task 4 的型別與 `layoutRuleChecks`。
- Produces：
  - `web/src/lib/agent/prompt.ts`：
    - 匯出 `NEGATIVE_BY_FIX`；
    - `buildDisclaimer(brand, brief, copy: Pick<Copy, 'headline' | 'subhead' | 'features' | 'badge'>): string`（由 `buildCopy` 抽出，結果不變）；
    - `positivePromptOf(template, brand, brief, scene: string | null): string`：`scene` 為 `null` 時與現在的 `buildPromptSpec` 完全相同；
    - `negativePromptOf(fixes, extra: string): string`：`BASE_NEGATIVE` ＋ `NEGATIVE_BY_FIX` ＋ `extra`，以逗號拆開、去除空白與重複。
  - `web/src/lib/agent/guard.ts`：
    - `LIMITS`（視覺寬度：標題每行 8、副標 22、賣點各 12、徽章上下 6、價格標籤 8；徽章英文 16 字元）；
    - `TEXT_MIN = { headline: 0.04, other: 0.01 }`（畫布短邊的比例，實驗決定；徽章英文不檢查）；
    - `interface GuardRequest { jobId; round; brand; product; brief: ParsedBrief; text: string; templateId; engine; seed; ragRefs: string[]; fixes: CheckId[] }`；
    - `finalizeSpec(draft: SpecDraft, req: GuardRequest): { spec: PromptSpec; issues: GuardIssue[] }`。

**行為**（規格 §4.4 的 16 條）：
- 回傳的 `spec` 一律可以直接使用：有 `retry` 問題的欄位已經改用預設值（文案用 `buildCopy(brand, product, brief, true)` 的同一欄位；版面用 `computeLayout`；`scene` 用 `null`）。GeminiAgent 第一次有 `retry` 問題時重問，第二次直接使用這個 `spec`。
- 文案的順序：替代用語 → 移除 emoji（`emoji_removed`）→ 去除前後空白 → 檢查空白（`empty_field`）、長度（`too_long`；徽章英文先轉大寫，有大寫英文、數字與空白以外的字也算 `too_long`）、禁用詞（`banned_word`）、缺字（`missing_glyph`）、新增的價格或優惠（`invented_offer`：`\d` 折、中文數字折、買幾送幾、`NT$`／`$`／元的金額、百分比，且不出現在需求文字、`brief.offer`、`brief.period`）。
- `brief.offer` 有值時 `badge.main` 固定為 offer，不檢查。
- 賣點任一項有問題時，整組改用預設賣點。
- 價格標籤、售價、原價、商品名稱、色票、註記由程式決定；註記用 `buildDisclaimer` 依最後的文案計算。商品名稱移除 emoji，其他缺字保留並記 `product_glyph`（不重問）。
- 版面：8 個元素各一次、整數、寬高 > 0、完全在畫布內、兩兩不相交（`layout_invalid`）；合法時再以 `layoutRuleChecks` 判斷（`layout_rule`，訊息例如「商品框佔畫面 28.0%，品牌規範為 40%–60%」「Logo 與標題間距 12px，需 ≥ 0.5 × Logo 高（38px）」）；再以 `composePoster` 與最後的文案計算字級（`text_too_small`）。任一問題時改用預設版型。`z` 由程式指定。
- 提示詞：`scene` 含非 ASCII 可列印字元時為 `prompt_invalid`，改用 `null`；`negativeExtra` 含非 ASCII 時同樣記 `prompt_invalid` 並捨棄。`injection` 由 `buildInjection` 產生，`ragRefs` 為 `req.ragRefs`。
- `field` 使用 JSON 路徑：`headline.0`、`features.1`、`badge.main`、`priceLabel`、`layout`、`scene`、`productName`。`message` 為中文，可以直接接在重問的提示詞後面，例如「標題第 1 行「…」有伺服器字型沒有的字：「…」，請改用繁體字」。

- [ ] **Step 1: 修改 `web/src/lib/agent/prompt.test.ts`（先寫測試）**

`positivePromptOf(…, null)`、`negativePromptOf` 與 `buildDisclaimer` 和 `buildPromptSpec`／`buildCopy` 的結果相同；`negativePromptOf` 去除重複。

- [ ] **Step 2: 建立 `web/src/lib/agent/guard.test.ts`（先寫測試）**

以 `buildPromptSpec` 的預設結果組出「合格的 draft」當基準，逐條驗證：
1. 合格的 draft：沒有 issues；spec 的文案與 draft 相同、`z` 為 product 1／badge 3／其他 2、`positivePrompt` 含 `scene`、`injection` 與 `buildInjection` 相同；
2. 替代用語每一輪都套用（「根治」→「改善外觀」，沒有 issue）；
3. emoji 移除並記 `emoji_removed`（retry false）；
4. 缺字記 `missing_glyph`（retry true），該欄位改用預設文案；
5. 替代用語之後仍有禁用詞（替代用語沒有涵蓋的詞）記 `banned_word`；
6. 標題第 2 行超過 8、副標超過 22 記 `too_long`；徽章英文含小寫自動轉大寫、不記問題，含中文則記 `too_long`；
7. `brief.offer` 有值時 `badge.main` 為 offer；需求沒有的「8折」「買一送一」「NT$990」「20%」記 `invented_offer`；需求文字有提到的不記；
8. 標題一行空白記 `empty_field`；
9. 商品名稱含 emoji 被移除、含表外字記 `product_glyph`（retry false）且保留原文；
10. 版面少一個元素、重複元素、小數、超出畫布、兩個框相交，各記 `layout_invalid`，版面改用預設版型；
11. 商品框太小（品牌 `productRatio` 改為 `[0.4, 0.6]`）記 `layout_rule`，訊息含百分比；
12. 標題框太扁使字級 < 4% 記 `text_too_small`；
13. `scene` 含中文記 `prompt_invalid`，`positivePrompt` 與模擬版相同；
14. 負向提示詞含 `NEGATIVE_BY_FIX` 與 `negativeExtra` 且不重複；
15. **預設不會被護欄擋下**：3 個示範品牌（含 `brands/my-brand-01.yaml` 的資料，以測試資料表示）× 4 種語氣的預設文案，在 5 個模板的預設版型都沒有 `layout_invalid` 與 `text_too_small`（若不成立，調整 `TEXT_MIN` 並在規格 §12 記錄）。

- [ ] **Step 3: 確認測試失敗**

Run（在 `web/`）：`npx vitest run src/lib/agent`
Expected：FAIL，找不到 `./guard`、`positivePromptOf` 等。

- [ ] **Step 4: 修改 `prompt.ts`，建立 `guard.ts`**

`buildPromptSpec` 的結果不變（golden fixtures 不變）。

- [ ] **Step 5: 確認全部通過**

Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint && npm run fixtures && git status --short contracts/`
Expected：沒有錯誤；fixture 沒有內容上的改變。

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/agent/guard.ts web/src/lib/agent/guard.test.ts web/src/lib/agent/prompt.ts web/src/lib/agent/prompt.test.ts
git commit -m "feat: guard the Gemini prompt spec with copy, layout and prompt rules" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6：composer 端點與 Agent 型別的 golden fixture

**Files:**
- Modify: `web/composer/handlers.ts`、`web/scripts/fixtures.ts`
- Create: `contracts/fixtures/agent.json`（由 `npm run fixtures` 產生）
- Test: `web/composer/handlers.test.ts`、`web/composer/app.test.ts`

**Interfaces:**
- Consumes：Task 3–5。
- Produces（規格 §4.9）：
  - `POST /spec`：`{ draft: SpecDraft, request: GuardRequest }` → `{ spec: PromptSpec, issues: GuardIssue[] }`；
  - `POST /review`：多兩個選填欄位 `vlm: VlmVerdict | null`、`vlmScale: number`（送出圖片與畫布長邊的比例，預設 1）。`vlm` 有值時 VLM 三項用 `geminiVlmChecks`，並以 `expectedSegments(composePoster(spec), { logoImage: brand.logo !== null })` 計算 `ocrDiffs`；`null` 或省略時與 6A 相同；
  - `POST /fixes`：`{ checks, brand, spec }` → `Fix[]`（`planFixes`，與 `/sim/fixes` 相同）；
  - `POST /glyphs`：`{ texts: string[] }` → `{ missing: string[][] }`；
  - 輸入格式不對時丟出中文錯誤（伺服器回 400）：例如 `draft.layout` 不是陣列、`vlm.lines` 不是字串陣列、`texts` 不是字串陣列。
  - `contracts/fixtures/agent.json`：`{ specDraft, guardIssues, vlmVerdict }`。`specDraft` 由 SÉLUNE 的 IG 貼文預設 spec 轉成，`guardIssues` 是 `finalizeSpec` 對一份刻意出錯的 draft 的結果（涵蓋每種 code），`vlmVerdict` 是一份含三種狀態的範例。

- [ ] **Step 1: 修改 `web/composer/handlers.test.ts` 與 `app.test.ts`（先寫測試）**

- `/spec`：合格的 draft 沒有 issues；刻意出錯的 draft 回傳 issues 且 spec 可用；`draft` 缺欄位時回 400 與中文訊息；
- `/review`：`vlm` 為 `null` 時與 6A 的結果相同；`vlm` 三項通過且轉錄正確時 10 項中 VLM 三項通過、說明不含「模擬」、`ocr_typo` 為「0 處差異」；轉錄含「□」時 `ocr_typo` fail、`passed` 為 false；
- `/fixes` 與 `/sim/fixes` 結果相同；
- `/glyphs`：`['晞月', '😀']` 中，第一段沒有缺字；`texts` 不是陣列時回 400；
- `app.test.ts`：經由 HTTP 呼叫 `/spec` 與 `/glyphs`，回應為 JSON。

- [ ] **Step 2: 確認測試失敗**

Run（在 `web/`）：`npx vitest run composer`
Expected：FAIL，`Unknown route: /spec` 等。

- [ ] **Step 3: 修改 `handlers.ts` 與 `scripts/fixtures.ts`**

- [ ] **Step 4: 產生 fixture**

Run（在 `web/`）：`npm run fixtures`
Expected：新增 `contracts/fixtures/agent.json`；其他 fixture 沒有內容上的改變。

- [ ] **Step 5: 確認全部通過**

Run（在 `web/`，有字型）：`npm run test && npm run typecheck && npm run lint`
Expected：沒有錯誤。

- [ ] **Step 6: Commit**

```bash
git add web/composer/handlers.ts web/composer/handlers.test.ts web/composer/app.test.ts web/scripts/fixtures.ts contracts/fixtures/agent.json
git commit -m "feat: add the composer /spec, /fixes and /glyphs endpoints and the VLM verdict in /review" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7：設定、單價表與 `job_usage`

**Files:**
- Create: `pricing.yaml`、`backend/app/usage.py`、`backend/app/repo/usage.py`、`backend/migrations/versions/0003_job_usage.py`
- Modify: `backend/app/settings.py`、`backend/app/db/models.py`、`backend/app/errors.py`、需要明確設定 `agent_mode` 的測試（`tests/conftest.py`、`tests/test_review.py`、`tests/test_worker.py`、`tests/test_api_catalog.py`）
- Test: `backend/tests/test_settings.py`、`backend/tests/test_usage.py`（不需要資料庫）、`backend/tests/test_usage_db.py`（需要資料庫）

**Interfaces:**
- Produces：
  - `pricing.yaml`（規格 §4.7 的內容與註解）。
  - `backend/app/settings.py`：
    - `AgentMode = Literal['gemini', 'sim']`；`agent_mode: AgentMode = 'gemini'`；
    - `gemini_api_key: SecretStr = SecretStr('')`、`gemini_llm_model = 'gemini-3.8-flash'`、`gemini_vlm_model = 'gemini-3.8-flash'`、`gemini_timeout_seconds: float = 60`、`gemini_max_retries: int = 3`、`gemini_concurrency: int = 4`、`gemini_job_budget_usd: float = 1`、`gemini_monthly_budget_usd: float = 20`、`pricing_file: Path = REPO_ROOT / 'pricing.yaml'`；
    - `model_validator`：`agent_mode == 'gemini'` 且 `review_mode == 'sim'` 時丟出「AGENT_MODE=gemini 需要 REVIEW_MODE=composer（目前為 sim）：請改為 REVIEW_MODE=composer，或設定 AGENT_MODE=sim」。`settings = Settings()` 在匯入時建立，所以 api 與 worker 會在啟動時失敗並顯示原因。
  - `backend/app/errors.py`：`BudgetExceeded(AppError)`（status 429、code `budget_exceeded`）。
  - `backend/app/usage.py`：
    - `PRICING_TZ = ZoneInfo('Asia/Taipei')`；
    - `Price`（`from_`（alias `from`）: date、`input`、`output`、`cached_input: float | None`）；`Pricing.load(path)`（Pydantic 驗證；檔案不存在或格式錯誤時丟出中文的 `PricingError`）；`Pricing.has(model)`；`Pricing.price(model, at: datetime) -> Price`（取台北時間 `at` 當天已生效的最新一筆）；
    - `cost_usd(price, input_tokens, cached_tokens, output_tokens) -> Decimal`：規格 §4.7 的公式，`ROUND_HALF_UP` 到小數 6 位；
    - `month_bounds(now, tz=PRICING_TZ) -> tuple[datetime, datetime]`（UTC 的開始與結束）；
    - `@dataclass(frozen=True) UsageScope(job_id: str | None, brand_id: str, round: int | None, target: str | None)`；`@dataclass(frozen=True) TokenUsage(input_tokens, cached_tokens, output_tokens, thinking_tokens)`（`output_tokens` 含思考）；
    - `class UsageRecorder(Protocol)`：`async check(scope) -> None`、`async record(scope, kind, model, usage) -> Decimal`；
    - `class UsageLedger(UsageRecorder)`：`__init__(db, pricing, *, job_budget, monthly_budget, clock=utc_now)`；`check` 依序檢查每月與單一任務（只在 `job_id` 有值時），達到上限丟出 `BudgetExceeded`（訊息見規格 §4.7，金額兩位小數）；`record` 依當時的單價寫入一筆並回傳費用；`month_total()`；`job_summary(job_id) -> tuple[Decimal, int]`；`costs_by_job(job_ids) -> dict[str, float]`。上限為 0 時不檢查。
  - `backend/app/db/models.py`：`JobUsageRow`（規格 §4.7 的欄位；`job_id` 參照 `jobs.id` ON DELETE CASCADE、可為空；`created_at` 有索引）。
  - `backend/app/repo/usage.py`：`add_usage`、`job_total`、`range_total(start, end)`、`costs_by_job`。
  - `0003_job_usage.py`：建立資料表與索引；downgrade 刪除。

- [ ] **Step 1: 建立 `backend/tests/test_settings.py`（先寫測試）**

- 預設 `agent_mode` 為 `gemini`、`review_mode` 為 `composer`；
- `agent_mode='gemini', review_mode='sim'` 丟出 `ValidationError`，訊息含「REVIEW_MODE=composer」；
- `agent_mode='sim', review_mode='sim'` 合法；
- `repr(Settings(gemini_api_key='AIza-test-1234'))` 不含 key。

- [ ] **Step 2: 建立 `backend/tests/test_usage.py`（先寫測試，不需要資料庫）**

- `Pricing.load` 讀 repo 的 `pricing.yaml`；2026-12-31 23:59（台北）用 0.75／3.75，2027-01-01 00:00（台北，即 UTC 2026-12-31 16:00）用 1.50／7.50；
- 沒有該模型時 `has` 為 false、`price` 丟出 `PricingError`；格式錯誤的 YAML 丟出中文錯誤；
- `cost_usd`：輸入 4,120（快取 1,000）、輸出 1,032，在 `cachedInput` 省略與設定為 0.1875 時的金額；四捨五入到 6 位；
- `month_bounds`：台北時間 11/01 00:30（UTC 10/31 16:30）屬於 11 月；邊界的開始與結束。

- [ ] **Step 3: 建立 `backend/tests/test_usage_db.py`（先寫測試，需要資料庫）**

- `UsageLedger.record` 寫入一筆，`cost_usd` 依當時單價；
- `check`：單一任務達到上限時丟出 `BudgetExceeded`，訊息為「已達單一任務的 Gemini 費用上限（US$1.00，已用 US$1.02）」；
- 每月加總只算台北時間當月（含 `job_id` 為空的紀錄），上個月的紀錄不算；達到上限時訊息為「本月 Gemini 費用已達上限（US$20.00）」；
- 上限為 0 時不檢查；
- 刪除任務時用量一併刪除；`costs_by_job` 沒有紀錄的任務不出現。

- [ ] **Step 4: 修改現有測試的 `Settings`**

`conftest.py` 的 `BASE_SETTINGS` 與 api fixture、`test_review.py`、`test_worker.py`、`test_api_catalog.py` 建立 `Settings` 的地方都明確加上 `agent_mode`（模擬版的測試用 `'sim'`；`review_mode='sim'` 時一定是 `'sim'`）。

- [ ] **Step 5: 確認測試失敗**

Run（在 `backend/`）：`uv run pytest tests/test_settings.py tests/test_usage.py -q`
Expected：FAIL，`agent_mode` 與 `app.usage` 不存在。

- [ ] **Step 6: 建立與修改程式，加上 migration**

- [ ] **Step 7: 確認全部通過**

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest tests/test_settings.py tests/test_usage.py tests/test_contract.py tests/test_stats.py -q`
Expected：沒有錯誤。`test_usage_db.py` 與其他需要資料庫的測試在有 docker compose 的環境執行（本機未執行）。

- [ ] **Step 8: Commit**

```bash
git add pricing.yaml backend/app/settings.py backend/app/usage.py backend/app/repo/usage.py backend/app/db/models.py backend/app/errors.py backend/migrations/versions/0003_job_usage.py backend/tests
git commit -m "feat: add AGENT_MODE, the Gemini settings, the pricing table and job_usage" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8：`GeminiClient`

**Files:**
- Create: `backend/app/adapters/gemini.py`、`backend/app/validation.py`、`backend/tests/data/gemini/*.json`
- Modify: `backend/pyproject.toml`、`backend/uv.lock`（`uv add google-genai==2.33.0`、`uv add --dev respx==0.23.1`）
- Test: `backend/tests/test_gemini_client.py`、`backend/tests/test_validation.py`

**Interfaces:**
- Consumes：Task 7 的 `UsageRecorder`、`UsageScope`、`TokenUsage`、`BudgetExceeded`、`Settings`；`RunContext`（本 Task 先在 `ports.py` 加上 `job_id` 與 `wait` 的宣告，Task 9 實作 `JobRun.wait`）。
- Produces：
  - `backend/app/validation.py`：`describe_error(error: ErrorDetails) -> str` 與 `describe_errors(errors) -> str`（規格 §8：依 `type` 轉中文；`value_error` 去掉「Value error, 」；沒有對應的保留原文；位置為 JSON 路徑並去掉開頭的 `body`）。
  - `backend/app/adapters/gemini.py`：
    - `GeminiKind = Literal['brief', 'spec', 'rewrite', 'vlm']`；`KIND_LABEL`（需求拆解、Prompt 構建、Query Rewriting、VLM 審查）；`THINKING: dict[GeminiKind, ThinkingLevel]`（實驗決定；先用 brief LOW、spec HIGH、rewrite LOW、vlm LOW）；
    - `@dataclass(frozen=True) GeminiCall(Generic[T])`：`kind`、`model`、`system: str`、`parts: list[types.Part | str]`、`schema: type[T]`、`scope: UsageScope`、`seed: int | None`；
    - `class LlmClient(Protocol)`：`async generate(call: GeminiCall[T], run: RunContext) -> T`；
    - `class GeminiClient(LlmClient)`：`__init__(settings, usage: UsageRecorder, *, http: httpx.AsyncClient | None = None, backoff=(1.0, 2.0, 4.0), jitter=0.2)`；`generate`；`check_model(model) -> None`（`client.aio.models.get`，不計費）；`aclose()`；`configured: bool`（有沒有 key）；
    - `GeminiError(AppError)`；`NOT_CONFIGURED`（「未設定 GEMINI_API_KEY：在 .env 加入後重新啟動 api 與 worker，或設 AGENT_MODE=sim」）；`INTERRUPTED_NOTE`（「已中斷進行中的 Gemini 呼叫，這次呼叫可能仍會計費（未記錄用量）」）；
    - `usage_message(model, usage, cost) -> str`：「gemini-3.8-flash：輸入 4,120（快取 0）／輸出 1,032（思考 640）tokens・US$0.0070」。

**`generate` 的流程**（規格 §4.2）：
1. 沒有 key 時丟出 `GeminiError(NOT_CONFIGURED)`；以 `usage.check(scope)` 檢查上限（`BudgetExceeded` 直接往外丟）。
2. 取得 semaphore（`gemini_concurrency`）後送出：`GenerateContentConfig(system_instruction, response_mime_type='application/json', response_json_schema=gemini_schema(schema), seed, thinking_config=ThinkingConfig(thinking_level=THINKING[kind]))`。SDK 的 `retry_options.attempts=1`（重試由我們處理），並傳入自己的 `httpx.AsyncClient`（respx 可以攔截）。每次請求以 `run.wait(asyncio.wait_for(…, gemini_timeout_seconds), note=INTERRUPTED_NOTE)` 等待。
3. 錯誤處理：
   - 429、5xx、逾時與連線錯誤：依 `backoff` 重試 `gemini_max_retries` 次（±`jitter`）；429 的 `RetryInfo.retryDelay` 有值時採用，最長 60 秒；退避也經過 `run.wait`。用完時「Gemini 暫時無法使用（HTTP 503），已重試 3 次」或「Gemini 沒有在 60 秒內回應，已重試 3 次」；
   - 400：「Gemini 請求錯誤：…」；401、403：「Gemini API key 無效或沒有權限」；404：「找不到 Gemini 模型：gemini-x」；不重試；
   - `prompt_feedback.block_reason` 有值，或 `finish_reason` 為 SAFETY、PROHIBITED_CONTENT、BLOCKLIST、SPII、IMAGE_SAFETY：「Gemini 拒絕產生內容（安全性過濾）」，不重試。
4. 每個有回應的請求都以 `usage.record` 寫入並以 `run.log`（brief、spec、rewrite 為 `agent`，vlm 為 `vlm`）送出 `usage_message`。
5. 以 `schema.model_validate_json` 驗證；失敗時把這次的回應（model 角色）與「上一次的回應格式錯誤：{describe_errors}。請修正後重新輸出完整的 JSON」（user 角色）接在對話後面重問一次；仍失敗時丟出「Gemini 回應格式錯誤（Prompt 構建）：layout.3.bbox：長度必須是 4」。
6. 所有丟出的錯誤訊息與 log 都經過 `redact`（把 key 換成 `***`）。

**respx 的回應**：`backend/tests/data/gemini/` 的 JSON 檔為 `{ status, body }`（`generateContent` 的 REST 回應）。沒有 key 時依 Gemini REST 文件手寫，Task 1 以錄製腳本取代。檔案：`spec-ok.json`（含 `cachedContentTokenCount` 與 `thoughtsTokenCount`）、`spec-invalid.json`（格式錯誤的 JSON）、`error-429.json`（含 `RetryInfo`）、`error-503.json`、`error-401.json`、`error-404.json`、`blocked.json`（`promptFeedback.blockReason`）、`model.json`（`models.get`）。

- [ ] **Step 1: 建立 `backend/tests/test_validation.py`（先寫測試）**

`missing`、`literal_error`、`too_short`／`too_long`（含上下限相同時「長度必須是 4」）、`greater_than_equal`、`int_parsing`、`value_error`（去掉「Value error, 」）、不認得的類型保留原文；位置 `('body', 'templateIds', 0)` →「templateIds.0」。

- [ ] **Step 2: 建立 `backend/tests/test_gemini_client.py`（先寫測試，respx 重播，不需要資料庫）**

以記憶體版的 `UsageRecorder`（記錄 `check` 與 `record` 的呼叫）與假的 `RunContext`（記錄 log；`wait` 直接 await，或在設定取消時中斷並丟出 `JobCancelled`）測試：
- 結構化輸出解析成 Pydantic 物件；請求本文含 `responseJsonSchema`、`seed`、`thinkingConfig`、`systemInstruction`；
- 用量：`input 4120、cached 1000、output = candidates + thoughts、thinking`；log 與 `usage_message` 相同；
- 429（`retryDelay` 2 秒，測試把等待換成記錄）後成功；
- 503 超過重試次數後失敗，訊息含「已重試 3 次」；用量只記錄有回應的那幾次（錯誤回應沒有用量時不記錄）；
- 格式錯誤時重問：第二次請求的 `contents` 含第一次的回應與中文的錯誤說明；兩次都寫入用量；兩次都錯時訊息為「Gemini 回應格式錯誤（Prompt 構建）：…」；
- 安全性過濾、401、404 的中文原因，且都不重試（respx 的 call 次數為 1）；
- 逾時（`gemini_timeout_seconds=0.05`、respx 延遲回應）重試後失敗；
- 取消：等待中設定取消旗標 → 進行中的請求被取消、丟出 `JobCancelled`、送出 `INTERRUPTED_NOTE` 警告、沒有寫入用量；
- 超過上限：`check` 丟出 `BudgetExceeded` 時不送出請求；
- 沒有 key：丟出 `NOT_CONFIGURED`，不送出請求；
- key（`AIza-test-key-0000`）不出現在任何錯誤訊息與 log（含 SDK 例外的訊息）；
- `check_model`：200 時通過；404 丟出「找不到 Gemini 模型」。

- [ ] **Step 3: 確認測試失敗**

Run（在 `backend/`）：`uv run pytest tests/test_validation.py tests/test_gemini_client.py -q`
Expected：FAIL，找不到 `app.validation` 與 `app.adapters.gemini`。

- [ ] **Step 4: 加入套件，建立程式與回應檔**

Run（在 `backend/`）：`uv add google-genai==2.33.0 && uv add --dev respx==0.23.1`
確認 SDK 的非同步 client 使用 httpx（沒有安裝 aiohttp）；在 `ports.py` 的 `RunContext` 加上 `job_id` 與 `wait` 的宣告，並把 `JobCancelled` 從 runner 移到 `ports.py`（`GeminiClient` 與 runner 共用，runner 繼續匯出同一個類別）。`gemini_schema(model)`（展開 `$ref`、去掉 `title` 與 `default`）放在本 Task 的 `gemini.py`，Task 10 的型別直接使用。

- [ ] **Step 5: 確認全部通過**

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest tests/test_validation.py tests/test_gemini_client.py tests/test_settings.py tests/test_usage.py -q`
Expected：沒有錯誤。

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/adapters/gemini.py backend/app/validation.py backend/app/pipeline/ports.py backend/tests/test_gemini_client.py backend/tests/test_validation.py backend/tests/data/gemini
git commit -m "feat: add the Gemini client with retries, cancellation, budgets and usage" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9：任務流程的介面與 runner

**Files:**
- Modify: `backend/app/pipeline/ports.py`、`backend/app/pipeline/runner.py`、`backend/app/pipeline/sim.py`、`backend/app/pipeline/review.py`、`backend/app/worker.py`（`run_job` 的新參數）
- Test: `backend/tests/test_pipeline.py`（需要資料庫）、`backend/tests/test_runner_order.py`（不需要資料庫）

**Interfaces:**
- Consumes：Task 7 的 `UsageLedger`（只用 `job_summary`）。
- Produces（規格 §4.8）：
  - `ports.py`：
    - `RunContext`：`job_id: str`；`async wait(awaitable, note: str | None = None) -> T`（可取消的等待：每 0.5 秒檢查取消旗標；取消時中斷 awaitable，`note` 有值時先寫入 warn log，再丟出 `JobCancelled`）；
    - `PreviousRound(spec: PromptSpec, checks: list[ReviewCheck], fixes: list[Fix])`；
    - `SpecRequest` 加上 `text: str`（使用者的一句話）、`hits: list[RagHit]`、`previous: PreviousRound | None`；
    - `Agent.build_spec(request, run)`、`Agent.plan_rewrite(brand, spec, checks, run, *, retries_left: int)`；`Reviewer.review(brand, render, seed, poster, run)`；
    - `class UsageReport(Protocol)`：`async job_summary(job_id) -> tuple[Decimal, int]`；`Ports.usage: UsageReport | None = None`。
  - `runner.py`：
    - `run_job(…, *, speed, pace_phases: bool = True)`：`False` 時跳過 `PHASE_MS` 的等待（`JobRun.phase`），生圖的進度（`run.pace`）照舊；
    - `JobRun.wait`：使用 `checkpoint()`，取消時以 `store.append` 直接寫入 `note`（不經過 `emit` 的取消檢查）；
    - `ordered(awaitables) -> AsyncIterator[T]`：全部並行，依原本順序逐一產出；任一個失敗時取消其他的並丟出原本的例外；
    - Prompt 構建與審查改用 `ordered`：seed 仍依模板順序先取好；事件依模板與候選順序送出，前面的完成就送；
    - 每個未通過的模板保存 `PreviousRound`（最高分候選的 spec、檢查結果與這一輪的修正項），放進下一輪的 `SpecRequest.previous`；`hits` 為 Rerank 後前 5 筆加上重新檢索的切塊；
    - `saving` 階段：`ports.usage` 有值且有呼叫紀錄時送出「本任務 Gemini 費用 US$0.18（17 次呼叫）」。
  - `sim.py`、`review.py`：`SimAgent`、`SimReviewer`、`ComposerReviewer` 接受新參數但不使用；`SimAgent.build_spec` 只傳原本的欄位給 `/sim/prompt`。

- [ ] **Step 1: 建立 `backend/tests/test_runner_order.py`（先寫測試，不需要資料庫）**

`ordered`：後面的先完成時仍依序產出；第二個失敗時取消第三個並丟出原本的例外；空清單。

- [ ] **Step 2: 修改 `backend/tests/test_pipeline.py`（先寫測試，需要資料庫）**

- 既有的替身改用新簽名；
- Prompt 構建並行：第 2 個模板先完成，`prompt.generated` 仍依模板順序；
- 審查並行：候選的事件依候選順序，且每個候選的 `review.check` 與 `review.completed` 相連；
- 第 2 輪的 `SpecRequest.previous` 為第 1 輪最高分候選的 spec、檢查結果與修正項；`hits` 含重新檢索的切塊；`text` 為需求文字；
- `pace_phases=False` 且 `speed=1` 時任務在 1 秒內完成（生圖的替身不等待）；
- `wait`：替身的 `build_spec` 等待 10 秒，期間設定取消 → 1 秒內 `job.status cancelled`，`note` 的 warn log 在它之前；
- 替身丟出 `BudgetExceeded` → `job.failed` 的原因為中文訊息；
- `Ports.usage` 回傳（0.18, 17）時 `saving` 階段有合計的 log。

- [ ] **Step 3: 確認測試失敗**

Run（在 `backend/`）：`uv run pytest tests/test_runner_order.py -q`
Expected：FAIL，找不到 `ordered`。

- [ ] **Step 4: 修改程式**

- [ ] **Step 5: 確認模擬模式的事件不變（本機驗證，不進 git）**

在 scratchpad 寫一個腳本：以記憶體版的 `JobRun`（記錄事件、不連資料庫、不等待）執行 `_pipeline`，搭配 `sim_ports` 與本機 composer（`npm run composer`），輸入取自三個 golden timelines，比較事件（去掉 `seq`、`ts`）與 fixture 完全相同。

- [ ] **Step 6: 確認全部通過**

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest tests/test_runner_order.py tests/test_gemini_client.py -q`
Expected：沒有錯誤。`test_pipeline.py`、`test_parity.py`、`test_worker.py` 在有 docker compose 的環境執行（本機未執行）。

- [ ] **Step 7: Commit**

```bash
git add backend/app/pipeline backend/app/worker.py backend/tests/test_pipeline.py backend/tests/test_runner_order.py
git commit -m "feat: run prompt building and review in parallel with cancellable waits and previous-round context" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10：提示詞與 `GeminiAgent`

**Files:**
- Create: `backend/app/pipeline/gemini_types.py`、`backend/app/pipeline/gemini.py`、`backend/app/pipeline/prompts/brief.md`、`spec.md`、`rewrite.md`、`backend/tests/fake_gemini.py`
- Modify: `backend/app/adapters/composer.py`
- Test: `backend/tests/test_gemini_types.py`、`backend/tests/test_gemini_agent.py`（需要 composer，不需要資料庫）

**Interfaces:**
- Consumes：Task 6 的 composer 端點與 `contracts/fixtures/agent.json`；Task 8 的 `LlmClient`、`GeminiCall`；Task 9 的介面。
- Produces：
  - `gemini_types.py`：`BriefDraft`（`sellingPoints` 0–3、`audience` ≤ 20、`tone`、`campaign`／`offer`／`period` 可為 null、`style` 0–5）、`SpecDraft`（`layout` 剛好 8 筆、`bbox` 4 個整數、`scene` ≤ 300、`negativeExtra` ≤ 200；長度與內容的規則由護欄處理）、`RewriteDraft`（`fixes: [{ checkId, title, desc }]`、`requery`）、`VlmVerdict`、`GuardIssue`。都繼承 `app.contract.Model`（camelCase）。
  - `composer.py`：
    - `brand_json(brand)`：只保留每個 tag 第一個非 `-alt` 的切塊（規格 §8）；所有送給 composer 的品牌都改用它；
    - `spec(draft, request) -> tuple[PromptSpec, list[GuardIssue]]`、`fixes(checks, brand, spec) -> list[Fix]`、`glyphs(texts) -> list[list[str]]`、`review(spec, brand, measured_primary, vlm=None, vlm_scale=1.0)`。
  - `prompts/*.md`：系統指示（繁體中文），說明角色、每個欄位的規則與限制、品牌規範的用法、輸出必須符合 JSON schema。動態的資料（品牌、商品、需求、模板與預設版型、引用的規範、上一輪的結果）以 JSON 放在 user 訊息，系統指示固定，讓隱式快取有機會命中。
  - `gemini.py`：
    - `load_prompt(name) -> str`；
    - `guard_brief(draft, text, product) -> ParsedBrief`（規格 §4.3 的四條護欄）；
    - `class GeminiAgent(Agent)`：`__init__(client: LlmClient, composer, settings)`；
      - `parse_brief(brand, text, product)`：`run` 為不檢查取消、log 寫到 logger 的 `BriefRun`；`UsageScope(job_id=None, brand_id, round=None, target=None)`；
      - `build_spec(request, run)`：組出 user 訊息（含 composer `/layout` 的預設版型、商品圖的長寬比、`request.hits` 的全文、`request.previous`）；呼叫 `kind='spec'`、`target=template.id`；送 `/spec`；第一次有 `retry` 問題時把問題說明接在對話後面重問一次，第二次直接使用回傳的 spec；每個問題送出 warn log「護欄：{message}，{處理方式}」（文案欄位「已改用預設文案」、版面「已改用預設版型」、提示詞「已改用預設提示詞」、`emoji_removed`「已移除」、`product_glyph`「保留原文」；第一次重問前的問題不送 log，只記錄重問）；`rationale` 以 info log 顯示；
      - `plan_rewrite(brand, spec, checks, run, *, retries_left)`：呼叫 `kind='rewrite'`；護欄（規格 §4.5）：移除不是未通過檢查的 `checkId`；每個未通過的檢查至少一個修正（沒有的以 `/fixes` 逐項補上）；同一個檢查的多個修正合併（保留第一個的標題，說明以「；」相連）；`title` 超過 8 字、`desc` 超過 80 字時截斷；`banned_words` 或 `vlm_exaggeration` 未通過而 `requery` 為 null 時改用「{類別} 禁用詞 合規替代用語」。
    - 商品圖的長寬比：示範商品為 500 × 800（`productArtSvg` 的尺寸）；上傳商品有去背圖時取不透明區域的外框，否則為照片尺寸（Pillow，在執行緒中讀取）。
  - `tests/fake_gemini.py`：`FakeGemini(LlmClient)`：依 `kind` 從佇列取出預先寫好的結果（Pydantic 物件、dict 或例外），記錄收到的 `GeminiCall`；佇列空時丟出明確的錯誤。

- [ ] **Step 1: 建立 `backend/tests/test_gemini_types.py`（先寫測試）**

- `contracts/fixtures/agent.json` 的 `specDraft`、`guardIssues`、`vlmVerdict` 都能解析，`to_json()` 後與原本相同；
- `gemini_schema(SpecDraft)` 沒有 `$ref`、`$defs` 與 `title`，`layout` 的 `minItems`／`maxItems` 為 8；
- `BriefDraft` 的 `tone` 不在四種之內時驗證失敗。

- [ ] **Step 2: 建立 `backend/tests/test_gemini_agent.py`（先寫測試）**

使用 `composer_url` fixture（需要字型）、`FakeGemini` 與假的 `RunContext`：
- `guard_brief`：沒有商品時 `productName` 為 null；`sellingPoints` 為空時用商品特色前 3 個；需求沒有數字時 `period` 為 null；`style` 只保留英文單字、轉小寫、去除重複；
- `parse_brief` 的 `GeminiCall`：`kind='brief'`、`scope.job_id` 為 None、user 訊息含品牌的四種語氣說明與商品特色；
- `build_spec`：
  - 合格的 draft 一次完成，回傳的 spec 文案與 draft 相同；`GeminiCall.scope.target` 為模板 id；user 訊息含 `hits` 全文與預設版型、不含 `guidelineChunks` 的其他切塊；
  - 第一次含缺字與商品框太小 → 重問一次，第二次的 user 訊息含兩個問題的中文說明；第二次合格時沒有 warn log；
  - 第二次仍有問題 → 使用預設文案與預設版型，warn log 含「已改用預設文案」「已改用預設版型」；
  - `previous` 有值時 user 訊息含上一輪的文案、版面、未通過的檢查與修正項；
- `plan_rewrite`：移除不相關的 `checkId`；缺少的檢查以 `/fixes` 補上；同一檢查的兩個修正合併；`banned_words` 未通過而 `requery` 為 null 時改用預設查詢；
- `brand_json`：含 `-alt` 與重複 tag 的品牌只留每個 tag 的第一個切塊。

- [ ] **Step 3: 確認測試失敗**

Run（在 `backend/`，`POSTER_FONTS_DIR` 指向字型資料夾）：`uv run pytest tests/test_gemini_types.py tests/test_gemini_agent.py -q`
Expected：FAIL，找不到 `app.pipeline.gemini_types` 與 `app.pipeline.gemini`。

- [ ] **Step 4: 建立型別、提示詞與 `GeminiAgent`，修改 composer 用戶端**

- [ ] **Step 5: 確認全部通過**

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest tests/test_gemini_types.py tests/test_gemini_agent.py tests/test_gemini_client.py tests/test_runner_order.py -q`
Expected：沒有錯誤。

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline/gemini_types.py backend/app/pipeline/gemini.py backend/app/pipeline/prompts backend/app/adapters/composer.py backend/tests/fake_gemini.py backend/tests/test_gemini_types.py backend/tests/test_gemini_agent.py
git commit -m "feat: add the Gemini agent with prompts for brief parsing, prompt building and query rewriting" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11：`GeminiReviewer`

**Files:**
- Create: `backend/app/pipeline/prompts/vlm.md`
- Modify: `backend/app/pipeline/gemini.py`
- Test: `backend/tests/test_gemini_reviewer.py`（需要 composer，不需要資料庫）

**Interfaces:**
- Consumes：Task 6 的 `/render` 與 `/review`（`vlm`）、Task 10。
- Produces：
  - `VLM_MAX_SIDE: int | None = None`（實驗決定；None 為原尺寸）；
  - `class GeminiReviewer(Reviewer)`：`__init__(client, composer, settings)`；`review(brand, render, seed, poster, run)`：
    1. 沒有 poster 時丟出與 `ComposerReviewer` 相同的錯誤；
    2. 以 `resolve_url` 讀審查用海報 PNG（在執行緒中）；`VLM_MAX_SIDE` 有值且長邊較大時縮小，`scale = 送出長邊 ÷ 畫布長邊`；
    3. user 訊息：圖片（`image/png`）與 JSON：品牌類別、禁用詞、效果宣稱詞、註記用語、圖片尺寸、8 個元素的中文名稱與方框（換算成送出圖片的座標）；**不提供預期文案**；
    4. `kind='vlm'`、`target=render.id`；
    5. 以 `composer.review(spec, brand, poster.measured_primary, vlm=verdict, vlm_scale=scale)` 取得 10 項檢查與分數；
    6. Gemini 呼叫失敗（`AppError`，不含 `BudgetExceeded` 與取消）時改丟「Gemini 無法審查海報：…」；composer 失敗時與 `ComposerReviewer` 相同。

- [ ] **Step 1: 建立 `backend/tests/test_gemini_reviewer.py`（先寫測試）**

以 composer 的 `/render` 在 `tmp_path` 畫一張 SÉLUNE 的海報當 poster：
- 轉錄與文案相同、三項通過 → 10 項檢查，VLM 三項的說明不含「模擬」，`ocr_typo` 為「0 處差異」；
- 轉錄的標題錯一個字 → `ocr_typo` warn；含「□」→ fail、`passed` false；
- `GeminiCall`：`kind='vlm'`、`target` 為候選 id、parts 含 PNG 位元組、user 訊息的方框座標與畫布一致（`VLM_MAX_SIDE` 為 None）；把 `VLM_MAX_SIDE` 設為 1024 時圖片長邊為 1024、座標等比例縮小、`vlmScale` 傳給 composer；
- user 訊息不含標題與副標的文字；
- FakeGemini 丟出 `GeminiError('…')` → 原因以「Gemini 無法審查海報：」開頭；丟出 `BudgetExceeded` 時原樣往外丟。

- [ ] **Step 2: 確認測試失敗**

Run（在 `backend/`）：`uv run pytest tests/test_gemini_reviewer.py -q`
Expected：FAIL，找不到 `GeminiReviewer`。

- [ ] **Step 3: 建立 `prompts/vlm.md`，實作 `GeminiReviewer`**

- [ ] **Step 4: 確認全部通過**

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest tests/test_gemini_reviewer.py tests/test_gemini_agent.py -q`
Expected：沒有錯誤。

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/gemini.py backend/app/pipeline/prompts/vlm.md backend/tests/test_gemini_reviewer.py
git commit -m "feat: review posters with the Gemini VLM and compare its transcription" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12：選用、需求拆解與建立任務的拒絕條件、驗證訊息中文化

**Files:**
- Modify: `backend/app/worker.py`、`backend/app/api/services.py`、`backend/app/api/jobs.py`、`backend/app/api/main.py`、`backend/app/api/catalog.py`（`api_options`）
- Test: `backend/tests/test_worker.py`、`backend/tests/test_api_jobs.py`、`backend/tests/test_api_catalog.py`（需要資料庫）、`backend/tests/test_services.py`（不需要資料庫）

**Interfaces:**
- Produces：
  - `app/pipeline/gemini.py`：`gemini_ports(base: Ports, client, composer, settings, ledger) -> Ports`（換掉 agent、reviewer，加上 `usage`）。
  - `worker.build_services`：依規格 §4.1 的表選擇；`AGENT_MODE=gemini` 時建立 `Pricing`、`UsageLedger` 與一個 `GeminiClient`（每個 worker 共用 semaphore），`run_job` 傳 `pace_phases=settings.agent_mode == 'sim'`；結束時關閉 client。
  - `api.services.start_services`：`agent` 依 `AGENT_MODE`；`ApiServices` 加上 `gemini: GeminiClient | None`、`ledger: UsageLedger | None`、`pricing_error: str | None`（單價表讀不到或沒有該模型時的原因；這時所有 Gemini 呼叫都被拒絕，系統狀態顯示）。
  - `POST /api/briefs/parse`：`asyncio.wait_for(…, 90)`；逾時「Gemini 沒有在 90 秒內完成需求拆解，請稍後再試」（503 `unavailable`）；`GeminiError` 為 503；`BudgetExceeded` 為 429；沒有 key 為 503，訊息為 `NOT_CONFIGURED`。
  - `POST /api/jobs`：`AGENT_MODE=gemini` 時，沒有 key、單價表有問題（503）、本月已達上限（429，訊息「本月 Gemini 費用已達上限（US$20.00）」）時拒絕，不建立任務。
  - `api_options`：`gemini` 時 `llm`、`vlm` 為設定的模型 ID；`sim` 時不變。
  - `main.py`：`invalid_request` 改用 `describe_errors`（規格 §8），例如「請求格式錯誤：templateIds.0：必須是 ecom-main、scene、ig-post、story、banner 其中之一」。

- [ ] **Step 1: 建立 `backend/tests/test_services.py`（先寫測試，不需要資料庫）**

`gemini_ports`：agent 為 `GeminiAgent`、reviewer 為 `GeminiReviewer`、retriever 與 image 沿用、`usage` 為 ledger；`api_options` 在兩種模式的結果。

- [ ] **Step 2: 修改需要資料庫的測試（先寫測試）**

- `test_worker.py`：`build_services` 在 `sim`／`composer`、`sim`／`sim`、`gemini`／`composer`（有 key）三種組合的 agent 與 reviewer 類別；
- `test_api_jobs.py`：需求拆解以假的 agent 模擬逾時（把 90 秒換成測試用的常數）→ 503；`BudgetExceeded` → 429；建立任務在沒有 key 時 503、本月已達上限時 429（以寫入 `job_usage` 的紀錄觸發）；`templateIds` 錯誤的 400 訊息為中文；
- `test_api_catalog.py`：`/api/options` 在 gemini 模式為模型 ID。

- [ ] **Step 3: 確認測試失敗**

Run（在 `backend/`）：`uv run pytest tests/test_services.py -q`
Expected：FAIL，找不到 `gemini_ports`。

- [ ] **Step 4: 修改程式**

- [ ] **Step 5: 確認全部通過**

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest tests/test_services.py tests/test_validation.py -q`
Expected：沒有錯誤。需要資料庫的測試在有 docker compose 的環境執行（本機未執行）。

- [ ] **Step 6: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: select the Gemini agent and reviewer by AGENT_MODE and reject briefs and jobs without a key or budget" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13：系統狀態、儀表板的實際用量與前端標示

**Files:**
- Modify: `backend/app/api/catalog.py`、`backend/app/api/jobs.py`（`/api/stats`）、`backend/app/stats.py`、`web/src/components/dashboard/kpi-cards.tsx`
- Test: `backend/tests/test_stats.py`（不需要資料庫）、`backend/tests/test_status_gemini.py`（不需要資料庫）、`backend/tests/test_api_catalog.py`、`backend/tests/test_api_jobs.py`（需要資料庫）、`web/src/components/dashboard/kpi-cards` 的測試（若現有測試涵蓋標示）

**Interfaces:**
- Produces：
  - `stats.py`：`dashboard_stats(snaps, usage_costs: dict[str, float] | None = None)`；有傳入時每個任務的 `costUsd` 為 `usage_costs.get(job_id, 0)`，否則依事件估算（與 TypeScript 相同，parity 不變）。
  - `/api/stats`：一律傳入 `job_usage` 的加總（沒有紀錄的任務為 0）。
  - `catalog._gemini(services)`（取代 `SIMULATED` 的 Gemini 一項，ComfyUI 仍為模擬）：
    - `sim`：`('sim', 'AGENT_MODE=sim：模擬 Agent 與 VLM 審查')`；
    - 沒有 key：error，`NOT_CONFIGURED`；
    - 單價表有問題：error，原因；
    - `check_model`（LLM 與 VLM 模型，結果快取 60 秒）失敗：error，例如「Gemini API key 無效或沒有權限」「找不到 Gemini 模型：gemini-x」；
    - 正常：「LLM／VLM gemini-3.8-flash・本月 US$1.23／上限 US$20・key …a1B2」（兩個模型不同時「LLM gemini-a／VLM gemini-b」；上限為 0 時「不設上限」）。
  - `catalog._brands`：以 composer `/glyphs` 檢查每個品牌的預設文案、註記用語與替代用語；有缺字時在說明後面加上「；Kayla 精緻少女 的預設文案有伺服器字型沒有的字：「…」」，狀態不變。composer 沒有回應時略過檢查。
  - `kpi-cards.tsx`：`API_MODE === 'live'` 時說明為「依實際用量：Gemini 呼叫的費用，攤到每張交付圖」，mock 維持「估算：…」。

- [ ] **Step 1: 修改 `backend/tests/test_stats.py`（先寫測試）**

不傳 `usage_costs` 時與 fixture 相同；傳入時 `costPerImage` 與 `recent[].costUsd` 依實際用量，沒有紀錄的任務為 0。

- [ ] **Step 2: 建立 `backend/tests/test_status_gemini.py`（先寫測試）**

以簡單的替身（`settings`、`gemini`、`ledger`）呼叫 `_gemini`，涵蓋上面五種結果；`check_model` 在 60 秒內只呼叫一次；說明不含完整的 key。

- [ ] **Step 3: 修改需要資料庫的測試**

`/api/status` 的 gemini 項目（測試的 api fixture 為 `AGENT_MODE=sim`）；品牌設定檔的缺字警告（測試品牌加上表外的字）；`/api/stats` 在有 `job_usage` 時的 `costPerImage`。

- [ ] **Step 4: 確認測試失敗**

Run（在 `backend/`）：`uv run pytest tests/test_stats.py tests/test_status_gemini.py -q`
Expected：FAIL。

- [ ] **Step 5: 修改程式**

- [ ] **Step 6: 確認全部通過**

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest tests/test_stats.py tests/test_status_gemini.py -q`
Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint`
Expected：沒有錯誤。

- [ ] **Step 7: Commit**

```bash
git add backend/app backend/tests web/src/components/dashboard/kpi-cards.tsx
git commit -m "feat: check Gemini in the system status and use the recorded costs in the dashboard" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14：Docker、設定檔、錄製腳本與 `pytest -m live`

**Files:**
- Create: `backend/scripts/record_gemini.py`、`backend/tests/test_gemini_live.py`
- Modify: `docker-compose.yml`、`docker-compose.e2e.yml`、`.env.example`、`backend/pyproject.toml`（`live` 標記、`addopts`）、`web/composer/dockerfile.test.ts` 或新增的 compose 測試（若現有測試檢查 compose 內容）

**Interfaces:**
- Produces：
  - `docker-compose.yml`：`x-backend` 的 `environment` 加上 `AGENT_MODE: ${AGENT_MODE:-gemini}`、`PRICING_FILE: /app/pricing.yaml`（其他 `GEMINI_*` 由 `.env` 傳入）；`x-backend` 與 worker 的 `volumes` 都加上 `./pricing.yaml:/app/pricing.yaml:ro`。
  - `docker-compose.e2e.yml`：`AGENT_MODE: sim`、`GEMINI_API_KEY: ""`；`volumes` 加上 `pricing.yaml`。
  - `.env.example`：規格 §6 的變數與中文說明（免費方案的資料使用說明見 README）。
  - `backend/pyproject.toml`：`markers` 加上 `live: 呼叫真的 Gemini API（需要 GEMINI_API_KEY，會產生費用），只以 pytest -m live 手動執行`；`addopts = "-m 'not live'"`。
  - `backend/scripts/record_gemini.py`：讀 `.env` 的 key，以 `GeminiAgent`／`GeminiReviewer` 對 SÉLUNE 的 IG 貼文各呼叫一次（需要 composer），以 httpx 的 event hook 存下回應；移除 key、`x-goog-*` 等與測試無關的標頭；寫入 `backend/tests/data/gemini/`。錯誤回應（429、401 等）維持手寫。
  - `backend/tests/test_gemini_live.py`：`pytestmark = pytest.mark.live`；只從環境變數或 `.env`（只讀 `GEMINI_API_KEY` 這一個值）取得 key，沒有時略過；需求拆解、Prompt 構建、VLM 審查（composer 繪製的海報）各一次，只檢查格式與護欄，不比對內容；用記憶體版的 `UsageRecorder` 印出費用。

- [ ] **Step 1: 寫測試（先寫測試）**

- 若 `web/composer/dockerfile.test.ts` 或其他測試讀取 compose 檔，新增：`docker-compose.yml` 的 api 與 worker 都掛載 `pricing.yaml`；`docker-compose.e2e.yml` 的 api 與 worker 都是 `AGENT_MODE: sim`、`GEMINI_API_KEY: ""`；
- `test_gemini_live.py`：沒有 key 時整個略過。

- [ ] **Step 2: 修改設定檔、建立腳本與 live 測試**

- [ ] **Step 3: 確認全部通過**

Run（在 repo 根目錄，有 Docker 時）：`docker compose config --quiet && docker compose -f docker-compose.yml -f docker-compose.e2e.yml config --quiet`（本機沒有 Docker，改以 YAML 解析確認）
Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q -m live`
Expected：沒有 key 時 live 測試全部略過；一般的 `uv run pytest` 不收集 live 測試。

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml docker-compose.e2e.yml .env.example backend/pyproject.toml backend/scripts/record_gemini.py backend/tests/test_gemini_live.py
git commit -m "feat: pass the Gemini settings and pricing to Compose, keep E2E simulated and add the live tests" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15：文件

**Files:**
- Modify: `README.md`、`backend/README.md`、`web/README.md`、`docs/superpowers/specs/2026-10-07-phase2-backend-design.md`（規格 §10 的修改）、`docs/superpowers/specs/2026-10-23-plan6b-gemini-vlm-design.md`（§12 未做實驗時註明延後）

說明以下幾點：
- `AGENT_MODE` 與 `REVIEW_MODE` 的組合；設定 key 的方式（`.env`，不進 git）；系統狀態的 Gemini 檢查；
- 費用：單價表、單一任務與每月上限、`job_usage`、儀表板的實際用量；
- 免費方案：Google 可能用輸入（包括商品照與海報）改善產品並可能由人工審閱，未發表的商品請用付費方案的 key；`job_usage` 仍依付費單價記錄；
- 測試：一般的 `pytest` 不呼叫真 API；`pytest -m live` 手動執行；`record_gemini.py` 與 `gemini_experiment.py` 的用法；
- 進度表：Plan 6B 完成（ComfyUI 仍為模擬）。

- [ ] **Step 1: 修改文件**

- [ ] **Step 2: 確認全部通過**

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint && npm run build && npm run e2e`
Expected：沒有錯誤（需要資料庫的後端測試、`npm run e2e:live` 在有 Docker 的環境執行）。

- [ ] **Step 3: Commit**

```bash
git add README.md backend/README.md web/README.md docs/superpowers/specs
git commit -m "docs: document AGENT_MODE, the Gemini key, costs and budgets" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 完成之後

- 推送分支，以 GitHub 的 compare 網址開 PR。
- 在有 Docker 的環境：
  - 後端全部測試（含資料庫）、`npm run e2e:live`；
  - 規格 §9 的驗收（`docker compose up -d --build`、三個品牌各一個任務、版面、缺字、取消、上限）。
- 有 key 之後：Task 1 的實驗（若尚未執行）、`pytest -m live`。
