import type { Palette } from '@/types/contract';
import type { Rect } from '@/lib/core/geometry';
import { mulberry32, round1 as r1 } from '@/lib/core/num';
import { visLen } from '@/lib/core/text';
import { mixHex } from '@/lib/review/color';

/** 程序化 SVG 素材：背景（第二階段由 ComfyUI 生成的圖取代）與示範商品圖。全部是純字串，不含文字以外的外部資源。 */

const SVG_NS = 'http://www.w3.org/2000/svg';
const SERIF = "'Noto Serif TC',serif";
const SANS = "'Noto Sans TC',sans-serif";

export const esc = (s: string) =>
  s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] ?? c);

/** t > 0 往白色混、t < 0 往黑色混 */
export const shade = (hex: string, t: number) => mixHex(hex, t < 0 ? '#000000' : '#ffffff', Math.abs(t));

export const svgDataUrl = (svg: string) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;

export interface BackgroundOptions {
  width: number;
  height: number;
  palette: Palette;
  seed: number;
  /** 背景風格（目前以品牌 id 區分） */
  style: string;
  /** 商品所在的框，光暈與桌面會以它為中心 */
  focus: Rect;
}

function seluneBackground({ width: W, height: H, palette: P, seed, focus: F }: BackgroundOptions): string {
  const R = mulberry32(seed);
  const cx = F.x + F.w / 2;
  const cy = F.y + F.h * 0.48;
  const halo = Math.min(F.w, F.h) * 0.46;
  let o = `<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${P.secondary}"/><stop offset=".55" stop-color="${mixHex(P.secondary, P.primary, 0.16)}"/><stop offset="1" stop-color="${mixHex(P.secondary, P.primary, 0.45)}"/></linearGradient>
<radialGradient id="glow"><stop offset="0" stop-color="#fff" stop-opacity=".9"/><stop offset=".45" stop-color="${mixHex(P.secondary, '#ffffff', 0.5)}" stop-opacity=".55"/><stop offset="1" stop-color="${P.secondary}" stop-opacity="0"/></radialGradient>
<linearGradient id="rib" x1="0" x2="1"><stop offset="0" stop-color="${P.primary}" stop-opacity="0"/><stop offset=".4" stop-color="${P.primary}"/><stop offset=".7" stop-color="${P.accent}"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
<filter id="blur" x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur stdDeviation="${r1(W * 0.012)}"/></filter>
</defs>`;
  o += `<rect width="${W}" height="${H}" fill="url(#bg)"/>`;
  o += `<circle cx="${r1(cx)}" cy="${r1(cy)}" r="${r1(F.w * 0.75)}" fill="url(#glow)"/>`;
  [0.3, 0.58, 0.84].forEach((k, i) => {
    const y0 = H * k + (R() - 0.5) * H * 0.06;
    const d = `M${r1(-W * 0.1)} ${r1(y0)} C${r1(W * 0.3)} ${r1(y0 - H * 0.12)} ${r1(W * 0.62)} ${r1(y0 + H * 0.1)} ${r1(W * 1.1)} ${r1(y0 - H * 0.05)}`;
    o += `<path d="${d}" fill="none" stroke="url(#rib)" stroke-width="${r1(W * (0.05 - i * 0.012))}" opacity=".32" filter="url(#blur)"/>`;
    o += `<path d="${d}" fill="none" stroke="${P.accent}" stroke-width="${r1(W * 0.0016)}" opacity=".55" transform="translate(0 ${r1(H * 0.018)})"/>`;
  });
  o += `<circle cx="${r1(cx)}" cy="${r1(cy)}" r="${r1(halo)}" fill="#fff" fill-opacity=".38"/>`;
  o += `<circle cx="${r1(cx)}" cy="${r1(cy)}" r="${r1(halo * 1.08)}" fill="none" stroke="${P.accent}" stroke-width="${r1(W * 0.0018)}" opacity=".75"/>`;
  for (let i = 0; i < 24; i++) {
    const x = R() * W, y = R() * H, rr = W * (0.003 + R() * 0.014), col = R() < 0.3 ? P.accent : '#ffffff', op = 0.25 + R() * 0.45;
    o += `<circle cx="${r1(x)}" cy="${r1(y)}" r="${r1(rr)}" fill="${col}" opacity="${r1(op)}"/>`;
  }
  return o;
}

