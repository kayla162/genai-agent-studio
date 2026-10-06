import { describe, it, expect } from 'vitest';
import JSZip from 'jszip';
import { dateStamp, posterFileName, safeName, zipFileName } from './naming';
import { buildZip, uniqueName } from './zip';

const DATE = new Date(2026, 9, 6, 23, 59);

describe('naming', () => {
  it('builds 品牌_商品_通路_日期 file names', () => {
    expect(posterFileName({ brandName: 'SÉLUNE 晞月', productName: '極光玻尿酸修護精華 30ml', channel: 'IG 貼文', date: DATE }))
      .toBe('SÉLUNE晞月_極光玻尿酸修護精華30ml_IG貼文_20261006.png');
    expect(zipFileName({ brandName: '霧嶼咖啡 MISTY ISLE', productName: '單一產區冷萃咖啡 330ml', date: DATE }))
      .toBe('霧嶼咖啡MISTYISLE_單一產區冷萃咖啡330ml_20261006.zip');
  });

  it('removes characters that are not allowed in file names', () => {
    expect(safeName('a/b:c*d?"e"<f>|g')).toBe('abcdefg');
    expect(safeName(' / ')).toBe('未命名');
    expect(dateStamp(new Date(2026, 0, 2))).toBe('20260102');
  });
});

describe('zip', () => {
  it('uniqueName appends a counter before the extension', () => {
    const used = new Set<string>();
    expect(uniqueName('a.png', used)).toBe('a.png');
    expect(uniqueName('a.png', used)).toBe('a (2).png');
    expect(uniqueName('a.png', used)).toBe('a (3).png');
    expect(uniqueName('README', used)).toBe('README');
  });

  it('packs blobs and bytes into a zip that can be read back', async () => {
    const blob = await buildZip([
      { name: 'a.png', data: new Blob([new Uint8Array([1, 2, 3])], { type: 'image/png' }) },
      { name: 'a.png', data: new Uint8Array([4, 5]) },
    ]);
    expect(blob.type).toBe('application/zip');
    const zip = await JSZip.loadAsync(await blob.arrayBuffer());
    expect(Object.keys(zip.files).sort()).toEqual(['a (2).png', 'a.png']);
    expect([...(await zip.file('a.png')!.async('uint8array'))]).toEqual([1, 2, 3]);
  });
});
