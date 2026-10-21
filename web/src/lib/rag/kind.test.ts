import { describe, expect, it } from 'vitest';
import { CHUNK_KIND_LABEL, chunkKind } from './kind';

describe('chunkKind', () => {
  it('tells uploaded, written-back, case-study and Query Rewriting chunks apart by id', () => {
    const ids = ['selune#doc-26kz3d-1', 'selune#hist-hist_3fa2c1d0e9b8', 'selune#case-2', 'selune#law-alt', 'selune#color'];
    expect(ids.map((id) => chunkKind(id))).toEqual(['upload', 'history', 'case', 'alt', null]);
    expect(ids.map((id) => {
      const kind = chunkKind(id);
      return kind && CHUNK_KIND_LABEL[kind];
    })).toEqual(['新上傳', '歷史回寫', '歷史案例', 'Query Rewriting 專用', null]);
  });
});
