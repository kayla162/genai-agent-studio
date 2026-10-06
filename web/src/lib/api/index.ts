import type { ApiClient } from './client';
import { MockApiClient } from './mock/client';

export type { ApiClient, DemoControls, ProductDraft } from './client';

let instance: ApiClient | null = null;

/** 依 NEXT_PUBLIC_API_MODE 選擇實作（預設 mock）。第二階段加入 live → HttpApiClient。 */
export function getApiClient(): ApiClient {
  if (instance) return instance;
  const mode = process.env.NEXT_PUBLIC_API_MODE || 'mock';
  if (mode !== 'mock') throw new Error(`API 模式「${mode}」尚未實作：第二階段會加入連線 FastAPI 的 HttpApiClient`);
  instance = new MockApiClient();
  return instance;
}
