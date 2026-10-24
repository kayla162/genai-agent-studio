import { describe, expect, it } from 'vitest';
import { colorWords, paletteWords } from './color-words';

describe('colorWords', () => {
  it('names the demo brand colours in words an image model understands', () => {
    // SÉLUNE
    expect(colorWords('#B76E79')).toBe('dusty rose');
    expect(colorWords('#F6EFE9')).toBe('warm off-white');
    expect(colorWords('#C9A96E')).toBe('muted gold');
    // misty-isle
    expect(colorWords('#2F4A44')).toBe('deep muted teal green');
    expect(colorWords('#EEF0EC')).toBe('off-white');
    // Kayla
    expect(colorWords('#B8A5D6')).toBe('soft lavender');
  });

  it('names neutrals by lightness and vivid colours plainly', () => {
    expect(colorWords('#FFFFFF')).toBe('off-white');
    expect(colorWords('#808080')).toBe('gray');
    expect(colorWords('#1A1A1A')).toBe('charcoal');
    expect(colorWords('#E02020')).toBe('red');
    expect(colorWords('#2050E0')).toBe('blue');
  });

  it('describes a brand palette without hex codes', () => {
    const words = paletteWords({ primary: '#B76E79', secondary: '#F6EFE9', accent: '#C9A96E', ink: '#3A3335' });
    expect(words).toBe('dusty rose and warm off-white color palette with muted gold accents');
    expect(words).not.toMatch(/#/);
  });
});
