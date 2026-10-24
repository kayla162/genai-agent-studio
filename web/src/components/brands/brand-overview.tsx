import type { Brand, Palette } from '@/types/contract';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

const ROLE: Record<keyof Palette, string> = { primary: '主色', secondary: '輔助色', accent: '點綴色', ink: '文字' };
const pct = (v: number) => `${Math.round(v * 100)}%`;

/** 品牌 CI：色票、字型、版面規則、禁用詞與合規替代用語 */
export function BrandOverview({ brand }: { brand: Brand }) {
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>{brand.name}</CardTitle>
          <CardDescription>{brand.category}・品牌 CI {brand.ciVersion}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-4 gap-2">
            {(Object.keys(ROLE) as (keyof Palette)[]).map((role) => (
              <div key={role} className="overflow-hidden rounded-lg border text-xs">
                <div className="h-10 border-b" style={{ background: brand.palette[role] }} />
                <div className="px-2 py-1.5">
                  <p className="font-medium">{ROLE[role]}</p>
                  <p className="font-mono text-muted-foreground">{brand.palette[role].toUpperCase()}</p>
                </div>
              </div>
            ))}
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">標題字型</dt>
            <dd style={{ fontFamily: 'var(--font-serif)' }}>{brand.fonts.headline}</dd>
            <dt className="text-muted-foreground">內文字型</dt>
            <dd>{brand.fonts.body}</dd>
            <dt className="text-muted-foreground">主色色差上限</dt>
            <dd>ΔE2000 ≤ {brand.rules.maxDeltaE}</dd>
            <dt className="text-muted-foreground">留白比例</dt>
            <dd>≥ {pct(brand.rules.minWhitespace)}</dd>
            <dt className="text-muted-foreground">商品主體佔比</dt>
            <dd>{pct(brand.rules.productRatio[0])} – {pct(brand.rules.productRatio[1])}</dd>
          </dl>
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">背景風格</p>
            {brand.visualStyles.map((v) => (
              <div key={v.id} className="space-y-1">
                <p className="text-sm">
                  <span className="font-medium">{v.label}</span>
                  {v.tones.length > 0 && <span className="ml-2 text-xs text-muted-foreground">語氣 {v.tones.join('、')}</span>}
                </p>
                <p className="rounded-lg bg-muted px-3 py-2 font-mono text-xs leading-relaxed text-muted-foreground">{v.prompt}</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>禁用詞與合規替代用語</CardTitle>
          <CardDescription>
            規則型審查比對禁用詞；第一輪失敗時，Query Rewriting 依替代用語改寫文案。
            {brand.disclaimerPhrase && `效果宣稱需加註「${brand.disclaimerPhrase}」。`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="py-1.5 font-medium">禁用詞</th>
                <th className="py-1.5 font-medium">替代用語</th>
              </tr>
            </thead>
            <tbody>
              {brand.bannedWords.map((w) => (
                <tr key={w} className="border-b last:border-0">
                  <td className="py-1.5">
                    <Badge variant="outline" className="border-red-200 bg-red-50 text-red-700">{w}</Badge>
                  </td>
                  <td className="py-1.5">{brand.replacements[w] ? brand.replacements[w] : <span className="text-muted-foreground">刪除</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
