'use client';

import { useState } from 'react';
import { ListOrdered } from 'lucide-react';
import type { Brand, TemplateId } from '@/types/contract';
import { ProductImage } from '@/components/product/product-image';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { CHANNEL_TEMPLATES } from '@/lib/compose/templates';
import { useProductsStore } from '@/lib/store/products';
import { useQueueStore } from '@/lib/store/queue';
import { DEMO_BRIEFS } from '@/lib/store/studio';

const toggle = <T,>(list: T[], x: T) => (list.includes(x) ? list.filter((y) => y !== x) : [...list, x]);

/** 新增批次：同一句需求 × 多個商品 × 多個模板，每個商品排成一筆任務 */
export function BatchForm({ brand }: { brand: Brand }) {
  const products = useProductsStore((s) => s.products);
  const enqueue = useQueueStore((s) => s.enqueue);
  const [brief, setBrief] = useState(DEMO_BRIEFS[brand.id] ?? '');
  const [productIds, setProductIds] = useState<string[]>([]);
  const [templateIds, setTemplateIds] = useState<TemplateId[]>(['ecom-main', 'ig-post', 'story']);
  const [variants, setVariants] = useState(2);
  const chosen = products.filter((p) => productIds.includes(p.id));
  const ready = brief.trim() !== '' && chosen.length > 0 && templateIds.length > 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>新增批次</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="batch-brief">一句話需求（所有商品共用）</Label>
          <Textarea id="batch-brief" rows={2} value={brief} onChange={(e) => setBrief(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label>商品（{chosen.length}／{products.length}）</Label>
          <div className="grid max-h-64 gap-1.5 overflow-auto">
            {products.map((p) => (
              <label key={p.id} className="flex cursor-pointer items-center gap-2.5 rounded-lg border px-2 py-1.5 text-sm">
                <Checkbox aria-label={p.name} checked={productIds.includes(p.id)} onCheckedChange={() => setProductIds(toggle(productIds, p.id))} />
                <ProductImage product={p} brand={brand} className="size-8 rounded" />
                <span className="truncate">{p.name}</span>
              </label>
            ))}
          </div>
        </div>
        <div className="space-y-1.5">
          <Label>通路模板</Label>
          <div className="flex flex-wrap gap-1.5">
            {CHANNEL_TEMPLATES.map((t) => (
              <label key={t.id} className="flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs">
                <Checkbox aria-label={t.label} checked={templateIds.includes(t.id)} onCheckedChange={() => setTemplateIds(toggle(templateIds, t.id))} />
                {t.label}
              </label>
            ))}
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="batch-variants">每個模板候選張數</Label>
          <Select value={String(variants)} onValueChange={(v) => setVariants(Number(v))}>
            <SelectTrigger id="batch-variants" className="w-32"><SelectValue /></SelectTrigger>
            <SelectContent>
              {[1, 2, 3, 4].map((n) => <SelectItem key={n} value={String(n)}>{n} 張</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </CardContent>
      <CardFooter>
        <Button
          className="w-full"
          disabled={!ready}
          onClick={() => {
            enqueue({ brandId: brand.id, brief, products: chosen.map((p) => ({ id: p.id, name: p.name })), templateIds, variants });
            setProductIds([]);
          }}
        >
          <ListOrdered />
          加入佇列（{chosen.length} 筆任務 × {templateIds.length} 個模板）
        </Button>
      </CardFooter>
    </Card>
  );
}
