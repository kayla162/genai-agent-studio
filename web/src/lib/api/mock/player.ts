import type { JobEvent } from '@/types/contract';
import type { TimedEvent } from './scenario';

export interface PlayerHandle { cancel(): void }

/**
 * 依 `at`（1× 毫秒）播放事件。每段等待時間 ÷ getSpeed()，所以播放中改速度會立即生效。
 * 第一批事件也用 setTimeout 送出，讓呼叫端有機會先訂閱。
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
    while (i < events.length && events[i].at <= now) opts.onEvent(events[i++].event);
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
