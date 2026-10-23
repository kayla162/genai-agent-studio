# Plan 7：ComfyUI 生圖 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在筆電以 Windows 原生的 ComfyUI 生成背景（商品像素一律使用原始去背圖，由 composer 疊上），worker 以 HTTP 與 WebSocket 連線（上傳、送出、進度、下載、取消）；生圖與去背以 Redis 鎖互斥，16 GB 記憶體可以穩定執行；新增第 11 項檢查「背景色系」（`bg_palette`）。

**Architecture:**
- **切換**：`IMAGE_MODE=comfyui|sim`，與 `AGENT_MODE`、`REVIEW_MODE` 各自獨立；`comfyui` 需要 `REVIEW_MODE=composer`。模擬模式的生圖、事件與 golden timelines 不變（只多了第 11 項檢查）。
- **composer（TypeScript）**：`POST /plate`（商品底圖與遮罩，與 `paint` 的商品矩形一致）；`POST /render` 多回傳背景色系的量測；`/review` 產生 `bg_palette`。
- **worker（Python）**：`ComfyClient`（httpx＋`websockets`）、`ComfyImageEngine`（每個 variant 一個 prompt，依序送出）、`heavy-memory` 鎖。
- **ComfyUI**：`comfyui/` 放 workflow（API 格式）、參數對照表、模型與自訂節點清單（含授權與 SHA-256）、安裝腳本。

**Tech Stack:** ComfyUI portable（Windows，版本在 Task 1 固定）、SDXL、httpx、websockets（版本在 Task 7 以 `uv add` 固定）、respx 0.23.1、Pillow、redis-py（asyncio Lock）、Node 24、@napi-rs/canvas 1.0.13、Vitest。

**Spec:** `docs/superpowers/specs/2026-10-23-plan7-comfyui-design.md`；背景見 `docs/superpowers/specs/2026-10-07-phase2-backend-design.md` §5.5 與 `docs/superpowers/specs/2026-10-23-plan6b-gemini-vlm-design.md`。

## 開始前

**分支**
- 在 `main`（含 Plan 7 規格的 merge commit）之上的分支執行。每個 Task 一個 commit，完成後推送分支並開 PR。

**ComfyUI 與模型**
- ComfyUI 本身由使用者從官方 GitHub release 下載 portable 版並解壓縮（不放進 repo）；自訂節點與模型由 `comfyui/setup.ps1` 安裝（Task 1）。模型下載約 10–15 GB，執行前向使用者確認。
- 需要 ComfyUI 的只有 Task 1（實驗）、Task 11 的錄製腳本與 `pytest -m live`。其他 Task 一律使用假的 client、respx 重播與假的 WebSocket 伺服器。
- 模型授權：只用授權明確允許商用的模型（規格 §3）。Task 1 逐一讀授權原文，結論寫進 `comfyui/models.md`；非商用或不明確的不用，也不下載。

**Task 1 的時間點**
- 依規格，實驗是第一個 Task；但實驗腳本要用 Task 2–10 的程式（composer `/plate` 與背景量測、`ComfyClient`、`ComfyImageEngine`）。所以：
  - **Step 1–3（安裝、授權、在 ComfyUI 介面建立兩種 workflow）先做**：確認 SDXL 在 6 GB VRAM 跑得動，並匯出 API 格式的 workflow，Task 5 的參數對照表才有實際的節點編號；
  - **其餘步驟在 Task 10 之後執行**。標示「實驗決定」的常數先用規格的預設值。
- 實驗結果寫進規格 §12；常數若改變，在同一個 commit 修改程式與測試。

**這台開發機（Windows）的限制**
- Node 24 不在 PATH：每個指令前加 `export PATH="/c/Users/User/AppData/Local/Programs/node-v24.22.1-win-x64:$PATH"`（Git Bash）。
- 海報字型在主工作目錄的 `web/composer/fonts/`（不進 git）。在 worktree 執行需要字型的測試時設定 `POSTER_FONTS_DIR` 指向那個資料夾；後端的 composer fixture 也需要 Node 在 PATH 上。
- 沒有 Docker：需要 postgres、redis、chroma 的後端測試、`npm run e2e:live` 與 `docker compose` 驗收不能在這台執行，回報時列出。
- 使用者自己的 PostgreSQL 服務在 5432。後端測試的預設是 5433，不可以把 `DATABASE_URL` 指向 5432。
- 一律用 `127.0.0.1`，不要用 `localhost`。
- `npm run fixtures` 在 Windows 以 LF 寫出 fixture；只有換行不同的檔案用 `git checkout -- <檔案>` 還原。
- GPU：RTX 3060 Laptop（6 GB VRAM，驅動 616.92）；記憶體 16 GB。

## 本計畫的驗證方式

與 6B 相同：
- 每個 Task 列出檔案、介面、要先寫的測試案例與執行指令；程式碼以每個 Task 的 commit 為準。
- 每個 Task 都要確認：「先寫測試」的步驟確實失敗；結束時全部通過，ruff、`ruff format --check`、mypy（strict）、tsc 與 ESLint 都沒有錯誤。
- 不能在這台機器執行的測試（資料庫、Redis、Chroma）照樣撰寫，並在回報中列為「未在本機執行」。純邏輯盡量放在不需要資料庫與 Redis 的函式。
- Task 8 修改 `ImageEngine` 介面後，以暫存的腳本（不進 git）在記憶體中執行模擬模式的 `_pipeline`，確認事件與 golden timelines 相同（`bg_palette` 之外）。

執行時若結果與預期不同，先檢查是否漏了步驟，不要修改測試來配合。

## 實作時的調整

（實作時與本計畫原文不同的地方記錄在這裡，程式碼以 commit 為準。）

- **Task 2**：
  - `bgPaletteCheck` 的完整判定（通過、警告、不通過與說明文字）在 Task 2 就實作，Task 3 只加上量測；色塊用的 `measuredBackgroundOf` 也放在 `background.ts`，由 `rules.ts` 轉出。
  - `recheckCopy`（文字編輯器改文案後的重新審查）沿用生成時的 `bg_palette`：背景與文案無關，否則會變回「（模擬）」。
  - 畫面與註解的「規則 7 項」改為 8 項（節點圖、合規報告、結果牆、composer 與 Python 的 docstring）；README 留到 Task 12。
  - 多一項檢查使審查階段內 `review.check` 的時間間隔變短（總長不變），sample snapshot 的 `seq` 也隨之後移；以 JSON 比對確認除此之外 fixtures 沒有改變，並以暫存腳本在記憶體中執行模擬模式的 `_pipeline`，三條 timelines 的事件完全相同（`test_parity` 需要資料庫，未在本機執行）。
