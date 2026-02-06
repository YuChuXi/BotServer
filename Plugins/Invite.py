"""
邀请处理插件 - 管理加群邀请
"""
from typing import List, Dict, Any
from nonebot import on_request, on_command
from nonebot.adapters.onebot.v11 import GroupRequestEvent, Bot, Message
from nonebot.params import CommandArg
from nonebot.log import logger
from Scripts.Utils import HOST_ADMIN_PERMISSION

# 邀请事件监听 (仅做日志记录，不再拦截存储)
invite_matcher = on_request(priority=1, block=False)

@invite_matcher.handle()
async def handle_group_invite(bot: Bot, event: GroupRequestEvent):
    """监听加群邀请并记录日志"""
    if event.sub_type == 'invite':
        logger.info(f"收到邀请入群请求: 群 {event.group_id}, 邀请人 {event.user_id}, Flag: {event.flag}")

# 查看邀请命令
view_invites_cmd = on_command("查看邀请", aliases={"list_invites"}, permission=HOST_ADMIN_PERMISSION, priority=10, block=True)

@view_invites_cmd.handle()
async def handle_view_invites(bot: Bot):
    try:
        # 尝试调用 go-cqhttp 扩展 API 获取群系统消息
        result = await bot.call_api("get_group_system_msg")
    except Exception as e:
        await view_invites_cmd.finish(f"获取邀请列表失败: {e}\n可能你的 OneBot 实现不支持 get_group_system_msg API，喵~")
        return

    invited_requests = result.get('invited_requests', [])
    # 筛选未处理的邀请
    pending_invites = [req for req in invited_requests if not req.get('checked')]

    if not pending_invites:
        await view_invites_cmd.finish("当前没有未处理的加群邀请，喵~")
        return

    msg = "当前未处理的邀请：\n"
    for idx, req in enumerate(pending_invites):
        invitor = req.get('invitor_uin')
        invitor_nick = req.get('invitor_nick', '未知')
        group_id = req.get('group_id')
        group_name = req.get('group_name', '未知群')
        msg += f"{idx + 1}. 群: {group_name}({group_id}) - 邀请人: {invitor_nick}({invitor})\n"
    
    msg += "\n发送 '同意邀请 <序号>' 进行处理，喵~"
    await view_invites_cmd.finish(msg)

# 同意邀请命令
approve_invite_cmd = on_command("同意邀请", aliases={"approve_invite"}, permission=HOST_ADMIN_PERMISSION, priority=10, block=True)

@approve_invite_cmd.handle()
async def handle_approve_invite(bot: Bot, args: Message = CommandArg()):
    arg = args.extract_plain_text().strip()
    
    if not arg.isdigit():
        await approve_invite_cmd.finish("请输入有效的邀请序号，例如：同意邀请 1，喵~")
        return
    
    idx = int(arg) - 1
    
    try:
        # 再次获取列表以确保序号对应
        result = await bot.call_api("get_group_system_msg")
        invited_requests = result.get('invited_requests', [])
        pending_invites = [req for req in invited_requests if not req.get('checked')]
    except Exception as e:
        await approve_invite_cmd.finish(f"获取邀请列表失败: {e}，喵~")
        return

    if idx < 0 or idx >= len(pending_invites):
        await approve_invite_cmd.finish("找不到该序号的邀请，请先使用 '查看邀请' 确认，喵~")
        return

    req = pending_invites[idx]
    flag = str(req.get('request_id'))
    
    try:
        # 调用处理加群请求/邀请 API
        await bot.set_group_add_request(
            flag=flag,
            sub_type='invite',
            approve=True
        )
        await approve_invite_cmd.finish(f"已同意加入群 {req.get('group_id')}，喵~")
    except Exception as e:
        logger.error(f"同意加群失败: {e}")
        await approve_invite_cmd.finish(f"操作失败: {e}，喵~")
