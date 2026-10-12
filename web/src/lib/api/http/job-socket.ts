import type { JobMessage } from '@/types/contract';
import type { ConnectionTracker } from './connection';

/** 伺服器關閉代碼：任務不存在（不再重新連線） */
export const WS_NOT_FOUND = 4404;
/** 重新連線的等待時間：1 秒起每次加倍，最長 10 秒 */
export const RECONNECT_DELAY = { min: 1_000, max: 10_000 };

const FINISHED = new Set(['done', 'needs_review', 'cancelled', 'failed']);
const isFinal = (m: JobMessage) => m.type === 'job.status' && FINISHED.has(m.stage);

export interface JobSocketOptions {
  /** 從 seq 之後開始補送的 WebSocket 網址 */
  url: (after: number) => string;
  WebSocket: typeof WebSocket;
  connection: ConnectionTracker;
}

/**
 * 訂閱任務事件：伺服器先補送已發生的事件，再轉送即時事件；任務結束且事件送完後以 1000 關閉。
 * 連線中斷時以最後收到的 seq 重新連線，並依 seq 略過重複的事件。回傳取消訂閱的函式。
 */
export function openJobSocket(
  jobId: string,
  onEvent: (message: JobMessage) => void,
  onError: (error: Error) => void,
  { url, WebSocket, connection }: JobSocketOptions,
): () => void {
  let socket: WebSocket | null = null;
  let retry: ReturnType<typeof setTimeout> | null = null;
  let delay = RECONNECT_DELAY.min;
  let lastSeq = 0;
  let finished = false;
  let stopped = false;

  const fail = (error: Error) => {
    stopped = true;
    socket?.close();
    onError(error);
  };

  const connect = () => {
    retry = null;
    let ws: WebSocket;
    try {
      ws = new WebSocket(url(lastSeq));
    } catch (err) {
      // 與 WebSocket 的其他錯誤一樣非同步回報
      queueMicrotask(() => {
        if (!stopped) fail(err instanceof Error ? err : new Error(String(err)));
      });
      return;
    }
    socket = ws;
    // 這裡不重設等待時間：伺服器先 accept 才訂閱 Redis，Redis 連不上時每次都會「連上」再以 1011 關閉
    ws.onopen = () => connection.set('connected');
    ws.onmessage = (e: MessageEvent) => {
      if (stopped) return;
      let message: JobMessage;
      try {
        message = JSON.parse(String(e.data)) as JobMessage;
      } catch {
        fail(new Error(`任務 ${jobId} 的事件格式錯誤`));
        return;
      }
      // 收到事件才算連線正常，之後的中斷從最短的等待時間重新計算
      delay = RECONNECT_DELAY.min;
      // 重新連線時伺服器從 lastSeq 之後補送；保險起見仍略過重複的事件
      if (message.seq <= lastSeq) return;
      lastSeq = message.seq;
      finished ||= isFinal(message);
      try {
        onEvent(message);
      } catch (err) {
        // 單一訂閱者出錯不可中斷事件流（與 mock 相同）
        console.error('[HttpApiClient] subscriber threw while handling', message.type, err);
      }
    };
    ws.onclose = (e: CloseEvent) => {
      socket = null;
      if (stopped || finished || e.code === 1000) return;
      if (e.code === WS_NOT_FOUND) {
        fail(new Error(`找不到任務：${jobId}`));
        return;
      }
      connection.set('disconnected', `任務事件的連線中斷，${delay / 1000} 秒後重新連線`);
      retry = setTimeout(connect, delay);
      delay = Math.min(delay * 2, RECONNECT_DELAY.max);
    };
  };

  connect();
  return () => {
    stopped = true;
    if (retry) clearTimeout(retry);
    socket?.close();
  };
}
