"""上傳手冊的抽字：Markdown、純文字、BOM、非 UTF-8、PDF（tests/data 的中文 PDF）、有密碼與讀不到文字的 PDF。

ci-sample.pdf 由 Chromium 以微軟正黑體輸出（兩頁）。它的文字層把「月」「色」「用」等字記成康熙部首（U+2F00–），
正好用來確認抽字時會換回一般的漢字。有密碼與只有圖片的 PDF 在測試時產生。
"""

import io

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

from app.errors import Invalid
from app.rag.chunking import chunk_document, guess_tag
from app.rag.extract import MAX_BYTES, MAX_CHARS, NO_TEXT, check_type, document_name, extract_text
from tests.fixtures import SAMPLE_PDF as SAMPLE


def encrypted(user_password: str, owner_password: str) -> bytes:
    writer = PdfWriter(clone_from=PdfReader(SAMPLE))
    # RC4 不需要額外的加密套件
    writer.encrypt(user_password, owner_password, algorithm='RC4-128')
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def scanned() -> bytes:
    """只有圖片、沒有文字層的 PDF（像掃描檔）。"""
    buf = io.BytesIO()
    Image.new('RGB', (200, 280), (240, 240, 240)).save(buf, 'PDF')
    return buf.getvalue()


@pytest.mark.parametrize('name', ['手冊.md', '手冊.markdown', 'notes.txt', 'CI.MD'])
def test_text_files_are_decoded_as_utf8_without_the_bom(name: str) -> None:
    text = '# 色彩\n主色為品牌紫。'
    assert extract_text(name, text.encode()) == text
    assert extract_text(name, b'\xef\xbb\xbf' + text.encode()) == text


def test_text_files_must_be_utf8() -> None:
    with pytest.raises(Invalid, match='^文字檔需為 UTF-8 編碼$'):
        extract_text('手冊.txt', '主色為品牌紫'.encode('big5'))


@pytest.mark.parametrize('name', ['手冊.docx', '手冊', 'logo.png', '.md.exe'])
def test_only_markdown_text_and_pdf_are_supported(name: str) -> None:
    with pytest.raises(Invalid, match='^只支援 .md、.txt、.pdf$'):
        check_type(name)
    with pytest.raises(Invalid, match='^只支援 .md、.txt、.pdf$'):
        extract_text(name, b'x')


def test_files_and_texts_have_size_limits() -> None:
    with pytest.raises(Invalid, match='^檔案不可超過 20 MB$'):
        extract_text('big.txt', b'a' * (MAX_BYTES + 1))
    assert len(extract_text('long.txt', b'a' * MAX_CHARS)) == MAX_CHARS
    with pytest.raises(Invalid, match=r'^文字超過 20 萬字（200,001 字），請分成幾份上傳$'):
        extract_text('long.txt', b'a' * (MAX_CHARS + 1))


def test_document_names_drop_any_path() -> None:
    assert document_name('C:\\fakepath\\晞月 CI 手冊.pdf') == '晞月 CI 手冊.pdf'
    assert document_name('a/b/手冊.md') == '手冊.md'
    assert document_name('手冊.md') == '手冊.md'


def test_pdf_pages_are_joined_by_a_blank_line_with_radicals_mapped_to_ideographs() -> None:
    pages = [page.extract_text() for page in PdfReader(SAMPLE).pages]
    # 原始的文字層：「色」是康熙部首 U+2F8A
    assert len(pages) == 2 and '\u2f8a彩系統' in pages[0]
    text = extract_text('ci-sample.pdf', SAMPLE.read_bytes())
    assert not [ch for ch in text if '\u2e80' <= ch <= '\u2fdf']
    assert text.startswith('晞月 CI 手冊\n§2.1 色彩系統\n品牌主色為晞月玫瑰 #B76E79，輔助色為月光米白 #F6EFE9。\n')
    assert '高度之淨空區。\n\n§5 廣告用語\n保養品廣告不得宣稱醫療效能。' in text
    assert text.endswith('改用「改善外觀」「專業配方」')
    # 部首看起來一樣，但切塊的標籤判斷認不得
    assert (guess_tag('主⾊佔畫⾯ 60% 以上'), guess_tag('主色佔畫面 60% 以上')) == ('general', 'color')
    # 每一頁是一段（PDF 沒有 Markdown 標題，section 是檔名）
    chunks = chunk_document('selune', 'ci-sample.pdf', text)
    assert [c.section for c in chunks] == ['ci-sample', 'ci-sample']
    assert chunks[0].text.startswith('晞月 CI 手冊 §2.1 色彩系統品牌主色為晞月玫瑰')
    assert chunks[1].text.startswith('§5 廣告用語保養品廣告不得宣稱醫療效能。')


def test_pdfs_that_need_a_password_are_refused() -> None:
    with pytest.raises(Invalid, match='^PDF 有加密保護（密碼或權限限制），請先移除保護再上傳$'):
        extract_text('locked.pdf', encrypted('secret', 'owner'))


def test_pdfs_with_only_an_owner_password_are_read() -> None:
    """只限制權限（開啟不需要密碼）的 PDF 照常抽字。"""
    assert extract_text('limited.pdf', encrypted('', 'owner')) == extract_text('ci-sample.pdf', SAMPLE.read_bytes())


def test_pdfs_without_a_text_layer_are_refused() -> None:
    with pytest.raises(Invalid, match=f'^{NO_TEXT}$'):
        extract_text('scan.pdf', scanned())
    blank = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(420, 595)
    writer.write(blank)
    with pytest.raises(Invalid, match=f'^{NO_TEXT}$'):
        extract_text('blank.pdf', blank.getvalue())


def test_broken_pdfs_are_refused() -> None:
    with pytest.raises(Invalid, match='^PDF 無法讀取：'):
        extract_text('broken.pdf', b'%PDF-1.4\nnot really a pdf')
    with pytest.raises(Invalid, match='^PDF 無法讀取：'):
        extract_text('empty.pdf', b'')


def test_pdfs_with_too_many_pages_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('app.rag.extract.MAX_PDF_PAGES', 1)
    with pytest.raises(Invalid, match='^PDF 超過 1 頁（2 頁），請分成幾份上傳$'):
        extract_text('ci-sample.pdf', SAMPLE.read_bytes())


def test_pdf_extraction_is_stopped_when_it_takes_too_long(monkeypatch: pytest.MonkeyPatch) -> None:
    """格式異常的 PDF 可能讓 pypdf 跑很久：在子行程抽字，逾時就結束它，api 的執行緒不會一直被佔住。"""
    monkeypatch.setattr('app.rag.extract.PDF_TIMEOUT', 0.001)
    with pytest.raises(Invalid, match='^PDF 處理超過 0.001 秒，請分成幾份上傳$'):
        extract_text('ci-sample.pdf', SAMPLE.read_bytes())
