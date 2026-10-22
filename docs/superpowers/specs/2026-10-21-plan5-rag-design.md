# Plan 5：RAG（Chroma＋BGE-M3＋Reranker）設計規格

- 日期：2026-10-21
- 狀態：使用者已同意設計方向（2026-10-21）；細節依草稿實作（分支 `plan5-draft`）的結果補充
- 相關：`2026-10-07-phase2-backend-design.md`（第二階段後端，§5.2、§13）。本規格補足 Plan 5 的細節，並修改第二階段規格的幾個地方（見第 10 節）。

## 1. 目標

Plan 4 的 RAG 全部是模擬版：
- 檢索依 mock 劇本，固定回傳 5 個切塊與寫死的分數；
- 上傳手冊只切塊並存進 PostgreSQL，「向量」是雜湊產生的假數字；
- 歷史回寫只把 `writtenToRag` 設成 true。

本規格把 live 模式的檢索與知識庫換成真的：
- BGE-M3 向量化、Chroma 向量召回、bge-reranker-v2-m3 重新排序；
- 上傳的 CI 手冊（含 PDF）真的切塊、向量化並寫入 Chroma；
- 選定的海報真的寫成歷史切塊，之後的任務檢索得到；
- 模擬版保留，測試、live E2E 與作品集 Demo 照舊使用。

## 2. 實測結果（2026-10-21）

**測試環境**：
- Intel i5-14500、Docker（WSL2）；
- 容器限制 4 顆 CPU；
- ONNX Runtime 1.31、tokenizers 0.23.3；
- 兩個模型都用 int8。

| 項目 | 結果 |
|---|---|
| 查詢向量化（短句） | 約 0.023 秒 |
| 切塊向量化（約 300 字） | 每秒約 4.8 塊 |
| Rerank 4 對短句 | 約 0.15 秒 |
| Rerank 20 對（各約 300 字） | 約 4.6 秒 |
| 載入模型 | 每個約 0.7 秒（不含下載） |
| 兩個模型都載入的記憶體峰值 | 預設 2.65 GB；關閉記憶體池（`enable_cpu_mem_arena=False`、`enable_mem_pattern=False`）1.93 GB（含約 0.33 GB 的 Python 基本用量） |
| int8 與原版（fp32）比較 | 向量餘弦相似度平均 0.98；Rerank 的 logit 平均差 0.15；10 個查詢的第一名都相同 |

**其他發現**：
- **批次會影響結果**。int8 動態量化的縮放值是以整個批次計算的，同一段文字單獨算和放在批次裡算，向量的餘弦相似度最低只有 0.971。逐筆計算時，結果固定，速度也快 10–14%。
- **Rerank 的分數很小**。經過 sigmoid 轉換後，「品牌｜商品｜需求」這類標題式查詢的最高分也常低於 0.05，所以不能用固定門檻篩選，只看排名。
- **一個 tokenizer 就夠**。兩個模型的 `tokenizer.json` 產生的 token id 完全相同，共用一個可省約 285 MB。
- **Chroma 的映像檔來源**。`ghcr.io/chroma-core/chroma:1.5.9` 不必登入就能拉取。`public.ecr.aws` 上沒有 Chroma。映像檔裡沒有 curl。

## 3. 已確認的決定

