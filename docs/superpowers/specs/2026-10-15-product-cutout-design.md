# 商品照去背（BiRefNet）設計規格

- 日期：2026-10-15
- 狀態：待使用者審閱
- 相關：`2026-10-07-phase2-backend-design.md`（第二階段後端）。本規格把原本排在 Plan 7、由 ComfyUI 執行的去背提前，改由 worker 直接執行。

## 1. 目標

Plan 4 的去背是模擬版：
- worker 等 1.2 秒，只在商品上標記 `BiRefNet-general`，不產生圖檔。
- 海報合成時，用「色彩增值」（multiply）讓白底「消失」。

這個做法在幾種情況下都會失敗：
- 背景不是純白；
- 商品本身有白色或淺色的部分；
- 商品疊在深色背景上。

本規格要在 live 模式加上真正的去背：
- 新增商品時自動產生透明 PNG；
- 海報合成與預覽都改用這張 PNG；
- mock 模式（作品集 Demo）維持示意。

## 2. 實測結果（2026-10-15）

**測試環境**：
- 電腦：Intel i5-14500（20 執行緒）、64 GB 記憶體，CPU 執行。
- ONNX Runtime 1.31。
- 照片：使用者的「2%水楊酸身體乳」，背景是淺米綠色絨毛巾，瓶蓋是白色。
- 計時方式：每個模型跑 3 次取中位數。

| | birefnet-general-lite | birefnet-general |
|---|---|---|
| 每張時間 | 4.8 秒 | 8.8 秒 |
| 模型檔 | 224 MB | 973 MB |
| 照片左緣鄰近的另一支商品 | 留下紫色殘邊 | 正確去掉 |
| 瓶蓋底部與絨毛的交界 | 較粗糙 | 較平順 |

birefnet-general 的記憶體用量：

| | ONNX Runtime 預設 | 關閉記憶體池（`enable_cpu_mem_arena=False`、`enable_mem_pattern=False`） |
|---|---|---|
| 模型載入後 | 1.1 GB | 1.1 GB |
| 推論時峰值 | 12.6 GB | 6.5 GB |
| 推論後 | 12.6 GB（不釋放） | 1.1 GB |
| 每張時間 | 8.7 秒 | 約 10.5 秒 |

模型輸出的商品主體透明度約為 98–99.6%，不是完全不透明，所以需要修正透明度（見 4.1）。

## 3. 已確認的決定

| 項目 | 決定 |
|---|---|
| 執行位置 | worker 以 ONNX Runtime 執行 BiRefNet，不經過 ComfyUI，也不使用 rembg 套件。rembg 會拉進 numba、OpenCV 等大型相依套件，在 Windows 上也遇到路徑過長的問題。 |
| 模型 | 預設 `birefnet-general`；環境變數 `CUTOUT_MODEL` 可改為 `birefnet-general-lite`，或測試用的 `sim` |
| 記憶體 | 關閉記憶體池；同一時間只做一張去背 |
| 佇列 | 新增 SAQ 佇列 `cutouts`（同時 1 個），不與 `tasks` 佇列（文件上傳、歷史回寫）共用，大量新增商品時不會擋住文件上傳 |
| 觸發時機 | 新增商品（上傳或本機匯入）時自動排入；另有「重新去背」 |
| 前端更新 | 有商品在「去背中」時，每 2 秒重新讀取商品清單 |
| 去背狀態 | 由伺服器管理；新增與修改商品時，請求裡的 `cutout` 一律忽略 |
| mock 模式 | 不下載模型，維持色彩增值示意，但模擬相同的狀態流程 |

## 4. 架構

### 4.1 去背模組（`backend/app/cutout/`）

| 檔案 | 內容 |
|---|---|
| `processing.py` | 純函式。前處理：依 EXIF 轉正、轉 RGB、以 LANCZOS 縮成 1024×1024、除以像素最大值、以 ImageNet 的平均值與標準差正規化，與實測時使用的 rembg 2.0.85 相同。後處理：sigmoid、min-max 正規化、以 LANCZOS 縮回原尺寸、修正透明度、合成 RGBA。 |
| `segmenter.py` | `Segmenter` 介面：`cut(photo: bytes) -> bytes`，輸入照片，輸出透明 PNG。有兩種實作：`OnnxSegmenter` 以 ONNX Runtime 執行，關閉記憶體池；`SimSegmenter` 產生中央橢圓遮罩，不需要模型。 |
| `models.py` | 模型清單（名稱、網址、位元組數、SHA-256）、下載與核對 |

