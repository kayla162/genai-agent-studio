"""儀表板統計與前端（web/src/lib/stats/dashboard.ts）的結果完全相同。"""

import pytest

from app.contract import JobSnapshot
from app.stats import dashboard_stats
from tests.fixtures import load_fixture


def snapshots(brand_id: str | None) -> list[JobSnapshot]:
    snaps = [JobSnapshot.model_validate(s) for s in load_fixture('stats.json')['snapshots']]
    return [s for s in snaps if brand_id is None or s.summary.input.brand_id == brand_id]


@pytest.mark.parametrize('case', range(3))
def test_matches_the_frontend_dashboard(case: int) -> None:
    expected = load_fixture('stats.json')['cases'][case]
    assert dashboard_stats(snapshots(expected['brandId'])).to_json() == expected['stats']


def test_cancelled_and_failed_jobs_are_left_out() -> None:
    stats = dashboard_stats(snapshots(None))
    assert stats.jobs == 6
    assert {j.job_id for j in stats.recent}.isdisjoint({'job_sample_cancelled', 'job_sample_failed'})


def test_empty_stats() -> None:
    stats = dashboard_stats([])
    assert (stats.jobs, stats.pass_rate, stats.cost_per_image, stats.rerank_hits, stats.recent) == (0, 0, None, [], [])
