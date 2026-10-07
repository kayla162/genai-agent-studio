import { Suspense } from 'react';
import { AgentInspector } from '@/components/agent/agent-inspector';

export default function AgentPage() {
  // useSearchParams 需要 Suspense，否則 next build 會失敗
  return (
    <Suspense>
      <AgentInspector />
    </Suspense>
  );
}
