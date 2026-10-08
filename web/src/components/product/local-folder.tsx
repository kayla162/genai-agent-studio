'use client';

import { useEffect, useState } from 'react';
import Image from 'next/image';
import { FolderOpen } from 'lucide-react';
import { toast } from 'sonner';
import type { Brand, LocalPhoto } from '@/types/contract';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { getApiClient } from '@/lib/api';
import { useProductsStore } from '@/lib/store/products';

type FolderState = { status: 'loading' } | { status: 'unavailable' } | { status: 'ready'; photos: LocalPhoto[] };

/** live 模式：列出 assets/products/ 的照片，一鍵匯入成商品（檔名當商品名稱） */
export function LocalFolder({ brand }: { brand: Brand }) {
  const [state, setState] = useState<FolderState>({ status: 'loading' });
  const [importing, setImporting] = useState<string | null>(null);
  const products = useProductsStore((s) => s.products);
  const load = useProductsStore((s) => s.load);

  useEffect(() => {
    let cancelled = false;
    getApiClient().listLocalPhotos().then(
      (photos) => !cancelled && setState(photos ? { status: 'ready', photos } : { status: 'unavailable' }),
      () => !cancelled && setState({ status: 'unavailable' }),
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const imported = new Set(products.flatMap((p) => (p.photo.source === 'local' ? [p.photo.url] : [])));
  const importPhoto = async (photo: LocalPhoto) => {
    setImporting(photo.file);
    try {
      await getApiClient().importLocalPhoto(photo.file, brand.id);
      await load(brand.id);
      toast.success(`已匯入「${photo.name}」`, { description: '請到卡片上補上價格與特徵。' });
    } catch (err) {
      toast.error('匯入失敗', { description: err instanceof Error ? err.message : String(err) });
    } finally {
      setImporting(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FolderOpen className="size-4" />
          本機資料夾 assets/products/
        </CardTitle>
        <CardDescription>把自己的商品照放進 repo 根目錄的 assets/products/（不會上傳 GitHub），live 模式下可直接匯入。</CardDescription>
      </CardHeader>
      <CardContent>
        {state.status === 'loading' && <p className="text-sm text-muted-foreground">讀取中…</p>}
        {state.status === 'unavailable' && <p className="text-sm text-muted-foreground">只有 live 模式可以讀取本機資料夾。</p>}
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
                <Button
                  size="xs"
                  variant="outline"
                  className="w-full"
                  disabled={imported.has(photo.url) || importing !== null}
                  onClick={() => void importPhoto(photo)}
                >
                  {imported.has(photo.url) ? '已匯入' : importing === photo.file ? '匯入中…' : '匯入'}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
