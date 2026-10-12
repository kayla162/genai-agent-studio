import { create } from 'zustand';
import type { Copy, Engine, JobInput, ParsedBrief, TemplateId, Tone } from '@/types/contract';
import { API_MODE, getApiClient } from '@/lib/api';
import { ApiError } from '@/lib/api/http/client';
import { MOCK_OPTIONS } from '@/lib/api/mock/options';
import { defaultSelection, emptyJobView, reduceJob, type JobView } from '@/lib/jobs/view';
import { useAppStore } from './app';

export const ENGINE_LABEL: Record<Engine, string> = { comfyui: 'ComfyUI（SDXL + ControlNet + IP-Adapter）', ideogram: 'Ideogram 4.0' };
export const TONE_LABEL: Record<Tone, string> = { gentle: '溫柔療癒', science: '專業科研', playful: '活潑年輕', minimal: '簡約' };

/** 各品牌的示範需求（第一個就是規格書的 Demo 句） */
export const DEMO_BRIEFS: Record<string, string> = {
  selune: '幫我做週年慶的精華液海報，主打買一送一，要溫柔療癒的感覺',
  'misty-isle': '幫我設計一款簡約風格的冷萃咖啡宣傳海報',
};

export interface StudioForm {
  brief: string;
  productId: string | null;
  parsed: ParsedBrief | null;
  templateIds: TemplateId[];
  variants: number;
  llm: string;
  engine: Engine;
  vlm: string;
  maxRetries: number;
}

interface StudioState extends StudioForm {
  brandId: string | null;
  parsing: boolean;
  starting: boolean;
  /** 目前（或上一個）任務的輸入 */
  input: JobInput | null;
  /** 還沒開始任務時為 null */
  view: JobView | null;
  /** 每個模板選定的候選 */
  selection: Partial<Record<TemplateId, string>>;
  /** 文字編輯器中的文案（所有選定的模板共用） */
  copy: Copy | null;
  /** 已寫入歷史紀錄的候選：renderId → 當時的文案（JSON），重複匯出時不重複寫入 */
  saved: Record<string, string>;
  error: string | null;
  setForm: (patch: Partial<StudioForm>) => void;
  patchParsed: (patch: Partial<ParsedBrief>) => void;
  toggleTemplate: (id: TemplateId) => void;
  /** 切換品牌：清掉表單與結果 */
  resetForBrand: (brandId: string) => void;
  /** 頁面載入後第一次進入：重設表單；這個分頁剛才有這個品牌的任務時接續顯示（執行中的繼續接收事件） */
  restore: (brandId: string) => Promise<void>;
  /** 歷史紀錄「以相同設定重做」 */
  prefill: (input: JobInput) => void;
  parse: () => Promise<void>;
  start: () => Promise<void>;
  cancel: () => Promise<void>;
  select: (templateId: TemplateId, renderId: string) => void;
  setCopy: (copy: Copy) => void;
  /** 把選定的候選與目前文案寫入歷史紀錄（標記已回寫 RAG）；回傳新寫入的筆數 */
  saveSelection: () => Promise<number>;
}

/** 表單預設值：模型與引擎取目前可用的第一個；live 模式真的會用到 GPU，預設每個模板 2 張 */
function defaultForm(): Omit<StudioForm, 'brief'> {
  const options = useAppStore.getState().options ?? MOCK_OPTIONS;
  return {
    productId: null, parsed: null, templateIds: ['ecom-main', 'ig-post'], variants: API_MODE === 'live' ? 2 : 4,
    llm: options.llm[0], engine: options.engines[0], vlm: options.vlm[0], maxRetries: 2,
  };
}

function formOf(input: JobInput): StudioForm {
  return {
    brief: input.brief, productId: input.productId, parsed: structuredClone(input.parsedBrief), templateIds: [...input.templateIds],
    variants: input.variantsPerTemplate, llm: input.llm, engine: input.engine, vlm: input.vlm, maxRetries: input.maxRetries,
  };
}

/** 這個分頁目前的任務（sessionStorage，重新整理後仍在）；沒有 sessionStorage 時（測試）記在模組內 */
interface CurrentJob { jobId: string; brandId: string }
const CURRENT_JOB_KEY = 'genai-agent:studio-job';
let currentJobFallback: CurrentJob | null = null;

function rememberJob(job: CurrentJob | null) {
  currentJobFallback = job;
  try {
    if (job) sessionStorage.setItem(CURRENT_JOB_KEY, JSON.stringify(job));
    else sessionStorage.removeItem(CURRENT_JOB_KEY);
  } catch {
    // 沒有 sessionStorage（測試環境、或瀏覽器停用儲存）
  }
}

function rememberedJob(): CurrentJob | null {
  try {
    const raw = sessionStorage.getItem(CURRENT_JOB_KEY);
    return raw ? (JSON.parse(raw) as CurrentJob) : null;
  } catch {
    return currentJobFallback;
  }
}

/** 事件訂閱放在 store 外：換頁再回來，生成仍在進行 */
let stopListening: (() => void) | null = null;
const stop = () => {
  stopListening?.();
  stopListening = null;
};

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

