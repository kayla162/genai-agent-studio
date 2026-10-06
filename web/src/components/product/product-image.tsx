import Image from 'next/image';
import type { Brand, Product } from '@/types/contract';
import { productImage } from '@/lib/compose/assets';
import { cn } from '@/lib/utils';

/**
 * 商品縮圖。cutoutPreview 時以透明格紋當底；尚未真正去背的照片用色彩增值讓白底「消失」（示意）。
 * 圖片都是 data URL 或本機 API，所以用 unoptimized。
 */
export function ProductImage({
  product, brand, cutoutPreview = false, className,
}: { product: Product; brand: Brand; cutoutPreview?: boolean; className?: string }) {
  const { src, blend } = productImage(product, brand);
  return (
    <div className={cn('relative overflow-hidden', cutoutPreview ? 'bg-checker' : 'bg-muted', className)}>
      <Image
        src={src}
        alt={product.name}
        fill
        unoptimized
        sizes="320px"
        className={cn('object-contain p-1', cutoutPreview && blend === 'multiply' && 'mix-blend-multiply')}
      />
    </div>
  );
}
