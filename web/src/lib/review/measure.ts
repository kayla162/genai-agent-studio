import type { LayoutBox } from '@/types/contract';
import { boxMap } from '@/lib/compose/layout';
import type { Rect } from '@/lib/core/geometry';
import { deltaEHex, hexToRgb, labToHex, rgbToLab, type Lab } from './color';

/** 非預乘的 RGBA 像素，逐列排列（canvas `getImageData().data`）。只讀 RGB，假設像素不透明。 */
export type RGBA = Uint8ClampedArray | Uint8Array;

export interface MeasuredPrimary {
  /** 量到的主色；量測範圍內沒有佔比 ≥ 2% 的彩色時為 null */
  hex: string | null;
  /** 這個顏色（峰值周圍 3×3×3 格）的取樣數 ÷ 量測範圍的取樣數，0–1；hex 為 null 時為 0 */
  share: number;
  /** hex 與品牌主色的 ΔE2000；hex 為 null 時為 null */
  deltaE: number | null;
}

/** 主色量測的參數（設計規格 Plan 6A §4.2） */
export const PRIMARY_MEASURE = {
  /** 取樣格的邊長（像素） */
  block: 4,
  /** 彩度門檻 T = min(chromaCap, chromaRatio × 品牌主色的 C*) */
  chromaCap: 10,
  chromaRatio: 0.5,
  /** Lab 直方圖每格的寬度 */
  bin: 3,
  /** 候選峰值的最低佔比 */
  minShare: 0.02,
} as const;

/** 一定以 palette.primary 繪製的區塊；量測範圍是它們的聯集扣掉商品區塊 */
export const PRIMARY_ROLE_IDS = ['headline', 'price', 'badge'] as const;

// 直方圖的格以整數索引表示：((l + OFF) × SPAN + (a + OFF)) × SPAN + (b + OFF)。
// L、a、b 的格號都在 ±43 以內，索引的大小順序就是 (l, a, b) 的字典序；「索引較小者」即字典序較小的格。
const OFF = 64;
const SPAN = 128;
const binIndex = (l: number, a: number, b: number) => ((l + OFF) * SPAN + (a + OFF)) * SPAN + (b + OFF);
/** 3×3×3 鄰域的索引差（含自己），以及去掉自己的 26 個相鄰格 */
const CUBE: number[] = [];
for (let dl = -1; dl <= 1; dl++) {
  for (let da = -1; da <= 1; da++) for (let db = -1; db <= 1; db++) CUBE.push((dl * SPAN + da) * SPAN + db);
}
const NEIGHBOURS = CUBE.filter((d) => d !== 0);

interface Bin { n: number; L: number; a: number; b: number }
interface Candidate { index: number; n: number; hex: string; deltaE: number; chroma: number }

/** ΔE 小者優先；同分時佔比大者，再取索引小者 */
const byDeltaE = (p: Candidate, q: Candidate) => p.deltaE - q.deltaE || q.n - p.n || p.index - q.index;
/** 彩度高者優先；同分時佔比大者，再取索引小者 */
const byChroma = (p: Candidate, q: Candidate) => q.chroma - p.chroma || q.n - p.n || p.index - q.index;
const first = (list: Candidate[], order: (p: Candidate, q: Candidate) => number) =>
  list.reduce((best, c) => (order(c, best) < 0 ? c : best));

const inRect = (x: number, y: number, r: Rect) => x >= r.x && x < r.x + r.w && y >= r.y && y < r.y + r.h;