export const useStudioStore = create<StudioState>()((set, get) => {
  /** 接收任務事件（伺服器先重播已發生的事件）；任務結束時預設選最佳候選，文案編輯器帶入它的文案 */
  const follow = (jobId: string) => {
    stopListening = getApiClient().subscribe(
      jobId,
      (e) =>
        set((st) => {
          if (!st.view || st.view.jobId !== jobId) return {};
          const view = reduceJob(st.view, e);
          if (st.view.outcome === 'running' && (view.outcome === 'done' || view.outcome === 'needs_review')) {
            const selection = defaultSelection(view);
            const first = Object.values(selection)[0];
            return { view, selection, copy: first ? structuredClone(view.renders[first].spec.copy) : null };
          }
          return { view };
        }),
      (err) => set({ error: message(err) }),
    );
  };

  return {
    ...defaultForm(),
    brief: '',
    brandId: null,
    parsing: false,
    starting: false,
    input: null,
    view: null,
    selection: {},
    copy: null,
    saved: {},
    error: null,

    setForm: (patch) => set(patch),
    patchParsed: (patch) => {
      const parsed = get().parsed;
      if (parsed) set({ parsed: { ...parsed, ...patch } });
    },
    toggleTemplate: (id) => {
      const ids = get().templateIds;
      set({ templateIds: ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id] });
    },

    resetForBrand: (brandId) => {
      stop();
      set({
        ...defaultForm(), brandId, brief: DEMO_BRIEFS[brandId] ?? '', parsing: false, starting: false,
        input: null, view: null, selection: {}, copy: null, saved: {}, error: null,
      });
    },

    restore: async (brandId) => {
      get().resetForBrand(brandId);
      const current = rememberedJob();
      if (current?.brandId !== brandId) return;
      // 讀取期間使用者已切換品牌或開始新任務
      const superseded = () => get().brandId !== brandId || get().view !== null || get().starting;
      let input: JobInput;
      try {
        input = (await getApiClient().getJob(current.jobId)).summary.input;
      } catch (err) {
        // 後端連不上或出錯（ApiError 的 status 為 0 或 5xx）：任務可能還在執行，保留記錄，後端恢復後重新整理即可接續
        if (err instanceof ApiError && (err.status === 0 || err.status >= 500)) {
          if (!superseded()) set({ error: '無法讀取進行中的任務，請確認後端已啟動後重新整理頁面' });
          return;
        }
        // 任務已不存在（後端回 404，或 mock 模式重新整理後，執行中的任務不會保留）：不再記住
        rememberJob(null);
        return;
      }
      if (superseded()) return;
      set({ ...formOf(input), input, view: emptyJobView(current.jobId), selection: {}, copy: null, saved: {}, error: null });
      follow(current.jobId);
    },

    prefill: (input) => {
      stop();
      rememberJob(null);
      set({
        ...formOf(input), brandId: input.brandId, input: null, view: null, selection: {}, copy: null, saved: {}, error: null,
      });
    },

    parse: async () => {
      const { brandId, brief, productId } = get();
      if (!brandId || !brief.trim()) return;
      set({ parsing: true, error: null });
      try {
        set({ parsed: await getApiClient().parseBrief(brandId, brief, productId) });
      } catch (err) {
        set({ error: message(err) });
      } finally {
        set({ parsing: false });
      }
    },

    start: async () => {
      const s = get();
      if (!s.brandId) return;
      if (!s.brief.trim()) return set({ error: '請先輸入一句話需求' });
      if (!s.productId) return set({ error: '請先選擇商品' });
      if (!s.templateIds.length) return set({ error: '至少要選一個通路模板' });
      set({ starting: true, error: null });
      const api = getApiClient();
      try {
        const parsed = s.parsed ?? (await api.parseBrief(s.brandId, s.brief, s.productId));
        const input: JobInput = {
          brandId: s.brandId, productId: s.productId, brief: s.brief, parsedBrief: parsed, templateIds: [...s.templateIds],
          variantsPerTemplate: s.variants, llm: s.llm, engine: s.engine, vlm: s.vlm, maxRetries: s.maxRetries,
        };
        const { jobId } = await api.createJob(input);
        stop();
        rememberJob({ jobId, brandId: input.brandId });
        set({ parsed, input, view: emptyJobView(jobId), selection: {}, copy: null, saved: {} });
        follow(jobId);
      } catch (err) {
        set({ error: message(err) });
      } finally {
        set({ starting: false });
      }
    },

    cancel: async () => {
      const jobId = get().view?.jobId;
      if (!jobId) return;
      try {
        await getApiClient().cancelJob(jobId);
      } catch (err) {
        set({ error: message(err) });
      }
    },

    select: (templateId, renderId) => set({ selection: { ...get().selection, [templateId]: renderId } }),
    setCopy: (copy) => set({ copy }),

    saveSelection: async () => {
      const { view, selection, copy, saved } = get();
      if (!view?.jobId || !copy) return 0;
      const key = JSON.stringify(copy);
      const todo = Object.values(selection).filter((id): id is string => id !== undefined && saved[id] !== key);
      const api = getApiClient();
      for (const id of todo) await api.selectRender(view.jobId, id, copy);
      set({ saved: { ...get().saved, ...Object.fromEntries(todo.map((id) => [id, key])) } });
      return todo.length;
    },
  };
});
