import type { Brand, PromptSpec, ReviewCheck } from '@/types/contract';
import { boxMap } from '@/lib/compose/layout';
import { verticalGap } from '@/lib/core/geometry';
import { copyTexts, findBannedWords, ragRefFor } from '@/lib/review/rules';

type Verdict = Pick<ReviewCheck, 'status' | 'value'>;

/** 模擬 VLM 看圖後的判斷。第二階段改為呼叫 Gemini Vision 或微調的 Llama 3.2 Vision，輸出格式不變。 */
export function mockVlmChecks(spec: PromptSpec, brand: Brand, variant: number): ReviewCheck[] {
  const texts = copyTexts(spec);
  const words = findBannedWords(texts.map((t) => t.text), brand.bannedWords);
  const exaggerationTarget = texts.find((t) => words.some((w) => t.text.includes(w)))?.id ?? null;
  const B = boxMap(spec.layout);
  const crowded = verticalGap(B.logo, B.headline) < 0;

  const occlusion: Verdict = crowded
    ? { status: 'fail', value: 'Logo 與標題重疊' }
    : variant % 4 === 1
      ? { status: 'warn', value: '標題貼近商品主體' }
      : { status: 'pass', value: '無重疊遮擋' };
  const quality: Verdict =
    variant % 4 === 2 ? { status: 'warn', value: '背景高光略過曝' } : { status: 'pass', value: '構圖與畫質良好' };

  return [
    {
      id: 'vlm_exaggeration', name: '誇大／療效用語', kind: 'vlm', rule: 'VLM 判讀海報文字語意',
      value: words.length ? `偵測到${words.map((w) => `「${w}」`).join('')}` : '未發現誇大用語',
      status: words.length ? 'fail' : 'pass', target: exaggerationTarget, ragRef: ragRefFor(brand, 'law'),
    },
    {
      id: 'vlm_occlusion', name: '物件與文字遮擋', kind: 'vlm', rule: 'VLM 判讀元素是否重疊', ...occlusion,
      target: crowded ? 'logo' : occlusion.status === 'warn' ? 'headline' : null, ragRef: ragRefFor(brand, 'logo'),
    },
    {
      id: 'vlm_quality', name: '整體畫質', kind: 'vlm', rule: 'VLM 判讀構圖、光線與瑕疵', ...quality,
      target: quality.status === 'warn' ? 'product' : null, ragRef: null,
    },
  ];
}
