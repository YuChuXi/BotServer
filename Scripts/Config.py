from nonebot import get_plugin_config
from pydantic import BaseModel


class Config(BaseModel):
    """配置类 - 只包含实际使用的字段"""
    # 认证配置
    token: str = ''
    
    # 权限配置（3层权限体系）
    # 层级：普通玩家 < 社区管理 < MC服务端管理 < 主机管理
    host_admins: list[int] = []  # 主机管理员（可以执行shell命令，包含MC服务端管理权限）
    mc_server_admins: list[int] = []  # MC服务端管理员（可以执行cmd命令，包含社区管理权限）
    community_admins: list[int] = []  # 社区管理员（可以管理绑定、白名单、黑名单）
    enable_group_admin_as_community_admin: bool = True  # 是否将群管理员自动视为社区管理员
    
    # 消息配置
    target_qq_groups: list[int] = []  # 目标QQ群（接收和发送消息，主群用于指令）
    sync_qq_group: int = 703195149  # 双向同步聊天群号（所有消息自动转发到所有服务器）
    enable_game_to_qq_sync: bool = True  # 是否启用游戏消息同步到QQ
    
    # 聊天群事件转发配置（控制服务器事件是否转发到sync_qq_group）
    enable_sync_group_server_startup: bool = True  # 是否转发服务器启动事件到聊天群
    enable_sync_group_server_shutdown: bool = True  # 是否转发服务器关闭事件到聊天群
    enable_sync_group_player_joined: bool = True  # 是否转发玩家加入事件到聊天群
    enable_sync_group_player_left: bool = True  # 是否转发玩家离开事件到聊天群
    enable_sync_group_player_chat: bool = True  # 是否转发玩家聊天到聊天群
    enable_sync_group_player_death: bool = True  # 是否转发玩家死亡事件到聊天群
    
    
    # 服务器配置
    bot_player_prefix: str = None  # 机器人玩家前缀（用于识别机器人）
    
    # 白名单配置
    bedrock_whitelist_command: str = 'fwhitelist'  # 基岩版白名单命令
    java_whitelist_command: str = 'whitelist'  # Java版白名单命令
    max_bindings_per_qq: int = 1  # 每个QQ最大绑定数量
    
    # 消息颜色配置
    message_color_source: str = 'gray'  # 消息颜色-来源
    message_color_player: str = 'gray'  # 消息颜色-玩家
    message_color_content: str = 'gray'  # 消息颜色-内容


config: Config = get_plugin_config(Config)

# 后处理配置
config.bot_player_prefix = config.bot_player_prefix.upper() if config.bot_player_prefix else None
config.message_color_source = config.message_color_source.lower()
config.message_color_player = config.message_color_player.lower()
config.message_color_content = config.message_color_content.lower()

