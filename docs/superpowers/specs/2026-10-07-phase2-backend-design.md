# 虛實整合 GenAI Agent：第二階段（後端與真實串接）設計規格

- 日期：2026-10-07
- 狀態：待使用者審閱
- 前一階段：`2026-10-05-genai-poster-agent-frontend-design.md`（第一階段前端，Plan 1–3 已完成）

## 1. 目標

把第一階段在瀏覽器內模擬的流程（`MockApiClient`）換成真實後端：

1. **每天使用的商品圖工具**：在筆電上用自己的品牌與真實商品照，一句話產出多通路海報。
2. **展示作品**：維持完整技術棧，每項技術都在流程中負責真正的工作，不為了簡化而刪減。

| 技術 | 第二階段的工作 |
|---|---|
| FastAPI＋WebSocket | REST API、任務事件即時推送與斷線補送 |
| SAQ＋Redis | 任務佇列（生圖任務一次一個）、事件推送 |
| PostgreSQL | 品牌、商品、任務、事件、用量、歷史紀錄 |
| Chroma＋BGE-M3＋bge-reranker-v2-m3 | 品牌規範與歷史案例的檢索、重新排序 |
| Gemini API | 需求拆解、文案／版面／提示詞、Query Rewriting、VLM 審查 |
| ONNX Runtime＋BiRefNet | 商品照去背（worker 執行，見 `2026-10-15-product-cutout-design.md`） |
| ComfyUI（SDXL＋ControlNet＋IP-Adapter＋IC-Light） | 背景生成、打光融合、放大 |
| composer（Node，沿用前端 TypeScript） | 伺服器端版型、海報繪製、量主色、規則審查與計分 |
| Docker Compose | 一鍵啟動（ComfyUI 除外） |
| Cloudflare Pages＋Access | 只給名單內的人觀看的作品集 Demo（mock 模式） |

## 2. 已確認的決定

| 項目 | 決定 |
|---|---|
| 運作方式 | 只在本機運作，不需要登入；所有連接埠只綁定 `127.0.0.1` |
| 目標電腦 | 筆電：RTX 3060 Laptop（6 GB VRAM）、i7-11800H、16 GB RAM。開發可在目前的桌機（GTX 1050 Ti 4 GB、64 GB RAM） |
| 生圖 | ComfyUI 在筆電上以 Windows 原生執行；後端以網址連線，可改連雲端 GPU |
| LLM／VLM | Gemini API，模型 ID 由設定指定 |
| 品牌資料 | 每個品牌一個 YAML 設定檔；CI 手冊從「品牌知識庫」頁面上傳 |
| 架構 | API 與 Worker 分離；排版與規則審查沿用前端 TypeScript |
| 作品集 Demo | 前端靜態輸出的 mock 版部署到 Cloudflare Pages，以 Access 的 email 名單限制觀看者 |

**不做（第三階段以後）**

- Unsloth 微調 Llama 3.2 Vision 與其部署（前端選項保留，live 模式不顯示）
- Ideogram 轉接器（介面保留，live 模式不顯示）
- 自訂字型檔（先只支援 Noto Sans TC、Noto Serif TC）
- 品牌編輯介面、登入與多人權限
- 對外公開的後端

**事前準備**

| 項目 | 需要的時間點 |
|---|---|
| Docker Desktop（WSL2） | Plan 4 |
| Google AI Studio API key | Plan 6 |
| 筆電上安裝 ComfyUI | Plan 7 |
| Cloudflare 帳號 | Plan 8 |

## 3. 架構

```
瀏覽器 ── 127.0.0.1:3000 ── web（nginx：前端靜態檔；/api、/ws、/files 轉給 api）
                                │
                              api（FastAPI）── postgres
                                │            └ data/（商品照、去背圖、生成圖、審查用海報）
                                │ SAQ 佇列＋事件推送
                              redis
                                │
                              worker（SAQ）
                                ├─ chroma＋BGE-M3／Reranker（ONNX int8，CPU）
                                ├─ composer（Node：版型、繪製、量主色、規則審查、模擬邏輯）
                                ├─ Gemini API
                                └─ ComfyUI（Windows 原生，host.docker.internal:8188，可改雲端）
```

