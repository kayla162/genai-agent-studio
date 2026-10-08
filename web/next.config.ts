import type { NextConfig } from 'next';
import { PHASE_DEVELOPMENT_SERVER } from 'next/constants';

/**
 * 建置時靜態輸出（out/）：live 版由 nginx 提供，mock 版部署到 Cloudflare Pages。
 * next dev 時若設定 API_PROXY_URL（例如 http://localhost:8000），把 /api 與 /files 轉給本機後端；
 * 靜態輸出不支援 rewrites，所以只在開發伺服器加上。
 */
export default function nextConfig(phase: string): NextConfig {
  const proxy = process.env.API_PROXY_URL;
  if (phase === PHASE_DEVELOPMENT_SERVER) {
    return proxy
      ? {
          rewrites: async () => [
            { source: '/api/:path*', destination: `${proxy}/api/:path*` },
            { source: '/files/:path*', destination: `${proxy}/files/:path*` },
          ],
        }
      : {};
  }
  return { output: 'export', images: { unoptimized: true } };
}
