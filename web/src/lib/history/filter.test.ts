import { describe, it, expect } from 'vitest';
import type { HistoryEntry, TemplateId } from '@/types/contract';
import { filterHistory, localDate, type HistoryFilters } from './filter';

const at = (y: number, m: number, d: number, h = 12) => new Date(y, m - 1, d, h).toISOString();
const entry = (id: string, brandId: string, templateId: TemplateId, selectedAt: string, favorite = false) =>
  ({ id, brandId, templateId, selectedAt, favorite }) as HistoryEntry;

const ENTRIES = [
  entry('a', 'selune', 'ig-post', at(2026, 10, 1)),
  entry('b', 'selune', 'story', at(2026, 10, 3), true),
  entry('c', 'misty-isle', 'ig-post', at(2026, 10, 5)),
];
const ALL: HistoryFilters = { brandId: 'all', templateId: 'all', from: null, to: null, favoritesOnly: false };
const ids = (f: Partial<HistoryFilters>) => filterHistory(ENTRIES, { ...ALL, ...f }).map((e) => e.id);

describe('filterHistory', () => {
  it('returns everything newest first without filters', () => {
    expect(ids({})).toEqual(['c', 'b', 'a']);
  });

  it('filters by brand, channel and favorites', () => {
    expect(ids({ brandId: 'selune' })).toEqual(['b', 'a']);
    expect(ids({ templateId: 'ig-post' })).toEqual(['c', 'a']);
    expect(ids({ favoritesOnly: true })).toEqual(['b']);
  });

  it('filters by an inclusive local date range', () => {
    expect(ids({ from: '2026-10-03' })).toEqual(['c', 'b']);
    expect(ids({ to: '2026-10-03' })).toEqual(['b', 'a']);
    expect(ids({ from: '2026-10-02', to: '2026-10-04' })).toEqual(['b']);
  });

  it('localDate uses the local calendar day', () => {
    expect(localDate(new Date(2026, 9, 6, 23, 30).toISOString())).toBe('2026-10-06');
  });
});
