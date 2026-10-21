"""與 web/src/lib/core/num.ts 相同的雜湊與偽隨機數：模擬模式的 seed 與前端 mock 完全一致。"""

_MASK = 0xFFFFFFFF


def _imul(a: int, b: int) -> int:
    """JavaScript Math.imul：32-bit 乘法取低 32 位（以無號整數表示）。"""
    return (a * b) & _MASK


def hash_string(s: str) -> int:
    """FNV-1a 32-bit 字串雜湊，回傳非負整數；以 Unicode code point 為單位（同 JS 的 for...of）。"""
    h = 2166136261
    for ch in s:
        h = _imul(h ^ ord(ch), 16777619)
    return h


_BASE36 = '0123456789abcdefghijklmnopqrstuvwxyz'


def to_base36(n: int) -> str:
    """整數的 36 進位表示（同 JS 的 n.toString(36)：小寫，負數加 -）。"""
    if n < 0:
        return '-' + to_base36(-n)
    digits = ''
    while True:
        n, r = divmod(n, 36)
        digits = _BASE36[r] + digits
        if n == 0:
            return digits


class Mulberry32:
    """可重現的偽隨機數產生器（同一 seed 產生同一序列，回傳 [0, 1) 的浮點數）。"""

    def __init__(self, seed: int) -> None:
        self._a = seed & _MASK

    def __call__(self) -> float:
        self._a = (self._a + 0x6D2B79F5) & _MASK
        a = self._a
        t = _imul(a ^ (a >> 15), 1 | a)
        t = ((t + _imul(t ^ (t >> 7), 61 | t)) & _MASK) ^ t
        return (t ^ (t >> 14)) / 4294967296
