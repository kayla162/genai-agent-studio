"""品牌設定檔（brands/*.yaml）：驗證後轉成合約的 Brand 與示範商品。

- 檔名必須與 id 相同；以底線開頭的檔案（_template.yaml）不匯入。
- 某個檔案有錯時只略過那個品牌，錯誤會顯示在系統狀態。
- 沒有 key 為 law-alt 的切塊時，依替代用語表自動產生「合規替代用語對照」。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError, field_validator

from app.contract import (
    Brand,
    BrandLogo,
    BrandRules,
    CaseStudy,
    CopyPreset,
    Fonts,
    Model,
    Palette,
    Price,
    Product,
    RagChunk,
    RagTag,
    SamplePhoto,
    Tone,
)

TONES: tuple[Tone, ...] = ('gentle', 'science', 'playful', 'minimal')
#: Logo 圖檔支援的格式（與 app/api/files.py 提供的圖片格式相同）
LOGO_TYPES = frozenset({'.png', '.jpg', '.jpeg', '.webp', '.svg'})


class GuidelineConfig(Model):
    key: str
    source: str
    section: str
    tag: RagTag
    text: str


class SampleConfig(Model):
    id: str
    name: str
    features: list[str]
    price: Price
    art: Literal['serum', 'coldbrew']
    created_at: str


class BrandConfig(Model):
    id: str = Field(pattern=r'^[a-z0-9]+(-[a-z0-9]+)*$')
    name: str
    category: str
    ci_version: str
    palette: Palette
    fonts: Fonts
    visual_style: str
    default_tone: Tone
    rules: BrandRules
    banned_words: list[str]
    replacements: dict[str, str]
    claim_words: list[str]
    disclaimer_phrase: str
    copy_presets: dict[Tone, CopyPreset]
    guidelines: list[GuidelineConfig]
    case_studies: list[CaseStudy] = []
    logo: str | None = None
    style_images: list[str] = []
    samples: list[SampleConfig] = []

    @field_validator('copy_presets')
    @classmethod
    def _every_tone(cls, presets: dict[Tone, CopyPreset]) -> dict[Tone, CopyPreset]:
        missing = [t for t in TONES if t not in presets]
        if missing:
            raise ValueError(f'缺少語氣：{"、".join(missing)}')
        return presets

    @field_validator('guidelines')
    @classmethod
    def _unique_keys(cls, guidelines: list[GuidelineConfig]) -> list[GuidelineConfig]:
        keys = [g.key for g in guidelines]
        duplicated = sorted({k for k in keys if keys.count(k) > 1})
        if duplicated:
            raise ValueError(f'key 重複：{"、".join(duplicated)}')
        return guidelines


@dataclass(frozen=True)
class LoadedBrand:
    brand: Brand
    samples: list[Product]
    logo_path: Path | None
    style_images: list[Path]
    #: 設定檔內容的 SHA-256；改變時重新寫入切塊
    source_hash: str


@dataclass(frozen=True)
class BrandLoadError:
    file: str
    message: str


class BrandFileError(Exception):
    pass


def load_brands(directory: Path) -> tuple[list[LoadedBrand], list[BrandLoadError]]:
    loaded: list[LoadedBrand] = []
    errors: list[BrandLoadError] = []
    for path in sorted(directory.glob('*.yaml')):
        if path.name.startswith('_'):
            continue
        try:
            item = _load_file(directory, path)
        except BrandFileError as e:
            errors.append(BrandLoadError(path.name, str(e)))
            continue
        loaded.append(item)
    return loaded, errors


def _load_file(directory: Path, path: Path) -> LoadedBrand:
    raw = path.read_bytes()
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise BrandFileError(f'YAML 格式錯誤：{e}') from e
    try:
        cfg = BrandConfig.model_validate(data)
    except ValidationError as e:
        raise BrandFileError(_describe(e)) from e
    if cfg.id != path.stem:
        raise BrandFileError(f'檔名必須與 id 相同（id 為 {cfg.id}）')

    logo_path = _inside(directory, cfg.logo, 'Logo 圖檔') if cfg.logo else None
    if logo_path is not None and logo_path.suffix.lower() not in LOGO_TYPES:
        raise BrandFileError(f'Logo 圖檔只支援 PNG、JPEG、WebP 與 SVG：{cfg.logo}')
    style_images = [_inside(directory, p, '參考圖') for p in cfg.style_images]
    alt = _alt_guideline(cfg, path.name)
    guidelines = [*cfg.guidelines, *([alt] if alt else [])]

    brand = Brand(
        id=cfg.id,
        name=cfg.name,
        category=cfg.category,
        ci_version=cfg.ci_version,
        palette=cfg.palette,
        fonts=cfg.fonts,
        visual_style=cfg.visual_style,
        default_tone=cfg.default_tone,
        rules=cfg.rules,
        banned_words=cfg.banned_words,
        replacements=cfg.replacements,
        claim_words=cfg.claim_words,
        disclaimer_phrase=cfg.disclaimer_phrase,
        guideline_chunks=[
            RagChunk(id=f'{cfg.id}#{g.key}', source=g.source, section=g.section, tag=g.tag, text=g.text)
            for g in guidelines
        ],
        case_studies=cfg.case_studies,
        copy_presets=cfg.copy_presets,
        logo=BrandLogo(url=f'/files/brands/{Path(cfg.logo).as_posix()}') if cfg.logo else None,
    )
    samples = [
        Product(
            id=s.id,
            brand_id=cfg.id,
            name=s.name,
            features=s.features,
            price=s.price,
            photo=SamplePhoto(source='sample', art=s.art),
            cutout=None,
            created_at=s.created_at,
        )
        for s in cfg.samples
    ]
    return LoadedBrand(brand, samples, logo_path, style_images, hashlib.sha256(raw).hexdigest())


def _describe(error: ValidationError) -> str:
    return '；'.join(f'{".".join(str(p) for p in e["loc"])}：{e["msg"]}' for e in error.errors())


def _inside(directory: Path, relative: str, what: str) -> Path:
    """相對於 brands/ 的檔案；不可跳出資料夾。"""
    path = directory / relative
    if not path.resolve().is_relative_to(directory.resolve()):
        raise BrandFileError(f'{what}必須放在 brands/ 資料夾內：{relative}')
    if not path.is_file():
        raise BrandFileError(f'{what}不存在：{relative}')
    return path


def _alt_guideline(cfg: BrandConfig, file_name: str) -> GuidelineConfig | None:
    if not cfg.replacements or any(g.key == 'law-alt' for g in cfg.guidelines):
        return None
    pairs = [f'「{word}」→「{alt}」' if alt else f'「{word}」→ 刪除' for word, alt in cfg.replacements.items()]
    return GuidelineConfig(
        key='law-alt', source=file_name, section='合規替代用語對照', tag='law', text='；'.join(pairs) + '。'
    )
