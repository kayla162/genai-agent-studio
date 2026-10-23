import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { GUARD_CODES, type GuardIssue } from '@/types/agent';
import { FIXTURES_DIR, goldenFixtures } from './golden';

describe('contracts/fixtures', () => {
  it('matches what the TypeScript code produces (run `npm run fixtures` after changing it)', () => {
    const fixtures = goldenFixtures();
    expect(Object.keys(fixtures).sort()).toEqual([
      'agent.json', 'brands.json', 'chunks.json', 'comfy.json', 'rng.json', 'stats.json',
      'timelines/misty-first-pass.json', 'timelines/selune-needs-review.json', 'timelines/selune-retry.json',
    ]);
    for (const [file, data] of Object.entries(fixtures)) {
      const onDisk: unknown = JSON.parse(readFileSync(new URL(file, FIXTURES_DIR), 'utf8'));
      expect(onDisk, file).toEqual(JSON.parse(JSON.stringify(data)));
    }
  });

  it('covers every guard issue code in the agent examples', () => {
    const { guardIssues } = goldenFixtures()['agent.json'] as { guardIssues: GuardIssue[] };
    expect([...new Set(guardIssues.map((i) => i.code))].sort()).toEqual([...GUARD_CODES].sort());
  });

  it('covers a retried job, a job that needs review and a job that passes the first round', () => {
    const fixtures = goldenFixtures();
    const lastStatus = (file: string) =>
      (fixtures[file] as { events: { event: { type: string } }[] }).events.filter((x) => x.event.type === 'job.status').at(-1)!.event;
    expect(lastStatus('timelines/selune-retry.json')).toMatchObject({ stage: 'done', round: 2 });
    expect(lastStatus('timelines/selune-needs-review.json')).toMatchObject({ stage: 'needs_review', round: 2 });
    expect(lastStatus('timelines/misty-first-pass.json')).toMatchObject({ stage: 'done', round: 1 });
  });
});
