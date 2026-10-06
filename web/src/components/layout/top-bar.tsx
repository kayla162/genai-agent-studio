'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { LayoutGrid, Network, Sparkles } from 'lucide-react';
import { API_MODE } from '@/lib/api';
import { cn } from '@/lib/utils';
import { BrandSwitcher } from './brand-switcher';
import { ConnectionBadge } from './connection-badge';
import { modeOf } from './nav';

const MODES = [
  { mode: 'workbench', href: '/studio', label: '工作台', icon: LayoutGrid },
  { mode: 'agent', href: '/agent', label: 'Agent 透視', icon: Network },
] as const;

export function TopBar() {
  const pathname = usePathname();
  const current = modeOf(pathname);
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-card/90 px-3 backdrop-blur sm:gap-3 md:px-6">
      <Link href="/studio" className="flex items-center gap-2.5">
        <span className="grid size-8 place-items-center rounded-[10px] bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500 text-white shadow-md shadow-indigo-500/30">
          <Sparkles className="size-4" />
        </span>
        <span className="hidden leading-tight lg:block">
          <span className="block text-sm font-bold">虛實整合 GenAI Agent</span>
          <span className="block text-xs text-muted-foreground">真實商品照 × AI 背景 × 品牌合規</span>
        </span>
      </Link>

      <nav className="flex rounded-[10px] border bg-muted p-0.5 sm:ml-2" aria-label="模式切換">
        {MODES.map(({ mode, href, label, icon: Icon }) => (
          <Link
            key={mode}
            href={href}
            aria-current={current === mode ? 'page' : undefined}
            className={cn(
              'flex items-center gap-1.5 rounded-lg px-3 py-1 text-sm text-muted-foreground transition-colors',
              current === mode && 'bg-card font-semibold text-primary shadow-sm',
            )}
          >
            <Icon className="size-4" />
            <span className="hidden sm:inline">{label}</span>
          </Link>
        ))}
      </nav>

      <div className="ml-auto flex items-center gap-2">
        <BrandSwitcher />
        {API_MODE === 'mock' && (
          <span className="hidden h-7 items-center rounded-full border border-amber-200 bg-amber-50 px-3 text-xs font-medium text-amber-800 md:inline-flex">
            Demo 模式
          </span>
        )}
        <ConnectionBadge />
      </div>
    </header>
  );
}
