'use client';

import { useState } from 'react';
import { LoaderCircle, RotateCcw } from 'lucide-react';
import type { Brand, Product } from '@/types/contract';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { ProductImage, type PreviewBackground } from './product-image';

const BACKGROUNDS: { id: PreviewBackground; label: string }[] = [
  { id: 'checker', label: '透明' },
  { id: 'light', label: '淺色' },
  { id: 'dark', label: '深色' },
];

/** 去背預覽：左邊原圖、右邊去背結果（可換底色檢查邊緣），可重新去背 */
export function CutoutDialog({ product, brand, onRecut, onClose }: {
  product: Product | null;
  brand: Brand;
  onRecut: (product: Product) => void;
  onClose: () => void;
}) {
  const [background, setBackground] = useState<PreviewBackground>('checker');
  const cut = product?.cutout;
  return (
    <Dialog open={product !== null} onOpenChange={(o) => !o && onClose()}>
      {product && (
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>去背預覽：{product.name}</DialogTitle>
            <DialogDescription>
              {cut?.status === 'done' && !cut.url
                ? '示意：mock 模式不執行模型，合成時以「色彩增值」讓白底融入背景。'
                : `模型 ${cut?.model ?? 'birefnet-general'}。切換底色可以檢查邊緣是否乾淨，深色最容易看出殘邊。`}
            </DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-4">
            <figure className="space-y-2">
              <ProductImage product={{ ...product, cutout: null }} brand={brand} className="aspect-[4/5] rounded-lg border" />
              <figcaption className="text-center text-xs text-muted-foreground">原圖</figcaption>
            </figure>
            <figure className="space-y-2">
              <div className="relative">
                <ProductImage product={product} brand={brand} preview={background} className="aspect-[4/5] rounded-lg border" />
                {cut?.status === 'pending' && (
                  <div className="absolute inset-0 grid place-items-center rounded-lg bg-background/70 text-sm text-muted-foreground">
                    <span className="flex items-center gap-2"><LoaderCircle className="size-4 animate-spin" />去背中…</span>
                  </div>
                )}
                {cut?.status === 'failed' && (
                  <div className="absolute inset-0 grid place-items-center rounded-lg bg-background/80 p-4 text-center text-sm text-destructive">
                    去背失敗：{cut.error}
                  </div>
                )}
              </div>
              <figcaption className="flex justify-center">
                <ToggleGroup
                  type="single"
                  variant="outline"
                  size="sm"
                  value={background}
                  onValueChange={(v) => v && setBackground(v as PreviewBackground)}
                  aria-label="預覽底色"
                >
                  {BACKGROUNDS.map((b) => (
                    <ToggleGroupItem key={b.id} value={b.id} className="px-3">{b.label}</ToggleGroupItem>
                  ))}
                </ToggleGroup>
              </figcaption>
            </figure>
          </div>
          <DialogFooter>
            <Button variant="outline" disabled={cut?.status === 'pending'} onClick={() => onRecut(product)}>
              <RotateCcw />
              重新去背
            </Button>
          </DialogFooter>
        </DialogContent>
      )}
    </Dialog>
  );
}
