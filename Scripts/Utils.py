"""
工具函数
"""
import binascii
from base64 import b64encode, b64decode
from json import dumps, loads
from typing import Any
from nonebot.log import logger
from nonebot.permission import Permission
from nonebot.adapters.onebot.v11 import MessageEvent, GroupMessageEvent

from .Config import config


def decode_header(string: str) -> dict[str, Any] | None:
    """Base64解码（用于HTTP header）"""
    try:
        string = b64decode(string.encode('Utf-8'))
        return loads(string.decode('Utf-8'))
    except (binascii.Error, Exception) as e:
        logger.warning(f'Header解码失败: {e}')
        return None


def is_configured_group(group_id: int) -> bool:
    """检查是否是已配置的群组（包括TargetGroups和GroupServers）"""
    str_gid = str(group_id)
    # 检查是否在 group_servers 中
    if str_gid in config.group_servers:
        return True
    # 检查是否在 target_qq_groups 中
    if group_id in config.target_qq_groups:
        return True
    return False


async def has_group_member_permission(event: GroupMessageEvent) -> bool:
    """群成员权限（在配置的群组中即可使用）"""
    return is_configured_group(event.group_id)


async def has_sync_group_member_permission(event: GroupMessageEvent) -> bool:
    """同步群成员权限（已合并到通用群权限，保留此函数为了兼容旧代码引用）"""
    return is_configured_group(event.group_id)


async def has_community_admin_permission(event: GroupMessageEvent) -> bool:
    """社区管理员权限（可以管理绑定、白名单、黑名单）"""
    # 1. 检查是否是配置里的管理员
    if event.user_id in config.community_admins:
        return True
        
    # 2. 检查群管理员权限（仅限已配置的群消息）
    if not config.enable_group_admin_as_community_admin:
        return False
        
    if not is_configured_group(event.group_id):
        return False

    return event.sender.role in ('admin', 'owner')


async def has_mc_server_admin_permission(event: GroupMessageEvent) -> bool:
    """MC服务端管理员权限（可以执行cmd命令）"""
    return event.user_id in config.mc_server_admins


async def has_host_admin_permission(event: GroupMessageEvent) -> bool:
    """主机管理员权限（可以执行shell命令）"""
    return event.user_id in config.host_admins


# 全局权限实例
GROUP_MEMBER_PERMISSION = Permission(has_group_member_permission)
SYNC_GROUP_MEMBER_PERMISSION = Permission(has_sync_group_member_permission)
COMMUNITY_ADMIN_PERMISSION = Permission(has_community_admin_permission, has_mc_server_admin_permission, has_host_admin_permission)
MC_SERVER_ADMIN_PERMISSION = Permission(has_mc_server_admin_permission, has_host_admin_permission)
HOST_ADMIN_PERMISSION = Permission(has_host_admin_permission) 
