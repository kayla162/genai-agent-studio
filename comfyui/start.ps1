<#
.SYNOPSIS
  啟動 ComfyUI（只監聽 127.0.0.1:8188；Docker 內的 api 與 worker 以 host.docker.internal 連得到）。

.DESCRIPTION
  已經有程式在 8188 埠時不重複啟動。關掉這個視窗就會停止 ComfyUI。
  GPU 記憶體不足（任務失敗的原因建議 --lowvram）時加上 -LowVram。

.EXAMPLE
  .\comfyui\start.ps1
  .\comfyui\start.ps1 -PortableDir D:\ComfyUI_windows_portable -LowVram
#>
param(
    [string]$PortableDir = (Join-Path $env:USERPROFILE 'ComfyUI\ComfyUI_windows_portable'),
    [switch]$LowVram
)
$ErrorActionPreference = 'Stop'

$python = Join-Path $PortableDir 'python_embeded\python.exe'
$main = Join-Path $PortableDir 'ComfyUI\main.py'
if (-not (Test-Path $python) -or -not (Test-Path $main)) {
    throw "找不到 ComfyUI portable 版：$PortableDir（請以 -PortableDir 指定解壓縮的資料夾，見 comfyui/README.md）"
}

if (Get-NetTCPConnection -LocalPort 8188 -State Listen -ErrorAction SilentlyContinue) {
    Write-Host 'ComfyUI 已經在執行（127.0.0.1:8188），不再重複啟動。'
    exit 0
}

$arguments = @('-s', $main, '--windows-standalone-build', '--listen', '127.0.0.1', '--port', '8188', '--disable-auto-launch')
if ($LowVram) { $arguments += '--lowvram' }
Write-Host "啟動 ComfyUI：$PortableDir（關掉這個視窗就會停止）"
Set-Location $PortableDir
& $python @arguments
