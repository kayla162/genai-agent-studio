import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { listLocalPhotos, localPhotoUrl, resolveLocalPhoto } from './local-products';

let dir = '';

beforeAll(async () => {
  dir = await mkdtemp(path.join(tmpdir(), 'local-products-'));
  await writeFile(path.join(dir, 'night_mask-50ml.PNG'), new Uint8Array([1, 2, 3]));
  await writeFile(path.join(dir, 'a-serum.jpg'), new Uint8Array([4]));
  await writeFile(path.join(dir, '.gitkeep'), '');
  await writeFile(path.join(dir, 'notes.txt'), 'x');
  await mkdir(path.join(dir, 'folder.png'));
});
afterAll(() => rm(dir, { recursive: true, force: true }));

describe('listLocalPhotos', () => {
  it('lists image files only, sorted, with names derived from the file name', async () => {
    expect(await listLocalPhotos(dir)).toEqual([
      { file: 'a-serum.jpg', name: 'a serum', url: '/api/local-products/a-serum.jpg', size: 1 },
      { file: 'night_mask-50ml.PNG', name: 'night mask 50ml', url: '/api/local-products/night_mask-50ml.PNG', size: 3 },
    ]);
  });

  it('returns an empty list when the folder does not exist', async () => {
    expect(await listLocalPhotos(path.join(dir, 'missing'))).toEqual([]);
  });

  it('encodes file names in URLs', () => {
    expect(localPhotoUrl('晚安 面膜.png')).toBe('/api/local-products/%E6%99%9A%E5%AE%89%20%E9%9D%A2%E8%86%9C.png');
  });
});

describe('resolveLocalPhoto', () => {
  it('resolves image files inside the folder', () => {
    expect(resolveLocalPhoto(dir, 'a-serum.jpg')).toEqual({ path: path.join(dir, 'a-serum.jpg'), type: 'image/jpeg' });
  });

  it('rejects traversal, sub-paths, hidden and non-image files', () => {
    for (const bad of ['../secret.png', '..\\secret.png', 'sub/x.png', '.hidden.png', 'notes.txt', '']) {
      expect(resolveLocalPhoto(dir, bad), bad).toBeNull();
    }
  });
});
