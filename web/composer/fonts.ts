// composer 伺服器端繪圖用的字型：清空所有字型後，只註冊固定版本的 Noto Sans／Serif TC（npm run fonts 下載）。
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { GlobalFonts } from '@napi-rs/canvas';

/** 前端 `fontStacks` 用到的字型名稱與 fonts.lock.json 中的檔案。一個可變字重檔涵蓋所有字重。 */
export const POSTER_FONTS = [
  { family: 'Noto Sans TC', file: 'NotoSansTC-VF.ttf' },
  { family: 'Noto Serif TC', file: 'NotoSerifTC-VF.ttf' },
] as const;

export const FONTS_HINT = '請在 web/ 執行 npm run fonts 下載字型';

export interface PosterFont { family: string; path: string }

/** 字型資料夾：環境變數 POSTER_FONTS_DIR，沒有設定時為 web/composer/fonts */
export function resolveFontsDir(env: Record<string, string | undefined> = process.env): string {
  return path.resolve(env.POSTER_FONTS_DIR || fileURLToPath(new URL('fonts', import.meta.url)));
}

/** dir 中缺少的字型檔（完整路徑） */
export function missingPosterFonts(dir: string): string[] {
  return POSTER_FONTS.map((f) => path.join(dir, f.file)).filter((p) => !existsSync(p));
}

/**
 * 先清空所有字型（含系統字型），再註冊兩個海報字型。
 * 系統可能裝了另一版 Noto Sans TC（字高不同），不清空的話，繪圖結果會依機器而異。
 * 任一檔案不存在或註冊失敗就丟出錯誤；檔案不存在時不會清空既有字型。
 */
export function registerPosterFonts(dir: string): PosterFont[] {
  const missing = missingPosterFonts(dir);
  if (missing.length) throw new Error(`找不到字型檔：${missing.join('、')}。${FONTS_HINT}`);
  GlobalFonts.removeAll();
  return POSTER_FONTS.map(({ family, file }) => {
    const fontPath = path.join(dir, file);
    if (!GlobalFonts.registerFromPath(fontPath, family)) {
      throw new Error(`字型註冊失敗：${fontPath}（${family}），檔案可能已損毀。${FONTS_HINT}`);
    }
    return { family, path: fontPath };
  });
}
