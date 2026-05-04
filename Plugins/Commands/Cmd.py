"""
服务器命令插件 - 在指定服务器执行命令，支持多行每行一个命令
"""
import re
from typing import Any
from nonebot import on_regex
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.log import logger

from Scripts.Managers import server_manager
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


def _predicate_by_group(group_id: str | None):
    if not group_id:
        return lambda s: True
    return lambda s: s.name in config.group_servers.get(str(group_id), {})


async def _execute_batch(commands: list[str], group_id: str | None) -> dict[str, list[tuple[str, Any]]]:
    """筛选器 + 并发：command 为 Union[str, Iterable[str]]，批量在 Server 上执行。"""
    pred = _predicate_by_group(group_id)
    results = await server_manager.execute_batch(pred, commands)
    return {name: list(zip(commands, res_list)) for name, res_list in results.items()}


async def _execute_single(server: Any, commands: list[str], timeout: float = 5.0) -> list[str]:
    """单服：Server.execute_batch，返回每条的格式化结果。"""
    res_list = await server.execute_batch(commands, timeout=timeout)
    return [_fmt(cmd, r) if r else f'{cmd}: 已发送' for cmd, r in zip(commands, res_list)]


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
    if not server or not server.status:
        await matcher.finish(f'服务器 [{server_flag}] 不存在或未在线，喵~')

    lines = await _execute_single(server, commands)
    await matcher.finish(f'服务器 [{server.name}] 执行结果：\n' + '\n'.join(lines) + '\n喵~')
