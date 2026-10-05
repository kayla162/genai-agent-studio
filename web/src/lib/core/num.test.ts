import { describe, it, expect } from 'vitest';
import { round1, clamp, mulberry32, hashString } from './num';

describe('num utils', () => {
  it('round1 rounds to one decimal place', () => {
    expect(round1(1.26)).toBe(1.3);
    expect(round1(2.04)).toBe(2);
  });

  it('clamp keeps values within bounds', () => {
    expect(clamp(5, 0, 3)).toBe(3);
    expect(clamp(-1, 0, 3)).toBe(0);
    expect(clamp(2, 0, 3)).toBe(2);
  });

  it('mulberry32 is deterministic and returns values in [0, 1)', () => {
    const a = mulberry32(42);
    const b = mulberry32(42);
    const xs = Array.from({ length: 5 }, () => a());
    expect(Array.from({ length: 5 }, () => b())).toEqual(xs);
    for (const x of xs) {
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThan(1);
    }
  });

  it('hashString is stable and differs between inputs', () => {
    expect(hashString('job_1')).toBe(hashString('job_1'));
    expect(hashString('job_1')).not.toBe(hashString('job_2'));
    expect(hashString('job_1')).toBeGreaterThanOrEqual(0);
  });
});
