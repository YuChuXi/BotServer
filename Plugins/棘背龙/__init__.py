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
from typing import List, Literal, Tuple

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
    "哈气|哈!|哈！": "workflow_jibeilong.json",
    "鼬": "workflow_you.json",
    "冲!|冲！": "workflow_chong.json",
    "我超|超!|超！|敲里": "workflow_qiaolima.json",
    r"这么强|强强|虽虽|<\(º0º\)>|弓虽": "workflow_qiang.json",
}

# 群配置中控制各功能的字段名
FeatureSwitch = Literal["enable_image_gen", "enable_avatar_gen"]


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
async def _handle_qwen_edit(bot: Bot, event: MessageEvent):
    """取参考图与提示词，执行生图编辑并回复输出图。"""
    emoji, prompt, ratio, resolution = parse_edit_text(event.get_plaintext())

    # 被回复消息的图片排最前，其后是本条消息的图片，共取前 10 张
    img_segs = [s for s in event.get_message() if s.type == "image"]
    if event.reply is not None:
        img_segs = [s for s in event.reply.message if s.type == "image"] + img_segs
    refs = [u for s in img_segs if (u := s.data.get("file") or s.data.get("url"))][:10]

    if not prompt and not refs:
        return

    img_files: List[Tuple[bytes, str]] = []
    for ref in refs:
        try:
            img_files.append(await fetch_message_image(bot, ref))
        except (ActionFailed, RuntimeError, ValueError) as e:
            logger.warning(f"获取参考图失败，已跳过: {ref} ({e})")

    images = await run_edit(
        prompt,
        img_files,
        ratio,
        resolution,
        os.path.join(WORKFLOWS_DIR, QWEN_WORKFLOW_TEMPLATES[emoji]),
    )
    if not images:
        return

    await qwen_edit.send(
        Message(
            [
                MessageSegment.image(f"base64://{base64.b64encode(b).decode()}")
                for b in images
            ]
        ),
        reply_message=True,
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
    async def _handle_avatar(bot: Bot, event: MessageEvent):
        """下载发送者头像，按模板出图并回复。"""
        img_bytes, filename = await download_avatar(event.get_user_id())
        images = await run_avatar_workflow(
            img_bytes, filename, os.path.join(WORKFLOWS_DIR, template)
        )
        if not images:
            return
        b64 = base64.b64encode(images[0]).decode()
        await matcher.send(MessageSegment.image(f"base64://{b64}"), reply_message=True)


for _pattern, _template in AVATAR_WORKFLOW_TEMPLATES.items():
    _register_avatar(_pattern, _template)
