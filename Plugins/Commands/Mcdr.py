"""
MCDR命令插件 - 在指定服务器执行MCDR命令
"""
import re
from nonebot import on_regex
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.log import logger

from Scripts.Managers import server_manager
from Scripts.Utils import MC_SERVER_ADMIN_PERMISSION


matcher = on_regex(r'^#mcdr\s(?P<server>\S+)\s+(?P<command>.*)$', priority=10, block=True, permission=MC_SERVER_ADMIN_PERMISSION)


@matcher.handle()
async def handle_mcdr(event: MessageEvent):
    """处理MCDR命令"""
    
    message_text = str(event.message).strip()
    match = re.match(r'^#mcdr\s(?P<server>\S+)\s+(?P<command>.*)$', message_text)
    if not match:
        await matcher.finish('命令格式错误！格式：#mcdr <服务器> <MCDR命令>')
        return
    
    server_flag = match.group('server')
    command = match.group('command').strip()
    
    if not command:
        await matcher.finish('命令不能为空！')
        return
    
    logger.info(f'用户 {event.user_id} 在服务器 {server_flag} 执行MCDR命令: {command}')
    
    if server_flag == '*':
        pred = lambda s: s.type == 'McdReforged'
        results = await server_manager.request_mcdr(pred, command, timeout=5.0)
        if not results:
            await matcher.finish('没有可用的MCDR服务器！')
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
        server = server_manager.get_server(server_flag)
        if not server or not server.status:
            await matcher.finish(f'服务器 [{server_flag}] 不存在或未在线！')
            return
        if server.type != 'McdReforged':
            await matcher.finish(f'服务器 [{server.name}] 不是MCDR服务器！')
            return
        result = await server.request_mcdr(command, timeout=5.0)
        if result:
            await matcher.finish(f'服务器 [{server.name}] 执行结果：\n{result}')
        else:
            await matcher.finish(f'MCDR命令已发送到服务器 [{server.name}]！')

