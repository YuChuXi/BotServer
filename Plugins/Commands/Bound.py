"""
绑定命令插件 - 绑定基岩版和Java版玩家，拉黑管理
"""
import re
from nonebot import on_regex
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.log import logger

from Scripts.Utils import GROUP_MEMBER_PERMISSION, COMMUNITY_ADMIN_PERMISSION, SYNC_GROUP_MEMBER_PERMISSION
from Scripts.Managers import bound_manager


def _fmt_whitelist_result(wl, success_label='成功', failed_label='失败', skipped_label='未连接(未同步)'):
    """将白名单同步结果格式化为一行追加文案，无结果返回空字符串。"""
    if not wl or not (wl.get('success') or wl.get('failed') or wl.get('skipped')):
        return ''
    parts = []
    if wl.get('success'):
        parts.append(f"{success_label}：{', '.join(wl['success'])}")
    if wl.get('failed'):
        parts.append(f"{failed_label}：{', '.join(wl['failed'])}")
    if wl.get('skipped'):
        parts.append(f"{skipped_label}：{', '.join(wl['skipped'])}")
    return '\n'.join(parts)


def _fmt_bind_limit(bindings):
    """已达上限时的提示文案（文案在插件层）。"""
    msg = "你在本群已绑定以下玩家："
    if bindings.bedrock:
        msg += f'\n基岩版：{", ".join(bindings.bedrock)}'
    if bindings.java:
        msg += f'\nJava：{", ".join(bindings.java)}'
    return msg + "\n绑定数量已达上限，喵~"


matcher_bedrock = on_regex(r'^绑定基岩版\s*(?P<id>.*)$', priority=10, block=True, permission=GROUP_MEMBER_PERMISSION)
matcher_java = on_regex(r'(?i)^绑定java版\s*(?P<id>.*)$', priority=10, block=True, permission=GROUP_MEMBER_PERMISSION)
matcher_check_bound = on_regex(r'^检查绑定$', priority=10, block=True, permission=GROUP_MEMBER_PERMISSION | SYNC_GROUP_MEMBER_PERMISSION)
matcher_check_bound_admin = on_regex(r'^检查绑定', priority=11, block=True, permission=COMMUNITY_ADMIN_PERMISSION)
matcher_remove_binding = on_regex(r'^解除绑定', priority=10, block=True, permission=COMMUNITY_ADMIN_PERMISSION)

@matcher_bedrock.handle()
async def handle_bedrock(event: GroupMessageEvent):
    """处理绑定基岩版"""
    message_text = str(event.message).strip()
    match = re.match(r'^绑定基岩版\s*(?P<id>.*)$', message_text)
    if not match:
        await matcher_bedrock.finish('命令格式错误，喵~')
        return
    
    qq = str(event.user_id)
    group_id = str(event.group_id)
    player_id = match.group('id').strip()
    
    if not player_id:
        await matcher_bedrock.finish('玩家ID不能为空，喵~')
        return

    if not bound_manager.validate_id(player_id, 'bedrock'):
        await matcher_bedrock.finish('玩家ID格式不正确！基岩版ID应为3-16位字符，允许空格，首尾不能有空格，喵~')
        return

    status, data = await bound_manager.try_add_binding(qq, player_id, 'bedrock', group_id)
    if status == 'occupied':
        await matcher_bedrock.finish(f'基岩版玩家 {player_id} 在本群已被QQ {data} 绑定，喵~')
        return
    if status == 'limit':
        await matcher_bedrock.finish(_fmt_bind_limit(data))
        return
    wl = data
    msg = '已在当前群成功绑定基岩版玩家 {0}' if status == 'new' else '你已绑定该玩家，已重新同步白名单'
    msg = msg.format(player_id)
    if extra := _fmt_whitelist_result(wl):
        msg += '\n' + extra
    await matcher_bedrock.finish(msg + '，喵~')