- **Task 3**：
  - Python 的 `BackgroundPalette` 放在 `app/pipeline/ports.py`（`ComposedPoster.background` 用到它，放在 `composer.py` 會循環匯入）；`RenderedPoster.background` 與 `ComposedPoster.background` 預設為 None（沒有標頭時背景色系為模擬）。
  - composer 的 `measureBackground(image, spec, brand)`：把背景以海報相同的拉伸方式縮小到長邊 256 再量，色票用品牌設定檔的（不是 spec 的，偏色的 spec 畫出的背景也要判定為色系外）；`measureBackgroundPalette` 的商品方框為 `BBox`，由呼叫端從 `boxMap` 的矩形轉換。
  - 程式產生的背景（3 個品牌 × 5 個模板 × 6 個 seed）色系外最多 0.7%（SÉLUNE），其他兩個品牌為 0%，與 15% 的門檻有很大的餘裕。
  - 審查清單在背景色系的說明旁畫出色系外的主要顏色（與主色色塊共用元件）。
- **Task 4**：
  - 生成尺寸用 SDXL 常用的尺寸，邊長都是 64 的倍數：4:3 為 1152 × 896、4:5 為 896 × 1152（規格原本寫 1152 × 864、896 × 1120，邊長不是 64 的倍數）；與模板比例相差都 < 5%，放大後只裁掉一點。規格 §4.3 一併修改。
  - `/plate` 的回應：`{ width, height, scale, crop: { x, y }, productRect, plate, mask, warning }`（`scale` 與 `crop` 給 worker 放大與裁切用）；Python 為 `PlateResult`（`crop_x`、`crop_y`、`product_rect: PlateRect | None`）。
  - 商品已刪除時沒有 `productRect`，遮罩全白（整張重繪）。
  - `renderPlate(input, grow)` 的 `grow` 參數讓測試比較有無擴張；遮罩擴張為正方形鄰域（`dilateMask`，先橫向再縱向）。
  - 上傳的商品還沒去背時，底圖照樣畫出原照片（給模型參考），遮罩保留整個照片矩形。
- **Task 5**：
  - Task 1 還沒做，先手寫 `comfyui/workflows/product_scene_v1.json`（方式 A：`InpaintModelConditioning` 讀底圖與遮罩），只用 ComfyUI 內建節點與 SDXL base 1.0（規格 §4.2 的授權為 CreativeML Open RAIL++-M）。Lightning LoRA 的授權還沒確認，依 Global Constraints 先不放進 workflow，步數暫為 20；Task 1 實測後換成匯出的 workflow。
  - 對照表沒有 `width`、`height`：重繪的尺寸由底圖決定（`/plate` 已經是生成尺寸）。多了 `scheduler`；`plate_image`、`mask_image` 的檔名含輪次（`{jobId}_r{round}_{templateId}_plate.png`），因為 Gemini 每輪可能調整版面。
  - 前端的表在 `web/src/lib/agent/comfy.ts`（`PRODUCT_SCENE`、`plateImageName`、`maskImageName`）；`npm run fixtures` 匯出成 `contracts/fixtures/comfy.json`，pytest 確認與 `comfyui/workflows/product_scene_v1.params.json` 相同。`buildInjection` 的輸入改為 `jobId`、`round`、`templateId`、提示詞與畫布（不再需要 `layout`）；mock 的 `logoCrowding` 失誤不再改 `layout_boxes`。
  - 模擬模式的 timelines 只有 `injection` 改變（以 JSON 比對確認）；記憶體中執行模擬模式的 `_pipeline`，三條 timelines 的事件仍完全相同。
- **Task 6**：測試與腳本建立 `Settings` 時一律加上 `image_mode='sim'`（conftest 的 `BASE_SETTINGS` 與 api 測試的設定、`test_review`、`test_worker`、`test_api_catalog`、Gemini 相關測試、`gemini_experiment.py`），之後 Task 10 依 `IMAGE_MODE` 選生圖引擎時，測試不會改連 ComfyUI。
- **Task 7**：
  - `uv add websockets`：`websockets>=17.2`（`uv.lock` 固定為 17.2）。
  - 錯誤分兩種：`ComfyError`（連不上、拒絕 workflow、缺少節點或模型、逾時，重試也不會好）與它的子類別 `ComfyExecutionError`（`execution_error`、`execution_interrupted`，`out_of_memory` 標示 GPU 記憶體不足），Task 8 只重試後者。
  - `missing(workflow, ignore)` 不需要另外傳模型清單：依 `/object_info` 檢查每個節點類型都存在，以及選項型輸入（模型檔名、取樣器、排程器…）的值都在 ComfyUI 的清單裡；`ignore` 排除每個任務上傳的底圖與遮罩。
  - `POST /free` 的回應沒有內容，只檢查 HTTP 狀態；`/interrupt` 與 `/queue` 失敗時略過（ComfyUI 已經關閉）。HTTP 請求的逾時為 30 秒，等待 prompt 另以 `COMFYUI_TIMEOUT_SECONDS` 計算。
  - 假的 WebSocket 伺服器送完訊息後等用戶端關閉（`wait_closed`），伺服器才能正常結束；respx 以 `assert_all_called=False` 共用同一組路由。

## Global Constraints

- **指令位置**：前端在 `web/`，後端在 `backend/`，`docker compose` 在 repo 根目錄；ComfyUI 相關檔案在 `comfyui/`。
- **後端檢查**：Python 3.13、uv。`uv run ruff check .`、`uv run ruff format --check .`（單引號、行寬 120）與 `uv run mypy`（strict）都必須通過。
- **前端檢查**：`npm run test`、`npm run typecheck`、`npm run lint` 都必須通過；不用 `eslint-disable` 繞過規則；不手動修改 `src/components/ui/*`。
- **前後端資料約定**：
  - `CheckId` 加上 `bg_palette` 是本計畫唯一的合約變更（`web/src/types/contract.ts`、`backend/app/contract.py`）；其他合約不變。
  - 新的資料格式（背景量測、底圖）在 TypeScript 與 Python 各定義一次，以 golden fixture 確認一致；JSON 一律 camelCase。
- **模擬模式不變**：`SimImageEngine` 與程序化背景不變；golden timelines 只因兩件事改變：`bg_palette`（模擬為通過，Task 2）與 `PromptSpec.injection.params` 換成實際的對照表（Task 5）。每次 `npm run fixtures` 後確認差異只有該 Task 的項目。`SimImageEngine`、`SimPosters` 接受新參數但不使用。
- **測試不連 ComfyUI**：一般的 `pytest` 不執行 `live` 標記的測試；測試的 `Settings` 一律以 `_env_file=None` 建立並明確設定 `image_mode`。
- **授權**：`comfyui/models.md` 沒有記錄商用許可的模型不得出現在 workflow、對照表或 `setup.ps1`。
- **文字與錯誤**：UI 文字、錯誤訊息、註解都用繁體中文；API 錯誤一律回傳 `{ error: { code, message } }`。
- **Commit**：每個 Task 結束都要 commit，訊息為英文，最後一行加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。

## File Structure

