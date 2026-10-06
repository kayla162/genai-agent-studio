'use client';

import { useEffect, useRef } from 'react';
import { paintPoster, preparePoster, type PosterInput } from '@/lib/compose/render';
import { cn } from '@/lib/utils';

/** 海報預覽：與匯出共用同一套 Canvas 繪製。文案改變時只重畫文字，不重新產圖。 */
export function PosterCanvas({
  render, copy, product, brand, pixelWidth = 480, className,
}: PosterInput & { pixelWidth?: number; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;
    preparePoster({ render, copy, product, brand })
      .then((prepared) => {
        // 較晚開始的繪製才算數，避免快速輸入時舊畫面蓋掉新畫面
        if (!cancelled && ref.current) paintPoster(ref.current, prepared, pixelWidth);
      })
      .catch((err: unknown) => console.error('[PosterCanvas]', err));
    return () => {
      cancelled = true;
    };
  }, [render, copy, product, brand, pixelWidth]);

  const { width, height } = render.spec.canvas;
  return (
    <canvas
      ref={ref}
      role="img"
      aria-label={`${copy.headline.join(' ')} 海報預覽`}
      className={cn('block h-auto w-full bg-muted', className)}
      style={{ aspectRatio: `${width} / ${height}` }}
    />
  );
}
