"""
监听器 - 监听QQ群成员退群事件、加群邀请
"""
from nonebot import on_notice, on_request
from nonebot.adapters.onebot.v11 import GroupDecreaseNoticeEvent, GroupRequestEvent, Bot
from nonebot.log import logger

from Scripts.Managers import bound_manager
from Scripts.Config import config


matcher_decrease = on_notice(priority=10)
matcher_invite = on_request(priority=1, block=True)


@matcher_decrease.handle()
async def handle_group_decrease(event: GroupDecreaseNoticeEvent):
    """处理群成员减少事件（退群）"""
    if not isinstance(event, GroupDecreaseNoticeEvent):
        return
    
    qq = str(event.user_id)
    group_id = str(event.group_id)
    
    # 检查是否有绑定
    bindings = bound_manager.get_bindings(qq, group_id)
    if not bindings.bedrock and not bindings.java:
        return  # 没有绑定，不需要处理
    
    logger.info(f'检测到QQ {qq} 退出群 {group_id}，自动移除该群的绑定和白名单')
    
    # 移除该群的绑定（会自动触发移除该群服务器的白名单）
    await bound_manager.remove_binding(qq, group_id)


@matcher_invite.handle()
async def handle_group_invite(bot: Bot, event: GroupRequestEvent):
    """处理加群邀请"""
    # 检查是否是加群请求且子类型为邀请
    if event.sub_type != 'invite':
        return

    logger.info(f"收到来自用户 {event.user_id} 的邀请加入群 {event.group_id}")

    # 获取所有管理员列表
    all_admins = set(config.host_admins + config.mc_server_admins + config.community_admins)
    
    # 检查邀请人是否是管理员
    if event.user_id in all_admins:
        try:
            # 同意邀请
            await event.approve(bot)
            logger.success(f"已自动同意管理员 {event.user_id} 的邀请加入群 {event.group_id}，喵~")
        except Exception as e:
            logger.error(f"同意加群失败: {e}")
    else:
        logger.warning(f"拒绝用户 {event.user_id} 的邀请：非管理员，喵~")
        # 拒绝邀请 (可选)
        # await event.reject(bot, "非管理员无法邀请Bot入群")
