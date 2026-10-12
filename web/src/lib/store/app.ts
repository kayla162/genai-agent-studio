import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ApiOptions, Brand } from '@/types/contract';
import { getApiClient } from '@/lib/api';

interface AppState {
  brandId: string;
  brands: Brand[];
  /** 目前可用的 LLM、VLM 與生圖引擎；載入前為 null */
  options: ApiOptions | null;
  /** 品牌或模型選項載入失敗的原因（繁體中文）；兩者都載入成功後為 null */
  loadError: string | null;
  setBrandId: (id: string) => void;
  /** 重新讀取品牌（上傳品牌文件後也要呼叫） */
  loadBrands: () => Promise<void>;
  loadOptions: () => Promise<void>;
}

const BRANDS_ERROR = '無法載入品牌資料：';
const OPTIONS_ERROR = '無法載入模型與生圖引擎：';

const reason = (error: unknown) => (error instanceof Error ? error.message : String(error));

/** 全域狀態：目前品牌（記在 localStorage）與品牌清單 */
export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      brandId: 'selune',
      brands: [],
      options: null,
      loadError: null,
      setBrandId: (brandId) => set({ brandId }),
      // 失敗時記下原因（AppShell 據此顯示重試）並照樣丟出錯誤；成功時只清除自己造成的錯誤，不蓋掉另一個載入的失敗
      loadBrands: async () => {
        try {
          const brands = await getApiClient().listBrands();
          set((s) => ({ brands, loadError: s.loadError?.startsWith(BRANDS_ERROR) ? null : s.loadError }));
        } catch (error) {
          set({ loadError: BRANDS_ERROR + reason(error) });
          throw error;
        }
      },
      loadOptions: async () => {
        try {
          const options = await getApiClient().getOptions();
          set((s) => ({ options, loadError: s.loadError?.startsWith(OPTIONS_ERROR) ? null : s.loadError }));
        } catch (error) {
          set({ loadError: OPTIONS_ERROR + reason(error) });
          throw error;
        }
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
