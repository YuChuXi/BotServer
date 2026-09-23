# plugins/comfy_runner/__init__.py
import asyncio
import base64
import json
import math
import os
import io
import re
import ssl
from PIL import Image
import uuid
import random
from typing import Dict, Any, Tuple, List, Optional

import httpx
import websockets
from nonebot import on_regex
from nonebot.rule import to_me
from nonebot.adapters.onebot.v11 import (
    Bot,
    Event,
    Message,
    MessageSegment,
    MessageEvent,
    GroupMessageEvent,
    PrivateMessageEvent,
)
from nonebot import logger

from Scripts.Config import config

# ===== 配置 =====
COMFY_SERVER = os.getenv(
    "COMFY_SERVER", "https://10.147.20.20:48189"
)  # ComfyUI 服务地址
POLL_TIMEOUT = int(os.getenv("COMFY_POLL_TIMEOUT", "600"))  # 等待生成完成的超时秒
SEND_JPEG_QUALITY = int(os.getenv("SEND_JPEG_QUALITY", "45"))  # 发送 JPEG 时的质量
RESOLUTION_STEP = int(os.getenv("COMFY_RESOLUTION_STEP", "32"))  # 分辨率取整步进
# 比例行后缀 -> 基准分辨率（1:1 边长）；无后缀为默认档
RESOLUTION_LEVELS = {"": 1024, "高清": 1536, "超清": 2048}
WORKFLOW_API_JSONS = {
    "哈气": os.path.join(os.path.dirname(__file__), "workflow_jibeilong.json"),
    "鼬": os.path.join(os.path.dirname(__file__), "workflow_you.json"),
    "冲": os.path.join(os.path.dirname(__file__), "workflow_chong.json"),
    "超": os.path.join(os.path.dirname(__file__), "workflow_qiaolima.json"),
    "强": os.path.join(os.path.dirname(__file__), "workflow_qiang.json"),
}
QWEN_WORKFLOW_JSONS = {
    "🤓": os.path.join(os.path.dirname(__file__), "workflow_qwenimage21.json"),  # LLM 重写版
    "😋": os.path.join(os.path.dirname(__file__), "workflow_qwenimage21dr.json"),  # 直出版
}
QWEN_EDIT_TRIGGER = re.compile(r"☝\ufe0f*\s*([🤓😋])")
QWEN_RATIO_LINE = re.compile(r"^(\d{1,4})[:：](\d{1,4})\s*(高清|超清)?$")


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

# you = on_regex("鼬", block=True, priority=10)
# @you.handle()
# async def _(bot: Bot, event: Event):
#     if not is_allow_session(event):
#         return

#     qq_id = getattr(event, "user_id", None) or event.get_user_id()

#     src_url = qq_avatar_url(str(qq_id))

#     img_bytes, filename = await download_image_httpx(src_url)
#     images = await run_comfy_workflow_httpx(img_bytes, filename, type="鼬")

#     if not images:
#         return

#     b64 = base64.b64encode(images[0]).decode()
#     await you.send(MessageSegment.image(f"base64://{b64}"), reply_message=True)

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

# qiang = on_regex("这么强|强强|虽虽|<\(º0º\)>|弓虽", block=True, priority=10)


# @qiang.handle()
# async def _(bot: Bot, event: Event):
#     if not is_allow_session(event):
#         return

#     qq_id = getattr(event, "user_id", None) or event.get_user_id()

#     src_url = qq_avatar_url(str(qq_id))

#     img_bytes, filename = await download_image_httpx(src_url)
#     images = await run_comfy_workflow_httpx(img_bytes, filename, type="强")

#     if not images:
#         return

#     b64 = base64.b64encode(images[0]).decode()
#     await qiang.send(MessageSegment.image(f"base64://{b64}"), reply_message=True)


# ===== Qwen 生图编辑：@bot / 回复 + ☝️{🤓|😋}提示词 [宽:高] + 0-10 张图片 =====


# to_me：@机器人 / 回复机器人消息 / 私聊；回复他人消息不算
qwen_edit = on_regex(QWEN_EDIT_TRIGGER.pattern, rule=to_me(), block=True, priority=10)


