# 虛實整合 GenAI Agent：前端（第一階段）設計規格

- 日期：2026-10-05
- 狀態：待使用者審閱
- 原型參考：`prototype/index.html`（單檔 HTML 示範，已確認流程與視覺方向）

## 1. 目標與定位

同一套系統要同時滿足兩件事：

1. **每天使用的商品圖工具**：保留真實商品照，AI 只生成背景／情境，文字由排版引擎疊加，一次輸出多通路尺寸。
2. **展示作品**：完整呈現課程技術棧。每項技術都在實際流程中負責一件真正的工作，不是裝飾。

| 課程章節 | 技術 | 在流程中的工作 |
|---|---|---|
| Ch19、21 LLM 與 Agent | Gemini 3.7 Flash／Unsloth 微調 Llama 3.2 Vision | 拆解一句話需求、產生文案、版面 BBox 與 ComfyUI 參數；審查失敗時改寫 Prompt |
| Ch22 多模態 RAG | Chroma + BGE Reranker | 檢索品牌 CI、禁用詞、Logo／字型規範、歷史優秀案例（含使用者挑中的圖） |
| Ch20 圖像生成控制 | ComfyUI `workflow_api.json`（ControlNet、IP-Adapter、SDXL／Flux）或 Ideogram 4.0 | 去背、背景生成、打光融合、放大；以 BBox 控制物件與文字佈局 |
| Ch22 後端與傳輸 | FastAPI + WebSocket + Docker | 任務調度、即時進度推送、一鍵啟動（第二階段） |

## 2. 本階段範圍

**要做**
- Next.js 前端，含「工作台」與「Agent 透視」雙模式，所有頁面可操作
- 一層 API 介面，先接 `MockApiClient`：在瀏覽器內依劇本模擬整條流程，送出的事件與未來 FastAPI WebSocket 完全相同
- 真正可用的部分：商品照上傳與保存、排版引擎（文字即時編輯）、規則型合規檢查（禁用詞、ΔE 色差、BBox 重疊）、PNG 與 zip 匯出
- 型別定義即前後端約定（`web/src/types/contract.ts`）

**不做（第二階段以後）**
- FastAPI、Chroma、ComfyUI、VLM 的真實串接與 Docker Compose
- 真正的去背與圖像生成（本階段背景為程序化 SVG 示意圖）
- 登入與多人權限

## 3. 品牌與示範資料

- **SÉLUNE 晞月**（美妝保養）：主色 #B76E79、米白 #F6EFE9、珍珠金 #C9A96E、墨灰 #3A3335；示範商品「極光玻尿酸修護精華 30ml」
- **霧嶼咖啡 MISTY ISLE**（虛構冷萃咖啡品牌）：對應規格 Demo 句「幫我設計一款簡約風格的冷萃咖啡宣傳海報」；示範商品「單一產區冷萃咖啡 330ml」
- 每個品牌各有：色票、字型、禁用詞庫、CI 手冊切塊、歷史優秀案例

## 4. 使用者主流程（工作台 › 新任務）

1. 輸入一句話需求 → Agent 拆成結構化欄位（商品、賣點、客群、語氣、檔期、價格），欄位可手動修改
2. 從商品庫選商品（真實照片），勾選通路模板（可多選）
3. 設定每個模板的候選張數（預設 4）→ 開始生成
4. 結果牆：依模板分組，每張附合規分數徽章；點開可看單張審查細節
5. 選定一張 → 文字編輯器：修改文案、價格、徽章，畫面即時重繪，不重新產圖
6. 匯出：每個模板輸出 PNG，打包成 zip，依「品牌_商品_通路_日期」命名
7. 選定的圖寫入歷史紀錄，並標記「已回寫 RAG（歷史優秀案例）」

**通路模板（預設）**

| 模板 | 比例 | 輸出尺寸 |
|---|---|---|
| 電商主圖 | 1:1 | 1600×1600 |
| 情境圖 | 4:3 | 2048×1536 |
| IG 貼文 | 4:5 | 1440×1800 |
| 限時動態 | 9:16 | 1152×2048 |
| 促銷 Banner | 16:9 | 2048×1152 |

## 5. 頁面

最上方的列：產品名稱、**模式切換（工作台／Agent 透視）**、品牌切換、Demo 模式標示、WebSocket 狀態。

**工作台**