| 項目 | 決定 |
|---|---|
| 模型 | 以 ONNX Runtime 在 CPU 執行 int8 版本，不使用 PyTorch 與 transformers。向量化用 `Xenova/bge-m3` 的 `sentence_transformers_int8.onnx`（輸出已正規化的 1024 維向量），Rerank 用 `onnx-community/bge-reranker-v2-m3-ONNX` 的 `model_int8.onnx`（輸出 logit，取 sigmoid），兩者共用 `Xenova/bge-m3` 的 `tokenizer.json`。 |
| 執行位置 | worker（與第二階段規格相同）；推論使用專用的單一執行緒，不與去背共用，去背時檢索不必等 |
| 載入時機 | worker 啟動時下載並核對模型檔，但不載入；第一次需要向量化或 Rerank 時才載入，之後常駐 |
| 計算方式 | 一律逐筆計算（批次大小 1）；關閉記憶體池 |
| 向量庫 | Chroma 1.5.9 獨立容器；每個品牌一個 collection `{brandId}_ci`，距離為 cosine |
| 資料的主從 | PostgreSQL 的 `brand_chunks` 為準，Chroma 只是索引。worker 比對兩邊後補上缺少的、刪除多餘的，所以 Chroma 的資料遺失時會自動重建 |
| 切換 | 環境變數 `RAG_MODE`：`bge`（預設）或 `sim` |
| 上傳格式 | `.md`、`.markdown`、`.txt`（UTF-8）、`.pdf`（以 pypdf 抽出文字層）；單檔 20 MB 以內 |
| 歷史案例 | 品牌設定檔的 `caseStudies` 也切塊（origin `config`、tag `history`） |
| 實際用量成本 | 移到 Plan 6：Plan 5 沒有付費呼叫，`job_usage` 表與單價設定等 Gemini 實際產生 token 時再一起做 |
| Plan 4 延後項目 | 併入本計畫（見第 8 節） |

## 4. 架構

### 4.1 RAG 模組（`backend/app/rag/`）

| 檔案 | 內容 |
|---|---|
| `chunking.py` | `web/src/lib/rag/chunk.ts` 的 Python 移植：`chunk_document`、`guess_tag`、`tag_of`、`embed_preview`。以 golden fixture 確認兩邊切出的結果完全相同。 |
| `extract.py` | 由上傳的檔案取出文字：Markdown 與純文字以 UTF-8 解碼（可有 BOM），PDF 以 pypdf 逐頁抽字、頁與頁之間空一行 |
| `models.py` | 模型清單（名稱、網址、位元組數、SHA-256） |
| `encoder.py` | `Encoder` 介面：`embed(text) -> list[float]`、`rerank(query, passages) -> list[float]`。`OnnxEncoder` 載入兩個 ONNX 模型與共用的 tokenizer（截斷 512 token、`<pad>` 的 id 為 1） |
| `engine.py` | `RagEngine`：下載、核對、按需載入，並把狀態寫到 Redis（模式與去背的 `CutoutEngine` 相同） |
| `state.py` | Redis 鍵 `rag:model` 與狀態名稱（api 讀取，不必 import onnxruntime） |
| `errors.py` | `RagError`（繼承 `Unavailable`，錯誤碼 `unavailable`，訊息為繁體中文） |
| `store.py` | `VectorStore`：Chroma 的非同步 HTTP 客戶端（`chromadb-client`），負責 collection、upsert、刪除、查詢與指紋列表 |
| `sync.py` | 比對 PostgreSQL 與 Chroma，並修正差異（見 4.4） |
| `retriever.py` | `BgeRetriever`：實作 `Retriever` 介面（見 4.5、4.6） |
| `history.py` | 由 `HistoryEntry` 組出歷史回寫切塊的文字（見 4.8） |

**共用的模型下載**：去背的下載與核對（`backend/app/cutout/models.py` 的 `ModelFile`、`has_model`、`ensure_model`）抽到 `backend/app/modelfiles.py`，去背與 RAG 共用。
- `ModelFile` 新增 `filename` 欄位，因為 tokenizer 是 `.json`；沒有指定時沿用 `{name}.onnx`，去背的模型清單不必修改。
- 去背對外的行為與中文錯誤訊息不變。

### 4.2 模型清單

| 名稱 | 網址 | 位元組數 | SHA-256 | 授權 |
|---|---|---|---|---|
| `bge-m3-int8.onnx` | `https://huggingface.co/Xenova/bge-m3/resolve/4de13258303883538bd53b696b452bf8099f0858/onnx/sentence_transformers_int8.onnx` | 568599071 | `e5b42096865cef734247dd8c7a44e35d305b70ba0c3736758065e1cad50f6453` | MIT |
| `bge-m3-tokenizer.json` | `https://huggingface.co/Xenova/bge-m3/resolve/4de13258303883538bd53b696b452bf8099f0858/tokenizer.json` | 17082821 | `6710678b12670bc442b99edc952c4d996ae309a7020c1fa0096dd245c2faf790` | MIT |
| `bge-reranker-v2-m3-int8.onnx` | `https://huggingface.co/onnx-community/bge-reranker-v2-m3-ONNX/resolve/6f5ff65298512715a1e669753bc754d2bc8f367b/onnx/model_int8.onnx` | 570727094 | `912fc1215c2dbff6499700534bd8d31253af01573861abbfc43afd1fab6cce5d` | Apache-2.0（上游 `BAAI/bge-reranker-v2-m3`） |

