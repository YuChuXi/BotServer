"""
绑定命令插件 - 绑定基岩版和Java版玩家，拉黑管理
"""
import re
from nonebot import on_regex
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.log import logger

from Scripts.Utils import GROUP_MEMBER_PERMISSION, COMMUNITY_ADMIN_PERMISSION, SYNC_GROUP_MEMBER_PERMISSION
from Scripts.Managers import bound_manager


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

    # 校验ID格式
    if not bound_manager.validate_id(player_id, 'bedrock'):
        await matcher_bedrock.finish('玩家ID格式不正确！基岩版ID应为3-16位字符，允许空格，首尾不能有空格，喵~')
        return
    
    # 检查绑定数量
    if not bound_manager.can_bind(qq, group_id):
        bindings = bound_manager.get_bindings(qq, group_id)
        message = "你在本群已绑定以下玩家："
        if bindings.bedrock:
            message += f'\n基岩版：{", ".join(bindings.bedrock)}'
        if bindings.java:
            message += f'\nJava：{", ".join(bindings.java)}'
        message += "\n绑定数量已达上限，喵~"
        await matcher_bedrock.finish(message)
        return
    
    # 检查玩家ID是否已被占用
    occupied_qq = bound_manager.is_player_id_occupied(player_id, 'bedrock', group_id, exclude_qq=qq)
    if occupied_qq:
        await matcher_bedrock.finish(f'基岩版玩家 {player_id} 在本群已被QQ {occupied_qq} 绑定，喵~')
        return

    # 添加绑定
    await bound_manager.add_binding(qq, player_id, 'bedrock', group_id)
    await matcher_bedrock.finish(f'已在当前群成功绑定基岩版玩家 {player_id}，喵~')


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
    
    # 校验ID格式
    if not bound_manager.validate_id(player_id, 'java'):
        await matcher_java.finish('玩家ID格式不正确！Java版ID应为3-16位字母数字或下划线，喵~')
        return
    
    # 检查绑定数量
    if not bound_manager.can_bind(qq, group_id):
        bindings = bound_manager.get_bindings(qq, group_id)
        message = "你在本群已绑定以下玩家："
        if bindings.bedrock:
            message += f'\n基岩版：{", ".join(bindings.bedrock)}'
        if bindings.java:
            message += f'\nJava：{", ".join(bindings.java)}'
        message += "\n绑定数量已达上限，喵~"
        await matcher_java.finish(message)
        return
    
    # 检查玩家ID是否已被占用
    occupied_qq = bound_manager.is_player_id_occupied(player_id, 'java', group_id, exclude_qq=qq)
    if occupied_qq:
        await matcher_java.finish(f'Java版玩家 {player_id} 在本群已被QQ {occupied_qq} 绑定，喵~')
        return

    # 添加绑定
    await bound_manager.add_binding(qq, player_id, 'java', group_id)
    await matcher_java.finish(f'已在当前群成功绑定Java版玩家 {player_id}，喵~')


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
    
    # 移除白名单
    await bound_manager.remove_binding(target_qq, group_id)
    
    message = f"已解除QQ {target_qq} 在本群的所有绑定："
    if bindings.bedrock:
        message += f'\n基岩版：{", ".join(bindings.bedrock)}'
    if bindings.java:
        message += f'\nJava：{", ".join(bindings.java)}'
    await matcher_remove_binding.finish(message + "\n喵~")
