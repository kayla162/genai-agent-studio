import { create } from 'zustand';
import type { Copy, Engine, JobInput, ParsedBrief, TemplateId, Tone } from '@/types/contract';
import { getApiClient } from '@/lib/api';
import { MOCK_OPTIONS } from '@/lib/api/mock/options';
import { defaultSelection, emptyJobView, reduceJob, type JobView } from '@/lib/jobs/view';

export const LLM_OPTIONS = MOCK_OPTIONS.llm;
export const VLM_OPTIONS = MOCK_OPTIONS.vlm;
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

const DEFAULT_FORM: Omit<StudioForm, 'brief'> = {
  productId: null, parsed: null, templateIds: ['ecom-main', 'ig-post'], variants: 4,
  llm: LLM_OPTIONS[0], engine: 'comfyui', vlm: VLM_OPTIONS[0], maxRetries: 2,
};

/** 事件訂閱放在 store 外：換頁再回來，生成仍在進行 */
let stopListening: (() => void) | null = null;
const stop = () => {
  stopListening?.();
  stopListening = null;
};

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

export const useStudioStore = create<StudioState>()((set, get) => ({
  ...DEFAULT_FORM,
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
      ...DEFAULT_FORM, brandId, brief: DEMO_BRIEFS[brandId] ?? '', parsing: false, starting: false,
      input: null, view: null, selection: {}, copy: null, saved: {}, error: null,
    });
  },

  prefill: (input) => {
    stop();
    set({
      brandId: input.brandId, brief: input.brief, productId: input.productId, parsed: structuredClone(input.parsedBrief),
      templateIds: [...input.templateIds], variants: input.variantsPerTemplate, llm: input.llm, engine: input.engine,
      vlm: input.vlm, maxRetries: input.maxRetries, input: null, view: null, selection: {}, copy: null, saved: {}, error: null,
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
      set({ parsed, input, view: emptyJobView(jobId), selection: {}, copy: null, saved: {} });
      stopListening = api.subscribe(
        jobId,
        (e) =>
          set((st) => {
            if (!st.view || st.view.jobId !== jobId) return {};
            const view = reduceJob(st.view, e);
            // 任務結束（完成或需人工審核）時：預設選最佳候選，文案編輯器帶入它的文案
            if (st.view.outcome === 'running' && (view.outcome === 'done' || view.outcome === 'needs_review')) {
              const selection = defaultSelection(view);
              const first = Object.values(selection)[0];
              return { view, selection, copy: first ? structuredClone(view.renders[first].spec.copy) : null };
            }
            return { view };
          }),
        (err) => set({ error: message(err) }),
      );
    } catch (err) {
      set({ error: message(err) });
    } finally {
      set({ starting: false });
    }
  },

  cancel: async () => {
    const jobId = get().view?.jobId;
    if (jobId) await getApiClient().cancelJob(jobId);
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
}));
