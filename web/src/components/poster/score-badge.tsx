import { LoaderCircle } from 'lucide-react';
import type { Render } from '@/types/contract';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

/** 合規分數徽章：綠＝通過、黃＝通過但有警告、紅＝未通過 */
export function ScoreBadge({ render, className }: { render: Pick<Render, 'score' | 'passed' | 'checks'>; className?: string }) {
  if (render.score === null) {
    return (
      <Badge variant="outline" className={className}>
        <LoaderCircle className="animate-spin" />
        審查中
      </Badge>
    );
  }
  const warn = render.checks.some((c) => c.status === 'warn');
  const tone = !render.passed
    ? 'border-red-200 bg-red-50 text-red-700'
    : warn
      ? 'border-amber-200 bg-amber-50 text-amber-800'
      : 'border-emerald-200 bg-emerald-50 text-emerald-700';
  return (
    <Badge variant="outline" className={cn(tone, className)}>
      {render.score} 分{render.passed ? '' : '・未通過'}
    </Badge>
  );
}
