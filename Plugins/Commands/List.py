"""
玩家列表插件 - 查询服务器玩家列表
"""
from nonebot import on_regex
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.log import logger

from Scripts.Managers import server_manager
from Scripts.Utils import GROUP_MEMBER_PERMISSION, SYNC_GROUP_MEMBER_PERMISSION

matcher = on_regex('[查|插][服|福]', priority=10, block=True, permission=GROUP_MEMBER_PERMISSION | SYNC_GROUP_MEMBER_PERMISSION)


@matcher.handle()
async def handle_list(event: GroupMessageEvent):
    """处理查服命令"""
    # 记录日志
    logger.info(f'群 {event.group_id} 用户 {event.user_id} 查询所有服务器玩家列表')
    
    pred = lambda s: s.config and s.config.enable_query
    player_lists = await server_manager.request_player_list(pred)
    
    if not player_lists:
        await matcher.finish('当前没有连接任何服务器，喵～')
        return
    
    # 格式化输出
    # 可以在这里做一些排序，比如按服务器名字母序，或者按在线人数排序
    # 这里简单按名称排序
    sorted_servers = sorted(player_lists.items(), key=lambda x: x[0])
    
    response = ''
    total_online = 0
    
    for server_name, players in sorted_servers:
        if isinstance(players, Exception):
            response += f'[{server_name}]: 获取失败 - {players}\n'
        elif players:
            player_count = len(players)
            total_online += player_count
            player_str = ', '.join(players)
            response += f'[{server_name}] ({player_count}人): {player_str}\n'
        else:
            response += f'[{server_name}]: 无玩家在线\n'
            
    if total_online > 0:
        response = f"当前共有 {total_online} 名玩家在线：\n{response}"
    
    await matcher.finish(response.strip() + ' 喵~')
