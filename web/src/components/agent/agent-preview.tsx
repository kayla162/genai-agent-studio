'use client';

import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Network } from 'lucide-react';
import type { JobSummary } from '@/types/contract';
import { EmptyState } from '@/components/common/empty-state';
import { PageHeader } from '@/components/common/page-header';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { getApiClient } from '@/lib/api';
import { emptyJobView, jobProgress, reduceJob, STAGE_LABEL } from '@/lib/jobs/view';
import { cn } from '@/lib/utils';

const LEVEL_COLOR = { info: 'text-slate-300', ok: 'text-emerald-300', warn: 'text-amber-300', error: 'text-red-300' } as const;

function JobLog({ jobId }: { jobId: string }) {
  const [view, setView] = useState(() => emptyJobView(jobId));
  useEffect(() => getApiClient().subscribe(jobId, (e) => setView((v) => reduceJob(v, e))), [jobId]);
  return (
    <Card>
      <CardHeader className="flex flex-row items-center gap-3">
        <CardTitle className="font-mono text-sm">{jobId}</CardTitle>
        <Badge variant="secondary">{view.stage ? STAGE_LABEL[view.stage] : '等待中'}</Badge>
        {view.round > 0 && <span className="text-xs text-muted-foreground">第 {view.round} 輪</span>}
      </CardHeader>
      <CardContent className="space-y-3">
        <Progress value={jobProgress(view) * 100} />
        <div className="max-h-[60vh] overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-xs leading-relaxed">
          {view.logs.map((l, i) => (
            <div key={i} className={LEVEL_COLOR[l.level]}>
              <span className="mr-2 text-slate-500">[{l.source.toUpperCase()}]</span>
              {l.message}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

/** Plan 2 的簡易版：選任務、看事件 Log。完整的任務透視在 Plan 3。 */
export function AgentPreview() {
  const router = useRouter();
  const params = useSearchParams();
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  useEffect(() => {
    void getApiClient().listJobs().then(setJobs);
  }, []);
  const jobId = params.get('job') ?? jobs?.[0]?.id ?? null;

  return (
    <>
      <PageHeader
        title="任務透視"
        description="流程節點圖、JSON Prompt、注入參數、RAG Rerank、BBox 疊圖與重試 diff 將在 Plan 3 完成；目前先顯示事件 Log。"
        actions={
          jobs && jobs.length > 0 ? (
            <Select value={jobId ?? ''} onValueChange={(id) => router.replace(`/agent?job=${encodeURIComponent(id)}`)}>
              <SelectTrigger className="w-72 bg-card">
                <SelectValue placeholder="選擇任務" />
              </SelectTrigger>
              <SelectContent>
                {jobs.map((j) => (
                  <SelectItem key={j.id} value={j.id}>
                    <span className="font-mono text-xs">{j.id}</span>
                    <span className={cn('text-xs', j.finished ? 'text-muted-foreground' : 'text-primary')}>{STAGE_LABEL[j.stage]}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : null
        }
      />
      {jobId ? (
        <JobLog key={jobId} jobId={jobId} />
      ) : (
        <EmptyState icon={Network} title="還沒有任務">到「新任務」開始生成後，這裡會顯示 Agent 的每一步。</EmptyState>
      )}
    </>
  );
}