### 3.1 服務

| 服務 | 執行位置 | 職責 |
|---|---|---|
| web | Docker（nginx） | 提供 live 版前端靜態檔；反向代理 `/api`、`/ws`、`/files` 到 api |
| api | Docker（FastAPI） | REST、WebSocket、檔案讀取；不載入任何模型 |
| worker | Docker（SAQ） | 任務流程、文件上傳、去背、歷史回寫；持有外部服務的轉接器 |
| postgres | Docker | 資料 |
| redis | Docker | SAQ 佇列、事件推送 |
| chroma | Docker | 向量庫 |
| composer | Docker（Node） | 見 5.6 |
| ComfyUI | 筆電 Windows 原生 | 生圖 |
| Gemini | 雲端 API | LLM 與 VLM |

### 3.2 外部服務的轉接器

worker 只依賴介面；每個介面都有真實版與模擬版，以環境變數切換。模擬版的行為與第一階段的 mock 劇本相同（預設首輪失敗、重試後通過），用於開發、測試，以及沒有 GPU 或 API key 時的展示。

| 介面 | 真實版 | 模擬版 |
|---|---|---|
| `LlmAgent`（拆解、Prompt、Query Rewriting） | Gemini | composer `/sim/*`：沿用 mock 的文案、失誤與修正邏輯 |
| `VisionReviewer` | Gemini | composer `/sim/review`：沿用 mock 的 VLM 檢查 |
| `Retriever` | Chroma＋BGE | 依 mock 的固定召回順序與分數，從品牌切塊產生結果（Python 實作） |
| `ImageEngine` | ComfyUI | 程序化背景（`Render.background.kind = 'procedural'`） |

### 3.3 目錄

```
GenAI Agent/
├─ backend/             Python（uv）：api 與 worker 共用
│  ├─ app/api/          REST、WebSocket、檔案
│  ├─ app/worker/       SAQ 任務：流程、文件上傳、去背、回寫
│  ├─ app/pipeline/     任務流程（階段、事件、取消）
│  ├─ app/adapters/     gemini、rag、comfyui、composer（各自含模擬版）
│  ├─ app/db/           SQLAlchemy 模型、Alembic migration
│  ├─ app/contract.py   Pydantic 模型（對應 web/src/types/contract.ts）
│  └─ tests/
├─ web/                 Next.js（靜態輸出）
│  └─ composer/         Node 服務，直接 import web/src/lib
├─ brands/              品牌設定檔：selune.yaml、misty-isle.yaml、_template.yaml、assets/
├─ comfyui/             workflows/、參數對照表、自訂節點清單、models.md（含授權）、安裝說明
├─ contracts/fixtures/  由 TypeScript 產生的 golden fixtures（pytest 使用）
├─ data/                執行時資料（.gitignore）
├─ docker-compose.yml
└─ .env.example         Gemini API key、COMFYUI_URL、各轉接器的真實／模擬切換
```

### 3.4 筆電記憶體（16 GB）

| 項目 | 估計 |
|---|---|
| Windows＋瀏覽器 | 約 4 GB |
| Docker（7 個容器＋WSL2） | 約 3–4 GB（不含去背）；用 `birefnet-general` 去背時，記憶體上限（`.wslconfig`）要設到約 10 GB 以上；16 GB 的筆電請改用 `birefnet-general-lite`（較小也較快，本機實測峰值約 5.75 GB，Docker 內未實測），或接受較大的上限 |
| ComfyUI（SDXL 部分卸載到系統記憶體） | 約 6–8 GB |
| 去背（BiRefNet，worker） | 平常約 2 GB，去背時約 7.6 GiB（Docker 實測） |

合計偏緊。BGE 模型使用 ONNX int8，用到才載入；建議筆電升級到 32 GB。實際數字在 Plan 7 實測並記錄。

