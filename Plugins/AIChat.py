"""
AI聊天插件

规则：
- 只处理已绑定服务器的QQ群（以 config.group_servers 为准）
- 仅当用户 @ 机器人（event.is_tome()）时触发回复
- 上下文包含：系统提示词、当前群历史消息、机器人记忆、当前群绑定的服务器信息（按时间顺序组织；过长自动压缩）
- 支持图片输入（从群消息图片段下载后转 base64 data URL 传给模型）
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from nonebot import get_plugin_config, get_bot, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment
from nonebot.log import logger
from pydantic import BaseModel, Field

from Scripts.Config import config
from Scripts.Managers import nickname_manager, server_manager
from Scripts.Utils import is_configured_group


class AIChatPluginConfig(BaseModel):
    ollama_base_url: str = Field(default="http://10.147.20.104:11434", alias="AI_OLLAMA_BASE_URL")
    ollama_model: str = Field(default="gemma4:26b", alias="AI_OLLAMA_MODEL")
    system_prompt: str = Field(
        default=(
            "你是群聊里的AI猫娘助手。你需要结合上下文回答用户被@时提出的问题。"
            "回答要简洁、准确，不要编造不存在的信息。"
            "如果信息不足，请直接说明缺少哪些关键信息。"
            "如果遇到超出你能力范围的服务器问题，请引导用户去询问管理员。"
            "可以和用户聊天. "
        ),
        alias="AI_SYSTEM_PROMPT",
    )
    history_max_items: int = Field(default=400, alias="AI_HISTORY_MAX_ITEMS")
    context_max_chars: int = Field(default=12000, alias="AI_CONTEXT_MAX_CHARS")
    compress_keep_last: int = Field(default=120, alias="AI_COMPRESS_KEEP_LAST")
    image_timeout_sec: float = Field(default=8.0, alias="AI_IMAGE_TIMEOUT_SEC")


plugin_config = get_plugin_config(AIChatPluginConfig)

_ROOT = Path(__file__).resolve().parents[1]
_DATA_DIR = _ROOT / "Data"
_HISTORY_PATH = _DATA_DIR / "AIChatHistory.json"
_MEMORY_PATH = _DATA_DIR / "AIChatMemory.json"
_FAQ_YAML_PATH = _DATA_DIR / "AIChatFAQ.yaml"


_DEFAULT_FAQ_TREE = "你在回答前，必须先按“常见问题树”判断：属于哪一类问题？缺什么信息就追问什么信息；能给出明确操作就给出步骤；不能确定就给出下一步验证方法。"


def _load_faq_tree_text() -> str:
    """
    只把 Data/AIChatFAQ.yaml 原样喂给模型（不做任何解析/匹配/渲染）。
    文件不存在则用内置默认文本。
    """
    if _FAQ_YAML_PATH.exists():
        try:
            raw_text = _FAQ_YAML_PATH.read_text(encoding="utf-8").strip()
            if raw_text:
                return "【常见问题树（YAML，原样）】\n" + raw_text
        except Exception as e:
            logger.warning(f"读取 AIChatFAQ.yaml 失败，将使用内置默认FAQ：{e}")
    return _DEFAULT_FAQ_TREE


@dataclass
class _HistoryItem:
    ts: int
    user_id: int
    sender_name: str
    text: str
    images: List[str]
    is_bot: bool


def _ensure_data_dir() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning(f"AI聊天读取JSON失败（格式错误），将忽略：{path}")
        return default


def _save_json(path: Path, data: Any) -> None:
    _ensure_data_dir()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_ts() -> int:
    return int(time.time())


async def _extract_sender_name(event: GroupMessageEvent) -> str:
    return event.sender.card or event.sender.nickname or f"QQ{event.user_id}"


async def _extract_text_and_images(event: GroupMessageEvent) -> Tuple[str, List[str]]:
    """
    从事件消息中提取可读文本与图片URL列表。
    - 会去掉针对机器人的 at 段，避免把“@机器人”当成用户内容
    - 文本部分尽量贴近 SyncGroup 的显示效果
    """
    bot = get_bot()
    parts: List[str] = []
    images: List[str] = []
    for seg in event.message:
        seg_type = getattr(seg, "type", "")
        data = getattr(seg, "data", {}) or {}
        if seg_type == "at":
            qq = str(data.get("qq", "")).strip()
            if qq and str(qq) == str(bot.self_id):
                continue
            nickname = await nickname_manager.get_nickname(qq, event.group_id)
            parts.append(f"@{nickname}")
            continue
        if seg_type == "image":
            url = str(data.get("url", "")).strip()
            if url:
                images.append(url)
            summary = str(data.get("summary") or data.get("file") or "图片").replace("[", "").replace("]", "")
            parts.append(f"[{summary if summary else '图片'}]")
            continue
        # 其它类型：用字符串化后的片段尽量保留
        if seg_type == "text":
            parts.append(str(data.get("text", "")))
            continue
        parts.append(str(seg))
    text = "".join(parts).strip()
    return text, images


def _history_key(group_id: int) -> str:
    return str(group_id)


def _load_history(group_id: int) -> List[_HistoryItem]:
    raw = _load_json(_HISTORY_PATH, default={})
    items = raw.get(_history_key(group_id), [])
    result: List[_HistoryItem] = []
    for it in items:
        try:
            result.append(
                _HistoryItem(
                    ts=int(it.get("ts") or 0),
                    user_id=int(it.get("user_id") or 0),
                    sender_name=str(it.get("sender_name") or ""),
                    text=str(it.get("text") or ""),
                    images=list(it.get("images") or []),
                    is_bot=bool(it.get("is_bot") or False),
                )
            )
        except (TypeError, ValueError):
            continue
    result.sort(key=lambda x: x.ts)
    return result


def _append_history(group_id: int, item: _HistoryItem) -> None:
    raw = _load_json(_HISTORY_PATH, default={})
    key = _history_key(group_id)
    items: List[Dict[str, Any]] = list(raw.get(key, []))
    items.append(
        {
            "ts": item.ts,
            "user_id": item.user_id,
            "sender_name": item.sender_name,
            "text": item.text,
            "images": item.images,
            "is_bot": item.is_bot,
        }
    )
    # 控制体积：只保留最后 N 条
    if len(items) > plugin_config.history_max_items:
        items = items[-plugin_config.history_max_items :]
    raw[key] = items
    _save_json(_HISTORY_PATH, raw)


def _load_memory(group_id: int) -> str:
    raw = _load_json(_MEMORY_PATH, default={})
    m = raw.get(_history_key(group_id), {})
    return str(m.get("summary") or "").strip()


def _save_memory(group_id: int, summary: str) -> None:
    raw = _load_json(_MEMORY_PATH, default={})
    raw[_history_key(group_id)] = {"summary": summary, "updated_at": _now_ts()}
    _save_json(_MEMORY_PATH, raw)


def _group_server_info_text(group_id: int) -> str:
    servers = config.group_servers.get(str(group_id), {}) or {}
    if not servers:
        return "本群未绑定任何服务器。"
    lines: List[str] = []
    for server_name, server_conf in sorted(servers.items(), key=lambda x: x[0]):
        online = server_manager.get_server(server_name) is not None
        lines.append(
            f"- {server_name}（在线：{'是' if online else '否'}，群聊同步：{'开' if getattr(server_conf, 'enable_sync_group_player_chat', True) else '关'}）"
        )
    return "本群绑定服务器信息：\n" + "\n".join(lines)


async def _download_image_as_data_url(url: str) -> Optional[str]:
    timeout = httpx.Timeout(plugin_config.image_timeout_sec)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(url)
        if r.status_code != 200 or not r.content:
            return None
        ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
        if not ctype:
            ctype = "image/jpeg"
        b64 = base64.b64encode(r.content).decode("ascii")
        return f"data:{ctype};base64,{b64}"


def _estimate_context_chars(texts: List[str]) -> int:
    return sum(len(t) for t in texts)


async def _compress_history_if_needed(history: List[_HistoryItem]) -> Tuple[str, List[_HistoryItem]]:
    """
    返回 (摘要文本, 需要保留的历史)。
    - 当文本过长时，对较早的历史做一次摘要，保留最后 N 条原文。
    - 摘要存入“机器人记忆”，并作为上下文的一部分传给模型。
    """
    if not history:
        return "", history
    keep_last = max(20, int(plugin_config.compress_keep_last))
    if len(history) <= keep_last:
        return "", history

    formatted = [f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(h.ts))} {h.sender_name}: {h.text}" for h in history]
    if _estimate_context_chars(formatted) <= int(plugin_config.context_max_chars):
        return "", history

    head = history[: max(0, len(history) - keep_last)]
    tail = history[-keep_last:]

    head_text = "\n".join(
        f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(h.ts))} {h.sender_name}: {h.text}" for h in head
    ).strip()
    if not head_text:
        return "", tail

    # 用同一个模型做摘要：减少外部依赖与复杂度
    summary = await _summarize_text(head_text)
    return summary, tail


async def _summarize_text(text: str) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_ollama import ChatOllama

    llm = ChatOllama(
        base_url=plugin_config.ollama_base_url,
        model=plugin_config.ollama_model,
        temperature=0.2,
    )
    sys = SystemMessage(
        content=(
            "请把下面的群聊历史压缩成“可用于后续对话的摘要”。要求："
            "保留人物关系、关键事实、未解决问题、约定、重要结论；"
            "不要编造；输出用中文，控制在 300~800 字。"
        )
    )
    resp = await llm.ainvoke([sys, HumanMessage(content=text)])
    return str(getattr(resp, "content", "") or "").strip()


async def _call_ai(
    group_id: int,
    user_text: str,
    user_images: List[str],
    history: List[_HistoryItem],
) -> str:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from langchain_ollama import ChatOllama

    memory_text = _load_memory(group_id)
    server_info = _group_server_info_text(group_id)

    compress_summary, kept_history = await _compress_history_if_needed(history)
    if compress_summary:
        # 把压缩摘要合并进记忆（覆盖式），避免无限增长
        merged = compress_summary if not memory_text else (memory_text + "\n\n" + compress_summary)
        _save_memory(group_id, merged[-4000:])  # 记忆上限：字符级
        memory_text = _load_memory(group_id)

    sys_parts = [plugin_config.system_prompt.strip(), _load_faq_tree_text()]
    if server_info:
        sys_parts.append(server_info)
    if memory_text:
        sys_parts.append("机器人记忆（摘要）：\n" + memory_text)
    if compress_summary:
        sys_parts.append("较早群历史摘要：\n" + compress_summary)

    messages: List[Any] = [SystemMessage(content="\n\n".join([p for p in sys_parts if p]))]

    for h in kept_history:
        role_text = f"{h.sender_name}: {h.text}".strip()
        if not role_text:
            continue
        if h.is_bot:
            messages.append(AIMessage(content=role_text))
        else:
            messages.append(HumanMessage(content=role_text))

    # 用户当前消息（支持图片）
    content: List[Dict[str, Any]] = []
    if user_text:
        content.append({"type": "text", "text": user_text})
    for url in user_images:
        data_url = await _download_image_as_data_url(url)
        if data_url:
            content.append({"type": "image_url", "image_url": {"url": data_url}})
    if not content:
        content = [{"type": "text", "text": "（用户没有提供可解析的文本内容）"}]

    messages.append(HumanMessage(content=content))

    llm = ChatOllama(
        base_url=plugin_config.ollama_base_url,
        model=plugin_config.ollama_model,
        temperature=0.7,
    )
    resp = await llm.ainvoke(messages)
    return str(getattr(resp, "content", "") or "").strip() or "我没能生成有效回复。"


# 1) 历史记录采集：只记录“已绑定服务器的群”的所有群消息（包括非@）
history_collector = on_message(priority=4, block=False)


@history_collector.handle()
async def _collect_history(event: GroupMessageEvent):
    if not is_configured_group(event.group_id):
        return
    if not config.get_group_config(event.group_id).enable_ai_chat:
        return
    bot = get_bot()
    sender_name = await _extract_sender_name(event)
    text, images = await _extract_text_and_images(event)
    if not text and not images:
        return
    _append_history(
        event.group_id,
        _HistoryItem(
            ts=int(getattr(event, "time", None) or _now_ts()),
            user_id=int(event.user_id),
            sender_name=sender_name,
            text=text,
            images=images,
            is_bot=(str(event.user_id) == str(getattr(bot, "self_id", ""))),
        ),
    )


def _ai_chat_rule(event: GroupMessageEvent) -> bool:
    if not is_configured_group(event.group_id) or not event.is_tome():
        return False
    return config.get_group_config(event.group_id).enable_ai_chat


# 2) @触发回复：仅在绑定服务器的群、且用户@机器人时
chat_matcher = on_message(priority=6, block=True, rule=_ai_chat_rule)


@chat_matcher.handle()
async def _handle_ai_chat(event: GroupMessageEvent):
    group_id = int(event.group_id)
    bot = get_bot()
    if str(event.user_id) == str(getattr(bot, "self_id", "")):
        return

    user_text, user_images = await _extract_text_and_images(event)
    if not user_text and not user_images:
        return
    history = _load_history(group_id)
    # 为了让上下文包含“当前群所有历史消息”，这里不额外过滤
    reply = await _call_ai(group_id, user_text, user_images, history)

    # 记录机器人回复到历史
    _append_history(
        group_id,
        _HistoryItem(
            ts=_now_ts(),
            user_id=int(getattr(bot, "self_id", 0) or 0),
            sender_name="机器人",
            text=reply,
            images=[],
            is_bot=True,
        ),
    )

    await chat_matcher.finish(reply)

