# Plan 7：ComfyUI 生圖 設計規格

- 日期：2026-10-23
- 狀態：設計決定已由使用者確認（§3、§11），文件已審閱同意（2026-10-23）
- 相關：
  - `2026-10-07-phase2-backend-design.md`（§3.2、§3.4、§4.4、§5.5、§5.8、§12、§13、§14）
  - `2026-10-15-product-cutout-design.md`（去背圖 `cutout.url`）
  - `2026-10-22-plan6a-server-compose-design.md`（`measurePrimary`、背景色系檢查延後到 Plan 7）
  - `2026-10-23-plan6b-gemini-vlm-design.md`（`scene` 與 `negativeExtra`、`planFixes`、`job_usage`）

## 1. 目標

6B 之後，文字、檢索與審查都是真的，只有背景還是程式畫的程序化背景（`SimImageEngine`）：
- 背景與商品沒有互動（沒有桌面、倒影、接觸陰影），每個品牌只有一種固定的風格；
- Gemini 寫的 `scene`（場景、道具、光線）沒有被使用；
- `PromptSpec.injection` 的 ComfyUI 參數（`web/src/lib/agent/prompt.ts` 的 `buildInjection`）是示意值，節點編號沒有對應任何 workflow；
- 品牌指南的色彩規範（例如 SÉLUNE「禁止使用高飽和桃紅與螢光色系」）只檢查文字的主色，不檢查背景。

本規格要完成四件事：
1. 在筆電（RTX 3060 Laptop，6 GB VRAM，16 GB 記憶體）以 Windows 原生的 ComfyUI 生成背景：AI 依商品的位置與輪廓生成場景與光影，**商品像素一律使用原始去背圖**，由 composer 疊在生成的背景上。
2. ComfyUI 連線程式：上傳、送出、進度、下載輸出、取消、錯誤處理。
3. 16 GB 記憶體下可以穩定執行：生圖與去背不同時佔用大量記憶體。
4. 新增第 11 項檢查「背景色系」：生成背景的顏色要在品牌色系內，且不可是高飽和的螢光色。

模擬模式（測試、live E2E、作品集 Demo）維持不變。只在本機執行：不做雲端 GPU 的計價與驗證。

## 2. 實作開頭的實驗（需要 ComfyUI 與模型）

撰寫本規格時，筆電還沒有安裝 ComfyUI。以下項目由實作計畫的第一個 Task 實測，結果記錄在 §12。標示「實驗決定」的數值依結果調整。

| 項目 | 方法 | 通過標準 | 不通過時 |
|---|---|---|---|
| 生成方式 | §4.3 的 A（商品周圍重繪）與 B（文生圖＋ControlNet）各跑 3 個品牌 × 5 個模板 | 背景與商品的透視、光線、接觸面合理；文字區塊乾淨（人工評分，加上 VLM `vlm_quality`） | 調整參數；兩者都不行時改用較少的模板先上線 |
| 時間 | 每張候選從送出到下載完成的秒數（不含排隊；第一次載入模型另外記錄） | 每張 ≤ 60 秒 | 減少步數、降低生成解析度、改用較快的放大方式 |
| VRAM | ComfyUI 的 `/system_stats` 與工作管理員 | 6 GB 不會記憶體不足（OOM） | ComfyUI 改用 `--lowvram`；模型改用 fp8 或較小的 ControlNet |
| 系統記憶體 | Docker 全部服務＋ComfyUI＋瀏覽器，生圖時的尖峰；另外量生圖與去背同時執行 | 生圖時不使用分頁檔造成明顯變慢、不 OOM | 啟用 §4.7 的互斥；生圖後呼叫 `/free` |
| 商品邊緣 | 疊上原始去背圖後檢查邊緣 | 沒有明顯的光暈、殘影或第二個商品 | 調整遮罩的擴張像素（`PLATE_MASK_GROW`）；B 方式加上商品區域的重繪遮罩 |
| 背景色系 | §4.8 的量測：程序化背景、依品牌提示詞生成的背景、刻意指定螢光色或其他色系的背景 | 程序化背景 100% 通過；正確提示詞的生成背景 ≥ 90% 通過；刻意偏離的全部不通過 | 調整 §4.8 的門檻 |
| 放大 | 生成約 100 萬像素後放大到模板尺寸（最大 2048 × 1536）：Lanczos 與 ESRGAN 類模型比較 | VLM `vlm_quality` 通過、人工看不出模糊 | 改用模型放大（多一個模型與授權確認） |

