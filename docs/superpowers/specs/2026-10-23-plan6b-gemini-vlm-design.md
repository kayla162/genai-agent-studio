# Plan 6B：Gemini Agent、VLM 審查、用量與成本 設計規格

- 日期：2026-10-23
- 狀態：設計決定已由使用者逐項確認，文件已審閱同意（2026-10-23）
- 相關：
  - `2026-10-07-phase2-backend-design.md`（§3.2、§4.4、§5.1、§5.3、§5.4、§5.6–5.8、§6.1、§13）
  - `2026-10-22-plan6a-server-compose-design.md`（§8 延後項目、§12 品牌設定的發現）

## 1. 目標

6A 之後，主色與 7 項規則已經是真的，但還有五個缺口：
- **Agent 是模擬的**：
  - 需求拆解用關鍵字規則；
  - 文案取自品牌的 `copyPresets`；
  - Query Rewriting 依檢查項套用固定的修正說明。
- **VLM 三項依內容判斷**：誇大用語看禁用詞、遮擋看 Logo 與標題的方框、畫質一律通過（`web/src/lib/review/vlm.ts` 的 `contentVlmChecks`）。
- **OCR 錯字比對永遠是 0 處差異**：沒有任何轉錄。
- **成本是估算的**：儀表板以事件數乘上固定單價。
- **版型改不了**：商品佔畫面 21–34%，品牌 `productRatio` 下限高於這個值時永遠無法通過（6A §12）。

本規格要完成五件事：
1. Gemini 負責需求拆解、Prompt 構建（文案、版面、生圖提示詞）與 Query Rewriting。程式護欄保證文案合規、畫得出來，版面也符合品牌規則。
2. Gemini VLM 讀審查用海報，判斷三項 VLM 檢查，並轉錄畫面上的文字，由 `ocrDiffs` 與文案比對。
3. 版面由 Gemini 依品牌規則調整，解決 6A §12 的問題。
4. 每次 Gemini 呼叫都寫入 `job_usage`，依單價表計算費用；設定單一任務與每月的費用上限；儀表板改用實際用量。
5. 處理 6A §8 留下的四個延後項目。

模擬模式（測試、live E2E、作品集 Demo）維持不變。背景仍是程序化背景，Plan 7 才接 ComfyUI。

## 2. 實作開頭的實驗（需要 API key）

撰寫本規格時還沒有 API key。以下項目由實作計畫的第一個 Task 以真的 API 實測，結果記錄在 §12。標示「實驗決定」的數值依結果調整。

| 項目 | 方法 | 通過標準 | 不通過時 |
|---|---|---|---|
| 結構化輸出 | 3 個品牌 × 5 個模板 × 2 次 Prompt 構建 | 第一次就通過格式驗證 ≥ 95%；不必重問就通過全部護欄 ≥ 70% | 調整提示詞 |
| 轉錄 | composer 繪製 3 個品牌 × 5 個模板的正確海報，VLM 轉錄後計算 `ocrDiffs` | 0 處差異 ≥ 90%，沒有任何一張 ≥ 2 處 | 提高送出圖片的解析度，或調整「字級過小不比對」的門檻 |
| 抓得到錯字 | 同上，但繪製前把標題換掉一個字，或放入一個缺字（畫成方塊） | 30 張全部有差異；有方塊的全部判定為不通過 | 同上 |
| VLM 判讀 | 正確的海報、Logo 壓在標題上、副標含禁用詞以外的誇大說法 | 正確海報三項都通過 ≥ 90%；刻意製造的遮擋與誇大全部抓到 | 調整提示詞 |
| 穩定性 | 同一張海報審查 3 次 | 三項檢查的狀態一致 ≥ 90% | 記錄為已知限制 |
| 用量與時間 | 記錄每種呼叫的 tokens（含思考）與時間 | — | 更新 §4.7 的估算；必要時調整預設上限 |
| 思考程度 | 每種呼叫比較低與高兩種思考程度的品質、tokens 與時間 | — | 決定每種呼叫的預設值 |

## 3. 已確認的決定

| 項目 | 決定 |
|---|---|
| 模型 | LLM 與 VLM 都用 `gemini-3.8-flash`（穩定版，有免費額度）。模型 ID 由 `GEMINI_LLM_MODEL`、`GEMINI_VLM_MODEL` 設定 |
| SDK | 官方 `google-genai`（Python，async 的 `client.aio`），版本固定在 `pyproject.toml` 與 `uv.lock`。重試與逾時由我們自己包一層，符合第二階段規格 §4.4 |
| API key | repo 根目錄的 `.env`（`GEMINI_API_KEY`，不進 git）。docker compose 傳給 api 與 worker；系統狀態只顯示末 4 碼；log、事件與錯誤訊息一律遮蔽 key |
| 測試 | 任務流程用假的 Gemini client；client 本身用錄製的 HTTP 回應（respx）；真 API 只在 `pytest -m live` 手動執行。live E2E 用 `AGENT_MODE=sim`，不需要 key |
| 費用上限 | 單一任務 US$1、每月 US$20（台北時間的月份），都可以在 `.env` 調整，設為 0 表示不設上限 |
| 版面調整 | Gemini 以預設版型為起點輸出 8 個元素的 BBox，程式驗證；不合法時帶著錯誤重問一次，仍不合法就退回預設版型 |
| 文案缺字 | emoji 與裝飾符號由程式直接移除；其他缺字列出來請 Gemini 重寫一次；仍缺字的欄位改用預設文案，並在 Agent 透視顯示警告 |
| 切換 | `AGENT_MODE=gemini｜sim`，LLM 與 VLM 一起切換；`gemini` 需要 `REVIEW_MODE=composer` |
| 護欄的位置 | composer 的 `POST /spec`（TypeScript）：與審查共用同一套文案與幾何函式，判斷結果才會一致 |
| VLM 的輸入 | 不提供預期文案，避免轉錄被預期文案帶偏（修改第二階段規格 §5.7） |

## 4. 架構

### 4.1 切換與元件

