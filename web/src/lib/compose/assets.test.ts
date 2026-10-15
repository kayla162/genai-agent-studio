import { describe, it, expect } from 'vitest';
import type { Product } from '@/types/contract';
import { SAMPLE_PRODUCTS, SELUNE } from '@/lib/api/mock/data';
import { fontStacks, productImage } from './assets';

const upload: Product = {
  ...SAMPLE_PRODUCTS[0], id: 'p_up', photo: { source: 'upload', url: 'data:image/png;base64,AQID' }, cutout: null,
};

describe('productImage', () => {
  it('uses the SVG art for sample products', () => {
    const img = productImage(SAMPLE_PRODUCTS[0], SELUNE);
    expect(img.blend).toBe('normal');
    expect(img.src.startsWith('data:image/svg+xml')).toBe(true);
    expect(decodeURIComponent(img.src)).toContain('SÉLUNE');
  });

  it('multiplies an uploaded photo until a real cutout exists', () => {
    expect(productImage(upload, SELUNE)).toEqual({ src: 'data:image/png;base64,AQID', blend: 'multiply' });
    expect(productImage({ ...upload, cutout: { model: 'BiRefNet-general', status: 'done', url: null, error: null } }, SELUNE).blend).toBe('multiply');
    expect(productImage({ ...upload, cutout: { model: 'BiRefNet-general', status: 'done', url: '/cutout.png', error: null } }, SELUNE))
      .toEqual({ src: '/cutout.png', blend: 'normal' });
  });
});

describe('fontStacks', () => {
  it('prefers the self-hosted variable fonts', () => {
    expect(fontStacks(SELUNE).headline.startsWith('"Noto Serif TC Variable", "Noto Serif TC"')).toBe(true);
    expect(fontStacks(SELUNE).body).toContain('sans-serif');
  });
});