**透明度修正**：遮罩值 ≥ 242（95%）設為 255，≤ 13（5%）設為 0，中間的值保留，讓邊緣維持柔和。

**模型清單**（來源：rembg 的 GitHub releases，MIT 授權）：

| `CUTOUT_MODEL` | 網址 | 位元組數 | SHA-256 |
|---|---|---|---|
| `birefnet-general` | `https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-epoch_244.onnx` | 972666916 | `58f621f00f5d756097615970a88a791584600dcf7c45b18a0a6267535a1ebd3c` |
| `birefnet-general-lite` | `https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx` | 224005088 | `5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333` |

### 4.2 模型下載與載入

- **存放位置**：設定 `models_dir`。本機開發時是 `REPO_ROOT/models`，加入 `.gitignore`；Docker 中是 `/app/models`，掛載 `models` volume。
- **啟動時下載**：worker 啟動時在背景準備模型，不阻擋 worker 開始處理其他工作。
  - 已有檔案且大小與 SHA-256 都正確，就直接載入。
  - 否則下載到 `<名稱>.onnx.part`，完成後核對大小與 SHA-256，正確才改名。
- **等待模型**：模型準備好之前，去背任務會等待；等待時間計入任務逾時。
- **下載失敗**：記錄錯誤。下一次去背時重新嘗試下載，不會在每個任務都重試多次。
- **常駐記憶體**：載入後的 session 留在 worker 行程裡，平常約 1.1 GB。
- **只在 worker 執行**：api 不載入模型。

### 4.3 任務與資料流程

**佇列**：
- worker 行程新增第三個 SAQ Worker，處理 `cutouts` 佇列，同時 1 個；沿用 `main()` 統一的 SIGTERM 處理。
- 任務的 key 為 `cutout:{商品id}:{照片網址的 SHA-256 前 8 碼}`，由 `Queues.enqueue_cutout(product)` 產生：
  - 同一張照片的去背還在排隊或執行時，不會重複排入；
  - 換了照片後產生新的 key，一定會排入。

**流程**：
1. **新增商品**：
   - `POST /api/products` 與 `POST /api/local-photos/{file}/import` 建立 `photo.source` 為 `upload` 或 `local` 的商品時，把 `cutout` 設為 `{ model, status: 'pending', url: null, error: null }`。
   - 寫入資料庫後排入 `cutouts` 佇列。
   - 立即回傳，不等待去背。
2. **重新去背**：`POST /api/products/{id}/cutout`。
   - 示範商品回 400。
   - 其他商品設為 `pending` 並排入，立即回傳 `202` 與商品。
3. **修改商品**：`PUT` 忽略請求中的 `cutout`。照片網址改變時，視同重新去背；沒有改變時保留原本的 `cutout`。
4. **worker 的 `cutout` 任務**（參數：商品 id、照片網址）：
   1. 讀取商品。商品不存在，或照片網址已經不同（表示已有較新的任務），就結束。
   2. 讀取照片檔：`upload` 從 `data/`，`local` 從本機資料夾，經 `app/files.py` 的 `photo_path`（內部使用 `resolve_file`）驗證路徑。
   3. 等待模型準備好。
   4. 推論以 `asyncio.to_thread` 執行，不阻擋 event loop。
   5. 寫入 `data/products/{id}/cutout-{PNG 內容的 SHA-256 前 12 碼}.png`。
   6. 在同一個交易中鎖定商品列（`SELECT … FOR UPDATE`），確認商品仍存在、照片網址相同，才把 `cutout` 設為 `{ model, status: 'done', url: '/files/products/{id}/cutout-….png', error: null }`。
   7. 交易提交後，刪除同一資料夾裡其他的 `cutout-*.png`。若第 6 步沒有寫入，就只刪除剛寫的檔案。
5. **失敗**：任何錯誤都以第 6 步同樣的確認方式，把 `cutout` 設為 `failed`。`error` 為繁體中文原因，例如「照片無法讀取」或「去背模型下載失敗：…」，並記錄 traceback。
6. **worker 啟動復原**：在 `recover()` 中：
   - 先放掉 `cutouts` 佇列裡前一個 worker 留下的 ACTIVE 紀錄，作法與 `jobs` 佇列相同；
   - 再把 `cutout.status` 仍是 `pending` 的商品重新排入。