| `AGENT_MODE` | `REVIEW_MODE` | Agent | 審查 |
|---|---|---|---|
| `gemini`（預設） | `composer` | `GeminiAgent` | `GeminiReviewer`：Gemini VLM 加上 composer 的 `/review` |
| `sim` | `composer` | `SimAgent` | `ComposerReviewer`：VLM 三項依內容判斷（與 6A 相同） |
| `sim` | `sim` | `SimAgent` | `SimReviewer` |
| `gemini` | `sim` | 設定錯誤：api 與 worker 啟動失敗並說明原因 | |

- api 的需求拆解（`ApiServices.agent`）也依 `AGENT_MODE` 選擇。
- **未設定 key**：`AGENT_MODE=gemini` 但沒有 `GEMINI_API_KEY` 時，服務照常啟動，以便在系統狀態看到提示。需求拆解與新任務會被拒絕，原因為中文。
- **時間軸**：`AGENT_MODE=gemini` 時，任務流程不再依 1× 時間軸（`PHASE_MS`）等待，因為實際呼叫本身就要時間。模擬生圖的進度照舊依時間軸，Plan 7 換成 ComfyUI。
- **新增檔案**：

| 檔案 | 內容 |
|---|---|
| `backend/app/adapters/gemini.py` | `GeminiClient`：呼叫、重試、取消、用量（4.2） |
| `backend/app/pipeline/gemini.py` | `GeminiAgent`、`GeminiReviewer` |
| `backend/app/pipeline/gemini_types.py` | Gemini 結構化輸出的 Pydantic 模型（`BriefDraft`、`SpecDraft`、`RewriteDraft`、`VlmVerdict`） |
| `backend/app/pipeline/prompts/*.md` | 四種呼叫的提示詞（繁體中文）。放在 .md 檔，方便檢視，也可以作為作品集展示 |
| `backend/app/usage.py` | 單價表、費用計算、用量寫入、上限檢查 |
| `web/src/lib/agent/guard.ts` | `finalizeSpec`：Prompt 構建的程式護欄（4.4） |
| `web/src/lib/compose/glyphs.ts`、`glyphs.json` | 字型涵蓋表、`missingGlyphs`、`stripEmoji`（4.11） |
| `web/src/lib/review/ocr.ts` | `ocrDiffs`（4.6） |
| `web/src/types/agent.ts` | `SpecDraft`、`VlmVerdict`、`GuardIssue`（對應 `gemini_types.py`） |

### 4.2 Gemini client（`backend/app/adapters/gemini.py`）

`GeminiClient.generate(kind, model, parts, schema, scope, run) -> T`：
1. **檢查費用上限**（4.7）。超過時不送出，直接丟出錯誤。
2. **送出**：
   - `response_mime_type` 為 `application/json`，`response_json_schema` 由 Pydantic 模型產生；
   - 系統指示與思考程度依 `kind`（`brief`、`spec`、`rewrite`、`vlm`）而定，思考程度由實驗決定，寫在程式常數；
   - 傳入任務的 seed，盡量讓結果可以重現（不保證）。
3. **驗證**：以 Pydantic 驗證回應。
   - 失敗時，把這次的回應與中文化的錯誤訊息（見 §8）接在對話後面，重問一次；
   - 仍失敗時任務失敗，原因例如「Gemini 回應格式錯誤（Prompt 構建）：layout.3.bbox：必須有 4 個數字」。
4. **用量**：每個有回應的請求（包括格式錯誤的那次）都寫一筆 `job_usage`，並送出一則 `log`。

**錯誤處理**：

| 情況 | 處理 |
|---|---|
| 429、5xx、逾時（每次請求 60 秒） | 指數退避重試 3 次（1、2、4 秒，±20% 抖動）。429 附有建議的等待時間時採用該值，最長 60 秒 |
| 400（請求錯誤）、401／403（key 無效或沒有權限）、404（找不到模型） | 不重試，原因為中文，例如「Gemini API key 無效或沒有權限」「找不到 Gemini 模型：gemini-x」 |
| 安全性過濾（提示詞被擋，或回應因安全性停止） | 不重試，原因為「Gemini 拒絕產生內容（安全性過濾）」 |
| 超過費用上限 | 不送出，原因見 4.7 |

**取消**（6A §8 的「可取消的等待」）：
- 等待回應與退避都經過 `run.wait()`，每 0.5 秒檢查取消旗標，與第二階段規格 §4.3 等待 ComfyUI 的做法相同。
- 取消時中斷進行中的 HTTP 請求，並送出 `job.status cancelled`。
- 中斷的請求拿不到用量，不寫入 `job_usage`。Google 仍可能對這次呼叫計費，所以送出警告 log：「已中斷進行中的 Gemini 呼叫，這次呼叫可能仍會計費（未記錄用量）」。

**其他**：
- **並行**：每個 worker 共用一個 semaphore，同時最多 `GEMINI_CONCURRENCY`（預設 4）個呼叫。
- **key**：只在建立 SDK client 時使用。錯誤訊息在輸出前把 key 字串換成 `***`。

### 4.3 需求拆解（`POST /api/briefs/parse`）

**輸入**：
- 品牌：名稱、類別、預設語氣，以及 4 種語氣的說明（溫柔療癒、專業科研、活潑年輕、簡約）；
- 商品：名稱與特色（沒有選商品時省略）；
- 使用者的一句話需求。

**輸出 `BriefDraft`**：

| 欄位 | 限制 |
|---|---|
| `sellingPoints` | 0–3 個 |
| `audience` | ≤ 20 字 |
| `tone` | `gentle`、`science`、`playful`、`minimal` |
| `campaign`、`offer`、`period` | 需求有提到才填，否則為 `null` |
| `style` | 0–5 個英文小寫單字 |

**護欄**：
- `productName` 取自商品資料，沒有商品時為 `null`；
- `sellingPoints` 為空時，改用商品特色的前 3 個；
- 需求文字不含任何數字時，`period` 一律為 `null`；
- `style` 只保留英文單字，轉小寫並去除重複。

**其他行為**：
- 用量的 `job_id` 為 `null`（還沒有任務），`kind` 為 `brief`。
- 整個請求最多等 90 秒；逾時或 Gemini 失敗時回 503（`unavailable`），超過費用上限時回 429（`budget_exceeded`），訊息皆為中文。
- 任務的 `parsing` 階段沿用表單確認過的 `parsedBrief`，與現在相同，不呼叫 Gemini。

### 4.4 Prompt 構建（每個模板每輪一次）

