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


async def has_group_member_permission(event: GroupMessageEvent) -> bool:
    """主群成员权限（主群成员可以使用）"""
    # 检查是否在主群中
    return event.group_id in config.target_qq_groups

async def has_sync_group_member_permission(event: GroupMessageEvent) -> bool:
    """同步群成员权限（同步群成员可以使用）"""
    return event.group_id == config.sync_qq_group

async def has_community_admin_permission(event: GroupMessageEvent) -> bool:
    """社区管理员权限（可以管理绑定、白名单、黑名单）"""
    # 检查群管理员权限（仅限群消息，且需要是主群）
    if not config.enable_group_admin_as_community_admin:
        return False
    # 检查是否在主群中
    if event.group_id  not in config.target_qq_groups:
        return False

    return event.sender.role in ('admin', 'owner')


async def has_mc_server_admin_permission(event: GroupMessageEvent) -> bool:
    """MC服务端管理员权限（可以执行cmd命令）"""
    user_id = str(event.user_id)
    
    # 检查MC服务端管理员
    return user_id in config.mc_server_admins


async def has_host_admin_permission(event: GroupMessageEvent) -> bool:
    """主机管理员权限（可以执行shell命令）"""
    user_id = str(event.user_id)
    return user_id in config.host_admins


# 全局权限实例
GROUP_MEMBER_PERMISSION = Permission(has_group_member_permission)
SYNC_GROUP_MEMBER_PERMISSION = Permission(has_sync_group_member_permission)
COMMUNITY_ADMIN_PERMISSION = Permission(has_community_admin_permission, has_mc_server_admin_permission, has_host_admin_permission) # 主机管理员和MC服务端管理员的权限也包含社区管理员权限
MC_SERVER_ADMIN_PERMISSION = Permission(has_mc_server_admin_permission, has_host_admin_permission) # 主机管理员的权限也包含MC服务端管理员权限
HOST_ADMIN_PERMISSION = Permission(has_host_admin_permission) 

