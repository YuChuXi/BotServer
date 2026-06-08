from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator
import json
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

QueryVisibility = Literal['禁用', '当前群', '跨群']

class GroupConfig(BaseModel):
    """群组配置"""
    include_other_groups_in_query: bool = False  # 查服时是否包含其他群的服务器
    enable_ai_chat: bool = True  # 是否响应 @ 机器人的 AI 聊天
    enable_poke: bool = True  # 是否响应戳一戳
    enable_tarot: bool = True  # 是否启用抽卡


class ServerDetailConfig(BaseModel):
    """单个服务器的配置"""
    java_whitelist_command: str = 'whitelist {action} {java_id}'
    bedrock_whitelist_command: str = 'fwhitelist {action} "{bedrock_id}"'
    enable_game_to_qq_sync: bool = True
    enable_sync_group_server_startup: bool = True
    enable_query: QueryVisibility = '当前群'  # 查服可见范围：禁用 / 当前群 / 跨群
    enable_sync_group_server_shutdown: bool = True
    enable_sync_group_player_joined: bool = False
    enable_sync_group_player_left: bool = False
    enable_sync_group_player_chat: bool = True
    enable_sync_group_player_death: bool = False
    strip_minecraft_format: bool = False  # 服务端返回带 § 格式化代码的内容，需要清理（含命令返回等）

    @field_validator('enable_query', mode='before')
    @classmethod
    def _coerce_enable_query(cls, v):
        if v is False or v == 'false':
            return '禁用'
        if v is True or v == 'true':
            return '跨群'
        if v in ('禁用', '当前群', '跨群'):
            return v
        raise ValueError(f'enable_query 无效: {v!r}，应为 禁用 / 当前群 / 跨群')

    def visible_in_query(
        self,
        query_group_id: str,
        server_group_id: Optional[str],
        include_other_groups: bool,
    ) -> bool:
        """结合群配置判断查服时是否显示该服务器。"""
        if self.enable_query == '禁用' or not server_group_id:
            return False
        if server_group_id == str(query_group_id):
            return True
        return include_other_groups and self.enable_query == '跨群'


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

    # 群组配置 (GroupId -> GroupConfig)，由 GroupManager 加载
    group_configs: Dict[str, GroupConfig] = Field(default_factory=dict)

    def get_group_config(self, group_id: str) -> GroupConfig:
        return self.group_configs.get(str(group_id), GroupConfig())

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
