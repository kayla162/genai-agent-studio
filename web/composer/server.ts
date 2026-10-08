// composer：npm run composer（預設 3900 埠，可用 PORT 變更）
import { createComposerServer } from './app';

const port = Number(process.env.PORT ?? 3900);
const host = process.env.HOST ?? '127.0.0.1';
createComposerServer().listen(port, host, () => console.log(`composer listening on http://${host}:${port}`));
