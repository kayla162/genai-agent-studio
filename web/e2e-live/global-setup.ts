import { compose } from './stack';

/**
 * 建置並啟動整套服務（外部服務用模擬版），等到所有健康檢查通過。
 * 先移除上次中斷（沒有執行 globalTeardown）留下的容器與資料，每次都從空的資料庫開始。
 */
export default function globalSetup(): void {
  compose('down', '-v', '--remove-orphans');
  compose('up', '-d', '--build', '--wait');
}
