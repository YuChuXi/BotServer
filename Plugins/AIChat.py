"""
AI聊天插件

规则：
- 只处理已绑定服务器的QQ群（以 config.group_servers 为准）
- 仅当用户 @ 机器人（event.is_tome()）时触发回复
- 上下文包含：系统提示词、当前群历史消息、机器人记忆、当前群绑定的服务器信息（按时间顺序组织；过长自动压缩）
- 支持图片输入（从群消息图片段下载后转 base64 data URL 传给模型）
- 支持工具调用（bind_tools）：联网搜索（AnySearch）、URL 请求、
  AI 工作区文件操作（列举 / 读取 / 新建 / 整体覆盖 / 精确替换 / glob 查找 / 正则逐行搜索）、
  群记忆增删查列改（memory_create / memory_delete / memory_search / memory_list / memory_update）、
  时间查询、安全数学计算；可通过 AI_ENABLE_TOOLS 开关
- 群长期记忆按主题键值存储（"群管理员" → 内容），同一主题唯一，重复写入会被拒绝并提示改用修改；
  预算内直接注入系统提示词，超预算部分由 memory_search / memory_list 检索；
  记忆内容上限 500 字，超限时返回错误并提示拆分
"""

from __future__ import annotations

import ast
import base64
import inspect
import json
import math
import operator
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, Tuple

import httpx
from langchain_core.tools import InjectedToolArg, tool
from nonebot import get_plugin_config, get_bot, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.log import logger
from pydantic import BaseModel, Field

from Scripts.Config import config
from Scripts.Managers import nickname_manager, server_manager
from Scripts.Utils import is_configured_group


class AIChatPluginConfig(BaseModel):
    ollama_base_url: str = Field(default="http://127.0.0.1:11434", alias="AI_OLLAMA_BASE_URL")
    ollama_model: str = Field(default="gemma4:26b", alias="AI_OLLAMA_MODEL")
    system_prompt: str = Field(
        default=(
            "你是群聊里的AI猫娘助手。你需要结合上下文回答用户被@时提出的问题。"
            "回答要简洁、准确，不要编造不存在的信息。"
            "如果信息不足，请直接说明缺少哪些关键信息。"
            "如果遇到超出你能力范围的服务器问题，请引导用户去询问管理员。"
            "可以和用户自由聊天. "
            "你是 GPT-6 Astra, 知识截止日期是 2024 年 6 月。需要最新信息时，可以联网查询。"
        ),
        alias="AI_SYSTEM_PROMPT",
    )
    history_max_items: int = Field(default=400, alias="AI_HISTORY_MAX_ITEMS")
    context_max_chars: int = Field(default=12000, alias="AI_CONTEXT_MAX_CHARS")
    compress_keep_last: int = Field(default=120, alias="AI_COMPRESS_KEEP_LAST")
    image_timeout_sec: float = Field(default=8.0, alias="AI_IMAGE_TIMEOUT_SEC")
    enable_tools: bool = Field(default=True, alias="AI_ENABLE_TOOLS")
    anysearch_api_key: str = Field(default="", alias="AI_ANYSEARCH_API_KEY")
    max_tool_rounds: int = Field(default=5, alias="AI_MAX_TOOL_ROUNDS")
    tool_timeout_sec: float = Field(default=15.0, alias="AI_TOOL_TIMEOUT_SEC")
    fetch_max_chars: int = Field(default=6000, alias="AI_FETCH_MAX_CHARS")
    memory_inject_max_chars: int = Field(default=4000, alias="AI_MEMORY_INJECT_MAX_CHARS")


plugin_config = get_plugin_config(AIChatPluginConfig)

_ROOT = Path(__file__).resolve().parents[1]
_DATA_DIR = _ROOT / "Data"
_HISTORY_PATH = _DATA_DIR / "AIChatHistory.json"
_MEMORY_PATH = _DATA_DIR / "AIChatMemory.json"
_FAQ_YAML_PATH = _DATA_DIR / "AIChatFAQ.yaml"
_WORKSPACE_DIR = _DATA_DIR / "AIWorkspace"
_ANYSEARCH_BASE_URL = "https://api.anysearch.com"
_RECALL_MAX_HITS = 20
_TOPIC_MAX_CHARS = 30
_MEMORY_CONTENT_MAX_CHARS = 500
_WORKSPACE_SCAN_MAX = 200
_WORKSPACE_GREP_MAX_LINES = 200
_WORKSPACE_GREP_MAX_FILE_BYTES = 1_000_000


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

def _sorted_memories(memories: Dict[str, Dict[str, Any]]) -> List[Tuple[str, Dict[str, Any]]]:
    """
    把主题到记忆的映射按创建时间排序。

    使用稳定排序，同一秒内创建的记忆保持字典中的写入顺序。

    Args:
        memories (Dict[str, Dict[str, Any]]): 主题到记忆记录的映射。

    Returns:
        List[Tuple[str, Dict[str, Any]]]: 按创建时间升序排列的 (主题, 记录) 列表。

    Callers:
        - `Plugins.AIChat._memory_display_text`: 按时间顺序渲染注入文本。
        - `Plugins.AIChat._get_chat_tools.memory_search`: 渲染模糊匹配结果。
        - `Plugins.AIChat._get_chat_tools.memory_list`: 分页列出全部记忆。
    """
    return sorted(memories.items(), key=lambda kv: int(kv[1].get("created_at") or 0))