| 檔案 | 責任 |
|---|---|
| `comfyui/README.md` | ComfyUI 版本、安裝步驟、啟動參數、`host.docker.internal` 的設定、記憶體建議 |
| `comfyui/models.md`、`comfyui/custom_nodes.md` | 模型與自訂節點：來源網址、版本或 commit、SHA-256、授權與商用結論 |
| `comfyui/setup.ps1` | 安裝自訂節點、下載模型並核對 SHA-256 |
| `comfyui/workflows/product_scene_v1.json` | API 格式的 workflow（Task 1 選定的生成方式） |
| `comfyui/workflows/product_scene_v1.params.json` | 參數對照表：`label` → `nodeId`、`input`、型別、預設值 |
| `web/src/lib/compose/paint.ts` | 匯出 `containBottom`（商品矩形，底圖共用） |
| `web/src/lib/compose/plate.ts` | `generationSize(ratio)`、`productPlate`（底圖與遮罩的幾何） |
| `web/src/lib/review/background.ts` | `measureBackgroundPalette`、`bgPaletteCheck`、門檻常數 |
| `web/src/lib/review/rules.ts` | `RuleContext.background?`；第 8 項規則 `bg_palette` |
| `web/src/lib/agent/fixes.ts`、`prompt.ts` | `bg_palette` 的修正；`NEGATIVE_BY_FIX.bg_palette`；`buildInjection` 依對照表 |
| `web/composer/handlers.ts`、`poster.ts`、`plate.ts` | `/plate`；`/render` 的背景量測標頭；`/review` 的 `background` |
| `web/src/types/contract.ts`、`backend/app/contract.py` | `CheckId` 加上 `bg_palette` |
| `web/src/test/golden.ts`、`contracts/fixtures/*` | 背景量測、對照表的範例；timelines 更新 |
| `backend/app/settings.py` | `IMAGE_MODE`、`COMFYUI_*`、`MEMORY_LOCK`；`comfyui` 加 `REVIEW_MODE=sim` 為設定錯誤 |
| `backend/app/adapters/comfyui.py` | `ComfyClient`：HTTP、WebSocket、上傳、送出、進度、下載、取消、`/free`、`/object_info` |
| `backend/app/adapters/composer.py` | `plate()`；`RenderedPoster.background`；`review(background=…)` |
| `backend/app/pipeline/ports.py` | `ImageEngine.render_round(…, product)`；`ComposedPoster.background` |
| `backend/app/pipeline/comfy.py` | `ComfyImageEngine`：底圖、送出、進度事件、放大與裁切、存檔 |
| `backend/app/pipeline/memory.py` | `HeavyMemoryLock`（Redis 鎖，自動延長，可取消的等待） |
| `backend/app/pipeline/runner.py` | 傳 `product` 給 `render_round`；「審查 N 張 × 11 項」 |
| `backend/app/worker.py`、`backend/app/api/services.py` | 依 `IMAGE_MODE` 選擇生圖引擎；去背取得 `heavy-memory` 鎖 |
| `backend/app/api/catalog.py` | 系統狀態的 ComfyUI 檢查 |
| `backend/app/stats.py`、`web/src/lib/stats/dashboard.ts` | `url` 背景的生圖成本為 0 |
| `web/src/components/agent/flow-graph.tsx`、`studio/result-wall.tsx`、`agent/review-panel.tsx`、`dashboard/kpi-cards.tsx` | 只顯示用到的節點群組、`url` 背景的 seed、`bg_palette` 的色塊、「本機 GPU」 |
| `backend/scripts/comfy_experiment.py`、`backend/scripts/record_comfy.py` | 規格 §2 的實驗、錄製 HTTP 與 WebSocket |
| `backend/tests/fake_comfy.py`、`backend/tests/data/comfy/*` | 假的 ComfyUI（HTTP 以 respx、WebSocket 以本機伺服器）與錄製的回應 |
| `docker-compose.yml`、`docker-compose.e2e.yml`、`.env.example` | 新變數；E2E 固定 `IMAGE_MODE=sim` |

---

### Task 1：ComfyUI 安裝與實測（需要 ComfyUI）

**Files:**
- Create: `comfyui/README.md`、`comfyui/models.md`、`comfyui/custom_nodes.md`、`comfyui/setup.ps1`、`comfyui/workflows/product_scene_v1.json`、`backend/scripts/comfy_experiment.py`
- Modify: `docs/superpowers/specs/2026-10-23-plan7-comfyui-design.md`（§12）、實驗決定的常數所在檔案（`web/src/lib/compose/plate.ts` 的 `PLATE_MASK_GROW`、`web/src/lib/review/background.ts` 的門檻、`backend/app/settings.py` 的 `comfyui_free_after_job` 預設、`web/src/lib/compose/paint.ts` 的商品陰影）、`backend/tests/data/comfy/*`（以 Task 11 的錄製腳本重新錄製）

**Interfaces:**
- Consumes（Step 4 起）：Task 2–10 的全部程式；composer 以 `npm run composer` 在 3900 執行（需要字型）。
- Produces：`uv run python -m scripts.comfy_experiment <probe|method|time|memory|edge|palette|upscale|all> [--limit N] [--offline]`；報告 JSON 寫到 `data/experiments/plan7-<時間>.json`（`data/` 不進 git），並在終端機印出摘要表。`--offline` 以假的 ComfyUI（回傳純色圖）跑完整個流程，檢查腳本本身。

**實驗的品牌與商品**：SÉLUNE、misty-isle、Kayla 精緻少女（`brands/my-brand-01.yaml`）。商品用已去背的真實照片（使用者提供，或 `assets/products/` 的照片先執行去背）；Kayla 沒有示範商品時，以 `serum` 向量素材建立暫時的示範商品（不寫入資料庫）。

- [ ] **Step 1: 授權與清單**

逐一讀規格 §4.2 候選模型的授權原文（模型頁的 license 檔，而不是摘要），在 `comfyui/models.md` 記錄：檔名、來源網址、版本、SHA-256、大小、授權名稱、授權原文連結、商用結論（可以／不可以／不明確）。只有「可以」的模型進入 `setup.ps1`。自訂節點同樣記錄在 `custom_nodes.md`（固定 commit；只使用授權允許商用的節點，盡量只用 ComfyUI 內建節點）。

結論有任何不確定時停下來，回報使用者，不自行判斷。

- [ ] **Step 2: 安裝與連線確認**

使用者下載 ComfyUI portable 並解壓縮後，以 `comfyui/setup.ps1 -ComfyDir <資料夾>` 安裝自訂節點與模型（下載前向使用者確認總大小）。`comfy_experiment probe`：
- `GET /system_stats`：印出 ComfyUI 版本、GPU 名稱、VRAM；
- `GET /object_info`：確認 workflow 需要的節點類型都存在；
- 從 Docker 容器內（有 Docker 的環境；這台沒有時記錄為待驗）以 `http://host.docker.internal:8188` 連線，確認 `--listen` 的設定。

Expected：連線正常、節點齊全。任何一項不成立時停下來，回報使用者並修改規格。

- [ ] **Step 3: 建立兩種 workflow**

在 ComfyUI 介面以規格 §4.3 的 A（SDXL inpainting 讀底圖與遮罩）與 B（文生圖＋ControlNet 讀遮罩輪廓）各建立一個 workflow，以 Lightning LoRA 減少步數；以一張手動做的底圖確認可以出圖，記錄 VRAM 與秒數；以「Save (API Format)」匯出到 `comfyui/workflows/`（`product_scene_v1_a.json`、`product_scene_v1_b.json`，Step 6 後只保留一個並改名為 `product_scene_v1.json`）。

