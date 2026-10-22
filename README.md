# 虛實整合 GenAI Agent

一句話需求 → Agent 拆解 → RAG 檢索品牌規範 → 多通路生圖 → 合規審查與自動重試 → 挑圖改字 → 匯出。
既是每天做商品圖的工具，也是全端技術的作品集。

- **前端**：Next.js 16（靜態輸出）、TypeScript、Tailwind CSS v4、shadcn/ui、Zustand：[web/README.md](web/README.md)
- **後端**：FastAPI、SAQ worker、PostgreSQL（SQLAlchemy、Alembic）、Redis：[backend/README.md](backend/README.md)
- **RAG**：Chroma 向量庫、BGE-M3 向量化與 bge-reranker-v2-m3 Rerank（ONNX Runtime，CPU）：[RAG 設計規格](docs/superpowers/specs/2026-10-21-plan5-rag-design.md)
- **composer**：Node 服務，直接執行前端的 TypeScript（版型與模擬邏輯），讓前後端只有一份實作
- **規格**：[第二階段設計規格](docs/superpowers/specs/2026-10-07-phase2-backend-design.md)；各計畫在 [docs/superpowers/plans/](docs/superpowers/plans/)

## 進度

| 計畫 | 內容 | 狀態 |
|---|---|---|
| Plan 1–3 | 前端與瀏覽器內模擬（mock 模式）、Agent 透視、成效儀表板 | 完成 |
| Plan 4 | 後端骨架與即時串流：全部 API、WebSocket、worker、Docker | 完成（外部服務為模擬版） |
| Plan 5 | RAG：Chroma、BGE-M3 與 Reranker、PDF 手冊上傳、歷史回寫 | 完成（Agent、生圖與審查仍為模擬版） |
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
                              │          └ models/（去背與 RAG 的 ONNX 模型）
                            chroma（向量庫，127.0.0.1:8001）
```

- 每則任務事件都在同一個交易中取得序號（`seq`）並寫入資料庫，再經 Redis 推送到 WebSocket；斷線或重新整理後，前端以最後收到的 `seq` 接續。Redis 停止時，WebSocket 改為每秒從資料庫讀取新事件，連線不中斷。
- **RAG**：品牌設定檔、上傳的手冊與選定的海報都切成切塊，存在 PostgreSQL；worker 以 BGE-M3 向量化後寫入 Chroma（每個品牌一個 collection）。任務先向量召回 8 筆、再以 Reranker 重新排序，前 5 筆放進 Prompt。PostgreSQL 為準，Chroma 只是索引：worker 啟動時與每次檢索前都會比對並補齊，Chroma 的資料遺失時會自動重建。
- Gemini 與 ComfyUI 目前是模擬版，行為與 mock 模式的劇本相同（第一輪刻意失誤，Query Rewriting 後通過）。右上角的連線狀態可以展開各服務的狀態，模擬版會標示「模擬」。

## 用 Docker 執行（live 模式）

需要 Docker Desktop（映像檔取自 AWS 的官方映像鏡像，Chroma 取自 GitHub 的 `ghcr.io/chroma-core/chroma:1.5.9`，都不必登入）。

```bash
docker compose up -d --build
```

- 前端：http://127.0.0.1:3000
- API 文件：http://127.0.0.1:3000/docs
- 停止：`docker compose down`（資料保留在 volume；加上 `-v` 會清空資料庫與 `chroma` 向量庫，也會刪除 `models` volume，下次啟動要重新下載約 1 GB 的去背模型與約 1.2 GB 的 RAG 模型）
- 設定：複製 `.env.example` 成 `.env` 後修改（模擬速度、首輪是否刻意失誤、去背模型、RAG 模式等），再 `docker compose up -d`
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
| `web/` | `npm run composer` | composer（3900 埠） |
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

開啟 http://127.0.0.1:3000（前端）；API 文件在 http://127.0.0.1:8000/docs。開發結束後，停掉本機的服務，再 `docker compose up -d` 回到 Docker 版。

## 測試

| 目錄 | 指令 | 內容 |
|---|---|---|
| `backend/` | `uv run pytest` | 後端（需要 `docker compose up -d postgres redis chroma`；使用 PostgreSQL 與 Chroma 的 `genai_test` 資料庫、Redis 第 15 號資料庫，會自行啟動 composer）。`models/` 有 RAG 模型檔時，也會執行標記 `model` 的真模型測試 |
| `web/` | `npm run test` | 前端與 composer 的單元測試 |
| `web/` | `npm run e2e` | mock 模式 E2E |
| `web/` | `npm run e2e:live` | live 模式 E2E：以獨立的 compose 專案啟動整套服務，測完移除，不影響平常的資料 |
| `web/` | `npm run fixtures` | 重新產生 `contracts/fixtures/`（後端與前端一致性測試的固定測資） |
