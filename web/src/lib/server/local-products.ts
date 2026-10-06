import { readdir, stat } from 'node:fs/promises';
import path from 'node:path';

/** 只在伺服器端（Route Handler）使用：讀取 repo 根目錄 assets/products/ 的商品照 */

export const IMAGE_TYPES: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
};

/** next dev 的工作目錄是 web/，商品照放在上一層的 assets/products/ */
export const LOCAL_PRODUCTS_DIR = path.resolve(process.cwd(), '..', 'assets', 'products');

export interface LocalPhoto {
  file: string;
  /** 檔名去掉副檔名，底線與連字號換成空白 */
  name: string;
  url: string;
  size: number;
}

export const localPhotoUrl = (file: string) => `/api/local-products/${encodeURIComponent(file)}`;

/** 列出資料夾內的圖片（依檔名排序）；資料夾不存在時回傳空陣列 */
export async function listLocalPhotos(dir: string): Promise<LocalPhoto[]> {
  let files: string[];
  try {
    files = await readdir(dir);
  } catch {
    return [];
  }
  const photos: LocalPhoto[] = [];
  for (const file of files.sort()) {
    const ext = path.extname(file).toLowerCase();
    if (!IMAGE_TYPES[ext]) continue;
    const info = await stat(path.join(dir, file));
    if (!info.isFile()) continue;
    photos.push({ file, name: path.basename(file, path.extname(file)).replace(/[_-]+/g, ' ').trim(), url: localPhotoUrl(file), size: info.size });
  }
  return photos;
}

/** 檔名 → 絕對路徑與 MIME。拒絕子目錄、路徑穿越與非圖片檔。 */
export function resolveLocalPhoto(dir: string, file: string): { path: string; type: string } | null {
  if (!file || /[\\/]/.test(file) || file.startsWith('.')) return null;
  const type = IMAGE_TYPES[path.extname(file).toLowerCase()];
  if (!type) return null;
  const full = path.resolve(dir, file);
  return path.dirname(full) === path.resolve(dir) ? { path: full, type } : null;
}