Task 5 依匯出的節點編號建立參數對照表。

- [ ] **Step 4–9（在 Task 10 之後執行）**

| Step | 子命令 | 方法與通過標準（規格 §2） |
|---|---|---|
| 4 | `method` | A、B 各跑 3 品牌 × 5 模板；人工評分（透視、光線、接觸面、文字區塊乾淨）加上 Gemini VLM 的 `vlm_quality`（有 key 時）；選定一種 |
| 5 | `time` | 每張候選從送出到下載完成的秒數（不含排隊；第一次載入另外記錄）；每張 ≤ 60 秒 |
| 6 | `memory` | Docker 全部服務＋ComfyUI＋瀏覽器：生圖時的系統記憶體尖峰與 VRAM；另外量生圖與去背同時執行（關閉 `MEMORY_LOCK`），決定互斥是否必要；量測 `/free` 的效果與重新載入的秒數，決定 `COMFYUI_FREE_AFTER_JOB` |
| 7 | `edge` | 疊上原始去背圖後檢查商品邊緣；調整 `PLATE_MASK_GROW`；決定 `url` 背景是否關閉程式陰影 |
| 8 | `palette` | 程序化背景（3 品牌 × 5 模板 × 4 個 seed）100% 通過；正確提示詞的生成背景 ≥ 90% 通過；正面提示詞指定 `neon green`、`fluorescent pink`、`deep blue` 等偏離色系的全部不通過；依結果決定 `NEUTRAL_C`、`HUE_TOL`、`CHROMA_MARGIN` 與判定門檻 |
| 9 | `upscale` | Lanczos 與 Real-ESRGAN（若通過授權）比較：VLM `vlm_quality` 與人工；選定放大方式 |

- [ ] **Step 10: 錄製回應**

以 Task 11 的 `scripts/record_comfy.py` 重新錄製 `backend/tests/data/comfy/`，取代手寫的版本；確認 `uv run pytest tests/test_comfy_client.py` 仍通過。

- [ ] **Step 11: 記錄結果並確認全部通過**

把每一項的方法、數字、決定與已知限制寫進規格 §12；`comfyui/README.md` 寫入 ComfyUI 版本、啟動參數與記憶體建議（含 `.wslconfig`）。常數改變時同步修改測試的預期值。

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint`
Expected：沒有錯誤（需要資料庫的後端測試在這台機器上會因為連不到 postgres 而失敗，只確認其他測試）。

- [ ] **Step 12: Commit**

Step 1–3 先以一個 commit 提交（`docs: list the commercially licensed ComfyUI models and add the setup script and workflows`）；Step 4–11 另一個：

```bash
git add comfyui backend/scripts/comfy_experiment.py backend/tests/data/comfy docs/superpowers/specs/2026-10-23-plan7-comfyui-design.md
# 加上實驗後修改的常數與測試
git commit -m "docs: record the Plan 7 ComfyUI experiment and tune the thresholds" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2：第 11 項檢查 `bg_palette`（合約）

**Files:**
- Create: `web/src/lib/review/background.ts`（本 Task 只放 `BackgroundPalette` 型別與 `bgPaletteCheck`；量測在 Task 3）
- Modify: `web/src/types/contract.ts`、`backend/app/contract.py`、`web/src/lib/review/rules.ts`、`web/src/lib/agent/fixes.ts`、`web/src/lib/agent/prompt.ts`（`NEGATIVE_BY_FIX`）、`web/src/components/agent/review-panel.tsx`（「11 項檢查」）、`web/src/lib/api/mock/scenario.ts`（log 文字）、`backend/app/pipeline/runner.py`（log 文字）、`backend/app/pipeline/gemini.py`（docstring）、`contracts/fixtures/*`（`npm run fixtures`）
- Test: `web/src/lib/review/rules.test.ts`、`web/src/lib/agent/fixes.test.ts`、`backend/tests/test_contract.py`

**Interfaces:**
- Produces：
  - `CHECK_IDS` 在 `color_delta` 之後插入 `bg_palette`（規則 8 項、VLM 3 項；前後端順序相同）。
  - `background.ts`：`interface BackgroundPalette { offShare: number; offHex: string | null; sampled: number }`；`bgPaletteCheck(result, brand)`（判定見 Task 3）。
  - `rules.ts`：`RuleContext.background?: BackgroundPalette | null`；沒有傳入時 `bg_palette` 為 `{ status: 'pass', value: '（模擬）', target: 'canvas', ragRef: ragRefFor(brand, 'color') }`，名稱「背景色系」、規則「品牌色系外 ≤ 15%」。
  - `fixes.ts`：`bg_palette` 不通過時加上「背景改用品牌色系」（說明含色票與偏離色）；`NEGATIVE_BY_FIX.bg_palette = 'neon colors, fluorescent colors, off-brand color cast'`。

- [ ] **Step 1: 寫測試（先寫測試）**

- `rules.test.ts`：`runRuleChecks` 回傳 8 項，第 3 項為 `bg_palette`，沒有 `background` 時為 pass、「（模擬）」；分數不變。
- `fixes.test.ts`：`bg_palette` 為 fail 時產生「背景改用品牌色系」；為 pass 時不產生。
- `test_contract.py`：`CHECK_IDS` 與 TypeScript 相同（既有的 golden 比對涵蓋）。

- [ ] **Step 2: 確認測試失敗**

Run（在 `web/`）：`npx vitest run src/lib/review/rules.test.ts src/lib/agent/fixes.test.ts`
Expected：FAIL，`bg_palette` 不存在。

- [ ] **Step 3: 修改合約、規則與修正；更新 log 與面板的「10 項」**

- [ ] **Step 4: 重新產生 fixtures，確認差異只有 `bg_palette`**

Run（在 `web/`）：`npm run fixtures && git diff --stat ../contracts/`
Expected：timelines 的每個 `review.check` 序列多一則 `bg_palette`（pass、「（模擬）」），`review.completed` 的 checks 多一項，分數不變；其他沒有改變（只有換行不同的檔案還原）。

- [ ] **Step 5: 確認全部通過**

Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint`
Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q tests/test_contract.py tests/test_parity.py tests/test_pipeline.py tests/test_stats.py`
Expected：沒有錯誤。

- [ ] **Step 6: Commit**