| 路由 | 頁面 | 重點 |
|---|---|---|
| `/studio` | 新任務 | 主流程（第 4 節）；生成中顯示精簡進度條，可一鍵切到 Agent 透視看細節 |
| `/products` | 商品庫 | 上傳／拖放照片、去背預覽（示意）、名稱／特徵／價格編輯 |
| `/queue` | 批次佇列 | 多商品 × 多模板排程，逐筆進度、暫停／取消 |
| `/history` | 歷史紀錄 | 篩選（品牌、通路、日期）、收藏、以相同設定重做 |
| `/brands` | 品牌知識庫 | 色票、禁用詞、CI 手冊切塊列表、歷史案例；上傳文件時展示 chunking → embedding 過程 |

**Agent 透視**

| 路由 | 頁面 | 重點 |
|---|---|---|
| `/agent` | 任務透視 | 預設顯示最新任務，可切換。內容：流程節點圖、WebSocket 事件串流、JSON Prompt、`workflow_api.json` 注入參數對照、RAG 召回與 Rerank 前後分數、合規報告與 BBox 疊圖、重試 diff |
| `/dashboard` | 成效儀表板 | 通過率、平均重試次數、平均耗時、每張成本、各檢查項失敗分布、Rerank 對命中率的影響 |

**流程節點（Agent 透視）**

1. Orchestrator（FastAPI）
2. 需求拆解 Agent（LLM）
3. RAG 檢索（Chroma 召回 → BGE Rerank）
4. Prompt 構建（JSON Prompt + BBox）
5. ComfyUI：去背（BiRefNet）→ 背景生成（SDXL／Flux + ControlNet + IP-Adapter）→ 打光融合（IC-Light）→ 放大
6. 文字排版合成
7. 合規審查：規則（禁用詞、ΔE、OCR 錯字）+ VLM（誇大用語、重疊遮擋、整體品質）
8. 通過 → 寫入 DB 與回傳；未通過 → Query Rewriting 回到 4（必要時重新檢索 3）

## 6. 前端架構

- **技術**：Next.js（App Router）+ TypeScript + Tailwind CSS + shadcn/ui + lucide-react；狀態用 Zustand；圖表用 Recharts；本機保存用 IndexedDB（idb-keyval）；zip 用 JSZip
- **UI 語言**：繁體中文；淺色 SaaS 風格（沿用原型）

**目錄**

```
GenAI Agent/
├─ assets/products/        使用者自己的商品照（.gitignore，不上傳 GitHub）
├─ prototype/index.html    第一版單檔原型
├─ docs/                   規格與計畫
└─ web/                    Next.js 前端
   └─ src/
      ├─ app/              路由：studio、products、queue、history、brands、agent、dashboard
      │  └─ api/local-products/   開發用：列出並讀取 assets/products/ 的照片
      ├─ components/       ui（shadcn）、layout、studio、agent、dashboard…
      ├─ lib/
      │  ├─ api/           ApiClient 介面、mock/（MockApiClient、劇本、示範資料）、http/（第二階段）
      │  ├─ compose/       排版引擎與 Canvas 繪製（預覽與匯出共用）
      │  ├─ review/        規則型合規檢查（禁用詞、ΔE2000、BBox 重疊）
      │  └─ store/         Zustand stores
      └─ types/contract.ts 前後端資料約定
```

**API 介面層**

- `ApiClient` 介面包含：品牌、商品、模板的 CRUD；`createJob(input)`；`subscribe(jobId, onEvent)`；`selectRender`；歷史紀錄；儀表板統計
- `NEXT_PUBLIC_API_MODE=mock|live` 決定使用 `MockApiClient` 或 `HttpApiClient`；元件只依賴介面
- 第二階段的 `HttpApiClient` 以 REST 呼叫 FastAPI，以 WebSocket `/ws/jobs/{jobId}` 接收同樣的事件

## 7. 資料約定（`contract.ts` 摘要）

