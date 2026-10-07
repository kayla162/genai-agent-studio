'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ChartColumn, FlaskConical, LoaderCircle } from 'lucide-react';
import type { DashboardStats } from '@/types/contract';
import { EmptyState } from '@/components/common/empty-state';
import { PageHeader } from '@/components/common/page-header';
import { CheckFailureChart } from '@/components/dashboard/check-failure-chart';
import { KpiCards } from '@/components/dashboard/kpi-cards';
import { RecentJobs } from '@/components/dashboard/recent-jobs';
import { RerankChart } from '@/components/dashboard/rerank-chart';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { API_MODE, getApiClient } from '@/lib/api';
import { useCurrentBrand } from '@/lib/store/app';

const SAMPLE_JOBS = 12;

export default function DashboardPage() {
  const brand = useCurrentBrand();
  const [scope, setScope] = useState<'brand' | 'all'>('brand');
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [seeding, setSeeding] = useState(false);
  // 產生示範任務後遞增，重新讀取統計
  const [version, setVersion] = useState(0);
  const brandId = scope === 'brand' ? brand.id : undefined;

  useEffect(() => {
    let alive = true;
    void getApiClient().getDashboardStats(brandId).then((s) => {
      if (alive) setStats(s);
    });
    return () => {
      alive = false;
    };
  }, [brandId, version]);

  const seed = async () => {
    const demo = getApiClient().demo;
    if (!demo) return;
    setSeeding(true);
    try {
      await demo.seedJobs(SAMPLE_JOBS);
      setVersion((v) => v + 1);
    } finally {
      setSeeding(false);
    }
  };

  const seedButton = API_MODE === 'mock' && (
    <Button variant="outline" disabled={seeding} onClick={() => void seed()}>
      {seeding ? <LoaderCircle className="animate-spin" /> : <FlaskConical />}
      產生 {SAMPLE_JOBS} 個示範任務
    </Button>
  );

  return (
    <>
      <PageHeader
        title="成效儀表板"
        description="依已結束任務的事件統計：通過率、平均重試次數、平均耗時、每張成本、各檢查項失敗分布，以及 Rerank 對命中率的影響。"
        actions={
          <>
            <Select value={scope} onValueChange={(v) => setScope(v as 'brand' | 'all')}>
              <SelectTrigger className="w-44 bg-card" aria-label="統計範圍">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="brand">{brand.name}</SelectItem>
                <SelectItem value="all">全部品牌</SelectItem>
              </SelectContent>
            </Select>
            {stats && stats.jobs > 0 && seedButton}
          </>
        }
      />
      {stats === null ? null : stats.jobs === 0 ? (
        <EmptyState icon={ChartColumn} title="還沒有已結束的任務">
          <p>
            到<Link href="/studio" className="mx-1 font-medium text-primary hover:underline">新任務</Link>或
            <Link href="/queue" className="mx-1 font-medium text-primary hover:underline">批次佇列</Link>
            執行幾個任務，或先產生示範任務（直接寫入任務紀錄，不播放）。
          </p>
          <div className="mt-4">{seedButton}</div>
        </EmptyState>
      ) : (
        <div className="space-y-5">
          <KpiCards stats={stats} />
          <div className="grid gap-5 xl:grid-cols-2">
            <CheckFailureChart data={stats.checkFailures} />
            <RerankChart data={stats.rerankHits} />
          </div>
          <RecentJobs jobs={stats.recent} />
        </div>
      )}
    </>
  );
}