## 3. 已確認的決定

| 項目 | 決定 |
|---|---|
| 商品像素 | ComfyUI 只生成背景與光影；composer 把原始去背 PNG 疊在版面的商品方框（`includesProduct: false`）。標籤文字與商品外形完全不變。不使用 IC-Light（修改第二階段規格 §5.5） |
| 模型授權 | **會商用**：只使用授權明確允許商用的模型與自訂節點。非商用（例如 CC BY-NC）或授權不明確的一律不用。每個模型的來源、版本、SHA-256 與授權條款記錄在 `comfyui/models.md` |
| 記憶體 | 以 16 GB 為準設計與驗收（不假設升級到 32 GB） |
| 執行位置 | 只在本機執行。`COMFYUI_URL` 只是連線位址（預設 `http://host.docker.internal:8188`）；不做雲端的驗證標頭、不做雲端 GPU 實測 |
| 成本 | 本機 GPU 不計費：不在 `pricing.yaml` 加 GPU 單價，`IMAGE_MODE=comfyui` 時儀表板的生圖成本為 0。每個 ComfyUI prompt 的執行秒數只記在 `log` 事件，用來驗收「每張 ≤ 60 秒」，不寫入 `job_usage` |
| 模型下載 | 只在本機下載（一次性，約 10–15 GB），由 `comfyui/setup.ps1` 下載並核對 SHA-256 |
| 背景色系檢查 | 列入 Plan 7（§4.8） |
| Ideogram | 不做。合約的 `engine: 'ideogram'` 保留，可用選項只列 `comfyui` |

## 4. 架構

### 4.1 切換與元件

新增 `IMAGE_MODE=comfyui|sim`，與 `AGENT_MODE`、`REVIEW_MODE` 各自獨立：

| `IMAGE_MODE` | `REVIEW_MODE` | 生圖 | 背景 |
|---|---|---|---|
| `comfyui`（docker compose 預設） | `composer` | `ComfyImageEngine` | 生成的背景（`UrlBackground`，`includesProduct: false`） |
| `sim` | 任何 | `SimImageEngine`（不變） | 程序化背景 |
| `comfyui` | `sim` | 設定錯誤：api 與 worker 啟動失敗並說明原因（商品底圖由 composer 產生，§4.3） | |

- `docker-compose.e2e.yml` 固定 `IMAGE_MODE=sim`；pytest 的 `Settings` 一律明確設定。
- **ComfyUI 沒有開啟**：服務照常啟動；系統狀態顯示「異常」與網址。任務進入 `rendering` 前檢查 `/system_stats`，失敗時任務失敗，原因為「ComfyUI 沒有回應（http://host.docker.internal:8188），請先啟動 ComfyUI」。不在建立任務時拒絕（ComfyUI 可能在排隊期間啟動）。
- **時間軸**：`IMAGE_MODE=comfyui` 時，生圖進度來自 ComfyUI 的 WebSocket，不再依 `RENDER_STEPS` 的時間軸等待。
- **新增檔案**：

| 檔案 | 內容 |
|---|---|
| `backend/app/adapters/comfyui.py` | `ComfyClient`：HTTP 與 WebSocket、上傳、送出、進度、下載、取消（4.5） |
| `backend/app/pipeline/comfy.py` | `ComfyImageEngine`（4.6） |
| `comfyui/workflows/product_scene_v1.json`、`product_scene_v1.params.json` | API 格式的 workflow 與參數對照表（4.3、4.4） |
| `comfyui/models.md`、`comfyui/custom_nodes.md` | 模型與自訂節點：來源、版本或 commit、SHA-256、授權 |
| `comfyui/setup.ps1`、`comfyui/README.md` | 安裝 ComfyUI（固定版本）、自訂節點與模型，核對 SHA-256；啟動參數 |
| `web/src/lib/review/background.ts` | `measureBackgroundPalette`、`bgPaletteCheck`（4.8） |
| `web/src/lib/compose/plate.ts` | `productPlate`：商品底圖與遮罩（4.3） |
| `backend/scripts/comfy_experiment.py` | §2 的實驗 |