```bash
git add web/src backend/app contracts backend/tests
git commit -m "feat: add the background palette check as the eleventh review check" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3：背景色系的量測

**Files:**
- Modify: `web/src/lib/review/background.ts`、`web/src/lib/review/rules.ts`、`web/composer/poster.ts`、`web/composer/handlers.ts`、`web/src/components/agent/review-panel.tsx`（色塊）、`backend/app/adapters/composer.py`、`backend/app/pipeline/ports.py`（`ComposedPoster.background`）、`backend/app/pipeline/review.py`、`backend/app/pipeline/gemini.py`（`GeminiReviewer` 傳 `background`）、`web/src/test/golden.ts`
- Test: `web/src/lib/review/background.test.ts`、`web/composer/poster.test.ts`、`web/composer/handlers.test.ts`、`backend/tests/test_review.py`、`backend/tests/test_gemini_reviewer.py`

**Interfaces:**
- Produces：
  - `background.ts`：
    - 常數（實驗決定）：`NEUTRAL_C = 12`、`HUE_TOL = 30`、`CHROMA_MARGIN = 25`、`BG_PASS_MAX = 0.15`、`BG_WARN_MAX = 0.3`、`PRODUCT_MARGIN = 0.02`、`SAMPLE_SIDE = 256`；
    - `measureBackgroundPalette(pixels: { data: Uint8ClampedArray; width: number; height: number }, product: BBox, canvas: { width; height }, palette: Palette): BackgroundPalette`：縮小後的像素（呼叫端負責縮小）；商品方框向外擴張 `PRODUCT_MARGIN` × 短邊後排除；LCh 判定（規格 §4.8）；`offHex` 為色系外像素中最多的顏色（Lab 量化到 8 階後取眾數，回傳 `#RRGGBB`）；
    - `bgPaletteCheck(result: BackgroundPalette | null | undefined, brand): Pick<ReviewCheck, 'value' | 'status' | 'target'>`：沒有結果為模擬；`value`「色系外 8%」「色系外 42%（主要為 #3FD27A）」。
  - `rules.ts`：`bg_palette` 由 `bgPaletteCheck(background)` 產生。
  - `measuredBackgroundOf(check)`（與 `measuredPrimaryOf` 相同的方式）：審查面板依此畫色塊。
  - composer `poster.ts`：`renderPoster` 在繪製文字前，把背景縮小到 `SAMPLE_SIDE` 並量測，回傳 `measured.background`；`/render` 加上標頭 `X-Background-Palette`（JSON：`{"offShare":0.08,"offHex":null,"sampled":61234}`）。
  - composer `/review` 接受 `background`（缺少時為模擬）；格式錯誤時回 400。
  - Python：`RenderedPoster.background: BackgroundPalette | None`（Pydantic，camelCase）、`ComposedPoster.background`、`ComposerClient.review(…, background=…)`；`ComposerReviewer` 與 `GeminiReviewer` 都傳入。

- [ ] **Step 1: 建立 `background.test.ts`（先寫測試）**

測試案例：
- 純品牌主色的圖：色系外 0%、pass；
- 純中性灰、純白、純黑：0%；
- 品牌主色到 secondary 的漸層：0%；
- 一半螢光綠（`#39FF14`）：約 50%、fail、`offHex` 接近 `#39FF14`；
- 主色但彩度比品牌色高出 `CHROMA_MARGIN` 以上（例如把 SÉLUNE 主色飽和度拉滿）：色系外；
- 商品方框內全是螢光綠、方框外是品牌色：0%（排除生效）；
- 三個示範品牌的程序化背景（以 `backgroundSvg` 在 Node 以 @napi-rs/canvas 繪製，5 模板 × 2 seed）全部 pass（有字型時；測試放在 `web/composer/poster.test.ts`）。

- [ ] **Step 2: composer 與 Python 的測試（先寫測試）**

- `handlers.test.ts`：`/render` 回傳 `X-Background-Palette`，可以 JSON 解析；`/review` 帶 `background` 時 `bg_palette` 依量測判定；格式錯誤回 400。
- `test_review.py`：`ComposerPosters` 讀到標頭並放進 `ComposedPoster.background`；`ComposerReviewer` 把它送給 `/review`（respx 檢查 request body）。
- `test_gemini_reviewer.py`：同上。

- [ ] **Step 3: 確認測試失敗**

Run（在 `web/`）：`npx vitest run src/lib/review/background.test.ts composer`
Run（在 `backend/`）：`uv run pytest -q tests/test_review.py tests/test_gemini_reviewer.py`
Expected：FAIL。

- [ ] **Step 4: 實作；golden 加上 `BackgroundPalette` 的範例**

- [ ] **Step 5: 確認全部通過**

Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint && npm run fixtures`
Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected：沒有錯誤；模擬模式的 timelines 沒有改變。

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/review web/composer web/src/components/agent/review-panel.tsx web/src/test contracts backend/app backend/tests
git commit -m "feat: measure the background palette in the composer and review it as bg_palette" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4：商品底圖 `/plate`

**Files:**
- Create: `web/src/lib/compose/plate.ts`、`web/composer/plate.ts`
- Modify: `web/src/lib/compose/paint.ts`（匯出 `containBottom`）、`web/composer/handlers.ts`、`backend/app/adapters/composer.py`
- Test: `web/src/lib/compose/plate.test.ts`、`web/composer/handlers.test.ts`、`backend/tests/test_composer_client.py`（新增；或併入既有的 composer client 測試）

**Interfaces:**
- Produces：
  - `web/src/lib/compose/plate.ts`：
    - `GENERATION_SIZES: Record<ChannelTemplate['ratio'], { width: number; height: number }>`（規格 §4.3 的五種尺寸，邊長為 64 的倍數）；`generationSize(ratio)`；
    - `PLATE_MASK_GROW = 8`（實驗決定，生成解析度的像素）；
    - `plateGeometry(spec: Pick<PromptSpec, 'canvas' | 'layout'>, product: { width; height } | null)`：回傳生成解析度下的商品矩形（`containBottom` 依比例換算）與裁切資訊（`cover` 縮放：生成圖放大到模板尺寸後置中裁切的位移）；
    - 數學上保證：生成圖經 `cover` 放大與裁切後，商品矩形與 `paint` 在模板尺寸畫的商品矩形誤差 ≤ 1 像素。
  - composer `POST /plate`：輸入 `{ spec, product, brand, images: { product } }`（與 `/render` 相同的商品格式）；輸出 JSON `{ width, height, plate: base64 PNG, mask: base64 PNG, productRect, crop }`。
    - `plate`：中性灰（`#808080`）畫布，商品依 `plateGeometry` 繪製（去背圖 normal；原圖或還沒去背時畫矩形外框並回傳 `warning: '商品尚未去背，背景依外框生成'`）；
    - `mask`：白色為重繪區域；商品不透明像素（alpha ≥ 128）向外擴張 `PLATE_MASK_GROW` 為黑色；還沒去背時整個矩形為黑。
  - Python：`ComposerClient.plate(spec, product, brand, images) -> PlateResult`（`width`、`height`、`plate: bytes`、`mask: bytes`、`product_rect`、`crop`、`warning`）。

- [ ] **Step 1: 寫測試（先寫測試）**

- `plate.test.ts`：五種比例的生成尺寸為 64 的倍數、約 100 萬像素；`plateGeometry` 換算回模板尺寸後與 `containBottom(B.product, w, h)` 誤差 ≤ 1 像素（5 模板 × 3 種商品比例）。
- `handlers.test.ts`：`/plate` 的 `plate` 與 `mask` 尺寸正確；`mask` 在商品中心為黑、四角為白；擴張後的黑色區域比商品 alpha 大；沒有去背圖時回傳 `warning`。
- Python：`plate()` 解析回應（respx）。

- [ ] **Step 2: 確認測試失敗**

- [ ] **Step 3: 實作**