## 4. 任務流程與事件

### 4.1 生命週期

1. `POST /api/jobs`：驗證後寫入 `jobs`，送出 `job.accepted` 與 `job.status queued`，放入 `jobs` 佇列。
2. worker 有三個佇列，在同一個行程內共用已載入的模型：
   - `jobs`：生圖任務，同時只執行 1 個（只有一張 GPU）。
   - `tasks`：文件上傳、歷史回寫，同時最多 2 個，不必等生圖任務。
   - `cutouts`：商品照去背（BiRefNet），同時只執行 1 個（推論時記憶體用量大），大量新增商品時不會擋住文件上傳。
3. 階段與事件順序與 mock 劇本相同：
   - `parsing` → `retrieving`（`rag.retrieved`、`rag.reranked`）
   - 每一輪：`prompting`（每個模板一則 `prompt.generated`）→ `rendering`（每個 variant 一則 `comfy.queued`、`render.progress`、`render.completed`）→ `composing` → `reviewing`（每張候選 10 則 `review.check`＋`review.completed`）
   - 有模板的候選全部未通過，且還有重試次數：`rewriting`（`rewrite.started`，需要時 `rag.retrieved`）→ 下一輪
   - `saving` → `job.completed`＋`done`；或 `job.needs_review`＋`needs_review`
4. 重試以模板為單位；最多重試次數由 `JobInput.maxRetries` 指定。
5. 每個 variant 是一個 ComfyUI prompt；seed 為基準 seed 加上 variant 編號。

### 4.2 事件保存與推送

- **寫入**：每則事件在同一個交易中鎖定任務列、取得下一個 `seq`、寫入 `job_events`，並更新任務摘要（stage、round、finished、best_render_ids）；commit 後發布到 Redis 頻道 `job:{id}`。
- **WebSocket `/ws/jobs/{id}?after={seq}`**：先訂閱 Redis，再從資料庫補送 `seq` 大於 `after` 的事件，接著轉送即時事件，依 `seq` 去除重複。任務結束且事件送完後由伺服器關閉連線。
- **前端**：斷線後以最後收到的 `seq` 重新連線（間隔 1 秒起，最長 10 秒）。重新整理頁面後也能接續執行中的任務。
- `ts` 一律為 UTC 的 ISO 8601。

### 4.3 取消

- **排隊中**：以 `stage = 'queued'` 為條件原子更新為取消，送出 `job.status cancelled`。
- **執行中**：設定 `cancel_requested`。worker 在每個步驟之間與等待 ComfyUI 時（每 0.5 秒）檢查；取消時中斷正在執行的、屬於此任務的 ComfyUI prompt，刪除此任務排隊中的 prompt，再送出 `job.status cancelled`。

### 4.4 錯誤處理

| 情況 | 處理 |
|---|---|
| Gemini 429、5xx、逾時（60 秒） | 指數退避重試 3 次；結構化輸出解析失敗時帶著錯誤再試 1 次；仍失敗則任務失敗 |
| ComfyUI 連不上 | 進入 `rendering` 前檢查 `/system_stats`，失敗則任務失敗，原因含網址 |
| ComfyUI 執行錯誤 | 該 variant 重試 1 次；仍失敗則任務失敗，原因含節點錯誤訊息 |
| ComfyUI 逾時 | 每個 prompt 預設 10 分鐘，逾時則任務失敗 |
| worker 重新啟動 | 啟動時把執行中的任務標記失敗（「worker 重新啟動，任務中斷」），不自動重跑 |
| 其他例外 | 任務失敗，原因為例外訊息摘要 |

任務失敗時送出 `job.failed { reason }` 與 `job.status failed`。所有錯誤同時送出 `log` 事件（level `error`），Agent 透視看得到。

## 5. 各階段的實作

### 5.1 需求拆解

- `POST /api/briefs/parse`（同步）：Gemini 以結構化輸出產生 `ParsedBrief`，包含新增的 `period`（活動期間，需求中有提到才填）。
- 任務的 `parsing` 階段沿用 `JobInput.parsedBrief`（使用者已在表單確認），不再呼叫 LLM。Agent 透視只記錄實際發生的呼叫。

