"""合約模型必須能無損解析 TypeScript 產生的 golden fixtures（contracts/fixtures/）。"""

import pytest

from app.contract import (
    Brand,
    ChannelTemplate,
    DashboardStats,
    DemoOptions,
    JobInput,
    JobStatusEvent,
    JobSummary,
    Product,
    RagHit,
    message_json,
    parse_event,
    parse_message,
)
from tests.fixtures import TIMELINES, load_fixture


def test_brands_products_and_templates_round_trip() -> None:
    data = load_fixture('brands.json')
    for raw in data['brands']:
        assert Brand.model_validate(raw).to_json() == raw
    for raw in data['products']:
        assert Product.model_validate(raw).to_json() == raw
    for raw in data['templates']:
        assert ChannelTemplate.model_validate(raw).to_json() == raw


@pytest.mark.parametrize('name', TIMELINES)
def test_every_event_of_a_timeline_round_trips(name: str) -> None:
    data = load_fixture(f'timelines/{name}.json')
    assert JobInput.model_validate(data['input']).to_json() == data['input']
    assert DemoOptions.model_validate(data['demo']).to_json() == data['demo']
    types = set()
    for item in data['events']:
        event = parse_event(item['event'])
        types.add(event.type)
        assert event.to_json() == item['event']
    assert {'job.accepted', 'prompt.generated', 'render.completed', 'review.check', 'job.status'} <= types


def test_job_summaries_and_dashboard_stats_round_trip() -> None:
    data = load_fixture('stats.json')
    for snap in data['snapshots']:
        assert JobSummary.model_validate(snap['summary']).to_json() == snap['summary']
    for case in data['cases']:
        assert DashboardStats.model_validate(case['stats']).to_json() == case['stats']


def test_messages_carry_seq_and_ts_next_to_the_event_fields() -> None:
    event = JobStatusEvent(type='job.status', stage='queued', round=0)
    message = message_json(event, 2, '2026-10-07T01:00:00.000Z')
    assert message == {'type': 'job.status', 'stage': 'queued', 'round': 0, 'seq': 2, 'ts': '2026-10-07T01:00:00.000Z'}
    assert parse_message(message) == (event, 2, '2026-10-07T01:00:00.000Z')


def test_rerank_score_is_omitted_until_reranked() -> None:
    hit = RagHit(chunk_id='c', source='s', section='§', tag='law', text='t', vector_score=0.8)
    assert 'rerankScore' not in hit.to_json()
    assert hit.model_copy(update={'rerank_score': 0.9}).to_json()['rerankScore'] == 0.9
