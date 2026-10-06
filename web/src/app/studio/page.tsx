'use client';

import { useEffect } from 'react';
import { WandSparkles } from 'lucide-react';
import { EmptyState } from '@/components/common/empty-state';
import { PageHeader } from '@/components/common/page-header';
import { BriefPanel } from '@/components/studio/brief-panel';
import { useCurrentBrand } from '@/lib/store/app';
import { useProductsStore } from '@/lib/store/products';
import { useStudioStore } from '@/lib/store/studio';

function Results() {
  const view = useStudioStore((s) => s.view);
  if (!view) {
    return (
      <EmptyState icon={WandSparkles} title="輸入一句話需求，開始生成">
        Agent 會拆解需求、檢索品牌規範、產生 Prompt 與版面，生成後自動做合規審查；未通過會改寫後重試。
      </EmptyState>
    );
  }
  // 進度與結果牆在 Task 11 加入
  return <p className="text-sm text-muted-foreground">任務 {view.jobId} 已送出。</p>;
}

export default function StudioPage() {
  const brand = useCurrentBrand();
  const loadProducts = useProductsStore((s) => s.load);
  const products = useProductsStore((s) => s.products);
  const studioBrandId = useStudioStore((s) => s.brandId);
  const productId = useStudioStore((s) => s.productId);
  const resetForBrand = useStudioStore((s) => s.resetForBrand);
  const setForm = useStudioStore((s) => s.setForm);

  useEffect(() => {
    void loadProducts(brand.id);
  }, [brand.id, loadProducts]);

  useEffect(() => {
    if (studioBrandId !== brand.id) resetForBrand(brand.id);
  }, [brand.id, studioBrandId, resetForBrand]);

  // 預設選第一個商品
  useEffect(() => {
    const own = products.filter((p) => p.brandId === brand.id);
    if (own.length && !own.some((p) => p.id === productId)) setForm({ productId: own[0].id });
  }, [products, productId, brand.id, setForm]);

  return (
    <>
      <PageHeader title="新任務" description="一句話需求 → Agent 拆解 → 多通路生成 → 合規審查與自動重試 → 挑圖改字 → 匯出" />
      <div className="grid items-start gap-5 lg:grid-cols-[380px_minmax(0,1fr)]">
        <BriefPanel brand={brand} />
        <div className="min-w-0 space-y-5">
          <Results />
        </div>
      </div>
    </>
  );
}
