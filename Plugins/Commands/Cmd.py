"""
服务器命令插件 - 在指定服务器执行命令，支持多行每行一个命令
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

matcher = on_regex(r'^#cmd\s[\s\S]+', priority=19, block=True, permission=MC_SERVER_ADMIN_PERMISSION)


def _parse(text: str) -> tuple[str | None, list[str]]:
    """解析 #cmd 消息 → (server_flag, commands)"""
    lines = [l.strip() for l in text.strip().split('\n') if l.strip()]
    if not lines:
        return None, []
    m = re.match(r'^#cmd\s+(\S+)\s*(.*)$', lines[0])
    if not m:
        return None, []
    server, rest = m.group(1), m.group(2)
    cmds = [rest] if rest else []
    cmds.extend(lines[1:])
    return server, cmds


def _fmt(cmd: str, result: Any, prefix: str = '') -> str:
    if isinstance(result, Exception):
        return f'{prefix}{cmd}: 执行失败 - {result}'
    return f'{prefix}{cmd}: {result}' if result else f'{prefix}{cmd}: 无返回结果'


async def _execute_batch(commands: list[str], group_id: str | None) -> dict[str, list[tuple[str, Any]]]:
    """批量执行到 server_manager，返回 {server_name: [(cmd, result), ...]}"""
    out = {}
    for cmd in commands:
        for name, result in (await server_manager.execute(cmd, group_id=group_id) or {}).items():
            out.setdefault(name, []).append((cmd, result))
    return out


async def _execute_single(conn: Any, event_router: Any, commands: list[str], timeout: float = 5.0) -> list[str]:
    """在单连接上顺序执行命令，返回每条的格式化结果"""
    lines = []
    for cmd in commands:
        fut = asyncio.Future()

        def make_cb(f):
            async def cb(data):
                f.set_result(data)
            return cb

        echo_id = event_router.request(make_cb(fut), timeout=timeout)
        await conn.send(EventType.COMMAND, cmd, echo=echo_id)
        try:
            r = await asyncio.wait_for(fut, timeout=timeout)
            lines.append(_fmt(cmd, r) if r else f'{cmd}: 已发送')
        except asyncio.TimeoutError:
            lines.append(f'{cmd}: 响应超时')
    return lines


@matcher.handle()
async def handle_cmd(event: GroupMessageEvent):
    group_id = str(event.group_id)
    server_flag, commands = _parse(str(event.get_plaintext()).strip())
    if not server_flag:
        await matcher.finish('命令格式错误，喵~')
    if not commands:
        await matcher.finish('命令不能为空，喵~')

    logger.info(f'群 {group_id} 用户 {event.user_id} 在服务器 {server_flag} 执行: {commands}')

    # 广播到所有服务器
    if server_flag == '**':
        results = await _execute_batch(commands, None)
        if not results:
            await matcher.finish('当前没有连接任何服务器，喵~')
            return
        lines = [_fmt(cmd, r, f'[{name}] ') for name, pairs in results.items() for cmd, r in pairs]
        await matcher.finish('\n'.join(lines) + '\n喵~')

    # if group_id not in config.group_servers:
    #     await matcher.finish('当前群组未绑定任何服务器，无法执行命令，喵~')
    # group_servers = config.group_servers[group_id]

    # 广播到当前群所有服务器
    if server_flag == '*':
        results = await _execute_batch(commands, group_id)
        if not results:
            await matcher.finish('当前群组没有可用的在线服务器，喵~')
        lines = [_fmt(cmd, r, f'[{name}] ') for name, pairs in results.items() for cmd, r in pairs]
        await matcher.finish('\n'.join(lines) + '\n喵~')

    # 执行到指定服务器
    # if server_flag not in group_servers:
    #     await matcher.finish(f'服务器 [{server_flag}] 未绑定到当前群组，无法操作，喵~')
    #     return
    server = server_manager.get_server(server_flag)
    if not server:
        await matcher.finish(f'服务器 [{server_flag}] 不存在或未在线，喵~')

    from Scripts.Core.Connection import connection_manager
    from Scripts.Core.EventRouter import event_router

    conn = connection_manager.get(server.name)
    if not conn:
        await matcher.finish(f'服务器 [{server.name}] 连接不可用，喵~')

    lines = await _execute_single(conn, event_router, commands)
    await matcher.finish(f'服务器 [{server.name}] 执行结果：\n' + '\n'.join(lines) + '\n喵~')
