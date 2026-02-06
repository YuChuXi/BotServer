from nonebot import get_plugin_config
from pydantic import BaseModel, Field
import json
from pathlib import Path
from typing import Dict, List, Optional

class ServerDetailConfig(BaseModel):
    """单个服务器的配置"""
    java_whitelist_command: str = 'whitelist "{java_id}"'
    bedrock_whitelist_command: str = 'fwhitelist "{bedrock_id}"'
    enable_game_to_qq_sync: bool = True
    enable_sync_group_server_startup: bool = True
    enable_sync_group_server_shutdown: bool = True
    enable_sync_group_player_joined: bool = False
    enable_sync_group_player_left: bool = False
    enable_sync_group_player_chat: bool = True
    enable_sync_group_player_death: bool = False

class Config(BaseModel):
    """配置类"""
    # 认证配置
    token: str = ''
    
    # 权限配置
    host_admins: list[int] = []
    mc_server_admins: list[int] = []
    community_admins: list[int] = []
    enable_group_admin_as_community_admin: bool = True
    
    # 全局白名单排除（保留字段，虽然逻辑可能下放到组）
    whitelist_exclude_servers: list[str] = []
    max_bindings_per_qq: int = 1
    
    # 消息颜色配置
    message_color_source: str = 'gray'
    message_color_player: str = 'gray'
    message_color_content: str = 'gray'
    
    # 机器人配置
    bot_player_prefix: str = None
    
    # 目标QQ群（用于自动添加服务器时的默认群组）
    target_qq_groups: list[int] = [] 
    
    # 双向同步聊天群号 (Deprecated: 现在使用 group_servers 里的配置)
    # 保留字段以防旧代码引用报错，但逻辑上已被 group_servers 替代
    sync_qq_group: int = 0

    # 多群多服配置 (GroupId -> {ServerName -> Config})
    # 由 DataManager 加载和更新
    group_servers: Dict[str, Dict[str, ServerDetailConfig]] = Field(default_factory=dict)

config: Config = get_plugin_config(Config)

# 后处理
config.bot_player_prefix = config.bot_player_prefix.upper() if config.bot_player_prefix else None
config.message_color_source = config.message_color_source.lower()
config.message_color_player = config.message_color_player.lower()
config.message_color_content = config.message_color_content.lower()
