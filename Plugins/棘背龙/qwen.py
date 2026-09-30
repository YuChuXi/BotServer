"""Qwen Image 2.1 生图编辑：触发词与尾行解析、输出尺寸计算、工作流构建与执行。

工作流模板由调用方给出路径（ComfyUI 导出的 API 格式），
节点 id 无关紧要，靠 class_type 与节点标题定位。
"""
import io
import json
import math
import os
import random
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx
from PIL import Image

from .comfy import POLL_TIMEOUT, execute_prompt, fetch_output_images, upload_image

RESOLUTION_STEP = int(os.getenv("COMFY_RESOLUTION_STEP", "32"))  # 分辨率取整步进
# 尾行档位 -> 基准分辨率（1:1 边长）；无档位为默认档
RESOLUTION_LEVELS = {"": 1024, "高清": 1536, "超清": 2048}
QWEN_EDIT_TRIGGER = re.compile(r"☝\ufe0f*\s*([🤓😋])")
QWEN_RATIO_LINE = re.compile(r"^(\d{1,4})[:：](\d{1,4})$")
_RESOLUTION_TOKENS = tuple(k for k in RESOLUTION_LEVELS if k)


def parse_tail_line(line: str) -> Tuple[Optional[Tuple[int, int]], Optional[str]]:
    """从提示词末行提取比例与清晰度档位。

    末行由两个独立参数组成：比例（如 16:9）与档位（如 高清），可单独出现或组合；
    两者皆无时该行不是格式行。

    Args:
        line (str): 提示词末行文本。

    Returns:
        Tuple[Optional[Tuple[int, int]], Optional[str]]: (比例 或 None, 档位 或 None)；
            两者均为 None 表示该行应保留在提示词中。

    Callers:
        - `Plugins/棘背龙/qwen.py:parse_edit_text`
    """
    level = ""
    for token in _RESOLUTION_TOKENS:
        if line.endswith(token):
            level = token
            line = line[: -len(token)].strip()
            break
    if not line:
        return None, level or None
    match = QWEN_RATIO_LINE.match(line)
    if match is None or int(match.group(1)) == 0 or int(match.group(2)) == 0:
        return None, None
    return (int(match.group(1)), int(match.group(2))), level or None


def parse_edit_text(text: str) -> Tuple[str, str, Optional[Tuple[int, int]], int]:
    """解析触发消息，得到提示词、比例与基准分辨率。

    触发词为 ☝️🤓 或 ☝️😋，其后内容为提示词；末行若为比例/档位则从提示词中提出。
    未给出比例时返回 None（由调用方按首图比例或 1:1 处理），未给出档位时取默认档。

    Args:
        text (str): 消息纯文本。

    Returns:
        Tuple[str, str, Optional[Tuple[int, int]], int]: (触发 emoji, 提示词,
            比例 或 None, 基准分辨率)。

    Callers:
        - `Plugins/棘背龙/__init__.py:qwen_edit.handle`
    """
    match = QWEN_EDIT_TRIGGER.search(text)
    if match is None:
        return "", "", None, RESOLUTION_LEVELS[""]

    lines = text[match.end():].strip().splitlines()
    ratio: Optional[Tuple[int, int]] = None
    resolution = RESOLUTION_LEVELS[""]
    if lines:
        tail_ratio, tail_level = parse_tail_line(lines[-1].strip())
        if tail_ratio or tail_level:
            ratio, resolution = tail_ratio, RESOLUTION_LEVELS[tail_level or ""]
            lines = lines[:-1]

    return match.group(1), "\n".join(lines).strip(), ratio, resolution


def calc_resolution(ratio_w: int, ratio_h: int, resolution: int) -> Tuple[int, int]:
    """按比例计算总像素约 resolution² 的输出尺寸。

    宽高均取 RESOLUTION_STEP 的倍数，语义同 TextEncodeQwenImage21 的
    resolution 参数（约 resolution × resolution 像素）。

    Args:
        ratio_w (int): 比例宽。
        ratio_h (int): 比例高。
        resolution (int): 基准分辨率（1:1 边长）。

    Returns:
        Tuple[int, int]: (宽, 高)，均为 RESOLUTION_STEP 的倍数且不小于该步进。

    Callers:
        - `Plugins/棘背龙/qwen.py:run_edit`
    """
    scale = resolution / math.sqrt(ratio_w * ratio_h)
    width = max(RESOLUTION_STEP, round(scale * ratio_w / RESOLUTION_STEP) * RESOLUTION_STEP)
    height = max(RESOLUTION_STEP, round(scale * ratio_h / RESOLUTION_STEP) * RESOLUTION_STEP)
    return width, height


