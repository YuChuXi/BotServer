"""
消息模型和事件类型枚举
"""
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel


class EventType(str, Enum):
    """事件类型枚举"""
    # 服务器事件
    SERVER_STARTUP = 'server_startup'
    SERVER_SHUTDOWN = 'server_shutdown'
    
    # 玩家事件
    PLAYER_JOINED = 'player_joined'
    PLAYER_LEFT = 'player_left'
    PLAYER_CHAT = 'player_chat'
    PLAYER_DEATH = 'player_death'
    
    # 消息事件
    MESSAGE = 'message'
    
    # 命令请求
    COMMAND = 'command'
    MCDR_COMMAND = 'mcdr_command'
    PLAYER_LIST = 'player_list'
    SERVER_OCCUPATION = 'server_occupation'
    
    # 响应
    COMMAND_RESPONSE = 'command_response'
    MCDR_COMMAND_RESPONSE = 'mcdr_command_response'
    PLAYER_LIST_RESPONSE = 'player_list_response'
    SERVER_OCCUPATION_RESPONSE = 'server_occupation_response'


class Message(BaseModel):
    """WebSocket消息模型"""
    type: EventType
    data: Optional[Any] = None
    echo: Optional[str] = None