def _load_memory_data(group_id: int) -> Dict[str, Any]:
    """
    读取指定群的记忆数据。

    Returns:
        Dict[str, Any]: 含 "summary"（自动压缩摘要文本）与 "memories"
        （主题到 {"text", "created_at", "updated_at"} 的映射）的字典。

    Callers:
        - `Plugins.AIChat._memory_display_text`: 构建注入系统提示词的记忆文本。
        - `Plugins.AIChat._call_ai`: 合并压缩摘要时读写记忆。
        - `Plugins.AIChat._get_chat_tools.memory_create`: 新建主题记忆。
        - `Plugins.AIChat._get_chat_tools.memory_search`: 按主题检索记忆。
        - `Plugins.AIChat._get_chat_tools.memory_list`: 列出全部记忆主题。
        - `Plugins.AIChat._get_chat_tools.memory_update`: 修改指定主题。
        - `Plugins.AIChat._get_chat_tools.memory_delete`: 删除指定主题。
    """
    raw = _load_json(_MEMORY_PATH, default={})
    m = raw.get(_history_key(group_id), {})
    memories: Dict[str, Dict[str, Any]] = {}
    for topic, item in (m.get("memories") or {}).items():
        if not isinstance(item, dict) or not item.get("text"):
            continue
        created_at = int(item.get("created_at") or 0)
        memories[str(topic)] = {
            "text": str(item["text"]),
            "created_at": created_at,
            "updated_at": int(item.get("updated_at") or created_at),
        }
    return {"summary": str(m.get("summary") or "").strip(), "memories": memories}


def _save_memory_data(group_id: int, data: Dict[str, Any]) -> None:
    """
    保存指定群的记忆数据（自动摘要 + 主题记忆映射）。

    Args:
        group_id (int): 群号。
        data (Dict[str, Any]): 含 "summary" 与 "memories" 的记忆数据。

    Callers:
        - `Plugins.AIChat._call_ai`: 写入压缩摘要。
        - `Plugins.AIChat._get_chat_tools.memory_create`: 新建主题记忆。
        - `Plugins.AIChat._get_chat_tools.memory_update`: 修改指定主题。
        - `Plugins.AIChat._get_chat_tools.memory_delete`: 删除指定主题。
    """
    raw = _load_json(_MEMORY_PATH, default={})
    raw[_history_key(group_id)] = {
        "summary": str(data.get("summary") or ""),
        "memories": dict(data.get("memories") or {}),
        "updated_at": _now_ts(),
    }
    _save_json(_MEMORY_PATH, raw)


def _format_memory_line(topic: str, item: Dict[str, Any]) -> str:
    """
    把一条主题记忆渲染为带主题和日期的单行文本。

    Args:
        topic (str): 记忆主题。
        item (Dict[str, Any]): 含 text/updated_at 的记忆记录。

    Returns:
        str: 形如 "[群管理员] 2026-10-17 张三" 的单行文本。

    Callers:
        - `Plugins.AIChat._memory_display_text`: 渲染注入系统提示词的记忆文本。
        - `Plugins.AIChat._get_chat_tools.memory_search`: 渲染检索结果。
        - `Plugins.AIChat._get_chat_tools.memory_list`: 渲染列表结果。
    """
    return f"[{topic}] {time.strftime('%Y-%m-%d', time.localtime(item['updated_at']))} {item['text']}"


def _memory_display_text(data: Dict[str, Any]) -> Tuple[str, int]:
    """
    把记忆数据渲染为注入系统提示词的文本。

    主题记忆按更新时间从新到旧装入字符预算；预算装不下时只注入较新的部分，
    其余主题由模型用 memory_search / memory_list 工具检索，避免上下文随记忆增长无限膨胀。

    Args:
        data (Dict[str, Any]): 含 "summary" 与 "memories" 的记忆数据。

    Returns:
        Tuple[str, int]: (渲染后的记忆文本, 未被注入的主题数)。文本为空表示无记忆。

    Callers:
        - `Plugins.AIChat._call_ai`: 组装系统提示词。
    """
    parts: List[str] = []
    if data.get("summary"):
        parts.append("自动摘要：\n" + str(data["summary"]))

    ordered = _sorted_memories(data.get("memories") or {})
    by_recent = sorted(ordered, key=lambda kv: int(kv[1].get("updated_at") or 0), reverse=True)
    shown: List[Tuple[str, Dict[str, Any]]] = []
    used = 0
    for topic, item in by_recent:
        line = _format_memory_line(topic, item)
        if used + len(line) + 1 > int(plugin_config.memory_inject_max_chars):
            break
        shown.append((topic, item))
        used += len(line) + 1
    shown.sort(key=lambda kv: int(kv[1].get("created_at") or 0))

    if shown:
        parts.append(
            "长期记忆（memory_create 工具按主题写入，方括号内为主题）：\n"
            + "\n".join(_format_memory_line(topic, item) for topic, item in shown)
        )
    hidden = len(ordered) - len(shown)
    if hidden:
        parts.append(f"另有 {hidden} 个更早的主题记忆未列出，需要时用 memory_search 按主题查询、memory_list 列出。")
    return "\n\n".join(parts), hidden


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