- 合計約 1.16 GB，存在 `models` volume（與去背共用）。
- 網址固定 commit，換模型或換版本都要重建索引。

### 4.3 Chroma

- **服務**：映像檔 `ghcr.io/chroma-core/chroma:1.5.9`，連接埠 `127.0.0.1:8001:8000`（8000 已給 api），volume `chroma:/data`。
- **健康檢查**：映像檔裡沒有 curl，改用 bash 的 `/dev/tcp` 讀 `GET /api/v2/heartbeat`。
- **連線**：api 與 worker 以 `CHROMA_URL`（Docker 內為 `http://chroma:8000`）連線。api 只用來檢查狀態；只有 worker 寫入。
- **collection**：`{brandId}_ci`，建立時設定 `configuration={'hnsw': {'space': 'cosine'}}`、`embedding_function=None`（向量由 worker 提供）。
- **每個切塊**：
  - id 與 PostgreSQL 相同，例如 `selune#color`；
  - 文件為切塊文字；
  - metadata 為 `brandId`、`tag`、`source`、`section`、`origin`，以及 `textHash`（向量化文字的 SHA-256 前 16 碼）。
- **向量化的文字**：`{section}：{text}`。章節名稱也帶有語意，例如「§2.1 色彩系統」。
- **測試**：使用同一個 Chroma 的另一個 database `genai_test`。這和 PostgreSQL 用 `genai_test`、Redis 用 DB 15 的做法相同。

### 4.4 資料同步（PostgreSQL → Chroma）

`sync_brand(brand_id)`：
1. 讀出 PostgreSQL 中該品牌的全部切塊，以及 Chroma 中各切塊的 metadata。
2. 缺少的、或 metadata 任何一項不同的（包括 `textHash`），逐筆向量化後 upsert，每 32 筆寫入一次。只比對 `textHash` 不夠：品牌設定檔只改了切塊的 tag 或 source 時，Chroma 也要更新，重新檢索的過濾條件就依賴 tag。
3. Chroma 有、PostgreSQL 沒有的，刪除。

沒有差異時，這個步驟只需要一次 Chroma 查詢與一次資料庫查詢，不會載入模型。

**執行時機**：
- **worker 啟動**：模型下載與核對完成後，依序同步所有啟用中的品牌，並刪除已停用品牌的 collection。品牌設定檔修改後重新啟動 api 與 worker，即可更新索引。
- **每次檢索前**：同步該品牌一次，不必依賴啟動的順序。
- **上傳手冊與歷史回寫**：先寫入 PostgreSQL，再寫入 Chroma。

**一致性**：
- 所有寫入 Chroma 的動作（同步、上傳、回寫）都要取得同一個品牌鎖（worker 行程內的 `asyncio.Lock`），避免同步時誤刪剛寫入的切塊。上傳與回寫在鎖外先向量化，鎖內只寫入，不會長時間擋住檢索。
- Chroma 的每個呼叫限時 30 秒（chromadb 的連線預設沒有逾時）。
- 寫入 Chroma 失敗時，PostgreSQL 的資料仍在，下一次同步會補上。

### 4.5 檢索（任務的 `retrieving` 階段）

1. 先同步該品牌（見 4.4）。
2. 查詢字串為「品牌名｜商品名｜一句話需求｜賣點」。
   - 賣點取 `parsedBrief.sellingPoints`，沒有時改用商品的 `features`，以「、」連接。
   - 空的部分省略，不留下多餘的「｜」。
   - 以 `rag.retrieved.query` 送出。
3. 向量召回 8 筆（`where={'origin': {'$ne': 'alt'}}`）。
   - 向量分數為 cosine 相似度（`1 - distance`）。
   - `rag.retrieved` 送出這 8 筆。
