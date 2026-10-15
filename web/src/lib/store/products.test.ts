import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Product, ProductCutout } from '@/types/contract';
import { getApiClient } from '@/lib/api';
import { CUTOUT_POLL_MS, useProductsStore } from './products';

const PENDING: ProductCutout = { model: 'birefnet-general', status: 'pending', url: null, error: null };
const DONE: ProductCutout = { model: 'birefnet-general', status: 'done', url: '/files/products/prod_a/cutout-1.png', error: null };

const product = (cutout: ProductCutout | null): Product => ({
  id: 'prod_a', brandId: 'selune', name: '晚安面膜', features: [], price: { sale: 0, original: 0 },
  photo: { source: 'upload', url: '/files/uploads/a.png' }, cutout, createdAt: '2026-10-15T00:00:00.000Z',
});

beforeEach(() => {
  vi.useFakeTimers();
  useProductsStore.setState({ brandId: null, products: [], loading: false, cutting: [] });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('products store', () => {
  it('re-reads the list every 2 seconds while a cutout is pending, without showing the loading state', async () => {
    const list = vi.spyOn(getApiClient(), 'listProducts')
      .mockResolvedValueOnce([product(PENDING)])
      .mockResolvedValueOnce([product(PENDING)])
      .mockResolvedValue([product(DONE)]);
    await useProductsStore.getState().load('selune');
    expect(CUTOUT_POLL_MS).toBe(2_000);
    await vi.advanceTimersByTimeAsync(1_999);
    expect(list).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(list).toHaveBeenCalledTimes(2);
    expect(useProductsStore.getState().loading).toBe(false);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(list).toHaveBeenCalledTimes(3);
    expect(useProductsStore.getState().products[0].cutout).toEqual(DONE);
    // 全部完成後停止
    await vi.advanceTimersByTimeAsync(10_000);
    expect(list).toHaveBeenCalledTimes(3);
  });

  it('stops polling the previous brand after switching brands', async () => {
    const list = vi.spyOn(getApiClient(), 'listProducts')
      .mockImplementation(async (brandId) => (brandId === 'selune' ? [product(PENDING)] : []));
    await useProductsStore.getState().load('selune');
    await useProductsStore.getState().load('misty-isle');
    await vi.advanceTimersByTimeAsync(10_000);
    expect(list.mock.calls.map(([brandId]) => brandId)).toEqual(['selune', 'misty-isle']);
  });

  it('keeps polling after a failed read', async () => {
    const list = vi.spyOn(getApiClient(), 'listProducts')
      .mockResolvedValueOnce([product(PENDING)])
      .mockRejectedValueOnce(new Error('無法連線到後端'))
      .mockResolvedValue([product(DONE)]);
    await useProductsStore.getState().load('selune');
    await vi.advanceTimersByTimeAsync(4_000);
    expect(list).toHaveBeenCalledTimes(3);
    expect(useProductsStore.getState().products[0].cutout).toEqual(DONE);
  });

  it('starts polling after asking for a new cutout', async () => {
    vi.spyOn(getApiClient(), 'listProducts').mockResolvedValueOnce([product(DONE)]).mockResolvedValue([product(DONE)]);
    vi.spyOn(getApiClient(), 'requestCutout').mockResolvedValue(product(PENDING));
    await useProductsStore.getState().load('selune');
    const updated = await useProductsStore.getState().cutout('prod_a');
    expect(updated.cutout).toEqual(PENDING);
    expect(useProductsStore.getState().products[0].cutout).toEqual(PENDING);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(useProductsStore.getState().products[0].cutout).toEqual(DONE);
  });
});
