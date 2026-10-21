import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { HistoryEntry, JobEvent, JobInput } from '@/types/contract';
import { FIXTURES_DIR } from '@/test/golden';
import { historyChunk } from './history';

/** selectedHistory 的商品（prod_selune_serum） */
const PRODUCT = '極光玻尿酸修護精華 30ml';

/** 與 backend/tests/test_rag_history.py 的 TEXT 相同：兩邊以同一筆歷史紀錄比對同一段文字 */
const TEXT =
  '極光玻尿酸修護精華 30ml・IG 貼文海報，審查 99 分。標題：一夜溫柔修護／醒來透亮發光。'
  + '副標：7天感受透亮光采・專業修護配方*。賣點：5重玻尿酸、神經醯胺、無香精。'
  + '正向提示詞：4:5 commercial product photography, the provided product photo on a styled surface, '
  + 'serene luxury skincare, crescent moo…';

/** 選定 selune-retry 任務的 IG 貼文最佳候選（第 2 輪 v0，審查 99 分）；與後端 tests/fixtures.py 的 selected_history 相同 */
function selectedHistory(): HistoryEntry {
  const timeline = JSON.parse(readFileSync(new URL('timelines/selune-retry.json', FIXTURES_DIR), 'utf8')) as {
    jobId: string; input: JobInput; events: { event: JobEvent }[];
  };
  const events = timeline.events.map((x) => x.event);
  const best = events.flatMap((e) => (e.type === 'job.completed' ? [e.bestRenderIds['ig-post']] : []))[0];
  const render = events.flatMap((e) => (e.type === 'render.completed' ? e.renders : [])).find((r) => r.id === best)!;
  return {
    id: 'hist_3fa2c1d0e9b8', jobId: timeline.jobId, brandId: 'selune', productId: timeline.input.productId, input: timeline.input,
    templateId: 'ig-post', render: { ...render, score: 99, passed: true }, copy: render.spec.copy,
    selectedAt: '2026-10-21T16:30:00.000Z', favorite: false, writtenToRag: false,
  };
}

describe('historyChunk', () => {
  it('builds the same chunk as the backend from the selected poster', () => {
    expect(historyChunk(selectedHistory(), PRODUCT)).toEqual({
      id: 'selune#hist-hist_3fa2c1d0e9b8',
      source: 'history/job_20261007_1000_a1b2',
      // 2026-10-21T16:30Z 是台灣時間 10 月 22 日 00:30（與執行測試的電腦時區無關）
      section: 'IG 貼文・2026-10-22',
      tag: 'history',
      text: TEXT,
    });
  });

  it('leaves out the product name when the product was deleted', () => {
    expect(historyChunk(selectedHistory(), null).text).toBe(TEXT.replace(`${PRODUCT}・`, ''));
  });

  it('leaves out empty fields and cuts the prompt at 120 code points (not UTF-16 units)', () => {
    const entry = selectedHistory();
    const edited = (score: number | null, positivePrompt: string, copy: Partial<HistoryEntry['copy']>): HistoryEntry => ({
      ...entry, templateId: 'story',
      render: { ...entry.render, score, spec: { ...entry.render.spec, positivePrompt } },
      copy: { ...entry.copy, ...copy },
    });
    const bare = edited(null, 'a'.repeat(120), { headline: ['只有一行', ''], subhead: '', features: [] });
    expect(historyChunk(bare, '商品').text).toBe(`商品・限時動態海報，未經審查評分。標題：只有一行。正向提示詞：${'a'.repeat(120)}`);
    const long = edited(80, '𠀀'.repeat(121), { headline: ['', ''], subhead: '副標', features: ['A'] });
    expect(historyChunk(long, null).text).toBe(`限時動態海報，審查 80 分。副標：副標。賣點：A。正向提示詞：${'𠀀'.repeat(120)}…`);
  });
});
