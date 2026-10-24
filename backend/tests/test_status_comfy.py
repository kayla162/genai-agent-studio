"""系統狀態的 ComfyUI 檢查（HTTP 以 respx 重播 tests/data/comfy/）：模擬、連不上、缺少節點或模型、正常。"""

from types import SimpleNamespace
from typing import cast

import httpx
import respx

from app.adapters.comfyui import ComfyClient
from app.api.catalog import _comfyui, _probe
from app.api.services import ApiServices
from app.contract import ComponentStatus
from app.settings import Settings
from tests.fake_comfy import BASE, data, mock_http

LABEL = 'ComfyUI（生圖）'


async def status(settings: Settings, comfy: ComfyClient | None = None) -> ComponentStatus:
    services = cast(ApiServices, SimpleNamespace(settings=settings, comfy=comfy))
    return await _probe('comfyui', LABEL, _comfyui(services))


def comfy_settings() -> Settings:
    return Settings(_env_file=None, image_mode='comfyui', agent_mode='sim', comfyui_url=BASE)


async def test_simulated_mode() -> None:
    result = await status(Settings(_env_file=None, image_mode='sim', agent_mode='sim'))
    assert (result.status, result.detail) == ('sim', '模擬生圖：程序化背景')


async def test_shows_the_gpu_and_the_version() -> None:
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=False) as router:
            mock_http(router)
            result = await status(comfy_settings(), ComfyClient(comfy_settings(), http))
    assert (result.status, result.detail) == ('ok', 'NVIDIA GeForce RTX 3060 Laptop GPU・VRAM 6.0 GB・ComfyUI 0.42.1')


async def test_an_unreachable_comfyui_says_to_start_it() -> None:
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=False) as router:
            router.get(f'{BASE}/system_stats').mock(side_effect=httpx.ConnectError('refused'))
            result = await status(comfy_settings(), ComfyClient(comfy_settings(), http))
    assert (result.status, result.detail) == ('error', 'ComfyUI 沒有回應（http://comfy.test），請先啟動 ComfyUI')


async def test_missing_models_are_listed() -> None:
    info = data('object_info.json')
    info['CheckpointLoaderSimple']['input']['required']['ckpt_name'][0] = []
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=False) as router:
            mock_http(router)
            router.get(f'{BASE}/object_info').respond(json=info)
            result = await status(comfy_settings(), ComfyClient(comfy_settings(), http))
    assert result.status == 'error'
    assert result.detail == (
        'ComfyUI 缺少 workflow 需要的項目：找不到 CheckpointLoaderSimple 的 ckpt_name：sd_xl_base_1.0.safetensors'
        '（安裝方式見 comfyui/README.md）'
    )
