# 虛實整合 GenAI Agent

一句話需求 → Agent 拆解 → RAG 檢索品牌規範 → 多通路生圖 → 合規審查與自動重試 → 挑圖改字 → 匯出。
既是每天做商品圖的工具，也是全端技術的作品集。

- **前端**：Next.js 16（靜態輸出）、TypeScript、Tailwind CSS v4、shadcn/ui、Zustand：[web/README.md](web/README.md)
- **後端**：FastAPI、SAQ worker、PostgreSQL（SQLAlchemy、Alembic）、Redis：[backend/README.md](backend/README.md)
- **RAG**：Chroma 向量庫、BGE-M3 向量化與 bge-reranker-v2-m3 Rerank（ONNX Runtime，CPU）：[RAG 設計規格](docs/superpowers/specs/2026-10-21-plan5-rag-design.md)
- **composer**：Node 服務，直接執行前端的 TypeScript（版型、審查用海報的繪製、規則審查、Gemini 結果的護欄與模擬邏輯），讓前後端只有一份實作；以 `@napi-rs/canvas` 在伺服器端畫出與瀏覽器相同的海報：[伺服器端排版設計規格](docs/superpowers/specs/2026-10-22-plan6a-server-compose-design.md)
- **Gemini**：官方 `google-genai` SDK（`gemini-3.8-flash`）負責需求拆解、Prompt 構建、Query Rewriting 與 VLM 審查，每次呼叫記錄用量與費用：[Gemini Agent 與 VLM 審查設計規格](docs/superpowers/specs/2026-10-23-plan6b-gemini-vlm-design.md)
- **規格**：[第二階段設計規格](docs/superpowers/specs/2026-10-07-phase2-backend-design.md)；各計畫在 [docs/superpowers/plans/](docs/superpowers/plans/)

## 進度

| 計畫 | 內容 | 狀態 |
|---|---|---|
| Plan 1–3 | 前端與瀏覽器內模擬（mock 模式）、Agent 透視、成效儀表板 | 完成 |
| Plan 4 | 後端骨架與即時串流：全部 API、WebSocket、worker、Docker | 完成（外部服務為模擬版） |
| Plan 5 | RAG：Chroma、BGE-M3 與 Reranker、PDF 手冊上傳、歷史回寫 | 完成（Agent、生圖與審查仍為模擬版） |
| Plan 6A | 伺服器端排版與規則審查：審查用海報、從像素量測品牌主色 | 完成（Agent、生圖與 VLM 審查仍為模擬版） |
| Plan 6B | Gemini Agent、VLM 審查、用量與成本 | 完成（生圖仍為模擬版；規格 §2 的實驗與 `pytest -m live` 待設定 API key 後執行） |
| Plan 7 | ComfyUI 生圖 | |
| Plan 8 | 作品集 Demo（Cloudflare Pages＋Access） | |

## 架構

```
瀏覽器 ── 127.0.0.1:3000 ── web（nginx：前端靜態檔；/api、/ws、/files、/docs 轉給 api）
                              │
                            api（FastAPI）── postgres
                              │            └ data/（上傳的商品照、去背圖、審查用海報；之後的生成圖）
                              │ SAQ 佇列＋事件推送
                            redis
                              │
                            worker（SAQ）── composer（Node：版型、繪製審查用海報、規則審查、Gemini 的護欄、模擬邏輯）
                              │          ├ Gemini API（AGENT_MODE=gemini：Agent 與 VLM 審查；api 也用它拆解需求）
                              │          └ models/（去背與 RAG 的 ONNX 模型）
                            chroma（向量庫，127.0.0.1:8001）
```

