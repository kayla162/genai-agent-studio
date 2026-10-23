import type { Brand, PromptSpec, ReviewCheck } from '@/types/contract';
import type { VlmVerdict } from '@/types/agent';
import { boxMap, ELEMENT_LABELS } from '@/lib/compose/layout';
import { intersectionArea } from '@/lib/core/geometry';
import { truncate } from '@/lib/core/text';
import { bannedWordHits, copyTexts, ragRefFor } from './rules';

/** AGENT_MODE=sim（依內容判斷）時，VLM 三項說明文字的標示 */
export const SIMULATED_VLM_NOTE = '（模擬：AGENT_MODE=sim）';
/** Gemini 理由的最大長度（字） */
const REASON_CHARS = 60;

/** VLM 三項的名稱與規則（模擬版與 Gemini 版相同） */
const VLM_CHECKS = {
  vlm_exaggeration: { name: '誇大／療效用語', rule: 'VLM 判讀海報文字語意' },
  vlm_occlusion: { name: '物件與文字遮擋', rule: 'VLM 判讀元素是否重疊' },
  vlm_quality: { name: '整體畫質', rule: 'VLM 判讀構圖、光線與瑕疵' },
} as const;

type VlmCheckId = keyof typeof VLM_CHECKS;
const vlmCheck = (id: VlmCheckId, fields: Pick<ReviewCheck, 'value' | 'status' | 'target' | 'ragRef'>): ReviewCheck => ({
  id, name: VLM_CHECKS[id].name, kind: 'vlm', rule: VLM_CHECKS[id].rule, ...fields,
});

/**
 * AGENT_MODE=sim 的 VLM 三項：依文案與版面判斷，不依候選編號出現劇本式警告
 * （REVIEW_MODE=sim 仍用 mock 的 mockVlmChecks）。
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
    vlmCheck('vlm_exaggeration', {
      value: note(words.length ? `偵測到${words.map((w) => `「${w}」`).join('')}` : '未發現誇大用語'),
      status: words.length ? 'fail' : 'pass', target, ragRef: ragRefFor(brand, 'law'),
    }),
    vlmCheck('vlm_occlusion', {
      value: note(occluded ? 'Logo 與標題重疊' : '無重疊遮擋'),
      status: occluded ? 'fail' : 'pass', target: occluded ? 'logo' : null, ragRef: ragRefFor(brand, 'logo'),
    }),
    vlmCheck('vlm_quality', { value: note('構圖與畫質良好'), status: 'pass', target: null, ragRef: null }),
  ];
}

/** AGENT_MODE=gemini 的 VLM 三項：狀態與理由取自 Gemini 的判讀，目標元素與引用的規範由程式決定 */
export function geminiVlmChecks(verdict: VlmVerdict, spec: PromptSpec, brand: Brand): ReviewCheck[] {
  const reason = (text: string) => truncate(text.trim(), REASON_CHARS);
  const { exaggeration: ex, occlusion: oc, quality: q } = verdict;

  const phrases = ex.phrases.map((p) => p.trim()).filter((p) => p !== '');
  const exTarget = copyTexts(spec).find((t) => phrases.some((p) => t.text.includes(p)))?.id ?? null;
  const exReason = reason(ex.reason);
  const exValue = phrases.length
    ? `偵測到${phrases.map((p) => `「${p}」`).join('')}${exReason ? `：${exReason}` : ''}`
    : exReason || '偵測到誇大用語';

  const ocTarget = oc.elements[0] ?? null;
  const ocValue = `${ocTarget ? `${ELEMENT_LABELS[ocTarget]}：` : ''}${reason(oc.reason) || '元素重疊或遮擋'}`;

  const issues = q.issues.map((i) => i.trim()).filter((i) => i !== '');
  const qValue = issues.length ? issues.join('、') : reason(q.reason) || '畫質有瑕疵';

  return [
    vlmCheck('vlm_exaggeration', {
      value: ex.status === 'pass' ? '未發現誇大用語' : exValue,
      status: ex.status, target: ex.status === 'pass' ? null : exTarget, ragRef: ragRefFor(brand, 'law'),
    }),
    vlmCheck('vlm_occlusion', {
      value: oc.status === 'pass' ? '無重疊遮擋' : ocValue,
      status: oc.status, target: oc.status === 'pass' ? null : ocTarget,
      ragRef: ragRefFor(brand, oc.elements.includes('logo') ? 'logo' : 'layout'),
    }),
    vlmCheck('vlm_quality', {
      value: q.status === 'pass' ? '構圖與畫質良好' : qValue, status: q.status, target: null, ragRef: null,
    }),
  ];
}
