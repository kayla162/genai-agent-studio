# 從手機開啟 Studio 與審核表單 計畫書（不買網域）

> 狀態：計畫中（2026-11-07）。Cloudflare Tunnel 的程式與文件已在 PR #35（`claude/n8n-line`）完成，但需要自己的網域，**目前不購買**；本計畫改以不需要網域的 Tailscale 先達成目標，之後買了網域再換成 Cloudflare Tunnel。

**Goal:** 手機收到 LINE 審核通知後，點訊息裡的 Studio 連結與 n8n 審核表單連結就能開啟（用 4G 也可以），而且只有自己的裝置進得來。

**現況：** LINE 訊息的連結是 `http://127.0.0.1:3080/...` 與 `http://127.0.0.1:5678/...`，只有這台電腦打得開。LINE 的海報圖片走 Cloudflare R2 的 `r2.dev` 公開網址，不需要網域，不受影響。

**Architecture（建議方案）：** 電腦與手機都加入同一個 Tailscale 私人網路（tailnet）。電腦上以 `tailscale serve` 把 `https://<電腦名稱>.<tailnet>.ts.net` 轉到本機的 Studio（`127.0.0.1:3080`），`:8443` 轉到 n8n（`127.0.0.1:5678`）。只有登入同一個 Tailscale 帳號的裝置連得到，不對網際網路公開。PR #35 加入的 `PUBLIC_HOST`、`N8N_PUBLIC_URL` 直接沿用，compose 不需要再修改。

**費用：** Tailscale Personal 方案免費（個人使用、裝置數足夠）；不需要網域。

## 方案比較

| 方案 | 需要網域 | 誰連得到 | 網址固定 | 結論 |
|---|---|---|---|---|
| **A. Tailscale（`tailscale serve`）** | 否 | 只有自己登入 Tailscale 的裝置 | 是（`*.ts.net`） | **現在採用** |
| B. Cloudflare Tunnel＋Access | 是（約每年 US$10） | 通過 email 驗證碼的人 | 是 | 買網域後採用；PR #35 已完成，照 `docs/tunnel.md` 設定 |
| C. Cloudflare Quick Tunnel（`trycloudflare.com`） | 否 | **任何人** | 否，每次啟動都換 | 不採用：無法加 Access，Studio 沒有登入功能，拿到網址就能花 Gemini 額度 |
| D. 同一個 Wi-Fi（區網 IP） | 否 | 同一個網路的所有人 | 否（目前是 iPhone 熱點的 `172.20.10.5`） | 不採用：離開這個網路就不能用，同網路的人也進得來 |
| E. 維持現狀 | 否 | 只有這台電腦 | 是 | 備案：在電腦上開連結 |

方案 A 的限制：手機要先開著 Tailscale（VPN 開關）才打得開連結；別人轉傳的連結對方打不開（這也是想要的效果）。

## Global Constraints

- **不使用 Tailscale Funnel**（會把服務公開到網際網路）；只用 `tailscale serve`（僅 tailnet 內）。
- compose 的埠維持只綁 `127.0.0.1`；不開放區網或對外的埠。
- 防止 DNS rebinding 的主機名稱檢查維持開啟：nginx 與 api 只接受 `127.0.0.1`、`localhost` 與 `PUBLIC_HOST`。
- 不在 repo 放任何 token 或 tailnet 名稱；`.env` 不進 repo。
- 本機的 `docker-compose.override.yml`（api 8010、web 3080）維持不進 repo。
- 文件一律繁體中文；commit 訊息以英文 conventional commits 撰寫，結尾加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。

## Tasks

### Task 1：合併 PR #35（前置）

PR #35 包含 LINE 通知、R2 附圖、`PUBLIC_HOST` 與 `N8N_PUBLIC_URL`，方案 A 會用到後兩者。

- [ ] 確認 GitHub Actions 的 backend 與 web 兩個 job 都通過（mypy 的 `windll` 錯誤已在 `22767f4` 修正）。
- [ ] Cloudflare 的「Workers Builds」在所有 PR 分支都失敗（`main` 上成功），與程式無關：到 Cloudflare 儀表板 → Workers & Pages → `genai-agent-studio` → Builds 查看原因，或在 Settings → Build 關閉非正式分支的建置。不擋合併。
- [ ] 合併後切回 `main` 並 `git pull`。

### Task 2：安裝與設定 Tailscale（使用者操作）

- [ ] 電腦（Windows）與手機各安裝 Tailscale，登入同一個帳號。
- [ ] Tailscale 管理頁 → **DNS**：開啟 **MagicDNS** 與 **HTTPS Certificates**。
- [ ] 記下電腦的完整名稱：`tailscale status` 或管理頁 → Machines（例如 `desktop-abc.tail1234.ts.net`）。

