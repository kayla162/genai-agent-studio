import { Suspense } from 'react';
import { AgentPreview } from '@/components/agent/agent-preview';

export default function AgentPage() {
  // useSearchParams 需要 Suspense，否則 next build 會失敗
  return (
    <Suspense>
      <AgentPreview />
    </Suspense>
  );
}