function mistyBackground({ width: W, height: H, palette: P, seed, focus: F }: BackgroundOptions): string {
  const R = mulberry32(seed);
  const table = F.y + F.h * 0.9;
  const tilt = (R() - 0.5) * W * 0.08;
  let o = `<defs>
<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${mixHex(P.secondary, '#ffffff', 0.4)}"/><stop offset=".6" stop-color="${P.secondary}"/><stop offset="1" stop-color="${mixHex(P.secondary, P.primary, 0.18)}"/></linearGradient>
<linearGradient id="desk" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${mixHex(P.secondary, P.accent, 0.35)}"/><stop offset="1" stop-color="${mixHex(P.secondary, P.accent, 0.6)}"/></linearGradient>
<filter id="soft" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="${r1(W * 0.02)}"/></filter>
<filter id="mist" x="-20%" y="-100%" width="140%" height="300%"><feGaussianBlur stdDeviation="${r1(H * 0.03)}"/></filter>
</defs>`;
  o += `<rect width="${W}" height="${H}" fill="url(#bg)"/>`;
  // 窗光：左上斜射的光帶
  for (let i = 0; i < 3; i++) {
    const x0 = W * (0.05 + i * 0.16) + tilt;
    const w = W * (0.06 + R() * 0.04);
    o += `<path d="M${r1(x0)} 0 H${r1(x0 + w)} L${r1(x0 + w + W * 0.35)} ${r1(table)} H${r1(x0 + W * 0.35)} Z" fill="#fff" opacity=".28" filter="url(#soft)"/>`;
  }
  // 晨霧
  [0.22, 0.45, 0.68].forEach((k) => {
    o += `<ellipse cx="${r1(W * (0.3 + R() * 0.4))}" cy="${r1(H * k)}" rx="${r1(W * 0.6)}" ry="${r1(H * 0.05)}" fill="#fff" opacity=".45" filter="url(#mist)"/>`;
  });
  // 霧面陶瓷桌面與商品投影
  o += `<rect x="0" y="${r1(table)}" width="${W}" height="${r1(H - table)}" fill="url(#desk)"/>`;
  o += `<rect x="0" y="${r1(table)}" width="${W}" height="${r1(H * 0.004)}" fill="#fff" opacity=".6"/>`;
  const sx = F.x + F.w * 0.5;
  o += `<path d="M${r1(sx - F.w * 0.2)} ${r1(table)} L${r1(sx + F.w * 0.2)} ${r1(table)} L${r1(sx + F.w * 0.75)} ${r1(table + (H - table) * 0.7)} L${r1(sx + F.w * 0.25)} ${r1(table + (H - table) * 0.7)} Z" fill="${P.ink}" opacity=".12" filter="url(#soft)"/>`;
  for (let i = 0; i < 18; i++) {
    o += `<circle cx="${r1(R() * W)}" cy="${r1(R() * table)}" r="${r1(W * (0.002 + R() * 0.004))}" fill="${P.accent}" opacity=".25"/>`;
  }
  return o;
}

function plainBackground({ width: W, height: H, palette: P, seed }: BackgroundOptions): string {
  const R = mulberry32(seed);
  let o = `<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${P.secondary}"/><stop offset="1" stop-color="${mixHex(P.secondary, P.primary, 0.3)}"/></linearGradient></defs>`;
  o += `<rect width="${W}" height="${H}" fill="url(#bg)"/>`;
  for (let i = 0; i < 16; i++) {
    o += `<circle cx="${r1(R() * W)}" cy="${r1(R() * H)}" r="${r1(W * (0.004 + R() * 0.012))}" fill="#fff" opacity=".4"/>`;
  }
  return o;
}

const STYLES: Record<string, (o: BackgroundOptions) => string> = { selune: seluneBackground, 'misty-isle': mistyBackground };

/** 依品牌色、模板比例與 seed 產生的背景（模擬 ComfyUI 生成的情境背景）。同一組參數輸出相同字串。 */
export function backgroundSvg(opts: BackgroundOptions): string {
  const body = (STYLES[opts.style] ?? plainBackground)(opts);
  return `<svg xmlns="${SVG_NS}" width="${opts.width}" height="${opts.height}" viewBox="0 0 ${opts.width} ${opts.height}">${body}</svg>`;
}

/** 由商品名稱產生瓶身標籤：去掉容量後超過 6 個字就拆成兩行 */
export function bottleLabel(name: string): { lines: string[]; size: string } {
  const m = name.match(/(\d+)\s*(ml|g)\s*$/i);
  const size = m ? `${m[1]} ${m[2].toLowerCase()}` : '';
  const base = (m ? name.slice(0, m.index) : name).trim() || name;
  const chars = [...base];
  if (chars.length <= 6) return { lines: [base], size };
  const half = Math.ceil(chars.length / 2);
  return { lines: [chars.slice(0, half).join(''), chars.slice(half).join('')], size };
}

