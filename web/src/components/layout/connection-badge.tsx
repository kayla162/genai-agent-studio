'use client';

import { useState, useSyncExternalStore } from 'react';
import type { ComponentStatus, ConnectionState, SystemStatus } from '@/types/contract';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { getApiClient } from '@/lib/api';
import { cn } from '@/lib/utils';

const SERVER_STATE: ConnectionState = { status: 'connecting', transport: 'mock', error: null };
const subscribe = (cb: () => void) => getApiClient().connection.subscribe(cb);
const getSnapshot = () => getApiClient().connection.get();
const getServerSnapshot = () => SERVER_STATE;

const LABEL: Record<ConnectionState['status'], string> = { connecting: '連線中', connected: 'WebSocket 已連線', disconnected: '連線中斷' };
const DOT: Record<ConnectionState['status'], string> = {
  connecting: 'bg-warning shadow-[0_0_0_3px_#fef5e6]',
  connected: 'bg-success shadow-[0_0_0_3px_#e9f8ef]',
  disconnected: 'bg-destructive shadow-[0_0_0_3px_#fdeeee]',
};

const COMPONENT: Record<ComponentStatus['status'], { label: string; className: string }> = {
  ok: { label: '正常', className: 'bg-emerald-50 text-emerald-700' },
  sim: { label: '模擬', className: 'bg-secondary text-primary' },
  off: { label: '準備中', className: 'bg-muted text-muted-foreground' },
  error: { label: '異常', className: 'bg-red-50 text-red-700' },
};

/** 右上角的連線狀態；點開可看各服務的狀態（開始生圖前確認 ComfyUI 是否開著） */
export function ConnectionBadge() {
  const state = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [failed, setFailed] = useState(false);

  const refresh = () => {
    setFailed(false);
    getApiClient().getSystemStatus().then(setSystem, () => setFailed(true));
  };

  return (
    <Popover onOpenChange={(open) => open && refresh()}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="系統狀態"
          className="inline-flex h-7 items-center gap-2 rounded-full border bg-card px-2.5 text-xs text-muted-foreground sm:px-3"
          title={state.error ?? undefined}
        >
          <span className={cn('size-1.5 rounded-full', DOT[state.status])} />
          <span className="hidden sm:inline">{LABEL[state.status]}</span>
          <span className="hidden font-mono text-[11px] opacity-70 sm:inline">{state.transport}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80">
        <p className="font-semibold">系統狀態</p>
        {failed && <p className="mt-2 text-sm text-destructive">無法取得系統狀態，請確認後端是否啟動。</p>}
        {!failed && !system && <p className="mt-2 text-sm text-muted-foreground">讀取中…</p>}
        {!failed && system && (
          <ul className="mt-2 space-y-2">
            {system.components.map((c) => (
              <li key={c.id} className="text-sm">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{c.label}</span>
                  <span className={cn('ml-auto rounded-full px-2 py-0.5 text-xs font-medium', COMPONENT[c.status].className)}>
                    {COMPONENT[c.status].label}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">{c.detail}</p>
              </li>
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  );
}