- 每則任務事件都在同一個交易中取得序號（`seq`）並寫入資料庫，再經 Redis 推送到 WebSocket；斷線或重新整理後，前端以最後收到的 `seq` 接續。Redis 停止時，WebSocket 改為每秒從資料庫讀取新事件，連線不中斷。
- **RAG**：品牌設定檔、上傳的手冊與選定的海報都切成切塊，存在 PostgreSQL；worker 以 BGE-M3 向量化後寫入 Chroma（每個品牌一個 collection）。任務先向量召回 8 筆、再以 Reranker 重新排序，前 5 筆放進 Prompt。PostgreSQL 為準，Chroma 只是索引：worker 啟動時與每次檢索前都會比對並補齊，Chroma 的資料遺失時會自動重建。
- **合規審查**（`REVIEW_MODE=composer`，預設）：排版階段由 composer 在伺服器端畫出每張候選的審查用海報（與瀏覽器使用同一套 `scene.ts` 與 `paint.ts`），worker 存成 `data/jobs/{任務 id}/{候選 id}.png`（每張約 0.3–1 MB，不會自動清理）。審查依這張圖計算：7 項規則加 3 項 VLM，分數不加隨機抖動。`AGENT_MODE=gemini` 時 VLM 三項由 Gemini 讀這張圖判斷，並轉錄畫面上的文字比對錯字（見下方）；`AGENT_MODE=sim` 時依內容判斷（誇大用語看禁用詞、遮擋看 Logo 是否與標題重疊、品質一律通過），說明標示「模擬：AGENT_MODE=sim」。任務透視的「合規報告」可以切換「預覽／審查用海報」，兩者疊上相同的 BBox。
- **主色色差**：從審查用海報的像素量出品牌主色，計算與 CI 主色的 ΔE2000。量測範圍是標題、售價、徽章三個區塊（扣掉商品區塊），這些元素一定以主色繪製：取出佔比 2% 以上的色塊，以最接近主色的一個計算色差；超過門檻時，說明文字改為顯示實際用錯的顏色（例如 `#E0458A`），合規報告在旁邊畫出色塊；量不到時判定不通過（「未偵測到主色（主色區塊 < 2%）」）。限制：只檢查排版上的品牌色元素，不檢查背景。程式產生的背景依品牌色繪製，目前沒有問題；Plan 7 換成 AI 生成的照片背景時，再新增「背景色系」檢查（標準不能沿用 ΔE ≤ 5：正確的程式背景量起來也有 24–53）。
- **Gemini Agent**（`AGENT_MODE=gemini`，預設；需要 `REVIEW_MODE=composer`）：
  - 需求拆解、Prompt 構建（文案、8 個元素的版面方框、生圖場景）與 Query Rewriting 都由 Gemini 產生，提示詞在 `backend/app/pipeline/prompts/*.md`。
  - **護欄**：composer 的 `/spec` 檢查 Gemini 寫的文案與版面：替代用語、移除 emoji、字型沒有的字、禁用詞、長度、需求沒有的價格或優惠、版面是否合法、商品佔比、留白、Logo 淨空區與字級。有問題時帶著中文說明請 Gemini 修正一次，仍不合格就改用預設文案或版型，Agent 透視以警告顯示。
  - **VLM 審查**：Gemini 讀審查用海報，判斷誇大用語、遮擋與畫質，並轉錄畫面上的文字（不提供預期文案，避免照抄）；`ocrDiffs` 把轉錄與實際畫出的文字比對，0 處差異通過、1 處警告、2 處以上或畫面有方塊（字型沒有的字）不通過。
  - **用量與費用**：每次呼叫寫入 `job_usage`（tokens 含思考、依 `pricing.yaml` 的單價計算費用），Agent 透視顯示每次呼叫的用量與任務的合計，儀表板的每張成本改用實際費用。單一任務與每月（台北時間）各有費用上限（`GEMINI_JOB_BUDGET_USD`、`GEMINI_MONTHLY_BUDGET_USD`）。
  - `AGENT_MODE=sim`：Agent 與 VLM 都是模擬版，行為與 mock 模式的劇本相同（第一輪刻意失誤，Query Rewriting 後通過），不需要 key。
- ComfyUI 目前是模擬版（程序化背景，Plan 7 接上）。右上角的連線狀態可以展開各服務的狀態，模擬版會標示「模擬」；composer 一項顯示目前的 `REVIEW_MODE` 與載入的海報字型，Gemini 一項顯示模型、本月費用與上限、key 末 4 碼（`models.get` 檢查 key 與模型，不計費）。

## 用 Docker 執行（live 模式）

需要 Docker Desktop（映像檔取自 AWS 的官方映像鏡像，Chroma 取自 GitHub 的 `ghcr.io/chroma-core/chroma:1.5.9`，都不必登入）。

```bash
docker compose up -d --build
```

