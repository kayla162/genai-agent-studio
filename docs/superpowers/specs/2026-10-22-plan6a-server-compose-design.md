# Plan 6A：伺服器端排版與規則審查 設計規格

- 日期：2026-10-22
- 狀態：使用者已逐段同意設計（2026-10-22），待審閱文件
- 相關：`2026-10-07-phase2-backend-design.md`（§5.6、§13）。原本的 Plan 6 拆成兩份計畫：
  - **6A**（本規格）：伺服器端排版與規則審查，不需要 API key；
  - **6B**：Gemini Agent、VLM 審查、用量與成本。

## 1. 目標

Plan 5 之後，10 項審查中有 7 項規則依版型與文案計算，但有兩個缺口：
- **海報只在瀏覽器繪製**：伺服器端沒有任何圖檔，之後的 VLM 審查（6B）沒有圖可看。
- **主色檢查是假的**：「偵測到的主色」是把 palette 的主色混入 1–3% 白色湊出來的（`web/src/lib/api/mock/review.ts`），從未讀過像素。

本規格要完成三件事：
1. composer 在伺服器端畫出與瀏覽器相同的海報，存成審查用海報。
2. 從實際像素量出主色，計算真實的 ΔE2000。
3. 新增 `/review` 端點：live 模式不加隨機分數，VLM 三項在 6B 之前依內容判斷。

模擬模式（測試、作品集 Demo）維持不變。

## 2. 實驗結果（2026-10-22）

### 2.1 字型與 canvas

- **字型**：Google Fonts 的 Noto Sans TC 與 Noto Serif TC 可變字重 TTF，固定在 `google/fonts` commit `45e3d5269e4a17d823f6d84470bc084dc5ae46f6`。
  - 兩個檔案共 28.8 MB，授權 OFL 1.1。
  - 一個檔案涵蓋前端用到的所有字重：Sans 400/500/700、Serif 700/900。來源和前端的 `@fontsource-variable` 相同。
- **涵蓋範圍**：Big5 常用字與次常用字 100%，全形標點、「」『』、。等符號 100%。
  - 不涵蓋簡體專用字與 emoji。這些字在伺服器端會畫成方塊，由 6B 的文案護欄處理。
- **@napi-rs/canvas 1.0.13**：
  - 有 Windows 與 Alpine（musl）的預編譯檔。
  - 1.0.12 起，`ctx.font` 的字重會自動對應可變字型的 `wght` 軸。1.0.10、1.0.11 會畫成細體再加假粗體，不能用。
  - 前端 `paint.ts` 用到的 `letterSpacing`、`filter: blur`、`multiply`、`shadowBlur`、`measureText` 都與瀏覽器一致。
- **效能**：
  - 1080×1350 的海報約 50 毫秒畫完並編碼成 PNG，檔案約 0.3 MB。misty-isle 的 SVG 模糊濾鏡較慢，最多約 250 毫秒。
  - 字型用到時才讀取，Alpine 上只多用約 10–15 MB 記憶體。
- **跨平台**：
  - Windows 與 Alpine 的反鋸齒不同，像素不會完全相同，但 `measureText` 的寬度相同。
  - 這台 Windows 裝了另一版系統 Noto Sans TC，字型高度和我們的檔案不同。所以 composer 先清空系統字型，再註冊我們的檔案。

### 2.2 主色量測

試畫 3 個品牌（SÉLUNE、misty-isle、Kayla 精緻少女）× 5 個模板 × 正確配色與偏色（`applyFlaws`）× 2 個 seed。

**規格原本的量法**（排除商品與文字區塊，取背景面積最大的彩色）：30 張正確配色的海報 **0 張通過**。

**原因**：
- 程式產生的背景是輔助色混入 16–45% 主色的淺色調。
- misty-isle 的主色（C* 11.8）比木紋桌面還不鮮豔。
- Kayla 的 plain 背景完全沒有彩色像素。

**可行做法：量標題、售價、徽章的品牌色元素，取最接近主色的色塊**（見 4.2）。

