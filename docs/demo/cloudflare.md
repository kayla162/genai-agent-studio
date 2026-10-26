# 作品集 Demo：部署到 Cloudflare Pages 並限制觀看者

前端的 mock 模式（瀏覽器內模擬，不需要後端、GPU 或 Gemini key）以靜態網站部署到 Cloudflare Pages，再以 Cloudflare Zero Trust 的 Access 只讓名單內的 email 觀看。全部使用免費方案（Access 最多 50 人）。設計見 [Plan 8 設計規格](../superpowers/specs/2026-10-24-plan8-portfolio-demo-design.md)。

以下操作都在你自己的 Cloudflare 帳號進行；repo 不放任何 token。Cloudflare 的介面名稱偶爾會調整，找不到選項時以頁面上的搜尋或同名的設定為準。

## 1. 部署前在本機檢查

在 `web/`：

```bash
npm run build
```

```bash
npm run demo:check
```

`demo:check` 確認是 mock 建置（沒有設定 `NEXT_PUBLIC_API_MODE=live`），而且 `out/` 有首頁、`_headers`（不讓搜尋引擎收錄、禁止被嵌入其他網站、關閉相機等權限）與 `robots.txt`。

## 2. 建立 Pages 專案（Git 整合，推薦）

1. Cloudflare 儀表板 → **Workers & Pages** → **Create** → **Pages** → **Connect to Git**，授權 GitHub 後選這個 repo。
2. 專案名稱：例如 `genai-agent-demo`（網址會是 `https://genai-agent-demo.pages.dev`）。
3. 建置設定：

   | 欄位 | 值 |
   |---|---|
   | Production branch | `main` |
   | Framework preset | None |
   | Root directory | `web` |
   | Build command | `npm ci && npm run build` |
   | Build output directory | `out` |
   | 環境變數 | `NODE_VERSION` = `24`（不要設定 `NEXT_PUBLIC_API_MODE`） |

4. **Save and Deploy**。之後推送 `main` 會自動部署 production；其他分支與 PR 會建立 preview（`https://<分支或雜湊>.genai-agent-demo.pages.dev`）。

**還沒設定 Access 之前，網址是公開的**：先完成第 3 節再分享網址，或在建立專案前先建立 Access 應用程式。

### 替代方式：手動上傳（wrangler）

不想連結 GitHub 時，在 `web/` 建置並檢查後：

```bash
npx wrangler login
```

```bash
npx wrangler pages deploy out --project-name genai-agent-demo
```

第一次執行時會建立專案。每次更新都要重新建置並上傳。

## 3. 用 Access 限制觀看者

1. Cloudflare 儀表板 → **Zero Trust**（第一次使用時建立團隊名稱，選 Free 方案；需要填付款方式驗證，但不收費）。
2. **Settings → Authentication → Login methods**：確認 **One-time PIN** 已啟用（預設就有）。觀看者輸入 email 後，Cloudflare 寄驗證碼到信箱。
3. **Access → Applications → Add an application → Self-hosted**：

   | 欄位 | 值 |
   |---|---|
   | Application name | `GenAI Agent Demo` |
   | Session duration | `24 hours` |
   | Application domain | `genai-agent-demo.pages.dev` |
   | 再加一個 domain | `*.genai-agent-demo.pages.dev`（保護所有 preview） |

4. **Policies → Add a policy**：
   - Policy name：`作品集觀看者`
   - Action：**Allow**
   - Include → Selector **Emails** → 填入名單（每個 email 一筆）。
5. 儲存。Pages 專案的 **Settings → General → Access policy** 也可以一鍵為 preview 啟用 Access；上面的萬用字元 domain 已經涵蓋，兩者擇一即可。

## 4. 驗證

用無痕視窗：

1. 開 `https://genai-agent-demo.pages.dev`：應該看到 Cloudflare Access 的登入頁，而不是 Demo。
2. 輸入名單內的 email：收到驗證碼，輸入後看到 Demo。
3. 輸入名單外的 email：頁面一樣顯示「已寄出」，但不會收到驗證碼（Access 不透露誰在名單內）。
4. 開一個 preview 網址：同樣要先登入。

## 5. 管理名單與紀錄

- **新增或移除觀看者**：Zero Trust → Access → Applications → `GenAI Agent Demo` → Policies → 編輯 `作品集觀看者` 的 Emails。移除的人在工作階段（24 小時）到期後就無法再進入；要立刻撤銷時，到 **My Team → Users** 撤銷該使用者的工作階段。
- **存取紀錄**：Zero Trust → **Logs → Access**，可以看到誰在什麼時間登入、被拒絕的嘗試。
- **人數**：免費方案每月最多 50 個使用者（以登入過的人計算）。

## 6. 觀看者看到什麼

- 全部在瀏覽器內模擬：示範品牌（SÉLUNE、misty-isle）、示範商品與任務，資料存在觀看者自己的瀏覽器（IndexedDB），不會互相影響，也不會傳到任何伺服器。
- 右下角的「Demo 控制台」可以調整模擬速度、讓第一輪刻意失敗或每輪都失敗，展示 Query Rewriting 與「需人工審核」。
- live 模式（真的 Gemini、RAG、ComfyUI）不在線上。
