"""ComfyUI 的參數對照表（comfyui/workflows/product_scene_v1.params.json）：與前端 buildInjection 用的表
（web/src/lib/agent/comfy.ts，npm run fixtures 匯出成 contracts/fixtures/comfy.json）完全相同，
而且每個參數都對得到 workflow（API 格式）裡的節點與輸入。不需要資料庫與 ComfyUI。"""

import json
from pathlib import Path
from typing import Any

from app.settings import REPO_ROOT
from tests.fixtures import load_fixture

WORKFLOWS = REPO_ROOT / 'comfyui' / 'workflows'
#: 參數型別對應 workflow 裡預設值的 Python 型別
TYPES: dict[str, tuple[type, ...]] = {'string': (str,), 'image': (str,), 'int': (int,), 'float': (int, float)}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def test_the_table_is_the_one_the_frontend_injects() -> None:
    assert load(WORKFLOWS / 'product_scene_v1.params.json') == load_fixture('comfy.json')


def test_every_parameter_points_at_an_input_of_the_workflow() -> None:
    table = load(WORKFLOWS / 'product_scene_v1.params.json')
    workflow = load(WORKFLOWS / table['workflow'])
    labels = [p['label'] for p in table['params']]
    assert len(labels) == len(set(labels))
    for p in table['params']:
        node = workflow.get(p['nodeId'])
        assert node is not None, f'{p["label"]}：workflow 沒有節點 {p["nodeId"]}'
        where = f'{p["label"]}：節點 {p["nodeId"]}（{node["class_type"]}）'
        assert p['input'] in node['inputs'], f'{where}沒有輸入 {p["input"]}'
        current = node['inputs'][p['input']]
        assert isinstance(current, TYPES[p['type']]) and not isinstance(current, bool), (p, current)
        if 'default' in p:
            assert current == p['default'], f'{p["label"]}：workflow 的值 {current!r} 與對照表的預設值不同'


def test_the_workflow_uses_only_built_in_nodes_and_saves_one_image() -> None:
    """自訂節點要先在 comfyui/custom_nodes.md 確認授權（Plan 7 Task 1）；手寫的版本只用 ComfyUI 內建節點。"""
    workflow = load(WORKFLOWS / 'product_scene_v1.json')
    built_in = {
        'CheckpointLoaderSimple',
        'LoraLoader',
        'CLIPTextEncode',
        'LoadImage',
        'LoadImageMask',
        'InpaintModelConditioning',
        'KSampler',
        'VAEDecode',
        'SaveImage',
    }
    assert {n['class_type'] for n in workflow.values()} <= built_in
    assert [n['class_type'] for n in workflow.values()].count('SaveImage') == 1
    # 節點之間的連線都指向存在的節點
    for node in workflow.values():
        for value in node['inputs'].values():
            if isinstance(value, list):
                assert value[0] in workflow