7. **刪除商品**：刪除自建商品時一併刪除 `data/products/{id}/`。示範商品只標記刪除，沒有資料夾。

### 4.4 逾時

- `cutouts` 佇列的任務逾時是 600 秒，涵蓋等待模型下載與推論。
- 逾時或 worker 中斷時，SAQ 會中止任務，商品仍是 `pending`；下次 worker 啟動時，由 4.3 第 6 步重新排入。

### 4.5 合約變更

前後端（`contract.py` 與 `contract.ts`）同步修改：

```ts
export type CutoutStatus = 'pending' | 'done' | 'failed';
export interface ProductCutout { model: string; status: CutoutStatus; url: string | null; error: string | null }
```

- `cutout: null` 表示不需要去背，例如示範商品。
- `status: 'done'` 且 `url: null` 表示示意，只會出現在 mock 模式。
- `ApiClient.requestCutout(productId)` 的回傳型別不變（`Product`），但回傳時商品可能仍是 `pending`。
- golden fixtures 的示範商品 `cutout` 都是 `null`，不受影響。

### 4.6 資料庫遷移（`0002`）

- 商品存在 `products.data`（JSON）裡。
- 遷移把所有 `photo.source` 為 `upload` 或 `local`、且 `cutout` 沒有 `status` 的商品，改為 `{ model: 'BiRefNet-general', status: 'pending', url: null, error: null }`。worker 啟動後由 4.3 第 6 步自動補做。
- downgrade 時把 `status`、`error` 欄位移除。

### 4.7 系統狀態

- worker 把模型狀態寫入 Redis key `cutout:model`：`{ model, state: 'downloading' | 'loading' | 'ready' | 'failed' | 'sim', error }`。key 與型別放在 `app/cutout/state.py`，api 讀取時不必匯入 onnxruntime。
- `GET /api/status` 讀取這個 key，新增一個元件 `{ id: 'cutout', label: '去背模型（BiRefNet）' }`：

| key 的內容 | `status` | `detail` |
|---|---|---|
| `ready` | `ok` | 例如「birefnet-general 已載入」 |
| `downloading` | `off` | 「第一次使用，正在下載模型（約 1 GB）」 |
| `loading` | `off` | 例如「正在載入 birefnet-general」（模型檔已在，載入約 15 秒） |
| `failed` | `error` | 失敗原因 |
| `sim` | `sim` | 「模擬去背」 |
| 沒有這個 key | `error` | 「worker 尚未回報」 |

- `ComponentStatus.id` 本來就是字串，不需要改合約。

## 5. 前端

### 5.1 商品卡（`product-card.tsx`）

| 狀態 | 標籤 | 按鈕 |
|---|---|---|
| `pending` | 「去背中…」加轉圈圖示 | 停用 |
| `done` | 「已去背」；`url` 為 null 時顯示「已去背（示意）」 | 「去背預覽」 |
| `failed` | 「去背失敗」，`title` 顯示原因 | 「重試去背」 |

縮圖直接改用去背後的 PNG。

### 5.2 去背預覽（`cutout-dialog.tsx`）

- 左邊是原圖，右邊是去背結果。
- 右邊的背景可以切換：棋盤格、淺色（品牌輔助色）、深色。
- 視窗裡有「重新去背」按鈕。
- 拿掉「第一階段為示意…」的說明；`url` 為 null 時才說明這是示意。

### 5.3 自動更新（`store/products.ts`）

- `load` 之後，只要清單裡有 `pending` 的商品，就在 2 秒後再 `load` 一次。全部完成或失敗時停止；切換品牌時，舊品牌的計時器也會取消。
- 同一時間只會有一個計時器。
- 商品庫、新任務的商品選單、批次佇列共用這份清單，所以都會自動更新。

### 5.4 其他

- **上傳提示**：「已新增 N 個商品，正在背景去背，完成後會自動更新」。
- **海報合成**（`compose/assets.ts`、`product-image.tsx`）：只有 `status === 'done'` 且 `url` 不是 null 時，才使用 PNG（`blend: 'normal'`）；其餘情況沿用色彩增值。
- **mock 模式**：
  - 新增上傳商品時先回傳 `pending`，排程約 1.2 秒後改為 `done`（`url: null`）。`requestCutout` 走同樣的流程。
  - 排程只存在記憶體裡。沒有排程的 `pending`（例如重新整理頁面後），在下一次讀取商品時直接改為 `done`。

