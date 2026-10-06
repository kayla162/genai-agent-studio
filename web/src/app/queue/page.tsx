'use client';

import { useEffect } from 'react';
import { PageHeader } from '@/components/common/page-header';
import { BatchForm } from '@/components/queue/batch-form';
import { QueueList } from '@/components/queue/queue-list';
import { useCurrentBrand } from '@/lib/store/app';
import { useProductsStore } from '@/lib/store/products';

export default function QueuePage() {
  const brand = useCurrentBrand();
  const load = useProductsStore((s) => s.load);
  useEffect(() => {
    void load(brand.id);
  }, [brand.id, load]);

  return (
    <>
      <PageHeader title="批次佇列" description="多商品 × 多模板排程，逐筆顯示進度；可暫停整個佇列、暫停或取消單筆。" />
      <div className="grid items-start gap-5 lg:grid-cols-[380px_minmax(0,1fr)]">
        {/* key：切換品牌時重設表單 */}
        <BatchForm key={brand.id} brand={brand} />
        <QueueList />
      </div>
    </>
  );
}
