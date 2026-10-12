# 兩個映像檔：
# - web：nginx 提供 live 版的靜態輸出，並把 /api、/files、/ws、/docs 轉給 api
# - composer：Node 服務，直接執行 src/lib 的 TypeScript（版型與模擬邏輯）
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

FROM source AS composer
ENV HOST=0.0.0.0 PORT=3900
EXPOSE 3900
CMD ["node", "--import", "tsx", "composer/server.ts"]
