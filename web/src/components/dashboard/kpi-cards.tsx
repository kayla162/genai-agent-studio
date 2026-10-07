import { CircleCheck, CircleDollarSign, RotateCcw, Timer } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { DashboardStats } from '@/types/contract';
import { Card, CardContent } from '@/components/ui/card';
import { formatDuration } from '@/lib/agent/events';

const pct = (v: number) => `${Math.round(v * 100)}%`;

function Kpi({ icon: Icon, label, value, note }: { icon: LucideIcon; label: string; value: string; note: string }) {
  return (
    <Card>
      <CardContent className="space-y-1">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Icon className="size-4" />
          {label}
        </div>
        <p className="text-2xl font-bold tracking-tight">{value}</p>
        <p className="text-xs text-muted-foreground">{note}</p>
      </CardContent>
    </Card>
  );
}

/** 通過率、平均重試次數、平均耗時、每張成本 */
export function KpiCards({ stats }: { stats: DashboardStats }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Kpi icon={CircleCheck} label="通過率" value={pct(stats.passRate)} note={`首輪就通過的模板 ${pct(stats.firstPassRate)}・共 ${stats.jobs} 個任務`} />
      <Kpi icon={RotateCcw} label="平均重試次數" value={`${stats.avgRetries.toFixed(1)} 輪`} note="審查未通過後 Query Rewriting 的輪數" />
      <Kpi icon={Timer} label="平均耗時" value={formatDuration(stats.avgDurationMs)} note={`從接收任務到回傳・共 ${stats.renders} 張候選`} />
      <Kpi
        icon={CircleDollarSign}
        label="每張成本"
        value={stats.costPerImage === null ? '—' : `US$ ${stats.costPerImage.toFixed(3)}`}
        note="估算：LLM、Rerank、生圖與 VLM 審查，攤到每張交付圖"
      />
    </div>
  );
}
