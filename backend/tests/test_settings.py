"""設定：AGENT_MODE、IMAGE_MODE 與 REVIEW_MODE 的組合、Gemini 與 ComfyUI 的預設值，以及 key 不會出現在 repr。"""

import pytest
from pydantic import ValidationError

from app.settings import REPO_ROOT, Settings


def test_gemini_defaults() -> None:
    s = Settings(_env_file=None)
    assert (s.agent_mode, s.review_mode) == ('gemini', 'composer')
    assert (s.gemini_llm_model, s.gemini_vlm_model) == ('gemini-3.8-flash', 'gemini-3.8-flash')
    assert (s.gemini_timeout_seconds, s.gemini_max_retries, s.gemini_concurrency) == (120, 3, 4)
    assert (s.gemini_job_budget_usd, s.gemini_monthly_budget_usd) == (1, 20)
    assert s.gemini_api_key.get_secret_value() == ''
    assert s.pricing_file == REPO_ROOT / 'pricing.yaml'


def test_gemini_agent_needs_the_composer_review() -> None:
    with pytest.raises(ValidationError, match='AGENT_MODE=gemini 需要 REVIEW_MODE=composer'):
        Settings(_env_file=None, agent_mode='gemini', review_mode='sim')
    assert Settings(_env_file=None, agent_mode='sim', image_mode='sim', review_mode='sim').review_mode == 'sim'
    assert Settings(_env_file=None, agent_mode='sim', review_mode='composer').agent_mode == 'sim'


def test_comfyui_defaults() -> None:
    s = Settings(_env_file=None)
    assert s.image_mode == 'comfyui'
    assert s.comfyui_url == 'http://127.0.0.1:8188'
    assert s.comfyui_timeout_seconds == 600
    assert s.comfyui_free_after_job is False
    assert s.memory_lock is True
    assert s.comfyui_workflows_dir == REPO_ROOT / 'comfyui' / 'workflows'


def test_comfyui_needs_the_composer_review() -> None:
    """商品底圖（/plate）由 composer 產生，所以 IMAGE_MODE=comfyui 不能搭配 REVIEW_MODE=sim。"""
    with pytest.raises(ValidationError, match='IMAGE_MODE=comfyui 需要 REVIEW_MODE=composer'):
        Settings(_env_file=None, agent_mode='sim', image_mode='comfyui', review_mode='sim')
    assert Settings(_env_file=None, agent_mode='sim', image_mode='sim', review_mode='sim').image_mode == 'sim'
    assert (
        Settings(_env_file=None, agent_mode='sim', image_mode='comfyui', review_mode='composer').image_mode == 'comfyui'
    )


def test_budgets_and_limits_reject_negative_values() -> None:
    for field, value in [
        ('gemini_job_budget_usd', -1),
        ('gemini_monthly_budget_usd', -1),
        ('gemini_max_retries', -1),
        ('gemini_concurrency', 0),
        ('gemini_timeout_seconds', 0),
        ('comfyui_timeout_seconds', 0),
    ]:
        with pytest.raises(ValidationError):
            Settings.model_validate({'agent_mode': 'sim', field: value})


def test_the_api_key_stays_out_of_repr() -> None:
    s = Settings(_env_file=None, gemini_api_key='AIza-test-key-1234')
    assert 'AIza-test-key-1234' not in repr(s)
    assert 'AIza-test-key-1234' not in str(s.model_dump())
    assert s.gemini_api_key.get_secret_value() == 'AIza-test-key-1234'


TOKEN = 't' * 32
SECRET = 's' * 32


def test_automation_defaults_are_off() -> None:
    s = Settings(_env_file=None)
    assert s.automation_token.get_secret_value() == ''
    assert s.job_webhook_url == ''
    assert s.job_webhook_secret.get_secret_value() == ''
    assert s.studio_base_url == 'http://127.0.0.1:3000'
    assert s.automation_templates == ['ig-post', 'story', 'ecom-main']
    assert s.automation_variants == 2
    assert TOKEN not in repr(Settings(_env_file=None, automation_token=TOKEN))


def test_automation_token_must_be_long_enough() -> None:
    with pytest.raises(ValidationError, match='AUTOMATION_TOKEN 至少要 32 個字元'):
        Settings(_env_file=None, automation_token='short')
    assert Settings(_env_file=None, automation_token=TOKEN).automation_token.get_secret_value() == TOKEN


def test_job_webhook_needs_an_http_url_and_a_secret() -> None:
    with pytest.raises(ValidationError, match='JOB_WEBHOOK_URL 只能是 http:// 或 https://'):
        Settings(_env_file=None, job_webhook_url='ftp://n8n/hook', job_webhook_secret=SECRET)
    with pytest.raises(ValidationError, match='JOB_WEBHOOK_SECRET 必填且至少 32 個字元'):
        Settings(_env_file=None, job_webhook_url='http://n8n:5678/webhook/x')
    ok = Settings(_env_file=None, job_webhook_url='http://n8n:5678/webhook/x', job_webhook_secret=SECRET)
    assert ok.job_webhook_url == 'http://n8n:5678/webhook/x'


def test_automation_variants_range() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, automation_variants=9)