- 前端：http://127.0.0.1:3000
- API 文件：http://127.0.0.1:3000/docs
- 停止：`docker compose down`（資料保留在 volume；加上 `-v` 會清空資料庫與 `chroma` 向量庫，也會刪除 `models` volume，下次啟動要重新下載約 1 GB 的去背模型與約 1.2 GB 的 RAG 模型）
- 設定：複製 `.env.example` 成 `.env` 後修改（模擬速度、首輪是否刻意失誤、去背模型、RAG 模式、審查模式等），再 `docker compose up -d`
- 海報字型：建置 composer 時從 GitHub 的 `google/fonts`（固定 commit）下載 Noto Sans TC 與 Noto Serif TC 的可變字重 TTF（約 29 MB）和兩份 OFL 1.1 授權文字，核對 SHA-256 後放在映像檔的 `/usr/local/share/poster-fonts`（`POSTER_FONTS_DIR`）。網址與 SHA-256 和 `web/composer/fonts.lock.json` 相同，不需要掛載資料夾。建置時要能連到 raw.githubusercontent.com。
- 審查模式：`REVIEW_MODE=composer`（預設）繪製審查用海報並依它審查；`REVIEW_MODE=sim` 不畫圖，審查結果與 mock 模式相同。api 與 worker 讀同一個值（`docker-compose.yml` 預設 `composer`，`.env` 或環境變數可以覆寫）。
- Gemini：在 `.env` 加上 `GEMINI_API_KEY=…`（Google AI Studio 建立；`.env` 不會上傳 GitHub），再 `docker compose up -d`。沒有 key 時服務照常啟動，系統狀態顯示提示，需求拆解與新任務會被拒絕；不想使用 Gemini 時設 `AGENT_MODE=sim`。`AGENT_MODE=gemini` 搭配 `REVIEW_MODE=sim` 是設定錯誤，api 與 worker 會啟動失敗並說明原因。
- 費用：單價表是 repo 根目錄的 `pricing.yaml`（唯讀掛載到 `/app/pricing.yaml`，有生效日期；`gemini-3.8-flash` 2027-01-01 起加倍）。單一任務的上限預設 US$1、每月 US$20，設為 0 表示不設上限；上限在每次呼叫前檢查，最多超出並行中的呼叫的費用（約 4 次呼叫）。估算：3 個模板 × 2 張、重試一輪的任務約 US$0.18。
- 免費方案：Google 可能用免費方案的輸入（包括商品照與海報）改善產品，並可能由人工審閱，未發表的商品請用付費方案的 key。免費方案實際不收費，但 `job_usage` 仍依付費單價記錄，上限照樣生效。
- 商品照去背：worker 以 BiRefNet（ONNX Runtime）執行，新增商品時自動去背，每張約 13 秒（Docker 實測）。第一次啟動時下載模型（約 1 GB，存在 `models` volume），點開右上角的系統狀態，可看到模型是下載中、載入中或已載入。去背時 worker 約使用 8 GB 記憶體（Docker 實測尖峰約 7.6 GiB；平常約 2 GB）。兩個模型的 Docker 記憶體上限都要設到約 10 GB 以上（Docker Desktop 的 Settings → Resources，WSL2 則改 `.wslconfig`）。`CUTOUT_MODEL=birefnet-general-lite` 較快、下載量較小（約 224 MB），但尖峰只低約 0.75 GB（本機實測 5.75 GB 對 6.50 GB），改用它解決不了記憶體不足；16 GB 的電腦只用去背時請把上限調到約 10 GB（同時使用 RAG 見下面的「RAG 的記憶體」），WSL2 預設是一半的記憶體（16 GB 的電腦是 8 GB），不夠用。
- RAG（`RAG_MODE=bge`，預設）：worker 第一次啟動時下載 BGE-M3、bge-reranker-v2-m3 與共用的 tokenizer（int8 ONNX，合計約 1.2 GB，存在 `models` volume），核對後先不載入：worker 啟動時的同步發現索引有差異（例如第一次啟動或 Chroma 重建）時就會載入；沒有差異時，第一次檢索才載入。載入後常駐。系統狀態的「RAG 模型」依序顯示下載中、已就緒（第一次檢索時載入）、載入中、已載入。下載或載入期間送出的任務會在「檢索」階段等候。
- RAG 的記憶體：模型載入後 worker 約再多用 1.7 GB（Docker 實測 1.75 GB；沒有載入時約 0.1 GB，為去背用模擬版時的實測）。與去背的尖峰相加約 10 GB，Docker 的記憶體上限請比上面的建議再多留約 2 GB（例如 12 GB）。16 GB 的電腦同時使用去背與 RAG 時，Docker 上限請設約 12 GB；不夠時改用 `RAG_MODE=sim`，也就是模擬檢索（不下載模型、不寫入 Chroma）。
- Chroma：`chroma` 服務（`127.0.0.1:8001`，容器之間為 `chroma:8000`），資料存在 `chroma` volume，worker 等它健康後才啟動。

自己的資料：

- **品牌**：複製 `brands/_template.yaml` 成 `brands/<品牌 id>.yaml` 填寫，改完執行 `docker compose restart api worker`（變更的切塊在 worker 啟動時或下一次檢索前重新向量化，寫入 Chroma）。格式錯誤的品牌會略過，原因顯示在系統狀態。
- **品牌手冊**：到「品牌知識庫」上傳 `.md`、`.markdown`、`.txt`（UTF-8）或 `.pdf`。PDF 只讀取文字層：掃描檔沒有文字，要先轉成文字（不做 OCR）；有密碼或權限保護的要先移除保護。單檔 20 MB、20 萬字以內。進度條顯示切塊、向量化（`bge` 模式為真實向量的前 6 維）與寫入；同一個檔名重新上傳會取代原本的切塊。
- **歷史回寫**：在新任務選定海報後，worker 把它寫成「歷史回寫」切塊（商品名稱、模板、審查分數、標題與副標、賣點、正向提示詞的前 120 字），之後的任務檢索得到。
- **商品照**：放在 `assets/products/`，到「商品庫 → 本機資料夾」匯入；也可以直接上傳（存在 `data/`）。這兩個資料夾都不會上傳 GitHub。去背結果存在 `data/products/{商品 id}/`。

