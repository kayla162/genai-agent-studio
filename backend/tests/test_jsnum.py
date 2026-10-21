"""數字轉字串與 JavaScript 相同（品牌設定檔的切塊文字要與 TypeScript 的示範資料一致）。"""

import pytest

from app.core.jsnum import js_number


@pytest.mark.parametrize(
    ('value', 'text'),
    [
        (4.0, '4'),
        (4.2, '4.2'),
        (12.5, '12.5'),
        (0.1 + 0.2, '0.30000000000000004'),
        (-0.5, '-0.5'),
        (0.0, '0'),
        (-0.0, '0'),
        (0.000001, '0.000001'),
        (0.00005, '0.00005'),
        (1e-7, '1e-7'),
        (1.5e-7, '1.5e-7'),
        (1e16, '10000000000000000'),
        (123456789012345680000.0, '123456789012345680000'),
        (1e21, '1e+21'),
        (float('inf'), 'Infinity'),
        (float('nan'), 'NaN'),
    ],
)
def test_numbers_are_written_like_javascript(value: float, text: str) -> None:
    # 預期值以 node 的 String(value) 產生
    assert js_number(value) == text
