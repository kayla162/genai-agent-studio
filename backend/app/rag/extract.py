"""上傳的品牌手冊 → 文字：Markdown 與純文字以 UTF-8 解碼（可有 BOM），PDF 以 pypdf 逐頁抽出文字層（頁與頁之間空一行）。

api 在開始串流之前呼叫（在執行緒裡）；檔案有問題時丟出 Invalid（400），訊息為繁體中文。之後只把文字放進佇列。
PDF 在子行程裡抽字（python -m app.rag.extract），有頁數、時間與記憶體上限：格式異常的 PDF 可能讓 pypdf
跑很久或用掉大量記憶體，逾時就結束子行程，不會一直佔住 api 的執行緒。
"""

import io
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path, PurePosixPath

from pypdf import PasswordType, PdfReader

from app.errors import Invalid

TEXT_TYPES = frozenset({'.md', '.markdown', '.txt'})
PDF_TYPE = '.pdf'
#: 單檔上限（位元組）
MAX_BYTES = 20 * 1024 * 1024
#: 抽出的文字上限（字數，以 code point 計算）：約 1,100 個以上的切塊，向量化需要幾分鐘
MAX_CHARS = 200_000
#: 切塊上限：一份文件的向量化要在 app.queues 的 TASK_TIMEOUT（600 秒）內完成（上傳的時限是兩倍，容許兩份同時上傳）。
#: 4 顆 CPU 約每秒 4.8 塊，2,000 塊約 420 秒。一般文章到 MAX_CHARS 約 1,170 塊；
#: 很多短段落的文件（FAQ、詞彙表、行距大的 PDF）字數沒超過也可能切出上萬塊，所以另外限制切塊數（api 在開始串流之前檢查）
MAX_CHUNKS = 2000
#: PDF 的頁數上限
MAX_PDF_PAGES = 1000
#: 抽出 PDF 文字的時間上限（秒）
PDF_TIMEOUT = 60
#: 抽字子行程的記憶體上限（位元組；Windows 不支援，不設限）
PDF_MEMORY_LIMIT = 2 << 30
#: 子行程的工作目錄（python -m app.rag.extract 要找得到 app 套件）
BACKEND_DIR = Path(__file__).resolve().parents[2]

NO_TEXT = 'PDF 沒有可讀取的文字（可能是掃描檔），請先轉成文字'

#: 康熙部首（U+2F00–）與 CJK 部首補充（U+2E80–）→ 一般的漢字，例如「⽉」→「月」。
#: Windows 的微軟正黑體等字型把部首與漢字對應到同一個字形，Chromium、Office 輸出 PDF 時，
#: 文字層常記成部首：看起來一樣，但切塊的標籤判斷（「色彩」）與向量化都會認不得
_RADICALS = {
    cp: unicodedata.normalize('NFKC', chr(cp))
    for cp in range(0x2E80, 0x2FE0)
    if unicodedata.normalize('NFKC', chr(cp)) != chr(cp)
}


def document_name(filename: str) -> str:
    """上傳的檔名（部分瀏覽器會帶完整路徑，只取最後一段）。"""
    return re.split(r'[\\/]', filename)[-1].strip()


def check_type(name: str) -> str:
    """副檔名（小寫）；不支援時丟出 Invalid。"""
    suffix = PurePosixPath(name).suffix.lower()
    if suffix not in TEXT_TYPES and suffix != PDF_TYPE:
        raise Invalid('只支援 .md、.txt、.pdf')
    return suffix


def extract_text(name: str, data: bytes) -> str:
    suffix = check_type(name)
    if len(data) > MAX_BYTES:
        raise Invalid(f'檔案不可超過 {MAX_BYTES // 1024 // 1024} MB')
    text = _pdf_text(data) if suffix == PDF_TYPE else _decode(data)
    if len(text) > MAX_CHARS:
        raise Invalid(f'文字超過 {MAX_CHARS // 10_000} 萬字（{len(text):,} 字），請分成幾份上傳')
    return text


def _decode(data: bytes) -> str:
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError as error:
        raise Invalid('文字檔需為 UTF-8 編碼') from error


def _pdf_text(data: bytes) -> str:
    """在子行程抽字；逾時就結束它。"""
    try:
        done = subprocess.run(
            [sys.executable, '-m', 'app.rag.extract', str(MAX_PDF_PAGES)],
            input=data,
            capture_output=True,
            timeout=PDF_TIMEOUT,
            cwd=BACKEND_DIR,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise Invalid(f'PDF 處理超過 {PDF_TIMEOUT:g} 秒，請分成幾份上傳') from error
    if done.returncode != 0:
        # 例如超過記憶體上限
        raise Invalid('PDF 無法讀取：處理時發生錯誤，可能是檔案格式異常或內容太大')
    result = json.loads(done.stdout)
    if 'error' in result:
        raise Invalid(result['error'])
    text: str = result['text']
    return text


def _read_pdf(data: bytes, max_pages: int) -> str:
    """子行程裡實際抽字的部分。"""
    try:
        reader = PdfReader(io.BytesIO(data))
        # 只設定權限（擁有者密碼）的 PDF 可以用空白密碼開啟；需要密碼才能開啟的拒絕。
        # AES 加密的 PDF 需要 cryptography 套件，沒有安裝時解密會出錯，同樣視為有加密保護
        if reader.is_encrypted and _decrypt(reader) == PasswordType.NOT_DECRYPTED:
            raise Invalid('PDF 有加密保護（密碼或權限限制），請先移除保護再上傳')
        if len(reader.pages) > max_pages:
            raise Invalid(f'PDF 超過 {max_pages:,} 頁（{len(reader.pages):,} 頁），請分成幾份上傳')
        pages = [page.extract_text() for page in reader.pages]
    except Invalid:
        raise
    except Exception as error:
        raise Invalid(f'PDF 無法讀取：{error}') from error
    text = '\n\n'.join(pages).translate(_RADICALS)
    if not text.strip():
        raise Invalid(NO_TEXT)
    return text


def _decrypt(reader: PdfReader) -> PasswordType:
    try:
        return reader.decrypt('')
    except Exception:
        return PasswordType.NOT_DECRYPTED


def _main() -> None:
    """子行程：stdin 是 PDF，參數是頁數上限；stdout 是 {"text": …} 或 {"error": …}（JSON）。"""
    if sys.platform != 'win32':
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (PDF_MEMORY_LIMIT, PDF_MEMORY_LIMIT))
    try:
        result = {'text': _read_pdf(sys.stdin.buffer.read(), int(sys.argv[1]))}
    except Invalid as error:
        result = {'error': error.message}
    sys.stdout.write(json.dumps(result))


if __name__ == '__main__':
    _main()