def _workspace_path(relative_path: str) -> Path:
    """
    把工作区相对路径解析为绝对路径，并拒绝逃逸出 Data/AIWorkspace 的路径。

    Args:
        relative_path (str): 工作区内的相对路径，"." 表示工作区根目录。

    Returns:
        Path: 解析后的绝对路径。

    Raises:
        ValueError: 路径为空、为绝对路径或越出工作区范围时抛出。

    Callers:
        - `Plugins.AIChat._get_chat_tools.workspace_list`: 解析要列出的目录。
        - `Plugins.AIChat._get_chat_tools.workspace_read`: 解析要读取的文件。
        - `Plugins.AIChat._get_chat_tools.workspace_create`: 解析要新建的文件。
        - `Plugins.AIChat._get_chat_tools.workspace_overwrite`: 解析要覆盖的文件。
        - `Plugins.AIChat._get_chat_tools.workspace_replace`: 解析要修改的文件。
        - `Plugins.AIChat._get_chat_tools.workspace_glob`: 解析搜索的起始目录。
        - `Plugins.AIChat._get_chat_tools.workspace_grep`: 解析搜索的起始目录。
    """
    rel = str(relative_path or "").strip()
    if not rel:
        raise ValueError("路径不能为空。")
    if rel.startswith("/") or rel.startswith("\\") or (len(rel) >= 2 and rel[1] == ":"):
        raise ValueError("路径越界：只允许访问 AI 工作区（Data/AIWorkspace）内的文件。")
    root = _WORKSPACE_DIR.resolve()
    candidate = (root / rel).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("路径越界：只允许访问 AI 工作区（Data/AIWorkspace）内的文件。")
    return candidate


def _workspace_glob_matches(root: Path, pattern: str) -> Tuple[List[Path], int]:
    """
    按 glob 模式列出工作区内的路径，并拦截指向工作区外的符号链接。

    Args:
        root (Path): 搜索起始目录（已在工作区内）。
        pattern (str): 相对 glob 模式，例如 "**/*.py"。

    Returns:
        Tuple[List[Path], int]: (按路径排序的匹配结果, 被跳过的越界符号链接数量)。

    Callers:
        - `Plugins.AIChat._get_chat_tools.workspace_glob`: 列出匹配的路径。
        - `Plugins.AIChat._get_chat_tools.workspace_grep`: 枚举待搜索的文件。
    """
    base = _WORKSPACE_DIR.resolve()
    matched: List[Path] = []
    skipped = 0
    for path in root.glob(pattern):
        resolved = path.resolve()
        if resolved != base and base not in resolved.parents:
            skipped += 1
            continue
        matched.append(path)
    return sorted(matched), skipped


_MATH_FUNC_NAMES = (
    "sqrt", "exp", "log", "log2", "log10",
    "sin", "cos", "tan", "asin", "acos", "atan",
    "sinh", "cosh", "tanh", "floor", "ceil", "fabs",
    "factorial", "gcd", "degrees", "radians",
)
_MATH_FUNCS: Dict[str, Any] = {name: getattr(math, name) for name in _MATH_FUNC_NAMES}
_MATH_FUNCS.update({"abs": abs, "round": round})
_MATH_CONSTS: Dict[str, Any] = {"pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf}
_BIN_OPS: Dict[type, Any] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY_OPS: Dict[type, Any] = {ast.USub: operator.neg, ast.UAdd: operator.pos}


def _safe_eval_node(node: ast.AST) -> Any:
    """
    递归求值一个只包含白名单数学语法与函数的 AST 节点。

    仅支持数值常量、四则/幂/模/整除运算、一元正负号、math 白名单函数与常量，
    不使用 eval，杜绝任意代码执行。

    Args:
        node (ast.AST): 经 ast.parse(mode="eval") 得到的节点。

    Returns:
        Any: 计算结果（int 或 float）。

    Raises:
        ValueError: 表达式包含白名单以外的语法、名称或函数时抛出。
        ZeroDivisionError / OverflowError: 由运算本身抛出。

    Callers:
        - `Plugins.AIChat._get_chat_tools.calculate`: 求值用户表达式。
    """
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_safe_eval_node(node.left), _safe_eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_safe_eval_node(node.operand))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _MATH_FUNCS
        and not node.keywords
    ):
        return _MATH_FUNCS[node.func.id](*[_safe_eval_node(arg) for arg in node.args])
    if isinstance(node, ast.Name) and node.id in _MATH_CONSTS:
        return _MATH_CONSTS[node.id]
    raise ValueError("表达式包含不支持的语法或函数。")