### 5.2 RAG

- **collection**：每個品牌一個 `{brandId}_ci`；metadata 包含 brandId、tag、source、section、origin（`config`、`upload`、`history`、`alt`）。
- **切塊來源**：
  - 品牌設定檔的規範與歷史案例（origin `config`）
  - 由替代用語表自動產生的「合規替代用語」切塊（origin `alt`，只在 Query Rewriting 時檢索，對應第一階段的 `-alt` 切塊）
  - 上傳的 CI 手冊（origin `upload`）
  - 選定海報的回寫（origin `history`）
- **模型**：BGE-M3 dense 向量（1024 維）、bge-reranker-v2-m3；兩者皆以 ONNX int8 在 CPU 執行，用到才載入。
- **檢索**：查詢為「品牌名｜商品名｜一句話需求｜賣點」→ 向量召回 8 筆（排除 `alt`）→ Rerank。`rag.retrieved` 送出 8 筆向量分數，`rag.reranked` 送出依 Rerank 分數排序的 8 筆；Prompt 使用前 5 筆。
- **上傳手冊**：切塊（`web/src/lib/rag/chunk.ts` 移植到 Python）→ 逐塊向量化（`ingest.embedded` 的 preview 為真實向量的前幾維）→ 寫入 Chroma（同一 source 先刪後寫）→ `ingest.stored`。API 以 NDJSON 串流回傳 `IngestEvent`。
- **歷史回寫**：`selectRender` 建立歷史紀錄後，`tasks` 佇列把模板、文案、Prompt 摘要與分數寫成 tag `history` 的切塊；完成後 `writtenToRag` 設為 true。API 最多等候 10 秒，逾時則先回傳 false，回寫在背景繼續。

### 5.3 Prompt 構建（Gemini，每個模板呼叫一次）

- **輸入**：品牌設定（色票、視覺風格、禁用詞、替代用語、效果宣稱詞、語氣範例）、商品、`ParsedBrief`、模板、預設版型（composer `/layout`）、Rerank 後前 5 筆切塊；重試時再加上修正項目、重新檢索的結果與上一輪的 spec。
- **結構化輸出**：文案（標題兩行、副標、最多 3 個賣點、徽章、價格標籤）、每個版面元素的 BBox、正向提示詞、負向提示詞。
- **程式護欄**（不交給 LLM 決定）：
  - 所有文案套用品牌的替代用語
  - `palette` 鎖定為品牌 CI
  - 價格與商品名稱取自商品資料
  - 註記：含效果宣稱時，由品牌註記、活動期間與固定說明組成
  - BBox 限制在畫布內並符合圖層順序；不合法則退回預設版型
  - 負向提示詞一定包含基本負向詞
  - `injection` 由 workflow 參數對照表產生（seed、尺寸、提示詞、商品圖、ControlNet 強度、IP-Adapter 權重、打光方向、版面座標）
- `ragRefs` 為實際放進 Prompt 的切塊 id。

### 5.4 Query Rewriting（Gemini）

- **觸發**：某個模板在該輪的候選全部未通過審查。
- Gemini 讀取未通過的檢查項、引用的規範與上一輪 spec，為每個未通過項產生一則修正（`Fix`），並判斷是否需要重新檢索；需要時改寫檢索查詢，檢索 origin `alt` 與 tag `law` 的切塊。
- **事件**：`job.status rewriting` → `rewrite.started`（reasons、fixes、requery）→ 重新檢索時 `rag.retrieved` → 下一輪 `prompting`。

### 5.5 生圖（ComfyUI）

