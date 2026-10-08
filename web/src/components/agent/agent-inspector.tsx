'use client';

import { useEffect, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Network } from 'lucide-react';
import type { JobInput, JobMessage, JobSummary } from '@/types/contract';
import { EmptyState } from '@/components/common/empty-state';
import { PageHeader } from '@/components/common/page-header';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { getApiClient } from '@/lib/api';
import { formatDuration } from '@/lib/agent/events';
import { flowState, type FlowState } from '@/lib/agent/flow';
import { getTemplate } from '@/lib/compose/templates';
import { jobProgress, STAGE_LABEL, withLiveStage, type JobView } from '@/lib/jobs/view';
import { useAppStore } from '@/lib/store/app';
import { cn } from '@/lib/utils';
import { EventStream } from './event-stream';
import { FlowGraph } from './flow-graph';
import { PromptPanel } from './prompt-panel';
import { RagPanel } from './rag-panel';
import { RetryPanel } from './retry-panel';
import { ReviewPanel } from './review-panel';
import { useJobStream } from './use-job-stream';

function JobPicker({ jobs, value, onChange, onOpen }: {
  jobs: JobSummary[]; value: string; onChange: (id: string) => void; onOpen: () => void;
}) {
  return (
    <Select value={value} onValueChange={onChange} onOpenChange={(open) => open && onOpen()}>
      <SelectTrigger className="w-full bg-card sm:w-80" aria-label="選擇任務">
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
  );
}

function AgentHeader({ actions }: { actions?: ReactNode }) {
  return (
    <PageHeader
      title="任務透視"
      description="Agent 每一步的輸入與輸出：流程節點、WebSocket 事件、JSON Prompt、注入參數、RAG Rerank、合規報告與重試 diff。"
      actions={actions}
    />
  );
}

function JobHeader({ view, flow, messages, input }: { view: JobView; flow: FlowState; messages: JobMessage[]; input: JobInput | null }) {
  const brand = useAppStore((s) => s.brands.find((b) => b.id === input?.brandId));
  return (
    <Card>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm font-semibold">{view.jobId}</span>
          <Badge variant="secondary">{view.stage ? STAGE_LABEL[view.stage] : '等待事件'}</Badge>
          {view.round > 0 && <Badge variant="outline">第 {view.round} 輪</Badge>}
          <span className="ml-auto text-xs text-muted-foreground">
            {messages.length} 則事件・{formatDuration(flow.elapsedMs)}
          </span>
        </div>
        {input && (
          <p className="text-sm text-muted-foreground">
            {brand?.name ?? input.brandId}・「{input.brief}」・{input.templateIds.map((t) => getTemplate(t).label).join('、')}
            ・每個模板 {input.variantsPerTemplate} 張・最多重試 {input.maxRetries} 次
          </p>
        )}
        <Progress value={jobProgress(view) * 100} className="h-2" />
      </CardContent>
    </Card>
  );
}

function JobInspector({ jobId, jobs, onPick, onOpenPicker }: {
  jobId: string; jobs: JobSummary[] | null; onPick: (id: string) => void; onOpenPicker: () => void;
}) {
  const { messages, view, error } = useJobStream(jobId);
  const input = jobs?.find((j) => j.id === jobId)?.input ?? null;
  // 選單裡正在看的任務用事件串流的即時階段，與下方的流程節點一致
  const header = (
    <AgentHeader
      actions={
        jobs && jobs.length > 0 ? (
          <JobPicker jobs={withLiveStage(jobs, view)} value={jobId} onChange={onPick} onOpen={onOpenPicker} />
        ) : null
      }
    />
  );
  if (error) {
    return (
      <>
        {header}
        <Alert variant="destructive">
          <AlertTitle>無法載入任務</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </>
    );
  }
  const flow = flowState(messages);
  return (
    <>
      {header}
      <div className="space-y-5">
        <JobHeader view={view} flow={flow} messages={messages} input={input} />
        <FlowGraph flow={flow} view={view} input={input} />
        <Tabs defaultValue="events">
          {/* line 樣式：主題的 background 與 muted 顏色接近，預設樣式看不出目前分頁 */}
          <TabsList variant="line" className="h-auto flex-wrap">
            <TabsTrigger value="events">事件串流</TabsTrigger>
            <TabsTrigger value="prompt">Prompt 與注入參數</TabsTrigger>
            <TabsTrigger value="rag">RAG Rerank</TabsTrigger>
            <TabsTrigger value="review">合規報告</TabsTrigger>
            <TabsTrigger value="retry">重試 diff{view.rewrites.length > 0 && `（${view.rewrites.length}）`}</TabsTrigger>
          </TabsList>
          <TabsContent value="events">
            <EventStream messages={messages} />
          </TabsContent>
          <TabsContent value="prompt">
            <PromptPanel view={view} />
          </TabsContent>
          <TabsContent value="rag">
            <RagPanel view={view} messages={messages} />
          </TabsContent>
          <TabsContent value="review">
            <ReviewPanel view={view} input={input} />
          </TabsContent>
          <TabsContent value="retry">
            <RetryPanel view={view} />
          </TabsContent>
        </Tabs>
      </div>
    </>
  );
}

/** Agent 透視：預設顯示最新的任務，可切換 */
export function AgentInspector() {
  const router = useRouter();
  const params = useSearchParams();
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  // 網址沒有指定任務時，顯示進入頁面時最新的任務；之後重新讀取列表不會換掉正在看的任務
  const [latestId, setLatestId] = useState<string | null>(null);
  // 打開任務選單時遞增，重新讀取列表：其他任務的階段可能已改變，也可能有之後才開始的任務
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let alive = true;
    void getApiClient().listJobs().then((j) => {
      if (!alive) return;
      setJobs(j);
      setLatestId((id) => id ?? j[0]?.id ?? null);
    });
    return () => {
      alive = false;
    };
  }, [version]);
  const jobId = params.get('job') ?? latestId;

  if (jobId) {
    return (
      <JobInspector
        key={jobId}
        jobId={jobId}
        jobs={jobs}
        onPick={(id) => router.replace(`/agent?job=${encodeURIComponent(id)}`)}
        onOpenPicker={() => setVersion((v) => v + 1)}
      />
    );
  }
  return (
    <>
      <AgentHeader />
      {jobs && (
        <EmptyState icon={Network} title="還沒有任務">
          到<Link href="/studio" className="mx-1 font-medium text-primary hover:underline">新任務</Link>
          開始生成後，這裡會顯示 Agent 的每一步。
        </EmptyState>
      )}
    </>
  );
}
