import type { Palette } from '@/types/contract';
import { hexToRgb, rgbToLab } from '@/lib/review/color';

/*
 * 品牌色票的英文顏色名稱，放進生圖的正面提示詞。SDXL 看不懂 #B76E79 這樣的色碼（Plan 7 規格 §12：
 * 以色碼寫提示詞時，SÉLUNE 的玫瑰色系背景常生成綠色），改用 LCh 的明度、彩度與色相組出名稱。
 */

/** Lab 色相角（度）→ 色名；依序比對上限 */
const HUES: [max: number, name: string][] = [
  [20, 'rose'],
  [45, 'coral'],
  [70, 'terracotta'],
  [100, 'gold'],
  [130, 'olive'],
  [165, 'green'],
  [200, 'teal green'],
  [250, 'teal'],
  [285, 'blue'],
  [320, 'lavender'],
  [345, 'mauve'],
  [360, 'rose'],
];
/** 彩度低於這個值為中性色 */
const NEUTRAL = 8;

/** 一個色碼的英文名稱，例如 #B76E79 → dusty rose、#F6EFE9 → warm off-white */
export function colorWords(hex: string): string {
  const { L, a, b } = rgbToLab(hexToRgb(hex));
  const chroma = Math.hypot(a, b);
  if (chroma < NEUTRAL) {
    const tone = L > 85 ? 'off-white' : L > 60 ? 'light gray' : L > 35 ? 'gray' : 'charcoal';
    // 偏暖的白（米白、象牙）
    return L > 85 && b > 3 ? `warm ${tone}` : tone;
  }
  const hue = (Math.atan2(b, a) * 180) / Math.PI + (b < 0 ? 360 : 0);
  let name = HUES.find(([max]) => hue < max)![1];
  // 飽和的顏色用最常見的名稱：Lab 的純紅色相約 40°、純藍約 300°；淡的藍紫才是 lavender
  if (chroma > 55 && hue < 45) name = 'red';
  if (chroma > 45 && hue >= 250 && hue < 320) name = 'blue';
  const depth = L < 35 ? 'deep ' : '';
  const strength = chroma < 22 ? 'muted ' : chroma < 34 && L >= 60 ? 'soft ' : chroma < 34 ? 'dusty ' : '';
  // 金色的彩度本來就高：低於 40 已是霧金
  const adjective = name === 'gold' ? (chroma < 40 ? 'muted ' : '') : strength;
  return `${depth}${adjective}${name}`.trim();
}

/** 正面提示詞的配色描述：主色、輔助色與點綴色的名稱 */
export function paletteWords(palette: Palette): string {
  return `${colorWords(palette.primary)} and ${colorWords(palette.secondary)} color palette with ${colorWords(palette.accent)} accents`;
}
