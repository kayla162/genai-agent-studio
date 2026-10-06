'use client';

import { useState } from 'react';
import { FlaskConical } from 'lucide-react';
import type { DemoOptions } from '@/types/contract';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Switch } from '@/components/ui/switch';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { API_MODE, getApiClient } from '@/lib/api';

const SPEEDS = [1, 2, 4] as const;

/** 畫面右下角的 Demo 控制台（只有 mock 模式） */
export function DemoConsole() {
  const [options, setOptions] = useState<DemoOptions | null>(null);
  if (API_MODE !== 'mock') return null;

  const update = (patch: Partial<DemoOptions>) => {
    const demo = getApiClient().demo;
    if (!demo) return;
    demo.set(patch);
    setOptions(demo.get());
  };

  return (
    <Popover onOpenChange={(open) => open && setOptions(getApiClient().demo?.get() ?? null)}>
      <PopoverTrigger asChild>
        <Button size="lg" className="fixed right-4 bottom-4 z-40 rounded-full shadow-lg" aria-label="開啟 Demo 控制台">
          <FlaskConical />
          Demo
        </Button>
      </PopoverTrigger>
      <PopoverContent side="top" align="end" className="w-80">
        <div className="space-y-4">
          <div>
            <p className="font-semibold">Demo 控制台</p>
            <p className="text-xs text-muted-foreground">瀏覽器內模擬整條 Agent 流程，事件格式與 FastAPI WebSocket 相同。</p>
          </div>
          <div className="space-y-2">
            <Label>播放速度（立即生效）</Label>
            <ToggleGroup
              type="single"
              variant="outline"
              spacing={0}
              value={String(options?.speed ?? 1)}
              onValueChange={(v) => v && update({ speed: Number(v) as DemoOptions['speed'] })}
            >
              {SPEEDS.map((s) => (
                <ToggleGroupItem key={s} value={String(s)} className="w-14">
                  {s}×
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
          <div className="flex items-center justify-between gap-3">
            <Label htmlFor="demo-first-fail" className="flex-col items-start gap-0.5">
              強制首輪失敗
              <span className="text-xs font-normal text-muted-foreground">展示 Query Rewriting 與重試</span>
            </Label>
            <Switch
              id="demo-first-fail"
              checked={options?.firstRoundFail ?? true}
              onCheckedChange={(v) => update({ firstRoundFail: v })}
            />
          </div>
          <div className="flex items-center justify-between gap-3">
            <Label htmlFor="demo-all-fail" className="flex-col items-start gap-0.5">
              強制全部失敗
              <span className="text-xs font-normal text-muted-foreground">展示「需人工審核」</span>
            </Label>
            <Switch id="demo-all-fail" checked={options?.forceAllFail ?? false} onCheckedChange={(v) => update({ forceAllFail: v })} />
          </div>
          <p className="text-xs text-muted-foreground">失敗設定從下一個任務開始生效。</p>
        </div>
      </PopoverContent>
    </Popover>
  );
}