def image_size(data: bytes) -> Tuple[int, int]:
    """读取图片的像素宽高。

    Args:
        data (bytes): 图片字节。

    Returns:
        Tuple[int, int]: (宽, 高)。

    Callers:
        - `Plugins/棘背龙/qwen.py:run_edit`
    """
    with Image.open(io.BytesIO(data)) as im:
        return im.width, im.height


def find_node(
    workflow: Dict[str, Any],
    class_type: str,
    title: Optional[str] = None,
    required: bool = True,
) -> Optional[str]:
    """按 class_type 与可选标题定位节点 id，使节点 id 变化不影响适配。

    Args:
        workflow (Dict[str, Any]): ComfyUI API 格式工作流。
        class_type (str): 节点类名。
        title (Optional[str]): 限定节点标题；None 表示不限定。
        required (bool): 未找到时是否抛错。

    Returns:
        Optional[str]: 数字序最小的匹配节点 id；required=False 且未找到时为 None。

    Raises:
        KeyError: required=True 且工作流中无匹配节点。

    Callers:
        - `Plugins/棘背龙/qwen.py:build_workflow`
    """
    nids = [
        nid
        for nid, node in workflow.items()
        if isinstance(node, dict)
        and node.get("class_type") == class_type
        and (title is None or node.get("_meta", {}).get("title") == title)
    ]
    if not nids:
        if required:
            where = f" class_type={class_type}" + (f" title={title}" if title else "")
            raise KeyError(f"工作流中找不到节点:{where}")
        return None
    return sorted(nids, key=int)[0]


def build_workflow(
    prompt: str,
    image_names: List[str],
    width: int,
    height: int,
    resolution: int,
    workflow_json: str,
) -> Dict[str, Any]:
    """构建本次生图的工作流。

    - 用户提示词填入标题为“提示词”的 PrimitiveStringMultiline
    - 参考图接 TextEncodeQwenImage21 的 images.image_1..N（重写版另接 OllamaImages
      的 images.image0..N-1）。标题以“输入图”开头的 LoadImage 是占位节点，由代码删除
      重建，其下游中转节点（如保留 alpha 的 JoinImageWithAlpha）一并删除后按序重建；
      其余 LoadImage（模板作者自备的底图）一律保留
    - 无参考图且 OllamaImages 已无底图输入时，删除该节点及其引用，LLM 改为纯文本改写
    - 宽高填入标题为“宽度”/“高度”的 PrimitiveInt，resolution 填入 TextEncode，
      随机 seed 填入 SeedNode

    Args:
        prompt (str): 用户提示词。
        image_names (List[str]): 已上传到 ComfyUI input 的参考图文件名。
        width (int): 输出图宽度。
        height (int): 输出图高度。
        resolution (int): TextEncodeQwenImage21 的参考图处理基准。
        workflow_json (str): 工作流模板路径，见 QWEN_WORKFLOW_JSONS。

    Returns:
        Dict[str, Any]: 可提交至 ComfyUI /prompt 的工作流。

    Raises:
        KeyError: 模板缺少必需节点（如“提示词”、宽度等）。

    Callers:
        - `Plugins/棘背龙/qwen.py:run_edit`
    """
    with open(workflow_json, "r", encoding="utf-8") as f:
        workflow = json.load(f)

    prompt_nid = find_node(workflow, "PrimitiveStringMultiline", "提示词")
    text_nid = find_node(workflow, "TextEncodeQwenImage21")
    ocr_nid = find_node(workflow, "OllamaImages", required=False)
    width_nid = find_node(workflow, "PrimitiveInt", "宽度")
    height_nid = find_node(workflow, "PrimitiveInt", "高度")
    seed_nid = find_node(workflow, "SeedNode")

    workflow[prompt_nid]["inputs"]["value"] = prompt

    enc = workflow[text_nid]["inputs"]
    enc["resolution"] = resolution
    ocr = workflow[ocr_nid]["inputs"] if ocr_nid is not None else None

    # 删除占位参考图及其下游中转节点：占位可能经中转节点（如 JoinImageWithAlpha）
    # 再接入锚点，故从占位集合沿引用链向下游传播，输入完全来自待删集合的非锚点节点一并删除
    placeholders = {
        nid
        for nid, node in workflow.items()
        if isinstance(node, dict)
        and node.get("class_type") == "LoadImage"
        and str(node.get("_meta", {}).get("title", "")).startswith("输入图")
    }
    anchors = {text_nid, ocr_nid} - {None}

    def is_link(value: Any) -> bool:
        """判断输入值是否为节点连线（[节点 id, 输出槽]）。"""
        return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)

    doomed = set(placeholders)
    while True:
        derived = {
            nid
            for nid, node in workflow.items()
            if nid not in doomed
            and nid not in anchors
            and isinstance(node, dict)
            and node.get("inputs")
            and all(is_link(v) and v[0] in doomed for v in node["inputs"].values())
        }
        if not derived:
            break
        doomed |= derived

    for inputs in (enc, ocr):
        if inputs is None:
            continue
        for key in [k for k in inputs if is_link(inputs[k]) and inputs[k][0] in doomed]:
            del inputs[key]
    for nid in doomed:
        workflow.pop(nid, None)

    # 参考图由代码新建，接在各锚点序列的下一个编号（模板自备的底图接线保持原位）。
    # LoadImage 槽 0 是 IMAGE、槽 1 是 alpha（MASK），经 JoinImageWithAlpha 合并为
    # RGBA 后接入锚点，透明信息对编码器与 LLM 均可见
    enc_index = _next_index(enc, "images.image_", 1)
    next_id = max((int(nid) for nid in workflow if str(nid).isdigit()), default=0) + 1
    for i, name in enumerate(image_names):
        load_id, join_id = str(next_id), str(next_id + 1)
        next_id += 2
        workflow[load_id] = {
            "inputs": {"image": name},
            "class_type": "LoadImage",
            "_meta": {"title": f"输入图{i + 1}"},
        }
        workflow[join_id] = {
            "inputs": {"image": [load_id, 0], "alpha": [load_id, 1]},
            "class_type": "JoinImageWithAlpha",
            "_meta": {"title": f"合并图像Alpha{i + 1}"},
        }
        enc[f"images.image_{enc_index + i}"] = [join_id, 0]
        if ocr is not None:
            ocr[f"images.image{_next_index(ocr, 'images.image', 0)}"] = [join_id, 0]

    if ocr is not None and not ocr:
        for node in workflow.values():
            if isinstance(node, dict):
                for key in [
                    k
                    for k, v in node.get("inputs", {}).items()
                    if is_link(v) and v[0] == ocr_nid
                ]:
                    del node["inputs"][key]
        workflow.pop(ocr_nid, None)

    workflow[width_nid]["inputs"]["value"] = width
    workflow[height_nid]["inputs"]["value"] = height
    workflow[seed_nid]["inputs"]["seed"] = random.randint(0, 2**32 - 1)
    return workflow