**輸入**：
- 品牌：名稱、類別、色票、字型、視覺風格、本次語氣的預設文案（當作範例）、禁用詞、替代用語、效果宣稱詞、註記用語、版面規則（商品佔比、留白、Logo 淨空區）。
- 商品：名稱、特色、售價、原價、商品圖的長寬比。有去背圖時取不透明區域的外框；範例商品用 SVG 的尺寸。
- 需求：使用者的一句話與 `ParsedBrief`。
- 模板：尺寸、比例、預設版型（composer `/layout`）。
- 檢索：實際引用的切塊全文，即 Rerank 後前 5 筆，加上重新檢索的切塊。
- 重試時：上一輪的文案與版面、未通過的檢查（名稱、規則、數值）、Query Rewriting 的修正項。

**輸出 `SpecDraft`**（長度以視覺寬度計：中文 1、英數 0.58，與 `visLen` 相同）：

| 欄位 | 限制 |
|---|---|
| `headline` | 2 行，每行 ≤ 8 |
| `subhead` | ≤ 22 |
| `features` | 0–3 個，各 ≤ 12 |
| `badge.top`、`badge.main` | 各 ≤ 6 |
| `badge.sub` | 英文大寫、數字與空白，≤ 16 字元 |
| `priceLabel` | ≤ 8 |
| `layout` | 8 個元素各一個 `[x, y, w, h]`（畫布像素）。不輸出 `z` |
| `scene` | 英文的生圖場景描述，≤ 300 字元 |
| `negativeExtra` | 英文，≤ 200 字元 |
| `rationale` | 一句中文，說明版面與文案的想法，≤ 60 字（顯示在 Agent 透視的 log） |

**程式護欄**（composer `POST /spec`，`finalizeSpec(draft, request) -> { spec, issues }`）：

每個問題記為一筆 `GuardIssue { code, field, message, retry }`。`retry` 為 true 的問題會觸發重問。

| # | 範圍 | 規則 | 問題代碼（重問） |
|---|---|---|---|
| 1 | 文案 | 所有 Gemini 寫的欄位都套用品牌的替代用語（每一輪都套，不只重試時） | — |
| 2 | 文案 | emoji 與裝飾符號直接移除 | `emoji_removed`（否） |
| 3 | 文案 | 不在字型涵蓋表的字 | `missing_glyph`（是） |
| 4 | 文案 | 套用替代用語後仍有禁用詞 | `banned_word`（是） |
| 5 | 文案 | 超過長度上限 | `too_long`（是） |
| 6 | 文案 | `brief.offer` 有值時，`badge.main` 固定為 offer；文案出現需求裡沒有的價格或優惠（折扣、買幾送幾、金額、百分比） | `invented_offer`（是） |
| 7 | 文案 | 標題兩行或徽章主文空白 | `empty_field`（是） |
| 8 | 文案 | 色票、售價、原價、商品名稱、註記由程式決定（註記與 `buildCopy` 相同：效果宣稱、活動期間、數量有限） | — |
| 9 | 文案 | 商品名稱是使用者資料：emoji 移除，其他缺字保留並警告 | `product_glyph`（否） |
| 10 | 版面 | 8 個元素各一次、整數、完全在畫布內、彼此不相交 | `layout_invalid`（是） |
| 11 | 版面 | 商品佔比、留白、Logo 淨空區：與 `product_ratio`、`whitespace`、`logo_clearance` 三項規則用同一套函式判斷 | `layout_rule`（是） |
| 12 | 版面 | 以實際文案計算字級：標題 ≥ 畫布短邊 4%，其他文字 ≥ 1%（實驗決定） | `text_too_small`（是） |
| 13 | 版面 | 圖層順序由程式指定（product 1、badge 3、其他 2） | — |
| 14 | 提示詞 | 正向提示詞＝程式固定的開頭（比例、商品攝影、提供的商品照）＋ `scene` ＋ 品牌視覺風格 ＋ 色票 ＋ `brief.style` ＋ 程式固定的結尾（排版留白、打光）。`scene` 含非英文時視為不合法 | `prompt_invalid`（是） |
| 15 | 提示詞 | 負向提示詞＝`BASE_NEGATIVE` ＋ 依先前未通過檢查加入的詞（`NEGATIVE_BY_FIX`）＋ `negativeExtra`，去除重複 | — |
| 16 | 提示詞 | `injection` 由 `buildInjection` 產生；`ragRefs` 為放進提示詞的切塊 id | — |

**重問與退回**：
- 第一次的 `issues` 中有 `retry` 的問題時，把問題說明接在對話後面重問一次。說明為中文，例如：
  - 「標題第 1 行『…』有伺服器字型沒有的字：『后』，請改用繁體字」；
  - 「商品框佔畫面 28.0%，品牌規範為 40%–60%」。
- 第二次的結果直接使用，仍有問題的部分改用預設：
  - 文案欄位改用預設文案，產生方式與 `buildCopy` 相同；
  - 版面改用預設版型（`computeLayout`）；
  - `scene` 改用模擬版的提示詞句型。
- 每個問題以 `log`（agent，warn）顯示，例如「護欄：標題第 1 行有伺服器字型沒有的字『后』，已改用預設文案」。
- 一個 spec 最多呼叫 2 次 Gemini（每次另外可能有 1 次格式重問）。
- 預設版型可能不符合品牌的商品佔比（6A §12）。這時審查的 `product_ratio` 不通過，下一輪 Gemini 會收到未通過的檢查與數值，再調整一次。
- 預設文案含缺字或禁用詞時照用（這是品牌設定檔的問題），由系統狀態提醒（4.11）。

### 4.5 Query Rewriting（每個未通過的模板一次）

**輸入**：
- 該模板最高分候選的未通過檢查：名稱、規則、數值、目標元素；
- 這些檢查引用的規範全文；
- 上一輪的文案與版面；
- 品牌的替代用語；
- 目前輪次與剩下的重試次數。

**輸出 `RewriteDraft`**：
- `fixes`：`[{ checkId, title, desc }]`，`title` ≤ 8 字，`desc` ≤ 80 字；
- `requery`：需要重新檢索合規用語時的查詢，不需要時為 `null`。