_CHAT_TOOLS_CACHE: Optional[List[Any]] = None
_TOOL_INDEX_CACHE: Dict[str, Any] = {}


def _get_chat_tools() -> List[Any]:
    """
    构建（首次调用时）并缓存 AI 可用的工具对象列表。

    工具通过 langchain 的 @tool 装饰器定义，供 bind_tools 生成模型侧 schema；
    group_id 等服务端上下文以 InjectedToolArg 标注，不会暴露给模型。

    Returns:
        List[Any]: langchain StructuredTool 列表。

    Callers:
        - `Plugins.AIChat._call_ai`: 组装系统提示词中的工具说明。
        - `Plugins.AIChat._invoke_with_tools`: 绑定工具并执行调用。
    """
    global _CHAT_TOOLS_CACHE
    if _CHAT_TOOLS_CACHE is not None:
        return _CHAT_TOOLS_CACHE

    @tool
    async def web_search(query: str, max_results: int = 5, zone: str = "") -> str:
        """联网搜索最新信息（AnySearch），用于回答时效性或知识性问题。

        搜索后如需某个结果的完整内容，可再用 fetch_url 抓取对应 URL。

        Args:
            query: 搜索查询语句，建议使用完整的问句或明确的关键词组合。
            max_results: 返回结果数量，范围 1 到 10，默认 5。
            zone: 结果地区偏好，"cn"（中国大陆）或 "intl"（国际），留空表示自动判断。
        """
        payload: Dict[str, Any] = {"query": query, "max_results": max(1, min(int(max_results), 10))}
        if zone in ("cn", "intl"):
            payload["zone"] = zone
        headers = {"Content-Type": "application/json"}
        if plugin_config.anysearch_api_key:
            headers["Authorization"] = f"Bearer {plugin_config.anysearch_api_key}"
        try:
            async with httpx.AsyncClient(timeout=plugin_config.tool_timeout_sec) as client:
                r = await client.post(f"{_ANYSEARCH_BASE_URL}/v1/search", json=payload, headers=headers)
        except httpx.HTTPError as e:
            return f"搜索请求失败：{e}"
        if r.status_code != 200:
            return f"搜索失败：HTTP {r.status_code}，{r.text[:300]}"
        body = r.json()
        if body.get("code") != 0:
            return f"搜索失败：{body.get('message', '未知错误')}"
        results = list((body.get("data") or {}).get("results") or [])
        if not results:
            return "搜索没有返回任何结果。"
        lines = []
        for i, item in enumerate(results, 1):
            entry = f"{i}. {item.get('title', '')}\n   {item.get('url', '')}"
            snippet = str(item.get("snippet", "") or "").strip()
            if snippet:
                entry += f"\n   {snippet}"
            lines.append(entry)
        return "搜索结果：\n" + "\n".join(lines)

    @tool
    async def fetch_url(url: str) -> str:
        """请求指定的 URL 并返回其文本内容（网页 HTML、JSON 接口、纯文本等）。

        仅支持 http/https；图片、文件等二进制内容不返回正文。

        Args:
            url: 要请求的完整 URL，必须以 http:// 或 https:// 开头。
        """
        if not (url.startswith("http://") or url.startswith("https://")):
            return "URL 无效：必须以 http:// 或 https:// 开头。"
        try:
            async with httpx.AsyncClient(timeout=plugin_config.tool_timeout_sec, follow_redirects=True) as client:
                r = await client.get(url)
        except httpx.HTTPError as e:
            return f"请求失败：{e}"
        if r.status_code != 200:
            return f"请求失败：HTTP {r.status_code}，{r.text[:300]}"
        ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
        text_types = ("application/json", "application/xml", "application/javascript", "application/xhtml+xml")
        if ctype and not (ctype.startswith("text/") or ctype in text_types):
            return f"该 URL 返回的是非文本内容（{ctype}），无法读取正文。"
        text = r.text
        limit = int(plugin_config.fetch_max_chars)
        if len(text) > limit:
            text = text[:limit] + f"\n…（内容过长，已截断，原始长度 {len(text)} 字符）"
        return text or "（响应正文为空）"

    @tool
    async def workspace_list(subdir: str = "") -> str:
        """列出 AI 工作区（Data/AIWorkspace）目录中的文件和子目录。

        Args:
            subdir: 工作区内的相对目录路径，留空表示根目录。
        """
        try:
            target = _workspace_path(subdir)
        except ValueError as e:
            return str(e)
        if not target.exists():
            return f"目录不存在：{subdir}"
        if not target.is_dir():
            return f"该路径不是目录：{subdir}"
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        if not entries:
            return "目录为空。"
        return "\n".join(
            f"[目录] {p.name}/" if p.is_dir() else f"[文件] {p.name}（{p.stat().st_size} 字节）"
            for p in entries
        )

    @tool
    async def workspace_read(path: str) -> str:
        """读取 AI 工作区（Data/AIWorkspace）内某个文本文件的内容。

        Args:
            path: 工作区内的相对文件路径。
        """
        try:
            target = _workspace_path(path)
        except ValueError as e:
            return str(e)
        if not target.exists() or not target.is_file():
            return f"文件不存在：{path}"
        text = target.read_text(encoding="utf-8", errors="replace")
        limit = int(plugin_config.fetch_max_chars)
        if len(text) > limit:
            text = text[:limit] + f"\n…（内容过长，已截断，原始长度 {len(text)} 字符）"
        return text or "（文件为空）"

    @tool
    async def workspace_create(path: str, content: str) -> str:
        """在 AI 工作区（Data/AIWorkspace）内新建一个文本文件（UTF-8 编码）。

        文件已存在时直接拒绝；需要整体替换请用 workspace_overwrite，局部修改请用 workspace_replace。
        会自动创建缺失的上级目录。

        Args:
            path: 工作区内的相对文件路径，必须尚不存在。
            content: 要写入的完整文本内容。
        """
        try:
            target = _workspace_path(path)
        except ValueError as e:
            return str(e)
        if target.exists():
            return f"路径已存在：{path}。新建请换路径；整体替换请用 workspace_overwrite；局部修改请用 workspace_replace。"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"已创建 {path}（{len(content)} 字符）。"

    @tool
    async def workspace_overwrite(path: str, content: str) -> str:
        """整体覆盖 AI 工作区（Data/AIWorkspace）内一个已存在的文本文件（UTF-8 编码）。

        文件不存在时直接拒绝；新建文件请用 workspace_create，局部修改请用 workspace_replace。

        Args:
            path: 工作区内的相对文件路径，必须已存在。
            content: 覆盖后的完整文本内容。
        """
        try:
            target = _workspace_path(path)
        except ValueError as e:
            return str(e)
        if not target.exists():
            return f"文件不存在：{path}。新建文件请用 workspace_create。"
        if target.is_dir():
            return f"该路径是目录，无法覆盖：{path}"
        target.write_text(content, encoding="utf-8")
        return f"已覆盖 {path}（{len(content)} 字符）。"

    @tool
    async def workspace_replace(path: str, old: str, new: str, replace_all: bool = False) -> str:
        """在 AI 工作区内的文本文件中做精确字符串替换（UTF-8 编码）。

        old 必须在文件中唯一出现；若出现多次，请提供更长的上下文，或显式传 replace_all=true。

        Args:
            path: 工作区内的相对文件路径。
            old: 要被替换的原文，必须与文件内容完全一致（包含空白与换行）。
            new: 替换后的新文本。
            replace_all: 是否替换全部出现位置，默认 false（要求 old 唯一）。
        """
        try:
            target = _workspace_path(path)
        except ValueError as e:
            return str(e)
        if not target.exists() or not target.is_file():
            return f"文件不存在：{path}"
        if not old:
            return "old 不能为空。"
        text = target.read_text(encoding="utf-8")
        occurrences = text.count(old)
        if not occurrences:
            return f"未找到要替换的内容：{old!r}"
        if occurrences > 1 and not replace_all:
            return f"old 在文件中出现了 {occurrences} 次，请提供更长的上下文，或传 replace_all=true 全部替换。"
        replaced = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        target.write_text(replaced, encoding="utf-8")
        return f"已替换 {occurrences if replace_all else 1} 处：{path}"

    @tool
    async def workspace_glob(pattern: str, subdir: str = "") -> str:
        """按 glob 模式在工作区内查找文件或目录（支持 ** 递归），用于定位路径。

        Args:
            pattern: 相对 glob 模式，例如 "**/*.py"、"docs/*.md"。
            subdir: 搜索起始目录，留空表示工作区根目录。
        """
        if pattern.startswith("/") or pattern.startswith("\\") or (len(pattern) >= 2 and pattern[1] == ":"):
            return "pattern 必须是工作区内的相对模式，例如 **/*.py。"
        try:
            root = _workspace_path(subdir or ".")
        except ValueError as e:
            return str(e)
        if not root.is_dir():
            return f"搜索起始路径不是目录：{subdir or '.'}"
        matched, skipped = _workspace_glob_matches(root, pattern)
        if not matched:
            return "没有匹配的路径。" + (f"（另外跳过了 {skipped} 个越出工作区的符号链接）" if skipped else "")
        base = _WORKSPACE_DIR.resolve()
        lines = []
        for item in matched[:_WORKSPACE_SCAN_MAX]:
            rel = item.relative_to(base)
            lines.append(f"[目录] {rel}/" if item.is_dir() else f"[文件] {rel}（{item.stat().st_size} 字节）")
        result = f"匹配到 {len(matched)} 个路径：\n" + "\n".join(lines)
        if len(matched) > _WORKSPACE_SCAN_MAX:
            result += f"\n…（结果过多，仅显示前 {_WORKSPACE_SCAN_MAX} 个）"
        if skipped:
            result += f"\n另外跳过了 {skipped} 个越出工作区的符号链接。"
        return result

    @tool
    async def workspace_grep(pattern: str, subdir: str = "", file_glob: str = "**/*") -> str:
        """在工作区内按正则表达式逐行搜索文本，返回 文件:行号:内容，用于定位代码或文本。

        自动跳过二进制文件和超过 1 MB 的文件。

        Args:
            pattern: Python 风格正则表达式。
            subdir: 搜索起始目录，留空表示工作区根目录。
            file_glob: 限定参与搜索的相对 glob 模式，默认 "**/*"。
        """
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"正则表达式无效：{e}"
        if file_glob.startswith("/") or file_glob.startswith("\\") or (len(file_glob) >= 2 and file_glob[1] == ":"):
            return "file_glob 必须是工作区内的相对模式，例如 **/*.py。"
        try:
            root = _workspace_path(subdir or ".")
        except ValueError as e:
            return str(e)
        if not root.is_dir():
            return f"搜索起始路径不是目录：{subdir or '.'}"
        files, skipped_links = _workspace_glob_matches(root, file_glob)
        base = _WORKSPACE_DIR.resolve()
        hits: List[str] = []
        total = 0
        skipped_binary = 0
        skipped_large = 0
        for item in files:
            if not item.is_file():
                continue
            if item.stat().st_size > _WORKSPACE_GREP_MAX_FILE_BYTES:
                skipped_large += 1
                continue
            try:
                text = item.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                skipped_binary += 1
                continue
            rel = item.relative_to(base)
            for lineno, line in enumerate(text.splitlines(), 1):
                if not regex.search(line):
                    continue
                total += 1
                if len(hits) < _WORKSPACE_GREP_MAX_LINES:
                    hits.append(f"{rel}:{lineno}: {line}")
        notes = []
        if len(hits) < total:
            notes.append(f"…（共命中 {total} 行，仅显示前 {len(hits)} 行）")
        if skipped_binary:
            notes.append(f"跳过了 {skipped_binary} 个非 UTF-8 文本文件。")
        if skipped_large:
            notes.append(f"跳过了 {skipped_large} 个超过 1 MB 的文件。")
        if skipped_links:
            notes.append(f"跳过了 {skipped_links} 个越出工作区的符号链接。")
        if not hits:
            return "没有匹配的行。" + ("\n" + "\n".join(notes) if notes else "")
        return "\n".join(hits) + ("\n" + "\n".join(notes) if notes else "")

    @tool
    async def memory_create(topic: str, content: str, group_id: Annotated[int, InjectedToolArg]) -> str:
        """按主题新建一条本群长期记忆（人物关系、用户偏好、重要约定与结论等）。

        主题是记忆的唯一键，应简短且能概括内容（如“群管理员”“周活动时间”）；
        同一主题只能存在一条记忆，已存在时请改用 memory_update 修改，不要换名字重复写入。

        Args:
            topic: 记忆主题，不超过 30 字。
            content: 该主题下的事实内容，用一句话表述，不超过 500 字。
        """
        if not topic:
            return "记忆主题不能为空。"
        if len(topic) > _TOPIC_MAX_CHARS:
            return f"记忆主题过长（{len(topic)} 字，上限 {_TOPIC_MAX_CHARS} 字），请概括成简短的名称，例如“群管理员”“活动时间”。"
        if not content:
            return "记忆内容不能为空。"
        if len(content) > _MEMORY_CONTENT_MAX_CHARS:
            return f"记忆内容过长（{len(content)} 字，上限 {_MEMORY_CONTENT_MAX_CHARS} 字）。请压缩成一句更短的事实，或拆分为多个主题分别写入。"
        data = _load_memory_data(group_id)
        existing = data["memories"].get(topic)
        if existing is not None:
            return (
                f"主题「{topic}」已存在（现有内容：{existing['text']}）。"
                "如要修改请调用 memory_update；如需记录不同事实，请使用更具体的主题。"
            )
        now = _now_ts()
        data["memories"][topic] = {"text": content, "created_at": now, "updated_at": now}
        _save_memory_data(group_id, data)
        return f"已记住主题「{topic}」：{content}"

    @tool
    async def memory_search(topic: str, group_id: Annotated[int, InjectedToolArg]) -> str:
        """按主题查询本群长期记忆：先精确匹配主题，未命中则返回主题包含关键词的全部条目。

        当上下文中没有所需信息、且提示词说明存在未列出的更早主题时，用本工具查询。

        Args:
            topic: 要查询的主题或关键词，例如“群管理员”“活动”。
        """
        if not topic:
            return "记忆主题不能为空。"
        data = _load_memory_data(group_id)
        exact = data["memories"].get(topic)
        if exact is not None:
            return "查询到 1 条长期记忆：\n" + _format_memory_line(topic, exact)
        keyword = topic.lower()
        matches = [
            (name, item)
            for name, item in _sorted_memories(data["memories"])
            if keyword in name.lower() or keyword in item["text"].lower()
        ][-_RECALL_MAX_HITS:]
        if not matches:
            return f"没有找到与「{topic}」相关的长期记忆。"
        return f"找到 {len(matches)} 条相关记忆：\n" + "\n".join(
            _format_memory_line(name, item) for name, item in matches
        )

    @tool
    async def memory_list(offset: int = 0, limit: int = 20, group_id: Annotated[int, InjectedToolArg] = 0) -> str:
        """分页列出本群全部长期记忆主题（按创建顺序），用于查看、校对或定位要修改/删除的主题。

        Args:
            offset: 起始偏移，从 0 开始，表示跳过前多少个主题；必须为非负整数。
            limit: 本次最多返回多少个主题，范围 1 到 50，默认 20。
        """
        if offset < 0:
            return f"offset 不能为负数（收到 {offset}）。"
        if not 1 <= limit <= 50:
            return f"limit 必须在 1 到 50 之间（收到 {limit}）。"
        data = _load_memory_data(group_id)
        ordered = _sorted_memories(data["memories"])
        total = len(ordered)
        if not total:
            return "本群还没有任何长期记忆。"
        if offset >= total:
            return f"offset {offset} 超出范围：本群共 {total} 个记忆主题，有效偏移为 0 到 {total - 1}。"
        page = ordered[offset:offset + limit]
        body = "\n".join(_format_memory_line(name, item) for name, item in page)
        return f"长期记忆第 {offset + 1}-{offset + len(page)} 个主题（共 {total} 个）：\n{body}"

    @tool
    async def memory_update(topic: str, content: str, group_id: Annotated[int, InjectedToolArg] = 0) -> str:
        """修改指定主题的长期记忆内容（主题本身不变，可先用 memory_search / memory_list 确认主题名）。

        Args:
            topic: 要修改的记忆主题，必须与现有主题完全一致。
            content: 修改后的完整事实内容，不超过 500 字。
        """
        if not topic:
            return "记忆主题不能为空。"
        if not content:
            return "记忆内容不能为空。"
        if len(content) > _MEMORY_CONTENT_MAX_CHARS:
            return f"记忆内容过长（{len(content)} 字，上限 {_MEMORY_CONTENT_MAX_CHARS} 字）。请压缩成一句更短的事实，或拆分为多个主题分别写入。"
        data = _load_memory_data(group_id)
        item = data["memories"].get(topic)
        if item is None:
            return f"未找到主题「{topic}」，请先用 memory_search 或 memory_list 查看现有主题。"
        item["text"] = content
        item["updated_at"] = _now_ts()
        _save_memory_data(group_id, data)
        return f"已更新主题「{topic}」：{content}"

    @tool
    async def memory_delete(topic: str, group_id: Annotated[int, InjectedToolArg] = 0) -> str:
        """删除指定主题的长期记忆（可先用 memory_search / memory_list 确认主题名）。

        仅在用户明确要求遗忘、或事实已被证伪/过时的情况下使用。

        Args:
            topic: 要删除的记忆主题，必须与现有主题完全一致。
        """
        if not topic:
            return "记忆主题不能为空。"
        data = _load_memory_data(group_id)
        removed = data["memories"].pop(topic, None)
        if removed is None:
            return f"未找到主题「{topic}」，请先用 memory_search 或 memory_list 查看现有主题。"
        _save_memory_data(group_id, data)
        return f"已删除主题「{topic}」：{removed['text']}"

    @tool
    async def get_current_time() -> str:
        """获取当前的准确日期、星期和时间（服务器时区 Asia/Shanghai）。"""
        lt = time.localtime()
        return f"{time.strftime('当前时间：%Y-%m-%d %H:%M:%S %A', lt)}（Unix 时间戳 {int(time.time())} 秒）"

    @tool
    async def calculate(expression: str) -> str:
        """计算一个数学表达式的值。

        支持四则运算、幂（**）、取模（%）、整除（//）、括号，
        函数 sqrt、log、log2、log10、exp、sin、cos、tan、floor、ceil、abs、round、factorial、gcd 等，
        以及常量 pi、e、tau、inf。示例："sqrt(2) * 1.5 + pi"。

        Args:
            expression: 数学表达式，例如 "(3 + 4) * 2 ** 10 / 7"。
        """
        try:
            value = _safe_eval_node(ast.parse(expression, mode="eval"))
        except (SyntaxError, ValueError, TypeError, ZeroDivisionError, OverflowError) as e:
            return f"计算失败：{e}"
        if isinstance(value, complex):
            sign = "+" if value.imag >= 0 else ""
            return f"{expression} = {value.real:.12g}{sign}{value.imag:.12g}j"
        if isinstance(value, int):
            return f"{expression} = {value}"
        return f"{expression} = {value:.12g}"

    _CHAT_TOOLS_CACHE = [
        web_search, fetch_url,
        workspace_list, workspace_read, workspace_create, workspace_overwrite, workspace_replace,
        workspace_glob, workspace_grep,
        memory_create, memory_search, memory_list, memory_update, memory_delete,
        get_current_time, calculate,
    ]
    _TOOL_INDEX_CACHE.clear()
    for t in _CHAT_TOOLS_CACHE:
        _TOOL_INDEX_CACHE[t.name] = t
    return _CHAT_TOOLS_CACHE


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
    if sum(len(t) for t in formatted) <= int(plugin_config.context_max_chars):
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


