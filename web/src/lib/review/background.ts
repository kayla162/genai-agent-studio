import type { BBox, Palette, ReviewCheck } from '@/types/contract';
import { hexToRgb, labToHex, rgbToLab } from './color';
import type { RGBA } from './measure';

/** 背景色系量測的參數（Plan 7 規格 §4.8；標示「實驗決定」的在 Plan 7 Task 1 依實測調整） */
export const BACKGROUND_MEASURE: {
  neutralChroma: number; brandMinChroma: number; hueTolerance: number; chromaMargin: number;
  productMargin: number; sampleSide: number; bin: number;
} = {
  /** 彩度 C* 低於這個值為中性色，一律在色系內（Plan 7 規格 §12：很淡的灰綠、灰米色的色相不穩定，視為中性） */
  neutralChroma: 18,
  /** 品牌色的彩度至少這麼高才當作色相參考（很暗、很淡的品牌色，例如 misty-isle 的深青綠 C* 11.8，仍有色相） */
  brandMinChroma: 5,
  /** 與品牌色的色相差 ≤ 這個角度（度）才算同一色系（實驗決定） */
  hueTolerance: 30,
  /** 彩度最多比同色系的品牌色高出這麼多，再高就是過度飽和（螢光色）。規格 §12 以實驗存下的 24 張背景校準：
   *  15 時一般背景全部 ≤ 4%、刻意偏色的 9 張有 7 張不通過；12 時一般背景開始出現警告 */
  chromaMargin: 15,
  /** 商品方框向外擴張的比例（× 畫布短邊） */
  productMargin: 0.02,
  /** 取樣格的邊數上限：大圖以等距取樣，最多約 sampleSide × sampleSide 個像素 */
  sampleSide: 256,
  /** 找色系外主要顏色時，Lab 量化的格寬 */
  bin: 8,
};

/** 背景色系外的面積比例 ≤ 這個值為通過（實驗決定，Plan 7 規格 §4.8） */
export const BG_PASS_MAX = 0.15;
/** 背景色系外的面積比例 ≤ 這個值為警告，超過為不通過（實驗決定） */
export const BG_WARN_MAX = 0.3;

/** 背景色系的量測結果（composer 從疊上文字與商品之前的背景量出；Plan 7 規格 §4.8） */
export interface BackgroundPalette {
  /** 商品方框以外、品牌色系外的像素比例（0–1） */
  offShare: number;
  /** 色系外像素中最多的顏色（#RRGGBB）；沒有色系外的像素時為 null */
  offHex: string | null;
  /** 量測的像素數 */
  sampled: number;
}

/** 背景的不透明像素（canvas `getImageData()` 的結果），可以是縮小後的樣本 */
export interface BackgroundPixels { data: RGBA; width: number; height: number }

interface Hue { h: number; c: number }

const hueOf = (L: { a: number; b: number }): Hue => ({ h: (Math.atan2(L.b, L.a) * 180) / Math.PI, c: Math.hypot(L.a, L.b) });
const hueGap = (x: number, y: number) => {
  const d = Math.abs(x - y) % 360;
  return d > 180 ? 360 - d : d;
};

/**
 * 量背景的品牌色系（Plan 7 規格 §4.8）：
 * 1. 範圍：商品方框（向外擴張 productMargin × 畫布短邊）以外的像素；pixels 可以比畫布小，方框依比例換算。
 * 2. 取樣：每 step 個像素取一個（step 讓取樣數不超過 sampleSide²）。
 * 3. 每個像素轉成 Lab 與 LCh：C* < neutralChroma 為中性色；與任一品牌色（C* ≥ brandMinChroma）的色相差
 *    ≤ hueTolerance 且彩度 ≤ 該品牌色彩度 + chromaMargin 為色系內；其他（含過度飽和）為色系外。
 * 4. offShare：色系外 ÷ 取樣數；offHex：色系外像素依 Lab 量化（bin）後最多的一格的平均色（大寫 #RRGGBB）。
 */
