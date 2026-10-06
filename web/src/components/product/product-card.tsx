'use client';

import { LoaderCircle, Pencil, Scissors, Trash } from 'lucide-react';
import type { Brand, Product } from '@/types/contract';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { formatPrice } from '@/lib/compose/scene';
import { useProductsStore } from '@/lib/store/products';
import { ProductImage } from './product-image';

const SOURCE_LABEL = { sample: '示範素材', upload: '上傳', local: '本機資料夾' } as const;

export function ProductCard({ product, brand, onEdit, onCutout, onDelete }: {
  product: Product;
  brand: Brand;
  onEdit: () => void;
  onCutout: () => void;
  onDelete: () => void;
}) {
  const cutting = useProductsStore((s) => s.cutting.includes(product.id));
  const isPhoto = product.photo.source !== 'sample';
  return (
    <div className="flex flex-col overflow-hidden rounded-xl border bg-card">
      <ProductImage product={product} brand={brand} className="aspect-[4/5]" />
      <div className="flex flex-1 flex-col gap-2 p-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="secondary">{SOURCE_LABEL[product.photo.source]}</Badge>
          {product.cutout && <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-emerald-700">已去背（示意）</Badge>}
          {product.price.sale === 0 && <Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-800">請補上價格</Badge>}
        </div>
        <p className="leading-snug font-semibold">{product.name}</p>
        <p className="text-sm">
          <span className="font-semibold text-primary">NT${formatPrice(product.price.sale)}</span>
          {product.price.original > product.price.sale && (
            <span className="ml-2 text-xs text-muted-foreground line-through">NT${formatPrice(product.price.original)}</span>
          )}
        </p>
        <div className="flex flex-wrap gap-1">
          {product.features.map((f) => (
            <span key={f} className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">{f}</span>
          ))}
        </div>
        <div className="mt-auto flex gap-1 pt-2">
          <Button size="sm" variant="outline" onClick={onEdit}>
            <Pencil />
            編輯
          </Button>
          {isPhoto && (
            <Button size="sm" variant="outline" disabled={cutting} onClick={onCutout}>
              {cutting ? <LoaderCircle className="animate-spin" /> : <Scissors />}
              {cutting ? '去背中…' : '去背預覽'}
            </Button>
          )}
          <Button size="icon-sm" variant="ghost" className="ml-auto text-muted-foreground hover:text-destructive" aria-label={`刪除 ${product.name}`} onClick={onDelete}>
            <Trash />
          </Button>
        </div>
      </div>
    </div>
  );
}
