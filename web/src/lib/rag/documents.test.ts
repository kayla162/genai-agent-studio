import { describe, expect, it } from 'vitest';
import type { RagChunk } from '@/types/contract';
import { uploadedDocuments } from './documents';

const chunk = (id: string, source: string): RagChunk => ({ id, source, section: '色彩', tag: 'color', text: '主色' });

describe('uploadedDocuments', () => {
  it('groups uploaded chunks by file name in order and skips config, history and case chunks', () => {
    const chunks = [
      chunk('selune#color', 'brand_guideline_v2.3.pdf'),
      chunk('selune#doc-a1b2-1', '手冊.md'),
      chunk('selune#hist-9', 'history'),
      chunk('selune#doc-c3d4-1', 'ci.pdf'),
      chunk('selune#doc-a1b2-2', '手冊.md'),
      chunk('selune#case-1', 'selune.yaml'),
    ];
    expect(uploadedDocuments(chunks)).toEqual([{ source: '手冊.md', chunks: 2 }, { source: 'ci.pdf', chunks: 1 }]);
    expect(uploadedDocuments([chunk('selune#law-alt', 'selune.yaml')])).toEqual([]);
  });
});
