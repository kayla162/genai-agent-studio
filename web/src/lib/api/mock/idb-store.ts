import { createStore, get, set, type UseStore } from 'idb-keyval';
import type { KeyValueStore } from './store';

/** 瀏覽器版本：資料存在 IndexedDB，重新整理後仍在。只能在有 indexedDB 的環境建立。 */
export class IdbStore implements KeyValueStore {
  private readonly db: UseStore;

  constructor(dbName = 'genai-poster-agent', storeName = 'kv') {
    this.db = createStore(dbName, storeName);
  }

  get<T>(key: string): Promise<T | undefined> {
    return get<T>(key, this.db);
  }

  set<T>(key: string, value: T): Promise<void> {
    return set(key, value, this.db);
  }
}
