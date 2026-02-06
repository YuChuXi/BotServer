"""
Shell命令插件 - 执行shell命令
"""
import asyncio
import re
from nonebot import on_regex
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.log import logger

from Scripts.Utils import HOST_ADMIN_PERMISSION


matcher = on_regex(r'(?s)^#shell\s+(?P<command>.*)$', priority=9, block=True, permission=HOST_ADMIN_PERMISSION)


@matcher.handle()
async def handle_shell(event: MessageEvent):
    """处理shell命令"""
    
    message_text = str(event.get_plaintext()).strip()
    match = re.match(r'(?s)^#shell\s+(?P<command>.*)$', message_text)
    if not match:
        await matcher.finish('命令格式错误！')
        return
    
    command = match.group('command').strip()
    if not command:
        await matcher.finish('命令不能为空！')
        return
    
    logger.info(f'用户 {event.user_id} 执行shell命令: {command}')
    
    # 执行shell命令
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
    except asyncio.TimeoutError:
        process.kill()
        await matcher.finish('命令执行超时！')
        return
    
    result = stdout.decode('utf-8', errors='ignore')
    if stderr:
        error = stderr.decode('utf-8', errors='ignore')
        result = f'{result}\n错误:\n{error}' if result else f'错误:\n{error}'
    
    if not result:
        result = '命令执行完成，无输出'
    
    await matcher.finish(result[:2000])  # 限制输出长度

