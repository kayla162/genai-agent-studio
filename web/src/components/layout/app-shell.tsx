'use client';

import { useEffect } from 'react';
import { LoaderCircle } from 'lucide-react';
import { useAppStore } from '@/lib/store/app';
import { DemoConsole } from './demo-console';
import { SideNav } from './side-nav';
import { TopBar } from './top-bar';

export function AppShell({ children }: { children: React.ReactNode }) {
  const ready = useAppStore((s) => s.brands.length > 0 && s.options !== null);

  useEffect(() => {
    void useAppStore.persist.rehydrate();
    void useAppStore.getState().loadBrands();
    void useAppStore.getState().loadOptions();
  }, []);

  return (
    <div className="min-h-screen">
      <TopBar />
      <div className="mx-auto flex max-w-[1680px] flex-col md:flex-row">
        <SideNav />
        <main className="min-w-0 flex-1 px-4 pt-5 pb-24 md:px-6">
          {ready ? (
            children
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
