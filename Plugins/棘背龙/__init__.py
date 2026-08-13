# plugins/comfy_runner/__init__.py
import asyncio
import base64
import json
import os
import io
from PIL import Image
import uuid
import random
from typing import Dict, Any, Tuple, List

import httpx
from nonebot import on_regex
from nonebot.adapters.onebot.v11 import (
    Bot,
    Event,
    MessageSegment,
    GroupMessageEvent,
    PrivateMessageEvent,
)
from nonebot import logger

# ===== 配置 =====
COMFY_SERVER = os.getenv(
    "COMFY_SERVER", "https://10.147.20.20:48189"
)  # ComfyUI 服务地址
POLL_INTERVAL = float(os.getenv("COMFY_POLL_INTERVAL", "0.3"))  # 轮询间隔秒
POLL_TIMEOUT = int(os.getenv("COMFY_POLL_TIMEOUT", "600"))  # 超时秒
SEND_JPEG_QUALITY = int(os.getenv("SEND_JPEG_QUALITY", "45"))  # 发送 JPEG 时的质量
WORKFLOW_API_JSONS = {
    "哈气": os.path.join(os.path.dirname(__file__), "workflow_jibeilong.json"),
    "鼬": os.path.join(os.path.dirname(__file__), "workflow_you.json"),
    "冲": os.path.join(os.path.dirname(__file__), "workflow_chong.json"),
    "超": os.path.join(os.path.dirname(__file__), "workflow_qiaolima.json"),
    "强": os.path.join(os.path.dirname(__file__), "workflow_qiang.json"),
}


def qq_avatar_url(qq_id: str, size: int = 640) -> str:
    # 你也可以换成自己的头像服务
    return f"https://q1.qlogo.cn/g?b=qq&nk={qq_id}&s={size}"


# haqi = on_regex("哈气|哈!|哈！", block=True, priority=10)

# @haqi.handle()
# async def _(bot: Bot, event: Event):
#     if not is_allow_session(event):
#         return

#     qq_id = getattr(event, "user_id", None) or event.get_user_id()

#     src_url = qq_avatar_url(str(qq_id))

#     img_bytes, filename = await download_image_httpx(src_url)
#     images = await run_comfy_workflow_httpx(img_bytes, filename, type="哈气")

#     if not images:
#         return

#     b64 = base64.b64encode(images[0]).decode()
#     await haqi.send(MessageSegment.image(f"base64://{b64}"), reply_message=True)

you = on_regex("鼬", block=True, priority=10)
@you.handle()
async def _(bot: Bot, event: Event):
    if not is_allow_session(event):
        return

    qq_id = getattr(event, "user_id", None) or event.get_user_id()

    src_url = qq_avatar_url(str(qq_id))

    img_bytes, filename = await download_image_httpx(src_url)
    images = await run_comfy_workflow_httpx(img_bytes, filename, type="鼬")

    if not images:
        return

    b64 = base64.b64encode(images[0]).decode()
    await you.send(MessageSegment.image(f"base64://{b64}"), reply_message=True)

# chong = on_regex("冲!|冲！", block=True, priority=10)
# @chong.handle()
# async def _(bot: Bot, event: Event):
#     if not is_allow_session(event):
#         return

#     qq_id = getattr(event, "user_id", None) or event.get_user_id()

#     src_url = qq_avatar_url(str(qq_id))

#     img_bytes, filename = await download_image_httpx(src_url)
#     images = await run_comfy_workflow_httpx(img_bytes, filename, type="冲")

#     if not images:
#         return

#     b64 = base64.b64encode(images[0]).decode()
#     await chong.send(MessageSegment.image(f"base64://{b64}"), reply_message=True)

# qiaolima = on_regex("我超|超!|超！|敲里", block=True, priority=10)
# @qiaolima.handle()
# async def _(bot: Bot, event: Event):
#     if not is_allow_session(event):
#         return

#     qq_id = getattr(event, "user_id", None) or event.get_user_id()

#     src_url = qq_avatar_url(str(qq_id))

#     img_bytes, filename = await download_image_httpx(src_url)
#     images = await run_comfy_workflow_httpx(img_bytes, filename, type="超")

#     if not images:
#         return

#     b64 = base64.b64encode(images[0]).decode()
#     await qiaolima.send(MessageSegment.image(f"base64://{b64}"), reply_message=True)

qiang = on_regex("这么强|强强|虽虽|<\(º0º\)>|弓虽", block=True, priority=10)


@qiang.handle()
async def _(bot: Bot, event: Event):
    if not is_allow_session(event):
        return

    qq_id = getattr(event, "user_id", None) or event.get_user_id()

    src_url = qq_avatar_url(str(qq_id))

    img_bytes, filename = await download_image_httpx(src_url)
    images = await run_comfy_workflow_httpx(img_bytes, filename, type="强")

    if not images:
        return

    b64 = base64.b64encode(images[0]).decode()
    await qiang.send(MessageSegment.image(f"base64://{b64}"), reply_message=True)


# ================= 具体实现（httpx 版本） =================


async def run_comfy_workflow_httpx(
    img_bytes: bytes, filename: str, type: str
) -> List[bytes]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0), verify=False) as client:
        # 1) 上传原图到 ComfyUI（落在 input）
        up_name, up_sub, up_type = await upload_to_comfy_httpx(
            client, img_bytes, filename
        )

        # 2) 加载并修补 API 工作流（把 LoadImage 的 image/subfolder/type 指向刚上传的图）
        prompt = await load_and_patch_workflow_api(
            WORKFLOW_API_JSONS[type], uploaded=(up_name, up_sub, up_type)
        )

        # 3) 提交队列
        client_id = str(uuid.uuid4())
        prompt_id = await queue_prompt_httpx(client, prompt, client_id)

        # 4) 轮询 history，直到有输出或超时
        await wait_until_finished_poll_httpx(
            client, prompt_id, interval=POLL_INTERVAL, timeout=POLL_TIMEOUT
        )

        # 5) 拉取输出图片字节
        images = await fetch_images_from_history_httpx(client, prompt_id)
    return images