- **workflow**（`comfyui/workflows/`，API 格式）：
  - 去背不在 ComfyUI 中執行：新增商品時由 worker 以 ONNX Runtime 執行 BiRefNet，結果存在 `data/products/{id}/`（見 `2026-10-15-product-cutout-design.md`）。下面的 workflow 直接讀取 `cutout.url` 的透明 PNG。
  - `product_scene_v1`：
    1. 依版面的商品 BBox，把去背商品放到畫布上（底圖＋遮罩）
    2. SDXL 生成背景：ControlNet 依商品輪廓維持構圖，IP-Adapter 參考品牌風格圖或歷史案例
    3. IC-Light 讓商品光線融入背景
    4. 放大到模板的輸出尺寸

    商品像素來自真實照片，AI 只產生背景與光影。
- **參數對照表**（`product_scene_v1.params.json`）：label 對應 nodeId 與 input。`PromptSpec.injection` 就是實際送出的參數。
- **進度**：ComfyUI WebSocket 的 `executing`、`progress` 依對照表的節點分組換成 `render.progress`（cutout、generate、relight、upscale）。
- **輸出**：存到 `data/jobs/{jobId}/`；`Render.background` 為 `{ kind: 'url', url, includesProduct: true }`。
- **模型組合**：由 Plan 7 開頭在筆電上實測決定。驗收標準：
  - 每張候選不超過 60 秒（約 100 萬像素生成加放大，不含排隊）
  - 6 GB VRAM 不會記憶體不足
  - 商品外形與標籤文字不變形

  候選有 SDXL 加 Lightning 類加速模型、輕量 ControlNet、IP-Adapter、IC-Light（SD1.5）、4x 放大模型。每個模型的授權記錄在 `comfyui/models.md`，商用前逐一確認。
- **雲端**：`COMFYUI_URL`（加上選填的驗證標頭）指向安裝了相同自訂節點與模型的雲端 ComfyUI，不必修改程式。

### 5.6 composer（伺服器端排版與規則審查）

| 端點 | 用途 |
|---|---|
| `POST /layout` | 模板的預設版型 BBox |
| `POST /render` | 把文字疊到背景上，輸出審查用海報 PNG，並回傳偵測到的主色 |
| `POST /review` | 7 項規則檢查（`runRuleChecks`）加上 3 項 VLM 結果，回傳 10 項檢查與分數（`scoreChecks`，live 模式不加隨機抖動） |
| `POST /sim/*` | 模擬模式使用：沿用 mock 的 Prompt、失誤、審查與修正邏輯 |

- 直接 import `web/src/lib` 的 compose（scene、paint、art、layout）與 review（rules、color）。瀏覽器專用的 `render.ts` 由 composer 的 Node 版本（@napi-rs/canvas）取代。
- **新增純函式**（以 Vitest 測試，前端也可以使用）：
  - `measurePrimary`：排除商品與文字區塊，對飽和像素分群，取面積最大的顏色，再與品牌主色計算 ΔE2000。飽和度門檻與分群數在 Plan 6 以測試圖調整。
  - `ocrDiffs`：每個文字元素在 VLM 轉錄結果中找最接近的片段，累計差異字數。
- **字型**：容器內放完整的 Noto Sans TC、Noto Serif TC（前端的 fontsource 套件是分段子集，不適合伺服器端）。
- **已實測**：@napi-rs/canvas 1.0.10 支援 `ctx.filter`（blur）、`multiply` 與中文字型；SVG 要先轉成 Buffer 才能載入。

### 5.7 VLM 審查（Gemini）

- **輸入**：composer 輸出的海報（長邊縮到約 1024 px）、品牌禁用詞與效果宣稱詞、預期文案。
- **結構化輸出**：`vlm_exaggeration`、`vlm_occlusion`（含對應的版面元素）、`vlm_quality` 的狀態與說明，以及畫面上所有文字的轉錄（供 `ocrDiffs` 使用）。
- 同一輪的 VLM 呼叫可並行（預設上限 4），事件依候選順序送出。

### 5.8 用量與成本

- 每次 Gemini 呼叫記錄 input／output tokens（寫入 `job_usage`，並以 `log` 事件顯示）；ComfyUI 記錄 GPU 秒數。
- 儀表板的每張成本改為實際用量乘以設定中的單價：Gemini 依模型計價；本機 GPU 計 0，雲端 GPU 依秒數計價。

