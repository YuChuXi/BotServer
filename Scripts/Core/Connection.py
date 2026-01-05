"""
连接管理 - 管理WebSocket连接和消息收发
"""
import asyncio
from typing import Optional, Any
from nonebot.drivers import WebSocket
from nonebot.exception import WebSocketClosed
from nonebot.log import logger

from .Message import Message, EventType


class Connection:
    """单个服务器连接"""
    
    def __init__(self, name: str, websocket: WebSocket):
        self.name = name
        self.websocket = websocket
        self.type = websocket.request.headers.get('type', 'Unknown')
        self.status = True
        self.player_list = []
    
    async def send(self, event_type: EventType | str, data: Any = None, echo: Optional[str] = None):
        """发送消息，支持echo标记"""
        if not self.status or self.websocket.closed:
            return False
        
        # 如果是字符串，转换为枚举
        if isinstance(event_type, str):
            try:
                event_type = EventType(event_type)
            except ValueError:
                logger.warning(f'未知事件类型: {event_type}')
                return False
        
        message = Message(type=event_type, data=data, echo=echo)
        
        try:
            await self.websocket.send(message.model_dump_json(exclude_none=True))
            logger.debug(F'[{self.name}] 发送消息: {event_type.value}, echo={echo}')
            return True
        except (WebSocketClosed, ConnectionError):
            self.status = False
            logger.warning(F'[{self.name}] 连接已断开')
            return False
    
    async def close(self):
        """关闭连接"""
        self.status = False
        if self.websocket and not self.websocket.closed:
            await self.websocket.close()


class ConnectionManager:
    """连接管理器"""
    
    def __init__(self):
        self.connections: dict[str, Connection] = {}
    
    def add(self, name: str, websocket: WebSocket) -> Connection:
        """添加连接"""
        if name in self.connections:
            old_conn = self.connections[name]
            old_conn.websocket = websocket
            old_conn.status = True
            return old_conn
        
        conn = Connection(name, websocket)
        self.connections[name] = conn
        return conn
    
    def get(self, name: str) -> Optional[Connection]:
        """获取连接"""
        return self.connections.get(name)
    
    def remove(self, name: str):
        """移除连接"""
        if name in self.connections:
            self.connections[name].status = False
            del self.connections[name]
    
    def get_all_online(self) -> list[Connection]:
        """获取所有在线连接"""
        return [conn for conn in self.connections.values() if conn.status]
    
    async def broadcast(self, event_type: EventType | str, data: Any = None, except_name: Optional[str] = None):
        """广播消息到所有连接"""
        tasks = []
        for name, conn in self.connections.items():
            if conn.status and name != except_name:
                tasks.append(conn.send(event_type, data))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


# 全局连接管理器
connection_manager = ConnectionManager()