**護欄**：
- `checkId` 不是未通過的檢查時移除。
- 每個未通過的檢查至少要有一個修正。Gemini 沒給的，以 `planFixes`（composer `/fixes`）補上。同一個檢查有多個修正時合併為一個。
- `banned_words` 或 `vlm_exaggeration` 未通過、而 `requery` 為 `null` 時，改用 `{類別} 禁用詞 合規替代用語`（與模擬版相同）。
- 一個任務仍只重新檢索一次（runner 現有的邏輯）。

**其他**：
- 同一輪的多個模板並行，上限與 4.2 相同。
- 下一輪的 Prompt 構建會收到 `PreviousRound`（4.8）。
- `rewrite.started` 的事件格式不變。

### 4.6 VLM 審查

**`GeminiReviewer.review(brand, render, seed, poster, run)`**：
1. 讀取排版階段存的審查用海報 PNG。
2. 呼叫 VLM（`kind = vlm`）。
3. 以 VLM 結果呼叫 composer 的 `/review`，得到 10 項檢查與分數。

**輸入**：
- 海報：模板原尺寸（長邊 1600–2048 像素）。是否縮小由實驗決定。
- 品牌：類別、禁用詞、效果宣稱詞、註記用語。
- 版面：8 個元素的中文名稱與方框，換算成送出圖片的座標。
- **不提供預期文案**：轉錄要讀畫面上實際的字。給了預期文案，VLM 容易照抄，`ocrDiffs` 就抓不到錯字。

**輸出 `VlmVerdict`**：

| 欄位 | 內容 |
|---|---|
| `lines` | 畫面上所有文字，依閱讀順序一行一筆。看不清楚的字寫成「?」，方塊或無法辨識的符號寫成「□」 |
| `exaggeration` | `{ status, phrases, reason }`：誇大或療效宣稱，依品牌類別判斷，不限於禁用詞 |
| `occlusion` | `{ status, elements, reason }`：文字或 Logo 被遮住、彼此重疊、與商品重疊 |
| `quality` | `{ status, issues, reason }`：構圖、光線、瑕疵、文字可讀性 |

`status` 為 `pass`、`warn` 或 `fail`；`reason` ≤ 60 字。

**三項檢查**（`geminiVlmChecks(verdict, spec, brand)`，`web/src/lib/review/vlm.ts`）：

| 檢查 | 說明文字（value） | target | ragRef |
|---|---|---|---|
| `vlm_exaggeration` | 通過：「未發現誇大用語」；否則「偵測到「…」「…」：理由」 | 文案含該片語的第一個元素，找不到時為 `null` | `law` |
| `vlm_occlusion` | 通過：「無重疊遮擋」；否則「元素中文名：理由」 | `elements` 的第一個 | 有 Logo 時為 `logo`，否則為 `layout` |
| `vlm_quality` | 通過：「構圖與畫質良好」；否則列出問題 | `null` | `null` |

- 名稱與 `rule` 文字不變，說明文字不再有「模擬」字樣。
- `contentVlmChecks` 保留，給 `AGENT_MODE=sim` 使用。

**`ocrDiffs`**（`web/src/lib/review/ocr.ts`）：
1. **預期文字**：`scene.ts` 實際繪製的每一段文字，依元素分組。包括價格的「NT$」、原價、按鈕文字、向量 Logo 的字標。
2. **正規化**：NFKC、移除空白與標點符號（「□」「?」除外）、英文轉小寫。
3. **比對**：每段文字在轉錄全文（各行相連）中，找編輯距離最小的子字串（semi-global alignment）。距離的總和就是差異數。
4. **方塊**：轉錄含「□」時，視為畫面有無法顯示的字。
5. **略過小字**：換算到送出圖片後，字級小於門檻（預設 14 像素，實驗決定）的段落不比對。
6. **判定**（實驗決定）：
   - 0 處：pass；
   - 1 處：warn（VLM 可能讀錯一個字）；
   - 2 處以上，或有方塊：fail。
7. **說明文字**：例如「1 處差異（標題「透亮」讀成「透高」）」「畫面有無法顯示的字（方塊）」。target 為差異最多的元素。
8. **介面**：`runRuleChecks` 的 `ocrDiffs?: number` 改為 `ocr?: OcrResult`。沒有傳入時，結果與現在相同（「0 處差異」、pass、target 為 headline），所以模擬模式與 golden fixtures 不變。

**其他行為**：
- **並行**：同一輪的審查並行，上限為 `GEMINI_CONCURRENCY`。事件依候選順序送出：前面的候選審查完就送，不必等整輪。
- **失敗**：VLM 呼叫失敗（重試後）時任務失敗，原因為「Gemini 無法審查海報：…」。

### 4.7 用量與成本

**`job_usage` 資料表**（新的 Alembic migration）：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | bigserial | 主鍵 |
| `job_id` | text，可為空 | 參照 `jobs.id`，ON DELETE CASCADE。需求拆解時為空 |
| `brand_id` | text | |
| `created_at` | timestamptz | 有索引 |
| `provider` | text | `gemini`（Plan 7 加上 `comfyui`） |
| `model` | text | |
| `kind` | text | `brief`、`spec`、`rewrite`、`vlm` |
| `round` | int，可為空 | |
| `target` | text，可為空 | 模板 id（spec、rewrite）或候選 id（vlm） |
| `input_tokens`、`cached_tokens` | int | `cached_tokens` 是輸入中命中隱式快取的部分 |
| `output_tokens`、`thinking_tokens` | int | `output_tokens` 包含思考（計費方式相同），`thinking_tokens` 另外記錄 |
| `seconds` | float，可為空 | Plan 7 的 GPU 秒數 |
| `cost_usd` | numeric(12,6) | 寫入時依當時的單價計算，之後單價改變也不影響舊紀錄 |

**單價表**（repo 根目錄的 `pricing.yaml`，與 `brands/` 一樣以唯讀方式掛載）：

```yaml
# Gemini 單價（美元／每百萬 tokens），依 Google AI Studio 公告；from 為生效日（台北時間）
# cachedInput 省略時與 input 相同（保守估計）
gemini-3.8-flash:
  - {from: 2026-01-01, input: 0.75, output: 3.75}
  - {from: 2027-01-01, input: 1.50, output: 7.50}
```