## 6. 資料

### 6.1 PostgreSQL（SQLAlchemy＋Alembic）

| 表 | 主要欄位 |
|---|---|
| `brands` | id、name、config（jsonb）、ci_version、source_hash、updated_at |
| `brand_chunks` | id、brand_id、source、section、tag、text、origin、created_at |
| `products` | id、brand_id、name、features、price、photo、cutout、created_at |
| `jobs` | id、brand_id、input、created_at、stage、round、finished、best_render_ids、cancel_requested、failure_reason |
| `job_events` | job_id、seq、ts、type、payload；主鍵為 (job_id, seq) |
| `job_usage` | job_id、provider、model、kind、input_tokens、output_tokens、seconds、cost_usd |
| `history` | id、job_id、render_id、brand_id、product_id、input、template_id、render、copy、selected_at、favorite、written_to_rag |

- 候選圖（`Render`）不另外建表，從事件組回（`render.completed` 加上審查事件）。
- 儀表板統計：`web/src/lib/stats/dashboard.ts` 移植成 Python。

### 6.2 檔案

- `data/products/{id}/`：去背圖（見 `2026-10-15-product-cutout-design.md`）；`data/jobs/{jobId}/`：生成圖、審查用海報。
- api 以 `/files/...` 提供唯讀存取，並驗證路徑不超出 `data/`。
- `assets/products/` 以唯讀掛載；本機資料夾的列出與匯入改由後端處理（複製到 `data/products/`），Docker 的正式版也能使用。

### 6.3 品牌設定檔（`brands/*.yaml`）

- 欄位對應 `Brand`：id、name、category、ciVersion、palette、fonts、visualStyle、defaultTone、rules、bannedWords、replacements、claimWords、disclaimerPhrase、copyPresets、guidelines（section、tag、text）、caseStudies，以及選填的 logo（圖檔）與 styleImages（IP-Adapter 參考圖，只有後端使用）。
- api 啟動時以 Pydantic 驗證後匯入；格式錯誤的品牌略過，並在系統狀態顯示原因。內容的雜湊值改變時，更新 `brand_chunks` 與 Chroma 中 origin 為 `config`、`alt` 的切塊。
- 提供 `selune.yaml`、`misty-isle.yaml`（由 TypeScript 示範資料轉出）與有註解的 `_template.yaml`。

## 7. 合約變更

`web/src/types/contract.ts` 與 `backend/app/contract.py` 同步修改：

1. `JobStage` 新增 `queued`、`failed`；`JobEvent` 新增 `job.failed { jobId, reason }`；`JobOutcome` 新增 `failed`；`JobSummary.finished` 包含失敗。儀表板統計不計失敗的任務（與取消相同）。
2. `ParsedBrief` 新增 `period: string | null`；移除寫死的 `CAMPAIGN_PERIOD`。
3. `RenderBackground` 的 url 型別改為 `{ kind: 'url'; url: string; includesProduct: boolean }`。
4. `Brand` 新增 `logo: { url: string } | null`。
5. `ApiClient` 新增：
   - `getOptions()`：可用的 LLM、VLM、生圖引擎與顯示名稱
   - `getSystemStatus()`：db、redis、chroma、composer、comfyui、gemini 的狀態
   - `listLocalPhotos()`、`importLocalPhoto()`：取代元件直接呼叫 Next 路由

   `MockApiClient` 一併實作。

## 8. API