- `Brand`：id、name、palette（primary／secondary／accent／ink）、fonts、bannedWords、guidelineChunks、caseStudies
- `Product`：id、brandId、name、features[]、price（sale、original）、photo（來源：sample／upload／local）、createdAt。去背圖欄位 `cutout` 由 Plan 2 商品庫任務加入
- `ChannelTemplate`：id、label、ratio、width、height（版型預設以模板 id 對應，不另設 layoutPreset 欄位）
- `JobInput`：brief（一句話）、parsedBrief、productId、templateIds[]、variantsPerTemplate、llm、engine、vlm、maxRetries
- `PromptSpec`：copy（headline、subhead、features、badge、price、disclaimer）、palette、layout（`{id, bbox:[x,y,w,h], z}`[]）、positivePrompt、negativePrompt、injection（`ComfyInjection`）、ragRefs
- `ComfyInjection`：engine（comfyui／ideogram）、workflowFile，以及 params：`{nodeId, input, label, value}`[]，涵蓋 positive／negative prompt、seed、sampler、steps、cfg、product image、ControlNet 強度、IP-Adapter 權重、排版座標
- `RagHit`：chunkId、source、section、text、vectorScore、rerankScore
- `Render`：id、jobId、round、templateId、variant、background（`{kind:'procedural', seed, palette, style}` 或 `{kind:'url', url}`；live 模式由後端回傳 url）、spec、score、passed、checks[]
- `HistoryEntry`：選定的 render、使用者編輯後的 copy、原始 `input: JobInput`（供「以相同設定重做」）、favorite、writtenToRag
- `ReviewCheck`：id、name、kind（rule／vlm）、rule、value、status（pass／warn／fail）、target（bbox id 或 canvas）、ragRef

**WebSocket 事件**（mock 與 live 共用）

| 事件 | 內容 |
|---|---|
| `job.accepted` | jobId |
| `job.status` | stage（parsing／retrieving／prompting／rendering／composing／reviewing／rewriting／saving／done／needs_review）、round |
| `brief.parsed` | parsedBrief |
| `rag.retrieved` | query、hits（vectorScore） |
| `rag.reranked` | hits（加上 rerankScore，重新排序） |
| `prompt.generated` | round、templateId、spec |
| `comfy.queued` | round、promptId、injection |
| `render.progress` | round、node（cutout／generate／relight／upscale）、step、maxStep |
| `render.completed` | round、renders[] |
| `review.check` | round、renderId、check |
| `review.completed` | round、renderId、score、passed |
| `rewrite.started` | round、reasons[]、fixes[]、requery |
| `job.completed` | jobId、bestRenderIds（每個模板一張） |
| `job.needs_review` | jobId、reason |
| `log` | source、level、message |

## 8. Mock 行為

- **劇本**：預設「第一輪全部未通過 → Query Rewriting（重新檢索合規用語）→ 第二輪通過」。第一輪的問題：主色偏差（ΔE 超標）、文案含禁用詞、Logo 淨空區不足、缺效果註記。第二輪各候選分數不同，部分附「文字貼近商品」之類的警告，讓挑圖有意義
- **重試單位**：以模板為單位，某模板的候選全部未通過才重試該模板
- **時間軸（1× 速度）**：請求與需求拆解約 1.1 秒、RAG 約 1.2 秒，每輪（Prompt、ComfyUI、排版、審查）約 5.5 秒，改寫約 0.8 秒，寫入約 0.4 秒；含一次重試共約 15 秒
- **Demo 控制台**：在畫面角落開關，可調播放速度（1×／2×／4×）、強制首輪失敗、強制全部失敗（展示「需人工審核」）
- **商品照來源**：內建示意圖；`/products` 上傳（存 IndexedDB）；`assets/products/` 資料夾（開發模式由 `app/api/local-products` 讀取，檔名當商品名稱）
- **背景圖**：依品牌色、模板比例、seed 程序化產生 SVG，商品照合成其上，再由排版引擎畫文字

## 9. 真實邏輯（會沿用到第二階段）

- **排版引擎**：依模板 layoutPreset 與文案算出 BBox，字級自動縮放以免溢出；預覽與匯出使用同一套 Canvas 繪製
- **規則型審查**：禁用詞比對（品牌詞庫）、ΔE2000 色差、BBox 重疊與 Logo 淨空區計算
- 這些邏輯寫成純函式，第二階段可直接照搬到 Python 後端，或由前端預檢重用

## 10. 測試

- **Vitest**：規則型審查（禁用詞、ΔE、重疊）、排版引擎（BBox 不超出畫布、字級縮放）、Prompt 組裝（改寫後鎖定品牌色、加入負面提示詞）、Mock 劇本（事件順序正確；用 fake timers 驗證 1× 總時長約 15 秒）
- **Playwright**：主流程 E2E。輸入一句話 → 生成 → 第一輪失敗並重試 → 選圖 → 修改價格 → 匯出 zip（檢查下載事件）；Agent 透視顯示重試 diff

## 11. 待決事項（不阻擋本階段）

- 使用者電腦的 GPU 規格：決定第二階段 ComfyUI 在本機或雲端執行
- 模型授權：SDXL／Flux 與社群微調模型商用前需逐一確認
- 正式品牌 CI 資料：之後由使用者提供，取代示範品牌
