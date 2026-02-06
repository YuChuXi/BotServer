"""
事件处理器 - 注册所有事件处理
"""
from typing import Optional, Any, Callable
from nonebot import get_bot
from nonebot.exception import NetworkError, ActionFailed
from nonebot.log import logger

from .EventRouter import event_router
from .Connection import connection_manager
from .Message import EventType
from ..Config import config, ServerDetailConfig
from ..Managers import server_manager


async def send_group_message(group_id: int, message: str):
    """发送QQ消息到指定群"""
    try:
        bot = get_bot()
        await bot.send_group_msg(group_id=group_id, message=message)
    except (NetworkError, ActionFailed, ValueError) as e:
        logger.warning(f'发送消息到群 {group_id} 失败: {e}')


def clean_message(message: str) -> str:
    """检查敏感词"""
    message = message.replace('你妈', '我妈')
    return message


async def broadcast_to_groups(
    server_name: Optional[str], 
    message_generator: Callable[[str], str], 
    check_config: Callable[[ServerDetailConfig], bool]
):
    """
    广播消息到该服务器所在的所有群组，根据配置决定是否发送
    :param server_name: 服务器名称
    :param message_generator: 生成消息的函数，接收 server_info 前缀
    :param check_config: 检查配置的函数，接收 ServerDetailConfig
    """
    if not server_name:
        return

    # 获取该服务器所属的所有群组
    groups = server_manager.get_groups_for_server(server_name)
    
    for group_id in groups:
        # 获取该群组下该服务器的配置
        server_conf = server_manager.get_server_config(group_id, server_name)
        if not server_conf:
            continue
            
        # 检查配置开关
        if check_config(server_conf):
            server_info = f'[{server_name}] '
            message = message_generator(server_info)
            await send_group_message(int(group_id), message)


# 注册所有事件处理器
def register_handlers():
    """注册所有事件处理器"""
    
    async def handle_message(data: str, echo: Optional[str] = None, server_name: Optional[str] = None):
        """处理来自服务器的消息（!!qq命令等），发送到该服务器所在的所有群"""
        if not data:
            return

        data = clean_message(data)
        
        # 定义消息生成器
        def msg_gen(prefix): 
            return f'{prefix}{data}'
        
        # !!qq消息默认开启同步（或者我们可以复用 enable_game_to_qq_sync）
        # 这里假设手动发送的消息总是需要转发的
        await broadcast_to_groups(
            server_name, 
            msg_gen,
            lambda conf: conf.enable_game_to_qq_sync
        )
    
    async def handle_server_startup(data: Any, echo: Optional[str] = None, server_name: Optional[str] = None):
        """处理服务器启动"""
        logger.info(F'收到服务器 [{server_name}] 启动事件')
        await broadcast_to_groups(
            server_name,
            lambda prefix: f'{prefix}服务器已开启，喵～',
            lambda conf: conf.enable_sync_group_server_startup
        )
    
    async def handle_server_shutdown(data: Any, echo: Optional[str] = None, server_name: Optional[str] = None):
        """处理服务器关闭"""
        logger.info(F'收到服务器 [{server_name}] 关闭事件')
        await broadcast_to_groups(
            server_name,
            lambda prefix: f'{prefix}服务器已关闭，呜……',
            lambda conf: conf.enable_sync_group_server_shutdown
        )
    
    async def handle_player_joined(player: str, echo: Optional[str] = None, server_name: Optional[str] = None):
        """处理玩家加入"""
        logger.info(F'玩家 {player} 加入服务器 [{server_name}]')
        
        def msg_gen(prefix):
            if config.bot_player_prefix and player.upper().startswith(config.bot_player_prefix):
                return f'{prefix}机器人 {player} 加入了服务器。'
            return f'{prefix}玩家 {player} 加入了服务器，喵～'

        await broadcast_to_groups(
            server_name,
            msg_gen,
            lambda conf: conf.enable_sync_group_player_joined
        )
    
    async def handle_player_left(player: str, echo: Optional[str] = None, server_name: Optional[str] = None):
        """处理玩家离开"""
        logger.info(F'玩家 {player} 离开服务器 [{server_name}]')
        
        def msg_gen(prefix):
            if config.bot_player_prefix and player.upper().startswith(config.bot_player_prefix):
                return f'{prefix}机器人 {player} 离开了服务器。'
            return f'{prefix}玩家 {player} 离开了服务器，呜……'

        await broadcast_to_groups(
            server_name,
            msg_gen,
            lambda conf: conf.enable_sync_group_player_left
        )
    
    async def handle_player_chat(data: list, echo: Optional[str] = None, server_name: Optional[str] = None):
        """处理玩家聊天"""
        player, chat_message = data
        logger.debug(F'玩家 {player} 在服务器 [{server_name}] 聊天: {chat_message}')
        
        cleaned_msg = clean_message(chat_message)
        
        await broadcast_to_groups(
            server_name,
            lambda prefix: f'{prefix}<{player}> {cleaned_msg}',
            lambda conf: conf.enable_sync_group_player_chat
        )
    
    async def handle_player_death(data: list, echo: Optional[str] = None, server_name: Optional[str] = None):
        """处理玩家死亡"""
        player, death_message = data
        
        if (config.bot_player_prefix) and (player.upper().startswith(config.bot_player_prefix)):
            return

        await broadcast_to_groups(
            server_name,
            lambda prefix: f'{prefix}玩家 {player} 死亡了，呜……',
            lambda conf: conf.enable_sync_group_player_death
        )
    
    # 注册所有处理器
    event_router.register(EventType.MESSAGE.value, handle_message)
    event_router.register(EventType.SERVER_STARTUP.value, handle_server_startup)
    event_router.register(EventType.SERVER_SHUTDOWN.value, handle_server_shutdown)
    event_router.register(EventType.PLAYER_JOINED.value, handle_player_joined)
    event_router.register(EventType.PLAYER_LEFT.value, handle_player_left)
    event_router.register(EventType.PLAYER_CHAT.value, handle_player_chat)
    event_router.register(EventType.PLAYER_DEATH.value, handle_player_death)
