import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getApiClient } from '@/lib/api';
import { ApiError } from '@/lib/api/http/client';
import { useAppStore } from './app';
import { DEMO_BRIEFS, useStudioStore } from './studio';

const store = () => useStudioStore.getState();

beforeEach(() => {
  vi.useFakeTimers();
  getApiClient().demo?.set({ speed: 1, firstRoundFail: true, forceAllFail: false });
  store().resetForBrand('selune');
  store().setForm({ productId: 'prod_selune_serum', templateIds: ['ig-post'] });
});
afterEach(() => {
  vi.useRealTimers();
  useAppStore.setState({ options: null });
});

describe('studio store', () => {
  it('starts from the brand demo brief', () => {
    expect(store().brief).toBe(DEMO_BRIEFS.selune);
    expect(store().view).toBeNull();
  });

  it('takes the default models and engine from the available options', () => {
    expect(store()).toMatchObject({ llm: 'Gemini 3.7 Flash', vlm: 'Gemini 3.7 Vision', engine: 'comfyui', variants: 4 });
    useAppStore.setState({ options: { llm: ['Gemini 3 Flash'], vlm: ['Gemini 3 Flash'], engines: ['comfyui' as const] } });
    store().resetForBrand('misty-isle');
    expect(store()).toMatchObject({ llm: 'Gemini 3 Flash', vlm: 'Gemini 3 Flash', engine: 'comfyui' });
  });

  it('parses the brief and lets the user edit the parsed fields', async () => {
    await store().parse();
    expect(store().parsed).toMatchObject({ campaign: '週年慶', offer: '買一送一', tone: 'gentle' });
    store().patchParsed({ audience: '25–35 歲上班族' });
    expect(store().parsed!.audience).toBe('25–35 歲上班族');
  });

  it('runs a job, then selects the best render and loads its copy into the editor', async () => {
    await store().start();
    expect(store().view!.outcome).toBe('running');
    expect(store().input!.templateIds).toEqual(['ig-post']);
    await vi.advanceTimersByTimeAsync(14_500);
    const { view, selection, copy } = store();
    expect(view!.outcome).toBe('done');
    expect(selection['ig-post']).toBe(view!.bestRenderIds['ig-post']);
    expect(copy).toEqual(view!.renders[selection['ig-post']!].spec.copy);
    expect(Object.isFrozen(copy)).toBe(false);
  });

  it('writes the selection to history once per copy version', async () => {
    store().setForm({ templateIds: ['ig-post', 'story'] });
    await store().start();
    await vi.advanceTimersByTimeAsync(14_500);
    const before = (await getApiClient().listHistory('selune')).length;
    expect(await store().saveSelection()).toBe(2);
    expect(await store().saveSelection()).toBe(0);
    store().setCopy({ ...store().copy!, subhead: '改過的副標' });
    expect(await store().saveSelection()).toBe(2);
    const history = await getApiClient().listHistory('selune');
    expect(history.length - before).toBe(4);
    expect(history[0].copy.subhead).toBe('改過的副標');
  });

  it('validates the form before starting', async () => {
    store().setForm({ templateIds: [] });
    await store().start();
    expect(store().error).toBe('至少要選一個通路模板');
    expect(store().view).toBeNull();
  });

  it('cancels a running job', async () => {
    await store().start();
    await vi.advanceTimersByTimeAsync(2_000);
    await store().cancel();
    expect(store().view!.outcome).toBe('cancelled');
  });

  it('reports a failed cancel instead of throwing', async () => {
    await store().start();
    const cancelJob = vi.spyOn(getApiClient(), 'cancelJob').mockRejectedValueOnce(new Error('後端沒有回應'));
    await expect(store().cancel()).resolves.toBeUndefined();
    expect(store().error).toBe('後端沒有回應');
    cancelJob.mockRestore();
  });

  it('stops listening to the old job when the brand changes', async () => {
    await store().start();
    store().resetForBrand('misty-isle');
    await vi.advanceTimersByTimeAsync(14_500);
    expect(store().view).toBeNull();
    expect(store().brief).toBe(DEMO_BRIEFS['misty-isle']);
  });

  it('picks up the current job again after the page reloads', async () => {
    await store().start();
    await vi.advanceTimersByTimeAsync(3_000);
    const jobId = store().view!.jobId;
    // 重新整理：store 回到初始狀態，任務仍在執行
    useStudioStore.setState({ brandId: null, view: null, input: null, templateIds: ['ecom-main'] });
    await store().restore('selune');
    expect(store()).toMatchObject({ brandId: 'selune', templateIds: ['ig-post'], input: { templateIds: ['ig-post'] } });
    expect(store().view!.jobId).toBe(jobId);
    await vi.advanceTimersByTimeAsync(14_500);
    expect(store().view!.outcome).toBe('done');
    expect(store().selection['ig-post']).toBe(store().view!.bestRenderIds['ig-post']);
  });

  it('starts empty after a reload when the job belongs to another brand or no longer exists', async () => {
    await store().start();
    useStudioStore.setState({ brandId: null, view: null });
    await store().restore('misty-isle');
    expect(store()).toMatchObject({ brandId: 'misty-isle', view: null });

    const getJob = vi.spyOn(getApiClient(), 'getJob').mockRejectedValueOnce(new Error('Unknown job'));
    useStudioStore.setState({ brandId: null, view: null });
    await store().restore('selune');
    expect(store().view).toBeNull();
    // 找不到的任務不再記住
    useStudioStore.setState({ brandId: null, view: null });
    await store().restore('selune');
    expect(getJob).toHaveBeenCalledTimes(1);
    getJob.mockRestore();
  });

  it('prefills the form from a previous job input', async () => {
    await store().parse();
    const input = {
      brandId: 'selune', productId: 'prod_selune_serum', brief: '再做一次', parsedBrief: store().parsed!,
      templateIds: ['story' as const], variantsPerTemplate: 2, llm: 'Gemini 3.7 Flash', engine: 'ideogram' as const,
      vlm: 'Gemini 3.7 Vision', maxRetries: 1,
    };
    store().prefill(input);
    expect(store()).toMatchObject({ brief: '再做一次', templateIds: ['story'], variants: 2, engine: 'ideogram', maxRetries: 1, view: null });
  });
});