@qwen_edit.handle()
async def _(bot: Bot, event: MessageEvent):
    if not is_allow_session(event):
        return

    emoji, prompt, ratio, resolution = _parse_qwen_edit_text(event.get_plaintext())

    # 被回复消息的图片排最前，其后是本条消息的图片，共取前 10 张
    img_segs = [s for s in event.get_message() if s.type == "image"]
    if event.reply is not None:
        img_segs = [s for s in event.reply.message if s.type == "image"] + img_segs
    urls = [u for s in img_segs if (u := s.data.get("url") or s.data.get("file"))][:10]

    if not prompt and not urls:
        return

    images = await run_qwen_workflow_httpx(
        prompt, urls, ratio, resolution, QWEN_WORKFLOW_JSONS[emoji]
    )

    if not images:
        return

    await qwen_edit.send(
        Message([MessageSegment.image(f"base64://{base64.b64encode(b).decode()}") for b in images]),
        reply_message=True,
    )


def _parse_qwen_edit_text(
    text: str,
) -> Tuple[str, str, Optional[Tuple[int, int]], int]:
    """
    解析 ☝️{🤓|😋} 后的提示词；若最后一行是 比例（如 16:9，可加 高清/超清），将其提出。
    无比例行时 ratio 为 None（用第一张图比例或 1:1），基准取默认档。
    返回 (触发 emoji, 提示词, 比例或 None, 基准分辨率)。
    """
    m = QWEN_EDIT_TRIGGER.search(text)
    if not m:
        return "", "", None, RESOLUTION_LEVELS[""]

    lines = text[m.end():].strip().splitlines()
    ratio, resolution = None, RESOLUTION_LEVELS[""]
    if lines:
        rm = QWEN_RATIO_LINE.match(lines[-1].strip())
        if rm and int(rm.group(1)) > 0 and int(rm.group(2)) > 0:
            ratio = (int(rm.group(1)), int(rm.group(2)))
            resolution = RESOLUTION_LEVELS.get(rm.group(3) or "", RESOLUTION_LEVELS[""])
            lines = lines[:-1]

    return m.group(1), "\n".join(lines).strip(), ratio, resolution


def calc_resolution(
    ratio_w: int, ratio_h: int, resolution: int, step: int = RESOLUTION_STEP
) -> Tuple[int, int]:
    """
    按比例计算总像素约 resolution² 的分辨率，宽高均取 step 的倍数。
    语义同 ComfyUI 的 resolution 参数：约 resolution x resolution 像素。
    """
    scale = resolution / math.sqrt(ratio_w * ratio_h)
    w = max(step, round(scale * ratio_w / step) * step)
    h = max(step, round(scale * ratio_h / step) * step)
    return w, h


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

        # 3) 通过 WebSocket 提交队列并等待执行完成
        client_id = str(uuid.uuid4())
        prompt_id = await execute_prompt_ws(
            client, prompt, client_id, timeout=POLL_TIMEOUT
        )

        # 4) 拉取输出图片字节
        images = await fetch_images_from_history_httpx(client, prompt_id)
    return images


async def run_qwen_workflow_httpx(
    prompt: str,
    img_urls: List[str],
    ratio: Optional[Tuple[int, int]],
    resolution: int,
    workflow_json: str,
) -> List[bytes]:
    img_files: List[Tuple[bytes, str]] = []
    for url in img_urls:
        try:
            img_files.append(await download_image_httpx(url))
        except Exception as e:
            logger.warning(f"下载参考图失败，已跳过: {url} ({e})")

    # 未指定比例时：有图用第一张图的比例，无图默认 1:1
    if ratio is None:
        ratio = _image_size(img_files[0][0]) if img_files else (1, 1)

    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0), verify=False) as client:
        # 上传参考图到 ComfyUI
        image_names = []
        for data, name in img_files:
            up_name, _, _ = await upload_to_comfy_httpx(client, data, name)
            image_names.append(up_name)

        width, height = calc_resolution(*ratio, resolution)
        workflow = build_qwen_workflow(
            prompt, image_names, width, height, resolution, workflow_json
        )

        client_id = str(uuid.uuid4())
        prompt_id = await execute_prompt_ws(
            client, workflow, client_id, timeout=POLL_TIMEOUT
        )
        return await fetch_images_from_history_httpx(client, prompt_id)


def _image_size(data: bytes) -> Tuple[int, int]:
    with Image.open(io.BytesIO(data)) as im:
        return im.width, im.height


