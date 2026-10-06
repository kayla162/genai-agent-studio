'use client';

import { useState } from 'react';
import type { RagChunk, RagTag } from '@/types/contract';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

export const TAG_LABEL: Record<RagTag, string> = {
  color: '色彩', logo: 'Logo', law: '法規', layout: '版型', font: '字型', history: '歷史成效', general: '其他',
};

/** CI 手冊切塊（Chroma 中的向量片段），可依標籤篩選 */
export function ChunkList({ chunks }: { chunks: RagChunk[] }) {
  const [tag, setTag] = useState<RagTag | 'all'>('all');
  const tags = [...new Set(chunks.map((c) => c.tag))];
  const visible = tag === 'all' ? chunks : chunks.filter((c) => c.tag === tag);
  return (
    <Card>
      <CardHeader>
        <CardTitle>CI 手冊切塊（{chunks.length}）</CardTitle>
        <CardDescription>RAG 檢索的來源：Chroma 向量召回後，再由 BGE Reranker 重新排序。</CardDescription>
        <div className="flex flex-wrap gap-1.5 pt-1">
          {(['all', ...tags] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTag(t)}
              className={cn('rounded-full border px-2.5 py-0.5 text-xs', tag === t ? 'border-primary bg-secondary font-semibold text-primary' : 'text-muted-foreground')}
            >
              {t === 'all' ? '全部' : TAG_LABEL[t]}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent>
        <ul className="divide-y rounded-lg border">
          {visible.map((c) => (
            <li key={c.id} className="space-y-1 px-3 py-2.5">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <Badge variant="secondary">{TAG_LABEL[c.tag]}</Badge>
                <span className="font-medium">{c.section}</span>
                <span className="text-muted-foreground">{c.source}</span>
                {c.id.includes('#doc-') && <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-emerald-700">新上傳</Badge>}
                {c.id.endsWith('-alt') && <Badge variant="outline">Query Rewriting 專用</Badge>}
                <span className="ml-auto font-mono text-[11px] text-muted-foreground">{c.id}</span>
              </div>
              <p className="text-sm leading-relaxed">{c.text}</p>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
