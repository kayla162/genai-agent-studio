'use client';

import { useEffect, useState } from 'react';
import { LoaderCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { getApiClient } from '@/lib/api';
import { useAppStore } from '@/lib/store/app';
import { DemoConsole } from './demo-console';
import { SideNav } from './side-nav';
import { TopBar } from './top-bar';

const isReady = (s: { brands: unknown[]; options: unknown }) => s.brands.length > 0 && s.options !== null;

/** 重新讀取品牌與模型選項；失敗的原因由 store 的 loadError 記錄，這裡不需要處理 */
const loadAll = () => {
  const { loadBrands, loadOptions } = useAppStore.getState();
  return Promise.allSettled([loadBrands(), loadOptions()]);
};

export function AppShell({ children }: { children: React.ReactNode }) {
  const ready = useAppStore(isReady);
  const loadError = useAppStore((s) => s.loadError);
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    void useAppStore.persist.rehydrate();
    void loadAll();
    // 後端還沒啟動、重啟或暫時連不上時，初次載入會失敗；連線恢復（中斷後再連上）時自動重試一次
    const { connection } = getApiClient();
    let previous = connection.get().status;
    return connection.subscribe(({ status }) => {
      const recovered = previous === 'disconnected' && status === 'connected';
      previous = status;
      if (recovered && !isReady(useAppStore.getState())) void loadAll();
    });
  }, []);

  const retry = () => {
    setRetrying(true);
    void loadAll().finally(() => setRetrying(false));
  };

  return (
    <div className="min-h-screen">
      <TopBar />
      <div className="mx-auto flex max-w-[1680px] flex-col md:flex-row">
        <SideNav />
        <main className="min-w-0 flex-1 px-4 pt-5 pb-24 md:px-6">
          {ready ? (
            children
          ) : loadError ? (
            <div role="alert" className="grid h-64 place-content-center justify-items-center gap-3 text-center">
              <p className="text-sm text-destructive">{loadError}</p>
              <Button variant="outline" disabled={retrying} onClick={retry}>
                {retrying && <LoaderCircle className="animate-spin" />}
                重試
              </Button>
            </div>
          ) : (
            <div className="grid h-64 place-items-center text-muted-foreground">
              <LoaderCircle className="size-6 animate-spin" aria-label="載入中" />
            </div>
          )}
        </main>
      </div>
      <DemoConsole />
    </div>
  );
}
