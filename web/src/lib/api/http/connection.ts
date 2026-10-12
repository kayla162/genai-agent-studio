import type { ConnectionState, ConnectionStatus } from '@/types/contract';
import type { ConnectionChannel } from '../client';

/** 連線狀態：最近一次請求或 WebSocket 的結果。狀態沒變時 get() 回傳同一個物件（給 useSyncExternalStore）。 */
export class ConnectionTracker implements ConnectionChannel {
  private state: ConnectionState = Object.freeze({ status: 'connecting', transport: 'websocket', error: null });
  private readonly listeners = new Set<(state: ConnectionState) => void>();

  /** onWatch：第一次有人訂閱時呼叫（連線狀態有人看，才需要主動確認後端是否在線） */
  constructor(private readonly onWatch?: () => void) {}

  get watched(): boolean {
    return this.listeners.size > 0;
  }

  get(): ConnectionState {
    return this.state;
  }

  subscribe(listener: (state: ConnectionState) => void): () => void {
    this.listeners.add(listener);
    if (this.listeners.size === 1) this.onWatch?.();
    return () => {
      this.listeners.delete(listener);
    };
  }

  set(status: ConnectionStatus, error: string | null = null): void {
    if (this.state.status === status && this.state.error === error) return;
    this.state = Object.freeze({ status, transport: 'websocket', error });
    for (const listener of this.listeners) listener(this.state);
  }
}
