'use client';

import type { Brand, Product } from '@/types/contract';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { ProductImage } from './product-image';

/** 去背預覽：左邊原圖、右邊透明格紋上的去背結果（mock 以色彩增值示意） */
export function CutoutDialog({ product, brand, onClose }: { product: Product | null; brand: Brand; onClose: () => void }) {
  return (
    <Dialog open={product !== null} onOpenChange={(o) => !o && onClose()}>
      {product && (
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>去背預覽：{product.name}</DialogTitle>
            <DialogDescription>
              模型 {product.cutout?.model ?? 'BiRefNet-general'}。第一階段為示意：白底以「色彩增值」融入背景；第二階段由 ComfyUI 的 BiRefNet 產生透明 PNG。
            </DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-4">
            <figure className="space-y-2">
              <ProductImage product={{ ...product, cutout: null }} brand={brand} className="aspect-[4/5] rounded-lg border" />
              <figcaption className="text-center text-xs text-muted-foreground">原圖</figcaption>
            </figure>
            <figure className="space-y-2">
              <ProductImage product={product} brand={brand} cutoutPreview className="aspect-[4/5] rounded-lg border" />
              <figcaption className="text-center text-xs text-muted-foreground">去背（示意）</figcaption>
            </figure>
          </div>
        </DialogContent>
      )}
    </Dialog>
  );
}
