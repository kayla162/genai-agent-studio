"""依 AGENT_MODE 選擇 Agent 與審查、可用的模型選項（不需要資料庫）。"""

from decimal import Decimal

from app.adapters.composer import ComposerClient
from app.api.catalog import api_options
from app.contract import ApiOptions
from app.pipeline.gemini import GeminiAgent, GeminiReviewer, gemini_ports
from app.pipeline.sim import sim_ports
from app.settings import Settings
from tests.fake_gemini import FakeGemini


class FakeUsage:
    async def job_summary(self, job_id: str) -> tuple[Decimal, int]:
        return Decimal('0'), 0


async def test_gemini_ports_swap_the_agent_and_the_reviewer_only() -> None:
    composer = ComposerClient('http://127.0.0.1:9')
    try:
        base = sim_ports(composer, first_round_fail=True, force_all_fail=False)
        usage = FakeUsage()
        ports = gemini_ports(
            base, FakeGemini(), composer, Settings(_env_file=None, image_mode='sim', agent_mode='gemini'), usage
        )
        assert isinstance(ports.agent, GeminiAgent)
        assert isinstance(ports.reviewer, GeminiReviewer)
        assert (ports.retriever, ports.image, ports.posters, ports.usage) == (
            base.retriever,
            base.image,
            base.posters,
            usage,
        )
    finally:
        await composer.aclose()


def test_the_model_options_follow_the_agent_mode() -> None:
    assert api_options(Settings(_env_file=None, image_mode='sim', agent_mode='sim')) == ApiOptions(
        llm=['Gemini 3.7 Flash'], vlm=['Gemini 3.7 Vision'], engines=['comfyui']
    )
    gemini = Settings(_env_file=None, image_mode='sim', agent_mode='gemini', gemini_vlm_model='gemini-3.8-pro')
    assert api_options(gemini) == ApiOptions(llm=['gemini-3.8-flash'], vlm=['gemini-3.8-pro'], engines=['comfyui'])