- [ ] **Step 4: 確認全部通過**（同 Task 3 的指令）

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add the composer /plate endpoint for the ComfyUI product plate and mask" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5：參數對照表與 `buildInjection`

**Files:**
- Create: `comfyui/workflows/product_scene_v1.params.json`
- Modify: `web/src/lib/agent/prompt.ts`（`buildInjection`、`seedOf`）、`web/src/test/golden.ts`（匯出對照表）、`web/src/lib/agent/inspect.ts`（若 Agent 透視依 label 顯示）、`contracts/fixtures/*`
- Test: `web/src/lib/agent/prompt.test.ts`、`backend/tests/test_comfy_params.py`

**Interfaces:**
- Produces：
  - `product_scene_v1.params.json`：`{ "workflow": "product_scene_v1.json", "params": [{ "label", "nodeId", "input", "type": "string"|"int"|"float"|"image", "default"? }] }`。必有的 label：`positive_prompt`、`negative_prompt`、`seed`、`steps`、`cfg`、`denoise`、`width`、`height`、`plate_image`、`mask_image`；B 方式另有 `controlnet_strength`。節點編號取自 Task 1 Step 3 匯出的 workflow（Task 1 還沒做時，先以手寫的最小 workflow 與對照表，Task 1 後更新）。
  - `buildInjection`：依對照表產生 `ComfyInjection.params`（`workflowFile: 'workflows/product_scene_v1.json'`）；`plate_image`、`mask_image` 的值為上傳後的檔名格式（`{jobId}_{templateId}_plate.png`），由 worker 在送出前確認；移除 `checkpoint`、`cutout_model`、`ip_adapter_style`、`ic_light`、`layout_boxes`。`ideogram` 分支不變。
  - pytest：讀對照表與 workflow JSON，每個 `nodeId` 存在、`input` 是該節點的輸入；`npm run fixtures` 匯出的對照表與 repo 的檔案相同。

- [ ] **Step 1: 寫測試（先寫測試）**

- `prompt.test.ts`：`buildInjection` 的 label 集合等於對照表；seed、寬高、提示詞的值正確；`seedOf` 不變。
- `test_comfy_params.py`：上述一致性。

- [ ] **Step 2: 確認測試失敗**

- [ ] **Step 3: 實作；`npm run fixtures`**

模擬模式的 `PromptSpec.injection` 會改變（Agent 透視顯示的參數），timelines 隨之更新；確認差異只有 `injection.params`。

- [ ] **Step 4: 確認全部通過**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: build the ComfyUI injection from the product_scene_v1 parameter table" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6：設定

**Files:**
- Modify: `backend/app/settings.py`
- Test: `backend/tests/test_settings.py`

**Interfaces:**
- Produces：
  - `ImageMode = Literal['comfyui', 'sim']`；`image_mode: ImageMode = 'comfyui'`；
  - `comfyui_url: str = 'http://127.0.0.1:8188'`（docker compose 設為 `http://host.docker.internal:8188`）；
  - `comfyui_timeout_seconds: float = Field(default=600, gt=0)`；
  - `comfyui_free_after_job: bool = False`（實驗決定）；
  - `memory_lock: bool = True`；
  - validator：`image_mode == 'comfyui'` 且 `review_mode == 'sim'` 時錯誤「IMAGE_MODE=comfyui 需要 REVIEW_MODE=composer（目前為 sim）：請改為 REVIEW_MODE=composer，或設定 IMAGE_MODE=sim」。

- [ ] **Step 1: 寫測試（先寫測試）**：預設值；validator；`comfyui_timeout_seconds=0` 不合法。
- [ ] **Step 2: 確認測試失敗**
- [ ] **Step 3: 實作**；既有測試裡以 `review_mode='sim'` 建立 `Settings` 的地方一併設定 `image_mode='sim'`。
- [ ] **Step 4: 確認全部通過**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add IMAGE_MODE and the ComfyUI settings" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7：`ComfyClient`

**Files:**
- Create: `backend/app/adapters/comfyui.py`、`backend/tests/fake_comfy.py`、`backend/tests/data/comfy/*.json`（手寫，Task 1 Step 10 換成錄製的）
- Modify: `backend/pyproject.toml`、`backend/uv.lock`（`uv add websockets`）
- Test: `backend/tests/test_comfy_client.py`

**Interfaces:**
- Produces：
  - `class ComfyError(AppError)`：訊息為中文。
  - `ComfyClient(settings, http: httpx.AsyncClient | None = None, connect_ws: Callable[..., AsyncContextManager[WebSocket]] | None = None)`（測試注入）：
    - `system_stats() -> ComfyStats`（`version`、`gpu`、`vram_total`）；連不上時 `ComfyError('ComfyUI 沒有回應（{url}），請先啟動 ComfyUI')`；
    - `missing(workflow: dict, models: dict[str, list[str]]) -> list[str]`：以 `/object_info` 檢查節點類型與模型檔名，回傳缺少的項目（結果快取 60 秒）；
    - `upload(name: str, png: bytes) -> str`（`POST /upload/image`，`overwrite=true`，回傳 ComfyUI 的檔名）；
    - `run(workflow: dict, run: RunContext, on_progress: Callable[[str, int, int], Awaitable[None]]) -> ComfyOutput`：
      1. 連上 WebSocket（`/ws?clientId=…`），再 `POST /prompt`（帶 `client_id`）；
      2. `executing` 與 `progress` 轉成 `on_progress(node_id, step, max_step)`；
      3. `execution_success` 後 `GET /history/{id}` 取得輸出檔名，`GET /view` 下載，回傳 `ComfyOutput(png, seconds)`；
      4. `execution_error`：`ComfyError`，訊息含節點類型與 ComfyUI 的 `exception_message`；OOM（訊息含 `CUDA out of memory` 或 `OutOfMemoryError`）時附上「請關閉其他使用 GPU 的程式，或以 --lowvram 啟動 ComfyUI」；
      5. WebSocket 斷線：每 2 秒以 `GET /history/{id}` 輪詢直到完成；
      6. 等待全部經過 `run.wait`（取消時先 `POST /interrupt`（帶 `prompt_id`，舊版不支援時不帶），再 `POST /queue` 刪除這個 prompt，然後丟出 `JobCancelled`）；
      7. 整體逾時 `comfyui_timeout_seconds`：中斷並丟出 `ComfyError('ComfyUI 沒有在 600 秒內完成…')`。
    - `free()`：`POST /free`（`unload_models`、`free_memory`）。
  - `fake_comfy.py`：respx 的路由（`/system_stats`、`/object_info`、`/upload/image`、`/prompt`、`/history/{id}`、`/view`、`/interrupt`、`/queue`、`/free`）與以 `websockets.serve` 在 127.0.0.1 隨機埠播放錄製訊息的假 WebSocket 伺服器（可以設定中途斷線）。

**重試**：`run` 本身不重試；variant 的重試（執行錯誤 1 次）在 `ComfyImageEngine`。

- [ ] **Step 1: 建立 `test_comfy_client.py`（先寫測試）**

