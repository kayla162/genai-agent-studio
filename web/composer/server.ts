// composer：npm run composer（預設 3900 埠，可用 PORT 變更；字型資料夾可用 POSTER_FONTS_DIR 變更）
import type { AddressInfo } from 'node:net';
import { createComposerServer } from './app';
import { registerPosterFonts, resolveFontsDir } from './fonts';

function main() {
  // 啟動時就註冊海報字型；缺少或無法註冊時印出原因並以代碼 1 結束，不帶著畫不出正確海報的狀態啟動。
  // 不呼叫 process.exit：POSIX 上寫到 pipe 是非同步的，直接結束可能來不及寫出錯誤訊息。
  let fonts: string[];
  try {
    fonts = registerPosterFonts(resolveFontsDir()).map((f) => f.family);
  } catch (err) {
    console.error(`composer 無法啟動：${err instanceof Error ? err.message : String(err)}`);
    process.exitCode = 1;
    return;
  }

  const port = Number(process.env.PORT ?? 3900);
  const host = process.env.HOST ?? '127.0.0.1';
  const server = createComposerServer({ fonts });
  server.listen(port, host, () => {
    const { port: actual } = server.address() as AddressInfo;
    console.log(`composer listening on http://${host}:${actual}（字型：${fonts.join('、')}）`);
  });

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
}

main();