async def _run_tool_call(tool_call: Dict[str, Any], group_id: int) -> Any:
    """
    执行模型发起的一次工具调用，并包装为 ToolMessage。

    服务端上下文（group_id）只注入给以 InjectedToolArg 声明该参数的工具；
    工具自身已把可预期失败（网络错误、路径越界等）转为可读的错误文本返回。

    Args:
        tool_call (Dict[str, Any]): 模型返回的单个 tool_call，含 name/args/id。
        group_id (int): 当前群号，用于注入需要群上下文的工具。

    Returns:
        Any: langchain ToolMessage，content 为工具执行结果文本。

    Callers:
        - `Plugins.AIChat._invoke_with_tools`: 多轮工具调用循环中逐个执行调用。
    """
    from langchain_core.messages import ToolMessage

    name = str(tool_call.get("name") or "")
    tool_obj = _TOOL_INDEX_CACHE.get(name)
    if tool_obj is None:
        content = f"未知工具：{name}。可用的工具：{'、'.join(_TOOL_INDEX_CACHE)}。"
    else:
        args = dict(tool_call.get("args") or {})
        if "group_id" in inspect.signature(tool_obj.coroutine).parameters:
            args["group_id"] = group_id
        content = str(await tool_obj.ainvoke(args))
    limit = 4000
    if len(content) > limit:
        content = content[:limit] + f"\n…（工具输出过长，已截断，原始长度 {len(content)} 字符）"
    return ToolMessage(content=content, tool_call_id=str(tool_call.get("id") or ""))