測試案例：
- 成功：進度依序回報、輸出的 bytes 與 `/view` 相同、`seconds` > 0；
- `system_stats` 連不上：中文訊息含網址；
- `missing`：缺少節點類型與模型檔名都列出；60 秒內只呼叫一次 `/object_info`；
- `execution_error`：訊息含節點類型；OOM 加上建議；
- WebSocket 中途斷線：以 history 輪詢取得結果；
- 取消：呼叫 `/interrupt` 與 `/queue` 的 delete，丟出 `JobCancelled`；
- 逾時（`comfyui_timeout_seconds=0.2`）：中斷並丟出中文錯誤；
- `upload` 的 multipart 欄位與 `overwrite`。

- [ ] **Step 2: 確認測試失敗**

Run（在 `backend/`）：`uv run pytest -q tests/test_comfy_client.py`
Expected：FAIL，找不到 `app.adapters.comfyui`。

- [ ] **Step 3: `uv add websockets`，實作**

- [ ] **Step 4: 確認全部通過**

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q tests/test_comfy_client.py`

- [ ] **Step 5: Commit**

```bash
git add backend/app/adapters/comfyui.py backend/tests/fake_comfy.py backend/tests/data/comfy backend/tests/test_comfy_client.py backend/pyproject.toml backend/uv.lock
git commit -m "feat: add the ComfyUI client with progress, history fallback, cancellation and timeouts" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8：`ComfyImageEngine`

**Files:**
- Create: `backend/app/pipeline/comfy.py`
- Modify: `backend/app/pipeline/ports.py`（`render_round` 加上 `product: Product`）、`backend/app/pipeline/sim.py`（接受但不使用）、`backend/app/pipeline/runner.py`（傳入 `product`）
- Test: `backend/tests/test_comfy_engine.py`

**Interfaces:**
- Produces：
  - `ComfyImageEngine(comfy: ComfyClient, composer: ComposerClient, settings, posters_images: Callable[[Product, Brand], PosterImages])`（沿用 `ComposerPosters` 讀商品圖的函式，抽成共用）：
    1. 每輪一次 `system_stats()`；
    2. 讀 workflow 與對照表（啟動時載入一次）；`missing()` 有缺少時 `ComfyError`，訊息列出缺少項目並指向 `comfyui/README.md`；
    3. 每個模板：`composer.plate(...)`；有 `warning` 時 `run.log('comfy', warning, 'warn')`；上傳底圖與遮罩；
    4. 每個 variant：依 `spec.injection.params` 填入 workflow（`seed` 加上 variant；底圖與遮罩換成上傳後的檔名）；送出 `ComfyQueuedEvent`；`run()`；執行錯誤時重試 1 次（`run.log` 說明），仍失敗則丟出；
    5. 進度：對照表的節點分組（`generate`、`upscale`）換成 `RenderProgressEvent`；同一組的步數依實際 `max_step`；
    6. 輸出：在執行緒中以 Pillow 依 `crop` 放大（Lanczos，或 Task 1 選定的方式）並裁切到模板尺寸，存成 `data/jobs/{jobId}/bg-{templateId}-r{round}-v{variant}.png`；
    7. `run.log('comfy', f'✓ {templateId} v{variant} 生成完成（{seconds:.1f} 秒）', 'ok')`；
    8. 回傳 `UrlBackground(kind='url', url='/files/jobs/…', includes_product=False)`。
  - `RENDER_GROUPS`：`generate` 與 `upscale` 的節點類型（依 workflow）。

- [ ] **Step 1: 建立 `test_comfy_engine.py`（先寫測試）**

以假的 `ComfyClient`（記錄送出的 workflow，回傳指定大小的純色 PNG）與假的 composer：
- 每個 variant 一則 `comfy.queued`，順序為模板 × variant；
- 送出的 workflow：提示詞、seed（基準加 variant）、底圖與遮罩檔名正確；
- 輸出存檔的尺寸等於模板尺寸，路徑與 `UrlBackground.url` 一致，`includes_product` 為 False；
- 執行錯誤一次後重試成功；兩次都失敗時丟出，訊息含節點錯誤；
- 缺少節點時的訊息；
- 底圖有 `warning` 時送出 warn 的 log；
- 進度事件的 node 只有 `generate`、`upscale`。

- [ ] **Step 2: 確認測試失敗**

- [ ] **Step 3: 實作；修改 `ImageEngine` 介面與 runner**

- [ ] **Step 4: 確認模擬模式不變**

以暫存的腳本（不進 git）在記憶體中執行模擬模式的 `_pipeline`，確認事件與 golden timelines 相同。

- [ ] **Step 5: 確認全部通過**

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`

- [ ] **Step 6: Commit**

```bash
git commit -m "feat: generate backgrounds with ComfyUI from the composer product plate" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9：生圖與去背互斥

**Files:**
- Create: `backend/app/pipeline/memory.py`
- Modify: `backend/app/pipeline/comfy.py`（`render_round` 取得鎖；結束後依設定 `free()`）、`backend/app/pipeline/ports.py`（`ImageEngine.finish(job_id)`）、`backend/app/pipeline/sim.py`（`SimImageEngine.finish` 不做事）、`backend/app/pipeline/runner.py`（任務結束時呼叫，含失敗與取消）、`backend/app/worker.py`（`cutout` 取得鎖）
- Test: `backend/tests/test_memory_lock.py`（不需要 Redis 的部分用假的鎖）、`backend/tests/test_worker.py`（需要 Redis，未在本機執行）

**Interfaces:**
- Produces：
  - `HeavyMemoryLock(redis, name='heavy-memory', ttl=60)`：`async with lock.hold(waiting: Callable[[], Awaitable[None]] | None = None, run: RunContext | None = None)`：
    - 以 redis-py 的 asyncio `Lock`（`timeout=ttl`、`blocking=True`），持有期間每 `ttl / 3` 秒延長；worker 異常結束時 ttl 到期自動釋放；
    - 第一次等不到時呼叫 `waiting()`（任務送出 log「等待商品去背完成」；去背只寫 logger）；
    - 傳入 `run` 時以 `run.wait` 等待，取消會中止等待；
    - `memory_lock=False` 時不取得鎖（直接進入）。
  - `ComfyImageEngine`：整個 `render_round` 持有鎖；`comfyui_free_after_job` 為 True 時在任務的最後一輪結束後呼叫 `free()`（runner 在任務結束時呼叫 `ports.image.finish(job_id)`；`SimImageEngine.finish` 不做事）。
  - `cutout`：讀照片之後、載入模型之前取得鎖。

- [ ] **Step 1: 寫測試（先寫測試）**

- 假的鎖：持有中時第二個 `hold` 等待並呼叫一次 `waiting()`；第一個釋放後進入；
- 延長：持有時間超過 ttl 仍不會被別人取得（以 fakeredis 或可控制時間的假鎖）；
- 取消：等待中取消丟出 `JobCancelled`，不取得鎖；
- `memory_lock=False` 時不呼叫 Redis；
- `test_worker.py`（需要 Redis）：生圖持有鎖時，去背在鎖釋放後才開始。

