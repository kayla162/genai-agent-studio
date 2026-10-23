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


def test_uses_the_recorded_costs_when_given() -> None:
    snaps = snapshots(None)
    first = dashboard_stats(snaps).recent[0].job_id
    stats = dashboard_stats(snaps, {first: 0.5, 'job_not_finished': 9.0})
    costs = {j.job_id: j.cost_usd for j in stats.recent}
    # 沒有用量紀錄的任務（例如模擬模式）為 0
    assert costs == {job_id: (0.5 if job_id == first else 0) for job_id in costs}
    delivered = sum(j.delivered for j in stats.recent)
    assert stats.jobs == len(stats.recent)
    assert stats.cost_per_image == 0.5 / delivered
