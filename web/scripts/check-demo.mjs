// 部署作品集 Demo 前檢查靜態輸出（npm run build 之後執行 npm run demo:check；Plan 8）：
// - 以 mock 模式建置（NEXT_PUBLIC_API_MODE 不是 live：Demo 不連後端）
// - out/ 有首頁，以及與 public/ 相同的 _headers（Cloudflare Pages 的標頭）與 robots.txt
// 有問題時以中文列出並以結束碼 1 結束。
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const root = process.cwd();
const out = join(root, 'out');
const problems = [];

if ((process.env.NEXT_PUBLIC_API_MODE ?? 'mock') !== 'mock') {
  problems.push(`NEXT_PUBLIC_API_MODE=${process.env.NEXT_PUBLIC_API_MODE}：作品集 Demo 要以 mock 模式建置（不要設定這個變數）`);
}
if (!existsSync(join(out, 'index.html'))) {
  problems.push('找不到 out/index.html：請先執行 npm run build');
} else {
  for (const name of ['_headers', 'robots.txt']) {
    const built = join(out, name);
    if (!existsSync(built)) problems.push(`out/${name} 不存在（public/${name} 沒有複製到靜態輸出）`);
    else if (readFileSync(built, 'utf8') !== readFileSync(join(root, 'public', name), 'utf8')) {
      problems.push(`out/${name} 與 public/${name} 不同：請重新執行 npm run build`);
    }
  }
}

if (problems.length) {
  console.error(`作品集 Demo 的靜態輸出有 ${problems.length} 個問題：`);
  for (const p of problems) console.error(`- ${p}`);
  process.exit(1);
}
console.log('作品集 Demo 的靜態輸出可以部署：out/（mock 模式，含 _headers 與 robots.txt）');
