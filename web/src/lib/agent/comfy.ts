import type { PromptSpec } from '@/types/contract';

/*
 * ComfyUI workflow product_scene_v1 的參數對照表（Plan 7 規格 §4.4）：label 對應 workflow（API 格式）的 nodeId 與 input。
 * buildInjection 依這張表產生 PromptSpec.injection；npm run fixtures 把它匯出成 contracts/fixtures/comfy.json，
 * pytest 確認與 comfyui/workflows/product_scene_v1.params.json 相同，而且每個參數都對得到 workflow 的節點。
 *
 * 目前的 workflow 是手寫的（只用 ComfyUI 內建節點與 SDXL base 1.0）；Plan 7 Task 1 在 ComfyUI 實測後，
 * 換成匯出的 workflow 與實驗決定的參數，這張表與 comfyui/ 的兩個檔案一起修改。
 */

export type ComfyParamType = 'string' | 'int' | 'float' | 'image';

export interface ComfyParamSpec {
  label: string;
  nodeId: string;
  input: string;
  type: ComfyParamType;
  /** 固定的值；沒有時由 buildInjection 依 spec 填入（提示詞、seed、底圖與遮罩的檔名） */
  default?: string | number;
}

export interface ComfyWorkflowTable {
  /** comfyui/workflows/ 底下的 workflow 檔名 */
  workflow: string;
  params: ComfyParamSpec[];
}

export const PRODUCT_SCENE: ComfyWorkflowTable = {
  workflow: 'product_scene_v1.json',
  params: [
    { label: 'checkpoint', nodeId: '1', input: 'ckpt_name', type: 'string', default: 'sd_xl_base_1.0.safetensors' },
    { label: 'positive_prompt', nodeId: '3', input: 'text', type: 'string' },
    { label: 'negative_prompt', nodeId: '4', input: 'text', type: 'string' },
    { label: 'plate_image', nodeId: '5', input: 'image', type: 'image' },
    { label: 'mask_image', nodeId: '6', input: 'image', type: 'image' },
    { label: 'seed', nodeId: '9', input: 'seed', type: 'int' },
    { label: 'steps', nodeId: '9', input: 'steps', type: 'int', default: 20 },
    { label: 'cfg', nodeId: '9', input: 'cfg', type: 'float', default: 6 },
    { label: 'sampler', nodeId: '9', input: 'sampler_name', type: 'string', default: 'euler' },
    { label: 'scheduler', nodeId: '9', input: 'scheduler', type: 'string', default: 'normal' },
    { label: 'denoise', nodeId: '9', input: 'denoise', type: 'float', default: 1 },
  ],
};

type SpecKey = Pick<PromptSpec, 'jobId' | 'round' | 'templateId'>;

/** 上傳到 ComfyUI 的商品底圖檔名：每個任務、每輪、每個模板一份（Gemini 每輪可能調整版面） */
export const plateImageName = (s: SpecKey) => `${s.jobId}_r${s.round}_${s.templateId}_plate.png`;
/** 上傳到 ComfyUI 的遮罩檔名 */
export const maskImageName = (s: SpecKey) => `${s.jobId}_r${s.round}_${s.templateId}_mask.png`;
