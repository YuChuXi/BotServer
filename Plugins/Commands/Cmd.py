"""
服务器命令插件 - 在指定服务器执行命令
"""
import asyncio
import re
from typing import Any
from nonebot import on_regex
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.log import logger

from Scripts.Managers import server_manager
from Scripts.Core.Message import EventType
from Scripts.Utils import MC_SERVER_ADMIN_PERMISSION


matcher = on_regex(r'^#cmd\s(?P<server>\S+)\s+(?P<command>.*)$', priority=10, block=True, permission=MC_SERVER_ADMIN_PERMISSION)


@matcher.handle()
async def handle_cmd(event: MessageEvent):
    """处理服务器命令"""
    
    message_text = str(event.message).strip()
    match = re.match(r'^#cmd\s(?P<server>\S+)\s+(?P<command>.*)$', message_text)
    if not match:
        await matcher.finish('命令格式错误！')
        return
    
    server_flag = match.group('server')
    command = match.group('command').strip()
    
    if not command:
        await matcher.finish('命令不能为空！')
        return
    
    logger.info(f'用户 {event.user_id} 在服务器 {server_flag} 执行命令: {command}')
    
    if server_flag == '*':
        # 执行到所有服务器
        results = await server_manager.execute(command)
        if not results:
            await matcher.finish('没有可用的服务器！')
            return
        
        response = ''
        for name, result in results.items():
            if isinstance(result, Exception):
                response += f'[{name}]: 执行失败 - {result}\n'
            elif result:
                response += f'[{name}]: {result}\n'
            else:
                response += f'[{name}]: 无返回结果\n'
        await matcher.finish(response.strip())
    else:
        # 执行到指定服务器
        server = server_manager.get_server(server_flag)
        if not server:
            await matcher.finish(f'服务器 [{server_flag}] 不存在或未在线！')
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
                    await matcher.finish(f'服务器 [{server.name}] 执行结果：\n{result}')
                else:
                    await matcher.finish(f'命令已发送到服务器 [{server.name}]！')
            except asyncio.TimeoutError:
                await matcher.finish(f'服务器 [{server.name}] 响应超时！')
        else:
            await matcher.finish(f'服务器 [{server.name}] 连接不可用！')

