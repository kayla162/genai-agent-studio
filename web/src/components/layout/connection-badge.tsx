'use client';

import { useSyncExternalStore } from 'react';
import type { ConnectionState } from '@/types/contract';
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

export function ConnectionBadge() {
  const state = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return (
    <span
      className="inline-flex h-7 items-center gap-2 rounded-full border bg-card px-2.5 text-xs text-muted-foreground sm:px-3"
      title={state.error ?? undefined}
    >
      <span className={cn('size-1.5 rounded-full', DOT[state.status])} />
      <span className="hidden sm:inline">{LABEL[state.status]}</span>
      <span className="hidden font-mono text-[11px] opacity-70 sm:inline">{state.transport}</span>
    </span>
  );
}
