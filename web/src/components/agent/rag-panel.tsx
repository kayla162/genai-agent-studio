import { ArrowDown, ArrowUp, Search } from 'lucide-react';
import type { JobMessage } from '@/types/contract';
import { EmptyState } from '@/components/common/empty-state';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { rerankRows } from '@/lib/agent/inspect';
import type { JobView } from '@/lib/jobs/view';

function ScoreBar({ value, className }: { value: number | null; className: string }) {
  if (value === null) return <span className="text-muted-foreground">—</span>;
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
        <div className={className} style={{ width: `${Math.round(value * 100)}%`, height: '100%' }} />
      </div>
      <span className="font-mono text-xs">{value.toFixed(3)}</span>
    </div>
  );
}

function RankShift({ from, to }: { from: number; to: number | null }) {
  if (to === null || to === from) return <span className="text-muted-foreground">—</span>;
  const up = to < from;
  return (
    <span className={up ? 'inline-flex items-center text-emerald-600' : 'inline-flex items-center text-muted-foreground'}>
      {up ? <ArrowUp className="size-3.5" /> : <ArrowDown className="size-3.5" />}
      {Math.abs(from - to)}
    </span>
  );
}

/** RAG 召回與 Rerank：向量分數與 Rerank 分數、排名變化，以及哪些未通過的檢查引用了這段規範 */
export function RagPanel({ view, messages }: { view: JobView; messages: JobMessage[] }) {
  const rows = rerankRows(view);
  const queries = messages.flatMap((m) => (m.type === 'rag.retrieved' ? [m.query] : []));
  const checkName = new Map(view.renderIds.flatMap((id) => view.renders[id].checks.map((c) => [c.id, c.name] as const)));
  if (!rows.length) {
    return <EmptyState icon={Search} title="尚未檢索">RAG 檢索完成後，這裡會比較向量召回與 Rerank 後的排序。</EmptyState>;
  }
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Chroma 召回 → BGE Rerank</CardTitle>
          <CardDescription>查詢：{queries[0]}</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Rerank</TableHead>
                <TableHead>向量排名</TableHead>
                <TableHead>規範</TableHead>
                <TableHead>向量分數</TableHead>
                <TableHead>Rerank 分數</TableHead>
                <TableHead>被未通過的檢查引用</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.chunkId}>
                  <TableCell className="font-mono font-semibold">{r.rerankRank ?? '—'}</TableCell>
                  <TableCell>
                    <span className="mr-1.5 font-mono">{r.vectorRank}</span>
                    <RankShift from={r.vectorRank} to={r.rerankRank} />
                  </TableCell>
                  <TableCell className="max-w-[22rem] whitespace-normal">
                    <div className="flex items-center gap-1.5">
                      <Badge variant="secondary">{r.tag}</Badge>
                      <span className="text-sm font-medium">{r.section}</span>
                    </div>
                    <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground" title={r.text}>
                      {r.source}・{r.text}
                    </p>
                  </TableCell>
                  <TableCell><ScoreBar value={r.vectorScore} className="bg-slate-400" /></TableCell>
                  <TableCell><ScoreBar value={r.rerankScore} className="bg-primary" /></TableCell>
                  <TableCell className="whitespace-normal">
                    <div className="flex flex-wrap gap-1">
                      {r.citedBy.length
                        ? r.citedBy.map((id) => <Badge key={id} variant="outline" className="border-red-200 text-red-700">{checkName.get(id) ?? id}</Badge>)
                        : <span className="text-muted-foreground">—</span>}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      {view.requeryHits.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Query Rewriting 重新檢索</CardTitle>
            <CardDescription>查詢：{queries.slice(1).join('；')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {view.requeryHits.map((h) => (
              <div key={h.chunkId} className="rounded-lg border p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="secondary">{h.tag}</Badge>
                  <span className="font-medium">{h.section}</span>
                  <span className="ml-auto font-mono text-xs text-muted-foreground">
                    向量 {h.vectorScore.toFixed(3)}・Rerank {(h.rerankScore ?? 0).toFixed(3)}
                  </span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{h.source}・{h.text}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
