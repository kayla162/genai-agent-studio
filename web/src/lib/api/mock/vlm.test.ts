import { describe, it, expect } from 'vitest';
import { cleanSpec } from '@/test/fixtures';
import { SELUNE } from './data';
import { mockVlmChecks } from './vlm';

const exaggeration = (spec: ReturnType<typeof cleanSpec>) =>
  mockVlmChecks(spec, SELUNE, 0).find((c) => c.id === 'vlm_exaggeration')!;

describe('mockVlmChecks vlm_exaggeration', () => {
  it('points at the copy block that contains the banned word', () => {
    const spec = cleanSpec();
    spec.copy.features = ['根治暗沉'];
    expect(exaggeration(spec)).toMatchObject({ status: 'fail', target: 'features' });
  });

  it('passes with no target when the copy is clean', () => {
    expect(exaggeration(cleanSpec())).toMatchObject({ status: 'pass', target: null });
  });
});