- [ ] **Step 2: 確認測試失敗**
- [ ] **Step 3: 實作**
- [ ] **Step 4: 確認全部通過**（需要 Redis 的列為「未在本機執行」）
- [ ] **Step 5: Commit**

```bash
git commit -m "feat: keep image generation and product cutouts from running at the same time" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10：選用、系統狀態、成本與前端

**Files:**
- Modify: `backend/app/worker.py`（`build_services` 依 `image_mode`）、`backend/app/api/services.py`（若 api 需要 `ComfyClient` 做狀態檢查）、`backend/app/api/catalog.py`（移除 `SIMULATED` 的 ComfyUI，改為 `_comfyui` 檢查）、`backend/app/stats.py`、`web/src/lib/stats/dashboard.ts`、`web/src/components/agent/flow-graph.tsx`、`web/src/components/studio/result-wall.tsx`、`web/src/components/dashboard/kpi-cards.tsx`
- Test: `backend/tests/test_services.py`、`backend/tests/test_status_comfy.py`（新增，不需要資料庫）、`backend/tests/test_stats.py`、`web/src/lib/stats/dashboard.test.ts`、`web/src/lib/agent/flow.test.ts`（或 flow-graph 的測試）、`web/src/lib/jobs/view.test.ts`

**Interfaces:**
- Produces：
  - `build_services`：`image_mode == 'comfyui'` 時 `ports.image = ComfyImageEngine(...)`；docstring 更新。
  - `_comfyui(services)`：`sim` →（'sim', '模擬生圖：程序化背景'）；連不上 → error「連不上 ComfyUI（{url}），請先啟動 ComfyUI」；缺少節點或模型 → error 並列出；正常 →「{GPU}・VRAM {n} GB・ComfyUI {version}」；結果快取 60 秒；每項仍受 `STATUS_TIMEOUT` 限制（`/object_info` 的快取在背景更新，第一次逾時時顯示「檢查中」）。
  - `stats.job_cost`：`render.completed` 的每張 `background.kind == 'url'` 時生圖成本為 0（前端 `dashboard.ts` 相同）；`kpi-cards` 在全部任務都是 `url` 背景時標示「生圖：本機 GPU（US$0）」。
  - 前端：節點圖只顯示事件中出現過的節點群組（模擬模式四組都出現，畫面不變）；結果牆的 seed：`url` 背景時讀 `seedOf(render.spec) + render.variant`。

- [ ] **Step 1: 寫測試（先寫測試）**：上述每一項。
- [ ] **Step 2: 確認測試失敗**
- [ ] **Step 3: 實作**
- [ ] **Step 4: 確認全部通過**；golden 的儀表板統計不變（模擬模式都是程序化背景）。
- [ ] **Step 5: Commit**

```bash
git commit -m "feat: select ComfyUI by IMAGE_MODE, check it in the system status and count local renders as free" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11：Docker、設定檔、錄製腳本與 `pytest -m live`

**Files:**
- Create: `backend/scripts/record_comfy.py`、`backend/tests/test_comfy_live.py`
- Modify: `docker-compose.yml`、`docker-compose.e2e.yml`、`.env.example`、`backend/tests/test_compose.py`

**Interfaces:**
- Produces：
  - `docker-compose.yml`：`x-backend` 的 `environment` 加上 `IMAGE_MODE: ${IMAGE_MODE:-comfyui}`、`COMFYUI_URL: ${COMFYUI_URL:-http://host.docker.internal:8188}`；worker 加上 `extra_hosts: ['host.docker.internal:host-gateway']`（Docker Desktop 已內建，Linux 需要）。
  - `docker-compose.e2e.yml`：api 與 worker 都是 `IMAGE_MODE: sim`。
  - `.env.example`：規格 §6 的變數與中文說明，取代原本的「`# COMFYUI_URL=… Plan 7：ComfyUI 生圖`」。
  - `record_comfy.py`：以真的 ComfyUI 跑一次 SÉLUNE 的 IG 貼文（需要 composer），存下 HTTP 回應與 WebSocket 訊息到 `backend/tests/data/comfy/`（圖片縮小成 64 × 64，避免 repo 變大）；錯誤回應（`execution_error`、OOM）維持手寫。
  - `test_comfy_live.py`：`pytestmark = pytest.mark.live`；`/system_stats` 連不上時略過；5 個模板各生成一張，檢查尺寸、檔案與秒數並印出。

- [ ] **Step 1: 寫測試（先寫測試）**：`test_compose.py` 加上 E2E 為 `IMAGE_MODE: sim`、正式環境有 `COMFYUI_URL`；`test_comfy_live.py` 沒有 ComfyUI 時整個略過。
- [ ] **Step 2: 修改設定檔、建立腳本與 live 測試**
- [ ] **Step 3: 確認全部通過**

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q -m live`
Expected：沒有 ComfyUI 時 live 測試全部略過；一般的 `uv run pytest` 不收集 live 測試。

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: pass IMAGE_MODE and COMFYUI_URL to Compose, keep E2E simulated and add the ComfyUI live tests" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12：文件

**Files:**
- Modify: `README.md`、`backend/README.md`、`web/README.md`、`comfyui/README.md`、`docs/superpowers/specs/2026-10-07-phase2-backend-design.md`（規格 §10 的修改）、`docs/superpowers/specs/2026-10-23-plan7-comfyui-design.md`（§12 未做實驗時註明延後）

說明以下幾點：
- `IMAGE_MODE` 與 `AGENT_MODE`、`REVIEW_MODE` 的組合；ComfyUI 的安裝、啟動與系統狀態；
- 商品像素一律來自原始去背圖；還沒去背的商品依外框生成；
- 記憶體：16 GB 的建議（`.wslconfig`、互斥、`COMFYUI_FREE_AFTER_JOB`）；
- 模型授權：`comfyui/models.md`，只用允許商用的模型；
- 第 11 項檢查「背景色系」的判定方式；
- 測試：一般的 `pytest` 不連 ComfyUI；`pytest -m live`、`record_comfy.py`、`comfy_experiment.py` 的用法；
- 進度表：Plan 6B 一列改為「完成（生圖仍為模擬版）」（規格 §8）；Plan 7 完成。

- [ ] **Step 1: 修改文件**
- [ ] **Step 2: 確認全部通過**

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Run（在 `web/`）：`npm run test && npm run typecheck && npm run lint && npm run build && npm run e2e`
Expected：沒有錯誤（需要資料庫的後端測試、`npm run e2e:live` 在有 Docker 的環境執行）。

- [ ] **Step 3: Commit**

```bash
git add README.md backend/README.md web/README.md comfyui/README.md docs/superpowers/specs
git commit -m "docs: document IMAGE_MODE, the ComfyUI setup, memory and model licenses" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 完成之後

- 推送分支，以 `gh pr create` 開 PR。
- 在有 Docker 的環境：後端全部測試（含資料庫與 Redis）、`npm run e2e:live`；規格 §9 的驗收（`docker compose up -d --build`、啟動 ComfyUI、三個品牌各一個任務、商品逐像素比對、螢光色需求、ComfyUI 未開啟、取消）。
- Task 1 的 Step 4–11（若尚未執行）、`pytest -m live`。