function labelTexts(name: string, wordmark: string, top: number, ink: string, accent: string, width: number): string {
  const { lines, size } = bottleLabel(name);
  const fs = Math.min(23, width / Math.max(...lines.map(visLen)));
  const y0 = lines.length > 1 ? top + 94 : top + 112;
  let o = `<text x="250" y="${top + 42}" text-anchor="middle" font-family="${SERIF}" font-weight="700" font-size="19" letter-spacing="3" fill="${ink}">${esc(wordmark)}</text>`;
  o += `<line x1="222" x2="278" y1="${top + 56}" y2="${top + 56}" stroke="${accent}" stroke-width="1.5"/>`;
  lines.forEach((t, i) => {
    o += `<text x="250" y="${r1(y0 + i * fs * 1.35)}" text-anchor="middle" font-family="${SERIF}" font-weight="700" font-size="${r1(fs)}" fill="${ink}">${esc(t)}</text>`;
  });
  if (size) o += `<text x="250" y="${top + 172}" text-anchor="middle" font-family="${SANS}" font-size="14" letter-spacing="2" fill="${ink}" fill-opacity=".6">${esc(size)}</text>`;
  return o;
}

/** 精華液滴管瓶 + 珍珠石台（座標 500×800） */
function serumArt(P: Palette, name: string, wordmark: string): string {
  let o = `<defs>
<linearGradient id="glass" x1="0" x2="1"><stop offset="0" stop-color="${shade(P.primary, -0.35)}"/><stop offset=".16" stop-color="${shade(P.primary, 0.25)}"/><stop offset=".45" stop-color="${P.primary}"/><stop offset=".8" stop-color="${shade(P.primary, 0.12)}"/><stop offset="1" stop-color="${shade(P.primary, -0.4)}"/></linearGradient>
<linearGradient id="gold" x1="0" x2="1"><stop offset="0" stop-color="#8E6F3A"/><stop offset=".3" stop-color="#F3E3B8"/><stop offset=".55" stop-color="#C9A96E"/><stop offset=".8" stop-color="#F6EACB"/><stop offset="1" stop-color="#9A7B45"/></linearGradient>
<linearGradient id="bulb" x1="0" x2="1"><stop offset="0" stop-color="${shade(P.primary, -0.6)}"/><stop offset=".35" stop-color="${shade(P.primary, -0.25)}"/><stop offset="1" stop-color="${shade(P.primary, -0.62)}"/></linearGradient>
<linearGradient id="pTop" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="${mixHex(P.secondary, '#ffffff', 0.3)}"/></linearGradient>
<linearGradient id="pSide" x1="0" x2="1"><stop offset="0" stop-color="${mixHex(P.secondary, P.ink, 0.12)}"/><stop offset=".45" stop-color="#ffffff"/><stop offset="1" stop-color="${mixHex(P.secondary, P.ink, 0.16)}"/></linearGradient>
<radialGradient id="bub" cx=".35" cy=".35" r=".65"><stop offset="0" stop-color="#fff" stop-opacity=".95"/><stop offset=".6" stop-color="#fff" stop-opacity=".2"/><stop offset="1" stop-color="#fff" stop-opacity=".55"/></radialGradient>
<filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="10"/></filter>
</defs>`;
  o += `<ellipse cx="250" cy="778" rx="236" ry="30" fill="${P.ink}" opacity=".16" filter="url(#soft)"/>`;
  o += `<path d="M30 700 V762 A220 36 0 0 0 470 762 V700 Z" fill="url(#pSide)"/>`;
  o += `<ellipse cx="250" cy="700" rx="220" ry="36" fill="url(#pTop)"/>`;
  o += `<ellipse cx="250" cy="700" rx="168" ry="26" fill="none" stroke="#fff" stroke-width="2.5" opacity=".9"/>`;
  o += `<ellipse cx="250" cy="700" rx="200" ry="31" fill="none" stroke="${P.accent}" stroke-width="1.5" opacity=".5"/>`;
  o += `<ellipse cx="250" cy="702" rx="112" ry="14" fill="${P.ink}" opacity=".28" filter="url(#soft)"/>`;
  o += `<path d="M214 236 V168 Q214 98 250 98 Q286 98 286 168 V236 Z" fill="url(#bulb)"/>`;
  o += `<rect x="226" y="118" width="9" height="104" rx="4.5" fill="#fff" opacity=".28"/>`;
  o += `<rect x="194" y="228" width="112" height="66" rx="10" fill="url(#gold)"/>`;
  for (let i = 0; i < 5; i++) o += `<line x1="198" x2="302" y1="${240 + i * 11}" y2="${240 + i * 11}" stroke="#7A5E2E" stroke-width="1" opacity=".22"/>`;
  o += `<rect x="210" y="290" width="80" height="44" fill="url(#glass)"/>`;
  o += `<path d="M150 384 Q150 330 210 328 H290 Q350 330 350 384 V668 Q350 702 316 702 H184 Q150 702 150 668 Z" fill="url(#glass)"/>`;
  o += `<path d="M164 420 H336 V660 Q336 688 310 688 H190 Q164 688 164 660 Z" fill="#fff" opacity=".07"/>`;
  o += `<rect x="172" y="440" width="156" height="196" rx="8" fill="${P.secondary}" opacity=".95"/>`;
  o += `<rect x="180" y="448" width="140" height="180" rx="5" fill="none" stroke="${P.accent}" stroke-width="1.2" opacity=".8"/>`;
  o += labelTexts(name, wordmark, 440, P.ink, P.accent, 128);
  o += `<rect x="160" y="356" width="11" height="310" rx="5.5" fill="#fff" opacity=".42"/>`;
  o += `<rect x="333" y="390" width="5" height="250" rx="2.5" fill="#fff" opacity=".22"/>`;
  for (const [x, y, r] of [[96, 430, 15], [402, 300, 10], [424, 520, 19], [84, 600, 9], [388, 642, 7], [120, 320, 6]]) {
    o += `<circle cx="${x}" cy="${y}" r="${r}" fill="url(#bub)" stroke="#fff" stroke-opacity=".7" stroke-width="1"/>`;
  }
  return o;
}

