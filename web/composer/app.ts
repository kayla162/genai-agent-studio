import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import { handle, UnknownRoute } from './handlers';

function send(res: ServerResponse, status: number, body: unknown) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}

async function readJson(req: IncomingMessage): Promise<unknown> {
  const parts: Buffer[] = [];
  for await (const part of req) parts.push(part as Buffer);
  return JSON.parse(Buffer.concat(parts).toString('utf8') || 'null');
}

/** composer 的 HTTP 介面：GET /health；其他都是 POST JSON → JSON。錯誤回 { error: { code, message } }。 */
export function createComposerServer(): Server {
  return createServer(async (req, res) => {
    const path = new URL(req.url ?? '/', 'http://composer').pathname;
    if (req.method === 'GET' && path === '/health') return send(res, 200, { status: 'ok' });
    try {
      const body = await readJson(req);
      send(res, 200, handle(path, body));
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (err instanceof UnknownRoute) send(res, 404, { error: { code: 'not_found', message } });
      else send(res, 400, { error: { code: 'invalid', message } });
    }
  });
}