- 以 Pydantic 驗證。設定使用的模型不在表內時，系統狀態顯示錯誤，所有 Gemini 呼叫都被拒絕（沒有單價就無法套用上限）。
- **費用**＝［（輸入 − 快取）× input ＋ 快取 × cachedInput ＋ 輸出 × output］÷ 1,000,000，四捨五入到小數 6 位。

**上限**（只在 `AGENT_MODE=gemini` 時生效）：
- **單一任務**：每次呼叫前加總該任務的 `cost_usd`，達到 `GEMINI_JOB_BUDGET_USD` 時任務失敗，原因為「已達單一任務的 Gemini 費用上限（US$1.00，已用 US$1.02）」。
- **每月**：每次呼叫前加總台北時間當月的全部紀錄（含需求拆解），達到 `GEMINI_MONTHLY_BUDGET_USD` 時：
  - 進行中的任務在下一次呼叫時失敗；
  - `POST /api/jobs` 與需求拆解回 429（`budget_exceeded`），訊息為「本月 Gemini 費用已達上限（US$20.00）」。
- **誤差**：上限在呼叫前檢查，最多超出並行中的呼叫的費用（約 4 次呼叫）。
- **設為 0**：不設上限。

**顯示**：
- 每次呼叫送出一則 `log`（agent 或 vlm），例如「gemini-3.8-flash：輸入 4,120（快取 0）／輸出 1,032（思考 640）tokens・US$0.0070」。
- `saving` 階段送出本任務的合計，例如「本任務 Gemini 費用 US$0.18（17 次呼叫）」。
- **儀表板**：
  - Python 的 `dashboard_stats(snaps, usage_costs=None)` 新增 `usage_costs` 參數。live 的 `/api/stats` 傳入每個任務的 `job_usage` 加總，沒有紀錄的任務（例如模擬模式）為 0。
  - 不傳入時，仍依事件估算，與 TypeScript 的結果相同，所以 parity 測試不變。
  - mock 的前端照舊估算。
  - 前端的「每張成本」標示：live 為「依實際用量」，mock 為「估算」。
- **系統狀態**：顯示當月費用與上限（4.10）。

**估算**（實驗後更新）：

假設每次呼叫：拆解為輸入 1.5k、輸出 0.5k；Prompt 構建為輸入 5k、輸出 2.5k；VLM 為輸入 3k、輸出 2k；改寫為輸入 3k、輸出 1.8k。輸出都含約 1k 的思考 tokens。

| 任務 | 呼叫 | 目前單價 | 2027-01 起 |
|---|---|---|---|
| 一般：3 個模板 × 2 張，第一輪 2 個模板未通過，第二輪通過 | Prompt 5、VLM 10、改寫 2 | 約 US$0.18 | 約 US$0.36 |
| 最大：5 個模板 × 2 張 × 3 輪，全部未通過 | Prompt 15、VLM 30、改寫 10 | 約 US$0.58 | 約 US$1.16（超過預設的單一任務上限） |

每月 US$20 約為 110 個一般任務（2027 年起約 55 個）。

**免費方案**：
- Google 可能用免費方案的輸入（包括商品照與海報）改善產品，並可能由人工審閱。未發表的商品請用付費方案的 key。README 會說明這一點。
- 免費方案實際不收費，但 `job_usage` 仍依付費單價記錄，上限照樣生效。

### 4.8 任務流程的修改

**介面**（`backend/app/pipeline/ports.py`）：

| 項目 | 修改 |
|---|---|
| `RunContext` | 新增 `job_id`，以及 `wait(awaitable)`：可取消的等待，每 0.5 秒檢查取消旗標 |
| `PreviousRound`（新增） | `spec`、`checks`、`fixes`：某個模板上一輪最高分候選的 spec、檢查結果與修正項 |
| `SpecRequest` | 新增 `hits: list[RagHit]`（ragRefs 對應的切塊全文）與 `previous: PreviousRound \| None` |
| `Agent` | `build_spec(request, run)`、`plan_rewrite(brand, spec, checks, run)` 多一個 `run`；`parse_brief` 不變 |
| `Reviewer` | `review(brand, render, seed, poster, run)` 多一個 `run` |

**runner**（`backend/app/pipeline/runner.py`）：
- **Prompt 構建**：同一輪的模板並行；`prompt.generated` 依模板順序送出。
- **審查**：同一輪的候選並行；事件依候選順序送出。
- **重試**：保存每個未通過模板的 `PreviousRound`，傳給下一輪的 `SpecRequest`。
- **時間軸**：`AGENT_MODE=gemini` 時跳過 `PHASE_MS` 的等待（4.1）。
- **模擬版**：`SimAgent`、`SimReviewer`、`ComposerReviewer` 接受新參數但不使用，事件與現在完全相同。

**選用**：`build_services` 依 `AGENT_MODE` 與 `REVIEW_MODE` 選擇 Agent 與 Reviewer（4.1 的表）。

### 4.9 composer 端點

| 端點 | 輸入 | 輸出 |
|---|---|---|
| `POST /spec`（新增） | `{ draft: SpecDraft, request }`。`request` 為 `SpecRequest` 的 JSON，品牌已精簡（§8） | `{ spec: PromptSpec, issues: GuardIssue[] }` |
| `POST /review` | 新增 `vlm: VlmVerdict \| null`。有值時，VLM 三項用 `geminiVlmChecks`，並計算 `ocrDiffs`；`null` 時與 6A 相同 | 不變 |
| `POST /fixes`（新增） | `{ checks, brand, spec }` | `Fix[]`（`planFixes`，與 `/sim/fixes` 相同） |
| `POST /glyphs`（新增） | `{ texts: string[] }` | `{ missing: string[][] }`：每段文字缺少的字 |

`SpecDraft`、`VlmVerdict`、`GuardIssue` 在 `web/src/types/agent.ts` 與 `backend/app/pipeline/gemini_types.py` 各定義一次，以 golden fixtures 確認一致。

### 4.10 前端

- **合約**：型別都不變。
  - `ApiOptions` 的 `llm`、`vlm` 在 `AGENT_MODE=gemini` 時是實際的模型 ID（`gemini-3.8-flash`）；
  - 模擬模式的名稱不變，與 mock 相同。
