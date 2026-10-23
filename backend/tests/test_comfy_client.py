"""ComfyClient：HTTP 以 respx 重播、WebSocket 以本機的假伺服器送出錄製的訊息（tests/fake_comfy.py）。
不需要 GPU、ComfyUI 與資料庫。"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx

from app.adapters.comfyui import ComfyClient, ComfyError, ComfyExecutionError, ComfyStats
from app.pipeline.ports import JobCancelled
from app.settings import REPO_ROOT, Settings
from tests.fake_comfy import BASE, PROMPT_ID, FakeWebSocket, messages, mock_http, png
from tests.fake_run import FakeRun

WORKFLOW: dict[str, Any] = json.loads(
    (REPO_ROOT / 'comfyui' / 'workflows' / 'product_scene_v1.json').read_text('utf-8')
)
#: 底圖與遮罩的檔名是每個任務上傳的，不在 ComfyUI 的清單裡
IMAGES = frozenset({('5', 'image'), ('6', 'image')})


def settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, image_mode='comfyui', agent_mode='sim', comfyui_url=BASE, **overrides)


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


Progress = list[tuple[str, int, int]]


async def run(client: ComfyClient, fake: FakeRun | None = None) -> tuple[bytes, float, Progress]:
    progress: Progress = []

    async def on_progress(node: str, step: int, total: int) -> None:
        progress.append((node, step, total))

    out = await client.run(WORKFLOW, fake or FakeRun(), on_progress)
    return out.png, out.seconds, progress


async def test_runs_a_prompt_reports_its_progress_and_downloads_the_image(http: httpx.AsyncClient) -> None:
    image = png((32, 32), (10, 20, 30))
    ws = FakeWebSocket(messages('ws-success.json'))
    with respx.mock(assert_all_called=False) as router:
        routes = mock_http(router, image=image)
        async with ws.serving():
            client = ComfyClient(settings(), http, connect_ws=ws.connect)
            data, seconds, progress = await run(client)
    assert data == image
    assert seconds >= 0
    # 其他 prompt 的進度不算
    assert progress == [('9', 1, 3), ('9', 2, 3), ('9', 3, 3)]
    sent = json.loads(routes['prompt'].calls.last.request.content)
    assert sent['prompt'] == WORKFLOW
    assert ws.paths == [f'/ws?clientId={sent["client_id"]}']
    assert dict(routes['view'].calls.last.request.url.params) == {
        'filename': 'genai_bg_00001_.png',
        'subfolder': '',
        'type': 'output',
    }


async def test_system_stats_reports_the_gpu_or_a_chinese_reason(http: httpx.AsyncClient) -> None:
    with respx.mock(assert_all_called=False) as router:
        mock_http(router)
        stats = await ComfyClient(settings(), http).system_stats()
    assert stats == ComfyStats(version='0.3.75', gpu='NVIDIA GeForce RTX 3060 Laptop GPU', vram_total=6441926656)
    with respx.mock(assert_all_called=False) as router:
        router.get(f'{BASE}/system_stats').mock(side_effect=httpx.ConnectError('refused'))
        with pytest.raises(ComfyError, match=r'^ComfyUI 沒有回應（http://comfy\.test），請先啟動 ComfyUI$'):
            await ComfyClient(settings(), http).system_stats()


async def test_missing_lists_unknown_nodes_and_models_and_caches_object_info(http: httpx.AsyncClient) -> None:
    broken = json.loads(json.dumps(WORKFLOW))
    broken['1']['inputs']['ckpt_name'] = 'juggernaut.safetensors'
    broken['12'] = {'class_type': 'UltimateSDUpscale', 'inputs': {}}
    with respx.mock(assert_all_called=False) as router:
        routes = mock_http(router)
        client = ComfyClient(settings(), http)
        assert await client.missing(WORKFLOW, ignore=IMAGES) == []
        assert await client.missing(broken, ignore=IMAGES) == [
            '找不到 CheckpointLoaderSimple 的 ckpt_name：juggernaut.safetensors',
            '缺少節點 UltimateSDUpscale',
        ]
        # 不忽略底圖時，上傳的檔名不在清單裡
        assert '找不到 LoadImage 的 image：plate.png' in await client.missing(WORKFLOW)
    assert routes['object_info'].call_count == 1


async def test_a_rejected_prompt_names_the_node_and_the_reason(http: httpx.AsyncClient) -> None:
    from tests.fake_comfy import data

    ws = FakeWebSocket([])
    with respx.mock(assert_all_called=False) as router:
        mock_http(router, prompt_status=400, prompt_body=data('prompt-invalid.json'))
        async with ws.serving():
            with pytest.raises(ComfyError) as info:
                await run(ComfyClient(settings(), http, connect_ws=ws.connect))
    assert not isinstance(info.value, ComfyExecutionError)
    assert str(info.value) == (
        'ComfyUI 拒絕這個 workflow：CheckpointLoaderSimple（節點 1）Value not in list：'
        "ckpt_name: 'sd_xl_base_1.0.safetensors' not in []"
    )


async def test_an_execution_error_names_the_node_type(http: httpx.AsyncClient) -> None:
    ws = FakeWebSocket(messages('ws-error.json'))
    with respx.mock(assert_all_called=False) as router:
        mock_http(router)
        async with ws.serving():
            with pytest.raises(ComfyExecutionError) as info:
                await run(ComfyClient(settings(), http, connect_ws=ws.connect))
    assert (
        str(info.value)
        == 'ComfyUI 執行失敗：KSampler（節點 9）RuntimeError：Expected all tensors to be on the same device'
    )
    assert not info.value.out_of_memory


async def test_running_out_of_gpu_memory_suggests_what_to_do(http: httpx.AsyncClient) -> None:
    ws = FakeWebSocket(messages('ws-oom.json'))
    with respx.mock(assert_all_called=False) as router:
        mock_http(router)
        async with ws.serving():
            with pytest.raises(ComfyExecutionError) as info:
                await run(ComfyClient(settings(), http, connect_ws=ws.connect))
    assert info.value.out_of_memory
    assert str(info.value).startswith('ComfyUI 執行失敗：VAEDecode（節點 10）GPU 記憶體不足')
    assert str(info.value).endswith('請關閉其他使用 GPU 的程式，或以 --lowvram 啟動 ComfyUI')


async def test_falls_back_to_the_history_when_the_websocket_drops(http: httpx.AsyncClient) -> None:
    from tests.fake_comfy import data

    ws = FakeWebSocket(messages('ws-progress-only.json'), close=True)
    with respx.mock(assert_all_called=False) as router:
        routes = mock_http(router, history=[{}, {}, data('history.json')])
        async with ws.serving():
            client = ComfyClient(settings(), http, connect_ws=ws.connect, poll_interval=0.01)
            image, _, progress = await run(client)
    assert image == png()
    assert progress == [('9', 1, 3)]
    # 兩次還沒完成，第三次完成；下載前不再重查
    assert routes['history'].call_count == 3


async def test_cancelling_interrupts_the_prompt_and_drops_it_from_the_queue(http: httpx.AsyncClient) -> None:
    ws = FakeWebSocket(messages('ws-progress-only.json'))
    fake = FakeRun()
    with respx.mock(assert_all_called=False) as router:
        routes = mock_http(router)
        async with ws.serving():
            task = asyncio.create_task(run(ComfyClient(settings(), http, connect_ws=ws.connect), fake))
            await asyncio.sleep(0.2)
            fake.cancelled = True
            with pytest.raises(JobCancelled):
                await task
    assert json.loads(routes['interrupt'].calls.last.request.content) == {'prompt_id': PROMPT_ID}
    assert json.loads(routes['queue'].calls.last.request.content) == {'delete': [PROMPT_ID]}


async def test_a_prompt_that_takes_too_long_is_interrupted(http: httpx.AsyncClient) -> None:
    ws = FakeWebSocket(messages('ws-progress-only.json'))
    with respx.mock(assert_all_called=False) as router:
        routes = mock_http(router)
        async with ws.serving():
            client = ComfyClient(settings(comfyui_timeout_seconds=0.2), http, connect_ws=ws.connect)
            with pytest.raises(ComfyError, match=r'^ComfyUI 沒有在 0\.2 秒內完成（prompt p-0001）$'):
                await run(client)
    assert routes['interrupt'].called
    assert routes['queue'].called


async def test_upload_overwrites_the_named_image_and_free_unloads_the_models(http: httpx.AsyncClient) -> None:
    with respx.mock(assert_all_called=False) as router:
        routes = mock_http(router)
        client = ComfyClient(settings(), http)
        assert await client.upload('job_t_r1_ig-post_plate.png', png()) == 'job_t_r1_ig-post_plate.png'
        await client.free()
    body = routes['upload'].calls.last.request.content
    assert b'filename="job_t_r1_ig-post_plate.png"' in body
    assert b'name="overwrite"\r\n\r\ntrue' in body
    assert json.loads(routes['free'].calls.last.request.content) == {'unload_models': True, 'free_memory': True}
