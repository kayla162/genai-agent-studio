import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import { BinaryResponse, handle as handleRoute, UnknownRoute } from './handlers';

/** 請求本文的上限（位元組）：/render 帶 base64 的商品圖與 Logo */
export const MAX_BODY_BYTES = 30 * 1024 * 1024;

/** 請求本文超過 MAX_BODY_BYTES（伺服器回 400） */
export class BodyTooLarge extends Error {
  constructor() {
    super(`請求本文超過 ${MAX_BODY_BYTES / 1024 / 1024} MB 上限`);
  }
}

export interface ComposerOptions {
  /** 路由；預設為 handlers.ts 的 handle。可以回傳 Promise，也可以回傳 BinaryResponse */
  handle?: (path: string, body: unknown) => unknown;
  /** 已註冊的海報字型名稱，/health 回報 */
  fonts?: string[];
}

function sendJson(res: ServerResponse, status: number, body: unknown, headers: Record<string, string> = {}) {
  res.writeHead(status, { ...headers, 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}

function send(res: ServerResponse, result: unknown) {
  if (!(result instanceof BinaryResponse)) return sendJson(res, 200, result);
  res.writeHead(200, { ...result.headers, 'Content-Type': result.contentType, 'Content-Length': result.body.length });
  res.end(result.body);
}

/**
 * 讀完整個請求本文。超過上限時不再保留內容，但照樣讀到結束才回應：
 * 用戶端（例如 httpx）先送完本文才讀回應，中途關閉連線的話它只會看到連線中斷，看不到 400。
 */
function readBody(req: IncomingMessage): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const parts: Buffer[] = [];
    let size = 0;
    req.on('data', (part: Buffer) => {
      size += part.length;
      if (size <= MAX_BODY_BYTES) parts.push(part);
      else parts.length = 0;
    });
    req.on('end', () => (size > MAX_BODY_BYTES ? reject(new BodyTooLarge()) : resolve(Buffer.concat(parts))));
    req.on('error', reject);
  });
}

/**
 * composer 的 HTTP 介面：GET /health；其他都是 POST JSON。
 * handler 的回傳值轉成 JSON 送出，BinaryResponse 則直接送出位元組（例如 /render 的 PNG）。
 * 錯誤回 { error: { code, message } }：找不到路徑 404，其他 400。
 */
export function createComposerServer({ handle = handleRoute, fonts = [] }: ComposerOptions = {}): Server {
  return createServer(async (req, res) => {
    const path = new URL(req.url ?? '/', 'http://composer').pathname;
    if (req.method === 'GET' && path === '/health') return sendJson(res, 200, { status: 'ok', fonts });
    try {
      const raw = await readBody(req);
      send(res, await handle(path, JSON.parse(raw.toString('utf8') || 'null')));
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (err instanceof UnknownRoute) sendJson(res, 404, { error: { code: 'not_found', message } });
      else if (err instanceof BodyTooLarge) sendJson(res, 400, { error: { code: 'too_large', message } });
      else sendJson(res, 400, { error: { code: 'invalid', message } });
    }
  });
}
