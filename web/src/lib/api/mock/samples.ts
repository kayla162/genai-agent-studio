import type { DemoOptions, JobInput, TemplateId } from '@/types/contract';
import { TEMPLATE_IDS } from '@/types/contract';
import { mulberry32 } from '@/lib/core/num';
import { parseBrief } from './brief';
import { BRANDS, SAMPLE_PRODUCTS } from './data';

/** 示範任務使用的需求（各品牌輪流） */
export const SAMPLE_BRIEFS: Record<string, string[]> = {
  selune: [
    '幫我做週年慶的精華液海報，主打買一送一，要溫柔療癒的感覺',
    '雙11精華液限時85折，要專業科研感',
    '秋冬保濕主打修護，簡約高級感',
  ],
  'misty-isle': [
    '幫我設計一款簡約風格的冷萃咖啡宣傳海報',
    '冷萃咖啡新品上市，第二件6折，活潑年輕',
    '夏季早午餐配冷萃，清新療癒的感覺',
  ],
};

export interface SampleJob { input: JobInput; demo: DemoOptions; createdAt: Date }

const HOUR = 3_600_000;

/**
 * 產生 count 筆示範任務的設定（最舊的在前），讓成效儀表板一開始就有資料。
 * 兩個品牌輪流；大部分首輪失敗後重試通過，每 5 筆有 1 筆全部失敗（需人工審核），每 3 筆有 1 筆首輪就通過。
 * 5 與 3 都是奇數，兩個品牌都會分到這三種結果。
 */
export function sampleJobs(count: number, now: Date, seed = 7): SampleJob[] {
  const rng = mulberry32(seed);
  return Array.from({ length: count }, (_, i): SampleJob => {
    const brand = BRANDS[i % BRANDS.length];
    const product = SAMPLE_PRODUCTS.find((p) => p.brandId === brand.id);
    if (!product) throw new Error(`Brand ${brand.id} has no sample product`);
    const briefs = SAMPLE_BRIEFS[brand.id];
    const brief = briefs[Math.floor(i / BRANDS.length) % briefs.length];
    const picked = TEMPLATE_IDS.filter(() => rng() < 0.45);
    const templateIds: TemplateId[] = picked.length ? picked : ['ecom-main'];
    const forceAllFail = i % 5 === 3;
    return {
      input: {
        brandId: brand.id,
        productId: product.id,
        brief,
        parsedBrief: parseBrief(brief, brand, product),
        templateIds,
        variantsPerTemplate: [4, 4, 2, 3][i % 4],
        llm: i % 3 === 2 ? 'Llama 3.2 Vision（Unsloth 微調）' : 'Gemini 3.7 Flash',
        engine: i % 5 === 4 ? 'ideogram' : 'comfyui',
        vlm: 'Gemini 3.7 Vision',
        maxRetries: 2,
      },
      demo: { speed: 1, firstRoundFail: forceAllFail || i % 3 !== 1, forceAllFail },
      createdAt: new Date(now.getTime() - (count - i) * 11 * HOUR - Math.floor(rng() * 3 * HOUR)),
    };
  });
}
