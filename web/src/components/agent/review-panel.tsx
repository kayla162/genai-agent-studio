'use client';

import { useEffect, useState } from 'react';
import Image from 'next/image';
import { ShieldCheck } from 'lucide-react';
import type { CheckStatus, JobInput, Product, Render } from '@/types/contract';
import { EmptyState } from '@/components/common/empty-state';
import { CheckList } from '@/components/poster/check-list';
import { PosterCanvas } from '@/components/poster/poster-canvas';
import { ScoreBadge } from '@/components/poster/score-badge';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { getApiClient } from '@/lib/api';
import { overlayFor } from '@/lib/agent/inspect';
import { getTemplate } from '@/lib/compose/templates';
import type { JobView } from '@/lib/jobs/view';
import { useAppStore } from '@/lib/store/app';

const STATUS_COLOR: Record<CheckStatus | 'none', string> = { fail: '#dc2626', warn: '#d97706', pass: '#059669', none: '#64748b' };
const LEGEND: [CheckStatus | 'none', string][] = [['fail', '未通過'], ['warn', '警告'], ['pass', '通過'], ['none', '無檢查']];

/** 疊圖的底圖：瀏覽器即時繪製的預覽，或 worker 存下的審查用海報（伺服器端繪製，主色依它量測） */
type PosterSource = 'preview' | 'review';
const POSTER_SOURCES: { id: PosterSource; label: string }[] = [
  { id: 'preview', label: '預覽' },
  { id: 'review', label: '審查用海報' },
];