def _find_node(
    workflow: Dict[str, Any], class_type: str, title: Optional[str] = None, required: bool = True
) -> Optional[str]:
    """按 class_type（可选 title）定位节点 id，节点 id 变化不影响适配。

    Args:
        workflow (Dict[str, Any]): ComfyUI API 格式工作流字典。
        class_type (str): 节点类名。
        title (Optional[str]): 限定节点 _meta.title，None 表示不限定。
        required (bool): True 时未找到抛 KeyError，False 时返回 None。

    Returns:
        Optional[str]: 节点 id，数字序最小的一个；required=False 且未找到时为 None。

    Raises:
        KeyError: required=True 且工作流中无匹配节点。

    Callers:
        - `Plugins/棘背龙/__init__.py:build_qwen_workflow`
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
            raise KeyError(f"工作流中找不到 class_type={class_type}" + (f" title={title}" if title else ""))
        return None
    return sorted(nids, key=int)[0]


def build_qwen_workflow(
    prompt: str,
    image_names: List[str],
    width: int,
    height: int,
    resolution: int,
    workflow_json: str,
) -> Dict[str, Any]:
    """构建 Qwen Image 2.1 工作流，两种模板共用本函数：

    - workflow_qwenimage21.json（LLM 重写版）：用户提示词填入 PrimitiveStringMultiline
      （提示词），经 OllamaChat 扩写后进 TextEncodeQwenImage21
    - workflow_qwenimage21dr.json（直出版）：提示词直连 TextEncodeQwenImage21，无 Ollama 节点
    - 0-10 张参考图接 TextEncode 的 images.image_1..N（重写版另接 OllamaImages 的
      images.image0..N-1）。模板中标题为“输入图N”的 LoadImage 是占位节点，由代码重建，
      其下游中转节点（如 JoinImageWithAlpha 保留 alpha）一并删除后按原编号重建接线；
      无参考图且 OllamaImages 无底图时删除该节点
    - 宽高填入 PrimitiveInt（宽度/高度），resolution（TextEncode 参考图基准），随机 seed 填 SeedNode

    Args:
        prompt (str): 用户提示词。
        image_names (List[str]): 已上传到 ComfyUI input 的参考图文件名。
        width (int): 输出图宽度。
        height (int): 输出图高度。
        resolution (int): TextEncodeQwenImage21 的参考图处理基准。
        workflow_json (str): 工作流模板 JSON 路径，见 QWEN_WORKFLOW_JSONS。

    Returns:
        Dict[str, Any]: 可提交至 ComfyUI /prompt 的工作流。

    Raises:
        KeyError: 模板缺少必需节点（如“提示词”、宽度等）。

    Callers:
        - `Plugins/棘背龙/__init__.py:run_qwen_workflow_httpx`
    """
    with open(workflow_json, "r", encoding="utf-8") as f:
        workflow = json.load(f)

    prompt_nid = _find_node(workflow, "PrimitiveStringMultiline", "提示词")
    text_nid = _find_node(workflow, "TextEncodeQwenImage21")
    ocr_nid = _find_node(workflow, "OllamaImages", required=False)
    width_nid = _find_node(workflow, "PrimitiveInt", "宽度")
    height_nid = _find_node(workflow, "PrimitiveInt", "高度")
    seed_nid = _find_node(workflow, "SeedNode")

    workflow[prompt_nid]["inputs"]["value"] = prompt

    enc = workflow[text_nid]["inputs"]
    enc["resolution"] = resolution
    ocr = workflow[ocr_nid]["inputs"] if ocr_nid is not None else None

    # 用户参考图由代码接管：模板中标题为“输入图N”的 LoadImage 是占位节点，
    # 其余 LoadImage（如接在 TextEncode/OllamaImages 上的底图）一律保留不动。
    # 占位节点可能经过中转节点（如 JoinImageWithAlpha 合并 alpha）再接入锚点，
    # 删除时沿引用链向下游传播，输入完全来自待删集合的中转节点一并删除。
    placeholders = {
        nid
        for nid, node in workflow.items()
        if isinstance(node, dict)
        and node.get("class_type") == "LoadImage"
        and str(node.get("_meta", {}).get("title", "")).startswith("输入图")
    }
    anchors = {text_nid, ocr_nid} - {None}

    def _is_link(value: Any) -> bool:
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
            and all(
                _is_link(v) and v[0] in doomed for v in node["inputs"].values()
            )
        }
        if not derived:
            break
        doomed |= derived

    for inputs in (enc, ocr):
        if inputs is None:
            continue
        for key in [k for k in inputs if _is_link(inputs[k]) and inputs[k][0] in doomed]:
            del inputs[key]
    for nid in doomed:
        workflow.pop(nid, None)

    # 新图追加到各序列的下一个编号（底图已有接线保持原位）
    def _next_index(inputs: Dict[str, Any], prefix: str, default: int) -> int:
        nums = [int(k[len(prefix):]) for k in inputs if k.startswith(prefix)]
        return (max(nums) + 1) if nums else default

    enc_i = _next_index(enc, "images.image_", 1)
    next_id = max((int(k) for k in workflow if str(k).isdigit()), default=0) + 1
    for i, name in enumerate(image_names):
        nid = str(next_id)
        next_id += 1
        workflow[nid] = {
            "inputs": {"image": name},
            "class_type": "LoadImage",
            "_meta": {"title": f"输入图{i + 1}"},
        }
        enc[f"images.image_{enc_i + i}"] = [nid, 0]
        if ocr is not None:
            ocr[f"images.image{_next_index(ocr, 'images.image', 0)}"] = [nid, 0]

    # 没有参考图且 OllamaImages 无底图输入时，删除该节点及其全部引用，LLM 纯文本改写
    if ocr is not None and not ocr:
        for node in workflow.values():
            if isinstance(node, dict):
                for key in [
                    k
                    for k, v in node.get("inputs", {}).items()
                    if isinstance(v, list) and len(v) == 2 and v[0] == ocr_nid
                ]:
                    del node["inputs"][key]
        workflow.pop(ocr_nid, None)

    workflow[width_nid]["inputs"]["value"] = width
    workflow[height_nid]["inputs"]["value"] = height
    workflow[seed_nid]["inputs"]["seed"] = random.randint(0, 2**32 - 1)
    return workflow


async def download_image_httpx(url: str) -> Tuple[bytes, str]:
    async with httpx.AsyncClient(verify=False) as client:
        r = await client.get(url)
        r.raise_for_status()
        name = url.split("?")[0].split("/")[-1] or "avatar.jpg"
        if "." not in name:
            name += ".jpg"
        return r.content, name


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


def _comfy_ws_url(client_id: str) -> str:
    base = COMFY_SERVER
    if base.startswith("https://"):
        base = "wss://" + base[len("https://"):]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://"):]
    return f"{base}/ws?clientId={client_id}"


def _comfy_ws_ssl():
    if COMFY_SERVER.startswith("https://"):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return None


async def execute_prompt_ws(
    client: httpx.AsyncClient, prompt: Dict[str, Any], client_id: str, timeout: int = 600
) -> str:
    """连接 ComfyUI WebSocket，提交工作流并等待执行完成。

    先建立 WebSocket 连接再提交队列，保证提交后的推送事件全部可达，
    随后收包直至收到完成或出错事件。总耗时受 timeout 限制。

    Args:
        client (httpx.AsyncClient): 提交队列使用的 HTTP 客户端。
        prompt (Dict[str, Any]): ComfyUI API 格式的工作流。
        client_id (str): WebSocket 客户端标识，需要与提交的队列一致。
        timeout (int): 总超时秒数，默认 600。

    Returns:
        str: ComfyUI 分配的 prompt_id；连接中断或超时以异常传播。

    Raises:
        TimeoutError: 超过 timeout 仍未收到完成事件。
        websockets exceptions: WebSocket 连接建立失败或中断。

    Callers:
        - `Plugins/棘背龙/__init__.py:run_comfy_workflow_httpx`
        - `Plugins/棘背龙/__init__.py:run_qwen_workflow_httpx`
    """
    url = _comfy_ws_url(client_id)
    async with websockets.connect(url, ssl=_comfy_ws_ssl(), max_size=None) as ws, asyncio.timeout(timeout):
        # 先连接后提交，提交之后的事件必然可达
        prompt_id = await queue_prompt_httpx(client, prompt, client_id)

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
                return prompt_id  # 兼容未发送 execution_success 的 ComfyUI 版本


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
    群聊由群配置 enable_image_gen 控制，主机管理员不受限制；私聊仅限主机管理员。
    """
    if isinstance(event, GroupMessageEvent):
        return (
            config.get_group_config(event.group_id).enable_image_gen
            or event.user_id in config.host_admins
        )

    if isinstance(event, PrivateMessageEvent):
        return event.user_id in config.host_admins

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
