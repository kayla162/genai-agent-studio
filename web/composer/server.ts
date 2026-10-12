// composer：npm run composer（預設 3900 埠，可用 PORT 變更）
import { createComposerServer } from './app';

const port = Number(process.env.PORT ?? 3900);
const host = process.env.HOST ?? '127.0.0.1';
const server = createComposerServer();
server.listen(port, host, () => console.log(`composer listening on http://${host}:${port}`));

/**
 * 在容器裡 node 是 PID 1，SIGTERM 沒有預設動作，不處理的話 docker stop 要等到逾時再 SIGKILL（結束代碼 137）。
 * 收到訊號就關閉伺服器並以 0 結束；還有連線沒關的話，3 秒後照樣結束。
 */
function shutdown() {
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 3_000).unref();
}
process.once('SIGTERM', shutdown);
process.once('SIGINT', shutdown);
