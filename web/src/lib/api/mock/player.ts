import type { JobEvent } from '@/types/contract';
import type { TimedEvent } from './scenario';

export interface PlayerHandle { cancel(): void }

/**
 * 依 `at`（1× 毫秒）播放事件。每段等待時間 ÷ getSpeed()，所以播放中改速度會從下一段等待開始生效（不會改動已排定的等待）。
 * 第一批事件也用 setTimeout 送出，讓呼叫端有機會先訂閱。
 * 在事件處理函式內呼叫 cancel() 會立刻停止後續事件（包含同一時間點尚未送出的事件），也不會再呼叫 onDone。
 */
export function playTimeline(
  events: TimedEvent[],
  opts: { getSpeed: () => number; onEvent: (e: JobEvent) => void; onDone: () => void },
): PlayerHandle {
  let i = 0;
  let now = 0;
  let cancelled = false;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const step = () => {
    if (cancelled) return;
    while (!cancelled && i < events.length && events[i].at <= now) opts.onEvent(events[i++].event);
    if (cancelled) return;
    if (i >= events.length) {
      opts.onDone();
      return;
    }
    const next = events[i].at;
    timer = setTimeout(() => {
      now = next;
      step();
    }, (next - now) / opts.getSpeed());
  };

  timer = setTimeout(step, 0);
  return {
    cancel() {
      cancelled = true;
      if (timer) clearTimeout(timer);
    },
  };
}
