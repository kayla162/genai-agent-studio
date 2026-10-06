import 'fake-indexeddb/auto';
import { describe, it, expect } from 'vitest';
import { IdbStore } from './idb-store';

describe('IdbStore', () => {
  it('round-trips values and returns undefined for missing keys', async () => {
    const store = new IdbStore('test-db-1');
    expect(await store.get('missing')).toBeUndefined();
    await store.set('products', [{ id: 'p1', price: { sale: 1 } }]);
    expect(await store.get('products')).toEqual([{ id: 'p1', price: { sale: 1 } }]);
  });

  it('persists across instances that share a database name', async () => {
    await new IdbStore('test-db-2').set('history', ['h1']);
    expect(await new IdbStore('test-db-2').get('history')).toEqual(['h1']);
    expect(await new IdbStore('test-db-3').get('history')).toBeUndefined();
  });

  it('stores frozen objects and returns mutable copies', async () => {
    const store = new IdbStore('test-db-4');
    await store.set('k', Object.freeze({ a: 1 }));
    const v = await store.get<{ a: number }>('k');
    expect(Object.isFrozen(v)).toBe(false);
  });
});
