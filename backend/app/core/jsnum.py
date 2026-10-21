"""數字轉字串，與 JavaScript 的 String(number) 相同（Python 的 str(4.0) 是 '4.0'，JS 是 '4'）。"""

import math
from decimal import Decimal


def js_number(x: float) -> str:
    """ECMAScript Number::toString：最短可還原的十進位數字，整數不帶小數點，太大或太小時用 e 表示。"""
    if math.isnan(x):
        return 'NaN'
    if math.isinf(x):
        return 'Infinity' if x > 0 else '-Infinity'
    if x == 0:
        return '0'
    # repr 是最短可還原的表示（與 JS 相同的有效數字）；x = 0.digits × 10^n
    _, digit_tuple, exponent = Decimal(repr(abs(x))).normalize().as_tuple()
    assert isinstance(exponent, int)
    digits = ''.join(map(str, digit_tuple))
    k = len(digits)
    n = exponent + k
    sign = '-' if x < 0 else ''
    if k <= n <= 21:
        return sign + digits + '0' * (n - k)
    if 0 < n <= 21:
        return f'{sign}{digits[:n]}.{digits[n:]}'
    if -6 < n <= 0:
        return f'{sign}0.{"0" * -n}{digits}'
    mantissa = digits[0] + (f'.{digits[1:]}' if k > 1 else '')
    return f'{sign}{mantissa}e{"+" if n > 0 else "-"}{abs(n - 1)}'