**結果**：

| 測試條件 | 正確配色 | 偏色 |
|---|---|---|
| 3 個示範品牌，加 3 個壓力測試品牌（深灰 #222222、淺粉 #F2C4CE、薄荷 #BFE3D0） | 180 張全部通過，ΔE 最大 1.5 | 180 張全部不通過，ΔE 最小 11.8 |
| PNG、JPEG q75、±8 雜訊、JPEG q60 加 ±12 雜訊 | 同上 | 同上 |

量一張海報約 7 毫秒（中位數）。

## 3. 已確認的決定

| 項目 | 決定 |
|---|---|
| 計畫拆分 | 6A：伺服器端排版與規則審查（本規格）；6B：Gemini、VLM、用量成本 |
| 架構 | composer 繪製並回傳 PNG，worker 存檔。composer 不寫入任何資料 |
| 圖片來源 | worker 以既有的 `resolve_file` 讀取商品圖與 Logo，連同請求傳給 composer。composer 不掛載任何資料夾，也不必另寫一套路徑檢查（設計確認時原本說由 composer 唯讀掛載，寫文件時改為這個更簡單、更安全的做法） |
| 繪圖邏輯 | 伺服器端直接沿用前端的 `scene.ts`（版面）與 `paint.ts`（繪製），只新增 Node 版的載圖與字型模組，取代瀏覽器專用的 `render.ts` |
| 切換 | 環境變數 `REVIEW_MODE`：`composer`（Docker 預設）或 `sim`（測試與作品集 Demo）。live E2E 使用 `composer` |
| 主色量測 | 量標題、售價、徽章區塊內的品牌色元素，取最接近主色的色塊（見 4.2）。背景色系的檢查留到 Plan 7 |
| VLM 三項（6B 之前） | 依內容判斷：誇大用語看禁用詞、遮擋看 Logo 是否與標題重疊、品質一律通過，說明標示「模擬，Plan 6B 改用 Gemini」。不再依候選編號出現劇本式警告 |
| 分數 | live 模式不加隨機抖動（`scoreChecks(checks, 0)`） |
| 審查用海報 | 存在 `data/jobs/{jobId}/{renderId}.png`；任務透視的審查面板可切換顯示 |
| 字型 | Google Fonts 可變字重 TTF，Docker 建置時下載並核對 SHA-256；本機以 `npm run fonts` 下載到不進 git 的資料夾 |
| Plan 6 延後項目 | 後端測試不再讀取 `.env`（6B 會放入 API key） |

## 4. 架構

### 4.1 composer

**新增檔案**（`web/composer/`）：

| 檔案 | 內容 |
|---|---|
| `fonts.ts` | `registerPosterFonts(dir)`：先 `GlobalFonts.removeAll()`，再以 `Noto Sans TC`、`Noto Serif TC` 註冊兩個字型檔，任一失敗就丟出錯誤 |
| `poster.ts` | `renderPoster(input) -> { png: Buffer, measured: MeasuredPrimary }`。用 `composePoster` 與 `paintScene` 繪製；以 `@napi-rs/canvas` 的 `loadImage` 載入圖片（SVG 先轉成 Buffer）；繪製完成後以 `getImageData` 量主色 |
| `fonts.lock.json`、`scripts/fetch-fonts.mjs` | 字型網址、位元組數、SHA-256；下載並核對到 `web/composer/fonts/`（不進 git）。Dockerfile 與本機共用同一份清單 |

**端點**：

| 端點 | 輸入 | 輸出 |
|---|---|---|
| `POST /render` | `{ render, product, brand, images }`。`render` 是 `Render`（含 spec 與背景）。`images` 是 worker 讀好的圖片：`product`（base64 與 blend）、`logo`（base64），沒有時為 `null` | `image/png`，標頭帶 `X-Measured-Primary`（主色 hex，量不到時為空字串）與 `X-Primary-Share`（佔比） |
| `POST /review` | `{ spec, brand, measuredPrimary: string \| null }` | `{ checks, score, passed }`：7 項規則加 3 項 VLM，分數不加抖動 |

