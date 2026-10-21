"""把品牌文件切成 RAG 切塊：web/src/lib/rag/chunk.ts 的移植，結果必須完全相同（contracts/fixtures/chunks.json）。

與 Python 預設行為不同、要照 JavaScript 處理的地方：
- 字數以 Unicode code point 計算（同 JS 的 [...s].length），Python 的 len() 剛好相同；
- 空白是 JS 的 \\s 與 trim()：包含 U+FEFF，不包含 U+0085 與 U+001C–U+001F（與 Python 的 str.isspace() 不同）；
- 正規表示式的 . 不比對 \\n、\\r、U+2028、U+2029；$ 只比對字串結尾（Python 要用 \\Z）；
- 四捨五入同 JS 的 Math.round：.5 一律往正無限大進位（Python 的 round() 是取偶數）。
"""

import math
import re
from collections.abc import Sequence

import regex

from app.contract import RagChunk, RagTag
from app.core.rng import Mulberry32, hash_string, to_base36

#: bge-m3 的向量維度
EMBED_DIMS = 1024

#: JavaScript 視為空白的字元（\s 與 String.prototype.trim() 相同）
_JS_SPACE = '\t\n\v\f\r \u00a0\u1680\u2028\u2029\u202f\u205f\u3000\ufeff' + ''.join(map(chr, range(0x2000, 0x200B)))
_S = f'[{_JS_SPACE}]'
#: JavaScript 的 .（沒有 s 旗標）
_DOT = '[^\n\r\u2028\u2029]'
_STOPS = '。！？!?；;'

#: 依序比對，第一個命中的規則決定標籤
_TAG_RULES: tuple[tuple[re.Pattern[str], RagTag], ...] = (
    (re.compile('禁用|法規|宣稱|療效|誇大|廣告|§'), 'law'),
    (re.compile('色彩|主色|輔助色|點綴色|色票|色差|ΔE|#[0-9a-fA-F]{6}'), 'color'),
    (re.compile('logo|標誌|淨空', re.IGNORECASE), 'logo'),
    (re.compile('字型|字體|字重|font', re.IGNORECASE), 'font'),
    (re.compile('版型|版面|留白|網格|構圖|佔比'), 'layout'),
    (re.compile('成效|CTR|點擊|互動|案例', re.IGNORECASE), 'history'),
)

#: 兩個漢字之間的空白（合併多行時產生）要拿掉。只認 Script=Han（同 JS）：頓號、引號等共用標點旁的空白保留
_CJK_GAP = regex.compile(r'(\p{Script=Han})' + _S + r'+(?=\p{Script=Han})')
_SPACES = re.compile(_S + '+')
_SENTENCE = re.compile(f'[^{_STOPS}]+[{_STOPS}]?')
_NEWLINE = re.compile('\r\n?')
_BLOCK_GAP = re.compile('\n' + _S + '*\n')
_HEADING = re.compile('#{1,6}' + _S + '+(' + _DOT + r'+)\Z')
_BULLET = re.compile('[-*•]' + _S + '+(' + _DOT + r'+)\Z')
_EXTENSION = re.compile(r'\.[^.]+\Z')


def guess_tag(text: str) -> RagTag:
    return next((tag for pattern, tag in _TAG_RULES if pattern.search(text)), 'general')


def tag_of(section: str, text: str) -> RagTag:
    """先看內文，內文無法判斷時再看段落標題。"""
    tag = guess_tag(text)
    return guess_tag(section) if tag == 'general' else tag


def _trim(s: str) -> str:
    return s.strip(_JS_SPACE)


def _pack(text: str, max_chars: int) -> list[str]:
    """依句號等標點切句，再把句子裝進不超過 max_chars 的塊；單句過長時硬切。"""
    out: list[str] = []
    cur = ''
    for raw in _SENTENCE.findall(text):
        s = _trim(raw)
        if not s:
            continue
        if len(cur) + len(s) <= max_chars:
            cur += s
            continue
        if cur:
            out.append(cur)
        out.extend(s[i : i + max_chars] for i in range(0, len(s) - max_chars, max_chars))
        cur = s[(len(s) - 1) // max_chars * max_chars :]
    if cur:
        out.append(cur)
    return out


def _paragraph(section: str, lines: list[str], max_chars: int) -> list[tuple[str, str]]:
    text = _trim(_CJK_GAP.sub(r'\1', _SPACES.sub(' ', ' '.join(lines))))
    return [(section, t) for t in _pack(text, max_chars)]


def chunk_document(brand_id: str, name: str, text: str, max_chars: int = 180) -> list[RagChunk]:
    """Markdown 標題（#）成為之後段落的 section（之前用去掉副檔名的檔名），空行分段，段落再依句子裝塊。"""
    doc_key = to_base36(hash_string(name))
    section = _EXTENSION.sub('', name, count=1)
    pieces: list[tuple[str, str]] = []
    for block in _BLOCK_GAP.split(_NEWLINE.sub('\n', text)):
        body: list[str] = []
        for line in filter(None, map(_trim, block.split('\n'))):
            if heading := _HEADING.match(line):
                pieces += _paragraph(section, body, max_chars)
                body = []
                section = _trim(heading[1])
            elif bullet := _BULLET.match(line):
                # 條列項目各自成句，避免合併後黏在一起
                item = bullet[1]
                body.append(item if item[-1] in _STOPS else item + '。')
            else:
                body.append(line)
        pieces += _paragraph(section, body, max_chars)

    return [
        RagChunk(id=f'{brand_id}#doc-{doc_key}-{i}', source=name, section=sec, tag=tag_of(sec, t), text=t)
        for i, (sec, t) in enumerate(pieces, start=1)
    ]


def _js_round(x: float) -> int:
    """JavaScript 的 Math.round：與 x 最接近的整數，剛好在中間時取較大的那個。"""
    floor = math.floor(x)
    return floor + 1 if x - floor >= 0.5 else floor


def vector_preview(vector: Sequence[float], n: int = 6) -> list[float]:
    """向量的前幾維，四捨五入到小數 3 位（同 JS 的 Math.round(x * 1000) / 1000）：上傳進度顯示的向量值。"""
    return [_js_round(x * 1000) / 1000 for x in vector[:n]]


def embed_preview(text: str, n: int = 6) -> list[float]:
    """模擬向量的前幾維（同前端 embedPreview）：由文字的雜湊決定，四捨五入到小數 3 位。"""
    rng = Mulberry32(hash_string(text))
    return vector_preview([rng() * 2 - 1 for _ in range(n)], n)