### 4.2 ComfyUI 的安裝

- Windows 原生，使用 ComfyUI 官方的 portable 版本（內含 Python 與 PyTorch），版本固定並記錄在 `comfyui/README.md`。不放進 Docker（Docker Desktop 在 Windows 使用 GPU 需要額外設定，且會多佔記憶體）。
- `comfyui/setup.ps1`：給定 ComfyUI 的安裝資料夾，安裝 `custom_nodes.md` 列出的自訂節點（固定 commit），下載 `models.md` 列出的模型並核對 SHA-256；已存在且雜湊相同的檔案略過。不自動下載 ComfyUI 本身（使用者從官方 GitHub release 下載並解壓縮）。
- 啟動參數記錄在 `comfyui/README.md`：`--listen 127.0.0.1`（容器以 `host.docker.internal` 連線時需要的設定由實驗確認）、VRAM 模式（實驗決定）。
- **候選模型**（實驗與授權確認後，只保留實際使用且允許商用的）：

| 用途 | 候選 | 授權（實作時逐一確認原文） |
|---|---|---|
| 主模型 | SDXL base 1.0 | CreativeML Open RAIL++-M |
| 重繪（方式 A） | SDXL inpainting 0.1 | CreativeML Open RAIL++-M |
| 加速 | SDXL-Lightning 的 LoRA（4 或 8 步） | 待確認 |
| 構圖（方式 B） | SDXL 的 ControlNet（canny 或 union 類，直接用商品遮罩的輪廓，不需要深度估計模型） | 依模型而定，非商用的不用 |
| 放大 | 不用模型（Lanczos）；或 Real-ESRGAN x4plus | Real-ESRGAN：BSD-3-Clause |

  第二階段規格 §5.5 的 IP-Adapter（參考品牌風格圖）不列入：品牌設定檔目前沒有風格參考圖，少一組模型也少一份授權與記憶體。

### 4.3 workflow：`product_scene_v1`

**商品底圖（product plate）**由 composer 產生，保證生成時的商品位置與最後疊上的位置完全相同：
- `POST /plate`（composer）：輸入 `PromptSpec`（畫布尺寸與版面）、商品與去背圖（base64，與 `/render` 相同的 `images.product`）、生成解析度；輸出兩張 PNG（base64）：
  - `plate`：生成解析度的畫布，商品依 `paint` 相同的縮放與置中規則放在商品方框，其餘為中性灰；
  - `mask`：要重繪的區域（商品以外為白，商品為黑），商品邊緣向外擴張 `PLATE_MASK_GROW` 像素（實驗決定，預設 8）。
- 共用 `web/src/lib/compose/` 計算商品矩形的函式，與 `paint` 的商品圖層一致（以 Vitest 測試兩者的矩形相同）。
- **示範商品**（向量 SVG）同樣可以產生底圖。**去背還沒完成**的商品（`cutout.status` 不是 `done`）：任務照常執行，但底圖改用原照片的矩形外框，並在 Agent 透視顯示警告「商品尚未去背，背景依外框生成」（實驗確認效果；不行時改為建立任務時拒絕）。

**生成解析度**：依模板比例選 SDXL 常用的約 100 萬像素尺寸（例如 1:1 → 1024 × 1024、4:5 → 896 × 1120、9:16 → 768 × 1344、16:9 → 1344 × 768、4:3 → 1152 × 864），放大後裁切到模板尺寸（裁切方式與底圖的縮放一致，商品位置不偏移）。

**兩種生成方式**（§2 實驗後只保留一種）：
- **A：商品周圍重繪**：SDXL inpainting 讀 `plate` 與 `mask`，只重繪商品以外的區域。模型看得到商品，透視、接觸面與陰影較自然。
- **B：文生圖＋ControlNet**：以 `mask` 的輪廓作為 ControlNet 條件生成整張圖，商品區域之後被原始去背圖蓋掉。速度較快，但可能在商品位置畫出另一個商品，邊緣需要檢查。

**提示詞**：沿用 6B 的 `positivePromptOf`（模板比例、`scene`、品牌 `visualStyle`、色票、`brief.style`、留白）與 `negativePrompt`。新增固定的負面詞，避免背景出現文字、Logo、浮水印與第二個商品（實驗決定確切的字詞）。

