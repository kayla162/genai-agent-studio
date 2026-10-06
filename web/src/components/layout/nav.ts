import type { LucideIcon } from 'lucide-react';
import { BookOpen, ChartColumn, Clock, ListOrdered, Network, Package, WandSparkles } from 'lucide-react';

export type AppMode = 'workbench' | 'agent';
export interface NavItem { href: string; label: string; icon: LucideIcon }

export const NAV: Record<AppMode, NavItem[]> = {
  workbench: [
    { href: '/studio', label: '新任務', icon: WandSparkles },
    { href: '/products', label: '商品庫', icon: Package },
    { href: '/queue', label: '批次佇列', icon: ListOrdered },
    { href: '/history', label: '歷史紀錄', icon: Clock },
    { href: '/brands', label: '品牌知識庫', icon: BookOpen },
  ],
  agent: [
    { href: '/agent', label: '任務透視', icon: Network },
    { href: '/dashboard', label: '成效儀表板', icon: ChartColumn },
  ],
};

export const modeOf = (pathname: string): AppMode =>
  NAV.agent.some((item) => pathname.startsWith(item.href)) ? 'agent' : 'workbench';

export const isActive = (pathname: string, href: string) => pathname === href || pathname.startsWith(`${href}/`);
