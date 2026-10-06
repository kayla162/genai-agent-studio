'use client';

import { Download, RotateCcw, Star } from 'lucide-react';
import type { Brand, HistoryEntry, Product } from '@/types/contract';
import { PosterCanvas } from '@/components/poster/poster-canvas';
import { ScoreBadge } from '@/components/poster/score-badge';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { getTemplate } from '@/lib/compose/templates';
import { cn } from '@/lib/utils';

export function HistoryCard({ entry, brand, product, onFavorite, onDownload, onRedo }: {
  entry: HistoryEntry;
  brand: Brand;
  product: Product | null;
  onFavorite: () => void;
  onDownload: () => void;
  onRedo: () => void;
}) {
  return (
    <div className="flex flex-col overflow-hidden rounded-xl border bg-card">
      <PosterCanvas render={entry.render} copy={entry.copy} product={product} brand={brand} pixelWidth={400} />
      <div className="flex flex-1 flex-col gap-2 p-3">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <p className="truncate font-semibold">{entry.copy.productName}</p>
            <p className="text-xs text-muted-foreground">
              {getTemplate(entry.templateId).label}・{new Date(entry.selectedAt).toLocaleString('zh-TW', { dateStyle: 'medium', timeStyle: 'short' })}
            </p>
          </div>
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label={entry.favorite ? '取消收藏' : '收藏'}
            aria-pressed={entry.favorite}
            onClick={onFavorite}
          >
            <Star className={cn(entry.favorite && 'fill-amber-400 text-amber-500')} />
          </Button>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <ScoreBadge render={entry.render} />
          {entry.writtenToRag && <Badge variant="outline" className="border-indigo-200 bg-indigo-50 text-indigo-700">已回寫 RAG</Badge>}
          {!product && <Badge variant="outline">商品已刪除</Badge>}
        </div>
        <div className="mt-auto flex gap-1 pt-1">
          <Button size="sm" variant="outline" onClick={onDownload}>
            <Download />
            PNG
          </Button>
          <Button size="sm" variant="ghost" onClick={onRedo}>
            <RotateCcw />
            以相同設定重做
          </Button>
        </div>
      </div>
    </div>
  );
}
