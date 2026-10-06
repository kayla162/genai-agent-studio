import type { Metadata } from 'next';
import '@fontsource-variable/noto-sans-tc';
import '@fontsource-variable/noto-serif-tc';
import './globals.css';
import { AppShell } from '@/components/layout/app-shell';
import { Toaster } from '@/components/ui/sonner';
import { TooltipProvider } from '@/components/ui/tooltip';

export const metadata: Metadata = {
  title: '虛實整合 GenAI Agent',
  description: '保留真實商品照，AI 生成背景、排版引擎疊字、RAG 品牌合規審查，一次輸出多通路尺寸。',
};

export default function RootLayout({ children }: LayoutProps<'/'>) {
  return (
    <html lang="zh-Hant">
      <body>
        <TooltipProvider>
          <AppShell>{children}</AppShell>
        </TooltipProvider>
        <Toaster theme="light" position="top-center" richColors />
      </body>
    </html>
  );
}
