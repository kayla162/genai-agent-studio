# ComfyUI（生圖）

`IMAGE_MODE=comfyui`（預設）時，worker 把每個模板的商品底圖與遮罩上傳到 ComfyUI，由 ComfyUI 重繪商品以外的背景與光影；商品像素一律使用原始去背圖，由 composer 疊在同一個位置。設計見 [Plan 7 設計規格](../docs/superpowers/specs/2026-10-23-plan7-comfyui-design.md)。

> **狀態**：程式已完成，但 ComfyUI 的安裝、模型授權確認與實測（規格 §2、實作計畫 Task 1）還沒執行。下面標示「待實測」的項目在 Task 1 之後補上；目前的 workflow 是手寫的最小版本。

## 檔案

| 檔案 | 內容 |
|---|---|
| `workflows/product_scene_v1.json` | API 格式的 workflow（目前手寫：SDXL base 1.0 以 `InpaintModelConditioning` 重繪商品以外的區域，只用 ComfyUI 內建節點） |
| `workflows/product_scene_v1.params.json` | 參數對照表：`label` → 節點與輸入。與前端的 `web/src/lib/agent/comfy.ts` 相同（`backend/tests/test_comfy_params.py` 檢查） |
| `models.md`、`custom_nodes.md` | 模型與自訂節點的來源、版本、SHA-256 與授權（Task 1 建立） |
| `setup.ps1` | 安裝自訂節點、下載模型並核對 SHA-256（Task 1 建立） |

## 安裝（Windows）

1. 從 ComfyUI 官方 GitHub 的 release 下載 Windows portable 版（內含 Python 與 PyTorch）並解壓縮。版本：待實測。
2. 下載 workflow 需要的模型，放到 ComfyUI 的 `models/` 底下：

   | 模型 | 放在 | 授權 |
   |---|---|---|
   | `sd_xl_base_1.0.safetensors` | `models/checkpoints/` | CreativeML Open RAIL++-M（待 Task 1 讀授權原文確認商用條款） |

   只使用授權明確允許商用的模型與自訂節點；非商用（例如 CC BY-NC）或授權不明確的一律不用。加速用的 LoRA、ControlNet 或放大模型確認授權後才會加入 workflow 與上表。
3. 啟動 ComfyUI。啟動參數（`--listen`、VRAM 模式）：待實測。Docker 內的 api 與 worker 以 `http://host.docker.internal:8188` 連線；本機執行後端時為 `http://127.0.0.1:8188`。
4. 開啟系統的連線狀態（右上角）：ComfyUI 一項顯示 GPU、VRAM 與版本時就完成了；缺少 workflow 需要的節點或模型時會列出缺少的項目。

## 記憶體（16 GB 的筆電）

- ComfyUI（SDXL）約用 6–8 GB 系統記憶體（規格的估計，待實測），與商品去背的尖峰相加會超過 16 GB。所以生圖與去背以 Redis 鎖互斥（`MEMORY_LOCK=true`，預設）。
- `COMFYUI_FREE_AFTER_JOB=true` 時，每個任務結束後請 ComfyUI 卸載模型、釋放記憶體（下一個任務要重新載入）。預設：待實測。
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
