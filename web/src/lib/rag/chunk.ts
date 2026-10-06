import type { BrandDocument, RagChunk, RagTag } from '@/types/contract';
import { hashString, mulberry32 } from '@/lib/core/num';

/** bge-m3 的向量維度 */
export const EMBED_DIMS = 1024;

/** 依序比對，第一個命中的規則決定標籤 */
const TAG_RULES: [RegExp, RagTag][] = [
  [/禁用|法規|宣稱|療效|誇大|廣告|§/, 'law'],
  [/色彩|主色|輔助色|點綴色|色票|色差|ΔE|#[0-9a-fA-F]{6}/, 'color'],
  [/logo|標誌|淨空/i, 'logo'],
  [/字型|字體|字重|font/i, 'font'],
  [/版型|版面|留白|網格|構圖|佔比/, 'layout'],
  [/成效|CTR|點擊|互動|案例/i, 'history'],
];

export function guessTag(text: string): RagTag {
  return TAG_RULES.find(([re]) => re.test(text))?.[1] ?? 'general';
}

/** 先看內文，內文無法判斷時再看段落標題 */
const tagOf = (section: string, text: string): RagTag => {
  const tag = guessTag(text);
  return tag === 'general' ? guessTag(section) : tag;
};

/** 兩個漢字之間的空白（合併多行時產生）要拿掉 */
const CJK_GAP = /(\p{Script=Han})\s+(?=\p{Script=Han})/gu;

/** 依句號等標點切句，再把句子裝進不超過 maxChars 的塊；單句過長時硬切 */
function pack(text: string, maxChars: number): string[] {
  const sentences = text.match(/[^。！？!?；;]+[。！？!?；;]?/g) ?? [];
  const out: string[] = [];
  let cur = '';
  for (const raw of sentences) {
    const s = raw.trim();
    if (!s) continue;
    if ([...cur].length + [...s].length <= maxChars) {
      cur += s;
      continue;
    }
    if (cur) out.push(cur);
    const chars = [...s];
    for (let i = 0; i + maxChars < chars.length; i += maxChars) out.push(chars.slice(i, i + maxChars).join(''));
    cur = chars.slice(Math.floor((chars.length - 1) / maxChars) * maxChars).join('');
  }
  if (cur) out.push(cur);
  return out;
}

/**
 * 把品牌文件切成 RAG 切塊：Markdown 標題（#）成為之後段落的 section，空行分段，
 * 段落再依句子裝塊。第二階段改由後端切塊，輸出格式不變。
 */
export function chunkDocument(brandId: string, doc: BrandDocument, { maxChars = 180 } = {}): RagChunk[] {
  const docKey = hashString(doc.name).toString(36);
  let section = doc.name.replace(/\.[^.]+$/, '');
  const pieces: { section: string; text: string }[] = [];
  const flush = (lines: string[]) => {
    const text = lines.join(' ').replace(/\s+/g, ' ').replace(CJK_GAP, '$1').trim();
    for (const t of pack(text, maxChars)) pieces.push({ section, text: t });
    lines.length = 0;
  };

  for (const block of doc.text.replace(/\r\n?/g, '\n').split(/\n\s*\n/)) {
    const body: string[] = [];
    for (const line of block.split('\n').map((l) => l.trim()).filter(Boolean)) {
      const heading = line.match(/^#{1,6}\s+(.+)$/);
      if (heading) {
        flush(body);
        section = heading[1].trim();
      } else {
        const bullet = line.match(/^[-*•]\s+(.+)$/);
        // 條列項目各自成句，避免合併後黏在一起
        body.push(bullet ? bullet[1].replace(/([^。！？!?；;])$/, '$1。') : line);
      }
    }
    flush(body);
  }

  return pieces.map((p, i) => ({
    id: `${brandId}#doc-${docKey}-${i + 1}`,
    source: doc.name,
    section: p.section,
    tag: tagOf(p.section, p.text),
    text: p.text,
  }));
}

/** 模擬向量的前幾維（第二階段由 bge-m3 產生真實向量） */
export function embedPreview(text: string, n = 6): number[] {
  const rng = mulberry32(hashString(text));
  return Array.from({ length: n }, () => Math.round((rng() * 2 - 1) * 1000) / 1000);
}
