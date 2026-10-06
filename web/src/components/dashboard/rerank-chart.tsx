'use client';

import { CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts';
import type { RerankHitStat } from '@/types/contract';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig } from '@/components/ui/chart';

const config = {
  vector: { label: '向量召回', color: 'var(--chart-5)' },
  rerank: { label: 'BGE Rerank 後', color: 'var(--chart-1)' },
} satisfies ChartConfig;

const pct = (v: number) => `${Math.round(v * 100)}%`;

/** Rerank 對命中率的影響：前 k 筆檢索結果涵蓋「審查未通過項目所引用規範」的比例 */
export function RerankChart({ data }: { data: RerankHitStat[] }) {
  const k3 = data.find((d) => d.k === 3);
  const rows = data.map((d) => ({ k: `Top ${d.k}`, vector: Math.round(d.vector * 100), rerank: Math.round(d.rerank * 100) }));
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Rerank 對命中率的影響</CardTitle>
        <CardDescription>
          前 k 筆檢索結果涵蓋「審查未通過項目所引用規範」的比例
          {k3 && `；Top 3：${pct(k3.vector)} → ${pct(k3.rerank)}`}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={config} className="aspect-auto h-80 w-full">
          <LineChart data={rows} margin={{ left: 0, right: 16, top: 8 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="k" tickLine={false} axisLine={false} />
            <YAxis domain={[0, 100]} unit="%" width={44} tickLine={false} axisLine={false} />
            <ChartTooltip content={<ChartTooltipContent formatter={(v, name) => `${config[name as keyof typeof config]?.label ?? name}：${v}%`} />} />
            <ChartLegend content={<ChartLegendContent />} />
            <Line dataKey="vector" type="monotone" stroke="var(--color-vector)" strokeWidth={2} strokeDasharray="5 4" dot />
            <Line dataKey="rerank" type="monotone" stroke="var(--color-rerank)" strokeWidth={2.5} dot />
          </LineChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
