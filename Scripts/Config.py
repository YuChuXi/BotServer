from nonebot import get_plugin_config
from pydantic import BaseModel, Field
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

class ServerDetailConfig(BaseModel):
    """单个服务器的配置"""
    java_whitelist_command: str = 'whitelist {action} {java_id}'
    bedrock_whitelist_command: str = 'fwhitelist {action} "{bedrock_id}"'
    enable_game_to_qq_sync: bool = True
    enable_sync_group_server_startup: bool = True
    enable_query: bool = True  # 是否在查服命令中显示该服务器
    enable_sync_group_server_shutdown: bool = True
    enable_sync_group_player_joined: bool = False
    enable_sync_group_player_left: bool = False
    enable_sync_group_player_chat: bool = True
    enable_sync_group_player_death: bool = False
    strip_minecraft_format: bool = False  # 服务端返回带 § 格式化代码的内容，需要清理（含命令返回等）

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
    
    # 双向同步聊天群号 (Deprecated: 现在使用 group_servers 里的配置)
    # 保留字段以防旧代码引用报错，但逻辑上已被 group_servers 替代
    sync_qq_group: int = 0

    # 多群多服配置 (GroupId -> {ServerName -> Config})
    # 由 DataManager 加载和更新
    group_servers: Dict[str, Dict[str, ServerDetailConfig]] = Field(default_factory=dict)

    def get_server_binding(self, server_name: str) -> Optional[Tuple[str, ServerDetailConfig]]:
        """一服一群：返回 (group_id, config)，未配置则 None。"""
        for gid, servers in self.group_servers.items():
            if server_name in servers:
                return (str(gid), servers[server_name])
        return None


config: Config = get_plugin_config(Config)

# 后处理
config.bot_player_prefix = config.bot_player_prefix.upper() if config.bot_player_prefix else None
config.message_color_source = config.message_color_source.lower()
config.message_color_player = config.message_color_player.lower()
config.message_color_content = config.message_color_content.lower()
