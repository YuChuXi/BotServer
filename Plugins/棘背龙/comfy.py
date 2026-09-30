"""ComfyUI 客户端：上传参考图、提交工作流、经 WebSocket 等待执行完成并取回输出图。

本模块只负责与 ComfyUI 的传输交互，不感知具体工作流的语义。
"""
import asyncio
import json
import os
import ssl
import uuid
from typing import Any, Dict, List, Optional

import httpx
import websockets
from nonebot import logger

COMFY_SERVER = os.getenv(
    "COMFY_SERVER", "https://10.147.20.20:48189"
)  # ComfyUI 服务地址
POLL_TIMEOUT = int(os.getenv("COMFY_POLL_TIMEOUT", "3600"))  # 等待执行完成的超时秒


def _ws_url(client_id: str) -> str:
    """拼接 ComfyUI 的 WebSocket 地址。

    Args:
        client_id (str): 本次任务的客户端标识。

    Returns:
        str: 与 COMFY_SERVER 协议对应的 ws/wss 地址。

    Callers:
        - `Plugins/棘背龙/comfy.py:execute_prompt`
    """
    base = COMFY_SERVER
    if base.startswith("https://"):
        base = "wss://" + base[len("https://"):]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://"):]
    return f"{base}/ws?clientId={client_id}"


def _ws_ssl_context() -> Optional[ssl.SSLContext]:
    """构造 WebSocket 的 SSL 上下文。

    Returns:
        Optional[ssl.SSLContext]: COMFY_SERVER 为 https 时返回不校验证书的上下文，
            否则返回 None。

    Callers:
        - `Plugins/棘背龙/comfy.py:execute_prompt`
    """
    if COMFY_SERVER.startswith("https://"):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return None


async def upload_image(client: httpx.AsyncClient, img_bytes: bytes, filename: str) -> str:
    """上传图片到 ComfyUI 的 input 目录。

    Args:
        client (httpx.AsyncClient): HTTP 客户端。
        img_bytes (bytes): 图片字节。
        filename (str): 上传时使用的文件名。

    Returns:
        str: ComfyUI 保存的文件名，供 LoadImage 节点引用。

    Raises:
        httpx.HTTPError: 请求失败或响应状态非 2xx。

    Callers:
        - `Plugins/棘背龙/qwen.py:run_edit`
    """
    r = await client.post(
        f"{COMFY_SERVER}/upload/image",
        files={"image": (filename, img_bytes, "image/jpeg")},
    )
    r.raise_for_status()
    j = r.json()
    return j.get("name") or j.get("filename") or filename


async def queue_prompt(
    client: httpx.AsyncClient, prompt: Dict[str, Any], client_id: str
) -> str:
    """把工作流提交到 ComfyUI 的队列。

    Args:
        client (httpx.AsyncClient): HTTP 客户端。
        prompt (Dict[str, Any]): ComfyUI API 格式工作流。
        client_id (str): 客户端标识。

    Returns:
        str: ComfyUI 分配的 prompt_id。

    Raises:
        httpx.HTTPError: 请求失败或响应状态非 2xx。
        RuntimeError: 服务端拒绝该工作流。

    Callers:
        - `Plugins/棘背龙/comfy.py:execute_prompt`
    """
    r = await client.post(
        f"{COMFY_SERVER}/prompt", json={"prompt": prompt, "client_id": client_id}
    )
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise RuntimeError(f"ComfyUI 拒绝工作流: {j}")
    return j["prompt_id"]


async def execute_prompt(
    client: httpx.AsyncClient, prompt: Dict[str, Any], timeout: int = POLL_TIMEOUT
) -> str:
    """连接 WebSocket 后提交工作流，等待其执行完成。

    先建立 WebSocket 连接再提交队列，保证提交之后的事件全部可达；
    随后持续接收事件，收到完成或出错事件即返回。

    Args:
        client (httpx.AsyncClient): 提交队列使用的 HTTP 客户端。
        prompt (Dict[str, Any]): ComfyUI API 格式工作流。
        timeout (int): 总超时秒数，默认 POLL_TIMEOUT。

    Returns:
        str: ComfyUI 分配的 prompt_id。

    Raises:
        TimeoutError: 超过 timeout 仍未收到完成事件。
        websockets.WebSocketException: WebSocket 建立失败或中断。

    Callers:
        - `Plugins/棘背龙/qwen.py:run_edit`
    """
    client_id = str(uuid.uuid4())
    async with websockets.connect(
        _ws_url(client_id), ssl=_ws_ssl_context(), max_size=None
    ) as ws, asyncio.timeout(timeout):
        prompt_id = await queue_prompt(client, prompt, client_id)
        async for msg in ws:
            if isinstance(msg, bytes):
                continue  # 预览图等二进制帧
            data = json.loads(msg)
            m_data = data.get("data") or {}
            if m_data.get("prompt_id") != prompt_id:
                continue
            m_type = data.get("type")
            if m_type == "execution_error":
                logger.error(f"ComfyUI 执行出错: {m_data}")
                return prompt_id
            if m_type == "execution_success" or (
                m_type == "executing" and m_data.get("node") is None
            ):
                return prompt_id


async def fetch_output_images(
    client: httpx.AsyncClient, prompt_id: str
) -> List[bytes]:
    """从 ComfyUI 的 /history 取回该任务的输出图片字节。

    Args:
        client (httpx.AsyncClient): HTTP 客户端。
        prompt_id (str): ComfyUI 任务 id。

    Returns:
        List[bytes]: 输出图片字节列表，按节点与图片顺序排列。

    Raises:
        httpx.HTTPError: 请求失败或响应状态非 2xx。

    Callers:
        - `Plugins/棘背龙/qwen.py:run_edit`
    """
    r = await client.get(f"{COMFY_SERVER}/history/{prompt_id}")
    r.raise_for_status()
    outputs = r.json().get(prompt_id, {}).get("outputs", {})

    images: List[bytes] = []
    for arr in outputs.values():
        for out in arr if isinstance(arr, list) else [arr]:
            for img in out.get("images") or []:
                resp = await client.get(
                    f"{COMFY_SERVER}/view",
                    params={
                        "filename": img.get("filename") or img.get("name"),
                        "subfolder": img.get("subfolder", ""),
                        "type": img.get("type", "output"),
                    },
                )
                resp.raise_for_status()
                images.append(resp.content)
    return images