async def _invoke_with_tools(llm: Any, messages: List[Any], group_id: int) -> str:
    """
    以多轮工具调用循环运行模型，直到模型给出最终回答或轮数用尽。

    每轮把模型输出（含 tool_calls）与其触发的 ToolMessage 依次追加进 messages；
    轮数用尽后去掉工具绑定再做一次调用，强制模型基于已有信息收尾作答。

    Args:
        llm (Any): ChatOllama 实例。
        messages (List[Any]): 已组装好的 langchain 消息列表（会被原地追加）。
        group_id (int): 当前群号，用于注入需要群上下文的工具。

    Returns:
        str: 模型的最终回答文本。

    Callers:
        - `Plugins.AIChat._call_ai`: enable_tools 开启时的推理入口。
    """
    llm_with_tools = llm.bind_tools(_get_chat_tools())
    for _ in range(max(1, int(plugin_config.max_tool_rounds))):
        resp = await llm_with_tools.ainvoke(messages)
        tool_calls = list(getattr(resp, "tool_calls", None) or [])
        if not tool_calls:
            return str(getattr(resp, "content", "") or "").strip() or "我没能生成有效回复。"
        messages.append(resp)
        for tool_call in tool_calls:
            messages.append(await _run_tool_call(tool_call, group_id))
    resp = await llm.ainvoke(messages)
    return str(getattr(resp, "content", "") or "").strip() or "我没能生成有效回复。"