- **系統狀態**的「Gemini（LLM／VLM）」改為實際檢查：
  - `AGENT_MODE=sim`：狀態為「模擬」，說明為「AGENT_MODE=sim：模擬 Agent 與 VLM 審查」；
  - 未設定 key：異常，「未設定 GEMINI_API_KEY：在 .env 加入後重新啟動 api 與 worker，或設 AGENT_MODE=sim」；
  - key 無效、找不到模型、單價表沒有該模型：異常，說明原因；
  - 正常：「LLM／VLM gemini-3.8-flash・本月 US$1.23／上限 US$20・key …a1B2」；
  - 以 `models.get` 檢查 key 與模型（不計費），結果快取 60 秒。
- **儀表板**：每張成本的標示依模式不同（4.7）。
- **審查面板**：VLM 三項顯示 Gemini 的判斷；`ocr_typo` 顯示差異說明。
- **`SIMULATED_VLM_NOTE`**：改為「（模擬：AGENT_MODE=sim）」。
- **需求拆解按鈕**：等待時顯示進行中，失敗時顯示 API 回傳的中文訊息。

### 4.11 字型涵蓋表

- **`glyphs.json`**：兩個海報字型（Noto Sans TC、Noto Serif TC）都涵蓋的字元，以 Unicode 區段列表儲存。
  - 由 `npm run glyphs` 從 6A 固定版本的字型檔產生，並進 git。字型以 SHA-256 固定，所以這份表不會變。
  - Vitest 在有字型時確認表與字型檔一致，沒有字型時略過。
- **函式**：
  - `missingGlyphs(text)`：不在表內的字（空白除外）；
  - `stripEmoji(text)`：移除 Extended_Pictographic、變體選擇符、ZWJ、keycap、膚色修飾符與區域指示符號。
- **品牌設定檔檢查**：系統狀態的「品牌設定檔」以 composer `/glyphs` 檢查預設文案、註記用語、替代用語。有缺字時在說明加上警告，不改變狀態，也不擋任務。

## 5. 模擬模式（`AGENT_MODE=sim`）

- `SimAgent` 不變。審查依 `REVIEW_MODE` 使用 `ComposerReviewer`（VLM 三項依內容判斷）或 `SimReviewer`。
- 不寫 `job_usage`，live 儀表板的成本為 0。
- golden timelines、parity 測試、mock（作品集 Demo）都不變。

## 6. 設定

| 變數 | 預設 | 說明 |
|---|---|---|
| `AGENT_MODE` | `gemini` | `gemini` 或 `sim`。`gemini` 需要 `REVIEW_MODE=composer` |
| `GEMINI_API_KEY` | （空） | 放在 repo 根目錄的 `.env` |
| `GEMINI_LLM_MODEL` | `gemini-3.8-flash` | 需求拆解、Prompt 構建、Query Rewriting |
| `GEMINI_VLM_MODEL` | `gemini-3.8-flash` | 審查 |
| `GEMINI_TIMEOUT_SECONDS` | `60` | 每次請求的逾時 |
| `GEMINI_MAX_RETRIES` | `3` | 429、5xx、逾時的重試次數 |
| `GEMINI_CONCURRENCY` | `4` | 每個 worker 同時進行的呼叫數 |
| `GEMINI_JOB_BUDGET_USD` | `1` | 單一任務上限，0 為不設 |
| `GEMINI_MONTHLY_BUDGET_USD` | `20` | 每月上限（台北時間），0 為不設 |
| `PRICING_FILE` | `pricing.yaml`（Docker 內為 `/app/pricing.yaml`） | 單價表 |

- 現有的 `llm_model`、`vlm_model` 只在 `AGENT_MODE=sim` 時作為選項名稱。
- `docker-compose.yml`：api 與 worker 共用的環境加上上表的變數，並以唯讀方式掛載 `pricing.yaml`。
- `.env.example`：加上上表的變數與中文說明。

## 7. 測試

**pytest**：
- **`GeminiClient`**：以 respx 重播錄製的回應（存在 `backend/tests/data/gemini/`），涵蓋：
  - 結構化輸出的解析；
  - 用量（含快取與思考 tokens）；
  - 429 後成功、5xx 超過次數後失敗；
  - 格式錯誤時帶著錯誤重問；
  - 安全性過濾；401、404 的中文原因；逾時；
  - 取消時中斷請求；
  - key 不會出現在任何錯誤訊息與 log。
- **錄製回應**：`backend/scripts/record_gemini.py`，手動執行、需要 key。呼叫一次真 API，存下回應，並移除 key 與無關的標頭。
- **`FakeGemini`**：依呼叫種類回傳預先寫好的結果，並記錄收到的請求。以它測試 gemini 模式的任務流程：
  - 事件順序；
  - 護欄的重問與退回；
  - 並行審查的事件順序；
  - 費用上限；
  - Gemini 呼叫中取消。
- **用量**：單價的生效日、快取 tokens、費用計算、每月加總的時區邊界、上限檢查。
- **API**：需求拆解、系統狀態、`POST /api/jobs` 的拒絕條件（沒有 key、超過每月上限）、驗證訊息的中文化。
- **儀表板**：有 `job_usage` 時用實際費用；不傳 `usage_costs` 時 parity 不變。
- **設定**：`AGENT_MODE=gemini` 加 `REVIEW_MODE=sim` 時為設定錯誤。測試的 `Settings` 一律明確設定 `AGENT_MODE`。

**`pytest -m live`**（手動）：
- 從環境變數或 `.env` 讀 `GEMINI_API_KEY`（只讀這一個值），沒有時略過。
- 需求拆解、Prompt 構建、VLM 審查（composer 繪製的海報）各呼叫一次。只檢查格式與護欄，不比對內容。

**Vitest**：
- `finalizeSpec`：§4.4 的每條護欄與退回；
- 字型涵蓋表與字型檔一致（沒有字型時略過）、`missingGlyphs`、`stripEmoji`；
- `ocrDiffs`：正規化、子字串比對、方塊、略過小字、判定門檻；
- `geminiVlmChecks`；
- `/spec`、`/review`（含 `vlm`）、`/fixes`、`/glyphs` 端點。

**golden fixtures**：模擬模式不變。新增 `SpecDraft`、`VlmVerdict`、`GuardIssue` 的範例，供 pytest 解析。

**E2E**：mock 照舊；live E2E 使用 `AGENT_MODE=sim`（§8）。

