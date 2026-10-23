# 兩個映像檔：
# - web：nginx 提供 live 版的靜態輸出，並把 /api、/files、/ws、/docs 轉給 api
# - composer：Node 服務，直接執行 src/lib 的 TypeScript（版型、伺服器端繪圖、審查與模擬邏輯）
FROM public.ecr.aws/docker/library/node:24-alpine AS source
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app/web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .

FROM source AS build
RUN NEXT_PUBLIC_API_MODE=live npm run build

FROM public.ecr.aws/docker/library/nginx:1.29-alpine AS web
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/web/out /usr/share/nginx/html

# 海報字型與授權文字：網址與 SHA-256 必須和 composer/fonts.lock.json 相同（composer/dockerfile.test.ts 會檢查）。
# 下載內容與 checksum 不符時建置失敗；只有建置 composer 時才會下載。
FROM scratch AS fonts
ADD --checksum=sha256:864727d210d54f2537bbe23b3a839436c3992af72de9322af5270897246bd44f \
    "https://raw.githubusercontent.com/google/fonts/45e3d5269e4a17d823f6d84470bc084dc5ae46f6/ofl/notosanstc/NotoSansTC%5Bwght%5D.ttf" \
    /NotoSansTC-VF.ttf
ADD --checksum=sha256:0077e18f57c6908f4a000969880940bdb0dad057c0e8d98b49dc364c3d1b09c6 \
    "https://raw.githubusercontent.com/google/fonts/45e3d5269e4a17d823f6d84470bc084dc5ae46f6/ofl/notoseriftc/NotoSerifTC%5Bwght%5D.ttf" \
    /NotoSerifTC-VF.ttf
ADD --checksum=sha256:1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9 \
    "https://raw.githubusercontent.com/google/fonts/45e3d5269e4a17d823f6d84470bc084dc5ae46f6/ofl/notosanstc/OFL.txt" \
    /OFL-NotoSansTC.txt
ADD --checksum=sha256:5e0da210fb04058a8c0087985d2d456b931c2579811a49655721d3cf0c36b6d6 \
    "https://raw.githubusercontent.com/google/fonts/45e3d5269e4a17d823f6d84470bc084dc5ae46f6/ofl/notoseriftc/OFL.txt" \
    /OFL-NotoSerifTC.txt

FROM source AS composer
# ADD 下載的檔案權限是 0600：先建立資料夾（0755），再以 0644 複製檔案，任何使用者都讀得到。
# 不先建立資料夾的話，--chmod 也會套用到 COPY 自動建立的資料夾，變成無法進入。授權文字（OFL）和字型放在一起。
RUN mkdir -p /usr/local/share/poster-fonts
COPY --chmod=0644 --from=fonts \
    /NotoSansTC-VF.ttf /NotoSerifTC-VF.ttf /OFL-NotoSansTC.txt /OFL-NotoSerifTC.txt \
    /usr/local/share/poster-fonts/
ENV POSTER_FONTS_DIR=/usr/local/share/poster-fonts
ENV HOST=0.0.0.0 PORT=3900
EXPOSE 3900
CMD ["node", "--import", "tsx", "composer/server.ts"]
