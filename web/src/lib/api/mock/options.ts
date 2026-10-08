import type { ApiOptions } from '@/types/contract';

/** mock 模式提供的模型與引擎（第一階段的示意名稱；live 模式改由後端回傳實際可用的選項） */
export const MOCK_OPTIONS: ApiOptions = {
  llm: ['Gemini 3.7 Flash', 'Llama 3.2 Vision（Unsloth 微調）'],
  vlm: ['Gemini 3.7 Vision', 'Llama 3.2 Vision（Unsloth 微調）'],
  engines: ['comfyui', 'ideogram'],
};
