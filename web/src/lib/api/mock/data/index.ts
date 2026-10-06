import type { Brand } from '@/types/contract';
import { SELUNE, MISTY_ISLE } from './brands';

export { SELUNE, MISTY_ISLE } from './brands';
export { SAMPLE_PRODUCTS } from './products';

export const BRANDS: Brand[] = [SELUNE, MISTY_ISLE];

export function getBrandById(id: string): Brand {
  const brand = BRANDS.find((b) => b.id === id);
  if (!brand) throw new Error(`Unknown brand: ${id}`);
  return brand;
}