**輸出**：worker 把生成的圖放大、裁切到模板尺寸，存為 `data/jobs/{jobId}/bg-{templateId}-r{round}-v{variant}.png`，`Render.background` 為 `{ kind: 'url', url: '/files/jobs/…', includesProduct: false }`。前端（`compose/render.ts`）與 composer（`poster.ts`）已支援 `url` 背景，商品圖層照常繪製。

**商品陰影**：`paint` 現在會在商品下方畫一個柔和的陰影。生成的背景若已有接觸陰影，兩者會重疊；是否在 `url` 背景時關閉程式陰影由實驗決定。

### 4.4 參數對照表與 `PromptSpec.injection`

- `product_scene_v1.params.json`：每個可調參數的 `label` 對應 workflow 的 `nodeId` 與 `input`，例如 `positive_prompt`、`negative_prompt`、`seed`、`steps`、`cfg`、`denoise`、`width`、`height`、`plate_image`、`mask_image`、`controlnet_strength`（B 方式）。
- `buildInjection`（`prompt.ts`）改為依對照表產生參數，移除示意的節點（`cutout_model`、`ip_adapter_style`、`ic_light`、`layout_boxes`）。對照表由 `npm run fixtures` 匯出到 `contracts/fixtures/`，pytest 確認 Python 讀到的節點與 workflow 一致。
- `PromptSpec.injection` 就是實際送出的參數（第二階段規格 §5.5）：Agent 透視顯示的值與送給 ComfyUI 的值相同。
- `seed`：基準 seed 加上 variant 編號；改寫後的下一輪換一個基準 seed。
- **Query Rewriting 的修正**：`bg_palette` 不通過時，`planFixes` 補上的修正為「背景改用品牌色系」：正面提示詞加上色票描述，負面提示詞加上偏離的色系（例如 `neon green, fluorescent colors`），沿用 6B `NEGATIVE_BY_FIX` 的機制。

### 4.5 `ComfyClient`（`backend/app/adapters/comfyui.py`）

使用 httpx（HTTP）與 `websockets`（或 httpx-ws，實作時擇一並固定版本）：

| 動作 | ComfyUI API |
|---|---|
| 檢查連線 | `GET /system_stats`（系統狀態與進入 `rendering` 前） |
| 檢查節點與模型 | `GET /object_info`：workflow 用到的節點類型都存在；模型清單包含對照表指定的檔名 |
| 上傳底圖與遮罩 | `POST /upload/image`（`overwrite=true`，檔名含 jobId，避免任務之間互相覆蓋） |
| 送出 | `POST /prompt`（帶 `client_id`），回傳 `prompt_id` |
| 進度 | WebSocket `/ws?clientId=…`：`executing`、`progress`、`execution_success`、`execution_error`、`execution_interrupted` |
| 下載輸出 | `GET /history/{prompt_id}` 取得輸出檔名，再 `GET /view` 下載 |
| 取消 | 正在執行的：`POST /interrupt`；排隊中的：`POST /queue`（`delete`） |
| 釋放記憶體 | `POST /free`（`unload_models`、`free_memory`；是否在每個任務後呼叫由實驗決定） |

- **進度**：依對照表的節點分組換成 `render.progress`（`generate`、`upscale`；`cutout` 與 `relight` 不再出現，前端的節點圖不顯示沒有用到的群組，見 4.10）。WebSocket 斷線時以 `GET /history` 輪詢補上結果。
- **錯誤**（訊息為中文，包含節點與 ComfyUI 的原始訊息）：
  - 連不上：任務失敗，原因含網址；
  - 節點或模型缺少（`/object_info` 或 `execution_error` 的 `missing`）：任務失敗，原因列出缺少的項目並指向 `comfyui/README.md`；
  - 執行錯誤（例如 CUDA OOM）：該 variant 重試 1 次（第二階段規格 §4.4）；仍失敗則任務失敗，OOM 時附上「請關閉其他使用 GPU 的程式，或以 --lowvram 啟動 ComfyUI」；
  - 逾時：每個 prompt `COMFYUI_TIMEOUT_SECONDS`（預設 600 秒，含排隊；第一次載入模型會比較久）。