**其他行為**：
- **背景**：`procedural` 用 `backgroundSvg` 產生 SVG；`url` 由 worker 讀成 base64 傳入（6A 用不到，Plan 7 使用）。
- **商品圖**：
  - 範例商品依 `productImage` 產生 SVG；
  - 上傳商品使用去背圖或原圖，`blend` 規則與前端相同。
- **Logo**：沒有圖檔時畫向量標誌，與前端相同。
- **啟動**：伺服器啟動時就註冊字型，失敗就結束行程。`/health` 回報字型已載入。
- **請求大小**：`/render` 的請求本文上限 30 MB，超過時回 400。

### 4.2 主色量測（`web/src/lib/review/measure.ts`，純函式，前端也可使用）

`measurePrimary(pixels: RGBA, width, height, layout, brandPrimary) -> { hex: string | null, share: number, deltaE: number | null }`：

1. **範圍**：`headline`、`price`、`badge` 三個區塊的聯集，扣掉 `product` 區塊。這三個區塊一定會用 `palette.primary` 繪製。
2. **取樣**：以 4×4 像素為一格，取 16 個像素的 sRGB 平均。只取完整的格子，格子中心落在範圍內才採用。用明確的迴圈計算，不用 canvas 縮放，結果才能固定。
3. **轉 Lab**：D65，與 `rgbToLab` 相同。
4. **彩度門檻**：C* ≥ T，T = min(10, 0.5 × 品牌主色的 C*)。中性色主色的 T 接近 0，等於不篩。不設亮度上下限。
5. **分群**：用 Lab 直方圖，不用 k-means。
   - 每格為 (⌊L/3⌋, ⌊a/3⌋, ⌊b/3⌋)。
   - 峰值是原始計數大於或等於所有 26 個相鄰格的格；同分時取索引較小者。
   - 峰值顏色是它周圍 3×3×3 格內所有取樣的 Lab 平均；佔比是這些取樣數除以總取樣數。
6. **候選**：佔比 ≥ 2% 的峰值。
7. **選擇**：與品牌主色 ΔE2000（`deltaEHex`）最小的候選。同分時取佔比大者，再取索引小者。
8. **顯示**：最小 ΔE 超過門檻時，改為回報候選中彩度最高的顏色。判定不變，但說明文字會顯示實際用錯的顏色，例如 `#E0458A`。
9. **沒有候選**：`hex = null`，`color_delta` 判定不通過，說明文字為「未偵測到主色（主色區塊 < 2%）」。

**取捨**：這項檢查確認的是「排版上的品牌色元素有沒有用對色」，不檢查背景圖。程式產生的背景依品牌色繪製，所以沒有問題。Plan 7 換成 AI 生成的照片背景時，要另外新增「背景色系」檢查，標準不能是「與主色 ΔE ≤ 5」，因為正確的程式背景量起來也有 24–53。

### 4.3 規則與 VLM

- `runRuleChecks` 的 `RuleContext.measuredPrimary` 改為 `string | null`。
  - `null` 時，`color_delta` 判定不通過，說明文字為「未偵測到主色（主色區塊 < 2%）」。
  - 其他 6 項規則不變。
- **新的 `contentVlmChecks(spec, brand)`**（`web/src/lib/review/vlm.ts`）：
  - `vlm_exaggeration`：與 `banned_words` 相同的偵測；
  - `vlm_occlusion`：Logo 與標題重疊時不通過，其他情況通過；
  - `vlm_quality`：一律通過。
  - 說明文字都加上「（模擬，Plan 6B 改用 Gemini）」。
  - mock 的 `mockVlmChecks` 保留不變，供模擬模式使用。
- `/review` 的分數為 `scoreChecks(checks, 0)`。

### 4.4 worker 流程