4. 逐筆 Rerank（passage 與向量化的文字相同，為「章節：內文」），分數為 sigmoid(logit)，依分數由高到低排序（同分時維持向量順序）。`rag.reranked` 送出這 8 筆。
5. `ragRefs` 取 Rerank 後的前 5 筆。這條規則由流程統一處理，模擬版只有 5 筆，結果不變。

**等候與錯誤**：
- 品牌還沒有任何切塊時，送出空的結果，任務繼續。
- 模型還沒載入時，先送出 `log` 事件「RAG 模型準備中」，再等候下載或載入。`Retriever.retrieve` 因此多一個 `run` 參數（與 `ImageEngine.render_round` 相同）；模擬版不使用它，事件不變。
- 模型準備失敗或 Chroma 連不上時，任務失敗。原因以中文說明，例如「向量庫（Chroma）無法連線：…」。

### 4.6 Query Rewriting 的重新檢索

- 觸發條件與事件順序不變，由 `LlmAgent.plan_rewrite` 決定是否重新檢索與查詢字串（Plan 5 仍是模擬版，Plan 6 換成 Gemini）。
- 真實版：
  - 以改寫後的查詢召回 4 筆（`where={'$or': [{'origin': 'alt'}, {'tag': 'law'}]}`）並 Rerank，不再同步一次（任務開始時已同步）；
  - `rag.retrieved` 送出這 4 筆，每筆都帶 Rerank 分數；
  - 沒有出現在 `ragRefs` 中的，依序加入。

### 4.7 上傳手冊

**API**：`POST /api/brands/{id}/documents`，改為 multipart，欄位 `file`。

**api 先檢查以下各項，有錯就直接回傳錯誤，不開始串流**：

| 情況 | 錯誤 |
|---|---|
| 品牌不存在 | 404 `not_found` |
| 副檔名不支援（接受 `.md`、`.markdown`、`.txt`、`.pdf`） | 400 `invalid`「只支援 .md、.txt、.pdf」 |
| 超過 20 MB | 400 `invalid`「檔案不可超過 20 MB」 |
| 文字檔不是 UTF-8 | 400 `invalid`「文字檔需為 UTF-8 編碼」 |
| PDF 有密碼，或以 AES 加密 | 400 `invalid`「PDF 有加密保護（密碼或權限限制），請先移除保護再上傳」。只有權限限制、沒有開啟密碼的 PDF 以空密碼開啟。AES 需要 `cryptography`，不安裝 |
| PDF 損壞 | 400 `invalid`「PDF 無法讀取：…」 |
| PDF 讀不到文字 | 400 `invalid`「PDF 沒有可讀取的文字（可能是掃描檔），請先轉成文字」 |
| 文字超過 20 萬字 | 400 `invalid`「文字超過 20 萬字（N 字），請分成幾份上傳」 |
| 切塊超過 2,000 | 400 `invalid`「切塊太多（N 塊，上限 2,000），請分成幾份上傳」 |

