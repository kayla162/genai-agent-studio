'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import { isActive, modeOf, NAV } from './nav';

/** 桌面版是左側選單；手機版是頂列下方可橫向捲動的分頁 */
export function SideNav() {
  const pathname = usePathname();
  const items = NAV[modeOf(pathname)];
  return (
    <nav
      aria-label="頁面"
      className="flex gap-1 overflow-x-auto border-b bg-card px-3 py-2 md:sticky md:top-14 md:h-[calc(100vh-3.5rem)] md:w-52 md:shrink-0 md:flex-col md:border-r md:border-b-0 md:px-3 md:py-4"
    >
      {items.map(({ href, label, icon: Icon }) => {
        const active = isActive(pathname, href);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-sidebar-foreground transition-colors hover:bg-muted',
              active && 'bg-sidebar-accent font-semibold text-sidebar-accent-foreground hover:bg-sidebar-accent',
            )}
          >
            <Icon className="size-4" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
