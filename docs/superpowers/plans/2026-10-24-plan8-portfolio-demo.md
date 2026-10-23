# Plan 8：作品集 Demo 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** mock 模式的靜態輸出可以部署到 Cloudflare Pages，以 Access 的 email 名單限制觀看；README 有架構圖與 Demo 說明，另有展示影片腳本。

**Spec:** `docs/superpowers/specs/2026-10-24-plan8-portfolio-demo-design.md`

**分支**：建立在 `claude/plan7-comfyui`（PR #10）之上的 `claude/plan8-demo`；PR #10 合併後改以 `main` 為基底。

## Global Constraints

- 前端檢查：`npm run test`、`npm run typecheck`、`npm run lint`、`npm run build`、`npm run e2e` 都必須通過。
- 文件與訊息用繁體中文；Commit 訊息為英文，最後一行加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。
- 不在 repo 放任何 Cloudflare 的 token 或帳號資訊。

---

### Task 1：標頭、robots 與範本殘留

**Files:** Create `web/public/_headers`、`web/public/robots.txt`、`web/src/test/demo.test.ts`；Delete `web/public/{file,globe,next,vercel,window}.svg`

- [ ] **Step 1: 寫測試（先寫測試）**：`_headers` 對 `/*` 設定 `X-Robots-Tag: noindex, nofollow`、`X-Frame-Options: DENY`、`X-Content-Type-Options: nosniff`、`Referrer-Policy: strict-origin-when-cross-origin`、`Permissions-Policy`（camera、microphone、geolocation 為 `()`）；`robots.txt` 為 `User-agent: *` 與 `Disallow: /`；`public/` 沒有範本的 SVG。
- [ ] **Step 2: 確認失敗**：`npx vitest run src/test/demo.test.ts`
- [ ] **Step 3: 建立檔案、刪除 SVG**
- [ ] **Step 4: 確認通過，Commit**：`feat: add the Cloudflare Pages headers and robots for the portfolio demo`

### Task 2：部署前檢查 `npm run demo:check`

**Files:** Create `web/scripts/check-demo.mjs`；Modify `web/package.json`

- 讀 `out/`：`index.html` 存在；`_headers`、`robots.txt` 與 `public/` 的相同；以 `out/**/*.html` 與 `.js` 確認是 mock 建置（含 Demo 控制台的文字「Demo 控制台」，不含 `NEXT_PUBLIC_API_MODE` 為 live 的字串 `"live"===`…，以建置時的環境變數判斷：腳本讀 `process.env.NEXT_PUBLIC_API_MODE`，為 `live` 時直接失敗並說明）；任一項不符時以中文列出並結束碼 1。
- [ ] **Step 1: 建立腳本與 `"demo:check": "node scripts/check-demo.mjs"`**
- [ ] **Step 2: 確認**：`npm run build && npm run demo:check` 通過；刪掉 `out/_headers` 時失敗並說明（手動確認後重新建置）。
- [ ] **Step 3: Commit**：`feat: check the static build before deploying the portfolio demo`

### Task 3：文件

**Files:** Create `docs/demo/cloudflare.md`、`docs/demo/video-script.md`；Modify `README.md`、`web/README.md`、`docs/superpowers/specs/2026-10-07-phase2-backend-design.md`（§10 註記）

- [ ] **Step 1: 撰寫**：部署與 Access 的逐步說明（規格 §2 的設定值）、影片腳本、README 的 Mermaid 架構圖與「作品集 Demo」一節、進度表。
- [ ] **Step 2: 確認全部通過**：`npm run test && npm run typecheck && npm run lint && npm run build && npm run demo:check && npm run e2e`
- [ ] **Step 3: Commit**：`docs: explain the Cloudflare Pages and Access setup and add the demo video script`

## 完成之後

- 推送分支並開 PR（base 為 `claude/plan7-comfyui`，PR #10 合併後改為 `main`）。
- 使用者依 `docs/demo/cloudflare.md` 部署並設定名單（規格 §4 第 2 項）。

## 實作時的調整

（實作時與本計畫原文不同的地方記錄在這裡。）
