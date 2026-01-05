"""
绑定命令插件 - 绑定基岩版和Java版玩家，拉黑管理
"""
import re
from nonebot import on_regex
from nonebot.adapters.onebot.v11 import MessageEvent

from Scripts.Utils import GROUP_MEMBER_PERMISSION, COMMUNITY_ADMIN_PERMISSION
from Scripts.Managers import bound_manager


matcher_bedrock = on_regex(r'^绑定基岩版\s*(?P<id>.*)$', priority=10, block=True, permission=GROUP_MEMBER_PERMISSION)
matcher_java = on_regex(r'(?i)^绑定java版\s*(?P<id>.*)$', priority=10, block=True, permission=GROUP_MEMBER_PERMISSION)
matcher_blacklist = on_regex(r'^拉黑', priority=10, block=True, permission=COMMUNITY_ADMIN_PERMISSION)
matcher_unblacklist = on_regex(r'^解除拉黑', priority=10, block=True, permission=COMMUNITY_ADMIN_PERMISSION)
matcher_remove_binding = on_regex(r'^解除绑定', priority=10, block=True, permission=COMMUNITY_ADMIN_PERMISSION)

@matcher_bedrock.handle()
async def handle_bedrock(event: MessageEvent):
    """处理绑定基岩版"""
    message_text = str(event.message).strip()
    match = re.match(r'^绑定基岩版\s*(?P<id>.*)$', message_text)
    if not match:
        await matcher_bedrock.finish('命令格式错误')
        return
    
    qq = str(event.user_id)
    player_id = match.group('id').strip()
    if not player_id:
        await matcher_bedrock.finish('玩家ID不能为空')
        return
    
    # 检查黑名单
    if bound_manager.is_blacklisted(qq):
        await matcher_bedrock.finish('你已被拉黑，无法绑定')
        return
    
    # 检查绑定数量
    if not bound_manager.can_bind(qq):
        bindings = bound_manager.get_bindings(qq)
        message = "你已绑定以下玩家："
        if bindings.bedrock:
            message += f'\n基岩版：{", ".join(bindings.bedrock)}'
        if bindings.java:
            message += f'\nJava：{", ".join(bindings.java)}'
        await matcher_bedrock.finish(message)
        return
    
    # 检查玩家ID是否已被占用
    occupied_qq = bound_manager.is_player_id_occupied(player_id, 'bedrock', exclude_qq=qq)
    if occupied_qq:
        await matcher_bedrock.finish(f'基岩版玩家 {player_id} 已被QQ {occupied_qq} 绑定')
        return

    # 添加绑定（如果不在黑名单则自动加白名单）
    await bound_manager.add_binding(qq, player_id, 'bedrock')
    await matcher_bedrock.finish(f'已绑定基岩版玩家 {player_id}')


@matcher_java.handle()
async def handle_java(event: MessageEvent):
    """处理绑定Java版"""
    message_text = str(event.message).strip()
    match = re.match(r'(?i)^绑定java版\s*(?P<id>.*)$', message_text)
    if not match:
        await matcher_java.finish('命令格式错误')
        return
    
    qq = str(event.user_id)
    player_id = match.group('id').strip()
    if not player_id:
        await matcher_java.finish('玩家ID不能为空')
        return
    
    # 检查黑名单
    if bound_manager.is_blacklisted(qq):
        await matcher_java.finish('你已被拉黑，无法绑定')
        return
    
    # 检查绑定数量
    if not bound_manager.can_bind(qq):
        bindings = bound_manager.get_bindings(qq)
        message = "你已绑定以下玩家："
        if bindings.bedrock:
            message += f'\n基岩版：{", ".join(bindings.bedrock)}'
        if bindings.java:
            message += f'\nJava：{", ".join(bindings.java)}'
        await matcher_java.finish(message)
        return
    
    # 检查玩家ID是否已被占用
    occupied_qq = bound_manager.is_player_id_occupied(player_id, 'java', exclude_qq=qq)
    if occupied_qq:
        await matcher_java.finish(f'Java版玩家 {player_id} 已被QQ {occupied_qq} 绑定')
        return

    # 添加绑定（如果不在黑名单则自动加白名单）
    await bound_manager.add_binding(qq, player_id, 'java')
    await matcher_java.finish(f'已绑定Java版玩家 {player_id}')


@matcher_blacklist.handle()
async def handle_blacklist(event: MessageEvent):
    """处理拉黑"""
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
            await matcher_blacklist.finish('命令格式错误！格式：拉黑 @QQ号')
            return
    
    # 添加黑名单
    bound_manager.add_blacklist(target_qq)
    
    # 如果已绑定，移除白名单和绑定记录
    bindings = bound_manager.get_bindings(target_qq)
    if bindings.bedrock or bindings.java:
        await bound_manager.remove_whitelist(target_qq, remove_binding=True)
    
    await matcher_blacklist.finish(f'已将QQ {target_qq} 拉黑')


@matcher_unblacklist.handle()
async def handle_unblacklist(event: MessageEvent):
    """处理解除拉黑"""
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
            await matcher_unblacklist.finish('命令格式错误！格式：解除拉黑 @QQ号')
            return
    
    bound_manager.remove_blacklist(target_qq)
    await matcher_unblacklist.finish(f'已解除QQ {target_qq} 的拉黑')


@matcher_remove_binding.handle()
async def handle_remove_binding(event: MessageEvent):
    """处理解除绑定（群管理可用）"""
    from nonebot.adapters.onebot.v11 import Message
    
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
            await matcher_remove_binding.finish('命令格式错误！格式：解除绑定 @QQ号')
            return
    
    # 获取绑定信息
    bindings = bound_manager.get_bindings(target_qq)
    if not bindings.bedrock and not bindings.java:
        await matcher_remove_binding.finish(f'QQ {target_qq} 没有绑定记录')
        return
    
    # 移除白名单
    await bound_manager.remove_whitelist(target_qq, remove_binding=True)
    
    message = f"已移除QQ {target_qq} 的绑定：\n"
    if bindings.bedrock:
        message += f'基岩版：{", ".join(bindings.bedrock)}\n'
    if bindings.java:
        message += f'Java：{", ".join(bindings.java)}'
    await matcher_remove_binding.finish(message)

