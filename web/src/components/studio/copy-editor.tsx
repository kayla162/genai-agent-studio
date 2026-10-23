'use client';

import { useState } from 'react';
import { CircleCheck, Download, FileDown, LoaderCircle, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import type { Brand, Copy, Product } from '@/types/contract';
import { CheckList } from '@/components/poster/check-list';
import { PosterCanvas } from '@/components/poster/poster-canvas';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { getTemplate } from '@/lib/compose/templates';
import type { Candidate } from '@/lib/jobs/view';
import { exportPosterPng, exportPosterZip } from '@/lib/export/posters';
import { copyBlockers, recheckCopy } from '@/lib/review/recheck';
import { useStudioStore } from '@/lib/store/studio';

function Field({ id, label, value, onChange }: { id: string; label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function CopyForm({ copy, onChange }: { copy: Copy; onChange: (c: Copy) => void }) {
  const set = (patch: Partial<Copy>) => onChange({ ...copy, ...patch });
  const features = [0, 1, 2].map((i) => copy.features[i] ?? '');
  const num = (v: string) => Math.max(0, Math.round(Number(v) || 0));
  return (
    <div className="space-y-3">
      <Field id="c-h1" label="標題第一行" value={copy.headline[0]} onChange={(v) => set({ headline: [v, copy.headline[1]] })} />
      <Field id="c-h2" label="標題第二行（主色強調）" value={copy.headline[1]} onChange={(v) => set({ headline: [copy.headline[0], v] })} />
      <Field id="c-sub" label="副標" value={copy.subhead} onChange={(v) => set({ subhead: v })} />
      <div className="space-y-1.5">
        <Label>賣點</Label>
        <div className="grid grid-cols-3 gap-2">
          {features.map((f, i) => (
            <Input
              key={i}
              aria-label={`賣點 ${i + 1}`}
              value={f}
              // 保留空字串讓欄位位置不變；排版引擎會略過空的賣點
              onChange={(e) => set({ features: features.map((x, j) => (j === i ? e.target.value : x)) })}
            />
          ))}
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Field id="c-bt" label="徽章上排" value={copy.badge.top} onChange={(v) => set({ badge: { ...copy.badge, top: v } })} />
        <Field id="c-bm" label="徽章主字" value={copy.badge.main} onChange={(v) => set({ badge: { ...copy.badge, main: v } })} />
        <Field id="c-bs" label="徽章英文" value={copy.badge.sub} onChange={(v) => set({ badge: { ...copy.badge, sub: v } })} />
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Field id="c-pl" label="價格標籤" value={copy.price.label} onChange={(v) => set({ price: { ...copy.price, label: v } })} />
        <div className="space-y-1.5">
          <Label htmlFor="c-ps">特價</Label>
          <Input id="c-ps" type="number" min={0} value={copy.price.sale} onChange={(e) => set({ price: { ...copy.price, sale: num(e.target.value) } })} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="c-po">原價</Label>
          <Input id="c-po" type="number" min={0} value={copy.price.original} onChange={(e) => set({ price: { ...copy.price, original: num(e.target.value) } })} />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="c-disc">頁尾註記</Label>
        <Textarea id="c-disc" rows={2} value={copy.disclaimer} onChange={(e) => set({ disclaimer: e.target.value })} />
      </div>
    </div>
  );
}

/** 選定候選後：改文案即時重繪、即時重跑規則審查、匯出 zip 並寫入歷史紀錄 */
export function CopyEditor({ brand, product }: { brand: Brand; product: Product | null }) {
  const view = useStudioStore((s) => s.view);
  const input = useStudioStore((s) => s.input);
  const selection = useStudioStore((s) => s.selection);
  const copy = useStudioStore((s) => s.copy);
  const setCopy = useStudioStore((s) => s.setCopy);
  const saveSelection = useStudioStore((s) => s.saveSelection);
  const [exporting, setExporting] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  if (!view || !input || !copy || (view.outcome !== 'done' && view.outcome !== 'needs_review')) return null;

  const selected = input.templateIds
    .map((t) => (selection[t] ? view.renders[selection[t]!] : undefined))
    .filter((r): r is Candidate => r !== undefined);
  const checks = selected.map((r) => ({ render: r, checks: recheckCopy(r, brand, copy) }));
  const blockers = checks.flatMap((x) => copyBlockers(x.checks));
  const needsConfirm = view.outcome === 'needs_review' || selected.some((r) => !r.passed);

  const exportAll = async () => {
    setExporting(true);
    try {
      await exportPosterZip(brand, product, selected.map((render) => ({ render, copy })));
      const written = await saveSelection();
      toast.success(`已匯出 ${selected.length} 張海報`, {
        description: written ? `${written} 張寫入歷史紀錄，並標記「已回寫 RAG（歷史優秀案例）」。` : '這些圖與文案先前已寫入歷史紀錄。',
      });
    } catch (err) {
      toast.error('匯出失敗', { description: err instanceof Error ? err.message : String(err) });
    } finally {
      setExporting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>文字編輯器</CardTitle>
        <CardDescription>修改文案、價格與徽章，所有選定的模板即時重繪，不重新產圖；規則型審查同步重跑。</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="space-y-3">
          <CopyForm copy={copy} onChange={setCopy} />
          <Button
            variant="ghost"
            size="sm"
            onClick={() => selected[0] && setCopy(structuredClone(selected[0].spec.copy))}
          >
            <RotateCcw />
            還原 AI 文案
          </Button>
        </div>
        <div className="min-w-0 space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {checks.map(({ render: r, checks: cs }) => {
              const issues = cs.filter((c) => c.status !== 'pass');
              return (
                <div key={r.id} className="space-y-2">
                  <div className="flex items-center gap-2 text-sm">
                    <span className="font-semibold">{getTemplate(r.templateId).label}</span>
                    <Button size="xs" variant="ghost" className="ml-auto" onClick={() => void exportPosterPng(brand, product, { render: r, copy })}>
                      <Download />
                      PNG
                    </Button>
                  </div>
                  <div className="overflow-hidden rounded-lg border">
                    <PosterCanvas render={r} copy={copy} product={product} brand={brand} pixelWidth={520} />
                  </div>
                  {issues.length ? (
                    <CheckList compact checks={issues} />
                  ) : (
                    <p className="flex items-center gap-1.5 text-xs text-success">
                      <CircleCheck className="size-4" />
                      規則型審查全部通過（VLM 結果沿用生成時）
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </CardContent>
      <CardFooter className="flex-wrap gap-3">
        {blockers.length > 0 && <p className="text-sm text-destructive">文案含禁用詞，請先修改：{blockers[0].value}</p>}
        {needsConfirm && (
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={confirmed} onCheckedChange={(v) => setConfirmed(v === true)} />
            部分候選未通過審查，我已人工確認可以使用
          </label>
        )}
        <Button
          size="lg"
          className="ml-auto"
          disabled={exporting || !selected.length || blockers.length > 0 || (needsConfirm && !confirmed)}
          onClick={() => void exportAll()}
        >
          {exporting ? <LoaderCircle className="animate-spin" /> : <FileDown />}
          匯出 zip 並寫入歷史（{selected.length} 張）
        </Button>
      </CardFooter>
    </Card>
  );
}