describe('studio store restore when reading the job fails', () => {
  const KEY = 'genai-agent:studio-job';
  let storage: Map<string, string>;

  /** 重新整理：store 回到初始狀態；sessionStorage（測試中以記憶體模擬）保留這個分頁的任務 */
  async function startAndReload() {
    await store().start();
    const jobId = store().view!.jobId!;
    useStudioStore.setState({ brandId: null, view: null, input: null });
    return jobId;
  }

  beforeEach(() => {
    storage = new Map();
    vi.stubGlobal('sessionStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => void storage.set(key, value),
      removeItem: (key: string) => void storage.delete(key),
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it.each([
    ['the backend cannot be reached', new ApiError('network', '無法連線到後端，請確認服務已啟動', 0)],
    ['the backend fails', new ApiError('http_error', '後端回應 HTTP 503', 503)],
  ])('keeps the remembered job and reports the error when %s', async (_name, failure) => {
    const jobId = await startAndReload();
    const getJob = vi.spyOn(getApiClient(), 'getJob').mockRejectedValueOnce(failure);
    await store().restore('selune');
    expect(store().view).toBeNull();
    expect(store().error).toBe('無法讀取進行中的任務，請確認後端已啟動後重新整理頁面');
    expect(JSON.parse(storage.get(KEY)!)).toEqual({ jobId, brandId: 'selune' });

    // 後端恢復後重新整理，仍接續同一個任務
    useStudioStore.setState({ brandId: null, view: null, input: null });
    await store().restore('selune');
    expect(store().view!.jobId).toBe(jobId);
    expect(store().error).toBeNull();
    getJob.mockRestore();
  });

  it('forgets the remembered job when the backend says it does not exist', async () => {
    await startAndReload();
    const getJob = vi.spyOn(getApiClient(), 'getJob').mockRejectedValueOnce(new ApiError('not_found', '找不到任務', 404));
    await store().restore('selune');
    expect(store()).toMatchObject({ view: null, error: null });
    expect(storage.has(KEY)).toBe(false);
    getJob.mockRestore();
  });

  it('does not overwrite the form when the user started a job while the old one was loading', async () => {
    const jobId = await startAndReload();
    const snapshot = await getApiClient().getJob(jobId);
    let release!: () => void;
    const getJob = vi.spyOn(getApiClient(), 'getJob').mockImplementationOnce(
      () => new Promise((resolve) => (release = () => resolve(snapshot))),
    );
    const restoring = store().restore('selune');
    store().setForm({ brief: '剛輸入的新需求' });
    useStudioStore.setState({ starting: true });
    release();
    await restoring;
    expect(store()).toMatchObject({ brief: '剛輸入的新需求', view: null, starting: true });
    getJob.mockRestore();
  });
});
