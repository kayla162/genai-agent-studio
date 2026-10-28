# 作品集 Demo：部署到 Cloudflare Workers

線上網址：https://genai-agent-studio.kayla-swag-19.workers.dev/

前端的 mock 模式（瀏覽器內模擬整條流程，不需要後端、GPU 或 Gemini key）建置成靜態網站，以 Cloudflare Workers 的靜態資源（只有檔案，沒有 Worker 程式）公開提供，不需要登入。全部使用免費方案。設定檔是 [`web/wrangler.jsonc`](../../web/wrangler.jsonc)。

以下操作都在你自己的 Cloudflare 帳號進行；repo 不放任何 token。Cloudflare 的介面名稱偶爾會調整，找不到選項時以頁面上的搜尋或同名的設定為準。

## Demo 不會產生費用

- Gemini 只由後端呼叫，API key 只放在後端的 `.env`。Demo 沒有後端，前端程式與靜態輸出都不含 Gemini 的程式或 key。
- 生圖、去背、RAG 都是瀏覽器內的模擬，不連任何服務。
- Workers 的靜態資源請求不計入 Workers 的請求次數，免費方案即可。

## 1. 部署前在本機檢查

在 `web/`：

```bash
npm run build
```

```bash
npm run demo:check
```

`demo:check` 確認是 mock 建置（沒有設定 `NEXT_PUBLIC_API_MODE=live`），而且 `out/` 有首頁、`_headers`（不讓搜尋引擎收錄、禁止被嵌入其他網站、關閉相機等權限）與 `robots.txt`。

想在本機以 Cloudflare 的方式預覽（`/studio` 對應 `studio.html`、套用 `_headers`）：

```bash
npx wrangler dev
```

## 2. 用 Git 整合自動部署（目前的方式）

Cloudflare 儀表板 → **Workers & Pages** → `genai-agent-studio` → **Settings** → **Build**：

| 欄位 | 值 |
|---|---|
| Git repository | 這個 repo，Production branch 為 `main` |
| Root directory | `web` |
| Build command | `npm ci && npm run build` |
| Deploy command | `npx wrangler deploy` |
| Build variables | `NODE_VERSION` = `24`（不要設定 `NEXT_PUBLIC_API_MODE`） |

`npx wrangler deploy` 讀 `web/wrangler.jsonc`：上傳 `out/` 的全部檔案，`/studio` 對應 `studio.html`，找不到的網址顯示 `404.html`。之後推送 `main` 就會自動建置並部署。

**Root directory 一定要是 `web`**：沒有設定時，Cloudflare 會從 repo 根目錄找靜態檔，部署到早期的單檔原型 `prototype/index.html`，而不是現在的介面。

### 替代方式：手動部署

不想連結 GitHub 時，在 `web/` 建置並檢查後：

```bash
npx wrangler login
```

```bash
npx wrangler deploy
```

每次更新都要重新建置並部署。

## 3. 驗證

用無痕視窗開下列網址：

1. 首頁：右上角顯示「Demo」，可以在新任務頁面送出需求並看到模擬的流程。
2. 直接開 `/studio`、`/products`、`/dashboard`：都能正常顯示，不是 404。
3. 在終端機檢查標頭：

   ```bash
   curl -sI https://genai-agent-studio.kayla-swag-19.workers.dev/studio
   ```

   應該有 `x-robots-tag: noindex, nofollow` 與 `x-frame-options: DENY`。

## 4. 想限制觀看者時

目前 Demo 公開，方便面試官直接開啟。要改成只讓名單內的人觀看時，可以加上 Cloudflare Zero Trust 的 Access（免費方案最多 50 人，以寄到信箱的一次性驗證碼登入）：

1. Cloudflare 儀表板 → **Zero Trust**（第一次使用時建立團隊名稱，選 Free 方案）。
2. **Access → Applications → Add an application → Self-hosted**，Application domain 填 `genai-agent-studio.kayla-swag-19.workers.dev`。
3. 新增 Allow 政策，Include 選 **Emails** 並填入名單。
4. 用無痕視窗確認：未登入時看到 Access 的登入頁，名單內的 email 收到驗證碼後才看得到 Demo。

## 5. 觀看者看到什麼

- 全部在瀏覽器內模擬：示範品牌（SÉLUNE、misty-isle）、示範商品與任務，資料存在觀看者自己的瀏覽器（IndexedDB），不會互相影響，也不會傳到任何伺服器。
- 右下角的「Demo 控制台」可以調整模擬速度、讓第一輪刻意失敗或每輪都失敗，展示 Query Rewriting 與「需人工審核」。
- live 模式（真的 Gemini、RAG、ComfyUI）不在線上。
