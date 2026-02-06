"""
服务器命令插件 - 在指定服务器执行命令
"""
import asyncio
import re
from typing import Any
from nonebot import on_regex
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.log import logger

from Scripts.Managers import server_manager
from Scripts.Core.Message import EventType
from Scripts.Utils import MC_SERVER_ADMIN_PERMISSION
from Scripts.Config import config


matcher = on_regex(r'^#cmd\s(?P<server>\S+)\s+(?P<command>.*)$', priority=19, block=True, permission=MC_SERVER_ADMIN_PERMISSION)


@matcher.handle()
async def handle_cmd(event: GroupMessageEvent):
    """处理服务器命令"""
    group_id = str(event.group_id)
    message_text = str(event.get_plaintext()).strip()
    match = re.match(r'^#cmd\s(?P<server>\S+)\s+(?P<command>.*)$', message_text)
    if not match:
        await matcher.finish('命令格式错误，喵~')
        return
    
    server_flag = match.group('server')
    command = match.group('command').strip()
    
    if not command:
        await matcher.finish('命令不能为空，喵~')
        return
    
    logger.info(f'群 {group_id} 用户 {event.user_id} 在服务器 {server_flag} 执行命令: {command}')

    # === 全局广播逻辑 ===
    if server_flag == '**':
        # 执行到所有连接的服务器（忽略群组限制）
        results = await server_manager.execute(command, group_id=None)
        
        if not results:
            await matcher.finish('当前没有连接任何服务器，喵~')
            return
        
        response = ""
        for name, result in results.items():
            if isinstance(result, Exception):
                response += f'[{name}]: 执行失败 - {result}\n'
            elif result:
                response += f'[{name}]: {result}\n'
            else:
                response += f'[{name}]: 无返回结果\n'
        await matcher.finish(response.strip() + "\n喵~")
        return

    # === 以下为群组内逻辑 ===
    
    # 检查当前群是否配置了服务器
    if group_id not in config.group_servers:
        await matcher.finish('当前群组未绑定任何服务器，无法执行命令，喵~')
        return
    
    # 获取当前群绑定的服务器列表
    group_servers = config.group_servers[group_id]

    if server_flag == '*':
        # 执行到当前群绑定的所有服务器
        results = await server_manager.execute(command, group_id=group_id)
        
        if not results:
            await matcher.finish('当前群组没有可用的在线服务器，喵~')
            return
        
        response = ''
        for name, result in results.items():
            if isinstance(result, Exception):
                response += f'[{name}]: 执行失败 - {result}\n'
            elif result:
                response += f'[{name}]: {result}\n'
            else:
                response += f'[{name}]: 无返回结果\n'
        await matcher.finish(response.strip() + "\n喵~")
    else:
        # 执行到指定服务器
        # 首先检查该服务器是否属于当前群
        if server_flag not in group_servers:
            await matcher.finish(f'服务器 [{server_flag}] 未绑定到当前群组，无法操作，喵~')
            return

        server = server_manager.get_server(server_flag)
        if not server:
            await matcher.finish(f'服务器 [{server_flag}] 不存在或未在线，喵~')
            return
        
        from Scripts.Core.Connection import connection_manager
        from Scripts.Core.EventRouter import event_router
        
        if conn := connection_manager.get(server.name):
            future = asyncio.Future()
            
            async def callback(data: Any):
                future.set_result(data)
            
            echo_id = event_router.request(callback, timeout=5.0)
            await conn.send(EventType.COMMAND, command, echo=echo_id)
            
            try:
                result = await asyncio.wait_for(future, timeout=5.0)
                if result:
                    await matcher.finish(f'服务器 [{server.name}] 执行结果：\n{result}\n喵~')
                else:
                    await matcher.finish(f'命令已发送到服务器 [{server.name}]，喵~')
            except asyncio.TimeoutError:
                await matcher.finish(f'服务器 [{server.name}] 响应超时，喵~')
        else:
            await matcher.finish(f'服务器 [{server.name}] 连接不可用，喵~')
