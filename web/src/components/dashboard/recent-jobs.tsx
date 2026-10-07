import Link from 'next/link';
import type { JobStat } from '@/types/contract';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatDuration } from '@/lib/agent/events';
import { useAppStore } from '@/lib/store/app';

const time = (iso: string) =>
  new Date(iso).toLocaleString('zh-TW', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });

/** 最近的任務：每列可點進 Agent 透視 */
export function RecentJobs({ jobs }: { jobs: JobStat[] }) {
  const brands = useAppStore((s) => s.brands);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>最近的任務</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>任務</TableHead>
              <TableHead>品牌</TableHead>
              <TableHead>結果</TableHead>
              <TableHead className="text-right">輪數</TableHead>
              <TableHead className="text-right">交付／候選</TableHead>
              <TableHead className="text-right">耗時</TableHead>
              <TableHead className="text-right">成本</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {jobs.map((j) => (
              <TableRow key={j.jobId}>
                <TableCell>
                  <Link href={`/agent?job=${encodeURIComponent(j.jobId)}`} className="font-mono text-xs text-primary hover:underline">
                    {j.jobId}
                  </Link>
                  <div className="text-xs text-muted-foreground">{time(j.createdAt)}</div>
                </TableCell>
                <TableCell>{brands.find((b) => b.id === j.brandId)?.name ?? j.brandId}</TableCell>
                <TableCell>
                  {j.outcome === 'done'
                    ? <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-emerald-700">完成</Badge>
                    : <Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-800">需人工審核</Badge>}
                </TableCell>
                <TableCell className="text-right font-mono">{j.rounds}</TableCell>
                <TableCell className="text-right font-mono">{j.delivered}／{j.renders}</TableCell>
                <TableCell className="text-right font-mono">{formatDuration(j.durationMs)}</TableCell>
                <TableCell className="text-right font-mono">${j.costUsd.toFixed(3)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
