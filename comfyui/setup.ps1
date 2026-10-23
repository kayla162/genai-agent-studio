<#
.SYNOPSIS
  下載 workflow 需要的模型到 ComfyUI 的 models 資料夾，並核對 SHA-256（模型與授權見 models.md）。

.DESCRIPTION
  ComfyUI 本身請從官方 release 下載 Windows portable 版並解壓縮（見 README.md）。
  已存在且 SHA-256 相同的檔案略過；不同時重新下載。目前的 workflow 不需要自訂節點（custom_nodes.md）。

.EXAMPLE
  .\comfyui\setup.ps1 -ComfyDir C:\Users\User\ComfyUI\ComfyUI_windows_portable\ComfyUI
#>
param(
    [Parameter(Mandatory = $true)][string]$ComfyDir
)
$ErrorActionPreference = 'Stop'

# 與 models.md 相同：只列授權允許商用的模型
$models = @(
    @{
        Folder = 'checkpoints'; Name = 'sd_xl_base_1.0.safetensors'
        Url = 'https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors'
        Sha256 = '31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b'
    },
    @{
        Folder = 'loras'; Name = 'sdxl_lightning_8step_lora.safetensors'
        Url = 'https://huggingface.co/ByteDance/SDXL-Lightning/resolve/main/sdxl_lightning_8step_lora.safetensors'
        Sha256 = '5aa30d94cdf7950a8b53a693682650ee061eddb128c5435a8f88defea73b2ac6'
    }
)

if (-not (Test-Path (Join-Path $ComfyDir 'main.py'))) {
    throw "找不到 ComfyUI：$ComfyDir 底下沒有 main.py（請指定 portable 版裡的 ComfyUI 資料夾）"
}

foreach ($m in $models) {
    $folder = Join-Path $ComfyDir (Join-Path 'models' $m.Folder)
    New-Item -ItemType Directory -Force $folder | Out-Null
    $target = Join-Path $folder $m.Name
    if ((Test-Path $target) -and ((Get-FileHash $target -Algorithm SHA256).Hash.ToLower() -eq $m.Sha256)) {
        Write-Host "已存在：$($m.Name)"
        continue
    }
    Write-Host "下載：$($m.Name)"
    $partial = "$target.part"
    curl.exe -L --fail --retry 3 -C - -o $partial $m.Url
    if ($LASTEXITCODE -ne 0) { throw "下載失敗：$($m.Url)" }
    $hash = (Get-FileHash $partial -Algorithm SHA256).Hash.ToLower()
    if ($hash -ne $m.Sha256) {
        Remove-Item $partial -Force
        throw "SHA-256 不符：$($m.Name)（$hash）"
    }
    Move-Item -Force $partial $target
    Write-Host "完成：$($m.Name)"
}
Write-Host '模型都已就緒。'
