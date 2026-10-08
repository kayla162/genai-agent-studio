import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ApiOptions, Brand } from '@/types/contract';
import { getApiClient } from '@/lib/api';

interface AppState {
  brandId: string;
  brands: Brand[];
  /** 目前可用的 LLM、VLM 與生圖引擎；載入前為 null */
  options: ApiOptions | null;
  setBrandId: (id: string) => void;
  /** 重新讀取品牌（上傳品牌文件後也要呼叫） */
  loadBrands: () => Promise<void>;
  loadOptions: () => Promise<void>;
}

/** 全域狀態：目前品牌（記在 localStorage）與品牌清單 */
export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      brandId: 'selune',
      brands: [],
      options: null,
      setBrandId: (brandId) => set({ brandId }),
      loadBrands: async () => {
        set({ brands: await getApiClient().listBrands() });
      },
      loadOptions: async () => {
        set({ options: await getApiClient().getOptions() });
      },
    }),
    // skipHydration：伺服器 render 用預設值，等 AppShell 掛載後才讀 localStorage，避免 hydration 不一致
    { name: 'genai-agent:app', partialize: (s) => ({ brandId: s.brandId }), skipHydration: true },
  ),
);

/** 目前品牌；AppShell 在品牌載入前不會 render 頁面，所以頁面內可視為一定有值 */
export function useCurrentBrand(): Brand {
  return useAppStore((s) => s.brands.find((b) => b.id === s.brandId) ?? s.brands[0]);
}