def _next_index(inputs: Dict[str, Any], prefix: str, default: int) -> int:
    """取输入键中形如 prefix + 数字 的最大编号加一，无匹配时返回 default。

    Args:
        inputs (Dict[str, Any]): 节点的 inputs 字典。
        prefix (str): 键前缀，如 "images.image_"。
        default (int): 无匹配键时的起始编号。

    Returns:
        int: 下一个可用编号。

    Callers:
        - `Plugins/棘背龙/qwen.py:build_workflow`
    """
    nums = [int(k[len(prefix):]) for k in inputs if k.startswith(prefix)]
    return max(nums) + 1 if nums else default


async def run_edit(
    prompt: str,
    img_files: List[Tuple[bytes, str]],
    ratio: Optional[Tuple[int, int]],
    resolution: int,
    workflow_json: str,
) -> List[bytes]:
    """执行一次生图编辑：上传参考图、构建并提交工作流、取回输出图。

    Args:
        prompt (str): 用户提示词。
        img_files (List[Tuple[bytes, str]]): 参考图 (字节, 文件名) 列表。
        ratio (Optional[Tuple[int, int]]): 宽高比例；None 时有图用首图比例，无图 1:1。
        resolution (int): 基准分辨率档位（1:1 边长）。
        workflow_json (str): 工作流模板路径。

    Returns:
        List[bytes]: 输出图片字节列表。

    Raises:
        httpx.HTTPError: 与 ComfyUI 交互失败。
        KeyError: 模板缺少契约节点。

    Callers:
        - `Plugins/棘背龙/__init__.py:qwen_edit.handle`
    """
    if ratio is None:
        ratio = image_size(img_files[0][0]) if img_files else (1, 1)

    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0), verify=False) as client:
        image_names = [await upload_image(client, data, name) for data, name in img_files]
        width, height = calc_resolution(*ratio, resolution)
        workflow = build_workflow(
            prompt, image_names, width, height, resolution, workflow_json
        )
        prompt_id = await execute_prompt(client, workflow, timeout=POLL_TIMEOUT)
        return await fetch_output_images(client, prompt_id)
