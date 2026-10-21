import type { BrandDocument } from '@/types/contract';

/**
 * 切塊一致性的範例（contracts/fixtures/chunks.json）：涵蓋 lib/rag/chunk.ts 的每個分支，
 * 後端 app/rag/chunking.py 必須切出完全相同的結果。特殊字元以跳脫序列寫出，方便看出測的是什麼。
 */
export interface ChunkSample extends BrandDocument {
  brandId: string;
  maxChars?: number;
}

export const CHUNK_SAMPLES: ChunkSample[] = [
  // Markdown：各級標題、同一個區塊中的標題、三種條列符號（有無句尾標點）、不算標題或條列的行
  {
    brandId: 'selune', name: 'ci_update_2026.md',
    text: [
      '# 色彩更新',
      '主色維持 #B76E79，新增輔助色「霧粉」#E8C7C8。',
      '',
      '## Logo 規範',
      '- Logo 淨空區至少 0.5 倍 Logo 高度',
      '* 深色背景使用反白 Logo。',
      '• 標誌不可變形！',
      '   - 縮排的條列；',
      '- 含有行分隔符號 的行不是條列',
      '-沒有空白的破折號不是條列',
      '####### 七個井號不是標題',
      '#沒有空白也不是標題',
      '',
      '週年慶素材的平均 CTR 為 4.2%',
      '###### 第六級標題',
      '標題下方的段落。',
      '#　全形空白後的標題   ',
      '# 含有行分隔符號 的行不是標題',
      '最後一段沒有句號',
    ].join('\n'),
  },
  // 合併換行：漢字（含擴充區）之間的空白拿掉，英文、標點、假名旁的保留；空白字元依 JavaScript 的定義
  {
    brandId: 'selune', name: 'wrapped.txt',
    text: [
      '標題靠左',
      '對齊網格。',
      'Logo',
      '置於左上。',
      '\t中文　　全形空白 不換行空白\v垂直定位\f換頁都算空白。',
      '漢字\u{20000} \u{20001}擴充區 B 的字也是漢字。',
      '品牌色「晞月玫瑰」 與「珍珠金」、 頓號後的空白保留。',
      'ひらがな と カタカナ 旁的空白保留。',
      '﻿開頭的 BOM 會被 trim 去掉。',
      '\u0085 與 \u001c 不是 JavaScript 的空白\u0085',
      '文字 中間的行分隔符號是空白。',
    ].join('\n'),
  },
  // 中英混排、半形句尾標點（! ? ;）、不分大小寫的標籤規則
  {
    brandId: 'misty-isle', name: 'Typography Guide.md',
    text: [
      '# Typography',
      'Use Noto Sans TC for body text. 標題使用 Noto Serif TC Bold! Is the FONT size 16px? Yes; line height 1.5',
      '',
      'Keep the misty green (#2F4A44) and avoid neon colors!',
    ].join('\n'),
  },
  // 每條標籤規則（依序比對，第一個命中的決定）；內文判斷不出來時才看段落標題
  {
    brandId: 'selune', name: 'tags.md',
    text: [
      '禁用高飽和色彩，避免誇大。', '',
      '依 §10 標示。', '',
      '色票 #a1B2c3 與 ΔE 容許值。', '',
      '主色與點綴色。', '',
      'LOGO 置中。', '',
      '標誌周圍淨空。', '',
      'Font 一律使用黑體，字重 700。', '',
      '版面留白 40%，商品佔比 30%。', '',
      'ctr 最高的素材。', '',
      '去年的案例。', '',
      '門市營業時間為上午十點。', '',
      '# 字型規範', '標題最多兩行。', '',
      '# §3 字型', '標題最多兩行。', '',
      '# 色彩', '標誌置於左上。',
    ].join('\n'),
  },
  // 預設 180 字：單句過長時硬切，剩下的留給下一句接續；剛好 180 字；裝不下時換新塊
  {
    brandId: 'selune', name: 'long.txt',
    text: [
      `${'長'.repeat(400)}。接在硬切後面的短句。`,
      '',
      '整'.repeat(360),
      '',
      `${'甲'.repeat(170)}。${'乙'.repeat(8)}。${'丙'.repeat(5)}。`,
    ].join('\n'),
  },
  // 字數以 code point 計算：emoji 與擴充區漢字各算一個字（UTF-16 是兩個）
  {
    brandId: 'selune', name: 'emoji.md', maxChars: 8,
    text: ['😀'.repeat(10) + '。', '', `${'\u{20000}'.repeat(5)}😀😀😀。👩‍💻 工程師。`].join('\n'),
  },
  // 只有空白的行也算空行（含全形空白與 BOM）；U+0085 不是 JavaScript 的空白，所以不算
  { brandId: 'selune', name: 'blocks.txt', text: '第一段\n　\t\n第二段\n﻿\n第三段\n\u0085\n仍是第三段' },
  // Windows（CRLF）與舊版 Mac（CR）的換行
  {
    brandId: 'selune', name: 'crlf.txt',
    text: '第一段第一行\r\n第一段第二行。\r\n\r\n第二段\r舊 Mac 換行？\r\r第三段\n\r\n第四段',
  },
  // 連續或開頭的標點、只有標點的段落
  {
    brandId: 'selune', name: 'punctuation.md',
    text: ['真的嗎？？好。！開頭的驚嘆號。;;結尾', '', '。。。', '', '。 。'].join('\n'),
  },
  // 第一個標題之前，以去掉副檔名的檔名為段落標題
  { brandId: 'selune', name: '規範.txt', text: '標題最多兩行。' },
  { brandId: 'selune', name: 'README', text: '沒有副檔名。' },
  { brandId: 'selune', name: 'ci.v2.final.md', text: '只去掉最後一個副檔名。' },
  { brandId: 'selune', name: '.env', text: '整個檔名都是副檔名時，段落標題是空字串。' },
  { brandId: 'selune', name: 'notes.', text: '結尾的句點不是副檔名。' },
  { brandId: 'misty-isle', name: '規範.txt', text: '標題最多兩行。' },
  // 沒有內文
  { brandId: 'selune', name: 'empty.txt', text: '' },
  { brandId: 'selune', name: 'blank.txt', text: ' \n\n 　\n' },
  { brandId: 'misty-isle', name: 'headings-only.md', text: '# 只有標題\n\n## 沒有內文' },
];

/** embedPreview 的範例：不同的 n，以及剛好落在四捨五入邊界的文字 */
export const PREVIEW_SAMPLES: { text: string; n?: number }[] = [
  { text: '' },
  { text: '品牌主色', n: 0 },
  { text: '品牌主色', n: 1 },
  { text: '品牌主色', n: 24 },
  // 刻意找出的文字：第一個值剛好是 -937.5，Math.round 得 -937（Python 的 round() 取偶數會得 -938）
  { text: '四捨五入丁愪狁' },
];
