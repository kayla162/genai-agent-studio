# ComfyUI（生圖）

`IMAGE_MODE=comfyui`（預設）時，worker 把每個模板的商品底圖與遮罩上傳到 ComfyUI，由 ComfyUI 重繪商品以外的背景與光影；商品像素一律使用原始去背圖，由 composer 疊在同一個位置。設計見 [Plan 7 設計規格](../docs/superpowers/specs/2026-10-23-plan7-comfyui-design.md)。

> **狀態**：模型授權已確認（`models.md`）；2026-10-24 在 RTX 3060 Laptop（6 GB）實測，結果見規格 §12。

## 檔案

| 檔案 | 內容 |
|---|---|
| `workflows/product_scene_v1.json` | API 格式的 workflow：SDXL base 1.0 加上 SDXL-Lightning 8 步的 LoRA，以 `InpaintModelConditioning` 重繪商品以外的區域；只用 ComfyUI 內建節點 |
| `workflows/product_scene_v1.params.json` | 參數對照表：`label` → 節點與輸入。與前端的 `web/src/lib/agent/comfy.ts` 相同（`backend/tests/test_comfy_params.py` 檢查） |
| `models.md`、`custom_nodes.md` | 模型與自訂節點的來源、版本、SHA-256 與授權（目前不需要自訂節點） |
| `setup.ps1` | 下載模型並核對 SHA-256 |

## 安裝（Windows）

1. 從 ComfyUI 官方 GitHub（[Comfy-Org/ComfyUI](https://github.com/Comfy-Org/ComfyUI/releases)）的 release 下載 `ComfyUI_windows_portable_nvidia.7z`（v0.42.1，約 2 GB，內含 Python 與 PyTorch）並解壓縮，例如到 `C:\Users\<你>\ComfyUI\`。Windows 11 內建的 `tar -xf` 就能解開 7z。
2. 下載模型（約 7.3 GB，核對 SHA-256）：

   ```powershell
   .\comfyui\setup.ps1 -ComfyDir C:\Users\<你>\ComfyUI\ComfyUI_windows_portable\ComfyUI
   ```

   | 模型 | 放在 | 授權 |
   |---|---|---|
   | `sd_xl_base_1.0.safetensors` | `models/checkpoints/` | CreativeML Open RAIL++-M：允許商用，附使用限制（`models.md`） |
   | `sdxl_lightning_8step_lora.safetensors` | `models/loras/` | CreativeML Open RAIL++-M：允許商用，附使用限制 |

   只使用授權明確允許商用的模型與自訂節點；非商用（例如 CC BY-NC）或授權不明確的一律不用。
3. 啟動 ComfyUI：雙擊 `comfyui/start.cmd`（或在 PowerShell 執行 `.\comfyui\start.ps1`；portable 版不在 `%USERPROFILE%\ComfyUI\ComfyUI_windows_portable` 時加上 `-PortableDir <資料夾>`，GPU 記憶體不足時加上 `-LowVram`）。已經在執行時不重複啟動；關掉視窗就會停止。腳本執行的指令與手動啟動相同（在 portable 資料夾）：

   ```powershell
   .\python_embeded\python.exe -s ComfyUI\main.py --windows-standalone-build --listen 127.0.0.1 --port 8188
   ```

   6 GB VRAM 時 VRAM 模式自動為 NORMAL_VRAM，不需要 `--lowvram`。本機執行後端時以 `http://127.0.0.1:8188` 連線；Docker 內的 api 與 worker 以 `http://host.docker.internal:8188` 連線（Docker Desktop 實測：`--listen 127.0.0.1` 時容器就連得到，不需要 `--listen 0.0.0.0`，ComfyUI 也不會對區網開放）。
4. 開啟系統的連線狀態（右上角）：ComfyUI 一項顯示 GPU、VRAM 與版本時就完成了；缺少 workflow 需要的節點或模型時會列出缺少的項目。

## 記憶體（16 GB 的筆電）

- 實測：GPU 尖峰 5.42 GB；ComfyUI 本身約用 6 GB 系統記憶體。與商品去背的尖峰（約 7.6 GiB）相加會超過 16 GB，所以生圖與去背以 Redis 鎖互斥（`MEMORY_LOCK=true`，預設）。
- `COMFYUI_FREE_AFTER_JOB=true` 時，每個任務結束後請 ComfyUI 卸載模型、釋放記憶體（下一個任務要重新載入模型；重新載入的秒數沒有實測）。預設 `false`。
- 6 GB VRAM：ComfyUI 會自動把部分模型卸載到系統記憶體；仍然 GPU 記憶體不足時，任務失敗的原因會建議以 `--lowvram` 啟動。

## 驗證與錄製（在 `backend/`）

```bash
uv run pytest -m live tests/test_comfy_live.py
```

每個模板生成一張背景，檢查尺寸並印出秒數（目標每張 ≤ 60 秒）。ComfyUI 沒有回應時略過。需要 composer（測試會自動啟動）。

```bash
uv run python -m scripts.record_comfy
```

以真的 ComfyUI 跑一次，把回應錄進 `backend/tests/data/comfy/`，取代目前手寫的回應（需要執行中的 composer：在 `web/` 執行 `npm run composer`）。
