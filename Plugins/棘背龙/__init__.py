"""棘背龙：ComfyUI 生图插件。

- Qwen 编辑：@机器人（或回复机器人消息）☝️{🤓|😋} 提示词 + 0-10 张参考图，
  群配置开关 `enable_image_gen`
- 旧头像工作流：消息含关键词（如 鼬、强）时以发送者头像出图，
  群配置开关 `enable_avatar_gen`

两个功能的模板均位于 workflows/，由 ComfyUI 导出（API 格式）。
"""
import base64
import os
import uuid
from typing import Awaitable, Callable, List, Literal, Tuple

import httpx
import websockets
from nonebot import logger, on_regex
from nonebot.adapters.onebot.v11 import (
    ActionFailed,
    Bot,
    Event,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from Scripts.Config import config

from .avatar import download_avatar, run_avatar_workflow
from .qwen import QWEN_EDIT_TRIGGER, parse_edit_text, run_edit

WORKFLOWS_DIR = os.path.join(os.path.dirname(__file__), "workflows")
# 触发 emoji -> 模板：🤓 先经本地 LLM 重写提示词，😋 直出
QWEN_WORKFLOW_TEMPLATES = {
    "🤓": "workflow_qwenimage21.json",
    "😋": "workflow_qwenimage21dr.json",
}
# 触发关键词 -> 模板
AVATAR_WORKFLOW_TEMPLATES = {
    # "哈气|哈!|哈！": "workflow_jibeilong.json",
    # "鼬": "workflow_you.json",
    # "冲!|冲！": "workflow_chong.json",
    # "我超|超!|超！|敲里": "workflow_qiaolima.json",
    # r"这么强|强强|虽虽|<\(º0º\)>|弓虽": "workflow_qiang.json",
}

# 群配置中控制各功能的字段名
FeatureSwitch = Literal["enable_image_gen", "enable_avatar_gen"]

# 生图链路（取参考图/下载头像/上传/提交/执行/取回输出）可能抛出的异常
GENERATE_ERRORS = (
    httpx.HTTPError,
    OSError,
    RuntimeError,
    KeyError,
    TimeoutError,
    ValueError,
    websockets.WebSocketException,
)


async def reply_generated(
    matcher: Matcher, generate: Callable[[], Awaitable[List[bytes]]]
) -> None:
    """执行生图流程并回复输出图，失败时向会话发送报错消息。

    Args:
        matcher (Matcher): 响应器，用于发送消息。
        generate (Callable[[], Awaitable[List[bytes]]]): 生图协程工厂，
            返回输出图字节列表；失败时抛出 GENERATE_ERRORS 中的异常。

    Callers:
        - `Plugins/棘背龙/__init__.py:_handle_qwen_edit`
        - `Plugins/棘背龙/__init__.py:_register_avatar`
    """
    try:
        images = await generate()
    except GENERATE_ERRORS as e:
        logger.exception("生图失败")
        await matcher.send(f"生图失败：{e}", reply_message=True)
        return
    if not images:
        await matcher.send("生图失败：ComfyUI 未返回输出图", reply_message=True)
        return
    await matcher.send(
        Message(
            [
                MessageSegment.image(f"base64://{base64.b64encode(b).decode()}")
                for b in images
            ]
        ),
        reply_message=True,
    )


def is_allowed(event: Event, flag: FeatureSwitch) -> bool:
    """判断事件是否允许处理某功能。

    群聊由群配置中名为 flag 的开关控制（见 GroupConfig），主机管理员不受限制；
    私聊仅限主机管理员。

    Args:
        event (Event): 消息事件。
        flag (FeatureSwitch): GroupConfig 中控制该功能的字段名。

    Returns:
        bool: 是否允许处理。

    Callers:
        - `Plugins/棘背龙/__init__.py:_image_gen_rule`
        - `Plugins/棘背龙/__init__.py:_avatar_rule`
    """
    if isinstance(event, GroupMessageEvent):
        group = config.get_group_config(event.group_id)
        return getattr(group, flag) or event.user_id in config.host_admins
    if isinstance(event, PrivateMessageEvent):
        return event.user_id in config.host_admins
    return False


def _image_gen_rule(event: MessageEvent) -> bool:
    """Qwen 编辑的触发条件：to_me 且该会话启用了 enable_image_gen。"""
    return event.to_me and is_allowed(event, "enable_image_gen")


def _avatar_rule(event: MessageEvent) -> bool:
    """旧头像工作流的触发条件：该会话启用了 enable_avatar_gen。"""
    return is_allowed(event, "enable_avatar_gen")


async def fetch_message_image(bot: Bot, ref: str) -> Tuple[bytes, str]:
    """经协议端 get_image 取得消息图片字节。

    图片下载交给协议端完成，bot 不自行访问 QQ 图片 CDN（其校验 Referer，且链接时效短）。

    Args:
        bot (Bot): OneBot V11 Bot 实例。
        ref (str): 图片标识，接受消息段的 file 字段或图片 URL。

    Returns:
        Tuple[bytes, str]: (图片字节, uuid 文件名)。

    Raises:
        RuntimeError: 协议端未返回 base64 字段。
        ActionFailed: 协议端返回失败。
        ValueError: base64 解码失败。

    Callers:
        - `Plugins/棘背龙/__init__.py:qwen_edit.handle`
    """
    data = await bot.get_image(file=ref)
    if not (b64 := data.get("base64")):
        raise RuntimeError(f"get_image 未返回 base64，响应字段: {sorted(data)}")
    return base64.b64decode(b64), f"{uuid.uuid4().hex}.png"


qwen_edit = on_regex(
    QWEN_EDIT_TRIGGER.pattern, rule=Rule(_image_gen_rule), block=True, priority=10
)


@qwen_edit.handle()
async def _handle_qwen_edit(matcher: Matcher, bot: Bot, event: MessageEvent):
    """取参考图与提示词，执行生图编辑并回复输出图，失败时报错。

    Args:
        matcher (Matcher): 响应器（依赖注入）。
        bot (Bot): OneBot V11 Bot 实例（依赖注入）。
        event (MessageEvent): 消息事件。

    Callers:
        - NoneBot 响应器 `qwen_edit` 的处理阶段。
    """
    emoji, prompt, ratio, resolution = parse_edit_text(event.get_plaintext())

    # 适配器读取被回复消息失败时（协议端 get_msg 未命中），reply 段会残留在消息里，
    # 此时被回复消息的内容不可得，无法取参考图
    if any(s.type == "reply" for s in event.get_message()):
        await matcher.send("读取被回复消息失败：协议端未返回该消息", reply_message=True)
        return

    # 被回复消息的图片排最前，其后是本条消息的图片，共取前 10 张
    img_segs = [s for s in event.get_message() if s.type == "image"]
    if event.reply is not None:
        img_segs = [s for s in event.reply.message if s.type == "image"] + img_segs
    refs = [u for s in img_segs if (u := s.data.get("file") or s.data.get("url"))][:10]

    # 回复消息却没有取到任何参考图：协议端很可能丢弃了被回复消息的图片段
    # （NapCat picElement 转换器在图片 URL 获取失败时丢弃整段），必须显式报错而非按纯文本直出
    if not refs and event.reply is not None:
        logger.warning(f"被回复消息中未提取到图片，消息段: {event.reply.message}")
        await matcher.send("被回复消息中未找到图片，请直接在消息中附图", reply_message=True)
        return

    if not prompt and not refs:
        return

    img_files: List[Tuple[bytes, str]] = []
    for ref in refs:
        try:
            img_files.append(await fetch_message_image(bot, ref))
        except (ActionFailed, RuntimeError, ValueError) as e:
            await matcher.send(f"参考图获取失败：{e}", reply_message=True)
            return

    await reply_generated(
        matcher,
        lambda: run_edit(
            prompt,
            img_files,
            ratio,
            resolution,
            os.path.join(WORKFLOWS_DIR, QWEN_WORKFLOW_TEMPLATES[emoji]),
        ),
    )


def _register_avatar(pattern: str, template: str) -> None:
    """注册一个旧头像工作流响应器。

    Args:
        pattern (str): 触发关键词正则。
        template (str): 工作流模板文件名。

    Callers:
        - `Plugins/棘背龙/__init__.py`（模块级按 AVATAR_WORKFLOW_TEMPLATES 注册）
    """
    matcher = on_regex(pattern, rule=Rule(_avatar_rule), block=True, priority=10)

    @matcher.handle()
    async def _handle_avatar(event: MessageEvent):
        """下载发送者头像，按模板出图并回复，失败时报错。"""

        async def generate() -> List[bytes]:
            """下载发送者头像并按模板执行工作流，返回输出图字节列表。"""
            img_bytes, filename = await download_avatar(event.get_user_id())
            return await run_avatar_workflow(
                img_bytes, filename, os.path.join(WORKFLOWS_DIR, template)
            )

        await reply_generated(matcher, generate)


for _pattern, _template in AVATAR_WORKFLOW_TEMPLATES.items():
    _register_avatar(_pattern, _template)
