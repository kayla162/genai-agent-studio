from app.core.rng import Mulberry32, hash_string
from tests.fixtures import load_fixture


def test_hash_string_matches_the_frontend() -> None:
    for text, expected in load_fixture('rng.json')['hashString']:
        assert hash_string(text) == expected


def test_mulberry32_matches_the_frontend_for_any_seed() -> None:
    for seed, expected in load_fixture('rng.json')['mulberry32']:
        rng = Mulberry32(seed)
        assert [rng() for _ in expected] == expected
