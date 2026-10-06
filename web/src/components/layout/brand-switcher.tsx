'use client';

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useAppStore } from '@/lib/store/app';

export function BrandSwitcher() {
  const brands = useAppStore((s) => s.brands);
  const brandId = useAppStore((s) => s.brandId);
  const setBrandId = useAppStore((s) => s.setBrandId);
  return (
    <Select value={brands.length ? brandId : ''} onValueChange={setBrandId} disabled={!brands.length}>
      <SelectTrigger size="sm" className="w-36 bg-card sm:w-52" aria-label="切換品牌">
        <SelectValue placeholder="載入品牌…" />
      </SelectTrigger>
      <SelectContent align="end">
        {brands.map((b) => (
          <SelectItem key={b.id} value={b.id}>
            <span className="size-2.5 rounded-full" style={{ background: b.palette.primary }} />
            {b.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
