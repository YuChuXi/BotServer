"""旧头像工作流：下载 QQ 头像，按模板生成图片。

模板为 ComfyUI 导出的 API 格式 JSON，其中的 LoadImage 由代码指向发送者头像。
"""
import json
import random
import uuid
from typing import Any, Dict, List, Tuple

import httpx

from .comfy import POLL_TIMEOUT, execute_prompt, fetch_output_images, upload_image


async def download_avatar(qq_id: str, size: int = 640) -> Tuple[bytes, str]:
    """下载 QQ 头像。

    Args:
        qq_id (str): QQ 号。
        size (int): 头像尺寸档位。

    Returns:
        Tuple[bytes, str]: (图片字节, uuid 文件名)。

    Raises:
        httpx.HTTPError: 请求失败或响应状态非 2xx。

    Callers:
        - `Plugins/棘背龙/__init__.py:_register_avatar`
    """
    async with httpx.AsyncClient(verify=False) as client:
        r = await client.get(f"https://q1.qlogo.cn/g?b=qq&nk={qq_id}&s={size}")
        r.raise_for_status()
        return r.content, f"{uuid.uuid4().hex}.jpg"


def patch_workflow(path: str, image_name: str) -> Dict[str, Any]:
    """读取模板，把其中 LoadImage 指向已上传的图片，并随机化 KSampler 种子。

    Args:
        path (str): 模板路径。
        image_name (str): 已上传到 ComfyUI input 的图片文件名。

    Returns:
        Dict[str, Any]: 可提交至 ComfyUI /prompt 的工作流。

    Raises:
        OSError: 模板读取失败。

    Callers:
        - `Plugins/棘背龙/avatar.py:run_avatar_workflow`
    """
    with open(path, "r", encoding="utf-8") as f:
        workflow = json.load(f)
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        class_type = (node.get("class_type") or "").lower()
        if class_type == "loadimage":
            node.setdefault("inputs", {})["image"] = image_name
        elif class_type == "ksampler":
            node.setdefault("inputs", {})["seed"] = random.randint(0, 2**32 - 1)
    return workflow


async def run_avatar_workflow(
    img_bytes: bytes, filename: str, template: str
) -> List[bytes]:
    """上传头像并按模板生成图片。

    Args:
        img_bytes (bytes): 头像图片字节。
        filename (str): 上传文件名。
        template (str): 模板的绝对路径。

    Returns:
        List[bytes]: 输出图片字节列表。

    Raises:
        httpx.HTTPError: 与 ComfyUI 交互失败。

    Callers:
        - `Plugins/棘背龙/__init__.py:_register_avatar`
    """
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0), verify=False) as client:
        image_name = await upload_image(client, img_bytes, filename)
        workflow = patch_workflow(template, image_name)
        prompt_id = await execute_prompt(client, workflow, timeout=POLL_TIMEOUT)
        return await fetch_output_images(client, prompt_id)
