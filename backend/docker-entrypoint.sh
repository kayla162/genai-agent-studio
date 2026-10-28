#!/bin/sh
# api 與 worker 的進入點：以 root 啟動時，先把要寫入的資料夾交給 app，再以 app（非 root）執行指令。
# 舊版以 root 執行時建立的 models volume 與 data/ 裡的檔案屬於 root，不交出去的話 app 寫不進去。
set -e
if [ "$(id -u)" = 0 ]; then
    for dir in /app/data /app/models; do
        # 已經屬於 app 時略過（data/ 可能有很多檔案）；不支援 chown 的掛載（例如 Windows 的資料夾）忽略錯誤
        if [ -d "$dir" ] && [ "$(stat -c %u "$dir")" != "$(id -u app)" ]; then
            chown -R app:app "$dir" 2>/dev/null || true
        fi
    done
    exec setpriv --reuid=app --regid=app --init-groups -- "$@"
fi
exec "$@"
