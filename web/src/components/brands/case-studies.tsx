'use client';

import { useEffect, useState } from 'react';
import type { Brand, HistoryEntry, Product } from '@/types/contract';
import { PosterCanvas } from '@/components/poster/poster-canvas';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { getApiClient } from '@/lib/api';
import { getTemplate } from '@/lib/compose/templates';

/** 歷史優秀案例：品牌資料內建的案例 + 使用者挑中並回寫 RAG 的圖 */
export function CaseStudies({ brand }: { brand: Brand }) {
  const [picked, setPicked] = useState<HistoryEntry[]>([]);
  const [products, setProducts] = useState<Product[]>([]);

  useEffect(() => {
    const api = getApiClient();
    void api.listHistory(brand.id).then((h) => setPicked(h.filter((e) => e.writtenToRag).slice(0, 8)));
    void api.listProducts(brand.id).then(setProducts);
  }, [brand.id]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>歷史優秀案例</CardTitle>
        <CardDescription>RAG 會檢索這些案例的風格與成效；使用者在新任務選定的圖也會回寫到這裡。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ul className="grid gap-2 sm:grid-cols-2">
          {brand.caseStudies.map((c) => (
            <li key={c.id} className="rounded-lg border p-3 text-sm">
              <div className="flex items-center gap-2">
                <span className="font-semibold">{c.title}</span>
                <span className="ml-auto rounded-full bg-secondary px-2 py-0.5 text-xs font-semibold text-primary">CTR {c.ctr}%</span>
              </div>
              <p className="text-xs text-muted-foreground">{c.channel}・{c.notes}</p>
            </li>
          ))}
        </ul>
        <div className="space-y-2">
          <p className="text-sm font-medium">使用者挑中的圖（{picked.length}）</p>
          {picked.length ? (
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-8">
              {picked.map((e) => (
                <figure key={e.id} className="space-y-1">
                  <div className="overflow-hidden rounded-md border">
                    <PosterCanvas render={e.render} copy={e.copy} product={products.find((p) => p.id === e.productId) ?? null} brand={brand} pixelWidth={200} />
                  </div>
                  <figcaption className="truncate text-[11px] text-muted-foreground">{getTemplate(e.templateId).label}</figcaption>
                </figure>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">還沒有。在新任務選圖並匯出後會出現在這裡。</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
