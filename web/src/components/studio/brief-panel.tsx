'use client';

import { useState } from 'react';
import { LoaderCircle, Play, Square, WandSparkles } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';
import { TONES, type Brand, type Engine, type ParsedBrief, type Tone } from '@/types/contract';
import { ProductImage } from '@/components/product/product-image';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { CHANNEL_TEMPLATES } from '@/lib/compose/templates';
import { useProductsStore } from '@/lib/store/products';
import { DEMO_BRIEFS, ENGINE_LABEL, LLM_OPTIONS, TONE_LABEL, useStudioStore, VLM_OPTIONS } from '@/lib/store/studio';

const splitList = (s: string) => s.split(/[,，、]/).map((x) => x.trim()).filter(Boolean);

/** 以分隔符號輸入清單：打字時保留原文，離開欄位才拆成陣列（否則打到「、」就會被吃掉） */
function ListInput({ id, value, separator, disabled, onCommit }: {
  id: string; value: string[]; separator: string; disabled: boolean; onCommit: (list: string[]) => void;
}) {
  const [text, setText] = useState(value.join(separator));
  return (
    <Input id={id} disabled={disabled} value={text} onChange={(e) => setText(e.target.value)} onBlur={() => onCommit(splitList(text))} />
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <span className="rounded-full bg-secondary px-2 py-0.5 text-[11px] font-semibold text-primary">STEP {n}</span>
        {title}
      </h3>
      {children}
    </section>
  );
}

