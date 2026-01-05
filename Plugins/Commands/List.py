"""
玩家列表插件 - 查询服务器玩家列表
"""
from nonebot import on_regex
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.log import logger

from Scripts.Managers import server_manager
from Scripts.Utils import GROUP_MEMBER_PERMISSION, SYNC_GROUP_MEMBER_PERMISSION

matcher = on_regex('查服', priority=10, block=True, permission=GROUP_MEMBER_PERMISSION | SYNC_GROUP_MEMBER_PERMISSION)


@matcher.handle()
async def handle_list(event: MessageEvent):
    """处理查服命令"""
    logger.info(f'用户 {event.user_id} 查询服务器玩家列表')
    
    # 获取所有服务器的玩家列表
    player_lists = await server_manager.get_player_list()
    
    if not player_lists:
        await matcher.finish('没有可用的服务器！')
        return
    
    # 格式化输出
    response = ''
    for server_name, players in player_lists.items():
        if isinstance(players, Exception):
            response += f'[{server_name}]: 获取失败 - {players}\n'
        elif players:
            player_count = len(players)
            player_str = ', '.join(players)
            response += f'[{server_name}] ({player_count}人): {player_str}\n'
        else:
            response += f'[{server_name}]: 无玩家在线\n'
    
    await matcher.finish(response.strip())

