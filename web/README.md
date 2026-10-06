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
| Agent 透視 | `/agent`、`/dashboard` | Plan 3 實作（目前為事件 Log 與預留頁） |

## 資料保存

- 商品、歷史紀錄與上傳的品牌文件存在瀏覽器的 IndexedDB（資料庫 `genai-poster-agent`）；清除網站資料就會重置。
- 自己的商品照可放在 repo 根目錄的 `assets/products/`（已在 `.gitignore`，不會上傳 GitHub），開發模式下到「商品庫」一鍵匯入，檔名即商品名稱。
- 字型使用 `@fontsource-variable` 自帶的 Noto Sans／Serif TC，執行時不連外部網路。

## Demo 控制台

畫面右下角「Demo」：播放速度 1×／2×／4×、強制首輪失敗（展示 Query Rewriting 與重試）、強制全部失敗（展示「需人工審核」）。

## 目錄

```
src/
├─ app/                 路由與 api/local-products（開發用）
├─ components/          ui（shadcn）、layout、studio、product、queue、history、brands、poster、agent
├─ lib/
│  ├─ api/              ApiClient 介面、mock/（MockApiClient、劇本、示範資料、IndexedDB）
│  ├─ agent/            Prompt 構建、修正策略、版本差異
│  ├─ compose/          版型、排版引擎（scene）、程序化素材（art）、Canvas 繪製（paint／render）
│  ├─ review/           規則型合規審查、ΔE2000、文案重新檢查
│  ├─ jobs/             事件 → 畫面狀態（reducer）
│  ├─ export/           檔名、zip、下載
│  ├─ store/            Zustand stores
│  └─ server/           只在伺服器端執行的工具
└─ types/contract.ts    前後端資料約定
```
