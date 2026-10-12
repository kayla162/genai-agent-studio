import { compose } from './stack';

/** 建置並啟動整套服務（外部服務用模擬版），等到所有健康檢查通過 */
export default function globalSetup(): void {
  compose('up', '-d', '--build', '--wait');
}
