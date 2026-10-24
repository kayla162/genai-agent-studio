"""任務使用的背景風格：對應 web/src/lib/agent/style.ts（選擇規則與說明文字兩邊一致）。"""

from dataclasses import dataclass

from app.contract import Brand, Tone, VisualStyle
from app.errors import AppError


@dataclass(frozen=True)
class ChosenStyle:
    style: VisualStyle
    #: 寫進任務 log 的說明，例如「背景風格：節慶（自動：語氣 playful）」
    note: str


def choose_visual_style(brand: Brand, tone: Tone, style_id: str | None) -> ChosenStyle:
    """style_id 有值時使用該組（品牌沒有這一組時丟出 AppError）；
    None 時取第一組 tones 含 tone 的風格，都沒有時用第一組。"""
    if style_id is not None:
        style = next((s for s in brand.visual_styles if s.id == style_id), None)
        if style is None:
            raise AppError(f'品牌「{brand.name}」沒有這個背景風格：{style_id}')
        return ChosenStyle(style, f'背景風格：{style.label}（指定）')
    matched = next((s for s in brand.visual_styles if tone in s.tones), None)
    if matched is not None:
        return ChosenStyle(matched, f'背景風格：{matched.label}（自動：語氣 {tone}）')
    first = brand.visual_styles[0]
    return ChosenStyle(first, f'背景風格：{first.label}（自動：沒有對應語氣 {tone} 的風格，使用第一組）')