function ParsedFields({ parsed, disabled }: { parsed: ParsedBrief; disabled: boolean }) {
  const patch = useStudioStore((s) => s.patchParsed);
  return (
    <div className="grid grid-cols-2 gap-3 rounded-lg border bg-muted/40 p-3">
      <div className="col-span-2 space-y-1.5">
        <Label htmlFor="pb-points">賣點（以頓號或逗號分隔）</Label>
        {/* key：重新拆解後清單改變時重設輸入框 */}
        <ListInput key={parsed.sellingPoints.join('|')} id="pb-points" separator="、" disabled={disabled} value={parsed.sellingPoints} onCommit={(sellingPoints) => patch({ sellingPoints })} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="pb-audience">客群</Label>
        <Input id="pb-audience" disabled={disabled} value={parsed.audience} onChange={(e) => patch({ audience: e.target.value })} />
      </div>
      <div className="space-y-1.5">
        <Label>語氣</Label>
        <Select disabled={disabled} value={parsed.tone} onValueChange={(v) => patch({ tone: v as Tone })}>
          <SelectTrigger className="w-full bg-card"><SelectValue /></SelectTrigger>
          <SelectContent>
            {TONES.map((t) => <SelectItem key={t} value={t}>{TONE_LABEL[t]}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="pb-campaign">檔期</Label>
        <Input id="pb-campaign" disabled={disabled} placeholder="無" value={parsed.campaign ?? ''} onChange={(e) => patch({ campaign: e.target.value.trim() || null })} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="pb-offer">優惠</Label>
        <Input id="pb-offer" disabled={disabled} placeholder="無" value={parsed.offer ?? ''} onChange={(e) => patch({ offer: e.target.value.trim() || null })} />
      </div>
      <div className="col-span-2 space-y-1.5">
        <Label htmlFor="pb-style">風格標籤（英文，進 Prompt）</Label>
        <ListInput key={parsed.style.join('|')} id="pb-style" separator=", " disabled={disabled} value={parsed.style} onCommit={(style) => patch({ style })} />
      </div>
    </div>
  );
}

export function BriefPanel({ brand }: { brand: Brand }) {
  // 只訂閱表單需要的欄位；生成中的事件（view）不會讓表單重繪
  const s = useStudioStore(useShallow((st) => ({
    brief: st.brief, productId: st.productId, parsed: st.parsed, templateIds: st.templateIds, variants: st.variants,
    llm: st.llm, engine: st.engine, vlm: st.vlm, maxRetries: st.maxRetries, parsing: st.parsing, starting: st.starting,
    error: st.error, jobRunning: st.view?.outcome === 'running',
    setForm: st.setForm, toggleTemplate: st.toggleTemplate, parse: st.parse, start: st.start, cancel: st.cancel,
  })));
  const products = useProductsStore((p) => p.products);
  const running = s.jobRunning || s.starting;

  const chooseProduct = (id: string) => {
    s.setForm({ productId: id });
    // 換商品後賣點與商品名稱會變，重新拆解
    if (s.parsed) void s.parse();
  };

  return (
    <Card className="lg:sticky lg:top-20">
      <CardHeader>
        <CardTitle>新任務</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <Step n={1} title="一句話需求">
          <Textarea
            aria-label="一句話需求"
            rows={3}
            disabled={running}
            value={s.brief}
            onChange={(e) => s.setForm({ brief: e.target.value })}
            placeholder={DEMO_BRIEFS[brand.id] ?? '例如：幫我做週年慶海報，主打買一送一'}
          />
          <div className="space-y-1.5">
            <Label htmlFor="studio-product">商品</Label>
            <Select disabled={running || !products.length} value={s.productId ?? ''} onValueChange={chooseProduct}>
              <SelectTrigger id="studio-product" className="h-11 w-full">
                <SelectValue placeholder="先到商品庫新增商品" />
              </SelectTrigger>
              <SelectContent>
                {products.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    <ProductImage product={p} brand={brand} className="size-7 rounded" />
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button variant="secondary" className="w-full" disabled={running || s.parsing || !s.brief.trim()} onClick={() => void s.parse()}>
            {s.parsing ? <LoaderCircle className="animate-spin" /> : <WandSparkles />}
            Agent 拆解需求
          </Button>
          {s.parsed && <ParsedFields parsed={s.parsed} disabled={running} />}
        </Step>

        <Step n={2} title="通路模板">
          <div className="grid gap-2">
            {CHANNEL_TEMPLATES.map((t) => (
              <label key={t.id} className="flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 text-sm has-[button[data-state=checked]]:border-primary has-[button[data-state=checked]]:bg-secondary/60">
                <Checkbox aria-label={t.label} disabled={running} checked={s.templateIds.includes(t.id)} onCheckedChange={() => s.toggleTemplate(t.id)} />
                <span className="font-medium">{t.label}</span>
                <span className="ml-auto font-mono text-xs text-muted-foreground">{t.ratio} · {t.width}×{t.height}</span>
              </label>
            ))}
          </div>
        </Step>

        <Step n={3} title="生成設定">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>每個模板候選張數</Label>
              <Select disabled={running} value={String(s.variants)} onValueChange={(v) => s.setForm({ variants: Number(v) })}>
                <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => <SelectItem key={n} value={String(n)}>{n} 張</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>最大重試次數</Label>
              <Select disabled={running} value={String(s.maxRetries)} onValueChange={(v) => s.setForm({ maxRetries: Number(v) })}>
                <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {[0, 1, 2, 3].map((n) => <SelectItem key={n} value={String(n)}>{n} 次</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          <details className="rounded-lg border px-3 py-2 text-sm">
            <summary className="cursor-pointer font-medium text-muted-foreground">模型與引擎</summary>
            <div className="mt-3 space-y-3">
              <div className="space-y-1.5">
                <Label>LLM（需求拆解、文案、Prompt）</Label>
                <Select disabled={running} value={s.llm} onValueChange={(v) => s.setForm({ llm: v })}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>{LLM_OPTIONS.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>生圖引擎</Label>
                <Select disabled={running} value={s.engine} onValueChange={(v) => s.setForm({ engine: v as Engine })}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {(Object.keys(ENGINE_LABEL) as Engine[]).map((e) => <SelectItem key={e} value={e}>{ENGINE_LABEL[e]}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>VLM（合規審查）</Label>
                <Select disabled={running} value={s.vlm} onValueChange={(v) => s.setForm({ vlm: v })}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>{VLM_OPTIONS.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            </div>
          </details>
        </Step>
        {s.error && <p className="text-sm text-destructive">{s.error}</p>}
      </CardContent>
      <CardFooter className="gap-2">
        {s.jobRunning ? (
          <Button variant="outline" className="w-full" onClick={() => void s.cancel()}>
            <Square />
            取消任務
          </Button>
        ) : (
          <Button size="lg" className="w-full" disabled={running} onClick={() => void s.start()}>
            {s.starting ? <LoaderCircle className="animate-spin" /> : <Play />}
            開始生成（{s.templateIds.length} 個模板 × {s.variants} 張）
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}
