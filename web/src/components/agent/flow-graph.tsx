import { RotateCcw } from 'lucide-react';
import type { JobInput, RenderNode } from '@/types/contract';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { formatDuration } from '@/lib/agent/events';
import { FLOW_NODES, type FlowNodeId, type FlowState, type FlowStatus } from '@/lib/agent/flow';
import type { JobView } from '@/lib/jobs/view';
import { ENGINE_LABEL } from '@/lib/store/studio';
import { cn } from '@/lib/utils';

const STATUS_STYLE: Record<FlowStatus, string> = {
  idle: 'border-dashed bg-card text-muted-foreground',
  active: 'border-primary bg-primary/5 ring-2 ring-primary/25',
  done: 'border-emerald-200 bg-emerald-50/70',
  warn: 'border-amber-200 bg-amber-50/80',
  error: 'border-red-200 bg-red-50/80',
};

const STATUS_LABEL: Record<FlowStatus, string> = {
  idle: '未開始', active: '執行中', done: '完成', warn: '重試後通過', error: '未完成',
};

const STEP_STYLE: Record<FlowStatus, string> = {
  idle: 'bg-muted text-muted-foreground',
  active: 'bg-primary text-primary-foreground',
  done: 'bg-emerald-600 text-white',
  warn: 'bg-amber-500 text-white',
  error: 'bg-red-600 text-white',
};

const COMFY_STEP: Record<RenderNode, string> = { cutout: '去背', generate: '背景生成', relight: '打光融合', upscale: '放大' };

/** 節點說明：有任務設定時顯示實際使用的模型 */
function techOf(id: FlowNodeId, fallback: string, input: JobInput | null): string {
  if (!input) return fallback;
  if (id === 'brief') return input.llm;
  if (id === 'comfy') return ENGINE_LABEL[input.engine];
  if (id === 'review') return `規則 8 項 + ${input.vlm}`;
  return fallback;
}

/** Agent 流程節點圖：每個節點的狀態、進入次數與耗時；審查未通過時經 Query Rewriting 回到 Prompt 構建 */
export function FlowGraph({ flow, view, input }: { flow: FlowState; view: JobView; input: JobInput | null }) {
  const progress = view.progress && view.progress.round === view.round ? view.progress : null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>流程節點</CardTitle>
        <CardDescription>依 WebSocket 事件即時更新；時間為各節點的累計耗時。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
          {FLOW_NODES.map((n) => {
            const s = flow.nodes[n.id];
            return (
              <li key={n.id} className={cn('flex flex-col gap-1.5 rounded-lg border p-2.5 text-sm transition-colors', STATUS_STYLE[s.status])}>
                <div className="flex items-center gap-2">
                  <span className={cn('grid size-5 shrink-0 place-items-center rounded-full text-[11px] font-bold', STEP_STYLE[s.status])}>
                    {n.step}
                  </span>
                  <span className="font-semibold leading-tight text-foreground">{n.label}</span>
                </div>
                <p className="text-xs leading-snug text-muted-foreground">{techOf(n.id, n.tech, input)}</p>
                <div className="mt-auto flex flex-wrap items-center gap-x-2 text-xs">
                  <span className={cn('font-medium', s.status === 'idle' && 'text-muted-foreground')}>{STATUS_LABEL[s.status]}</span>
                  {s.visits > 1 && <span className="text-muted-foreground">× {s.visits}</span>}
                  {s.ms > 0 && <span className="ml-auto font-mono text-muted-foreground">{formatDuration(s.ms)}</span>}
                </div>
                {n.id === 'comfy' && s.status === 'active' && progress && (
                  <p className="font-mono text-xs text-primary">
                    {COMFY_STEP[progress.node]} {progress.step}/{progress.maxStep}
                  </p>
                )}
              </li>
            );
          })}
        </ol>
        <div
          className={cn(
            'flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-sm',
            flow.loop.active ? 'border-amber-300 bg-amber-50' : flow.loop.count ? 'border-amber-200' : 'border-dashed text-muted-foreground',
          )}
        >
          <RotateCcw className={cn('size-4', flow.loop.count > 0 && 'text-amber-600', flow.loop.active && 'animate-spin')} />
          <span className="font-medium">Query Rewriting</span>
          <span className="text-muted-foreground">
            審查未通過 → 回到 ④ Prompt 構建{flow.loop.requery ? '，並重新檢索 ③ 合規用語' : ''}
          </span>
          <span className="ml-auto text-xs">
            {flow.loop.count ? `${flow.loop.count} 次・${formatDuration(flow.loop.ms)}` : '未觸發'}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
