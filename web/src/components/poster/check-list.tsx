import { CircleCheck, CircleX, TriangleAlert } from 'lucide-react';
import type { CheckStatus, ReviewCheck } from '@/types/contract';
import { measuredBackgroundOf, measuredPrimaryOf } from '@/lib/review/rules';
import { cn } from '@/lib/utils';

const ICON: Record<CheckStatus, React.ReactNode> = {
  pass: <CircleCheck className="size-4 text-success" />,
  warn: <TriangleAlert className="size-4 text-warning" />,
  fail: <CircleX className="size-4 text-destructive" />,
};

/** 主色與背景色系檢查說明旁的色塊：量到的主色（偏色時是實際用錯的顏色），或背景中最多的色系外顏色 */
function PrimarySwatch({ check }: { check: ReviewCheck }) {
  const primary = measuredPrimaryOf(check);
  const hex = primary ?? measuredBackgroundOf(check);
  if (!hex) return null;
  return (
    <span
      className="inline-block size-3 shrink-0 rounded-sm border" style={{ backgroundColor: hex }}
      title={primary ? `偵測主色 ${hex}` : `背景色系外 ${hex}`} aria-hidden
    />
  );
}

/** 審查項目清單（單張審查細節、文字編輯器的即時檢查共用）；compact 只顯示名稱與結果，完整清單在主色檢查旁顯示量到的主色色塊 */
export function CheckList({ checks, compact = false, className }: { checks: ReviewCheck[]; compact?: boolean; className?: string }) {
  if (compact) {
    return (
      <ul className={cn('space-y-1 text-xs', className)}>
        {checks.map((c) => (
          <li key={c.id} className="flex items-start gap-1.5">
            <span className="mt-px [&_svg]:size-3.5">{ICON[c.status]}</span>
            <span>
              <span className="font-medium">{c.name}</span>
              <span className="text-muted-foreground">：{c.value}</span>
            </span>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <ul className={cn('divide-y rounded-lg border', className)}>
      {checks.map((c) => (
        <li key={c.id} className="flex gap-2.5 px-3 py-2">
          <span className="mt-0.5">{ICON[c.status]}</span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">{c.name}</span>
              <span className="rounded bg-muted px-1.5 text-[10px] font-semibold text-muted-foreground">{c.kind === 'rule' ? '規則' : 'VLM'}</span>
              <span className={cn('ml-auto inline-flex items-center gap-1.5 text-xs', c.status === 'pass' ? 'text-muted-foreground' : c.status === 'warn' ? 'text-warning' : 'text-destructive')}>
                <PrimarySwatch check={c} />
                {c.value}
              </span>
            </div>
            <p className="text-xs text-muted-foreground">
              {c.rule}
              {c.ragRef && <span className="ml-2 font-mono text-[11px]">RAG: {c.ragRef}</span>}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}
