'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import type { Product } from '@/types/contract';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useProductsStore } from '@/lib/store/products';

const splitList = (s: string) => s.split(/[,，、]/).map((x) => x.trim()).filter(Boolean);

function EditForm({ product, onDone }: { product: Product; onDone: () => void }) {
  const save = useProductsStore((s) => s.save);
  const [name, setName] = useState(product.name);
  const [features, setFeatures] = useState(product.features.join('、'));
  const [sale, setSale] = useState(String(product.price.sale));
  const [original, setOriginal] = useState(String(product.price.original));
  const [saving, setSaving] = useState(false);
  const saleN = Number(sale);
  const originalN = Number(original);
  const error = !name.trim()
    ? '請輸入商品名稱'
    : !Number.isFinite(saleN) || saleN < 0 || !Number.isFinite(originalN) || originalN < 0
      ? '價格需為 0 以上的數字'
      : null;

  const submit = async () => {
    if (error) return;
    setSaving(true);
    try {
      await save({
        ...product, name: name.trim(), features: splitList(features).slice(0, 6),
        price: { sale: Math.round(saleN), original: Math.round(originalN) },
      });
      toast.success('已儲存商品');
      onDone();
    } catch (err) {
      toast.error('儲存失敗', { description: err instanceof Error ? err.message : String(err) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="p-name">商品名稱</Label>
          <Input id="p-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="p-features">特徵／賣點（以頓號分隔，最多 6 個）</Label>
          <Input id="p-features" value={features} onChange={(e) => setFeatures(e.target.value)} placeholder="例如：5重玻尿酸、無香精" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="p-sale">特價（NT$）</Label>
            <Input id="p-sale" type="number" min={0} value={sale} onChange={(e) => setSale(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="p-original">原價（NT$）</Label>
            <Input id="p-original" type="number" min={0} value={original} onChange={(e) => setOriginal(e.target.value)} />
          </div>
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onDone}>取消</Button>
        <Button disabled={!!error || saving} onClick={() => void submit()}>儲存</Button>
      </DialogFooter>
    </>
  );
}

export function ProductEditDialog({ product, onClose }: { product: Product | null; onClose: () => void }) {
  return (
    <Dialog open={product !== null} onOpenChange={(o) => !o && onClose()}>
      {product && (
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>編輯商品</DialogTitle>
            <DialogDescription>名稱、特徵與價格會帶入新任務的需求拆解與海報文案。</DialogDescription>
          </DialogHeader>
          {/* key：換商品時重設表單 */}
          <EditForm key={product.id} product={product} onDone={onClose} />
        </DialogContent>
      )}
    </Dialog>
  );
}
