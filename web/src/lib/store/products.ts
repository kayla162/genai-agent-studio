import { create } from 'zustand';
import type { Product } from '@/types/contract';
import { getApiClient, type ProductDraft } from '@/lib/api';

interface ProductsState {
  brandId: string | null;
  products: Product[];
  loading: boolean;
  load: (brandId: string) => Promise<void>;
  save: (draft: ProductDraft) => Promise<Product>;
  remove: (id: string) => Promise<void>;
  /** 去背進行中的商品 id */
  cutting: string[];
  cutout: (id: string) => Promise<Product>;
}

/** 目前品牌的商品清單（商品庫、新任務、批次佇列、歷史紀錄共用） */
export const useProductsStore = create<ProductsState>()((set, get) => ({
  brandId: null,
  products: [],
  loading: false,
  cutting: [],
  load: async (brandId) => {
    set({ brandId, loading: true });
    const products = await getApiClient().listProducts(brandId);
    // 載入期間切換了品牌就丟棄舊結果
    if (get().brandId === brandId) set({ products, loading: false });
  },
  save: async (draft) => {
    const saved = await getApiClient().saveProduct(draft);
    if (get().brandId) await get().load(get().brandId!);
    return saved;
  },
  remove: async (id) => {
    await getApiClient().deleteProduct(id);
    set({ products: get().products.filter((p) => p.id !== id) });
  },
  cutout: async (id) => {
    set({ cutting: [...get().cutting, id] });
    try {
      const updated = await getApiClient().requestCutout(id);
      set({ products: get().products.map((p) => (p.id === id ? updated : p)) });
      return updated;
    } finally {
      set({ cutting: get().cutting.filter((x) => x !== id) });
    }
  },
}));