/**
 * 從繪製好的海報量出品牌主色（設計規格 §4.2）：
 * 1. 範圍：標題、售價、徽章區塊的聯集，扣掉商品區塊。
 * 2. 取樣：完整的 4×4 格，格子中心落在範圍內才採用，取 16 個像素的 sRGB 平均（四捨五入到整數）。
 * 3–4. 轉成 Lab（與 rgbToLab 相同），只保留 C* ≥ T 的取樣。
 * 5. Lab 直方圖（每格 3 單位）：原始計數 ≥ 全部 26 個相鄰格的格為峰值，同分時取索引較小者；
 *    峰值顏色是周圍 3×3×3 格內所有取樣的 Lab 平均，佔比是這些取樣數 ÷ 範圍內的總取樣數。
 * 6–7. 佔比 ≥ 2% 的峰值為候選，取與品牌主色 ΔE2000 最小者；同分時取佔比大者，再取索引小者。
 * 8. 最小 ΔE 超過 maxDeltaE 時（判定一定不通過），改為回報彩度最高的候選，讓說明文字顯示實際用錯的顏色。
 * 9. 沒有候選時 hex 為 null。
 */
export function measurePrimary(
  pixels: RGBA, width: number, height: number, layout: LayoutBox[], brandPrimary: string, maxDeltaE = 5,
): MeasuredPrimary {
  const { block: S, bin: Q } = PRIMARY_MEASURE;
  const boxes = boxMap(layout);
  const include = PRIMARY_ROLE_IDS.map((id) => boxes[id]);
  const product = boxes.product;
  const target = rgbToLab(hexToRgb(brandPrimary));
  const T = Math.min(PRIMARY_MEASURE.chromaCap, PRIMARY_MEASURE.chromaRatio * Math.hypot(target.a, target.b));

  const bins = new Map<number, Bin>();
  let total = 0;
  for (let y0 = 0; y0 + S <= height; y0 += S) {
    for (let x0 = 0; x0 + S <= width; x0 += S) {
      const cx = x0 + S / 2;
      const cy = y0 + S / 2;
      if (inRect(cx, cy, product) || !include.some((r) => inRect(cx, cy, r))) continue;
      let r = 0, g = 0, b = 0;
      for (let y = y0; y < y0 + S; y++) {
        for (let x = x0; x < x0 + S; x++) {
          const i = (y * width + x) * 4;
          r += pixels[i];
          g += pixels[i + 1];
          b += pixels[i + 2];
        }
      }
      total++;
      const lab = rgbToLab([Math.round(r / (S * S)), Math.round(g / (S * S)), Math.round(b / (S * S))]);
      if (Math.hypot(lab.a, lab.b) < T) continue;
      const k = binIndex(Math.floor(lab.L / Q), Math.floor(lab.a / Q), Math.floor(lab.b / Q));
      const bin = bins.get(k);
      if (bin) {
        bin.n++;
        bin.L += lab.L;
        bin.a += lab.a;
        bin.b += lab.b;
      } else {
        bins.set(k, { n: 1, L: lab.L, a: lab.a, b: lab.b });
      }
    }
  }

  const candidates: Candidate[] = [];
  for (const [k, bin] of bins) {
    // 每個相鄰格的計數都較少，或同分但索引較大（d > 0），這格才是峰值
    const isPeak = NEIGHBOURS.every((d) => {
      const nb = bins.get(k + d);
      return !nb || nb.n < bin.n || (nb.n === bin.n && d > 0);
    });
    if (!isPeak) continue;
    const sum = { n: 0, L: 0, a: 0, b: 0 };
    for (const d of CUBE) {
      const nb = bins.get(k + d);
      if (!nb) continue;
      sum.n += nb.n;
      sum.L += nb.L;
      sum.a += nb.a;
      sum.b += nb.b;
    }
    if (sum.n / total < PRIMARY_MEASURE.minShare) continue;
    const lab: Lab = { L: sum.L / sum.n, a: sum.a / sum.n, b: sum.b / sum.n };
    const hex = labToHex(lab);
    candidates.push({ index: k, n: sum.n, hex, deltaE: deltaEHex(hex, brandPrimary), chroma: Math.hypot(lab.a, lab.b) });
  }
  if (!candidates.length) return { hex: null, share: 0, deltaE: null };

  const nearest = first(candidates, byDeltaE);
  const shown = nearest.deltaE <= maxDeltaE ? nearest : first(candidates, byChroma);
  return { hex: shown.hex, share: shown.n / total, deltaE: shown.deltaE };
}
