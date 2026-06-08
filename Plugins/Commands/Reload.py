"""
重载Data配置插件 - 从磁盘重新读取Data目录下的配置文件（只读，不保存/覆盖）
"""
import re
from nonebot import on_regex
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.log import logger

from Scripts.Managers import data_manager, group_manager, bound_manager, nickname_manager
from Scripts.Utils import HOST_ADMIN_PERMISSION


matcher = on_regex(r'^#reload\s*$', priority=9, block=True, permission=HOST_ADMIN_PERMISSION)


@matcher.handle()
async def handle_reload(event: MessageEvent):
    """重载 Data 下的配置文件，仅读取，不写入"""
    message_text = str(event.get_plaintext()).strip()
    if not re.match(r'^#reload\s*$', message_text):
        await matcher.finish('命令格式： #reload')
        return

    logger.info(f'用户 {event.user_id} 执行配置重载')
    errors = []

    try:
        data_manager.load()  # Server.json
    except Exception as e:
        logger.error(f'重载 Server.json 失败: {e}')
        errors.append(f'Server.json: {e}')

    try:
        group_manager.load()  # Group.json
    except Exception as e:
        logger.error(f'重载 Group.json 失败: {e}')
        errors.append(f'Group.json: {e}')

    try:
        bound_manager._load()  # Player.json
    except Exception as e:
        logger.error(f'重载 Player.json 失败: {e}')
        errors.append(f'Player.json: {e}')

    try:
        nickname_manager._load()  # Nickname.json
    except Exception as e:
        logger.error(f'重载 Nickname.json 失败: {e}')
        errors.append(f'Nickname.json: {e}')

    if errors:
        await matcher.finish('重载完成，部分失败：\n' + '\n'.join(errors))
    else:
        await matcher.finish('Data 配置已重载（Server.json / Group.json / Player.json / Nickname.json）')