/** 冷萃咖啡玻璃瓶 + 陶瓷杯墊（座標 500×800） */
function coldbrewArt(P: Palette, name: string, wordmark: string): string {
  const bottle = 'M220 120 H280 V190 C280 215 340 225 340 265 V668 Q340 700 308 700 H192 Q160 700 160 668 V265 C160 225 220 215 220 190 Z';
  let o = `<defs>
<clipPath id="body"><path d="${bottle}"/></clipPath>
<linearGradient id="coffee" x1="0" x2="1"><stop offset="0" stop-color="#1A0F09"/><stop offset=".35" stop-color="#4A2C1A"/><stop offset=".7" stop-color="#2E1B10"/><stop offset="1" stop-color="#140B06"/></linearGradient>
<linearGradient id="cTop" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${mixHex(P.secondary, '#ffffff', 0.5)}"/><stop offset="1" stop-color="${mixHex(P.secondary, P.ink, 0.08)}"/></linearGradient>
<linearGradient id="cSide" x1="0" x2="1"><stop offset="0" stop-color="${mixHex(P.secondary, P.ink, 0.22)}"/><stop offset=".45" stop-color="${mixHex(P.secondary, '#ffffff', 0.3)}"/><stop offset="1" stop-color="${mixHex(P.secondary, P.ink, 0.26)}"/></linearGradient>
<filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="10"/></filter>
</defs>`;
  o += `<ellipse cx="250" cy="778" rx="220" ry="28" fill="${P.ink}" opacity=".18" filter="url(#soft)"/>`;
  o += `<path d="M50 712 V756 A200 30 0 0 0 450 756 V712 Z" fill="url(#cSide)"/>`;
  o += `<ellipse cx="250" cy="712" rx="200" ry="30" fill="url(#cTop)"/>`;
  o += `<ellipse cx="250" cy="706" rx="104" ry="12" fill="${P.ink}" opacity=".3" filter="url(#soft)"/>`;
  o += `<g clip-path="url(#body)"><rect x="150" y="300" width="200" height="420" fill="url(#coffee)"/><rect x="150" y="296" width="200" height="8" fill="#6B4630" opacity=".8"/></g>`;
  o += `<path d="${bottle}" fill="#fff" fill-opacity=".14" stroke="#fff" stroke-opacity=".6" stroke-width="2"/>`;
  o += `<rect x="212" y="84" width="76" height="46" rx="7" fill="${P.ink}"/>`;
  for (let i = 0; i < 6; i++) o += `<line x1="${220 + i * 12}" x2="${220 + i * 12}" y1="90" y2="124" stroke="#fff" stroke-opacity=".12" stroke-width="2"/>`;
  o += `<rect x="172" y="420" width="156" height="200" rx="4" fill="${mixHex(P.accent, '#ffffff', 0.25)}"/>`;
  o += `<rect x="180" y="428" width="140" height="184" rx="2" fill="none" stroke="${P.primary}" stroke-width="1.2" opacity=".7"/>`;
  o += labelTexts(name, wordmark, 424, P.primary, P.primary, 128);
  o += `<rect x="172" y="250" width="10" height="400" rx="5" fill="#fff" opacity=".35"/>`;
  o += `<rect x="324" y="300" width="5" height="300" rx="2.5" fill="#fff" opacity=".2"/>`;
  return o;
}

const ARTS = { serum: serumArt, coldbrew: coldbrewArt } as const;

/** 示範商品圖（模擬已去背的商品照）。商品是真實存在的東西，所以永遠用品牌色票繪製，不跟背景一起變色。 */
export function productArtSvg(art: keyof typeof ARTS, palette: Palette, name: string, wordmark: string): string {
  return `<svg xmlns="${SVG_NS}" width="500" height="800" viewBox="0 0 500 800">${ARTS[art](palette, name, wordmark)}</svg>`;
}
