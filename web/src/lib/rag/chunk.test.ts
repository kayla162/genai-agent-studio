import { describe, it, expect } from 'vitest';
import { chunkDocument, embedPreview, guessTag, EMBED_DIMS } from './chunk';

const DOC = {
  name: 'ci_update_2026.md',
  text: [
    '# 色彩更新',
    '主色維持 #B76E79，新增輔助色「霧粉」#E8C7C8。',
    '',
    '# Logo 規範',
    '- Logo 淨空區至少 0.5 倍 Logo 高度',
    '- 深色背景使用反白 Logo',
    '',
    '週年慶素材的平均 CTR 為 4.2%。',
  ].join('\n'),
};

describe('chunkDocument', () => {
  it('splits by heading and paragraph, keeping the latest heading as the section', () => {
    const chunks = chunkDocument('selune', DOC);
    expect(chunks.map((c) => c.section)).toEqual(['色彩更新', 'Logo 規範', 'Logo 規範']);
    expect(chunks[1].text).toBe('Logo 淨空區至少 0.5 倍 Logo 高度。深色背景使用反白 Logo。');
    expect(chunks.every((c) => c.source === 'ci_update_2026.md')).toBe(true);
  });

  it('joins wrapped lines without adding spaces between Chinese characters', () => {
    const text = '標題靠左\n對齊網格。\nLogo\n置於左上。';
    expect(chunkDocument('selune', { name: 'a.txt', text })[0].text).toBe('標題靠左對齊網格。Logo 置於左上。');
  });

  it('uses the file name as the section before any heading', () => {
    expect(chunkDocument('selune', { name: '規範.txt', text: '標題最多兩行。' })[0].section).toBe('規範');
  });

  it('tags chunks by keywords', () => {
    expect(chunkDocument('selune', DOC).map((c) => c.tag)).toEqual(['color', 'logo', 'history']);
  });

  it('packs sentences into chunks no longer than maxChars', () => {
    const text = '第一句話很短。第二句話也很短。第三句話一樣很短。';
    const chunks = chunkDocument('selune', { name: 'a.txt', text }, { maxChars: 16 });
    expect(chunks.map((c) => c.text)).toEqual(['第一句話很短。第二句話也很短。', '第三句話一樣很短。']);
    const long = chunkDocument('selune', { name: 'b.txt', text: '字'.repeat(40) }, { maxChars: 16 });
    expect(long.map((c) => [...c.text].length)).toEqual([16, 16, 8]);
  });

  it('gives stable ids that are unique per document', () => {
    const a = chunkDocument('selune', DOC);
    expect(chunkDocument('selune', DOC).map((c) => c.id)).toEqual(a.map((c) => c.id));
    expect(new Set(a.map((c) => c.id)).size).toBe(a.length);
    expect(a[0].id).toMatch(/^selune#doc-[0-9a-z]+-1$/);
    expect(chunkDocument('selune', { ...DOC, name: 'other.md' })[0].id).not.toBe(a[0].id);
  });

  it('returns no chunks for blank text', () => {
    expect(chunkDocument('selune', { name: 'empty.txt', text: ' \n\n ' })).toEqual([]);
  });
});

describe('guessTag', () => {
  it('falls back to general', () => {
    expect(guessTag('禁止宣稱療效')).toBe('law');
    expect(guessTag('標題使用思源宋體字型')).toBe('font');
    expect(guessTag('商品主體置中，留白 40%')).toBe('layout');
    expect(guessTag('門市營業時間')).toBe('general');
  });
});

describe('embedPreview', () => {
  it('is deterministic and bounded', () => {
    const v = embedPreview('品牌主色');
    expect(v).toEqual(embedPreview('品牌主色'));
    expect(v).toHaveLength(6);
    for (const x of v) expect(Math.abs(x)).toBeLessThanOrEqual(1);
    expect(embedPreview('另一段文字')).not.toEqual(v);
    expect(EMBED_DIMS).toBe(1024);
  });
});
