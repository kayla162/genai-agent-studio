'use client';

import { useEffect, useState } from 'react';
import Image from 'next/image';
import { FolderOpen } from 'lucide-react';
import { toast } from 'sonner';
import type { Brand } from '@/types/contract';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import type { LocalPhoto } from '@/lib/server/local-products';
import { useProductsStore } from '@/lib/store/products';

type FolderState = { status: 'loading' } | { status: 'unavailable' } | { status: 'ready'; photos: LocalPhoto[] };

/** 開發模式：列出 assets/products/ 的照片，一鍵匯入成商品（檔名當商品名稱） */
export function LocalFolder({ brand }: { brand: Brand }) {
  const [state, setState] = useState<FolderState>({ status: 'loading' });
  const products = useProductsStore((s) => s.products);
  const save = useProductsStore((s) => s.save);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/local-products')
      .then((res) => (res.ok ? (res.json() as Promise<{ photos: LocalPhoto[] }>) : Promise.reject(new Error(String(res.status)))))
      .then((data) => !cancelled && setState({ status: 'ready', photos: data.photos }))
      .catch(() => !cancelled && setState({ status: 'unavailable' }));
    return () => {
      cancelled = true;
    };
  }, []);

  const imported = new Set(products.flatMap((p) => (p.photo.source === 'local' ? [p.photo.url] : [])));
  const importPhoto = async (photo: LocalPhoto) => {
    await save({
      brandId: brand.id, name: photo.name, features: [], price: { sale: 0, original: 0 },
      photo: { source: 'local', url: photo.url }, cutout: null,
    });
    toast.success(`已匯入「${photo.name}」`, { description: '請到卡片上補上價格與特徵。' });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FolderOpen className="size-4" />
          本機資料夾 assets/products/
        </CardTitle>
        <CardDescription>把自己的商品照放進 repo 根目錄的 assets/products/（不會上傳 GitHub），開發模式下可直接匯入。</CardDescription>
      </CardHeader>
      <CardContent>
        {state.status === 'loading' && <p className="text-sm text-muted-foreground">讀取中…</p>}
        {state.status === 'unavailable' && <p className="text-sm text-muted-foreground">只有 `npm run dev` 開發模式可以讀取本機資料夾。</p>}
        {state.status === 'ready' && state.photos.length === 0 && (
          <p className="text-sm text-muted-foreground">資料夾目前沒有圖片（支援 .png、.jpg、.webp）。</p>
        )}
        {state.status === 'ready' && state.photos.length > 0 && (
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
            {state.photos.map((photo) => (
              <li key={photo.file} className="space-y-1.5">
                <div className="relative aspect-square overflow-hidden rounded-lg border bg-muted">
                  <Image src={photo.url} alt={photo.name} fill unoptimized sizes="160px" className="object-contain" />
                </div>
                <p className="truncate text-xs" title={photo.file}>{photo.name}</p>
                <Button size="xs" variant="outline" className="w-full" disabled={imported.has(photo.url)} onClick={() => void importPhoto(photo)}>
                  {imported.has(photo.url) ? '已匯入' : '匯入'}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
