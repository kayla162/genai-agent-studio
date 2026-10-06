import { LOCAL_PRODUCTS_DIR, listLocalPhotos } from '@/lib/server/local-products';

/** 開發用：列出 assets/products/ 的商品照。正式環境回傳 404。 */
export async function GET() {
  if (process.env.NODE_ENV !== 'development') return new Response('Not found', { status: 404 });
  return Response.json({ photos: await listLocalPhotos(LOCAL_PRODUCTS_DIR) });
}
