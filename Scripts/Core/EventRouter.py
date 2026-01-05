"""
事件路由系统 - 使用echo消息标记和callback机制
"""
import asyncio
import uuid
from typing import Callable, Optional, Any, Awaitable
from collections import defaultdict
from nonebot.log import logger

from .Message import Message, EventType


class EventRouter:
    """事件路由器，支持echo标记和callback"""
    
    def __init__(self):
        # 事件处理器: {event_type: [handler1, handler2, ...]}
        self._handlers: defaultdict[str, list[Callable]] = defaultdict(list)
        
        # 请求回调: {echo_id: callback}
        self._callbacks: dict[str, Callable[[Any], Awaitable[None]]] = {}
        
        # 请求超时管理
        self._timeouts: dict[str, asyncio.Task] = {}
    
    def register(self, event_type: str, handler: Callable):
        """注册事件处理器"""
        self._handlers[event_type].append(handler)
        logger.debug(F'注册事件处理器: {event_type}')
    
    def unregister(self, event_type: str, handler: Callable):
        """取消注册事件处理器"""
        if handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)
    
    async def emit(self, event_type: str, data: Any, echo: Optional[str] = None, server_name: Optional[str] = None):
        """发送事件，支持echo标记和服务器名称"""
        handlers = self._handlers.get(event_type, [])
        if not handlers:
            logger.warning(F'没有找到事件类型 {event_type} 的处理器')
            return
        
        # 并发执行所有处理器
        tasks = [handler(data, echo, server_name) for handler in handlers]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    def request(self, callback: Callable[[Any], Awaitable[None]], timeout: float = 5.0) -> str:
        """创建请求，返回echo_id"""
        echo_id = str(uuid.uuid4())
        self._callbacks[echo_id] = callback
        
        # 设置超时
        async def timeout_handler():
            await asyncio.sleep(timeout)
            if echo_id in self._callbacks:
                del self._callbacks[echo_id]
                if echo_id in self._timeouts:
                    del self._timeouts[echo_id]
                logger.warning(F'请求 {echo_id} 超时')
        
        self._timeouts[echo_id] = asyncio.create_task(timeout_handler())
        return echo_id
    
    async def response(self, echo: str, data: Any):
        """处理响应，调用对应的callback"""
        if echo not in self._callbacks:
            logger.warning(F'收到未知echo的响应: {echo}')
            return
        
        callback = self._callbacks.pop(echo, None)
        if echo in self._timeouts:
            self._timeouts[echo].cancel()
            del self._timeouts[echo]
        
        if callback:
            try:
                await callback(data)
            except Exception as e:
                logger.error(F'执行callback时出错: {e}')
    
    async def handle_message(self, message: Message, server_name: Optional[str] = None):
        """处理消息，自动路由到对应处理器或callback"""
        # 如果有echo，说明是响应消息
        if message.echo:
            await self.response(message.echo, message.data)
        else:
            # 否则是事件消息
            await self.emit(message.type.value, message.data, message.echo, server_name)


# 全局事件路由器
event_router = EventRouter()