## 8. 併入的 Plan 6 延後項目

6A §8 只列出名稱。以下依目前的程式解讀並處理：

- **`Brand.guidelineChunks` 的大小**：
  - 問題：品牌含上傳的手冊與歷史回寫時，最多可達 2,000 個切塊，現在每次呼叫 composer 都整份送出。
  - 送給 composer 的品牌只保留每個 tag 第一個非 `-alt` 的切塊。`ragRefFor` 只用到這些，所以結果與現在相同。
  - Gemini 的提示詞只放實際引用的切塊全文（`SpecRequest.hits`），不放 `guidelineChunks`。
  - `/api/brands` 照舊回傳全部切塊（知識庫頁面要用）。
- **可取消的等待**：Gemini 的呼叫與退避都經過 `run.wait()`（4.2、4.8）。
- **e2e 的 `GEMINI_API_KEY`**：`docker-compose.e2e.yml` 明確設定 `AGENT_MODE: sim` 與 `GEMINI_API_KEY: ""`，開發者 `.env` 裡的 key 不會進到 E2E 的容器。
- **驗證訊息的中文化**：
  - `_describe` 依 Pydantic 錯誤的 `type` 轉成中文，例如：
    - `missing`：缺少欄位；
    - `literal_error`：必須是 …；
    - `too_long`、`too_short`：長度必須在 … 之間；
    - `greater_than_equal`：必須 ≥ …。
  - 自訂的 `value_error` 本身已是中文，只去掉「Value error, 」開頭。沒有對應的類型保留原文。
  - 位置改為 JSON 欄位路徑，去掉開頭的 `body.`。
  - API 的 400 回應與 Gemini 的格式錯誤（4.2）共用這個函式。

## 9. 驗收

1. 在 `.env` 設定 key 後執行 `docker compose up -d --build`：
   - 系統狀態的 Gemini 為正常，顯示模型、本月費用與上限、key 末 4 碼；
   - 移除 key 後顯示中文提示。
2. 新任務以一句話需求拆解：欄位由 Gemini 產生，`job_usage` 多一筆 `kind=brief`。
3. 三個品牌（SÉLUNE、misty-isle、Kayla 精緻少女）各跑一個任務（3 個模板 × 2 張）：
   - Agent 透視的 Prompt 是 Gemini 產生的文案與版面，護欄做的調整以警告顯示；
   - VLM 三項的說明沒有「模擬」字樣；正確海報的 `ocr_typo` 為 0 處差異；
   - 每次 Gemini 呼叫都有用量 log；任務結束時的合計等於 `job_usage` 的加總；儀表板的每張成本依實際用量。
4. **版面**（6A §12）：把一個品牌的 `productRatio` 暫時改為 `[0.4, 0.6]`，5 個模板都有候選通過 `product_ratio`（必要時經過重試）。
5. **缺字**：需求要求加上 emoji，或用簡體字撰寫時，審查用海報沒有方塊，Agent 透視顯示護欄的警告。
6. **取消**：Gemini 呼叫進行中按下取消，1 秒內任務變成已取消。
7. **上限**：
   - `GEMINI_JOB_BUDGET_USD=0.01` 時，任務失敗，原因為中文；
   - `GEMINI_MONTHLY_BUDGET_USD` 低於當月費用時，新任務與需求拆解被拒絕。
8. **測試**：後端、前端、mock E2E、live E2E（`AGENT_MODE=sim`）全部通過；`pytest -m live` 手動執行通過。

## 10. 對第二階段規格的修改

- **§2**：「LLM／VLM」加上預設模型 `gemini-3.8-flash`。
- **§3.2**：`LlmAgent` 與 `VisionReviewer` 以 `AGENT_MODE` 一起切換；`VisionReviewer` 的真實版需要 `REVIEW_MODE=composer`。
- **§4.4**：錯誤處理加上 4xx、安全性過濾與費用上限；等待 Gemini 時每 0.5 秒檢查取消。
- **§5.1**：加上需求拆解的護欄（本規格 4.3）。
- **§5.3**：
  - 護欄改放在 composer 的 `/spec`；
  - 新增文案缺字、優惠事實、禁用詞、字級的護欄；
  - 版面驗證與三項版面規則共用同一套函式；
  - 有問題時重問一次，仍不合法再退回預設。
- **§5.4**：修正項由程式補齊；禁用詞或誇大用語未通過時一定重新檢索。
- **§5.6**：`ocrDiffs` 改為 4.6 的定義（正規化、方塊、略過小字、判定門檻）。
- **§5.7**：
  - VLM 不提供預期文案；
  - 圖片解析度由實驗決定；
  - 輸出改為 4.6 的 `VlmVerdict`。
- **§5.8、§6.1**：
  - `job_usage` 改為 4.7 的欄位，`job_id` 可為空；
  - 單價表為 `pricing.yaml`；
  - 加上單一任務與每月的上限。
- **§14**：Gemini 的模型 ID 與單價已決定（本規格 §3、4.7）。

## 11. 不做

- **明確的 context caching**：每次呼叫的提示詞大多不同，能共用的部分不大，還要另付每小時的儲存費用。隱式快取命中的 tokens 照樣記錄。
- **Batch API**：便宜 50%，但非同步，不適合互動流程。
- **Gemini 看商品照片寫文案**：只提供商品圖的長寬比。
- **文字編輯器改文案後重跑 VLM 與 OCR**：照現在的做法，沿用生成時的結果。
- **前端顯示 VLM 轉錄全文、每個任務的費用明細頁**。
- **在前端切換多個 Gemini 模型**：選單只有設定的一個。
- **自動判斷免費或付費方案**。
- **版面改由「Gemini 只給參數、程式計算 BBox」**：實驗中版面的合法率太低時，再另外評估。
- **ComfyUI 的 GPU 秒數、背景色系檢查**：Plan 7。

## 12. 實驗結果

### §2 的實驗（2026-10-23，付費方案，`uv run python -m scripts.gemini_experiment all`）

思考程度用預設值（需求拆解 LOW、Prompt 構建 HIGH、Query Rewriting LOW、VLM LOW），VLM 送原尺寸的海報。111 個回應，US$0.88。

