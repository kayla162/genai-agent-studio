# 虛實整合 GenAI Agent — 前端

Next.js 16（App Router，靜態輸出）+ TypeScript + Tailwind CSS v4 + shadcn/ui + Zustand。畫面只依賴 `ApiClient` 介面，有兩種實作，送出的事件格式相同（`src/types/contract.ts`）：

- **mock**（預設）：瀏覽器內的 `MockApiClient` 模擬整條 Agent 流程，不需要後端；作品集 Demo 使用。
- **live**：`HttpApiClient` 連線 FastAPI（REST＋WebSocket），任務由後端執行。整套服務的執行方式見 [repo 根目錄的 README](../README.md)。

## 需求

- Node.js 24、npm 11

## 開始

```bash
npm ci
npm run dev
```

開啟 http://127.0.0.1:3000（會導向「新任務」），預設為 mock 模式。

live 模式：先啟動後端（要先停掉 Docker 的 web、api 與 worker，見 [repo 根目錄的 README](../README.md#開發-live-模式)），再執行：

```bash
# bash／zsh
NEXT_PUBLIC_API_MODE=live API_PROXY_URL=http://127.0.0.1:8000 npm run dev
```

```powershell
# Windows PowerShell
$env:NEXT_PUBLIC_API_MODE='live'; $env:API_PROXY_URL='http://127.0.0.1:8000'; npm run dev
```

開發伺服器會把 `/api`、`/files`、`/ws` 轉給後端。也可以把這兩個值寫進 `.env.development.local`（見 `.env.example`）：它只在 `next dev` 生效；`.env.local` 在 `next build` 也會套用，之後的 `npm run e2e`（mock）就會建置出 live 版的前端。正式的 live 版由 Docker 的 nginx 提供靜態輸出。

右上角的連線狀態：連不上後端，或收到不是後端錯誤 JSON 的 5xx（nginx 連不上 api 時的 502、504，或後端停止時 `next dev` 轉送失敗回的 500）時顯示「連線中斷」，並定期確認後端是否恢復。

## 指令

| 指令 | 用途 |
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

## 頁面

| 模式 | 路由 | 頁面 |
|---|---|---|
| 工作台 | `/studio` | 新任務：一句話需求 → 生成 → 挑圖改字 → 匯出 zip |
| 工作台 | `/products` | 商品庫：上傳／拖放、自動去背（live：BiRefNet；mock：示意）與預覽、本機資料夾匯入（live 模式） |
| 工作台 | `/queue` | 批次佇列：多商品 × 多模板 |
| 工作台 | `/history` | 歷史紀錄：篩選、收藏、以相同設定重做 |
| 工作台 | `/brands` | 品牌知識庫：CI、禁用詞、RAG 切塊（標示新上傳、歷史回寫、歷史案例、Query Rewriting 專用）、上傳文件（live：`.md`、`.txt`、`.pdf`；mock：`.md`、`.txt`） |
| Agent 透視 | `/agent` | 任務透視：流程節點、WebSocket 事件串流、JSON Prompt 與注入參數、RAG Rerank、合規報告與 BBox 疊圖、重試 diff |
| Agent 透視 | `/dashboard` | 成效儀表板：通過率、平均重試次數、平均耗時、每張成本、各檢查項失敗分布、Rerank 對命中率的影響 |

## 資料保存

- **mock 模式**：商品、歷史紀錄、上傳的品牌文件與選定海報的歷史回寫切塊，以及已結束的任務（最近 40 筆，含完整事件）存在瀏覽器的 IndexedDB（資料庫 `genai-poster-agent`）；清除網站資料就會重置。mock 只能讀取 `.md`、`.txt`，PDF 要用 live 模式上傳。
- **live 模式**：存在後端的 PostgreSQL（RAG 切塊另外寫入 Chroma 向量庫）；上傳的商品照存在 repo 根目錄的 `data/`。上傳品牌文件時以 `FormData` 傳送檔案，PDF 由後端抽出文字層（單檔 20 MB、20 萬字以內，掃描檔要先轉成文字）。WebSocket 斷線時以最後收到的序號重新連線（1 秒起，最長 10 秒）；重新整理後，新任務頁面會接續這個分頁的任務。
- 每則事件都帶序號（`seq`）與時間戳（`ts`）。Agent 透視用來顯示事件串流與各節點耗時；儀表板依此統計耗時。
- 自己的商品照可放在 repo 根目錄的 `assets/products/`（已在 `.gitignore`，不會上傳 GitHub），live 模式下到「商品庫」一鍵匯入，檔名即商品名稱。
- 字型使用 `@fontsource-variable` 自帶的 Noto Sans／Serif TC，執行時不連外部網路。

## Demo 控制台（只有 mock 模式）

畫面右下角「Demo」：播放速度 1×／2×／4×、強制首輪失敗（展示 Query Rewriting 與重試）、強制全部失敗（展示「需人工審核」）。

成效儀表板可一鍵「產生 12 個示範任務」：直接算出完整事件（時間戳以 1× 計）並寫入任務紀錄，兩個品牌各有重試後通過、首輪通過與需人工審核的任務。每張成本是依 `lib/stats/dashboard.ts` 的單價估算。

## 目錄

```
src/
├─ app/                 路由
├─ components/          ui（shadcn）、common（EmptyState、PageHeader）、layout、studio、product、queue、history、brands、poster、agent、dashboard
├─ lib/
│  ├─ api/              ApiClient 介面；mock/（MockApiClient、劇本、示範資料與示範任務、IndexedDB）；http/（HttpApiClient、WebSocket 重新連線）
│  ├─ agent/            Prompt 構建、修正策略、版本差異、流程節點狀態、事件摘要、透視用的資料整理
│  ├─ compose/          版型、排版引擎（scene）、程序化素材（art）、Canvas 繪製（paint／render）
│  ├─ review/           規則型合規審查、ΔE2000、文案重新檢查
│  ├─ jobs/             事件 → 畫面狀態（reducer）
│  ├─ stats/            成效儀表板統計與成本估算
│  ├─ export/           檔名、zip、下載
│  ├─ core/             共用的基礎函式：round1／clamp 與可重現的亂數（num）、視覺寬度（text）、矩形運算（geometry）、deepFreeze（freeze）
│  ├─ history/          歷史紀錄的篩選（品牌、通路、日期、收藏），最新的在前
│  ├─ image/            上傳前把商品照縮到最長邊 1600 px（downscale）
│  ├─ rag/              品牌文件的切塊、標籤與向量預覽（chunk；後端的 Python 移植以 golden fixture 比對）、切塊類型（kind）、歷史回寫切塊（history；與後端格式相同）
│  └─ store/            Zustand stores
├─ test/                測試共用的資料（fixtures）、golden fixtures 的產生（golden）與切塊的範例文件（chunk-samples）
└─ types/contract.ts    前後端資料約定
composer/               Node 服務：版型與模擬邏輯（/layout、/sim/brief、/sim/prompt、/sim/review、/sim/fixes），由後端呼叫
scripts/                產生 fixtures、提供靜態輸出（Playwright 使用）
e2e/                    Playwright（mock）：主流程（含匯出 zip）、Agent 透視重試 diff、儀表板、手機寬度
e2e-live/               Playwright（live）：主流程、重新整理後接續、API 重新啟動後重新連線、取消、文件（Markdown 與 PDF）與商品照上傳
Dockerfile、nginx.conf  live 版（nginx）與 composer 的映像檔
```
