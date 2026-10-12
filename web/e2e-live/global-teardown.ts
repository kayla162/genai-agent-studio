import { compose } from './stack';

/** 移除 E2E 的容器與資料（映像檔保留，下次建置較快） */
export default function globalTeardown(): void {
  compose('down', '-v');
}
