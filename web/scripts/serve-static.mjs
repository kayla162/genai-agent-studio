// 提供 next build 的靜態輸出（out/）：/studio → studio.html，找不到時回 404.html。Playwright 與本機預覽使用。
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { createServer } from 'node:http';
import path from 'node:path';

const ROOT = path.resolve(import.meta.dirname, '..', 'out');
const PORT = Number(process.argv[2] ?? 3100);
const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json', '.txt': 'text/plain; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png',
  '.ico': 'image/x-icon', '.woff2': 'font/woff2',
};

async function isFile(file) {
  try {
    return (await stat(file)).isFile();
  } catch {
    return false;
  }
}

/**
 * 在 Windows 上 next build 會把預先載入檔 __next.studio.__PAGE__.txt 寫成 __next.studio/__PAGE__.txt
 * （路徑分隔符沒有換成「.」）；Linux 建置（Docker、Cloudflare）沒有這個問題。
 */
function windowsSegmentFile(file) {
  const m = path.basename(file).match(/^__next\.(.+)\.txt$/);
  if (!m) return null;
  const [first, ...rest] = m[1].split('.');
  return rest.length ? path.join(path.dirname(file), `__next.${first}`, ...rest.slice(0, -1), `${rest.at(-1)}.txt`) : null;
}

async function resolveFile(url) {
  const pathname = decodeURIComponent(new URL(url, 'http://localhost').pathname);
  const base = path.join(ROOT, pathname);
  if (base !== ROOT && !base.startsWith(ROOT + path.sep)) return null;
  const candidates = [base, `${base}.html`, path.join(base, 'index.html'), windowsSegmentFile(base)];
  for (const file of candidates) if (file && (await isFile(file))) return file;
  return null;
}

createServer(async (req, res) => {
  const file = await resolveFile(req.url ?? '/');
  const target = file ?? path.join(ROOT, '404.html');
  res.writeHead(file ? 200 : 404, { 'Content-Type': TYPES[path.extname(target)] ?? 'application/octet-stream' });
  createReadStream(target).pipe(res);
}).listen(PORT, '127.0.0.1', () => console.log(`serving ${ROOT} on http://127.0.0.1:${PORT}`));