async def download_image_httpx(url: str) -> Tuple[bytes, str]:
    async with httpx.AsyncClient(verify=False) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.content
        name = url.split("?")[0].split("/")[-1] or "avatar.jpg"
        if "." not in name:
            name += ".jpg"
        return data, name


async def upload_to_comfy_httpx(
    client: httpx.AsyncClient, img_bytes: bytes, filename: str
) -> Tuple[str, str, str]:
    """
    POST /upload/image
    返回 (name, subfolder, type)
    """
    files = {"image": (filename, img_bytes, "image/jpeg")}
    # 如需覆盖或指定子目录，也可加入 data={"overwrite": "true", "subfolder": "", "type": "input"}
    r = await client.post(
        f"{COMFY_SERVER}/upload/image", files=files
    )  # , data={"subfolder": "qbot", "type": "input"})
    r.raise_for_status()
    j = r.json()
    name = j.get("name") or j.get("filename") or filename
    subfolder = j.get("subfolder", "")
    ftype = j.get("type", "input")
    return name, subfolder, ftype


async def load_and_patch_workflow_api(
    path: str, uploaded: Tuple[str, str, str]
) -> Dict[str, Any]:
    """
    读取“Save (API format)”导出的 JSON，更新所有 LoadImage 节点的 image/subfolder/type 字段
    """
    with open(path, "r", encoding="utf-8") as f:
        prompt = json.load(f)

    name, sub, typ = uploaded
    nodes = (
        prompt.get("nodes")
        if isinstance(prompt, dict) and "nodes" in prompt
        else prompt
    )
    if not isinstance(nodes, dict):
        return prompt  # 非预期结构也原样返回

    changed = 0
    for _nid, node in nodes.items():
        if isinstance(node, dict):
            class_type = (node.get("class_type") or "").lower()
            if class_type == "loadimage":
                inputs = node.setdefault("inputs", {})
                inputs["image"] = name
                inputs["subfolder"] = sub
                inputs["type"] = typ
                changed += 1

            if class_type == "ksampler":
                seed = random.randint(0, 2**32 - 1)
                inputs = node.setdefault("inputs", {})
                inputs["seed"] = seed

    return prompt


async def queue_prompt_httpx(
    client: httpx.AsyncClient, prompt: Dict[str, Any], client_id: str
) -> str:
    payload = {"prompt": prompt, "client_id": client_id}
    r = await client.post(f"{COMFY_SERVER}/prompt", json=payload)
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise RuntimeError(f"提交失败: {j}")
    return j["prompt_id"]


async def wait_until_finished_poll_httpx(
    client: httpx.AsyncClient, prompt_id: str, interval: float = 1.5, timeout: int = 600
):
    """
    纯 httpx 轮询 /history/{prompt_id}，直到能拿到 outputs 或超时。
    """
    deadline = asyncio.get_event_loop().time() + timeout
    url = f"{COMFY_SERVER}/history/{prompt_id}"

    while True:
        if asyncio.get_event_loop().time() > deadline:
            # 超时不直接失败：后面 fetch_images 会再尝试一次读取
            break

        try:
            r = await client.get(url)
            if r.status_code == 200:
                j = r.json()
                entry = j.get(prompt_id, {})
                outputs = entry.get("outputs", {})
                if outputs:
                    # 已有输出，结束等待
                    break
        except httpx.HTTPError:
            # 服务器还没产出记录或短暂错误，忽略
            pass

        await asyncio.sleep(interval)


async def fetch_images_from_history_httpx(
    client: httpx.AsyncClient, prompt_id: str
) -> List[bytes]:
    r = await client.get(f"{COMFY_SERVER}/history/{prompt_id}")
    r.raise_for_status()
    j = r.json()

    result: List[bytes] = []
    entry = j.get(prompt_id, {})
    outputs = entry.get("outputs", {})

    for _node_id, arr in (outputs or {}).items():
        if not isinstance(arr, list):
            arr = [arr]
        for out in arr:
            for img in out.get("images") or []:
                params = {
                    "filename": img.get("filename") or img.get("name"),
                    "subfolder": img.get("subfolder", ""),
                    "type": img.get("type", "output"),
                }
                resp = await client.get(f"{COMFY_SERVER}/view", params=params)
                resp.raise_for_status()
                result.append(resp.content)

    return result


def is_allow_session(event: Event) -> bool:
    """
    检查事件是否允许处理。
    """
    allowed_qqs = {"3619545924"}

    allowed_groups = {
        "703195149",
        "980315536",
        "871345452",
        "782870715",
        "1082347712",
        "853603766",
        "1081450195",
    }

    if isinstance(event, GroupMessageEvent) and (
        str(event.group_id) in allowed_groups or str(event.user_id) in allowed_qqs
    ):
        return True

    if isinstance(event, PrivateMessageEvent) and str(event.user_id) in allowed_qqs:
        return True

    return False


def compress_for_send(img_bytes: bytes) -> tuple[bytes, str]:
    """
    返回 (compressed_bytes, ext)，ext 为 'jpg' 或 'png'
    """
    im = Image.open(io.BytesIO(img_bytes))
    im.load()  # 确保已解码

    buf = io.BytesIO()

    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    im.save(buf, format="JPEG", quality=SEND_JPEG_QUALITY, optimize=True)
    return buf.getvalue(), "jpg"
