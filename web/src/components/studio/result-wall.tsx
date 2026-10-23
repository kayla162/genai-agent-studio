'use client';

import { useState } from 'react';
import type { Brand, Product, Render, TemplateId } from '@/types/contract';
import { CheckList } from '@/components/poster/check-list';
import { PosterCanvas } from '@/components/poster/poster-canvas';
import { ScoreBadge } from '@/components/poster/score-badge';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { renderSeed } from '@/lib/agent/prompt';
import { getTemplate } from '@/lib/compose/templates';
import { finalCandidates } from '@/lib/jobs/view';
import { useStudioStore } from '@/lib/store/studio';
import { cn } from '@/lib/utils';

interface CardProps {
  render: Render;
  brand: Brand;
  product: Product | null;
  best: boolean;
  selected: boolean;
  selectable: boolean;
  onOpen: () => void;
  onSelect: () => void;
}

function RenderCard({ render, brand, product, best, selected, selectable, onOpen, onSelect }: CardProps) {
  return (
    <div className={cn('overflow-hidden rounded-xl border bg-card transition-shadow hover:shadow-md', selected && 'ring-2 ring-primary')}>
      <button type="button" className="block w-full cursor-zoom-in" onClick={onOpen} aria-label={`檢視候選 ${render.variant + 1} 的審查細節`}>
        <PosterCanvas render={render} copy={render.spec.copy} product={product} brand={brand} pixelWidth={360} />
      </button>
      <div className="flex items-center gap-1.5 p-2">
        <ScoreBadge render={render} />
        {best && <Badge>推薦</Badge>}
        <span className="text-xs text-muted-foreground">#{render.variant + 1}</span>
        <Button size="xs" variant={selected ? 'default' : 'outline'} className="ml-auto" disabled={!selectable} onClick={onSelect}>
          {selected ? '已選用' : '選用'}
        </Button>
      </div>
    </div>
  );
}

/** 結果牆：依模板分組，只顯示每個模板最後一輪的候選 */
export function ResultWall({ brand, product }: { brand: Brand; product: Product | null }) {
  const view = useStudioStore((s) => s.view);
  const input = useStudioStore((s) => s.input);
  const selection = useStudioStore((s) => s.selection);
  const select = useStudioStore((s) => s.select);
  const [openId, setOpenId] = useState<string | null>(null);
  if (!view || !input) return null;

  const candidates = finalCandidates(view);
  const selectable = view.outcome === 'done' || view.outcome === 'needs_review';
  const open = openId ? view.renders[openId] : null;

  return (
    <div className="space-y-6">
      {input.templateIds.map((templateId: TemplateId) => {
        const t = getTemplate(templateId);
        const list = candidates[templateId] ?? [];
        const wide = t.width / t.height >= 1.3;
        const retried = view.rewrites.some((r) => r.templateId === templateId);
        return (
          <section key={templateId} className="space-y-3">
            <div className="flex items-center gap-2">
              <h3 className="font-semibold">{t.label}</h3>
              <span className="font-mono text-xs text-muted-foreground">{t.ratio} · {t.width}×{t.height}</span>
              {retried && <Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-800">已重試</Badge>}
              {list[0] && <span className="text-xs text-muted-foreground">第 {list[0].round} 輪</span>}
            </div>
            <div className={cn('grid gap-3', wide ? 'grid-cols-1 sm:grid-cols-2' : 'grid-cols-2 xl:grid-cols-4')}>
              {list.length
                ? list.map((r) => (
                  <RenderCard
                    key={r.id}
                    render={r}
                    brand={brand}
                    product={product}
                    best={view.bestRenderIds[templateId] === r.id}
                    selected={selection[templateId] === r.id}
                    selectable={selectable}
                    onOpen={() => setOpenId(r.id)}
                    onSelect={() => select(templateId, r.id)}
                  />
                ))
                : Array.from({ length: input.variantsPerTemplate }, (_, i) => (
                  <div key={i} className="grid animate-pulse place-items-center rounded-xl border bg-muted text-xs text-muted-foreground" style={{ aspectRatio: `${t.width} / ${t.height}` }}>
                    生成中…
                  </div>
                ))}
            </div>
          </section>
        );
      })}

      <Dialog open={open !== null} onOpenChange={(o) => !o && setOpenId(null)}>
        {open && (
          <DialogContent className="max-h-[90vh] overflow-auto sm:max-w-4xl">
            <DialogHeader>
              <DialogTitle>{getTemplate(open.templateId).label} · 候選 #{open.variant + 1}</DialogTitle>
              <DialogDescription>
                第 {open.round} 輪・seed {renderSeed(open)}
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="overflow-hidden rounded-lg border">
                <PosterCanvas render={open} copy={open.spec.copy} product={product} brand={brand} pixelWidth={720} />
              </div>
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <ScoreBadge render={open} />
                  <span className="text-sm text-muted-foreground">規則 8 項 + VLM 3 項</span>
                </div>
                <CheckList checks={open.checks} />
              </div>
            </div>
            <DialogFooter>
              <Button
                disabled={!selectable}
                onClick={() => {
                  select(open.templateId, open.id);
                  setOpenId(null);
                }}
              >
                選用此張
              </Button>
            </DialogFooter>
          </DialogContent>
        )}
      </Dialog>
    </div>
  );
}
