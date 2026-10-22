'use client';

import { useState } from 'react';
import Link from 'next/link';
import { FileDown, ListOrdered, LoaderCircle, Network, Pause, Play, X } from 'lucide-react';
import { toast } from 'sonner';
import { EmptyState } from '@/components/common/empty-state';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { getApiClient } from '@/lib/api';
import { getTemplate } from '@/lib/compose/templates';
import { exportPosterZip } from '@/lib/export/posters';
import { defaultSelection, jobProgress, STAGE_LABEL, type Candidate } from '@/lib/jobs/view';
import { useAppStore } from '@/lib/store/app';
import { isFinished, useQueueStore, type QueueItem, type QueueStatus } from '@/lib/store/queue';
import { cn } from '@/lib/utils';

const STATUS: Record<QueueStatus, { label: string; className: string }> = {
  pending: { label: '等待中', className: 'bg-muted text-muted-foreground' },
  held: { label: '已暫停', className: 'bg-amber-50 text-amber-800' },
  running: { label: '執行中', className: 'bg-secondary text-primary' },
  done: { label: '完成', className: 'bg-emerald-50 text-emerald-700' },
  needs_review: { label: '需人工審核', className: 'bg-amber-50 text-amber-800' },
  cancelled: { label: '已取消', className: 'bg-muted text-muted-foreground' },
  error: { label: '失敗', className: 'bg-red-50 text-red-700' },
};

function QueueRow({ item }: { item: QueueItem }) {
  const { hold, release, cancel } = useQueueStore();
  const brand = useAppStore((s) => s.brands.find((b) => b.id === item.brandId));
  const [exporting, setExporting] = useState(false);
  const view = item.view;
  const progress = item.status === 'running' && view ? jobProgress(view) : isFinished(item.status) && item.status !== 'error' && item.status !== 'cancelled' ? 1 : 0;

  // 匯出每個模板的最佳候選（沿用 AI 文案），並寫入歷史紀錄
  const exportBest = async () => {
    if (!view?.jobId || !brand) return;
    setExporting(true);
    try {
      const api = getApiClient();
      const product = (await api.listProducts(item.brandId)).find((p) => p.id === item.productId) ?? null;
      const renders = Object.values(defaultSelection(view)).map((id) => view.renders[id!]).filter((r): r is Candidate => !!r);
      await exportPosterZip(brand, product, renders.map((render) => ({ render, copy: render.spec.copy })));
      for (const r of renders) await api.selectRender(view.jobId, r.id, r.spec.copy);
      toast.success(`已匯出「${item.productName}」${renders.length} 張海報`, { description: '已寫入歷史紀錄並標記已回寫 RAG。' });
    } catch (err) {
      toast.error('匯出失敗', { description: err instanceof Error ? err.message : String(err) });
    } finally {
      setExporting(false);
    }
  };

  return (
    <li className="space-y-2 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{item.productName}</span>
        <span className={cn('rounded-full px-2 py-0.5 text-xs font-medium', STATUS[item.status].className)}>{STATUS[item.status].label}</span>
        {item.status === 'running' && view?.stage && (
          <span className="text-xs text-muted-foreground">
            {STAGE_LABEL[view.stage]}
            {view.round > 0 && `・第 ${view.round} 輪`}
          </span>
        )}
        <div className="ml-auto flex gap-1">
          {item.status === 'pending' && <Button size="xs" variant="ghost" onClick={() => hold(item.id)}><Pause />暫停此筆</Button>}
          {item.status === 'held' && <Button size="xs" variant="ghost" onClick={() => release(item.id)}><Play />繼續</Button>}
          {(item.status === 'pending' || item.status === 'held' || item.status === 'running') && (
            <Button size="xs" variant="ghost" className="text-muted-foreground hover:text-destructive" onClick={() => void cancel(item.id)}>
              <X />
              取消
            </Button>
          )}
          {item.jobId && (
            <Button size="xs" variant="ghost" asChild>
              <Link href={`/agent?job=${encodeURIComponent(item.jobId)}`}><Network />透視</Link>
            </Button>
          )}
          {(item.status === 'done' || item.status === 'needs_review') && (
            <Button size="xs" variant="outline" disabled={exporting} onClick={() => void exportBest()}>
              {exporting ? <LoaderCircle className="animate-spin" /> : <FileDown />}
              匯出最佳
            </Button>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-1">
        {item.templateIds.map((t) => <Badge key={t} variant="outline">{getTemplate(t).label}</Badge>)}
        <span className="text-xs text-muted-foreground">× {item.variants} 張</span>
      </div>
      <Progress value={progress * 100} className="h-1.5" />
      {item.error && <p className="text-xs text-destructive">{item.error}</p>}
    </li>
  );
}

export function QueueList() {
  const { items, paused, togglePause, clearFinished } = useQueueStore();
  const done = items.filter((i) => isFinished(i.status)).length;
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center gap-2">
        <CardTitle>佇列</CardTitle>
        <span className="text-sm text-muted-foreground">{done}／{items.length} 筆已結束</span>
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant="outline" disabled={!items.length} onClick={togglePause}>
            {paused ? <Play /> : <Pause />}
            {paused ? '繼續佇列' : '暫停佇列'}
          </Button>
          <Button size="sm" variant="ghost" disabled={!done} onClick={clearFinished}>清除已結束</Button>
        </div>
      </CardHeader>
      <CardContent className="px-0">
        {paused && <p className="mx-4 mb-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">佇列已暫停：執行中的這筆會跑完，之後不會再啟動新的任務。</p>}
        {items.length ? (
          <ul className="divide-y border-t">{items.map((i) => <QueueRow key={i.id} item={i} />)}</ul>
        ) : (
          <div className="px-4">
            <EmptyState icon={ListOrdered} title="佇列是空的">選擇商品與模板後加入佇列，任務會一筆一筆執行。</EmptyState>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
