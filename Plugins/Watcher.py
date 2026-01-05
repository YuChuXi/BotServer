"""
监听器 - 监听QQ群成员退群事件，自动移除白名单
"""
from nonebot import on_notice
from nonebot.adapters.onebot.v11 import GroupDecreaseNoticeEvent
from nonebot.log import logger

from Scripts.Managers import bound_manager


matcher = on_notice(priority=10)


@matcher.handle()
async def handle_group_decrease(event: GroupDecreaseNoticeEvent):
    """处理群成员减少事件（退群）"""
    if not isinstance(event, GroupDecreaseNoticeEvent):
        return
    
    qq = str(event.user_id)
    
    # 检查是否有绑定
    bindings = bound_manager.get_bindings(qq)
    if not bindings.bedrock and not bindings.java:
        return  # 没有绑定，不需要处理
    
    # 检查是否已在黑名单中
    if bound_manager.is_blacklisted(qq):
        logger.info(f'QQ {qq} 退群，已在黑名单中')
        return
    
    logger.info(f'检测到QQ {qq} 退群，自动加入黑名单并移除白名单')
    
    # 自动加入黑名单
    bound_manager.add_blacklist(qq)
    
    # 移除白名单（但保留绑定记录）
    await bound_manager.remove_whitelist(qq, remove_binding=False)