## 6. Docker 與設定

- **相依套件**：`backend/pyproject.toml` 新增 `onnxruntime`、`numpy`、`pillow`。api 與 worker 共用映像檔，約多 60 MB。
- **docker-compose**：
  - 新增 `models` volume，掛載到 worker 的 `/app/models`；`MODELS_DIR` 以環境變數固定。
  - live E2E 的 compose 設定 `CUTOUT_MODEL=sim`。
- **`.env.example`**：說明 `CUTOUT_MODEL`（`birefnet-general`／`birefnet-general-lite`／`sim`），以及第一次啟動會下載約 1 GB 的模型。
- **README**：說明去背模型、第一次下載，以及記憶體需求（去背時 worker 約 8 GB；Docker 實測尖峰約 7.6 GiB、平常約 2 GB）。
- **`.gitignore`**：加入本機開發時的模型資料夾 `models/`。

## 7. 測試

### 7.1 後端（pytest，`CUTOUT_MODEL=sim`）

| 範圍 | 內容 |
|---|---|
| `processing` | 輸入的形狀與正規化；EXIF 轉正；透明度修正的門檻；縮回原尺寸；輸出的 RGBA |
| `models` | 本機的假 HTTP 伺服器：核對成功後才改名；SHA-256 不符時刪除暫存檔並回報；已有正確的檔案就不下載 |
| `cutout` 任務 | pending → done，寫入檔案與網址，並刪除舊檔；照片無法讀取 → failed；途中刪除商品或更換照片 → 丟棄結果，新照片的任務仍會完成；worker 啟動時放掉 ACTIVE 殘留紀錄、重新排入 pending；`cutouts` 佇列同時只執行一個 |
| API | 新增上傳或本機匯入商品時排入且回傳 pending；`PUT` 忽略 `cutout`，換照片時重新排入；`POST …/cutout` 回 202；同一張照片重複排入只做一次；刪除商品時刪除資料夾；系統狀態的「去背模型」五種情況 |
| 遷移 | 舊格式轉為 pending；示範商品不變；可以 downgrade |

**真模型測試**：標記為 `model`，照片路徑由環境變數 `CUTOUT_TEST_PHOTO` 指定；沒有模型檔或沒有指定照片時略過。確認四角透明、商品中央不透明。

### 7.2 前端（vitest）

- 商品 store：有 pending 時每 2 秒讀取，完成後停止，切換品牌後停止（fake timers）。
- `assets.ts`：只有 done 且有 url 時使用 PNG。
- mock client：新增上傳商品時 pending → done；`requestCutout` 的狀態流程。
- HTTP client：`requestCutout` 接受 202。

### 7.3 E2E

- **live**（`CUTOUT_MODEL=sim`）：上傳商品照後，商品卡顯示「去背中」→「已去背」，預覽中看得到去背圖。
- **mock**：既有測試維持通過。

### 7.4 實機驗收（Docker，`birefnet-general`）

- 第一次啟動時下載模型。
- 用使用者的商品照去背，在預覽的三種背景下確認邊緣，並合成一張海報。
- 記錄 Docker 內每張的時間與記憶體峰值。

## 8. 與第二階段規格的關係

已同步修改 `2026-10-07-phase2-backend-design.md`：

- 第 1 節技術表：去背改由「ONNX Runtime＋BiRefNet」負責，ComfyUI 只負責背景生成、打光融合與放大。
- 5.5：刪除 `cutout_v1` workflow。`product_scene_v1` 直接讀取 `cutout.url` 的透明 PNG。
- 3.4 筆電記憶體：加上去背時約 7.6 GB、平常約 2 GB（Docker 實測；第 2 節的表是本機實測）。
- 6.2：`data/products/{id}/` 存放去背圖。原圖仍在 `data/uploads/`，本機匯入的照片仍在本機資料夾，本規格不搬移原圖。

## 9. 不在範圍內

- GPU 加速：GTX 1050 Ti 只有 4 GB 顯示記憶體，Docker 的 GPU 設定也較複雜；CPU 的速度已經足夠。
- 手動修正遮罩（筆刷）。
- 在瀏覽器中去背，以及 mock 模式的真實去背。
- 陰影或倒影的合成（Plan 7 的 IC-Light 負責光影融合）。
