import { ChartColumn } from 'lucide-react';
import { EmptyState } from '@/components/common/empty-state';
import { PageHeader } from '@/components/common/page-header';

export default function DashboardPage() {
  return (
    <>
      <PageHeader title="成效儀表板" description="通過率、平均重試次數、平均耗時、每張成本與各檢查項失敗分布。" />
      <EmptyState icon={ChartColumn} title="Plan 3 實作">儀表板會依歷史任務的事件統計，並比較有無 Rerank 的命中率。</EmptyState>
    </>
  );
}
