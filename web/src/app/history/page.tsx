'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Clock } from 'lucide-react';
import { toast } from 'sonner';
import type { HistoryEntry, Product, TemplateId } from '@/types/contract';
import { EmptyState } from '@/components/common/empty-state';
import { PageHeader } from '@/components/common/page-header';
import { HistoryCard } from '@/components/history/history-card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { getApiClient } from '@/lib/api';
import { CHANNEL_TEMPLATES } from '@/lib/compose/templates';
import { exportPosterPng } from '@/lib/export/posters';
import { filterHistory, type HistoryFilters } from '@/lib/history/filter';
import { useAppStore } from '@/lib/store/app';
import { useStudioStore } from '@/lib/store/studio';

export default function HistoryPage() {
  const router = useRouter();
  const brands = useAppStore((s) => s.brands);
  const currentBrandId = useAppStore((s) => s.brandId);
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [filters, setFilters] = useState<HistoryFilters>({ brandId: currentBrandId, templateId: 'all', from: null, to: null, favoritesOnly: false });

  useEffect(() => {
    const api = getApiClient();
    void api.listHistory().then(setEntries);
    // 縮圖需要商品照：讀取所有品牌的商品
    void Promise.all(brands.map((b) => api.listProducts(b.id))).then((lists) => setProducts(lists.flat()));
  }, [brands]);

  const patch = (p: Partial<HistoryFilters>) => setFilters({ ...filters, ...p });
  const visible = entries ? filterHistory(entries, filters) : [];

  const toggleFavorite = async (entry: HistoryEntry) => {
    const updated = await getApiClient().setFavorite(entry.id, !entry.favorite);
    setEntries((list) => list?.map((e) => (e.id === updated.id ? updated : e)) ?? null);
  };

  const redo = (entry: HistoryEntry) => {
    useAppStore.getState().setBrandId(entry.brandId);
    useStudioStore.getState().prefill(entry.input);
    router.push('/studio');
    toast.info('已帶入當時的需求與設定', { description: '確認後按「開始生成」。' });
  };

  return (
    <>
      <PageHeader title="歷史紀錄" description="選定並匯出的海報。每一張都已回寫 RAG，成為之後檢索的歷史優秀案例。" />
      <div className="mb-5 flex flex-wrap items-end gap-3 rounded-xl border bg-card p-3">
        <div className="space-y-1.5">
          <Label htmlFor="h-brand">品牌</Label>
          <Select value={filters.brandId} onValueChange={(v) => patch({ brandId: v })}>
            <SelectTrigger id="h-brand" className="w-48"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部品牌</SelectItem>
              {brands.map((b) => <SelectItem key={b.id} value={b.id}>{b.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="h-channel">通路</Label>
          <Select value={filters.templateId} onValueChange={(v) => patch({ templateId: v as TemplateId | 'all' })}>
            <SelectTrigger id="h-channel" className="w-36"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部通路</SelectItem>
              {CHANNEL_TEMPLATES.map((t) => <SelectItem key={t.id} value={t.id}>{t.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="h-from">起日</Label>
          <Input id="h-from" type="date" className="w-40" value={filters.from ?? ''} onChange={(e) => patch({ from: e.target.value || null })} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="h-to">迄日</Label>
          <Input id="h-to" type="date" className="w-40" value={filters.to ?? ''} onChange={(e) => patch({ to: e.target.value || null })} />
        </div>
        <label className="flex h-8 items-center gap-2 text-sm">
          <Switch checked={filters.favoritesOnly} onCheckedChange={(v) => patch({ favoritesOnly: v })} />
          只看收藏
        </label>
        <span className="ml-auto text-sm text-muted-foreground">{visible.length} 張</span>
      </div>

      {entries && !visible.length ? (
        <EmptyState icon={Clock} title={entries.length ? '沒有符合條件的紀錄' : '還沒有歷史紀錄'}>
          在「新任務」選圖後按「匯出 zip 並寫入歷史」，紀錄就會出現在這裡。
        </EmptyState>
      ) : (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
          {visible.map((entry) => {
            const brand = brands.find((b) => b.id === entry.brandId);
            if (!brand) return null;
            const product = products.find((p) => p.id === entry.productId) ?? null;
            return (
              <HistoryCard
                key={entry.id}
                entry={entry}
                brand={brand}
                product={product}
                onFavorite={() => void toggleFavorite(entry)}
                onDownload={() => void exportPosterPng(brand, product, { render: entry.render, copy: entry.copy })}
                onRedo={() => redo(entry)}
              />
            );
          })}
        </div>
      )}
    </>
  );
}
