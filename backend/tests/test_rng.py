from app.core.rng import Mulberry32, hash_string, to_base36
from tests.fixtures import load_fixture


def test_hash_string_matches_the_frontend() -> None:
    for text, expected in load_fixture('rng.json')['hashString']:
        assert hash_string(text) == expected


def test_mulberry32_matches_the_frontend_for_any_seed() -> None:
    for seed, expected in load_fixture('rng.json')['mulberry32']:
        rng = Mulberry32(seed)
        assert [rng() for _ in expected] == expected


def test_to_base36_matches_number_to_string() -> None:
    # 數值與 JS 的 n.toString(36) 相同（node 驗證過）；切塊 id 也以此比對 chunks.json
    cases = {0: '0', 35: 'z', 36: '10', 1295: 'zz', 1296: '100', 2166136261: 'ztntfp', 4294967295: '1z141z3', -5: '-5'}
    assert {n: to_base36(n) for n in cases} == cases