async def _call_ai(
    group_id: int,
    user_text: str,
    user_images: List[str],
    history: List[_HistoryItem],
) -> str:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from langchain_ollama import ChatOllama

    memory_data = _load_memory_data(group_id)
    server_info = _group_server_info_text(group_id)

    compress_summary, kept_history = await _compress_history_if_needed(history)
    if compress_summary:
        # 把压缩摘要合并进记忆（覆盖式），避免无限增长
        memory_data["summary"] = (
            compress_summary
            if not memory_data["summary"]
            else (memory_data["summary"] + "\n\n" + compress_summary)
        )
        if len(memory_data["summary"]) > 4000:
            memory_data["summary"] = memory_data["summary"][-4000:] + "…（更早的自动摘要已因长度裁剪）"
        _save_memory_data(group_id, memory_data)

    memory_text, hidden_facts = _memory_display_text(memory_data)
    sys_parts = [plugin_config.system_prompt.strip(), _load_faq_tree_text()]
    if server_info:
        sys_parts.append(server_info)
    if memory_text:
        sys_parts.append("机器人记忆：\n" + memory_text)
    if hidden_facts and plugin_config.enable_tools:
        sys_parts.append("本群存在未全部列出的长期记忆，涉及过往约定、偏好或结论的问题请先用 memory_search 检索再回答。")
    if plugin_config.enable_tools:
        tool_names = "、".join(t.name for t in _get_chat_tools())
        sys_parts.append(
            "你可以调用工具：" + tool_names + "。"
            "遇到需要实时信息、网页内容、精确计算、长期记忆或工作区文件操作的情况时，先调用工具再回答；不需要时直接回答。"
        )
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
    if plugin_config.enable_tools:
        return await _invoke_with_tools(llm, messages, group_id)
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