@matcher_java.handle()
async def handle_java(event: GroupMessageEvent):
    """处理绑定Java版"""
    message_text = str(event.message).strip()
    match = re.match(r'(?i)^绑定java版\s*(?P<id>.*)$', message_text)
    if not match:
        await matcher_java.finish('命令格式错误，喵~')
        return
    
    qq = str(event.user_id)
    group_id = str(event.group_id)
    player_id = match.group('id').strip()
    
    if not player_id:
        await matcher_java.finish('玩家ID不能为空，喵~')
        return
    
    if not bound_manager.validate_id(player_id, 'java'):
        await matcher_java.finish('玩家ID格式不正确！Java版ID应为3-16位字母数字或下划线，喵~')
        return

    status, data = await bound_manager.try_add_binding(qq, player_id, 'java', group_id)
    if status == 'occupied':
        await matcher_java.finish(f'Java版玩家 {player_id} 在本群已被QQ {data} 绑定，喵~')
        return
    if status == 'limit':
        await matcher_java.finish(_fmt_bind_limit(data))
        return
    wl = data
    msg = '已在当前群成功绑定Java版玩家 {0}' if status == 'new' else '你已绑定该玩家，已重新同步白名单'
    msg = msg.format(player_id)
    if extra := _fmt_whitelist_result(wl):
        msg += '\n' + extra
    await matcher_java.finish(msg + '，喵~')


@matcher_check_bound.handle()
async def handle_check_bound(event: GroupMessageEvent):
    """处理检查绑定"""
    qq = str(event.user_id)
    group_id = str(event.group_id)
    bindings = bound_manager.get_bindings(qq, group_id)
    
    if not bindings.bedrock and not bindings.java:
        await matcher_check_bound.finish('你在本群还没有绑定任何玩家，喵~')
        return

    message = "你在本群已绑定以下玩家："
    if bindings.bedrock:
        message += f'\n基岩版：{", ".join(bindings.bedrock)}'
    if bindings.java:
        message += f'\nJava：{", ".join(bindings.java)}'
    await matcher_check_bound.finish(message + "\n喵~")


@matcher_check_bound_admin.handle()
async def handle_check_bound_admin(event: GroupMessageEvent):
    """处理检查绑定（管理员可用，可检查任意QQ）"""
    group_id = str(event.group_id)
    
    # 检查是否有@的QQ号
    target_qq = None
    for segment in event.message:
        if segment.type == 'at':
            target_qq = str(segment.data.get('qq', ''))
            break
    
    if not target_qq:
        # 尝试从字符串中匹配 [at:qq=数字] 格式
        message_text = str(event.message).strip()
        match = re.search(r'\[at:qq=(\d+)\]', message_text)
        if match:
            target_qq = match.group(1)
    
    # 如果没有@，跳过处理（让普通版本处理）
    if not target_qq:
        return
    
    # 获取绑定信息
    bindings = bound_manager.get_bindings(target_qq, group_id)
    if not bindings.bedrock and not bindings.java:
        await matcher_check_bound_admin.finish(f'QQ {target_qq} 在本群没有绑定记录，喵~')
        return
    
    message = f"QQ {target_qq} 在本群已绑定以下玩家："
    if bindings.bedrock:
        message += f'\n基岩版：{", ".join(bindings.bedrock)}'
    if bindings.java:
        message += f'\nJava：{", ".join(bindings.java)}'
    await matcher_check_bound_admin.finish(message + "\n喵~")


@matcher_remove_binding.handle()
async def handle_remove_binding(event: GroupMessageEvent):
    """处理解除绑定（群管理可用）"""
    group_id = str(event.group_id)
    
    # 从消息中提取 @ 的QQ号
    target_qq = None
    for segment in event.message:
        if segment.type == 'at':
            target_qq = str(segment.data.get('qq', ''))
            break
    
    if not target_qq:
        # 尝试从字符串中匹配 [at:qq=数字] 格式
        message_text = str(event.message).strip()
        match = re.search(r'\[at:qq=(\d+)\]', message_text)
        if match:
            target_qq = match.group(1)
        else:
            await matcher_remove_binding.finish('命令格式错误！格式：解除绑定 @QQ号，喵~')
            return
    
    # 获取绑定信息
    bindings = bound_manager.get_bindings(target_qq, group_id)
    if not bindings.bedrock and not bindings.java:
        await matcher_remove_binding.finish(f'QQ {target_qq} 在本群没有绑定记录，喵~')
        return
    
    wl = await bound_manager.remove_binding(target_qq, group_id)
    message = f"已解除QQ {target_qq} 在本群的所有绑定："
    if bindings.bedrock:
        message += f'\n基岩版：{", ".join(bindings.bedrock)}'
    if bindings.java:
        message += f'\nJava：{", ".join(bindings.java)}'
    if extra := _fmt_whitelist_result(wl, '白名单移除成功', '白名单移除失败', '未连接(未同步)'):
        message += '\n' + extra
    await matcher_remove_binding.finish(message + "\n喵~")
