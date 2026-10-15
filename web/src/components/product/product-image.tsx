import Image from 'next/image';
import type { Brand, Product } from '@/types/contract';
import { productImage } from '@/lib/compose/assets';
import { cn } from '@/lib/utils';

/** 去背預覽的底：透明格紋、品牌輔助色（淺）、品牌文字色（深）；邊緣的殘留在深色上最明顯 */
export type PreviewBackground = 'checker' | 'light' | 'dark';

/**
 * 商品縮圖。preview 時以指定的底色呈現去背結果；還沒有去背圖的照片用色彩增值讓白底「消失」（示意）。
 * 圖片都是 data URL 或本機 API，所以用 unoptimized。
 */
export function ProductImage({
  product, brand, preview, className,
}: { product: Product; brand: Brand; preview?: PreviewBackground; className?: string }) {
  const { src, blend } = productImage(product, brand);
  const background = preview === 'light' ? brand.palette.secondary : preview === 'dark' ? brand.palette.ink : undefined;
  return (
    <div
      className={cn('relative overflow-hidden', preview === 'checker' ? 'bg-checker' : !preview && 'bg-muted', className)}
      style={background ? { backgroundColor: background } : undefined}
    >
      <Image
        src={src}
        alt={product.name}
        fill
        unoptimized
        sizes="320px"
        className={cn('object-contain p-1', preview && blend === 'multiply' && 'mix-blend-multiply')}
      />
    </div>
  );
}