### Task 3：以 `tailscale serve` 提供 Studio 與 n8n，並先驗證

在電腦的 PowerShell 執行：

```bash
tailscale serve --bg --https=443 http://127.0.0.1:3080
```

```bash
tailscale serve --bg --https=8443 http://127.0.0.1:5678
```

```bash
tailscale serve status
```

需要驗證的事（手機關掉 Wi-Fi，只用 4G＋Tailscale）：

- [ ] `https://<電腦名稱>.ts.net/studio` 打得開，頁面正常、即時更新（WebSocket）正常。
- [ ] 若頁面空白或回應被中斷：代表 `tailscale serve` 轉送時保留了原本的主機名稱，nginx 不認得 → 完成 Task 4 的 `PUBLIC_HOST` 後再試。若轉送時改成 `127.0.0.1`，nginx 本來就接受，`PUBLIC_HOST` 可以不設（設了也無害）。
- [ ] `https://<電腦名稱>.ts.net:8443` 打得開 n8n。
- [ ] 手機關掉 Tailscale 時兩個網址都打不開（確認沒有公開）。

### Task 4：`.env` 設定並重新建立容器

```
PUBLIC_HOST=<電腦名稱>.<tailnet>.ts.net
STUDIO_BASE_URL=https://<電腦名稱>.<tailnet>.ts.net
N8N_PUBLIC_URL=https://<電腦名稱>.<tailnet>.ts.net:8443/
```

```bash
docker compose --profile automation up -d --build
```

- [ ] `TUNNEL_TOKEN` 不設定、不加 `--profile tunnel`（方案 A 不需要 cloudflared）。
- [ ] 確認 worker 讀到新值：`docker compose exec worker printenv STUDIO_BASE_URL`。

### Task 5：文件（repo 變更）

- [ ] `docs/tunnel.md` 改名為「從手機開啟」，分成兩節：**Tailscale（不需要網域）** 與 **Cloudflare Tunnel（需要網域）**，各自列出步驟、`.env` 與限制。
- [ ] `n8n/README.md` §9 與 `.env.example` 的說明連到兩種方式。
- [ ] 文件明寫：只用 `tailscale serve`，不要用 Funnel。
- [ ] 開新的 PR（在 PR #35 合併之後）。

### Task 6：端對端驗收

- [ ] 在 Studio 建一個新任務。
- [ ] 手機（4G＋Tailscale）收到 LINE 訊息：有海報圖片（R2）、Studio 連結與審核表單連結都是 `https://…ts.net…`。
- [ ] 點 Studio 連結：看到該任務的 Agent 頁面。
- [ ] 點審核表單、選「核准」送出：LINE 收到「✅ 已選定…」，Studio 的歷史紀錄多一筆。
- [ ] 再做一次「退回＋修改意見」：LINE 收到「🔁 已退回，新任務…」。
- [ ] 在設定之前就送出的舊訊息，連結還是 `127.0.0.1`（預期中，不處理）。

## 之後：買了網域時改用 Cloudflare Tunnel

1. 照 `docs/tunnel.md`：先設定 Cloudflare Access（只允許自己的 email），再建立 Tunnel（`studio.<網域>` → `web:8080`、`review.<網域>` → `n8n:5678`）。
2. `.env` 改成 `TUNNEL_TOKEN`、`PUBLIC_HOST=studio.<網域>`、`STUDIO_BASE_URL=https://studio.<網域>`、`N8N_PUBLIC_URL=https://review.<網域>/`。
3. `docker compose --profile automation --profile tunnel up -d --build`。
4. 停止 Tailscale 的轉送：`tailscale serve reset`。

好處：手機不用開 VPN、可以分享給其他審核者（加進 Access 的 email 名單）。

## 風險與注意事項

| 風險 | 處理方式 |
|---|---|
| 手機沒開 Tailscale 就點連結 | 打不開；在 LINE 訊息文字或文件提醒先開 Tailscale |
| LINE 內建瀏覽器不走 VPN 或擋自簽憑證 | `ts.net` 是正式的 HTTPS 憑證；若內建瀏覽器有問題，長按連結改用外部瀏覽器開啟 |
| 誤用 Tailscale Funnel 把 Studio 公開 | Global Constraints 與文件明寫禁止；驗收時確認關掉 Tailscale 就打不開 |
| 電腦休眠或關機 | 手機打不開；與現況相同（服務本來就在這台電腦上） |
| 電腦名稱改變 | `ts.net` 網址跟著變：更新 `.env` 三個值並重新建立容器 |
