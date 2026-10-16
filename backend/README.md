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
2. worker 一次執行一個生圖任務（只有一張 GPU）；文件上傳與回寫在 `tasks` 佇列，最多同時兩個；商品照去背在 `cutouts` 佇列，一次一個。
3. 每則事件在同一個交易中鎖定任務列並取得下一個 `seq`，commit 後發布到 Redis 頻道 `job:{id}`；結束任務的 `job.status` 一定是最後一則。
4. 取消：排隊中的直接取消；執行中的設定旗標，worker 在步驟之間停止。

外部服務都經過 `app/pipeline/ports.py` 的介面；目前由 `app/pipeline/sim.py` 的模擬版實作（Agent 與審查透過 composer 沿用前端 mock 的 TypeScript），之後的計畫逐一換成 Chroma、Gemini 與 ComfyUI。

## 目錄

```
app/
├─ api/            FastAPI：main.py（入口與錯誤格式）、catalog、jobs、files、services
├─ pipeline/       任務流程（runner）、外部服務介面（ports）、模擬版（sim）
├─ adapters/       composer 用戶端
├─ cutout/         商品照去背：前後處理（processing）、BiRefNet 與模擬版（segmenter）、模型下載（models）、準備與狀態（engine）
├─ core/           時間（clock：一律 UTC）與偽隨機數（rng：與前端的 num.ts 相同，模擬的 seed 才會一致）
├─ db/             SQLAlchemy 模型與連線
├─ repo/           資料存取：品牌與商品（catalog）、任務（jobs）、歷史紀錄（history）
├─ contract.py     Pydantic 模型（對應 web/src/types/contract.ts）
├─ errors.py       領域錯誤（AppError 與子類別）；api 轉成 { error: { code, message } }
├─ templates.py    通路模板（與 web/src/lib/compose/templates.ts 相同）
├─ events.py       事件保存與推送、WebSocket 串流
├─ files.py        /files/... 網址與資料夾的對應（api 提供檔案、worker 讀取商品照）
├─ queues.py       SAQ 佇列
├─ worker.py       worker 的任務與啟動時復原
├─ brands.py       品牌設定檔（brands/*.yaml）的驗證與匯入
├─ stats.py        成效儀表板統計（與前端的結果完全相同）
└─ settings.py
migrations/        Alembic
tests/             pytest；與前端的一致性測試讀取 contracts/fixtures/（由 web 的 npm run fixtures 產生）
```
