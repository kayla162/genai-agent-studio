import type { ApiClient } from './client';
import { HttpApiClient } from './http/client';
import { MockApiClient } from './mock/client';
import { IdbStore } from './mock/idb-store';
import { MemoryStore } from './mock/store';

export type { ApiClient, ConnectionChannel, DemoControls, JobSnapshot, ProductDraft } from './client';

/** 建置時由 Next 內嵌；伺服器與瀏覽器看到的值相同，可直接用於 render */
export const API_MODE = process.env.NEXT_PUBLIC_API_MODE || 'mock';

let instance: ApiClient | null = null;

/**
 * 依 NEXT_PUBLIC_API_MODE 選擇實作：mock（預設，瀏覽器內模擬）或 live（連線 FastAPI）。
 * 單例內含計時器與訂閱，只能在 client component 的事件處理、effect 或 store action 中呼叫，不可在伺服器端 render 時呼叫。
 */
export function getApiClient(): ApiClient {
  if (instance) return instance;
  if (API_MODE === 'live') instance = new HttpApiClient();
  else if (API_MODE === 'mock') {
    // 瀏覽器把商品、歷史紀錄與上傳文件存在 IndexedDB；測試環境沒有 indexedDB，改用記憶體
    instance = new MockApiClient(typeof indexedDB === 'undefined' ? new MemoryStore() : new IdbStore());
  } else throw new Error(`不支援的 API 模式「${API_MODE}」：NEXT_PUBLIC_API_MODE 請設定為 mock 或 live`);
  return instance;
}
