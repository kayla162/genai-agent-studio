import { create } from 'zustand';
import type { TemplateId } from '@/types/contract';
import { getApiClient } from '@/lib/api';
import { emptyJobView, reduceJob, type JobView } from '@/lib/jobs/view';
import { MOCK_OPTIONS } from '@/lib/api/mock/options';
import { useAppStore } from './app';

/** pending 等待中、held 此筆暫停（輪到也不啟動） */
export type QueueStatus = 'pending' | 'held' | 'running' | 'done' | 'needs_review' | 'cancelled' | 'error';

export interface QueueItem {
  id: string;
  brandId: string;
  productId: string;
  productName: string;
  brief: string;
  templateIds: TemplateId[];
  variants: number;
  status: QueueStatus;
  jobId: string | null;
  view: JobView | null;
  error: string | null;
}

export interface BatchRequest {
  brandId: string;
  brief: string;
  products: { id: string; name: string }[];
  templateIds: TemplateId[];
  variants: number;
}

interface QueueState {
  items: QueueItem[];
  /** 整個佇列暫停：執行中的這筆會跑完，但不再啟動下一筆 */
  paused: boolean;
  enqueue: (batch: BatchRequest) => void;
  togglePause: () => void;
  hold: (id: string) => void;
  release: (id: string) => void;
  cancel: (id: string) => Promise<void>;
  clearFinished: () => void;
  /** 沒有執行中的項目且未暫停時，啟動下一筆 */
  pump: () => Promise<void>;
}

const FINISHED: QueueStatus[] = ['done', 'needs_review', 'cancelled', 'error'];
export const isFinished = (s: QueueStatus) => FINISHED.includes(s);

let seq = 0;
const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

/** 批次佇列：多商品 × 多模板，一次執行一筆（每筆是一個商品的任務） */
export const useQueueStore = create<QueueState>()((set, get) => {
  const update = (id: string, patch: Partial<QueueItem>) =>
    set({ items: get().items.map((i) => (i.id === id ? { ...i, ...patch } : i)) });

  return {
    items: [],
    paused: false,

    enqueue: ({ brandId, brief, products, templateIds, variants }) => {
      const added: QueueItem[] = products.map((p) => ({
        id: `q${++seq}`, brandId, productId: p.id, productName: p.name, brief, templateIds: [...templateIds], variants,
        status: 'pending', jobId: null, view: null, error: null,
      }));
      set({ items: [...get().items, ...added] });
      void get().pump();
    },

    togglePause: () => {
      set({ paused: !get().paused });
      void get().pump();
    },
    hold: (id) => {
      if (get().items.find((i) => i.id === id)?.status === 'pending') update(id, { status: 'held' });
    },
    release: (id) => {
      if (get().items.find((i) => i.id === id)?.status === 'held') update(id, { status: 'pending' });
      void get().pump();
    },
    cancel: async (id) => {
      const item = get().items.find((i) => i.id === id);
      if (!item) return;
      if (item.status === 'running' && item.jobId) await getApiClient().cancelJob(item.jobId);
      else if (item.status === 'pending' || item.status === 'held') update(id, { status: 'cancelled' });
    },
    clearFinished: () => set({ items: get().items.filter((i) => !isFinished(i.status)) }),

    pump: async () => {
      const { paused, items } = get();
      if (paused || items.some((i) => i.status === 'running')) return;
      const next = items.find((i) => i.status === 'pending');
      if (!next) return;
      update(next.id, { status: 'running', error: null });
      const api = getApiClient();
      const options = useAppStore.getState().options ?? MOCK_OPTIONS;
      const fail = (err: unknown) => {
        update(next.id, { status: 'error', error: message(err) });
        void get().pump();
      };
      try {
        const parsedBrief = await api.parseBrief(next.brandId, next.brief, next.productId);
        const { jobId } = await api.createJob({
          brandId: next.brandId, productId: next.productId, brief: next.brief, parsedBrief, templateIds: next.templateIds,
          variantsPerTemplate: next.variants, llm: options.llm[0], engine: options.engines[0], vlm: options.vlm[0], maxRetries: 2,
        });
        update(next.id, { jobId, view: emptyJobView(jobId) });
        let finished = false;
        let unsubscribe: (() => void) | null = null;
        unsubscribe = api.subscribe(
          jobId,
          (e) => {
            const item = get().items.find((i) => i.id === next.id);
            if (!item?.view) return;
            const view = reduceJob(item.view, e);
            const status: QueueStatus = view.outcome === 'running' ? 'running' : view.outcome === 'failed' ? 'error' : view.outcome;
            update(next.id, { view, status, error: view.failureReason });
            if (status !== 'running' && !finished) {
              finished = true;
              unsubscribe?.();
              void get().pump();
            }
          },
          fail,
        );
        if (finished) unsubscribe();
      } catch (err) {
        fail(err);
      }
    },
  };
});
