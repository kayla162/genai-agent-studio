'use client';

import { PageHeader } from '@/components/common/page-header';
import { BrandOverview } from '@/components/brands/brand-overview';
import { CaseStudies } from '@/components/brands/case-studies';
import { ChunkList } from '@/components/brands/chunk-list';
import { DocIngest } from '@/components/brands/doc-ingest';
import { useCurrentBrand } from '@/lib/store/app';

export default function BrandsPage() {
  const brand = useCurrentBrand();
  return (
    <>
      <PageHeader title="品牌知識庫" description="品牌 CI、禁用詞、CI 手冊切塊與歷史案例；這些內容是 RAG 檢索與合規審查的依據。" />
      <div className="space-y-5">
        <BrandOverview brand={brand} />
        <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
          <ChunkList chunks={brand.guidelineChunks} />
          {/* key：切換品牌時清掉上一個品牌的上傳進度 */}
          <DocIngest key={brand.id} brand={brand} />
        </div>
        <CaseStudies brand={brand} />
      </div>
    </>
  );
}
