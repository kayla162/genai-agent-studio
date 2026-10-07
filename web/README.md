# 虛實整合 GenAI Agent — 前端（第一階段）

Next.js 16（App Router）+ TypeScript + Tailwind CSS v4 + shadcn/ui + Zustand。第一階段由瀏覽器內的 `MockApiClient` 模擬整條 Agent 流程，送出的事件與第二階段 FastAPI WebSocket 相同，所以不需要後端。

## 需求

- Node.js 24、npm 11

## 開始

```bash
npm ci
npm run dev
```

開啟 http://localhost:3000（會導向「新任務」）。預設就是 mock 模式；要明確設定時複製 `.env.example` 成 `.env.local`。

## 指令

| 指令 | 用途 |
|---|---|
| `npm run dev` | 開發伺服器 |
| `npm run test` | Vitest 單元測試 |
| `npm run e2e` | Playwright E2E（自動建置並在 3100 埠啟動正式版；第一次要先執行 `npx playwright install chromium`） |
| `npm run typecheck` | 型別檢查（含路由型別） |
| `npm run lint` | ESLint |
| `npm run build` | 正式建置 |

## 頁面

| 模式 | 路由 | 頁面 |
|---|---|---|
| 工作台 | `/studio` | 新任務：一句話需求 → 生成 → 挑圖改字 → 匯出 zip |
| 工作台 | `/products` | 商品庫：上傳／拖放、去背預覽（示意）、本機資料夾匯入 |
| 工作台 | `/queue` | 批次佇列：多商品 × 多模板 |
| 工作台 | `/history` | 歷史紀錄：篩選、收藏、以相同設定重做 |
| 工作台 | `/brands` | 品牌知識庫：CI、禁用詞、RAG 切塊、上傳文件 |
| Agent 透視 | `/agent` | 任務透視：流程節點、WebSocket 事件串流、JSON Prompt 與注入參數、RAG Rerank、合規報告與 BBox 疊圖、重試 diff |
| Agent 透視 | `/dashboard` | 成效儀表板：通過率、平均重試次數、平均耗時、每張成本、各檢查項失敗分布、Rerank 對命中率的影響 |

## 資料保存

- 商品、歷史紀錄、上傳的品牌文件，以及已結束的任務（最近 40 筆，含完整事件）存在瀏覽器的 IndexedDB（資料庫 `genai-poster-agent`）；清除網站資料就會重置。
- 每則事件都帶序號（`seq`）與時間戳（`ts`）。Agent 透視用來顯示事件串流與各節點耗時；儀表板依此統計耗時。
- 自己的商品照可放在 repo 根目錄的 `assets/products/`（已在 `.gitignore`，不會上傳 GitHub），開發模式下到「商品庫」一鍵匯入，檔名即商品名稱。
- 字型使用 `@fontsource-variable` 自帶的 Noto Sans／Serif TC，執行時不連外部網路。

## Demo 控制台

畫面右下角「Demo」：播放速度 1×／2×／4×、強制首輪失敗（展示 Query Rewriting 與重試）、強制全部失敗（展示「需人工審核」）。

成效儀表板可一鍵「產生 12 個示範任務」：直接算出完整事件（時間戳以 1× 計）並寫入任務紀錄，兩個品牌各有重試後通過、首輪通過與需人工審核的任務。每張成本是依 `lib/stats/dashboard.ts` 的單價估算。

## 目錄

```
src/
├─ app/                 路由與 api/local-products（開發用）
├─ components/          ui（shadcn）、layout、studio、product、queue、history、brands、poster、agent、dashboard
├─ lib/
│  ├─ api/              ApiClient 介面、mock/（MockApiClient、劇本、示範資料與示範任務、IndexedDB）
│  ├─ agent/            Prompt 構建、修正策略、版本差異、流程節點狀態、事件摘要、透視用的資料整理
│  ├─ compose/          版型、排版引擎（scene）、程序化素材（art）、Canvas 繪製（paint／render）
│  ├─ review/           規則型合規審查、ΔE2000、文案重新檢查
│  ├─ jobs/             事件 → 畫面狀態（reducer）
│  ├─ stats/            成效儀表板統計與成本估算
│  ├─ export/           檔名、zip、下載
│  ├─ store/            Zustand stores
│  └─ server/           只在伺服器端執行的工具
└─ types/contract.ts    前後端資料約定
e2e/                    Playwright：主流程（含匯出 zip）、Agent 透視重試 diff、儀表板、手機寬度
```
