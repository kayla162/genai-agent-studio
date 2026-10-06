'use client';

import { useEffect, useState } from 'react';
import { Package } from 'lucide-react';
import { toast } from 'sonner';
import type { Product } from '@/types/contract';
import { EmptyState } from '@/components/common/empty-state';
import { PageHeader } from '@/components/common/page-header';
import { CutoutDialog } from '@/components/product/cutout-dialog';
import { LocalFolder } from '@/components/product/local-folder';
import { ProductCard } from '@/components/product/product-card';
import { ProductEditDialog } from '@/components/product/product-edit-dialog';
import { UploadZone } from '@/components/product/upload-zone';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { useCurrentBrand } from '@/lib/store/app';
import { useProductsStore } from '@/lib/store/products';

export default function ProductsPage() {
  const brand = useCurrentBrand();
  const { products, loading, load, remove, cutout } = useProductsStore();
  const [editing, setEditing] = useState<Product | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Product | null>(null);
  const preview = products.find((p) => p.id === previewId) ?? null;

  useEffect(() => {
    void load(brand.id);
  }, [brand.id, load]);

  const startCutout = async (p: Product) => {
    if (p.cutout) {
      setPreviewId(p.id);
      return;
    }
    try {
      await cutout(p.id);
      setPreviewId(p.id);
    } catch (err) {
      toast.error('去背失敗', { description: err instanceof Error ? err.message : String(err) });
    }
  };

  return (
    <>
      <PageHeader title="商品庫" description={`${brand.name} 的商品。海報會保留真實商品照，AI 只生成背景與情境。`} />
      <div className="space-y-5">
        <UploadZone brand={brand} />
        {products.length ? (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
            {products.map((p) => (
              <ProductCard
                key={p.id}
                product={p}
                brand={brand}
                onEdit={() => setEditing(p)}
                onCutout={() => void startCutout(p)}
                onDelete={() => setDeleting(p)}
              />
            ))}
          </div>
        ) : (
          !loading && <EmptyState icon={Package} title="還沒有商品">上傳商品照，或從本機資料夾匯入。</EmptyState>
        )}
        <LocalFolder brand={brand} />
      </div>

      <ProductEditDialog product={editing} onClose={() => setEditing(null)} />
      <CutoutDialog product={preview} brand={brand} onClose={() => setPreviewId(null)} />
      <Dialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)}>
        {deleting && (
          <DialogContent className="sm:max-w-sm">
            <DialogHeader>
              <DialogTitle>刪除「{deleting.name}」？</DialogTitle>
              <DialogDescription>商品會從商品庫移除；已存在的歷史紀錄不受影響。</DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeleting(null)}>取消</Button>
              <Button
                variant="destructive"
                onClick={() => {
                  void remove(deleting.id);
                  setDeleting(null);
                }}
              >
                刪除
              </Button>
            </DialogFooter>
          </DialogContent>
        )}
      </Dialog>
    </>
  );
}
