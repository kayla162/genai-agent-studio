import type { Rect } from '@/lib/core/geometry';
import type { BadgeOp, LogoOp, PillOp, PosterScene, ProductOp, TextOp } from './scene';
import { fitLogoImage, textBounds } from './scene';

/** 繪製海報需要的圖片與字型（由 render.ts 準備） */
export interface PaintAssets {
  background: CanvasImageSource;
  /** blend = multiply：沒有真正去背的商品照，用色彩增值讓白底融入背景 */
  product: { image: CanvasImageSource; width: number; height: number; blend: 'normal' | 'multiply' } | null;
  /** 品牌的 Logo 圖檔（品牌沒有 Logo 圖檔或載入失敗時為 null） */
  logo: { image: CanvasImageSource; width: number; height: number } | null;
  /** CSS font-family 字串 */
  fonts: { headline: string; body: string };
}

type Ctx = CanvasRenderingContext2D;

function drawText(ctx: Ctx, op: TextOp, fonts: PaintAssets['fonts']) {
  ctx.save();
  ctx.font = `${op.weight} ${op.size}px ${op.role === 'headline' ? fonts.headline : fonts.body}`;
  ctx.fillStyle = op.color;
  ctx.globalAlpha = op.alpha;
  ctx.textAlign = op.align;
  ctx.textBaseline = 'middle';
  ctx.letterSpacing = `${op.letterSpacing}px`;
  // 版型以估算字寬排版；實際字型較寬時用 maxWidth 壓縮，保證不超出 BBox
  const maxWidth = textBounds(op).w * 1.04;
  ctx.fillText(op.text, op.x, op.y, maxWidth);
  if (op.strike) {
    const w = Math.min(ctx.measureText(op.text).width, maxWidth);
    const x0 = op.align === 'center' ? op.x - w / 2 : op.x;
    ctx.fillRect(x0, op.y - op.size * 0.04, w, Math.max(1, op.size * 0.07));
  }
  ctx.restore();
}

function drawPill(ctx: Ctx, op: PillOp) {
  const { x, y, w, h } = op.rect;
  ctx.save();
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, h / 2);
  ctx.globalAlpha = op.fillAlpha;
  ctx.fillStyle = op.fill;
  ctx.fill();
  if (op.stroke) {
    ctx.globalAlpha = op.strokeAlpha;
    ctx.strokeStyle = op.stroke;
    ctx.lineWidth = op.lineWidth;
    ctx.stroke();
  }
  ctx.restore();
}

function drawBadge(ctx: Ctx, op: BadgeOp, fonts: PaintAssets['fonts']) {
  const { cx, cy, r } = op;
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate((op.rotate * Math.PI) / 180);
  ctx.translate(-cx, -cy);
  ctx.save();
  ctx.shadowColor = `${op.shadow}38`;
  ctx.shadowBlur = r * 0.12;
  ctx.shadowOffsetY = r * 0.04;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fillStyle = op.fill;
  ctx.fill();
  ctx.restore();
  ctx.beginPath();
  ctx.arc(cx, cy, r * 0.86, 0, Math.PI * 2);
  ctx.setLineDash([r * 0.05, r * 0.035]);
  ctx.lineWidth = r * 0.018;
  ctx.strokeStyle = op.ring;
  ctx.stroke();
  ctx.setLineDash([]);
  for (const t of op.texts) drawText(ctx, t, fonts);
  ctx.restore();
}

function drawLogo(ctx: Ctx, op: LogoOp, assets: PaintAssets) {
  if (op.image && assets.logo) {
    const r = fitLogoImage(op.rect, assets.logo.width, assets.logo.height);
    ctx.drawImage(assets.logo.image, r.x, r.y, r.w, r.h);
    return;
  }
  const fonts = assets.fonts;
  const { x, y, h: s } = op.rect;
  ctx.save();
  ctx.fillStyle = op.color;
  if (op.mark === 'crescent') {
    const r = s * 0.42;
    const cx = x + r;
    const cy = y + s / 2;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.clip();
    ctx.beginPath();
    ctx.rect(cx - r, cy - r, r * 2, r * 2);
    ctx.arc(cx + r * 0.45, cy - r * 0.28, r * 0.82, 0, Math.PI * 2);
    ctx.fill('evenodd');
  } else if (op.mark === 'isle') {
    ctx.beginPath();
    ctx.moveTo(x + s * 0.04, y + s * 0.78);
    ctx.lineTo(x + s * 0.36, y + s * 0.22);
    ctx.lineTo(x + s * 0.58, y + s * 0.6);
    ctx.lineTo(x + s * 0.7, y + s * 0.42);
    ctx.lineTo(x + s * 0.96, y + s * 0.78);
    ctx.closePath();
    ctx.fill();
    ctx.lineWidth = s * 0.05;
    ctx.strokeStyle = op.color;
    ctx.beginPath();
    ctx.moveTo(x + s * 0.08, y + s * 0.9);
    ctx.quadraticCurveTo(x + s * 0.3, y + s * 0.82, x + s * 0.5, y + s * 0.9);
    ctx.quadraticCurveTo(x + s * 0.7, y + s * 0.98, x + s * 0.92, y + s * 0.9);
    ctx.stroke();
  } else {
    ctx.beginPath();
    ctx.arc(x + s / 2, y + s / 2, s * 0.45, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.font = `700 ${s * 0.5}px ${fonts.headline}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText([...(op.wordmark?.text ?? '?')][0], x + s / 2, y + s / 2);
  }
  ctx.restore();
  if (op.wordmark) drawText(ctx, op.wordmark, fonts);
}

/** 等比縮放放進框內，底部對齊（商品站在桌面上）；ComfyUI 的商品底圖（plate.ts）以同一個矩形放商品 */
export function containBottom(rect: Rect, w: number, h: number): Rect {
  const s = Math.min(rect.w / w, rect.h / h);
  const dw = w * s;
  const dh = h * s;
  return { x: rect.x + (rect.w - dw) / 2, y: rect.y + rect.h - dh, w: dw, h: dh };
}

function drawProduct(ctx: Ctx, op: ProductOp, product: PaintAssets['product']) {
  if (!product) return;
  const d = containBottom(op.rect, product.width, product.height);
  ctx.save();
  if (product.blend === 'multiply') {
    // 接觸陰影（示範素材本身已含陰影）
    ctx.save();
    ctx.filter = `blur(${Math.max(2, d.w * 0.03)}px)`;
    ctx.globalAlpha = 0.18;
    ctx.fillStyle = op.shadow;
    ctx.beginPath();
    ctx.ellipse(d.x + d.w / 2, d.y + d.h * 0.98, d.w * 0.42, d.h * 0.035, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    ctx.globalCompositeOperation = 'multiply';
  }
  ctx.drawImage(product.image, d.x, d.y, d.w, d.h);
  ctx.restore();
}

/** 依 composePoster 的指令畫到 Canvas（座標是輸出圖的像素；呼叫端自行 scale） */
export function paintScene(ctx: Ctx, scene: PosterScene, assets: PaintAssets): void {
  for (const op of scene.ops) {
    switch (op.kind) {
      case 'background':
        ctx.drawImage(assets.background, 0, 0, scene.width, scene.height);
        break;
      case 'product':
        drawProduct(ctx, op, assets.product);
        break;
      case 'logo':
        drawLogo(ctx, op, assets);
        break;
      case 'text':
        drawText(ctx, op, assets.fonts);
        break;
      case 'pill':
        drawPill(ctx, op);
        break;
      case 'badge':
        drawBadge(ctx, op, assets.fonts);
        break;
    }
  }
}