- **取消**：等待期間每 0.5 秒檢查（沿用 6B 的 `run.wait`）；取消時中斷屬於本任務的 prompt 並刪除排隊中的 prompt。
- **秒數**：每個 prompt 記錄執行秒數（`execution_start` 到 `execution_success`），以 `log` 事件顯示，例如「✓ ig-post v1 生成完成（18.4 秒）」。

### 4.6 `ComfyImageEngine`（`backend/app/pipeline/comfy.py`）

實作 `ImageEngine.render_round`（介面不變）：
1. 檢查 `/system_stats`（每輪一次）。
2. 每個模板：composer `/plate` 產生底圖與遮罩，上傳到 ComfyUI。
3. 每個 variant 一個 prompt，依序送出（只有一張 GPU；ComfyUI 本身也是依序執行）。每個 prompt 送出一則 `comfy.queued`（現有事件）。
4. 等待進度、下載輸出、放大與裁切（在執行緒中執行，不擋住事件迴圈），存檔。
5. 回傳每個 `(templateId, variant)` 的 `UrlBackground`。

- 事件的種類與順序與模擬模式相同（`comfy.queued` → `render.progress` → `render.completed`），golden timelines 只適用模擬模式，不受影響。
- 重新整理或斷線後的接續沿用現有的事件補送；worker 重新啟動時，執行中的任務照現有規則處理（失敗並說明原因），不嘗試接回 ComfyUI 的 prompt。

### 4.7 記憶體（16 GB）

第二階段規格 §3.4 的估計：Windows＋瀏覽器約 4 GB、Docker 約 3–4 GB（去背時尖峰約 7.6 GiB）、RAG 模型約 1.7 GB、ComfyUI（SDXL 部分卸載）約 6–8 GB。生圖與去背同時執行時會超過 16 GB。

- **互斥**：生圖與去背以 Redis 的鎖互斥（`heavy-memory`，有逾時，worker 異常結束時會自動釋放）：
  - 任務在 `rendering` 前取得鎖；若有去背正在執行，任務送出 `log`「等待商品去背完成」後等待（可取消）；
  - 去背任務在開始前取得同一個鎖；生圖期間新上傳的商品維持 `pending`，生圖結束後自動開始。
  - 實驗確認同時執行不會 OOM 時，可以由設定關閉（`MEMORY_LOCK=false`，預設 `true`）。
- **ComfyUI 釋放記憶體**：每個任務的生圖結束後是否呼叫 `/free`（下一個任務要重新載入模型，約多 10–30 秒）由實驗決定，以設定 `COMFYUI_FREE_AFTER_JOB` 控制。
- **WSL 記憶體上限**：去背需要約 10 GB 的上限（`.wslconfig`）。上限不是預先保留，實際使用量才佔用記憶體；在互斥之下 10 GB 仍可使用。實驗量測並把建議值寫進 README。

### 4.8 背景色系檢查（`bg_palette`）

**新增第 11 項檢查**（`CheckId` 加上 `bg_palette`，名稱「背景色系」，`kind: 'rule'`，`target: 'canvas'`，`ragRef` 指向品牌的色彩規範切塊）。這是合約變更（`contract.ts`、`contract.py`、golden fixtures、mock 劇本、儀表板的檢查列表）。分數公式不變（每個 fail −14、warn −6）。

**量測**（`measureBackgroundPalette`，純函式，Vitest 測試）：
- 輸入：背景圖（composer `/render` 已經解碼的背景，疊上文字與商品之前）、商品方框、品牌色票（primary、secondary、accent、ink）。
- 只量商品方框以外的像素（方框向外擴張 2% 畫布短邊）。縮小到約 256 × 256 再計算，速度與雜訊都較穩定。
- 每個像素轉成 CIE LCh：
  - 彩度 `C* < NEUTRAL_C`（預設 12）：中性色，一律算色系內；
  - 色相與任一品牌色（彩度 ≥ `NEUTRAL_C` 者）相差 ≤ `HUE_TOL`（預設 30°），且彩度不超過該品牌色彩度加 `CHROMA_MARGIN`（預設 25）：色系內；
  - 其他：色系外。彩度過高（螢光色）也算色系外。
- 結果：色系外的面積比例，以及色系外像素中最多的顏色（用於說明）。
- `NEUTRAL_C`、`HUE_TOL`、`CHROMA_MARGIN` 與判定門檻都是**實驗決定**（§2）。

