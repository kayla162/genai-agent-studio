'use client';

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts';
import type { CheckFailureStat } from '@/types/contract';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig } from '@/components/ui/chart';

const config = {
  fail: { label: '未通過', color: 'var(--destructive)' },
  warn: { label: '警告', color: 'var(--warning)' },
} satisfies ChartConfig;

/** 各檢查項的失敗分布（含所有輪次的候選） */
export function CheckFailureChart({ data }: { data: CheckFailureStat[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>各檢查項失敗分布</CardTitle>
        <CardDescription>所有輪次的候選；第一輪的問題會在 Query Rewriting 後修正。</CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={config} className="aspect-auto h-80 w-full">
          <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }}>
            <CartesianGrid horizontal={false} />
            <XAxis type="number" allowDecimals={false} tickLine={false} axisLine={false} />
            <YAxis type="category" dataKey="name" width={108} tickLine={false} axisLine={false} />
            <ChartTooltip cursor={false} content={<ChartTooltipContent />} />
            <ChartLegend content={<ChartLegendContent />} />
            <Bar dataKey="fail" stackId="n" fill="var(--color-fail)" radius={[0, 0, 0, 0]} />
            <Bar dataKey="warn" stackId="n" fill="var(--color-warn)" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
