// 產生 contracts/fixtures/（後端一致性測試的固定測資，不縮排以縮小檔案）：npm run fixtures
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { FIXTURES_DIR, goldenFixtures } from '../src/test/golden';

for (const [file, data] of Object.entries(goldenFixtures())) {
  const target = fileURLToPath(new URL(file, FIXTURES_DIR));
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, `${JSON.stringify(data)}\n`);
  console.log(`wrote contracts/fixtures/${file}`);
}