| 方法 | 路徑 | 對應的 `ApiClient` 方法 |
|---|---|---|
| GET | `/api/options` | `getOptions` |
| GET | `/api/status` | `getSystemStatus` |
| GET | `/api/brands` | `listBrands` |
| POST | `/api/brands/{id}/documents` | `ingestBrandDocument`（NDJSON 串流） |
| GET | `/api/templates` | `listTemplates` |
| GET | `/api/products?brandId=` | `listProducts` |
| POST、PUT | `/api/products`、`/api/products/{id}` | `saveProduct` |
| DELETE | `/api/products/{id}` | `deleteProduct` |
| POST | `/api/products/photos` | `uploadProductPhoto` |
| POST | `/api/products/{id}/cutout` | `requestCutout` |
| GET | `/api/local-photos` | `listLocalPhotos` |
| POST | `/api/local-photos/{name}/import` | `importLocalPhoto` |
| POST | `/api/briefs/parse` | `parseBrief` |
| POST | `/api/jobs` | `createJob` |
| GET | `/api/jobs`、`/api/jobs/{id}` | `listJobs`、`getJob` |
| POST | `/api/jobs/{id}/cancel` | `cancelJob` |
| WS | `/ws/jobs/{id}?after={seq}` | `subscribe` |
| POST | `/api/jobs/{id}/select` | `selectRender` |
| GET | `/api/history?brandId=` | `listHistory` |
| PATCH | `/api/history/{id}` | `setFavorite` |
| GET | `/api/stats?brandId=` | `getDashboardStats` |
| GET | `/files/{path}` | 圖片 |

- 錯誤回應格式為 `{ error: { code, message } }`，message 為繁體中文。
- FastAPI 自動產生的 OpenAPI 文件（`/docs`）一併作為作品集展示。

## 9. 前端調整

- **`HttpApiClient`**（`web/src/lib/api/http/`）：REST 使用 fetch；`subscribe` 使用 WebSocket，斷線後以最後的 `seq` 重新連線；`connection` 頻道反映連線狀態；`ingestBrandDocument` 讀取 NDJSON 串流。
- `NEXT_PUBLIC_API_MODE=live` 時使用 `HttpApiClient`。API 網址預設同源（經 nginx 轉送）；開發時以 `NEXT_PUBLIC_API_URL` 指向 `http://localhost:8000`，api 對 `http://localhost:3000` 開放 CORS。
- **live 模式**：
  - 隱藏 Demo 控制台與「產生示範任務」
  - 右上角的連線狀態可展開系統狀態（各服務是否正常）
  - 模型與引擎選項來自 `getOptions()`
  - 每個模板預設 2 張候選
  - 失敗狀態顯示在新任務、Agent 透視、批次佇列與儀表板的最近任務
- **繪製**：`includesProduct` 為 true 時跳過商品圖層；`Brand.logo` 有圖時繪製圖檔，沒有時沿用現在的向量標誌與文字。
- **商品照**：上傳到後端（`photo.url` 為 `/files/...`）；本機資料夾改用 `listLocalPhotos()`、`importLocalPhoto()`，刪除 Next 的 `/api/local-products`。mock 模式改為提示「只有 live 模式可以讀取本機資料夾」。
- **靜態輸出**（`output: 'export'`）：live 版由 nginx 提供；mock 版部署到 Cloudflare Pages。Playwright 的 webServer 改為建置後以靜態伺服器提供 `out/`。

## 10. 作品集 Demo（Cloudflare）

- mock 版靜態輸出部署到 Cloudflare Pages（Git 整合或 wrangler）。
- Cloudflare Zero Trust（免費方案最多 50 人）建立 Access 應用程式，保護 production 與 preview 的 `pages.dev` 網址；政策只允許名單內的 email，以寄到信箱的一次性驗證碼登入。名單可隨時增減，並可查看存取紀錄。
- 部署與名單設定由使用者以自己的 Cloudflare 帳號操作；Plan 8 提供逐步說明。

## 11. 測試

- **Python（pytest）**：
  - 任務流程：以模擬轉接器與假時鐘驗證事件順序與 mock 劇本一致，涵蓋首輪失敗後重試通過、全部失敗轉人工審核、取消、失敗
  - 事件 `seq` 的交易處理；WebSocket 從指定 `seq` 補送
  - 品牌設定檔驗證、程式護欄
  - Gemini 與 ComfyUI 的連線程式：以錄製的回應模擬 HTTP 與 WebSocket
  - 資料庫與佇列：以測試用的 compose profile 啟動 postgres、redis、chroma
