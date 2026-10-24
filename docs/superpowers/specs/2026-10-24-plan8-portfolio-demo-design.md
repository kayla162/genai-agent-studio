# Plan 8：作品集 Demo（Cloudflare Pages＋Access）設計規格

- 日期：2026-10-24
- 狀態：設計決定依第二階段規格 §10 與使用者的指示（「有問題時都依推薦的選項選」）決定，未逐項詢問
- 相關：`2026-10-07-phase2-backend-design.md`（§1、§9、§10、§12、§13）

## 1. 目標

讓名單內的人以瀏覽器觀看作品集 Demo，不需要安裝任何東西：
1. 前端 mock 模式的靜態輸出（`web/out/`）部署到 Cloudflare Pages。
2. Cloudflare Zero Trust 的 Access 只允許名單內的 email，以寄到信箱的一次性驗證碼登入。
3. README 的架構圖與操作說明、展示影片的腳本。

部署與名單設定需要使用者自己的 Cloudflare 帳號，由使用者操作；本計畫提供設定檔、檢查腳本與逐步說明（第二階段規格 §10）。

## 2. 已確認的決定

| 項目 | 決定 | 理由 |
|---|---|---|
| 部署方式 | Cloudflare Pages 的 Git 整合（連結 GitHub repo，推送 `main` 自動建置；PR 建立 preview） | repo 不需要放 API token 或 GitHub Actions 的 secret；preview 網址一樣受 Access 保護。手動部署（`wrangler pages deploy`）列為替代方式 |
| 建置 | 根目錄 `web`、建置指令 `npm ci && npm run build`、輸出 `out`、環境變數 `NODE_VERSION=24`，不設定 `NEXT_PUBLIC_API_MODE`（預設 mock） | 與本機的 mock 建置相同；mock 版不需要 composer、字型或後端 |
| 觀看限制 | Access 應用程式保護 production 與所有 preview（`*.<專案>.pages.dev`）；政策 Allow、Include「Emails」名單；登入方式為 One-time PIN；工作階段 24 小時 | 免費方案最多 50 人；名單可隨時增減並查看存取紀錄（第二階段規格 §10） |
| 搜尋引擎 | `X-Robots-Tag: noindex, nofollow` 與 `robots.txt` 全部 Disallow | 私人作品集；Access 擋住內容，但登入頁與 preview 仍不該被收錄 |
| 安全標頭 | `public/_headers`：`X-Frame-Options: DENY`、`X-Content-Type-Options: nosniff`、`Referrer-Policy: strict-origin-when-cross-origin`、`Permissions-Policy` 關閉相機、麥克風與位置 | 靜態網站不需要的權限一律關閉；不加 CSP（Next.js 的內嵌 script 需要 nonce 或 hash，靜態輸出無法動態產生，加錯會讓頁面空白） |
| 範本殘留 | 刪除 `public/` 裡沒有使用的 create-next-app SVG | 不部署用不到的檔案 |
| 架構圖 | README 加上 Mermaid 圖（GitHub 會直接畫出），保留現有的文字圖 | 作品集的讀者多半先看 GitHub |
| 影片腳本 | `docs/demo/video-script.md`：約 3 分鐘、6 個段落，每段寫畫面、操作與旁白 | 錄影由使用者進行 |

## 3. 內容

| 檔案 | 內容 |
|---|---|
| `web/public/_headers`、`web/public/robots.txt` | Cloudflare Pages 的標頭與 robots（靜態輸出時複製到 `out/`） |
| `web/scripts/check-demo.mjs`（`npm run demo:check`） | 檢查 `out/`：有 `index.html`、`_headers` 含上面的標頭、`robots.txt` 全部 Disallow、建置不是 live 模式（mock 的 Demo 控制台存在、沒有 `NEXT_PUBLIC_API_MODE=live` 的設定）。部署前在本機執行 |
| `web/src/test/demo.test.ts` | Vitest：`public/_headers` 與 `robots.txt` 的內容（不需要建置） |
| `docs/demo/cloudflare.md` | 逐步說明：建立 Pages 專案（Git 整合與替代的 wrangler）、Zero Trust 與 Access 應用程式、名單、驗證、移除觀看者、查看紀錄、費用 |
| `docs/demo/video-script.md` | 展示影片腳本 |
| `README.md` | 進度表、Mermaid 架構圖、「作品集 Demo」一節 |

## 4. 驗收

1. `npm run build && npm run demo:check` 通過；`npm run test`、`npm run e2e`（mock）通過。
2. 使用者依 `docs/demo/cloudflare.md` 部署後：未登入時看到 Access 登入頁；名單內的 email 收到驗證碼後可以觀看；名單外的 email 收不到驗證碼（Access 不透露名單）；preview 網址同樣受保護。第 2 項需要使用者的 Cloudflare 帳號，由使用者確認。

## 5. 不做

- 自訂網域（使用 `pages.dev`；之後要用自訂網域時，Access 應用程式加上該網域即可）。
- live 模式的線上 Demo（需要 GPU 與 Gemini key 的後端，不適合公開部署）。
- 分析工具、留言等需要額外服務的功能。