**判定**（預設，實驗決定）：色系外 ≤ 15% 通過、≤ 30% 警告、> 30% 不通過。`value` 例如「色系外 8%」「色系外 42%（主要為 #3FD27A）」；合規報告在旁邊畫出色塊（沿用 `color_delta` 的顯示方式）。

**各模式**：
- `REVIEW_MODE=composer`：`/render` 量測並回傳（與 `measuredPrimary` 相同的方式），`/review` 產生檢查。程序化背景也照常量測（§2 的校準要求程序化背景全部通過）。
- `REVIEW_MODE=sim` 與前端 mock 模式：固定為通過，`value`「（模擬）」，與現行 VLM 模擬檢查的標示一致。mock 劇本的首輪失誤不加入這一項（劇本不變）。

### 4.9 系統狀態與可用選項

- 系統狀態的 ComfyUI 一項：
  - `IMAGE_MODE=sim`：「模擬」（現行文字）；
  - 連不上：「異常」，說明含網址與「請先啟動 ComfyUI」；
  - 連得上但缺少節點或模型：「異常」，列出缺少的項目；
  - 正常：顯示 GPU 名稱、VRAM 與 ComfyUI 版本（`/system_stats`），結果快取 60 秒。
- `getOptions().engines` 維持 `['comfyui']`。

### 4.10 前端

- `compose/render.ts`、`composer/poster.ts`：已支援 `url` 背景，不需修改（以測試確認背景尺寸與畫布不同時的縮放方式一致）。
- 結果牆的 seed 顯示：`url` 背景改為從 `spec.injection` 讀 seed（現在顯示「—」）。
- 合規報告與儀表板：新增的 `bg_palette`；儀表板的生圖成本在 `IMAGE_MODE=comfyui` 時為 0，標示「本機 GPU」。
- Agent 透視的節點圖：只顯示有出現的節點群組（`generate`、`upscale`）。

### 4.11 成本

- `AGENT_MODE=gemini` 時，儀表板的每張成本已經只用 `job_usage` 的加總（`stats.job_stat` 的 `usage_cost`），本機生圖本來就不計入，不需修改。
- `AGENT_MODE=sim` 時仍依事件估算（`stats.job_cost`）：`IMAGE_MODE=comfyui` 的任務不再乘上 `comfy_image` 的估算單價（US$0.0042），生圖成本為 0；`IMAGE_MODE=sim` 維持現狀，golden 統計不變。任務摘要需要記錄生圖模式，估算時才分得出來（實作時確認摘要現有的欄位）。
- `job_usage` 不新增 ComfyUI 的資料列（修改第二階段規格 §5.8 的「ComfyUI 記錄 GPU 秒數」）。

## 5. 模擬模式（`IMAGE_MODE=sim`）

`SimImageEngine`、程序化背景、事件與 golden timelines 都不變。唯一的差異是第 11 項檢查 `bg_palette`（模擬為通過），golden fixtures 與 mock 劇本隨合約更新。

## 6. 設定

| 變數 | 預設 | 說明 |
|---|---|---|
| `IMAGE_MODE` | `comfyui`（docker compose）；`Settings` 預設 `comfyui` | `sim` 為程序化背景 |
| `COMFYUI_URL` | `http://host.docker.internal:8188` | ComfyUI 的位址 |
| `COMFYUI_TIMEOUT_SECONDS` | `600` | 每個 prompt 的逾時（含排隊與第一次載入模型） |
| `COMFYUI_FREE_AFTER_JOB` | 實驗決定 | 每個任務生圖結束後是否呼叫 `/free` |
| `MEMORY_LOCK` | `true` | 生圖與去背互斥（4.7） |

## 7. 測試

- **一般的 pytest 不連 ComfyUI**：
  - `ComfyClient`：以 respx 重播錄製的 HTTP 回應，WebSocket 以假的伺服器（本機 asyncio）重播錄製的訊息；涵蓋成功、進度轉換、連不上、缺少節點與模型、執行錯誤後重試、OOM、逾時、取消（interrupt 與刪除排隊）、WebSocket 斷線後以 history 補上。
  - `ComfyImageEngine`：假的 `ComfyClient` 與 composer；事件順序、檔名、seed、`UrlBackground`。
  - 互斥鎖：以假的 Redis 或測試用 Redis（需要 Docker 的部分列為「未在本機執行」）。
  - 設定：`IMAGE_MODE=comfyui` 加 `REVIEW_MODE=sim` 為設定錯誤。
