"""
戳一戳插件 - 被戳时发送肘一肘.gif；资源预加载
"""
from io import BytesIO
from pathlib import Path

from nonebot import on_notice
from nonebot.adapters.onebot.v11 import MessageSegment, PokeNotifyEvent

_ROOT = Path(__file__).resolve().parents[1]
GIF_PATH = _ROOT / "Assets" / "肘一肘.gif"

# 资源预加载（启动时读取到内存，避免每次戳一戳都读盘）
_poke_gif_bytes: bytes | None = None


def _preload_gif() -> bytes | None:
    global _poke_gif_bytes
    if _poke_gif_bytes is None and GIF_PATH.is_file():
        _poke_gif_bytes = GIF_PATH.read_bytes()
    return _poke_gif_bytes


# 启动时预加载
_preload_gif()

matcher = on_notice(priority=10, block=True)


@matcher.handle()
async def handle_poke(event: PokeNotifyEvent):
    """被戳时回复肘一肘.gif"""
    if not event.is_tome():
        return

    data = _preload_gif()
    if data is None:
        return

    msg = MessageSegment.image(BytesIO(data))
    await matcher.finish(msg)
