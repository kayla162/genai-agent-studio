import { afterEach, describe, expect, it, vi } from 'vitest';
import { getApiClient } from '@/lib/api';
import { MOCK_OPTIONS } from '@/lib/api/mock/options';
import { useAppStore } from './app';

afterEach(() => {
  vi.restoreAllMocks();
  useAppStore.setState({ brands: [], options: null, loadError: null });
});

describe('app store', () => {
  it('loads the models and engines the current API offers', async () => {
    expect(useAppStore.getState().options).toBeNull();
    await useAppStore.getState().loadOptions();
    expect(useAppStore.getState().options).toEqual(MOCK_OPTIONS);
  });

  it('records why the brands could not be loaded and clears it once they load', async () => {
    vi.spyOn(getApiClient(), 'listBrands').mockRejectedValueOnce(new Error('無法連線到後端，請確認服務已啟動'));
    await expect(useAppStore.getState().loadBrands()).rejects.toThrow('無法連線到後端');
    expect(useAppStore.getState().loadError).toBe('無法載入品牌資料：無法連線到後端，請確認服務已啟動');
    expect(useAppStore.getState().brands).toEqual([]);

    await useAppStore.getState().loadBrands();
    expect(useAppStore.getState().loadError).toBeNull();
    expect(useAppStore.getState().brands.length).toBeGreaterThan(0);
  });

  it('records why the options could not be loaded and clears it once they load', async () => {
    vi.spyOn(getApiClient(), 'getOptions').mockRejectedValueOnce(new Error('後端沒有回應（HTTP 502）'));
    await expect(useAppStore.getState().loadOptions()).rejects.toThrow('HTTP 502');
    expect(useAppStore.getState().loadError).toBe('無法載入模型與生圖引擎：後端沒有回應（HTTP 502）');
    expect(useAppStore.getState().options).toBeNull();

    await useAppStore.getState().loadOptions();
    expect(useAppStore.getState().loadError).toBeNull();
  });

  it('keeps one loader failure visible when the other loader succeeds', async () => {
    vi.spyOn(getApiClient(), 'listBrands').mockRejectedValueOnce(new Error('boom'));
    await Promise.allSettled([useAppStore.getState().loadBrands(), useAppStore.getState().loadOptions()]);
    expect(useAppStore.getState().options).toEqual(MOCK_OPTIONS);
    expect(useAppStore.getState().loadError).toBe('無法載入品牌資料：boom');

    await Promise.allSettled([useAppStore.getState().loadBrands(), useAppStore.getState().loadOptions()]);
    expect(useAppStore.getState().loadError).toBeNull();
  });
});