- **TypeScript（Vitest）**：`productPlate` 的商品矩形與 `paint` 一致；`measureBackgroundPalette` 與 `bgPaletteCheck`（純色、品牌色漸層、中性色、螢光色、商品區域排除）；`buildInjection` 依對照表產生參數；composer `/plate` 與 `/render` 回傳的背景量測。
- **一致性**：對照表、`bg_palette` 的檢查格式以 golden fixtures 確認前後端一致。
- **`pytest -m live`**：需要本機 ComfyUI；每個模板生成一張，檢查尺寸、檔案與秒數。沒有 ComfyUI 時略過。
- **錄製腳本**：`scripts/record_comfy.py` 以真的 ComfyUI 錄下 HTTP 與 WebSocket 訊息，取代手寫的回應。
- **E2E**：live E2E 固定 `IMAGE_MODE=sim`，不需要 GPU。

## 8. 併入的延後項目

- **背景色系檢查**（6A §8、README）：§4.8。
- **README 的進度表**：Plan 6B 一列的「規格 §2 的實驗與 `pytest -m live` 待設定 API key 後執行」已經完成，改為「完成（生圖仍為模擬版）」。

## 9. 驗收

在筆電上 `docker compose up -d`、啟動 ComfyUI 之後：
1. 3 個品牌各建立一個任務（5 個模板、預設 variant 數），全部完成；Agent 透視的 ComfyUI 參數、進度與秒數都是真的。
2. 每張候選 ≤ 60 秒（不含排隊與第一次載入模型）。
3. 執行期間筆電不 OOM；生圖期間上傳商品時，去背會等生圖結束後才開始。
4. 商品與標籤文字與原始去背圖完全相同（逐像素比對商品方框內的不透明像素）。
5. 刻意在需求中要求螢光色背景時，`bg_palette` 不通過，下一輪改寫後通過或轉人工審核。
6. ComfyUI 沒有開啟時，任務失敗且原因明確；系統狀態顯示「異常」。
7. 取消會中斷 ComfyUI 正在執行的 prompt。
8. 全部測試通過（需要 Docker 的在有 Docker 的環境執行）。

## 10. 對第二階段規格的修改

- **§5.5**：
  - 商品不經過 IC-Light，像素來自原始去背圖，`includesProduct: false`；不使用 IP-Adapter；
  - workflow 由 composer 產生的商品底圖與遮罩驅動；
  - 雲端：只保留 `COMFYUI_URL`，不做驗證標頭。
- **§5.8**：ComfyUI 不寫入 `job_usage`；本機 GPU 成本為 0，秒數只記在 `log`。
- **§3.4**：生圖與去背互斥；實測數字寫進 §12。
- **§5.6**：composer 新增 `POST /plate`；`/render` 回傳背景色系的量測；第 11 項檢查 `bg_palette`。
- **§14**：「筆電是否升級到 32 GB」已決定為維持 16 GB；「SDXL 等模型的商用授權」由 `comfyui/models.md` 逐一記錄。

## 11. 撰寫時的其他決定（已確認）

以下是撰寫草稿時提出、會影響範圍或介面的決定，使用者已全部同意（2026-10-23）：

1. **背景色系是新的第 11 項檢查**（合約變更），而不是併入現有的「主色色差」。分開比較清楚，但「10 項檢查」的說明、合規報告與儀表板都要更新。
2. **去背還沒完成的商品**：照常生成（依外框），而不是拒絕建立任務。
3. **生圖與去背互斥**（Redis 鎖）預設開啟。
4. **不使用 IP-Adapter**：品牌設定檔沒有風格參考圖。
5. **`IMAGE_MODE` 的 docker compose 預設為 `comfyui`**：沒有啟動 ComfyUI 時任務會失敗（原因明確）。改為預設 `sim` 則開箱即可展示，但要記得切換。
6. **生圖的 variant 依序送出**，不並行（只有一張 GPU）。

## 12. 實驗結果

（實作計畫的第一個 Task 完成後填入，見 §2。）