**新的介面 `PosterComposer`**（`backend/app/pipeline/ports.py`）：
- 簽名：`compose(job_id, render, product, brand) -> ComposedPoster | None`。
- `ComposedPoster` 有兩個欄位：`url`（審查用海報的 `/files/...` 網址）與 `measured_primary: str | None`。

**實作**：
- **`ComposerPosters`**（真實）：
  - 以 `resolve_file` 讀商品圖與 Logo；
  - 呼叫 `/render`；
  - 把 PNG 寫到 `data/jobs/{jobId}/{renderId}.png`。
- **`SimPosters`**（模擬）：回傳 `None`。

**流程**：
- **排版階段**（`composing`）：對每張候選呼叫 `compose`。
  - 真實版送出一則 `log` 事件「伺服器端排版 N 張」。
  - 模擬版的事件與目前完全相同。
- **審查階段**：`Reviewer.review(brand, render, seed, poster)` 多一個 `poster` 參數。
  - **`ComposerReviewer`**（真實）：以 `poster.measured_primary` 呼叫 `/review`。
  - **`SimReviewer`**：忽略 `poster`，結果不變。
- **錯誤**：composer 無法連線或回傳錯誤時，任務失敗，原因為中文，例如「排版服務（composer）無法繪製海報：…」。
- **選用**：`build_services` 依 `settings.review_mode` 選擇 `PosterComposer` 與 `Reviewer`。

### 4.5 合約

- `ReviewCompletedEvent` 新增 `image: str | None`，內容是審查用海報的網址。
  - TypeScript 的 `review.completed` 新增 `image: string | null`。
  - 模擬版與 mock 一律為 `null`，golden timelines 只多這個欄位。
- 前端 `JobView` 依事件把 `image` 存進候選，供審查面板使用。

### 4.6 前端

- **任務透視的審查面板**（`web/src/components/agent/review-panel.tsx`）：
  - 有 `image` 時，顯示「預覽／審查用海報」切換。
  - 審查用海報直接顯示 PNG，框線標示照常疊加，兩者座標相同。
  - `color_delta` 的說明文字旁顯示量到的主色色塊。
- **系統狀態**：composer 的說明改為「排版、繪製與規則審查」，並顯示目前的 `REVIEW_MODE`。

### 4.7 字型與 Docker

- **`web/Dockerfile`**：
  - 新增 `FROM scratch AS fonts` 階段，以 `ADD --checksum=sha256:…` 下載兩個字型檔與兩份 `OFL.txt`。
  - composer 階段先 `mkdir -p` 字型資料夾，再以 `COPY --chmod=0644` 複製進去，並設定 `POSTER_FONTS_DIR`。
- **`docker-compose.yml`**：worker 的環境變數加上 `REVIEW_MODE`（預設 `composer`）。composer 不需要掛載任何資料夾。
- **`docker-compose.e2e.yml`**：`REVIEW_MODE: composer`。
- **`@napi-rs/canvas`**：版本固定為 `1.0.13`（不加 `^`），並提交 lockfile。lockfile 含各平台的預編譯檔。

### 4.8 字型清單

| 檔案 | 網址（`https://raw.githubusercontent.com/google/fonts/45e3d5269e4a17d823f6d84470bc084dc5ae46f6/ofl/` 之後） | 位元組數 | SHA-256 |
|---|---|---|---|
| `NotoSansTC-VF.ttf` | `notosanstc/NotoSansTC%5Bwght%5D.ttf` | 11941968 | `864727d210d54f2537bbe23b3a839436c3992af72de9322af5270897246bd44f` |
| `NotoSerifTC-VF.ttf` | `notoseriftc/NotoSerifTC%5Bwght%5D.ttf` | 16851596 | `0077e18f57c6908f4a000969880940bdb0dad057c0e8d98b49dc364c3d1b09c6` |
| `OFL-NotoSansTC.txt` | `notosanstc/OFL.txt` | 4388 | `1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9` |
| `OFL-NotoSerifTC.txt` | `notoseriftc/OFL.txt` | 4350 | `5e0da210fb04058a8c0087985d2d456b931c2579811a49655721d3cf0c36b6d6` |

