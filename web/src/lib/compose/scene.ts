import type { Copy, LayoutBox, LayoutElementId, Palette } from '@/types/contract';
import type { Rect } from '@/lib/core/geometry';
import { visLen } from '@/lib/core/text';
import { mixHex } from '@/lib/review/color';
import { boxMap, fitFontSize } from './layout';

/** headline → 品牌標題字型（襯線）；body → 品牌內文字型 */
export type FontRole = 'headline' | 'body';
export type LogoMark = 'crescent' | 'isle' | 'monogram';

/** 一段文字。y 是文字的垂直中心（繪製時 textBaseline = 'middle'）。 */
export interface TextOp {
  kind: 'text';
  el: LayoutElementId;
  text: string;
  x: number;
  y: number;
  size: number;
  weight: number;
  role: FontRole;
  color: string;
  alpha: number;
  align: 'left' | 'center';
  letterSpacing: number;
  strike: boolean;
}
export interface PillOp {
  kind: 'pill';
  el: LayoutElementId;
  rect: Rect;
  fill: string;
  fillAlpha: number;
  stroke: string | null;
  strokeAlpha: number;
  lineWidth: number;
}
export interface BadgeOp {
  kind: 'badge';
  cx: number;
  cy: number;
  r: number;
  /** 角度（度） */
  rotate: number;
  fill: string;
  ring: string;
  shadow: string;
  texts: TextOp[];
}
/** image：品牌的 Logo 圖檔；有圖時畫圖檔，沒有或載入失敗時畫標誌圖形與字標 */
export interface LogoOp { kind: 'logo'; rect: Rect; mark: LogoMark; color: string; wordmark: TextOp | null; image: string | null }
export interface ProductOp { kind: 'product'; rect: Rect; shadow: string }
export type SceneOp = { kind: 'background' } | ProductOp | LogoOp | TextOp | PillOp | BadgeOp;

export interface PosterScene { width: number; height: number; ops: SceneOp[] }

export interface SceneInput {
  canvas: { width: number; height: number };
  layout: LayoutBox[];
  palette: Palette;
  copy: Copy;
  brand: { id: string; name: string; logo?: { url: string } | null };
}

const MARKS: Record<string, LogoMark> = { selune: 'crescent', 'misty-isle': 'isle' };

