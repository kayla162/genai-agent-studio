import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Product, ProductCutout } from '@/types/contract';
import { getApiClient } from '@/lib/api';
import { CUTOUT_POLL_MS, useProductsStore } from './products';

const PENDING: ProductCutout = { model: 'birefnet-general', status: 'pending', url: null, error: null };
const DONE: ProductCutout = { model: 'birefnet-general', status: 'done', url: '/files/products/prod_a/cutout-1.png', error: null };

const product = (cutout: ProductCutout | null, id = 'prod_a'): Product => ({
  id, brandId: 'selune', name: '晚安面膜', features: [], price: { sale: 0, original: 0 },
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

  it('keeps polling and leaves the loading state when a load fails while a cutout is pending', async () => {
    const list = vi.spyOn(getApiClient(), 'listProducts')
      .mockResolvedValueOnce([product(PENDING)])
      .mockRejectedValueOnce(new Error('無法連線到後端'))
      .mockResolvedValue([product(DONE)]);
    await useProductsStore.getState().load('selune');
    await expect(useProductsStore.getState().load('selune')).rejects.toThrow('無法連線到後端');
    expect(useProductsStore.getState().loading).toBe(false);
    expect(useProductsStore.getState().products[0].cutout).toEqual(PENDING);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(list).toHaveBeenCalledTimes(3);
    expect(useProductsStore.getState().products[0].cutout).toEqual(DONE);
  });

  /** 一份稍後才送達的讀取結果：模擬讀取已經送出、回應還在路上 */
  const lateRead = () => {
    let arrive!: (products: Product[]) => void;
    const read = new Promise<Product[]>((resolve) => {
      arrive = resolve;
    });
    return { read, arrive };
  };

  it('drops a poll result that was read before a new cutout was requested, and keeps polling', async () => {
    const late = lateRead();
    const list = vi.spyOn(getApiClient(), 'listProducts')
      .mockResolvedValueOnce([product(PENDING, 'prod_a'), product(DONE, 'prod_b')])
      .mockReturnValueOnce(late.read)
      .mockResolvedValue([product(PENDING, 'prod_a'), product(PENDING, 'prod_b')]);
    vi.spyOn(getApiClient(), 'requestCutout').mockResolvedValue(product(PENDING, 'prod_b'));
    await useProductsStore.getState().load('selune');
    await vi.advanceTimersByTimeAsync(2_000);
    expect(list).toHaveBeenCalledTimes(2);
    // 讀取還在路上時，商品 b 重新去背；之後才收到讀取當時的結果（b 還是完成的）
    await useProductsStore.getState().cutout('prod_b');
    late.arrive([product(DONE, 'prod_a'), product(DONE, 'prod_b')]);
    await vi.advanceTimersByTimeAsync(0);
    expect(useProductsStore.getState().products.map((p) => p.cutout?.status)).toEqual(['pending', 'pending']);
    // 舊結果不會讓輪詢停下來
    await vi.advanceTimersByTimeAsync(2_000);
    expect(list).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(list).toHaveBeenCalledTimes(4);
  });

  it('does not bring back a product that was removed while a poll was in flight', async () => {
    const late = lateRead();
    const list = vi.spyOn(getApiClient(), 'listProducts')
      .mockResolvedValueOnce([product(PENDING, 'prod_a'), product(PENDING, 'prod_b')])
      .mockReturnValueOnce(late.read)
      .mockResolvedValue([product(PENDING, 'prod_b')]);
    vi.spyOn(getApiClient(), 'deleteProduct').mockResolvedValue(undefined);
    await useProductsStore.getState().load('selune');
    await vi.advanceTimersByTimeAsync(2_000);
    await useProductsStore.getState().remove('prod_a');
    late.arrive([product(PENDING, 'prod_a'), product(PENDING, 'prod_b')]);
    await vi.advanceTimersByTimeAsync(0);
    expect(useProductsStore.getState().products.map((p) => p.id)).toEqual(['prod_b']);
    // 還有去背中的商品：輪詢繼續
    await vi.advanceTimersByTimeAsync(2_000);
    expect(list).toHaveBeenCalledTimes(3);
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
