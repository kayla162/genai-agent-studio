# ComfyUI 的模型與授權

只使用授權明確允許商用的模型（Plan 7 規格 §3）。授權結論依各模型頁的授權原文（不是摘要）；有疑問的模型不放進 workflow，也不下載。`setup.ps1` 只下載下表「商用：可以」的檔案，並核對 SHA-256。

確認日期：2026-10-24。

| 檔案 | 放在 | 來源 | 大小 | SHA-256 | 授權 | 商用 |
|---|---|---|---|---|---|---|
| `sd_xl_base_1.0.safetensors` | `models/checkpoints/` | [stabilityai/stable-diffusion-xl-base-1.0](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0) | 6,938,078,334 | `31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b` | CreativeML Open RAIL++-M（2023-07-26，[原文](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md)） | 可以 |
| `sdxl_lightning_8step_lora.safetensors` | `models/loras/` | [ByteDance/SDXL-Lightning](https://huggingface.co/ByteDance/SDXL-Lightning) | 393,854,592 | `5aa30d94cdf7950a8b53a693682650ee061eddb128c5435a8f88defea73b2ac6` | CreativeML Open RAIL++-M（模型頁標示 `openrail++`） | 可以 |

## 授權重點（CreativeML Open RAIL++-M）

- 授予使用、修改與散布模型的權利，沒有限制非商用。
- 生成結果（Output）：授權方不主張權利；使用者對生成結果及其用途負責，用途不得違反授權條款。
- 使用限制（Attachment A）：不得用於違法、傷害未成年人、散布不實資訊、未經同意的個人資料、歧視等用途。商品海報的背景生成不在限制內。
- 散布模型或衍生模型時要附上同樣的使用限制；本專案不散布模型，只在本機使用。

## 沒有採用的候選

| 候選 | 原因 |
|---|---|
| SDXL inpainting 0.1（diffusers） | 授權同為 Open RAIL++-M，但沒有單一檔案的 checkpoint；改以 SDXL base 加上 ComfyUI 內建的 `InpaintModelConditioning` 重繪 |
| ControlNet（方式 B） | 方式 A（商品周圍重繪）不需要；規格 §2 的方式比較見規格 §12 |
| IP-Adapter、IC-Light | 規格 §3、§11：不使用 |
| 4x-UltraSharp 等放大模型 | 多為 CC BY-NC（非商用）；放大改在 worker 以 Lanczos 進行 |
