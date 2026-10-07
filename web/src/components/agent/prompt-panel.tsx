'use client';

import { useState } from 'react';
import { Copy } from 'lucide-react';
import { toast } from 'sonner';
import { EmptyState } from '@/components/common/empty-state';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { inlineDiff } from '@/lib/agent/diff';
import { injectionRows, specOptions, type InjectionRow } from '@/lib/agent/inspect';
import { getTemplate } from '@/lib/compose/templates';
import type { JobView } from '@/lib/jobs/view';
import { cn } from '@/lib/utils';

const CONTEXT = 24;

/** 改寫後的值：短的值顯示「舊 → 新」，長的文字只標出改變的片段 */
function ChangedValue({ row }: { row: InjectionRow }) {
  const before = String(row.previous ?? '');
  const after = String(row.value);
  if (after.length <= 40) {
    return (
      <>
        <span className="text-muted-foreground line-through">{before}</span> → <span className="font-semibold text-emerald-700">{after}</span>
      </>
    );
  }
  const d = inlineDiff(before, after);
  return (
    <>
      <span className="text-muted-foreground">{d.prefix.length > CONTEXT ? `…${d.prefix.slice(-CONTEXT)}` : d.prefix}</span>
      {d.removed && <del className="bg-red-100 text-red-700">{d.removed}</del>}
      {d.added && <ins className="bg-emerald-100 text-emerald-800 no-underline">{d.added}</ins>}
      <span className="text-muted-foreground">{d.suffix.length > CONTEXT ? `${d.suffix.slice(0, CONTEXT)}…` : d.suffix}</span>
    </>
  );
}

/** JSON Prompt 與 workflow_api.json 注入參數；與同模板上一輪比較，標出改寫後變動的參數 */
export function PromptPanel({ view }: { view: JobView }) {
  const options = specOptions(view);
  const [picked, setPicked] = useState<string | null>(null);
  // 預設看最新一輪，重試時可直接看到改寫後的參數
  const key = picked && view.specs[picked] ? picked : (options.at(-1)?.key ?? null);
  if (!key) {
    return <EmptyState icon={Copy} title="尚未產生 Prompt">Prompt 構建完成後，這裡會顯示每個模板每一輪的 JSON Prompt。</EmptyState>;
  }
  const spec = view.specs[key];
  const rows = injectionRows(view, key);
  const json = JSON.stringify(spec, null, 2);
  const changed = rows.filter((r) => r.changed).length;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(json);
      toast.success('已複製 JSON Prompt');
    } catch {
      toast.error('無法存取剪貼簿');
    }
  };

  return (
    <div className="space-y-4">
      <Select value={key} onValueChange={setPicked}>
        <SelectTrigger className="w-full bg-card sm:w-72" aria-label="選擇 Prompt">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o.key} value={o.key}>
              第 {o.round} 輪・{getTemplate(o.templateId).label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <div className="grid items-start gap-4 xl:grid-cols-2">
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>JSON Prompt</CardTitle>
            <CardDescription>LLM 產生的完整規格：文案、色票、版面 BBox、正負向提示詞與 RAG 引用。</CardDescription>
            <CardAction>
              <Button size="sm" variant="outline" onClick={() => void copy()}>
                <Copy />
                複製
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent>
            <pre className="max-h-[60vh] overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-xs leading-relaxed text-slate-200">
              {json}
            </pre>
          </CardContent>
        </Card>
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>workflow_api.json 注入參數</CardTitle>
            <CardDescription>
              {spec.injection.workflowFile}・{rows.length} 個參數
              {spec.round > 1 && `・與第 ${spec.round - 1} 輪相比改了 ${changed} 個`}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>節點</TableHead>
                  <TableHead>參數</TableHead>
                  <TableHead>值</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={`${r.nodeId}.${r.input}`} className={cn(r.changed && 'bg-amber-50 hover:bg-amber-50')}>
                    <TableCell className="align-top font-mono text-xs text-muted-foreground">
                      {r.nodeId}.{r.input}
                    </TableCell>
                    <TableCell className="align-top">
                      <span className="font-mono text-xs">{r.label}</span>
                      {r.changed && <Badge variant="outline" className="ml-1.5 border-amber-300 text-amber-800">已改寫</Badge>}
                    </TableCell>
                    <TableCell className="max-w-[28rem] font-mono text-xs break-all whitespace-normal" title={String(r.value)}>
                      {r.changed ? <ChangedValue row={r} /> : <span className="line-clamp-3">{String(r.value)}</span>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