- 抽字在 api 以 `asyncio.to_thread` 執行。之後只把文字放進佇列，不傳原檔。
- **切塊上限**（`MAX_CHUNKS = 2000`）：api 抽字後先以 `chunk_document` 切塊，只檢查塊數（worker 會再切一次）。20 萬字的一般文章約 1,170 塊，但很多短段落的文件（FAQ、詞彙表、行距大的 PDF）可能切出上萬塊。2,000 塊在 4 顆 CPU 上約每秒 4.8 塊，約 420 秒，在任務時限 600 秒之內。
- **康熙部首**：以微軟正黑體輸出的 PDF（Chromium、Office 都會），常把「月」「色」「用」等字記成外觀相同的康熙部首（U+2F00 起）。分類規則與向量都認不出這些字，所以抽字後只對這個範圍做 NFKC，轉回一般漢字；全形標點不受影響。
- **PDF 的章節**：PDF 沒有 Markdown 標題，每一頁成為一段，章節為檔名。
- 檔名去掉瀏覽器加上的 `C:\fakepath\`。
- **逾時**：從「整體 120 秒」改為「120 秒沒有任何進度」（`INGEST_IDLE_TIMEOUT`），訊息為「文件處理逾時：120 秒沒有任何進度。第一次使用時 worker 可能仍在下載 RAG 模型，請稍後再試；若持續發生，請確認 worker 正在執行」。大份手冊向量化需要幾分鐘，只要持續有進度就不算逾時。

**worker 的 `ingest`**：
1. 以 Python 的 `chunk_document` 切塊，送出 `ingest.chunked`。
2. 逐塊向量化，每塊送出 `ingest.embedded`，`preview` 為真實向量的前 6 維（四捨五入到小數 3 位）、`dims` 為 1024。
3. 以 `replace_document_chunks` 寫入 PostgreSQL（同一個 source 先刪後寫）。
4. 刪除 Chroma 中同一個 source 的上傳切塊，再 upsert 新的切塊。
5. 送出 `ingest.stored`。

**錯誤碼**：
- 品牌不存在：`not_found`；
- 沒有可用文字：`invalid`；
- 模型準備失敗或 Chroma 無法連線：`unavailable`；
- 其他：`internal`，訊息為「文件處理失敗：…」。
- 超過任務時限（`TASK_TIMEOUT` 600 秒）被 SAQ 取消：`unavailable`「文件處理超過 10 分鐘而中止，請把文件分成幾份再上傳」。發布後仍把 `CancelledError` 往外丟，讓 SAQ 看到取消；發布失敗（例如 Redis 停止）時也一樣。
- 訊息都是繁體中文。

**模擬版**：同樣用 Python 的 `chunk_document` 切塊，`preview` 用 `embed_preview`，只寫入 PostgreSQL。原本 composer 的 `/sim/ingest` 改由 Python 處理，所以刪除。

### 4.8 歷史回寫

選定海報後，`tasks` 佇列的 `write_back` 依序：
1. 由 `HistoryEntry` 組出一個切塊：
   - id：`{brandId}#hist-{historyId}`；
   - tag `history`、origin `history`；
   - source：`history/{jobId}`；
   - section：「{模板名稱}・{選定日期}」；
   - 文字以商品名稱開頭（商品已刪除時省略），接著是模板、審查分數、標題與副標、賣點、正向提示詞的前 120 字，例如「極光玻尿酸修護精華 30ml・IG 貼文海報，審查 99 分。標題：…」；空的欄位省略，沒有分數時寫「未經審查評分」。
   - 選定日期以設定的時區（`TIMEZONE`，預設 Asia/Taipei）計算。
2. 寫入 PostgreSQL。以 id upsert，所以重跑不會產生重複的切塊。
3. 真實版再向量化並 upsert 到 Chroma。
4. 把 `writtenToRag` 設成 true。

**API**：
- 最多等 10 秒的規則不變。
- 回寫失敗（SAQ 回報失敗或中止）時，回傳 `writtenToRag: false`，不再回 500，前端也就不會重送。
- 回寫以歷史紀錄的 id 為單位，可以重跑；「選定」本身每次都會建立一筆新的歷史紀錄。
- `writtenToRag: false` 表示回寫沒有完成。切塊若已寫入 PostgreSQL，下一次檢索前的同步會補進 Chroma，但這個欄位維持 false。

**mock**：`selectRender` 同樣在知識庫加上這個切塊。品牌知識庫頁面以「歷史回寫」標示這類切塊。

### 4.9 歷史案例切塊

品牌設定檔的每個 `caseStudies` 項目都產生一個切塊：
- id：`{brandId}#case-{序號}`，序號從 1 開始；
- source：品牌設定檔的檔名；
- section：案例標題；
- tag `history`、origin `config`；
- 文字：「{通路}素材，CTR {ctr}%：{notes}」。CTR 依 JavaScript 的數字格式，例如 4 寫成「4」而不是「4.0」。

**順序**：一般規範、歷史案例、`law-alt`。品牌設定檔載入的順序、API 列出的順序（origin `alt` 一律最後）與 TypeScript 的順序都相同。模擬檢索選到的 history 切塊不變。

**保留的 key**：guidelines 的 key 不可以 `doc-`、`hist-`、`case-` 開頭，避免與系統產生的 id 重複。

