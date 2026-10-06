import type { Product } from '@/types/contract';

export const SAMPLE_PRODUCTS: Product[] = [
  {
    id: 'prod_selune_serum', brandId: 'selune', name: '極光玻尿酸修護精華 30ml',
    features: ['5重玻尿酸', '神經醯胺', '無香精', '敏感肌適用'],
    price: { sale: 1280, original: 1680 }, photo: { source: 'sample', art: 'serum' },
    createdAt: '2026-10-01T09:00:00.000Z',
  },
  {
    id: 'prod_misty_coldbrew', brandId: 'misty-isle', name: '單一產區冷萃咖啡 330ml',
    features: ['18小時冷萃', '單一產區', '無添加糖', '低酸順口'],
    price: { sale: 120, original: 150 }, photo: { source: 'sample', art: 'coldbrew' },
    createdAt: '2026-10-01T09:00:00.000Z',
  },
];
