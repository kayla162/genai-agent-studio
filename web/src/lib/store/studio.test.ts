import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getApiClient } from '@/lib/api';
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

  it('stops listening to the old job when the brand changes', async () => {
    await store().start();
    store().resetForBrand('misty-isle');
    await vi.advanceTimersByTimeAsync(14_500);
    expect(store().view).toBeNull();
    expect(store().brief).toBe(DEMO_BRIEFS['misty-isle']);
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