| 項目 | 結果 | 通過標準 |
|---|---|---|
| 結構化輸出（3 品牌 × 5 模板 × 2 次） | 格式第一次就通過 30/30；不必重問就通過全部護欄 30/30 | ≥ 95%、≥ 70%：通過 |
| 轉錄（15 張正確的海報） | 0 處差異 15/15 | ≥ 90%、沒有 ≥ 2 處：通過 |
| 抓得到錯字（標題換一個字 15 張、缺字畫成方塊 15 張） | 30/30 有差異；換字的 15 張為 warn（1 處），方塊的 15 張全部 fail | 全部有差異、方塊全部不通過：通過 |
| VLM 判讀（3 品牌 × 正確／Logo 壓標題／副標「三天見效・全台第一」） | 正確海報三項通過 3/3；遮擋 3/3 fail；誇大 3/3 fail（其中 2 張遮擋海報的畫質為 warn） | ≥ 90%、全部抓到：通過 |
| 穩定性（9 張 × 3 次） | 三項狀態一致 9/9 | ≥ 90%：通過 |
| Prompt 構建（HIGH） | 平均輸入 3,123、輸出 4,916（思考 4,402）tokens；平均 38.5 秒、最長 48.3 秒；每次約 US$0.021 | — |
| VLM 審查（LOW） | 平均輸入 2,414（圖片約 1,073）、輸出 377（思考 0）tokens；平均 8.6 秒、最長 32.7 秒；每次約 US$0.0032 | — |

決定：
- 標示「實驗決定」的數值都維持預設：`THINKING`、`VLM_MAX_SIDE = None`、`OCR_MIN_PX = 14`、`OCR_WARN_MAX = 1`、`TEXT_MIN`。
- §4.7 的估算更新：一般任務（Prompt 5、VLM 10、改寫 2、拆解 1）約 US$0.15（2027 年起約 US$0.30）；最大任務（Prompt 15、VLM 30、改寫 10）約 US$0.45（2027 年起約 US$0.90，仍低於預設的單一任務上限 US$1）。
- 沒做：思考程度的低／高比較（現行設定已全部通過，留待需要降低成本或延遲時再做）。
- 待決定：Prompt 構建最長 48 秒，接近 60 秒的逾時（`GEMINI_TIMEOUT_SECONDS`）；高負載時段（見下方）會全部逾時。建議下一個 session 評估把預設提高到 90–120 秒。

**實作時不需要 key 就能確認的結果**：

- **字級護欄的門檻**：徽章英文（`badge.sub`）在預設版型的字級低於畫布短邊的 1%（例如電商主圖 14.3 px、促銷 Banner 9.7 px），所以不列入字級護欄（也低於 OCR 的 14 像素門檻，不比對）。3 個品牌 × 4 種語氣的預設文案在 5 個模板的預設版型都沒有 `layout_invalid` 與 `text_too_small`（`web/src/lib/agent/guard.test.ts`）。
- **轉錄比對的流程**：以 `--offline`（轉錄等於 Python 依文案組出的文字）在 3 個品牌 × 5 個模板執行：正確海報 15/15 為 0 處差異；把標題換掉一個字或放入缺字的 30 張全部有差異。確認 composer 繪製的文字段落（含價格的「NT$」、原價、寬版型的按鈕、向量字標）與比對的預期文字一致。
- **字型涵蓋表**：兩個海報字型都涵蓋的字元共 20,738 個（5,049 個區段）。例：「后」有，「这」「们」沒有。

### 2026-10-23 的實測（免費方案的 key）

| 項目 | 結果 |
|---|---|
| 連線 | `models.get` 正常：`gemini-3.8-flash` 存在，輸入上限 1,048,576、輸出上限 65,536 tokens。`response_json_schema` 的結構化輸出正常 |
| 免費方案的配額 | 每個專案、每個模型每天 20 次 `generateContent`（`GenerateRequestsPerDayPerProjectPerModel-FreeTier`）。一般任務約 18 次呼叫（拆解 1、Prompt 構建 5、VLM 10、改寫 2），所以免費方案每天最多跑一個任務；§2 的實驗也無法在免費方案完成 |
| 延遲 | 當天下午 Gemini 回報「high demand」，503 頻繁。成功的呼叫連簡單問題（輸入 14 tokens）都要 286 秒；需求拆解 125–300 秒，與 `response_json_schema` 無關（完整 schema、簡化 schema、不用 schema 分別為 300、179、178 秒）。60 秒的逾時在這種時候全部逾時。傍晚改用付費方案時恢復正常：三種呼叫合計 60 秒 |
| 思考程度 | `MINIMAL` 不支援（400）。需求拆解用 LOW 時思考為 0 tokens（輸入 582–629、輸出 61–94）；不設思考程度時思考 435 tokens |
| 錄製（付費方案） | `backend/tests/data/gemini/` 的 `brief-ok.json`、`spec-ok.json`、`vlm-ok.json` 換成真的回應。需求拆解（LOW）：輸入 629、輸出 93、思考 0 tokens。Prompt 構建（HIGH）：輸入 2,923、輸出 5,230（思考 4,657）tokens，US$0.0218，第一次就通過護欄。VLM 審查（LOW）：輸入 2,244（其中圖片 1,073）、輸出 373、思考 0 tokens，US$0.0031；轉錄含商品包裝上的字與「NT$ 1,280」這類合併的價格，三項都通過 |
| `pytest -m live`（付費方案） | 通過：需求拆解、Prompt 構建與 VLM 審查各一次，共 60 秒、US$0.0239 |
| 費用 | 免費方案約 15 次呼叫（免費額度內）；付費方案 7 次，約 US$0.05 |

依實測修改的程式：
- 每日配額用完（或 429 建議的等待超過 60 秒）時不重試，任務失敗與需求拆解的原因為中文，例如「Gemini 免費方案今天的請求數已用完（每天 20 次），約 22 小時後恢復；或在 Google AI Studio 為這個 key 的專案啟用付費方案」。原本會以 60 秒的間隔重試 3 次。
- 實驗腳本的各組合改為並行（同時最多 `GEMINI_CONCURRENCY` 個呼叫），並另外記錄每次呼叫的秒數。

待決定：延遲很高的時段 60 秒的逾時（`GEMINI_TIMEOUT_SECONDS`）不夠；是否提高預設值，等付費方案量到正常的延遲再決定。
