"""
事件处理器 - 注册所有事件处理
"""
from typing import Optional, Any
from nonebot import get_bot
from nonebot.exception import NetworkError, ActionFailed
from nonebot.log import logger

from .EventRouter import event_router
from .Connection import connection_manager
from .Message import EventType
from ..Config import config
from ..Managers import server_manager


async def send_qq_message(message: str):
    """发送QQ消息到主群（target_qq_groups）"""
    try:
        bot = get_bot()
        for group in config.target_qq_groups:
            await bot.send_group_msg(group_id=group, message=message)
    except (NetworkError, ActionFailed, ValueError):
        logger.warning('发送QQ消息失败')


async def send_to_sync_group(message: str):
    """发送QQ消息到双向同步聊天群（sync_qq_group）"""
    if not config.sync_qq_group:
        return
    try:
        bot = get_bot()
        await bot.send_group_msg(group_id=config.sync_qq_group, message=message)
    except (NetworkError, ActionFailed, ValueError):
        logger.warning('发送消息到同步群失败')


def clean_message(message: str) -> str:
    """检查敏感词"""
    message = message.replace('你妈', '我妈')
    return message


# 注册所有事件处理器
def register_handlers():
    """注册所有事件处理器"""
    
    async def handle_message(data: str, echo: Optional[str] = None, server_name: Optional[str] = None):
        """处理来自服务器的消息（!!qq命令等），发送到主群"""
        if not data:
            return

        data = clean_message(data)
        server_info = f'[{server_name}] ' if server_name else ''
        await send_qq_message(F'{server_info}{data}')
    
    async def handle_server_startup(data: Any, echo: Optional[str] = None, server_name: Optional[str] = None):
        """处理服务器启动"""
        logger.info(F'收到服务器 [{server_name}] 启动事件')
        if config.enable_sync_group_server_startup:
            server_info = f'[{server_name}] ' if server_name else ''
            await send_to_sync_group(F'{server_info}服务器已开启，喵～')
    
    async def handle_server_shutdown(data: Any, echo: Optional[str] = None, server_name: Optional[str] = None):
        """处理服务器关闭"""
        logger.info(F'收到服务器 [{server_name}] 关闭事件')
        if config.enable_sync_group_server_shutdown:
            server_info = f'[{server_name}] ' if server_name else ''
            await send_to_sync_group(F'{server_info}服务器已关闭，呜……')
    
    async def handle_player_joined(player: str, echo: Optional[str] = None, server_name: Optional[str] = None):
        """处理玩家加入"""
        logger.info(F'玩家 {player} 加入服务器 [{server_name}]')
        server_info = f'[{server_name}] ' if server_name else ''
        message = F'{server_info}玩家 {player} 加入了服务器，喵～'
        if config.bot_player_prefix and player.upper().startswith(config.bot_player_prefix):
            message = F'{server_info}机器人 {player} 加入了服务器。'
        if config.enable_sync_group_player_joined:
            await send_to_sync_group(message)
    
    async def handle_player_left(player: str, echo: Optional[str] = None, server_name: Optional[str] = None):
        """处理玩家离开"""
        logger.info(F'玩家 {player} 离开服务器 [{server_name}]')
        server_info = f'[{server_name}] ' if server_name else ''
        message = F'{server_info}玩家 {player} 离开了服务器，呜……'
        if config.bot_player_prefix and player.upper().startswith(config.bot_player_prefix):
            message = F'{server_info}机器人 {player} 离开了服务器。'
        if config.enable_sync_group_player_left:
            await send_to_sync_group(message)
    
    async def handle_player_chat(data: list, echo: Optional[str] = None, server_name: Optional[str] = None):
        """处理玩家聊天"""
        player, chat_message = data
        logger.debug(F'玩家 {player} 在服务器 [{server_name}] 聊天: {chat_message}')
        server_info = f'[{server_name}] ' if server_name else ''
        if config.enable_sync_group_player_chat:
            chat_message = clean_message(chat_message)
            await send_to_sync_group(F'{server_info}<{player}> {chat_message}')
    
    async def handle_player_death(data: list, echo: Optional[str] = None, server_name: Optional[str] = None):
        """处理玩家死亡"""
        player, death_message = data
        if (not config.bot_player_prefix) or (not player.upper().startswith(config.bot_player_prefix)):
            server_info = f'[{server_name}] ' if server_name else ''
            message = F'{server_info}玩家 {player} 死亡了，呜……'
            if config.enable_sync_group_player_death:
                await send_to_sync_group(message)
    
    # 注册所有处理器
    event_router.register(EventType.MESSAGE.value, handle_message)
    event_router.register(EventType.SERVER_STARTUP.value, handle_server_startup)
    event_router.register(EventType.SERVER_SHUTDOWN.value, handle_server_shutdown)
    event_router.register(EventType.PLAYER_JOINED.value, handle_player_joined)
    event_router.register(EventType.PLAYER_LEFT.value, handle_player_left)
    event_router.register(EventType.PLAYER_CHAT.value, handle_player_chat)
    event_router.register(EventType.PLAYER_DEATH.value, handle_player_death)

