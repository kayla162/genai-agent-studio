'use client';

import { useRef, useState } from 'react';
import { CircleCheck, Database, FileText, LoaderCircle, Upload } from 'lucide-react';
import type { Brand, IngestEvent, RagChunk } from '@/types/contract';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { API_MODE, getApiClient } from '@/lib/api';
import { useAppStore } from '@/lib/store/app';
import { cn } from '@/lib/utils';
import { TAG_LABEL } from './chunk-list';

interface Ingest {
  status: 'running' | 'done' | 'error';
  source: string;
  chunks: RagChunk[];
  embedded: { chunkId: string; dims: number; preview: number[] }[];
  stored: { collection: string; count: number } | null;
  error: string | null;
}

function reduce(s: Ingest, e: IngestEvent): Ingest {
  switch (e.type) {
    case 'ingest.chunked':
      return { ...s, chunks: e.chunks };
    case 'ingest.embedded':
      return { ...s, embedded: [...s.embedded, { chunkId: e.chunkId, dims: e.dims, preview: e.preview }] };
    case 'ingest.stored':
      return { ...s, stored: { collection: e.collection, count: e.count } };
  }
}

function StepRow({ n, title, active, done, children }: { n: number; title: string; active: boolean; done: boolean; children?: React.ReactNode }) {
  return (
    <div className={cn('rounded-lg border p-3', active && 'border-primary bg-secondary/40')}>
      <p className="flex items-center gap-2 text-sm font-semibold">
        {done ? <CircleCheck className="size-4 text-success" /> : active ? <LoaderCircle className="size-4 animate-spin text-primary" /> : <span className="grid size-4 place-items-center rounded-full border text-[10px]">{n}</span>}
        {title}
      </p>
      {children && <div className="mt-2">{children}</div>}
    </div>
  );
}

/** 可選的檔案：live 由後端抽出文字（PDF 讀文字層）；示範模式在瀏覽器內讀取，只能讀文字檔 */
const ACCEPT = '.md,.markdown,.txt,.pdf,text/plain,text/markdown,application/pdf';
const FORMATS = API_MODE === 'live'
  ? '支援 .md、.txt 與 .pdf（PDF 需有文字層，掃描檔請先轉成文字）。'
  : '示範模式支援 .md 與 .txt（PDF 需要 live 模式）。';

/** 上傳品牌文件（.md／.txt／.pdf），展示 chunking → embedding → 寫入 Chroma 的過程 */
export function DocIngest({ brand }: { brand: Brand }) {
  const input = useRef<HTMLInputElement>(null);
  const loadBrands = useAppStore((s) => s.loadBrands);
  const [ingest, setIngest] = useState<Ingest | null>(null);

  const run = async (file: File) => {
    setIngest({ status: 'running', source: file.name, chunks: [], embedded: [], stored: null, error: null });
    try {
      await getApiClient().ingestBrandDocument(brand.id, file, (e) => setIngest((s) => (s ? reduce(s, e) : s)));
      setIngest((s) => (s ? { ...s, status: 'done' } : s));
      await loadBrands();
    } catch (err) {
      setIngest((s) => (s ? { ...s, status: 'error', error: err instanceof Error ? err.message : String(err) } : s));
    }
  };

  const total = ingest?.chunks.length ?? 0;
  const embedded = ingest?.embedded.length ?? 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>上傳品牌文件</CardTitle>
        <CardDescription>{FORMATS}Markdown 的 # 標題會成為切塊的段落名稱；同名文件重新上傳會取代舊的切塊。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Button variant="outline" disabled={ingest?.status === 'running'} onClick={() => input.current?.click()}>
          <Upload />
          選擇文件
        </Button>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void run(file);
            e.target.value = '';
          }}
        />
        {ingest && (
          <div className="space-y-2">
            <p className="flex items-center gap-1.5 text-sm text-muted-foreground"><FileText className="size-4" />{ingest.source}</p>
            <StepRow n={1} title={`切塊 Chunking${total ? `：${total} 塊` : ''}`} active={ingest.status === 'running' && !total} done={total > 0}>
              {total > 0 && (
                <ul className="space-y-1 text-xs">
                  {ingest.chunks.map((c) => (
                    <li key={c.id} className="truncate"><span className="mr-1.5 rounded bg-muted px-1">{TAG_LABEL[c.tag]}</span>{c.section}｜{c.text}</li>
                  ))}
                </ul>
              )}
            </StepRow>
            <StepRow n={2} title={`向量化 Embedding（bge-m3）${total ? `：${embedded}/${total}` : ''}`} active={total > 0 && embedded < total} done={total > 0 && embedded === total}>
              {total > 0 && (
                <div className="space-y-1.5">
                  <Progress value={(embedded / total) * 100} />
                  {ingest.embedded.at(-1) && (
                    <p className="truncate font-mono text-[11px] text-muted-foreground">
                      [{ingest.embedded.at(-1)!.preview.join(', ')}, …] · {ingest.embedded.at(-1)!.dims} 維
                    </p>
                  )}
                </div>
              )}
            </StepRow>
            <StepRow n={3} title="寫入 Chroma" active={total > 0 && embedded === total && !ingest.stored} done={ingest.stored !== null}>
              {ingest.stored && (
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Database className="size-3.5" />
                  collection「{ingest.stored.collection}」新增 {ingest.stored.count} 筆
                </p>
              )}
            </StepRow>
            {ingest.error && <p className="text-sm text-destructive">{ingest.error}</p>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