## 5. 模擬模式（`REVIEW_MODE=sim`）

- `SimPosters` 不畫圖。`SimReviewer` 呼叫 `/sim/review`，結果與目前完全相同。
- parity 測試只多比對 `image: null`。
- mock（作品集 Demo）不變，`image` 為 `null`。

## 6. 設定

| 變數 | 預設 | 說明 |
|---|---|---|
| `REVIEW_MODE` | `composer` | `composer` 或 `sim` |
| `POSTER_FONTS_DIR` | `web/composer/fonts`（Docker 內為 `/usr/local/share/poster-fonts`） | composer 的字型資料夾 |

## 7. 測試

- **Vitest**：
  - `measurePrimary`：合成圖片涵蓋純色區塊、雜訊、範圍外的干擾色、佔比門檻、量不到主色、中性色主色；
  - `contentVlmChecks`；
  - `poster.ts`：字型註冊、`measureText` 寬度、PNG 尺寸，不比對像素；
  - `/render` 與 `/review` 端點。
- **端到端的主色測試**：在 Vitest 以伺服器端繪製 3 個品牌 × 5 個模板，正確配色全部通過、偏色全部不通過。
  - 這需要字型。沒有字型時，以清楚的訊息略過，並提示執行 `npm run fonts`。
- **pytest**：
  - `ComposerPosters` 與 `ComposerReviewer` 使用測試啟動的 composer（埠 3902），因此 composer 需要字型；
  - 依 `REVIEW_MODE` 選擇實作；
  - composer 失敗時任務失敗，原因為中文；
  - 審查用海報存在正確的路徑。
- **測試不讀 `.env`**：後端測試的 `Settings` 一律以 `_env_file=None` 建立。
- **golden fixture**：timelines 只多 `image: null`，以 `npm run fixtures` 重新產生。
- **E2E**：mock 照舊；live 使用 `REVIEW_MODE=composer`，確認主流程、審查用海報的切換與圖片可以讀取。

## 8. 併入的 Plan 6 延後項目

- **後端測試與 `.env` 隔離**：`conftest` 與各測試的 `Settings(...)` 一律加上 `_env_file=None`。

其他延後項目要等 6B 才做：
- `Brand.guidelineChunks` 的大小；
- 可取消的等待；
- e2e 的 `GEMINI_API_KEY`；
- 驗證訊息的中文化。

## 9. 驗收

1. 以 `docker compose up -d --build` 啟動後，系統狀態的 composer 顯示字型已載入，`REVIEW_MODE` 為 `composer`。
2. 三個品牌各跑一個任務：
   - 第一輪（模擬偏色）的 `color_delta` 不通過，說明文字顯示實際用錯的主色；
   - 重試後通過；
   - 分數沒有隨機抖動。
3. 任務透視可以切換到審查用海報，伺服器繪製的結果與瀏覽器一致（版面、字型、顏色）。
4. `data/jobs/` 有每張候選的 PNG。
5. 全部測試通過：後端、前端、mock E2E、live E2E。

## 10. 對第二階段規格的修改

- **§5.6**：
  - `measurePrimary` 改為 4.2 的定義（量品牌色元素，不量背景）；
  - `ocrDiffs` 移到 6B；
  - 背景色系檢查移到 Plan 7。
- **§13**：Plan 6 拆成 6A 與 6B。
  - 6A 是本規格；
  - 6B 是需求拆解、Prompt 構建、Query Rewriting、VLM 審查、`ocrDiffs`、文案缺字護欄、用量與成本。
- **§2 事前準備**：Google AI Studio API key 的時間點改為 Plan 6B。

## 11. 不做

- **`includesProduct` 的繪製**：Plan 7 才有包含商品的生成圖。
- **背景色系檢查**：Plan 7。
- **伺服器端匯出海報**：前端匯出照舊。
- **自動清理 `data/jobs/` 的舊海報**：每張約 0.3–1 MB，之後視需要再加。
