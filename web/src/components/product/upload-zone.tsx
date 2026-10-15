'use client';

import { useRef, useState } from 'react';
import { ImagePlus, LoaderCircle } from 'lucide-react';
import { toast } from 'sonner';
import type { Brand } from '@/types/contract';
import { Button } from '@/components/ui/button';
import { API_MODE, getApiClient } from '@/lib/api';
import { downscaleImage, nameFromFile } from '@/lib/image/downscale';
import { useProductsStore } from '@/lib/store/products';
import { cn } from '@/lib/utils';

const STORED_AT = API_MODE === 'live' ? '照片已上傳到後端（data/uploads/）。' : '照片存在這台電腦的瀏覽器（IndexedDB）。';

/** 上傳／拖放商品照：縮圖後交給 ApiClient 保存，再建立商品（價格與特徵之後再補） */
export function UploadZone({ brand }: { brand: Brand }) {
  const input = useRef<HTMLInputElement>(null);
  const save = useProductsStore((s) => s.save);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);

  const upload = async (files: File[]) => {
    const images = files.filter((f) => f.type.startsWith('image/'));
    if (!images.length) {
      toast.error('只能上傳圖片檔');
      return;
    }
    setBusy(true);
    try {
      const api = getApiClient();
      for (const file of images) {
        const photo = await api.uploadProductPhoto(await downscaleImage(file));
        await save({ brandId: brand.id, name: nameFromFile(file.name), features: [], price: { sale: 0, original: 0 }, photo, cutout: null });
      }
      toast.success(`已新增 ${images.length} 個商品`, { description: `${STORED_AT}正在背景去背，完成後會自動更新；請補上價格與特徵。` });
    } catch (err) {
      toast.error('上傳失敗', { description: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        void upload([...e.dataTransfer.files]);
      }}
      className={cn(
        'flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed bg-card px-6 py-8 text-center transition-colors',
        over && 'border-primary bg-secondary',
      )}
    >
      {busy ? <LoaderCircle className="size-7 animate-spin text-primary" /> : <ImagePlus className="size-7 text-muted-foreground" />}
      <p className="font-medium">拖放商品照到這裡，或</p>
      <Button size="sm" disabled={busy} onClick={() => input.current?.click()}>
        選擇照片
      </Button>
      <p className="text-xs text-muted-foreground">白底商品照效果最好；最長邊會縮到 1600px。</p>
      <input
        ref={input}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        multiple
        hidden
        onChange={(e) => {
          void upload([...(e.target.files ?? [])]);
          e.target.value = '';
        }}
      />
    </div>
  );
}