- **Python 與 TypeScript 的一致性**：TypeScript 產生 golden fixtures（事件、`PromptSpec`、`Render`、切塊結果、儀表板統計）；pytest 以 Pydantic 解析並比對 Python 移植的輸出。
- **TypeScript（Vitest）**：既有測試全部保留；新增 `measurePrimary`、`ocrDiffs`、`includesProduct` 與 Logo 的繪製邏輯、`HttpApiClient`（以模擬的 fetch 與 WebSocket 測試重新連線與依 `seq` 去除重複）、composer 的各個端點。
- **E2E（Playwright）**：
  - mock 模式：既有測試照跑
  - live 模式：以 docker compose 啟動整套服務（外部服務用模擬版），測主流程、重新整理後接續執行中的任務、取消、品牌文件上傳
- **真實整合測試**：`pytest -m live` 手動觸發，呼叫真的 Gemini 與 ComfyUI，不放在一般測試中。

## 12. 驗收（第二階段完成的標準）

1. 在筆電上 `docker compose up -d` 並開啟 ComfyUI 後，用自己的品牌設定檔與真實商品照，以一句話需求產出海報；Agent 透視顯示的 RAG 分數、Gemini 產生的 Prompt、ComfyUI 參數與進度、VLM 審查結果都是真實資料。
2. 每張候選不超過 60 秒（不含排隊），執行過程中筆電不會記憶體不足。
3. 重新整理或斷線後可以接續；取消會生效；ComfyUI 沒有開啟時顯示明確的錯誤。
4. 作品集 Demo 在 Cloudflare 上線，只有名單內的 email 能觀看。
5. 全部測試通過。

## 13. 實作計畫

依序進行；每份計畫完成後，系統都能完整運作。與第一階段相同，前一份完成後才撰寫下一份。

| 計畫 | 內容 | 完成時 |
|---|---|---|
| Plan 4：後端骨架與即時串流 | 目錄與 Docker Compose、PostgreSQL 與 Alembic、品牌 YAML（示範品牌轉檔與範本）、全部 REST 端點、WebSocket 補送、SAQ worker、composer 的 `/layout` 與 `/sim/*`、所有轉接器的模擬版、合約變更、`HttpApiClient` 與 live 模式調整、靜態輸出與 nginx、golden fixtures 機制 | live 模式以模擬資料跑完整流程 |
| Plan 5：RAG | Chroma、BGE-M3 與 Reranker、切塊移植、文件上傳串流、檢索與 Rerank、Query Rewriting 的重新檢索、歷史回寫、儀表板統計移植與實際用量成本 | 檢索與知識庫是真的 |
| Plan 6：Gemini Agent、伺服器端排版與 VLM 審查 | composer 的 `/render`、`/review`、`measurePrimary`、`ocrDiffs` 與字型；需求拆解、Prompt 構建（結構化輸出與程式護欄）、Query Rewriting、VLM 審查、用量紀錄 | 文字與審查是真的，圖仍是程序化背景 |
| Plan 7：ComfyUI 生圖 | 筆電實測與模型組合、workflow 與參數對照表、ComfyUI 連線程式（上傳、進度、輸出、取消）、讀取已去背的商品圖、`includesProduct` 繪製、雲端切換、安裝與模型授權文件 | 全部流程都是真的 |
| Plan 8：作品集 Demo | Cloudflare Pages 部署、Access 名單設定步驟、README 架構圖與操作說明、展示影片腳本 | 名單內的人可以觀看 Demo |

## 14. 待決事項（不阻擋開始）

- 筆電是否升級到 32 GB 記憶體（影響 SDXL 能同時載入的元件與速度）
- 實際使用的 Gemini 模型 ID 與單價：實作時以 Google AI Studio 當時提供的為準
- SDXL 等模型的商用授權：Plan 7 逐一確認
- 自己品牌的設定檔內容與 Logo 圖檔：Plan 4 提供範本後由使用者填寫