/** 品牌標誌：已知品牌用專屬圖形，字標取品牌名稱中的拉丁字（沒有就用全名） */
export function logoFor(brand: { id: string; name: string }): { mark: LogoMark; wordmark: string } {
  const latin = brand.name.match(/[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ&.' -]*[A-Za-zÀ-ÿ]/)?.[0];
  return { mark: MARKS[brand.id] ?? 'monogram', wordmark: latin ?? brand.name };
}

/** Logo 圖檔放進 Logo 框：等比例縮放、靠左、垂直置中 */
export function fitLogoImage(box: Rect, width: number, height: number): Rect {
  const scale = Math.min(box.w / width, box.h / height);
  const w = width * scale;
  const h = height * scale;
  return { x: box.x, y: box.y + (box.h - h) / 2, w, h };
}

export const formatPrice = (n: number): string => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');

/** 依 visLen 估算的文字外框（測試與 BBox 疊圖用） */
export function textBounds(op: TextOp): Rect {
  const w = visLen(op.text) * op.size + op.letterSpacing * Math.max(0, [...op.text].length - 1);
  return { x: op.align === 'center' ? op.x - w / 2 : op.x, y: op.y - op.size / 2, w, h: op.size };
}

const CTA_TEXT = '立即選購 →';

type TextInit = Pick<TextOp, 'el' | 'text' | 'x' | 'y' | 'size' | 'color'> & Partial<TextOp>;
const text = (t: TextInit): TextOp => ({
  kind: 'text', weight: 500, role: 'body', alpha: 1, align: 'left', letterSpacing: 0, strike: false, ...t,
});

/**
 * 排版引擎：依版面 BBox 與文案產生繪製指令。字級一律依框的寬高自動縮放，所以使用者改文案時不會溢出。
 * 預覽與匯出共用同一份指令（由 paint.ts 畫到 Canvas）。
 */
export function composePoster({ canvas, layout, palette: P, copy: C, brand }: SceneInput): PosterScene {
  const B = boxMap(layout);
  const ops: SceneOp[] = [{ kind: 'background' }, { kind: 'product', rect: B.product, shadow: P.ink }];

  // Logo：標誌圖形 + 字標
  const L = B.logo;
  const logo = logoFor(brand);
  const wordW = L.w - L.h * 1.12;
  const wordChars = [...logo.wordmark].length;
  const wordSize = Math.min(L.h * 0.62, wordW / (visLen(logo.wordmark) + 0.08 * Math.max(0, wordChars - 1)));
  ops.push({
    kind: 'logo', rect: L, mark: logo.mark, color: P.accent, image: brand.logo?.url ?? null,
    wordmark: wordW > 0
      ? text({ el: 'logo', text: logo.wordmark, x: L.x + L.h * 1.12, y: L.y + L.h / 2, size: wordSize, weight: 700, role: 'headline', color: P.ink, letterSpacing: wordSize * 0.08 })
      : null,
  });

  // 標題：最多兩行，第二行用品牌主色強調
  const H = B.headline;
  const lines = C.headline.filter((l) => l.trim() !== '');
  if (lines.length) {
    const size = fitFontSize(lines, H);
    lines.forEach((line, i) =>
      ops.push(text({ el: 'headline', text: line, x: H.x, y: H.y + size * 1.2 * (i + 0.5), size, weight: 900, role: 'headline', color: i === 0 ? P.ink : P.primary })),
    );
  }

  // 副標
  const S = B.subhead;
  if (C.subhead.trim()) {
    const size = Math.min(S.h * 0.8, S.w / visLen(C.subhead));
    ops.push(text({ el: 'subhead', text: C.subhead, x: S.x, y: S.y + S.h / 2, size, color: P.ink, alpha: 0.85 }));
  }

  // 賣點膠囊：放不下的就不畫
  const F = B.features;
  const features = C.features.filter((f) => f.trim() !== '');
  if (features.length) {
    const size = Math.min(F.h * 0.46, F.w / (visLen(features[0]) + 1.5));
    const pad = size * 0.75;
    let x = F.x;
    for (const f of features) {
      const w = visLen(f) * size + pad * 2;
      if (x + w > F.x + F.w) break;
      ops.push({ kind: 'pill', el: 'features', rect: { x, y: F.y, w, h: F.h }, fill: '#ffffff', fillAlpha: 0.72, stroke: P.primary, strokeAlpha: 0.45, lineWidth: F.h * 0.03 });
      ops.push(text({ el: 'features', text: f, x: x + w / 2, y: F.y + F.h / 2, size, align: 'center', color: mixHex(P.primary, P.ink, 0.3) }));
      x += w + size * 0.45;
    }
  }

  // 價格：商品名稱｜價格標籤、特價、原價；寬版型右側加 CTA
  const R = B.price;
  const cta = R.w / R.h > 3;
  const top = [C.productName, C.price.label].filter((s) => s.trim() !== '').join('｜');
  if (top) {
    const size = Math.min(R.h * 0.15, (cta ? R.w * 0.62 : R.w) / visLen(top));
    ops.push(text({ el: 'price', text: top, x: R.x, y: R.y + R.h * 0.1, size, color: P.ink, alpha: 0.72 }));
  }
  const sale = formatPrice(C.price.sale);
  const saleSize = Math.min(R.h * 0.46, (cta ? R.w * 0.6 : R.w * 0.95) / (visLen(sale) + 1));
  const prefixSize = saleSize * 0.42;
  ops.push(text({ el: 'price', text: 'NT$', x: R.x, y: R.y + R.h * 0.55, size: prefixSize, weight: 700, color: P.primary }));
  ops.push(text({ el: 'price', text: sale, x: R.x + prefixSize * 2.2, y: R.y + R.h * 0.53, size: saleSize, weight: 900, role: 'headline', color: P.primary }));
  if (C.price.original > C.price.sale) {
    const orig = `原價 NT$${formatPrice(C.price.original)}`;
    const size = Math.min(R.h * 0.13, (cta ? R.w * 0.6 : R.w) / visLen(orig));
    ops.push(text({ el: 'price', text: orig, x: R.x, y: R.y + R.h * 0.9, size, color: P.ink, alpha: 0.5, strike: true }));
  }
  if (cta) {
    const size = R.h * 0.16;
    const w = visLen(CTA_TEXT) * size + size * 2.4;
    const h = size * 2.5;
    const rect = { x: R.x + R.w - w, y: R.y + R.h * 0.5 - h / 2, w, h };
    ops.push({ kind: 'pill', el: 'price', rect, fill: P.ink, fillAlpha: 1, stroke: null, strokeAlpha: 0, lineWidth: 0 });
    ops.push(text({ el: 'price', text: CTA_TEXT, x: rect.x + w / 2, y: rect.y + h / 2, size, weight: 700, align: 'center', color: '#ffffff' }));
  }

  // 頁尾註記
  const D = B.disclaimer;
  if (C.disclaimer.trim()) {
    const size = Math.min(D.h * 0.75, D.w / visLen(C.disclaimer));
    ops.push(text({ el: 'disclaimer', text: C.disclaimer, x: D.x, y: D.y + D.h / 2, size, weight: 400, color: P.ink, alpha: 0.55 }));
  }

  // 促銷徽章（z 最高，最後畫）
  const G = B.badge;
  if (C.badge.main.trim()) {
    const r = Math.min(G.w, G.h) / 2;
    const cx = G.x + G.w / 2;
    const cy = G.y + G.h / 2;
    const texts: TextOp[] = [];
    if (C.badge.top.trim()) {
      texts.push(text({ el: 'badge', text: C.badge.top, x: cx, y: cy - r * 0.42, size: Math.min(r * 0.15, (r * 1.3) / visLen(C.badge.top)), align: 'center', color: P.secondary }));
    }
    texts.push(text({ el: 'badge', text: C.badge.main, x: cx, y: cy + r * 0.02, size: Math.min(r * 0.4, (r * 1.45) / visLen(C.badge.main)), weight: 900, role: 'headline', align: 'center', color: '#ffffff' }));
    if (C.badge.sub.trim()) {
      const n = [...C.badge.sub].length;
      const size = Math.min(r * 0.105, (r * 1.3) / (visLen(C.badge.sub) + 0.28 * Math.max(0, n - 1)));
      texts.push(text({ el: 'badge', text: C.badge.sub, x: cx, y: cy + r * 0.46, size, weight: 700, align: 'center', color: mixHex(P.accent, '#ffffff', 0.35), letterSpacing: size * 0.28 }));
    }
    ops.push({ kind: 'badge', cx, cy, r, rotate: -6, fill: P.primary, ring: P.accent, shadow: P.ink, texts });
  }

  return { width: canvas.width, height: canvas.height, ops };
}
