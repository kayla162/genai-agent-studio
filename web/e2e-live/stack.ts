import { execFileSync } from 'node:child_process';
import path from 'node:path';

/** live 模式 E2E 使用的獨立 docker compose 專案（見 repo 根目錄的 docker-compose.e2e.yml） */
export const E2E_URL = 'http://127.0.0.1:3200';
export const REPO_ROOT = path.resolve(__dirname, '..', '..');

export function compose(...args: string[]): void {
  execFileSync(
    'docker',
    ['compose', '-p', 'genai-agent-e2e', '-f', 'docker-compose.yml', '-f', 'docker-compose.e2e.yml', ...args],
    { cwd: REPO_ROOT, stdio: 'inherit' },
  );
}