**`brands.source_hash`**：改為對轉換後的品牌與範例商品 JSON 計算，不再對 YAML 原文計算。這樣既有的資料庫不必修改 YAML 也會補上歷史案例切塊，之後轉換規則改變時也會自動重新同步。

TypeScript 的示範品牌資料以相同規則產生，所以 golden fixture 與 mock 的知識庫一致。

### 4.10 系統狀態

`/api/status` 新增兩個元件，取代原本的模擬項目「向量庫（Chroma＋BGE）」：

- `chroma`「向量庫（Chroma）」：
  - 以 `GET {CHROMA_URL}/api/v2/heartbeat` 檢查，限時 3 秒；
  - 正常時顯示網址；連不上時為 `error`「連不上 Chroma（網址）：…」，回應不是 200 時為「Chroma 回應 HTTP n（網址）」。
  - `RAG_MODE=sim` 時不檢查，顯示 `sim`「模擬模式不使用向量庫」。
- `rag`「RAG 模型（BGE-M3＋Reranker）」：讀 Redis 的 `rag:model`，狀態對應如下：

| 狀態 | 顯示 | 說明 |
|---|---|---|
| `sim` | `sim` | 模擬檢索：固定的召回與 Rerank 順序 |
| `downloading` | `off` | 第一次使用，正在下載模型（約 1.2 GB） |
| `standby` | `ok` | 模型已就緒，第一次檢索時載入 |
| `loading` | `off` | 正在載入模型 |
| `ready` | `ok` | bge-m3＋bge-reranker-v2-m3 已載入 |
| `failed` | `error` | 原因 |

- 鍵不存在時顯示「worker 尚未回報」，格式錯誤時顯示「RAG 模型狀態無法辨識」。

### 4.11 前端

- **`ApiClient.ingestBrandDocument(brandId, file: File, onEvent)`**：原本傳 `{ name, text }`，改為傳檔案。
  - `HttpApiClient` 以 `FormData` 上傳。
  - `HttpApiClient` 在上傳之前拒絕超過 20 MB 的檔案（`invalid`「檔案不可超過 20 MB」，與後端的 `MAX_BYTES` 相同），不送出請求；nginx 的 `client_max_body_size` 回的 HTML 413 轉成 `invalid`「檔案太大，超過伺服器允許的上傳大小」（商品照上傳也適用）。
  - `MockApiClient` 以 `file.text()` 讀取 `.md`、`.markdown`、`.txt`；其他格式（包括 PDF）回報「示範模式只能讀取 .md、.txt」。
  - `BrandDocument` 從合約移除；切塊使用的 `{ name, text }` 改名為 `TextDocument`，放在 `web/src/lib/rag/chunk.ts`。
- **品牌知識庫**：
  - 檔案選擇加上 `.pdf`。
  - 依 id 標示切塊類型：`#doc-` 為「新上傳」、`#hist-` 為「歷史回寫」、`#case-` 為「歷史案例」、`-alt` 為「Query Rewriting 專用」。
- **系統狀態**：顯示新的 `chroma` 與 `rag` 元件，不需要改程式。
- **Agent 透視**：顯示方式不變。真實的 Rerank 分數很小，以排名為主；分數條依實際數值顯示。

## 5. 模擬模式（`RAG_MODE=sim`）

- 檢索沿用 `SimRetriever`，比對 mock 劇本的 parity 測試不受影響。
- 上傳與歷史回寫只寫 PostgreSQL，不連 Chroma，也不下載模型。
- `rag` 狀態為 `sim`。
- live E2E（`docker-compose.e2e.yml`）設定 `RAG_MODE: sim`。

## 6. 設定與部署

**環境變數**：

| 變數 | 預設 | 說明 |
|---|---|---|
| `RAG_MODE` | `bge` | `bge` 或 `sim` |
| `CHROMA_URL` | `http://127.0.0.1:8001` | Docker 內為 `http://chroma:8000` |

**Compose**：
- 新增 `chroma` 服務與 `chroma` volume。
- worker 等 chroma 健康後才啟動。
- e2e 的 chroma 使用自己的 volume。

