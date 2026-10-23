"""docker-compose.yml 與 docker-compose.e2e.yml 的 Gemini 設定（只解析 YAML，不需要 Docker）。"""

from pathlib import Path
from typing import Any

import yaml

from app.settings import REPO_ROOT


class ComposeLoader(yaml.SafeLoader):
    """接受 Compose 的 !override、!reset 標記（取標記後的內容）。"""


def _tagged(loader: ComposeLoader, suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_scalar(node)  # type: ignore[arg-type]


ComposeLoader.add_multi_constructor('!', _tagged)


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.load((REPO_ROOT / name).read_text(encoding='utf-8'), Loader=ComposeLoader)  # noqa: S506
    return data


def test_api_and_worker_share_the_agent_mode_and_read_the_pricing_file() -> None:
    services = load('docker-compose.yml')['services']
    for name in ('api', 'worker'):
        service = services[name]
        assert service['environment']['AGENT_MODE'] == '${AGENT_MODE:-gemini}'
        assert service['environment']['PRICING_FILE'] == '/app/pricing.yaml'
        assert './pricing.yaml:/app/pricing.yaml:ro' in service['volumes']
        assert service['env_file'][0]['path'] == '.env'
    assert Path(REPO_ROOT / 'pricing.yaml').is_file()


def test_the_e2e_stack_is_simulated_and_never_gets_the_developer_key() -> None:
    services = load('docker-compose.e2e.yml')['services']
    for name in ('api', 'worker'):
        environment = services[name]['environment']
        assert (environment['AGENT_MODE'], environment['GEMINI_API_KEY']) == ('sim', '')
        assert './pricing.yaml:/app/pricing.yaml:ro' in services[name]['volumes']


def test_env_example_lists_the_gemini_settings() -> None:
    example = (REPO_ROOT / '.env.example').read_text(encoding='utf-8')
    for name in (
        'AGENT_MODE',
        'GEMINI_API_KEY',
        'GEMINI_LLM_MODEL',
        'GEMINI_VLM_MODEL',
        'GEMINI_TIMEOUT_SECONDS',
        'GEMINI_MAX_RETRIES',
        'GEMINI_CONCURRENCY',
        'GEMINI_JOB_BUDGET_USD',
        'GEMINI_MONTHLY_BUDGET_USD',
        'PRICING_FILE',
    ):
        assert f'{name}=' in example, name
