"""任務使用的背景風格：與 web/src/lib/agent/style.test.ts 相同的情況與說明文字。"""

import pytest

from app.brands import load_brands
from app.contract import VisualStyle
from app.errors import AppError
from app.visual_style import choose_visual_style
from tests.fixtures import BRANDS_DIR

SELUNE = next(b.brand for b in load_brands(BRANDS_DIR)[0] if b.brand.id == 'selune')
BRAND = SELUNE.model_copy(
    update={
        'visual_styles': [
            VisualStyle(id='daily', label='日常', prompt='soft linen', tones=['gentle', 'minimal']),
            VisualStyle(id='festive', label='節慶', prompt='gold confetti', tones=['playful']),
            VisualStyle(id='plain', label='素面', prompt='plain wall', tones=[]),
        ]
    }
)


def test_uses_the_chosen_style() -> None:
    chosen = choose_visual_style(BRAND, 'gentle', 'plain')
    assert (chosen.style.id, chosen.note) == ('plain', '背景風格：素面（指定）')


def test_picks_the_first_style_whose_tones_include_the_brief_tone() -> None:
    chosen = choose_visual_style(BRAND, 'playful', None)
    assert (chosen.style.id, chosen.note) == ('festive', '背景風格：節慶（自動：語氣 playful）')
    assert choose_visual_style(BRAND, 'minimal', None).style.id == 'daily'


def test_falls_back_to_the_first_style_when_no_style_matches_the_tone() -> None:
    chosen = choose_visual_style(BRAND, 'science', None)
    assert chosen.style.id == 'daily'
    assert chosen.note == '背景風格：日常（自動：沒有對應語氣 science 的風格，使用第一組）'


def test_rejects_a_style_the_brand_does_not_have() -> None:
    with pytest.raises(AppError, match='沒有這個背景風格：nope'):
        choose_visual_style(BRAND, 'gentle', 'nope')
