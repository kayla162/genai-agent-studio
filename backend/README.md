# 虛實整合 GenAI Agent — 後端

FastAPI（REST、WebSocket、檔案）與 SAQ worker（任務流程、RAG、文件上傳、去背、回寫），共用同一份程式碼與映像檔。
Python 3.13，以 [uv](https://docs.astral.sh/uv/) 管理。

## 開始

```bash
docker compose up -d postgres redis chroma   # 在 repo 根目錄
cd backend
uv sync
```

| 指令 | 用途 |
|---|---|
| `uv run uvicorn app.api.main:app --port 8000 --reload` | api（啟動時執行 migration 並匯入 `brands/*.yaml`） |
| `uv run python -m app.worker` | worker（啟動時把中斷的任務標記失敗，排隊中的重新放回佇列；在背景準備去背與 RAG 模型，再把品牌同步到 Chroma） |
| `uv run pytest` | 測試：重建 PostgreSQL 的 `genai_test` 資料庫、使用 Redis 第 15 號資料庫與 Chroma 的 `genai_test` database（需要 `docker compose up -d postgres redis chroma`），並在 3902 埠啟動 composer（需要 `web/` 已 `npm ci` 與 `npm run fonts`；composer 缺少字型就結束，測試立即失敗並提示）。測試不讀 `.env`（設定一律以 `_env_file=None` 建立），環境變數仍然有效 |
| `uv run pytest -m model` | 只跑真模型的測試（標記 `model`）：repo 根目錄的 `models/` 有模型檔時才執行，否則略過。去背模型的測試另外需要以 `CUTOUT_TEST_PHOTO` 指定一張商品照（例如 `CUTOUT_TEST_PHOTO=../data/uploads/xxx.jpg uv run pytest -m model`） |
| `uv run ruff check . && uv run ruff format --check .` | lint 與格式 |
| `uv run mypy` | 型別檢查（strict） |
| `uv run alembic revision --autogenerate -m "說明"` | 新增 migration（產生後自動以 ruff 修正與排版，見 `alembic.ini` 的 `post_write_hooks`） |

設定來自環境變數或 repo 根目錄的 `.env`（見 `app/settings.py` 與 `.env.example`）。預設值對應本機開發：PostgreSQL 在 5433 埠（避開 Windows 原生的 5432）、Chroma 在 8001 埠（8000 給 api）、一律使用 `127.0.0.1`。

| 變數 | 預設 | 說明 |
|---|---|---|
| `RAG_MODE` | `bge` | `bge`：BGE-M3＋Reranker＋Chroma；`sim`：模擬檢索（固定的召回與 Rerank 順序，不下載模型、不連 Chroma；測試與 live E2E 使用） |
| `REVIEW_MODE` | `composer` | `composer`：composer 繪製審查用海報（存到 `data/jobs/`），量出主色後審查，分數不加抖動；`sim`：不畫圖，審查結果與前端 mock 相同（parity 測試與作品集 Demo）。live E2E 使用 `composer` |
| `COMPOSER_URL` | `http://127.0.0.1:3900` | Docker 內為 `http://composer:3900`。`REVIEW_MODE=composer` 時 composer 要有海報字型（在 `web/` 執行 `npm run fonts`） |
| `CHROMA_URL` | `http://127.0.0.1:8001` | Docker 內為 `http://chroma:8000` |
| `MODELS_DIR` | repo 根目錄的 `models/` | 去背與 RAG 的模型檔（Docker 為 `models` volume） |

PowerShell 不能在指令前加環境變數，例如改用模擬檢索執行 worker：

```powershell
$env:RAG_MODE='sim'; uv run python -m app.worker
```

本機的 worker 預設是 `REVIEW_MODE=composer`，每張候選都會呼叫 composer 的 `/render`。先在 `web/` 執行 `npm run fonts` 與 `npm run composer`（缺少字型時 composer 會結束）；不需要審查用海報時改用模擬審查（api 也要設定同一個值，系統狀態才會一致）：

```powershell
$env:REVIEW_MODE='sim'; uv run python -m app.worker
```

## API

- 文件：http://127.0.0.1:8000/docs
- 錯誤一律回傳 `{ error: { code, message } }`，message 為繁體中文，前端直接顯示。
- `WS /ws/jobs/{id}?after={seq}`：先補送 `seq` 大於 `after` 的事件，再轉送即時事件；任務結束且事件送完後以 1000 關閉，任務不存在時以 4404 關閉。Redis 停止或訂閱失敗時不中斷，改為每秒從資料庫讀取新事件，直到任務結束。
- `POST /api/brands/{id}/documents`：multipart，欄位 `file`（`.md`、`.markdown`、`.txt` 為 UTF-8；`.pdf` 以 pypdf 抽出文字層）。api 先檢查副檔名、大小（20 MB）、編碼、PDF 是否加密或沒有文字、文字長度（20 萬字），有錯直接回 400，不開始串流；之後以 NDJSON 串流回報切塊、向量化與寫入的進度。120 秒沒有任何進度時回報逾時（大份手冊只要持續有進度就不算逾時）。
- `POST /api/jobs/{id}/select`：寫入歷史紀錄後，由 worker 回寫成歷史切塊，最多等 10 秒；逾時、失敗或被中止時 `writtenToRag` 為 false（不回 500，歷史紀錄已經建立）。
- `GET /api/status`：各服務的狀態，每項最多等 3 秒。composer 與 RAG 的兩項：

| 元件 | 狀態 |
|---|---|
| composer（排版、繪製與規則審查） | `GET {COMPOSER_URL}/health`：`REVIEW_MODE=composer` 時顯示載入的海報字型與網址，composer 沒有回報字型（舊的映像檔）時為「異常」，提示重新建置；`REVIEW_MODE=sim` 時為「模擬」（模擬審查，不繪製審查用海報）；連不上為「異常」 |
| 向量庫（Chroma） | `GET {CHROMA_URL}/api/v2/heartbeat`：正常時顯示網址，連不上為「異常」；`RAG_MODE=sim` 時不檢查，顯示「模擬模式不使用向量庫」 |
| RAG 模型（BGE-M3＋Reranker） | 讀 Redis 的 `rag:model`（worker 回報）：模擬、下載中（約 1.2 GB）、已就緒（第一次檢索時載入）、載入中、已載入、失敗（原因）；worker 還沒回報時為「worker 尚未回報」 |

## 任務流程

1. `POST /api/jobs` 驗證後寫入任務，送出 `job.accepted` 與 `job.status queued`，放進 `jobs` 佇列。
2. worker 一次執行一個生圖任務（只有一張 GPU）；文件上傳與回寫在 `tasks` 佇列，最多同時兩個；商品照去背在 `cutouts` 佇列，一次一個。
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

- **切塊**：品牌設定檔的 guidelines 與 `caseStudies`、上傳的手冊、選定的海報（歷史回寫）都存在 PostgreSQL 的 `brand_chunks`。切塊規則是前端 `web/src/lib/rag/chunk.ts` 的 Python 移植（`app/rag/chunking.py`），以 golden fixture（`contracts/fixtures/chunks.json`）確認兩邊結果完全相同。
- **向量庫**：Chroma 每個品牌一個 collection `{brandId}_ci`（cosine），切塊 id 與 PostgreSQL 相同，向量化的文字為「章節：內容」。PostgreSQL 為準：worker 啟動時（模型核對完成後）與每次檢索前比對兩邊，補上缺少或內容不同的、刪除多餘的，沒有差異時不載入模型。所有寫入 Chroma 的動作都取得同一個品牌鎖。
- **模型**：BGE-M3 與 bge-reranker-v2-m3 的 int8 ONNX，共用一個 tokenizer（合計約 1.2 GB，網址固定 commit、核對 SHA-256）。worker 啟動時下載並核對，第一次向量化或 Rerank 時才載入，之後常駐；推論在專用的單一執行緒逐筆計算（批次大小 1），不與去背共用。
- **記憶體**：模型載入後 worker 約再多用 1.7 GB（Docker 實測 1.75 GB；沒有載入時約 0.1 GB，為去背用模擬版時的實測）。
- **檢索**：查詢為「品牌名｜商品名｜一句話需求｜賣點」；向量召回 8 筆（不含合規替代用語）→ 逐筆 Rerank（分數為 sigmoid，很小，只看排名）→ 前 5 筆進入 Prompt。Query Rewriting 時以改寫後的查詢召回 4 筆（合規替代用語與法規切塊）並 Rerank。模型準備中時任務在「檢索」階段等候；模型準備失敗或 Chroma 連不上時任務失敗，原因以中文說明。
- **上傳**：worker 切塊、逐塊向量化，再把 PostgreSQL 與 Chroma 中同一個檔名的切塊換成新的。錯誤碼：品牌不存在 `not_found`、沒有可用文字 `invalid`、模型或 Chroma 無法使用 `unavailable`、其他 `internal`。
- **歷史回寫**：選定的海報寫成切塊 `{brandId}#hist-{historyId}`（以 id upsert，重跑不會重複），寫入 PostgreSQL 後再寫入 Chroma；寫入 Chroma 失敗時，下一次同步會補上。

## 目錄

```
app/
├─ api/            FastAPI：main.py（入口與錯誤格式）、catalog、jobs、files、services
├─ pipeline/       任務流程（runner）、外部服務介面（ports）、審查用海報與審查（review）、模擬版（sim）
├─ adapters/       composer 用戶端（版型、/render、/review、/sim/*、/health）
├─ cutout/         商品照去背：前後處理（processing）、BiRefNet 與模擬版（segmenter）、模型清單（models）、狀態鍵（state）、準備與狀態（engine）
├─ rag/            RAG：切塊（chunking）、抽字（extract：Markdown、純文字、PDF）、模型清單（models）、ONNX 推論（encoder）、
│                  準備與狀態（engine、state）、錯誤（errors）、Chroma 用戶端（store）、PostgreSQL → Chroma 同步（sync）、
│                  檢索（retriever）、歷史回寫切塊（history）
├─ core/           時間（clock：一律 UTC）、偽隨機數（rng：與前端的 num.ts 相同，模擬的 seed 才會一致）、
│                  數字轉字串（jsnum：與 JavaScript 的 String(number) 相同）
├─ db/             SQLAlchemy 模型與連線
├─ repo/           資料存取：品牌與商品（catalog）、任務（jobs）、歷史紀錄（history）
├─ contract.py     Pydantic 模型（對應 web/src/types/contract.ts）
├─ errors.py       領域錯誤（AppError 與子類別）；api 轉成 { error: { code, message } }
├─ templates.py    通路模板（與 web/src/lib/compose/templates.ts 相同）
├─ events.py       事件保存與推送、WebSocket 串流
├─ files.py        /files/... 網址與資料夾的對應（api 提供檔案、worker 讀取商品照與寫入審查用海報）
├─ queues.py       SAQ 佇列
├─ worker.py       worker 的任務、啟動時復原與模型準備
├─ modelfiles.py   模型檔的下載與核對（去背與 RAG 共用）
├─ brands.py       品牌設定檔（brands/*.yaml）的驗證與匯入
├─ stats.py        成效儀表板統計（與前端的結果完全相同）
└─ settings.py
migrations/        Alembic
tests/             pytest；與前端的一致性測試讀取 contracts/fixtures/（由 web 的 npm run fixtures 產生）；
                   fake_encoder.py（不需要模型檔的 Encoder）、data/ci-sample.pdf（含中文文字層的 PDF）
```
