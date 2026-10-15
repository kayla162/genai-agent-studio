import type { Brand, Product } from '@/types/contract';
import { productArtSvg, svgDataUrl } from './art';
import { logoFor } from './scene';

/** 純函式：決定海報要用的商品圖與字型（預覽、匯出、商品庫縮圖共用） */

export interface ProductImageSource { src: string; blend: 'normal' | 'multiply' }

/** 示範商品用 SVG 素材；上傳照片在去背完成後用透明 PNG，去背中、失敗或示意（url 為 null）時以色彩增值（multiply）合成 */
export function productImage(product: Product, brand: Brand): ProductImageSource {
  if (product.photo.source === 'sample') {
    return { src: svgDataUrl(productArtSvg(product.photo.art, brand.palette, product.name, logoFor(brand).wordmark)), blend: 'normal' };
  }
  const cut = product.cutout;
  return cut?.status === 'done' && cut.url ? { src: cut.url, blend: 'normal' } : { src: product.photo.url, blend: 'multiply' };
}

/** 品牌字型（@fontsource-variable 註冊的名稱帶 Variable），找不到時退回系統字型 */
export function fontStacks(brand: Pick<Brand, 'fonts'>): { headline: string; body: string } {
  return {
    headline: `"${brand.fonts.headline} Variable", "${brand.fonts.headline}", "Noto Serif TC", serif`,
    body: `"${brand.fonts.body} Variable", "${brand.fonts.body}", "Noto Sans TC", "Microsoft JhengHei", sans-serif`,
  };
}
