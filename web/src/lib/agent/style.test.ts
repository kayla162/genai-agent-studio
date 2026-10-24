import { describe, expect, it } from 'vitest';
import type { Brand } from '@/types/contract';
import { SELUNE } from '@/lib/api/mock/data';
import { chooseVisualStyle, styleById } from './style';

const BRAND: Brand = {
  ...SELUNE,
  visualStyles: [
    { id: 'daily', label: '日常', prompt: 'soft linen', tones: ['gentle', 'minimal'] },
    { id: 'festive', label: '節慶', prompt: 'gold confetti', tones: ['playful'] },
    { id: 'plain', label: '素面', prompt: 'plain wall', tones: [] },
  ],
};

describe('chooseVisualStyle', () => {
  it('uses the chosen style', () => {
    expect(chooseVisualStyle(BRAND, 'gentle', 'plain')).toEqual({ style: BRAND.visualStyles[2], note: '背景風格：素面（指定）' });
  });

  it('picks the first style whose tones include the brief tone', () => {
    expect(chooseVisualStyle(BRAND, 'playful', null)).toEqual({ style: BRAND.visualStyles[1], note: '背景風格：節慶（自動：語氣 playful）' });
    expect(chooseVisualStyle(BRAND, 'minimal', null).style.id).toBe('daily');
  });

  it('falls back to the first style when no style matches the tone', () => {
    expect(chooseVisualStyle(BRAND, 'science', null)).toEqual({
      style: BRAND.visualStyles[0], note: '背景風格：日常（自動：沒有對應語氣 science 的風格，使用第一組）',
    });
  });

  it('rejects a style the brand does not have', () => {
    expect(() => chooseVisualStyle(BRAND, 'gentle', 'nope')).toThrow('沒有這個背景風格：nope');
    expect(() => styleById(BRAND, 'nope')).toThrow('沒有這個背景風格：nope');
    expect(styleById(BRAND, 'festive').prompt).toBe('gold confetti');
  });
});
