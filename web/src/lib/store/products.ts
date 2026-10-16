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

/** 有商品在去背中時，每隔這麼久重新讀取一次商品清單（毫秒） */
export const CUTOUT_POLL_MS = 2_000;

/** 目前品牌的商品清單（商品庫、新任務、批次佇列、歷史紀錄共用） */
export const useProductsStore = create<ProductsState>()((set, get) => {
  let poll: ReturnType<typeof setTimeout> | null = null;
  /** 商品清單被其他操作（載入、重新去背、刪除）改過就加一：讀取送出之後清單變了，回來的結果就是舊的 */
  let generation = 0;

  /** 有去背中的商品就排下一次讀取（同一時間只有一個計時器）；全部完成或失敗、或切換品牌後停止 */
  const schedulePoll = (brandId: string) => {
    if (poll) clearTimeout(poll);
    poll = null;
    if (!get().products.some((p) => p.cutout?.status === 'pending')) return;
    poll = setTimeout(() => {
      poll = null;
      if (get().brandId !== brandId) return;
      const sent = generation;
      // 結果回來時清單已被改過：丟掉（不寫入、也不排下一次；改動的那一方已經自己排了）
      const stale = () => generation !== sent || get().brandId !== brandId;
      getApiClient().listProducts(brandId).then(
        (products) => {
          if (stale()) return;
          set({ products });
          schedulePoll(brandId);
        },
        // 讀取失敗（例如後端重新啟動）：下一輪再試
        () => {
          if (!stale()) schedulePoll(brandId);
        },
      );
    }, CUTOUT_POLL_MS);
  };

  return {
    brandId: null,
    products: [],
    loading: false,
    cutting: [],
    load: async (brandId) => {
      if (poll) clearTimeout(poll);
      poll = null;
      generation += 1;
      set({ brandId, loading: true });
      let products: Product[];
      try {
        products = await getApiClient().listProducts(brandId);
      } catch (error) {
        // 載入失敗：不能一直停在載入中；清單裡有去背中的商品時也要繼續更新
        if (get().brandId === brandId) {
          set({ loading: false });
          schedulePoll(brandId);
        }
        throw error;
      }
      // 載入期間切換了品牌就丟棄舊結果
      if (get().brandId !== brandId) return;
      set({ products, loading: false });
      schedulePoll(brandId);
    },
    save: async (draft) => {
      const saved = await getApiClient().saveProduct(draft);
      if (get().brandId) await get().load(get().brandId!);
      return saved;
    },
    remove: async (id) => {
      await getApiClient().deleteProduct(id);
      generation += 1;
      set({ products: get().products.filter((p) => p.id !== id) });
      // 送出中的讀取結果會被丟掉，所以由這裡接著排下一次讀取
      const brandId = get().brandId;
      if (brandId) schedulePoll(brandId);
    },
    cutout: async (id) => {
      set({ cutting: [...get().cutting, id] });
      try {
        const updated = await getApiClient().requestCutout(id);
        generation += 1;
        set({ products: get().products.map((p) => (p.id === id ? updated : p)) });
        const brandId = get().brandId;
        if (brandId) schedulePoll(brandId);
        return updated;
      } finally {
        set({ cutting: get().cutting.filter((x) => x !== id) });
      }
    },
  };
});
