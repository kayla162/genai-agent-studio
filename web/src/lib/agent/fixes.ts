import type { Brand, CheckId, Fix, PromptSpec, ReviewCheck } from '@/types/contract';
import { copyTexts, findBannedWords } from '@/lib/review/rules';

/** 審查未通過 → Query Rewriting 要採取的修正策略（同標題只保留第一筆） */
export function planFixes(checks: ReviewCheck[], brand: Brand, spec: PromptSpec): Fix[] {
  const fixes: Fix[] = [];
  const add = (checkId: CheckId, title: string, desc: string) => {
    if (!fixes.some((f) => f.title === title)) fixes.push({ checkId, title, desc });
  };

  for (const c of checks.filter((x) => x.status !== 'pass')) {
    switch (c.id) {
      case 'banned_words':
      case 'vlm_exaggeration': {
        const words = findBannedWords(copyTexts(spec).map((t) => t.text), brand.bannedWords);
        const pairs = words.map((w) => `「${w}」→${brand.replacements[w] ? `「${brand.replacements[w]}」` : '刪除'}`);
        add(c.id, '文案改寫', pairs.length ? `依合規替代用語改寫：${pairs.join('、')}` : '移除誇大用語，改為使用者感受描述');
        break;
      }
      case 'color_delta':
        add(c.id, '色彩修正', `鎖定品牌 CI 色票（primary ${brand.palette.primary}），negative_prompt 加入 oversaturated / neon / off-brand colors`);
        break;
      case 'logo_clearance':
        add(c.id, '版面修正', 'Logo 回到網格起點，與標題保留 ≥ 0.5 × Logo 高的淨空區');
        break;
      case 'disclaimer':
        add(c.id, '補充註記', `效果宣稱句尾加「*」，頁尾加註「${brand.disclaimerPhrase || '效果說明'}」`);
        break;
      case 'vlm_occlusion':
        add(c.id, '構圖修正', '拉開商品與文字區塊的距離，negative_prompt 加入 cluttered composition');
        break;
      case 'vlm_quality':
        add(c.id, '畫質修正', '降低高光強度，negative_prompt 加入 overexposed highlights');
        break;
      case 'product_ratio':
      case 'whitespace':
        add(c.id, '版面比例修正', '調整商品主體縮放，維持品牌規範的佔比與留白');
        break;
      case 'ocr_typo':
        add(c.id, '文字重繪', '改由排版引擎重新繪製文字圖層');
        break;
    }
  }
  return fixes;
}
