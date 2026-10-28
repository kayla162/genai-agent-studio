"""模型檔的下載與核對（去背與 RAG 共用）：串流下載到 .part，邊下載邊算 SHA-256，大小與 SHA-256 都正確才改名。"""

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path

import httpx

#: 下載與核對時每次讀取的位元組數
CHUNK = 1 << 20
#: 下載模型的逾時（秒）：連線與兩次讀取之間的間隔
DOWNLOAD_TIMEOUT = 60


def download_client() -> httpx.AsyncClient:
    """下載模型用的 HTTP client（去背與 RAG 的引擎每次準備模型時建立一個）。"""
    return httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT)


@dataclass(frozen=True)
class ModelFile:
    name: str
    url: str
    size: int
    sha256: str
    #: 存放在 models/ 的檔名；省略時為 {name}.onnx（tokenizer 是 .json，所以要能另外指定）
    filename: str = ''

    def __post_init__(self) -> None:
        if not self.filename:
            object.__setattr__(self, 'filename', f'{self.name}.onnx')


class ModelFileError(Exception):
    """下載失敗或檔案不符。訊息以「下載」開頭，呼叫端在前面加上模型的用途（例如「去背模型」）後轉成自己的錯誤。"""


def _matches(path: Path, model: ModelFile) -> bool:
    if path.stat().st_size != model.size:
        return False
    digest = hashlib.sha256()
    with path.open('rb') as f:
        while block := f.read(CHUNK):
            digest.update(block)
    return digest.hexdigest() == model.sha256


def has_model(model: ModelFile, models_dir: Path) -> bool:
    """已有大小與 SHA-256 都正確的檔案。"""
    path = models_dir / model.filename
    return path.is_file() and _matches(path, model)


async def ensure_model(model: ModelFile, models_dir: Path, http: httpx.AsyncClient) -> Path:
    """回傳模型檔的路徑；沒有正確的檔案時先下載到 .part，核對大小與 SHA-256 後才改名。"""
    target = models_dir / model.filename
    if await asyncio.to_thread(has_model, model, models_dir):
        return target
    models_dir.mkdir(parents=True, exist_ok=True)
    part = models_dir / f'{model.filename}.part'
    mismatch = f'下載不完整（{model.name}）：檔案大小或 SHA-256 不符'
    digest = hashlib.sha256()
    size = 0
    try:
        async with http.stream('GET', model.url, follow_redirects=True) as res:
            res.raise_for_status()
            with part.open('wb') as f:
                async for chunk in res.aiter_bytes(CHUNK):
                    f.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                    # 已經比宣告的大：不必讀完（伺服器出錯時可能一直送，會寫滿磁碟）
                    if size > model.size:
                        raise ModelFileError(mismatch)
        if size != model.size or digest.hexdigest() != model.sha256:
            raise ModelFileError(mismatch)
        part.replace(target)
    except httpx.HTTPError as error:
        raise ModelFileError(f'下載失敗：{error}') from error
    finally:
        part.unlink(missing_ok=True)
    return target
