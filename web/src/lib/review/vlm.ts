import type { Brand, PromptSpec, ReviewCheck } from '@/types/contract';
import { boxMap } from '@/lib/compose/layout';
import { intersectionArea } from '@/lib/core/geometry';
import { bannedWordHits, ragRefFor } from './rules';

/** Plan 6B 接上 Gemini 之前，VLM 三項說明文字的標示 */
export const SIMULATED_VLM_NOTE = '（模擬，Plan 6B 改用 Gemini）';

/**
 * live 模式在 Plan 6B 之前的 VLM 三項：依文案與版面判斷，不依候選編號出現劇本式警告
 * （模擬模式仍用 mock 的 mockVlmChecks）。
 * - 誇大／療效用語：與禁用詞檢查相同的偵測；
 * - 物件與文字遮擋：Logo 框與標題框重疊時不通過，其他情況通過；
 * - 整體畫質：一律通過。
 */
export function contentVlmChecks(spec: PromptSpec, brand: Brand): ReviewCheck[] {
  const { words, target } = bannedWordHits(spec, brand);
  const B = boxMap(spec.layout);
  const occluded = intersectionArea(B.logo, B.headline) > 0;
  const note = (value: string) => `${value}${SIMULATED_VLM_NOTE}`;

  return [
    {
      id: 'vlm_exaggeration', name: '誇大／療效用語', kind: 'vlm', rule: 'VLM 判讀海報文字語意',
      value: note(words.length ? `偵測到${words.map((w) => `「${w}」`).join('')}` : '未發現誇大用語'),
      status: words.length ? 'fail' : 'pass', target, ragRef: ragRefFor(brand, 'law'),
    },
    {
      id: 'vlm_occlusion', name: '物件與文字遮擋', kind: 'vlm', rule: 'VLM 判讀元素是否重疊',
      value: note(occluded ? 'Logo 與標題重疊' : '無重疊遮擋'),
      status: occluded ? 'fail' : 'pass', target: occluded ? 'logo' : null, ragRef: ragRefFor(brand, 'logo'),
    },
    {
      id: 'vlm_quality', name: '整體畫質', kind: 'vlm', rule: 'VLM 判讀構圖、光線與瑕疵',
      value: note('構圖與畫質良好'), status: 'pass', target: null, ragRef: null,
    },
  ];
}
