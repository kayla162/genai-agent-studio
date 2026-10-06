import { readFile } from 'node:fs/promises';
import type { NextRequest } from 'next/server';
import { LOCAL_PRODUCTS_DIR, resolveLocalPhoto } from '@/lib/server/local-products';

/** 開發用：讀取 assets/products/ 的單張商品照。正式環境回傳 404。 */
export async function GET(_req: NextRequest, ctx: RouteContext<'/api/local-products/[file]'>) {
  if (process.env.NODE_ENV !== 'development') return new Response('Not found', { status: 404 });
  const { file } = await ctx.params;
  const hit = resolveLocalPhoto(LOCAL_PRODUCTS_DIR, file);
  if (!hit) return new Response('Not found', { status: 404 });
  try {
    const bytes = await readFile(hit.path);
    return new Response(new Uint8Array(bytes), { headers: { 'Content-Type': hit.type, 'Cache-Control': 'no-store' } });
  } catch {
    return new Response('Not found', { status: 404 });
  }
}
