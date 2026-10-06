import type { Brand, Copy, Product, Render } from '@/types/contract';
import { posterBlob } from '@/lib/compose/render';
import { getTemplate } from '@/lib/compose/templates';
import { downloadBlob } from './download';
import { posterFileName, zipFileName } from './naming';
import { buildZip } from './zip';

/** 瀏覽器端匯出（新任務、批次佇列、歷史紀錄共用）。只能在事件處理中呼叫。 */

export interface PosterItem { render: Render; copy: Copy }

const productNameOf = (product: Product | null, items: PosterItem[]) => product?.name ?? items[0]?.copy.productName ?? '商品';

/** 每個模板一張原尺寸 PNG，打包成「品牌_商品_日期.zip」 */
export async function exportPosterZip(brand: Brand, product: Product | null, items: PosterItem[], date = new Date()): Promise<void> {
  const productName = productNameOf(product, items);
  const entries = await Promise.all(items.map(async ({ render, copy }) => ({
    name: posterFileName({ brandName: brand.name, productName, channel: getTemplate(render.templateId).label, date }),
    data: await posterBlob({ render, copy, product, brand }),
  })));
  downloadBlob(await buildZip(entries), zipFileName({ brandName: brand.name, productName, date }));
}

/** 單張 PNG：「品牌_商品_通路_日期.png」 */
export async function exportPosterPng(brand: Brand, product: Product | null, item: PosterItem, date = new Date()): Promise<void> {
  const name = posterFileName({ brandName: brand.name, productName: productNameOf(product, [item]), channel: getTemplate(item.render.templateId).label, date });
  downloadBlob(await posterBlob({ ...item, product, brand }), name);
}
