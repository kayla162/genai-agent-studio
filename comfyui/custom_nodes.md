# ComfyUI 的自訂節點

目前的 workflow（`workflows/product_scene_v1.json`）只用 ComfyUI 內建的節點，不需要安裝任何自訂節點：

`CheckpointLoaderSimple`、`LoraLoader`、`CLIPTextEncode`、`LoadImage`、`LoadImageMask`、`InpaintModelConditioning`、`KSampler`、`VAEDecode`、`SaveImage`

之後若要加入自訂節點，先在這裡記錄：repo 網址、固定的 commit、授權與商用結論（只用允許商用的），再由 `setup.ps1` 安裝。