/** 海報上疊出版面 BBox，依指向該元素的檢查結果上色 */
function BBoxOverlay({ render }: { render: Render }) {
  const { width: W, height: H } = render.spec.canvas;
  const overlay = overlayFor(render);
  const canvasIssue = overlay.canvas.status === 'fail' || overlay.canvas.status === 'warn';
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="pointer-events-none absolute inset-0 size-full" aria-hidden>
      {canvasIssue && (
        <rect x={0} y={0} width={W} height={H} fill="none" stroke={STATUS_COLOR[overlay.canvas.status!]} strokeWidth={W * 0.012} />
      )}
      {overlay.boxes.map((b) => {
        const [x, y, w, h] = b.bbox;
        const color = STATUS_COLOR[b.status ?? 'none'];
        const bad = b.status === 'fail' || b.status === 'warn';
        const size = W * 0.022;
        return (
          <g key={b.id}>
            <rect
              x={x} y={y} width={w} height={h} fill={color} fillOpacity={bad ? 0.14 : 0} stroke={color} strokeWidth={W * 0.004}
              strokeDasharray={b.status ? undefined : `${W * 0.01} ${W * 0.008}`}
            />
            <text
              x={x + size * 0.3} y={y + size * 1.05} fontSize={size} fontWeight={700} fill={color}
              stroke="#fff" strokeWidth={size * 0.18} paintOrder="stroke"
            >
              {b.id}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** 依任務的品牌讀取商品（換品牌或商品已刪除時為 null） */
function useProduct(brandId: string, productId: string | null): Product | null {
  const [product, setProduct] = useState<Product | null>(null);
  useEffect(() => {
    if (!productId) return;
    let alive = true;
    void getApiClient().listProducts(brandId).then((list) => {
      if (alive) setProduct(list.find((p) => p.id === productId) ?? null);
    });
    return () => {
      alive = false;
    };
  }, [brandId, productId]);
  return product;
}

/** 合規報告：選一張候選，看 BBox 疊圖與 10 項檢查 */
export function ReviewPanel({ view, input }: { view: JobView; input: JobInput | null }) {
  const reviewed = view.renderIds.map((id) => view.renders[id]).filter((r) => r.score !== null);
  const [picked, setPicked] = useState<string | null>(null);
  const [showBoxes, setShowBoxes] = useState(true);
  const [source, setSource] = useState<PosterSource>('preview');
  const fallback = Object.values(view.bestRenderIds)[0] ?? reviewed.at(-1)?.id ?? null;
  const render = (picked && view.renders[picked]) || (fallback ? view.renders[fallback] : null);
  const brandId = render?.spec.brandId ?? input?.brandId ?? '';
  const brand = useAppStore((s) => s.brands.find((b) => b.id === brandId));
  const product = useProduct(brandId, input?.productId ?? null);

  if (!render || !brand) {
    return <EmptyState icon={ShieldCheck} title="尚未審查">候選完成合規審查後，這裡會顯示 BBox 疊圖與每一項檢查。</EmptyState>;
  }
  const best = Object.values(view.bestRenderIds).includes(render.id);
  // 模擬模式（REVIEW_MODE=sim、mock）沒有審查用海報：不顯示切換，一律用預覽
  const reviewImage = render.reviewImage;
  const showReview = source === 'review' && reviewImage !== null;
  const { width: W, height: H } = render.spec.canvas;

  return (
    <div className="space-y-4">
      <Select value={render.id} onValueChange={setPicked}>
        <SelectTrigger className="w-full bg-card sm:w-96" aria-label="選擇候選">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {reviewed.map((r) => (
            <SelectItem key={r.id} value={r.id}>
              第 {r.round} 輪・{getTemplate(r.templateId).label}・#{r.variant + 1}
              <span className={r.passed ? 'text-xs text-success' : 'text-xs text-destructive'}>{r.score} 分</span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>BBox 疊圖</CardTitle>
            <CardDescription>LLM 輸出的版面座標；顏色依指向該元素的檢查結果，外框代表整張圖的檢查（主色色差）。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {reviewImage && (
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <ToggleGroup
                  type="single"
                  variant="outline"
                  size="sm"
                  value={showReview ? 'review' : 'preview'}
                  onValueChange={(v) => v && setSource(v as PosterSource)}
                  aria-label="預覽／審查用海報"
                >
                  {POSTER_SOURCES.map((s) => (
                    <ToggleGroupItem key={s.id} value={s.id} className="px-3">{s.label}</ToggleGroupItem>
                  ))}
                </ToggleGroup>
                <p className="text-xs text-muted-foreground">
                  {showReview ? '伺服器端繪製並存檔的 PNG，主色色差依這張圖的像素量測。' : '瀏覽器即時繪製的預覽。'}
                </p>
              </div>
            )}
            <div className="relative overflow-hidden rounded-lg border">
              {showReview ? (
                <Image
                  src={reviewImage}
                  alt={`${render.spec.copy.headline.join(' ')} 審查用海報`}
                  width={W}
                  height={H}
                  unoptimized
                  className="block h-auto w-full bg-muted"
                />
              ) : (
                <PosterCanvas render={render} copy={render.spec.copy} product={product} brand={brand} pixelWidth={720} />
              )}
              {showBoxes && <BBoxOverlay render={render} />}
            </div>
            <div className="flex flex-wrap items-center gap-3 text-xs">
              {LEGEND.map(([status, label]) => (
                <span key={status} className="inline-flex items-center gap-1.5">
                  <span className="size-3 rounded-sm border-2" style={{ borderColor: STATUS_COLOR[status] }} />
                  {label}
                </span>
              ))}
              <div className="ml-auto flex items-center gap-2">
                <Switch id="show-bbox" checked={showBoxes} onCheckedChange={setShowBoxes} />
                <Label htmlFor="show-bbox" className="font-normal">顯示 BBox</Label>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2">
              合規報告
              <ScoreBadge render={render} />
              {best && <Badge>最佳候選</Badge>}
            </CardTitle>
            <CardDescription>規則 7 項（禁用詞、ΔE2000、Logo 淨空區…）+ VLM 3 項；附上引用的 RAG 規範。</CardDescription>
          </CardHeader>
          <CardContent>
            <CheckList checks={render.checks} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