**後端相依套件**：

| 套件 | 版本 | 說明 |
|---|---|---|
| `chromadb-client` | `==1.5.9` | 與伺服器版本相同；不帶 onnxruntime 與 tokenizers |
| `tokenizers` | `>=0.23.3` | |
| `pypdf` | | |
| `regex` | | 切塊需要 `\p{Script=Han}` |

**記憶體**（2026-10-21 Docker 驗收實測）：
- RAG 模型載入後，worker 約增加 1.7 GB（實測 1.75 GB；沒有載入時 worker 約 0.1 GB，為去背用模擬版時的實測），向量化與 Rerank 時幾乎不再增加（峰值 1.81 GB）。
- 與去背的尖峰（約 7.6 GiB）相加約 10 GB，所以 Docker 的記憶體上限建議約 12 GB；記憶體不夠時可以設 `RAG_MODE=sim`。
- Chroma 本身約 20 MB。

## 7. 測試

- **切塊一致性**：
  - TypeScript 由一組範例文件產生 `contracts/fixtures/chunks.json`，加入 golden fixtures 清單；
  - pytest 比對 Python 的 `chunk_document` 與 `embed_preview` 輸出完全相同。
  - 範例文件涵蓋標題、條列、中英混排、長句硬切與空白文件。
- **抽字**：Markdown、純文字、BOM、非 UTF-8、PDF（測試資料夾放一份含中文文字層的小 PDF）、有密碼的 PDF、讀不到文字的 PDF。
- **Encoder**：
  - 一般測試使用 `FakeEncoder`，依字元產生確定的向量，相關文字的相似度較高。
  - 真模型的測試標記 `model`，只在本機有模型檔時執行。測試內容是相關段落排在不相關段落之前。
- **Chroma**：
  - 整合測試連 `127.0.0.1:8001` 的 Chroma，使用 database `genai_test`，每個測試結束後刪除建立的 collection；
  - 涵蓋同步（補上、更新、刪除、無差異時不向量化）、召回的過濾條件、品牌鎖。
- **流程**：
  - `BgeRetriever` 搭配 `FakeEncoder` 與真的 Chroma，測試召回 8 筆、Rerank 排序、前 5 筆進入 `ragRefs`、重新檢索的過濾與合併；
  - parity 測試不變。
- **API**：multipart 上傳的各種錯誤、進度串流、閒置逾時、回寫失敗時回傳 `writtenToRag: false`；以子行程確認 api 不會載入 onnxruntime、tokenizers、chromadb。
- **前端**：`HttpApiClient` 以 `FormData` 上傳；mock 拒絕 PDF；知識庫的切塊標示。
- **E2E**：
  - mock 照舊；
  - live 的文件上傳測試改用檔案上傳（模擬版）。
- **驗收**（真模型，Docker）：
  - 上傳 Markdown 與 PDF 手冊；
  - 跑一個任務，確認 Agent 透視的分數是真實的；
  - 選定海報，確認之後的檢索找得到這個歷史切塊；
  - 重新啟動 worker，確認沒有重新向量化；
  - 刪除 chroma volume 後，確認會自動重建；
  - 記錄 worker 的記憶體。

## 8. 併入的 Plan 4 延後項目

1. **Redis 停止時**，任務的 WebSocket 改為每秒從資料庫讀取新事件，不中斷連線，直到任務結束（Redis 恢復後也不再切回）。
2. **`HttpApiClient` 收到不是 JSON 的 5xx 回應**（例如 `next dev` 在後端停止時回的 500、nginx 的 502／504）時，視為連不上後端（`network`），連線狀態不再顯示「已連線」。後端自己的錯誤一律是 JSON，所以不受影響。
3. **live E2E 的 `globalSetup`** 先執行 `down -v --remove-orphans`，清掉上次中斷留下的容器。
4. **nginx** 設定 `resolver_timeout 2s`。
5. **Alembic 的 `script.py.mako`**：產生的 migration 要能通過 ruff（不使用 `typing.Union`、import 依序排列、空的 migration 不 import 用不到的 `op`／`sa`）。自動產生的程式碼無法只靠範本通過 `ruff format`，所以 `alembic.ini` 加上 `post_write_hooks`（先 `ruff check --fix`，再 `ruff format`）。`alembic.ini` 必須維持 ASCII：Alembic 以系統編碼（Windows 為 cp950）讀取它，中文註解會讓 migration 失敗。
6. **上傳的錯誤碼**（見 4.7）與**歷史回寫失敗不再回 500**（見 4.8）已在上面處理。

