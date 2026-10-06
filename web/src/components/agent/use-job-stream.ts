'use client';

import { useEffect, useState } from 'react';
import type { JobMessage } from '@/types/contract';
import { getApiClient } from '@/lib/api';
import { emptyJobView, reduceJob, type JobView } from '@/lib/jobs/view';

export interface JobStream {
  /** 原始訊息（含 seq、ts），事件串流與耗時使用 */
  messages: JobMessage[];
  view: JobView;
  error: string | null;
}

/** 訂閱任務事件：保留原始訊息，同時累積成 JobView。換任務時請以 key 重新掛載元件。 */
export function useJobStream(jobId: string): JobStream {
  const [state, setState] = useState<JobStream>(() => ({ messages: [], view: emptyJobView(jobId), error: null }));
  useEffect(
    () =>
      getApiClient().subscribe(
        jobId,
        (m) =>
          setState((s) =>
            // 重新訂閱時會重播已收到的事件（開發模式的 StrictMode 會執行兩次 effect）：依序號略過重複的
            m.seq <= (s.messages.at(-1)?.seq ?? 0) ? s : { ...s, messages: [...s.messages, m], view: reduceJob(s.view, m) },
          ),
        (err) => setState((s) => ({ ...s, error: err.message })),
      ),
    [jobId],
  );
  return state;
}
