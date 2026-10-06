import { describe, expect, it } from 'vitest';
import { getBrandById, SAMPLE_PRODUCTS } from './data';
import { SAMPLE_BRIEFS, sampleJobs } from './samples';

const NOW = new Date(2026, 9, 5, 9, 30);

describe('sampleJobs', () => {
  it('is deterministic for the same seed', () => {
    expect(sampleJobs(8, NOW)).toEqual(sampleJobs(8, NOW));
  });

  it('alternates brands with their sample product and parsed brief', () => {
    const jobs = sampleJobs(6, NOW);
    expect(jobs.map((j) => j.input.brandId)).toEqual(['selune', 'misty-isle', 'selune', 'misty-isle', 'selune', 'misty-isle']);
    for (const { input } of jobs) {
      const product = SAMPLE_PRODUCTS.find((p) => p.id === input.productId)!;
      expect(product.brandId).toBe(input.brandId);
      expect(SAMPLE_BRIEFS[input.brandId]).toContain(input.brief);
      expect(input.parsedBrief.productName).toBe(product.name);
      expect(getBrandById(input.brandId).id).toBe(input.brandId);
    }
  });

  it('picks at least one template, in the standard order, without duplicates', () => {
    for (const { input } of sampleJobs(20, NOW)) {
      expect(input.templateIds.length).toBeGreaterThan(0);
      expect(new Set(input.templateIds).size).toBe(input.templateIds.length);
    }
  });

  it('gives both brands retries, first-round passes and forced failures', () => {
    const jobs = sampleJobs(12, NOW);
    for (const brandId of ['selune', 'misty-isle']) {
      const demos = jobs.filter((j) => j.input.brandId === brandId).map((j) => j.demo);
      expect(demos.filter((d) => d.forceAllFail)).toHaveLength(1);
      expect(demos.filter((d) => !d.firstRoundFail)).toHaveLength(2);
      expect(demos.filter((d) => d.firstRoundFail && !d.forceAllFail)).toHaveLength(3);
    }
    expect(jobs.every((j) => j.demo.speed === 1)).toBe(true);
  });

  it('spreads creation times over the past, oldest first', () => {
    const times = sampleJobs(10, NOW).map((j) => j.createdAt.getTime());
    expect(times).toEqual([...times].sort((a, b) => a - b));
    expect(new Set(times).size).toBe(10);
    expect(times.at(-1)!).toBeLessThan(NOW.getTime());
  });
});
