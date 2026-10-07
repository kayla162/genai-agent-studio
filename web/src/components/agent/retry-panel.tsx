import { ArrowRight, GitCompareArrows } from 'lucide-react';
import { EmptyState } from '@/components/common/empty-state';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { retryDiffs } from '@/lib/agent/inspect';
import { getTemplate } from '@/lib/compose/templates';
import type { JobView } from '@/lib/jobs/view';

/** 重試 diff：每次 Query Rewriting 的原因、修正策略，以及改寫前後 Prompt 的差異 */
export function RetryPanel({ view }: { view: JobView }) {
  const diffs = retryDiffs(view);
  const checkName = new Map(view.renderIds.flatMap((id) => view.renders[id].checks.map((c) => [c.id, c.name] as const)));
  if (!diffs.length) {
    return (
      <EmptyState icon={GitCompareArrows} title={view.outcome === 'running' ? '尚未觸發重試' : '沒有重試'}>
        {view.outcome === 'running' ? '審查未通過時，這裡會顯示改寫前後的差異。' : '所有模板第一輪就通過了合規審查。'}
      </EmptyState>
    );
  }
  return (
    <div className="space-y-4">
      {diffs.map((d) => (
        <Card key={`${d.round}:${d.templateId}`}>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2">
              第 {d.round} 輪 → 第 {d.round + 1} 輪・{getTemplate(d.templateId).label}
              {d.scoreBefore !== null && (
                <Badge variant="outline" className="font-mono">
                  {d.scoreBefore} 分 <ArrowRight /> {d.scoreAfter ?? '…'} 分
                </Badge>
              )}
            </CardTitle>
            <CardDescription className="flex flex-wrap items-center gap-1">
              未通過：
              {d.reasons.map((id) => (
                <Badge key={id} variant="outline" className="border-red-200 text-red-700">{checkName.get(id) ?? id}</Badge>
              ))}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <ul className="grid gap-2 sm:grid-cols-2">
              {d.fixes.map((f) => (
                <li key={f.title} className="rounded-lg border bg-muted/40 p-3 text-sm">
                  <p className="font-semibold">{f.title}</p>
                  <p className="text-xs text-muted-foreground">{f.desc}</p>
                </li>
              ))}
            </ul>
            {d.requery && view.requeryHits.length > 0 && (
              <p className="text-sm text-muted-foreground">
                重新檢索：{view.requeryHits.map((h) => `${h.section}（${h.chunkId}）`).join('、')}
              </p>
            )}
            {d.diffs.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>欄位</TableHead>
                    <TableHead>改寫前</TableHead>
                    <TableHead>改寫後</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.diffs.map((x) => (
                    <TableRow key={x.path}>
                      <TableCell className="align-top font-mono text-xs">{x.path}</TableCell>
                      <TableCell className="max-w-[20rem] align-top text-xs break-all whitespace-normal text-red-700 line-through decoration-red-300">
                        {x.before}
                      </TableCell>
                      <TableCell className="max-w-[20rem] align-top text-xs break-all whitespace-normal text-emerald-700">{x.after}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className="text-sm text-muted-foreground">改寫中，下一輪的 Prompt 產生後會顯示差異。</p>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
