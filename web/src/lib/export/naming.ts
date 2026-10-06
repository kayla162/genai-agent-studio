const pad = (n: number) => String(n).padStart(2, '0');

/** 去掉空白與檔名不允許的字元 */
export const safeName = (s: string): string => s.replace(/[\\/:*?"<>|\s]+/g, '') || '未命名';

/** 本地日期 YYYYMMDD */
export const dateStamp = (d: Date): string => `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`;

export interface PosterNameParts { brandName: string; productName: string; channel: string; date: Date }

/** 「品牌_商品_通路_日期.png」 */
export const posterFileName = ({ brandName, productName, channel, date }: PosterNameParts): string =>
  `${safeName(brandName)}_${safeName(productName)}_${safeName(channel)}_${dateStamp(date)}.png`;

/** 「品牌_商品_日期.zip」 */
export const zipFileName = ({ brandName, productName, date }: Omit<PosterNameParts, 'channel'>): string =>
  `${safeName(brandName)}_${safeName(productName)}_${dateStamp(date)}.zip`;
