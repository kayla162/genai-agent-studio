'use client';

import { useEffect, useRef, useState } from 'react';
import type { JobMessage } from '@/types/contract';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { describeEvent, EVENT_GROUPS, eventGroup, formatOffset, type EventGroup } from '@/lib/agent/events';
import { cn } from '@/lib/utils';

const GROUP_COLOR: Record<EventGroup, string> = {
  job: 'text-sky-300',
  agent: 'text-violet-300',
  rag: 'text-emerald-300',
  comfy: 'text-amber-300',
  review: 'text-pink-300',
  log: 'text-slate-400',
};

const LEVEL_COLOR = { info: 'text-slate-300', ok: 'text-emerald-300', warn: 'text-amber-300', error: 'text-red-300' } as const;

/** WebSocket 事件串流：序號、相對時間、事件類型與摘要；可依分類篩選 */
export function EventStream({ messages }: { messages: JobMessage[] }) {
  const [groups, setGroups] = useState<string[]>(EVENT_GROUPS.map((g) => g.id));
  const [hideProgress, setHideProgress] = useState(true);
  const box = useRef<HTMLDivElement>(null);
  // 使用者捲到底部時，新事件進來會自動捲動；往上捲時保持位置
  const stick = useRef(true);

  const t0 = messages[0] ? Date.parse(messages[0].ts) : 0;
  const shown = messages.filter((m) => groups.includes(eventGroup(m)) && !(hideProgress && m.type === 'render.progress'));

  useEffect(() => {
    const el = box.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [shown.length]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>WebSocket 事件串流</CardTitle>
        <CardDescription>
          共 {messages.length} 則；每則都帶序號（seq）與時間戳（ts），live 模式斷線重新連線時，以序號補齊漏掉的事件。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <ToggleGroup
            type="multiple"
            variant="outline"
            size="sm"
            spacing={1}
            className="flex-wrap"
            value={groups}
            onValueChange={setGroups}
            aria-label="事件分類"
          >
            {EVENT_GROUPS.map((g) => (
              <ToggleGroupItem key={g.id} value={g.id} className="px-3">
                {g.label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <div className="flex items-center gap-2">
            <Switch id="hide-progress" checked={hideProgress} onCheckedChange={setHideProgress} />
            <Label htmlFor="hide-progress" className="font-normal">隱藏 render.progress</Label>
          </div>
        </div>
        <div
          ref={box}
          onScroll={(e) => {
            const el = e.currentTarget;
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
          }}
          className="max-h-[60vh] overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-xs leading-relaxed"
          role="log"
          aria-label="事件串流"
        >
          {shown.length === 0 && <p className="text-slate-500">等待事件…</p>}
          {shown.map((m) => {
            const group = eventGroup(m);
            return (
              <div key={m.seq} className="flex gap-2" title={m.ts}>
                <span className="w-9 shrink-0 text-right text-slate-500">#{m.seq}</span>
                <span className="w-14 shrink-0 text-slate-500">{formatOffset(Date.parse(m.ts) - t0)}</span>
                <span className={cn('hidden w-36 shrink-0 sm:inline', GROUP_COLOR[group])}>{m.type}</span>
                <span className={cn('min-w-0 break-words', m.type === 'log' ? LEVEL_COLOR[m.level] : 'text-slate-200')}>
                  <span className={cn('mr-2 sm:hidden', GROUP_COLOR[group])}>{m.type}</span>
                  {describeEvent(m)}
                </span>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
