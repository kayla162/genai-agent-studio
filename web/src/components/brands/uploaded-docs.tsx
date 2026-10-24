'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import { FileText, Trash2 } from 'lucide-react';
import type { Brand } from '@/types/contract';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { getApiClient } from '@/lib/api';
import { uploadedDocuments, type UploadedDocument } from '@/lib/rag/documents';
import { useAppStore } from '@/lib/store/app';

/** 已上傳的品牌手冊：列出檔名與切塊數，可以刪除（品牌設定檔的規範不在這裡） */
export function UploadedDocs({ brand }: { brand: Brand }) {
  const loadBrands = useAppStore((s) => s.loadBrands);
  const [deleting, setDeleting] = useState<UploadedDocument | null>(null);
  const [busy, setBusy] = useState(false);
  const docs = uploadedDocuments(brand.guidelineChunks);

  const remove = async (doc: UploadedDocument) => {
    setBusy(true);
    try {
      await getApiClient().deleteBrandDocument(brand.id, doc.source);
      await loadBrands();
      toast.success(`已刪除手冊：${doc.source}`, { description: `${doc.chunks} 個切塊不會再被檢索。` });
      setDeleting(null);
    } catch (err) {
      toast.error('無法刪除手冊', { description: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>已上傳的手冊</CardTitle>
        <CardDescription>刪除後，這份手冊的切塊不再被檢索；品牌設定檔的規範與歷史案例不受影響。</CardDescription>
      </CardHeader>
      <CardContent>
        {docs.length === 0 ? (
          <p className="text-sm text-muted-foreground">還沒有上傳手冊。</p>
        ) : (
          <ul className="divide-y rounded-lg border">
            {docs.map((d) => (
              <li key={d.source} className="flex items-center gap-2 px-3 py-2 text-sm">
                <FileText className="size-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate" title={d.source}>{d.source}</span>
                <span className="shrink-0 text-xs text-muted-foreground">{d.chunks} 個切塊</span>
                <Button size="icon-sm" variant="ghost" className="text-muted-foreground hover:text-destructive"
                  aria-label={`刪除 ${d.source}`} onClick={() => setDeleting(d)}>
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
      <Dialog open={deleting !== null} onOpenChange={(o) => !o && !busy && setDeleting(null)}>
        {deleting && (
          <DialogContent className="sm:max-w-sm">
            <DialogHeader>
              <DialogTitle>刪除「{deleting.source}」？</DialogTitle>
              <DialogDescription>這份手冊的 {deleting.chunks} 個切塊會從知識庫移除，之後的任務不再檢索；要恢復請重新上傳原檔。</DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" disabled={busy} onClick={() => setDeleting(null)}>取消</Button>
              <Button variant="destructive" disabled={busy} onClick={() => void remove(deleting)}>刪除</Button>
            </DialogFooter>
          </DialogContent>
        )}
      </Dialog>
    </Card>
  );
}