## 只看前端（mock 模式）

```bash
cd web
npm ci
npm run dev
```

瀏覽器內模擬整條流程，不需要後端；作品集 Demo 也是這個模式。

## 開發 live 模式

先停掉 Docker 的 web、api、worker 與 composer，只留 postgres、redis 與 chroma：

```bash
docker compose stop web api worker composer
docker compose up -d postgres redis chroma
```

不先停掉的話：Docker 的 web 與 api 佔用 3000 與 8000 埠，本機的前端與 api 起不來；Docker 的 worker 與本機的 worker 共用同一個 `jobs` 佇列，而且 Docker worker 啟動時的復原會把本機 worker 正在執行的任務標記為失敗。

接著各開一個終端機：

| 目錄 | 指令 | 服務 |
|---|---|---|
| `backend/` | `uv run uvicorn app.api.main:app --port 8000 --reload` | api |
| `backend/` | `uv run python -m app.worker` | worker |
| `web/` | `npm run composer` | composer（3900 埠；先執行一次 `npm run fonts`） |
| `web/` | `NEXT_PUBLIC_API_MODE=live API_PROXY_URL=http://127.0.0.1:8000 npm run dev` | 前端（/api、/files、/ws 轉給 api） |

Windows PowerShell 不能在指令前加環境變數，前端改用：

```powershell
$env:NEXT_PUBLIC_API_MODE='live'; $env:API_PROXY_URL='http://127.0.0.1:8000'; npm run dev
```

`$env:` 只在該視窗有效；同一個視窗接著要跑 `npm run e2e` 或 `npm run build`（mock）的話，先執行 `Remove-Item Env:NEXT_PUBLIC_API_MODE, Env:API_PROXY_URL`。

本機的 worker 把模型下載到 repo 根目錄的 `models/`（已在 `.gitignore`），第一次啟動時下載約 1.2 GB 的 RAG 模型。不想下載的話，api 與 worker 都改用模擬檢索（`.env` 的 `RAG_MODE=sim`，api 與 worker 都會讀到；或在兩個視窗都設定）：

```powershell
$env:RAG_MODE='sim'; uv run python -m app.worker
```

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

`REVIEW_MODE=sim` 時 Gemini 的 VLM 審查無法使用，所以也要設 `AGENT_MODE=sim`（api 與 worker 都要）。只想省下 Gemini 的費用時，只設 `AGENT_MODE=sim` 即可（Agent 與 VLM 審查用模擬版，審查用海報照常繪製）。

開啟 http://127.0.0.1:3000（前端）；API 文件在 http://127.0.0.1:8000/docs。開發結束後，停掉本機的服務，再 `docker compose up -d` 回到 Docker 版。

## 測試

| 目錄 | 指令 | 內容 |
|---|---|---|
| `backend/` | `uv run pytest` | 後端（需要 `docker compose up -d postgres redis chroma`，以及在 `web/` 執行過 `npm run fonts`；使用 PostgreSQL 與 Chroma 的 `genai_test` 資料庫、Redis 第 15 號資料庫，會自行在 3902 埠啟動 composer，缺少字型時立即失敗並提示）。不讀 `.env`，開發用的 `RAG_MODE`、`REVIEW_MODE`、`AGENT_MODE` 與 `GEMINI_API_KEY` 不影響測試；不呼叫真的 Gemini API（Gemini 的 client 以 respx 重播 `tests/data/gemini/` 的回應，任務流程用假的 Gemini）。`models/` 有 RAG 模型檔時，也會執行標記 `model` 的真模型測試 |
| `backend/` | `uv run pytest -m live` | 手動執行：呼叫真的 Gemini API（需要 `GEMINI_API_KEY`，會產生少量費用），需求拆解、Prompt 構建與 VLM 審查各一次，只檢查格式與護欄。沒有 key 時略過 |
| `web/` | `npm run test` | 前端與 composer 的單元測試；伺服器端繪製海報的測試需要字型（`npm run fonts`），沒有字型時略過並提示 |
| `web/` | `npm run e2e` | mock 模式 E2E |
| `web/` | `npm run e2e:live` | live 模式 E2E：以獨立的 compose 專案啟動整套服務（審查用 `REVIEW_MODE=composer`；Agent、RAG 與去背用模擬版，`AGENT_MODE=sim` 且不帶 key），測完移除，不影響平常的資料 |
| `web/` | `npm run fixtures` | 重新產生 `contracts/fixtures/`（後端與前端一致性測試的固定測資） |
