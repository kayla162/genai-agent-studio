@echo off
rem Double-click to start ComfyUI via start.ps1 (bypasses the execution policy for this run only)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
pause
