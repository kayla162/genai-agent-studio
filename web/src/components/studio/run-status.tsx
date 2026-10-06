'use client';

import Link from 'next/link';
import { CircleCheck, Network, TriangleAlert } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { getTemplate } from '@/lib/compose/templates';
import { jobProgress, STAGE_LABEL, type JobView } from '@/lib/jobs/view';

/** 生成中的精簡進度；細節一鍵切到 Agent 透視 */
export function RunStatus({ view }: { view: JobView }) {
  const pct = Math.round(jobProgress(view) * 100);
  const lastLog = view.logs.at(-1);
  const retried = [...new Set(view.rewrites.map((r) => r.templateId))];
  const fixes = [...new Set(view.rewrites.flatMap((r) => r.fixes.map((f) => f.title)))];

  return (
    <Card>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          {view.outcome === 'done' && <CircleCheck className="size-5 text-success" />}
          {view.outcome === 'needs_review' && <TriangleAlert className="size-5 text-warning" />}
          <span className="font-semibold">{view.stage ? STAGE_LABEL[view.stage] : '排隊中'}</span>
          {view.round > 0 && <Badge variant="secondary">第 {view.round} 輪</Badge>}
          <span className="font-mono text-xs text-muted-foreground">{view.jobId}</span>
          <Link href={`/agent?job=${encodeURIComponent(view.jobId ?? '')}`} className="ml-auto inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline">
            <Network className="size-4" />
            在 Agent 透視查看細節
          </Link>
        </div>
        <Progress value={pct} className="h-2" />
        {view.outcome === 'running' && lastLog && <p className="truncate text-xs text-muted-foreground">{lastLog.message}</p>}
        {retried.length > 0 && (
          <p className="text-sm text-muted-foreground">
            {retried.map((t) => getTemplate(t).label).join('、')} 第 1 輪未通過審查，Query Rewriting 後重試：
            {fixes.map((f) => <Badge key={f} variant="outline" className="ml-1">{f}</Badge>)}
          </p>
        )}
        {view.outcome === 'needs_review' && (
          <p className="text-sm text-warning">{view.needsReviewReason}。可以檢視候選後手動選用，匯出前請人工確認。</p>
        )}
        {view.outcome === 'cancelled' && <p className="text-sm text-muted-foreground">任務已取消。</p>}
      </CardContent>
    </Card>
  );
}