## 9. 驗收

1. 以 `docker compose up -d` 啟動後，系統狀態依序顯示模型下載中、就緒，Chroma 正常。
2. 上傳一份 Markdown 和一份 PDF 手冊：進度條顯示真實的向量值；品牌知識庫看得到新切塊；Chroma 的切塊數與 PostgreSQL 相同。
3. 跑一個任務：Agent 透視的召回分數與 Rerank 排序來自真實模型，`ragRefs` 為前 5 筆。
4. 選定海報後，`writtenToRag` 為 true，知識庫出現「歷史回寫」切塊，之後的任務可以召回它。
5. 重新啟動 worker 不會重新向量化；刪除 chroma volume 後，重新啟動會自動重建。
6. 全部測試通過（後端、前端、mock E2E、live E2E）。

## 10. 對第二階段規格的修改

- **§5.2**：
  - 加上：PostgreSQL 為準、Chroma 為索引；
  - 加上：查詢的賣點取自 `parsedBrief.sellingPoints`；
  - 加上：Prompt 使用前 5 筆；
  - 上傳手冊加上 PDF 與 multipart；
  - 重新檢索的過濾條件與筆數。
- **§5.8、§13**：「實際用量成本」從 Plan 5 移到 Plan 6。
- **§7**：`ApiClient.ingestBrandDocument` 改為傳入 `File`。
- **§8**：`POST /api/brands/{id}/documents` 改為 multipart。
- **§3.4**：補上 RAG 模型約 1.7 GB（Docker 實測）。

## 11. 不做

- **混合檢索**：不使用 BGE-M3 的稀疏向量或 ColBERT 向量，只用 dense。
- **OCR**：掃描的 PDF 不做 OCR，只提示使用者先轉成文字。
- **Word 檔**：不支援 `.docx`。
- **閒置釋放**：模型閒置時不卸載。記憶體調整在 Plan 7 統一處理。
- **知識庫編輯**：不提供刪除單一切塊或整份文件的介面。
- **PDF 的章節判斷**：不從 PDF 的字級或版面推測標題。

## 12. 驗收結果（2026-10-21，草稿分支，Docker 專案 `plan5-accept`）

主機為 20 個邏輯 CPU，容器沒有限制 CPU，所以時間比第 2 節（4 顆 CPU）短。

| 項目 | 結果 |
|---|---|
| 第一次啟動 | 下載 3 個模型檔（1.157 GB）約 117 秒；從 worker 啟動到「已載入」約 120 秒（啟動同步要向量化 17 個設定檔切塊，所以立即載入模型） |
| 上傳 Markdown | 7 個切塊，平均每塊 93 毫秒；PostgreSQL 與 Chroma 的切塊數相同 |
| 上傳 PDF（`ci-sample.pdf`） | 2 個切塊，每塊約 70 毫秒 |
| 任務的檢索 | 召回 8 筆（不含替代用語），Rerank 分數 0.16–0.68；`ragRefs` 為 Rerank 前 5 筆；扣掉模擬的節奏，同步、查詢向量化與召回約 0.13 秒，Rerank 8 筆約 1.4 秒 |
| Query Rewriting | 召回 4 筆 law 切塊並 Rerank，只加入新的 id |
| 歷史回寫 | `writtenToRag: true`；下一個任務的召回與 Rerank 都把它排第一（Rerank 0.97） |
| 重新啟動 worker | 沒有重新向量化：模型維持「待命」、worker 約 0.1 GB |
| 刪除 chroma volume 後重新啟動 | 約 6.5 秒重建 27 個切塊，分數與重建前完全相同 |
| 模型尚未載入的任務 | 送出「RAG 模型準備中」，檢索階段約 4.5 秒 |
| 記憶體 | 見第 6 節 |