export function measureBackgroundPalette(
  pixels: BackgroundPixels, product: BBox, canvas: { width: number; height: number }, palette: Palette,
  params: typeof BACKGROUND_MEASURE = BACKGROUND_MEASURE,
): BackgroundPalette {
  // params：校準門檻時以不同的參數重新量（Plan 7 規格 §12），平常用預設值
  const M = params;
  const { data, width, height } = pixels;
  const sx = width / canvas.width;
  const sy = height / canvas.height;
  const margin = M.productMargin * Math.min(canvas.width, canvas.height);
  const [px, py, pw, ph] = product;
  const hasProduct = pw > 0 && ph > 0;
  const x0 = (px - margin) * sx, x1 = (px + pw + margin) * sx;
  const y0 = (py - margin) * sy, y1 = (py + ph + margin) * sy;
  const brand = [palette.primary, palette.secondary, palette.accent, palette.ink]
    .map((hex) => hueOf(rgbToLab(hexToRgb(hex))))
    .filter((p) => p.c >= M.brandMinChroma);
  const step = Math.max(1, Math.ceil(Math.max(width, height) / M.sampleSide));

  const bins = new Map<string, { n: number; L: number; a: number; b: number }>();
  let sampled = 0;
  let off = 0;
  for (let y = Math.floor(step / 2); y < height; y += step) {
    for (let x = Math.floor(step / 2); x < width; x += step) {
      if (hasProduct && x + 0.5 >= x0 && x + 0.5 < x1 && y + 0.5 >= y0 && y + 0.5 < y1) continue;
      sampled++;
      const i = (y * width + x) * 4;
      const lab = rgbToLab([data[i], data[i + 1], data[i + 2]]);
      const p = hueOf(lab);
      if (p.c < M.neutralChroma) continue;
      if (brand.some((q) => hueGap(p.h, q.h) <= M.hueTolerance && p.c <= q.c + M.chromaMargin)) continue;
      off++;
      const key = `${Math.floor(lab.L / M.bin)},${Math.floor(lab.a / M.bin)},${Math.floor(lab.b / M.bin)}`;
      const bin = bins.get(key) ?? { n: 0, L: 0, a: 0, b: 0 };
      bin.n++;
      bin.L += lab.L;
      bin.a += lab.a;
      bin.b += lab.b;
      bins.set(key, bin);
    }
  }
  // 最多的一格；同分時取先出現的（Map 依插入順序）
  const top = [...bins.values()].reduce<{ n: number; L: number; a: number; b: number } | null>(
    (best, bin) => (!best || bin.n > best.n ? bin : best), null,
  );
  return {
    offShare: sampled ? off / sampled : 0,
    offHex: top ? labToHex({ L: top.L / top.n, a: top.a / top.n, b: top.b / top.n }).toUpperCase() : null,
    sampled,
  };
}

/** 背景色系檢查說明中色系外的主要顏色：`色系外 42%（主要為 #3FD27A）`（hex 為大寫） */
export const OFF_PALETTE_LABEL = '主要為';
const OFF_PALETTE_PATTERN = new RegExp(`${OFF_PALETTE_LABEL} (#[0-9A-F]{6})）$`);

/**
 * 背景色系檢查（bg_palette）的判定。沒有量測結果（模擬模式、前端 mock）時為通過，說明為「（模擬）」，
 * 與 VLM 模擬檢查的標示一致。
 */
export function bgPaletteCheck(result: BackgroundPalette | null | undefined): Pick<ReviewCheck, 'value' | 'status' | 'target'> {
  if (!result) return { value: '（模擬）', status: 'pass', target: 'canvas' };
  const pct = Math.round(result.offShare * 100);
  const hex = result.offHex?.toUpperCase() ?? null;
  const status = result.offShare <= BG_PASS_MAX ? 'pass' : result.offShare <= BG_WARN_MAX ? 'warn' : 'fail';
  const value = status !== 'pass' && hex ? `色系外 ${pct}%（${OFF_PALETTE_LABEL} ${hex}）` : `色系外 ${pct}%`;
  return { value, status, target: 'canvas' };
}

/** 背景色系檢查說明文字裡色系外的主要顏色（#RRGGBB）；其他檢查或沒有時為 null。審查面板依此畫出色塊。 */
export function measuredBackgroundOf(check: Pick<ReviewCheck, 'id' | 'value'>): string | null {
  return check.id === 'bg_palette' ? (OFF_PALETTE_PATTERN.exec(check.value)?.[1] ?? null) : null;
}
