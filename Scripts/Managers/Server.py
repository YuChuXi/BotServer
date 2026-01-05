"""
服务器管理器 - 使用事件路由和并发处理
"""
import asyncio
from typing import Union, Optional, Callable, Awaitable, Any
from nonebot.log import logger

from ..Core.Connection import connection_manager
from ..Core.EventRouter import event_router
from ..Core.Message import EventType
from ..Config import config
from .Data import data_manager


class ServerManager:
    """服务器管理器"""
    
    def __init__(self):
        self._init_handlers()
    
    def _init_handlers(self):
        """初始化事件处理器"""
        # 注册响应处理器
        event_router.register(EventType.COMMAND_RESPONSE.value, self._handle_command_response)
        event_router.register(EventType.MCDR_COMMAND_RESPONSE.value, self._handle_mcdr_command_response)
        event_router.register(EventType.PLAYER_LIST_RESPONSE.value, self._handle_player_list_response)
        event_router.register(EventType.SERVER_OCCUPATION_RESPONSE.value, self._handle_occupation_response)
    
    async def _handle_command_response(self, data: Any, echo: Optional[str] = None):
        """处理命令响应"""
        # 响应通过callback处理，这里不需要额外操作
        pass
    
    async def _handle_mcdr_command_response(self, data: Any, echo: Optional[str] = None):
        """处理MCDR命令响应"""
        # 响应通过callback处理，这里不需要额外操作
        pass
    
    async def _handle_player_list_response(self, data: list, echo: Optional[str] = None):
        """处理玩家列表响应"""
        # 响应通过callback处理，callback会更新result，这里不需要额外操作
        pass
    
    async def _handle_occupation_response(self, data: tuple, echo: Optional[str] = None):
        """处理占用率响应"""
        # 响应通过callback处理，这里不需要额外操作
        pass
    
    def get_server(self, server_flag: Union[str, int]) -> Optional:
        """获取服务器连接"""
        if isinstance(server_flag, int) or (isinstance(server_flag, str) and server_flag.isdigit()):
            index = int(server_flag)
            if index > len(data_manager.servers):
                return None
            server_flag = data_manager.servers[index - 1]
        
        return connection_manager.get(server_flag)
    
    async def _request_all_servers(
        self,
        event_type: EventType,
        data: Any = None,
        filter_func: Optional[Callable[[str, Any], bool]] = None,
        callback_extra: Optional[Callable[[str, Any], None]] = None,
        timeout: float = 5.0
    ) -> dict[str, Any]:
        """通用的并发请求所有服务器方法"""
        result = {}
        futures = {}
        
        def make_callback(server_name: str):
            async def cb(response_data: Any):
                result[server_name] = response_data
                if callback_extra:
                    callback_extra(server_name, response_data)
                if server_name in futures:
                    futures[server_name].set_result(response_data)
            return cb
        
        tasks = []
        
        for name, conn in connection_manager.connections.items():
            if not conn.status:
                continue
            if filter_func and not filter_func(name, conn):
                continue
            
            future = asyncio.Future()
            futures[name] = future
            echo_id = event_router.request(make_callback(name), timeout=timeout)
            tasks.append(conn.send(event_type, data, echo=echo_id))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            if futures:
                await asyncio.gather(*futures.values(), return_exceptions=True)
        
        return result
    
    async def execute(self, command: str) -> dict[str, Any]:
        """并发执行命令到所有服务器，返回执行结果"""
        return await self._request_all_servers(EventType.COMMAND, command)
    
    async def execute_mcdr(self, command: str) -> dict[str, Any]:
        """并发执行MCDR命令到所有服务器，返回执行结果"""
        return await self._request_all_servers(
            EventType.MCDR_COMMAND,
            command,
            filter_func=lambda name, conn: conn.type == 'McdReforged'
        )
    
    async def get_player_list(self) -> dict[str, list[str]]:
        """并发获取所有服务器玩家列表"""
        def update_player_list(server_name: str, data: list):
            if conn := connection_manager.get(server_name):
                conn.player_list = data if data else []
        
        return await self._request_all_servers(
            EventType.PLAYER_LIST,
            callback_extra=update_player_list
        )
    
    async def get_server_occupation(self) -> dict[str, tuple[float, float]]:
        """并发获取所有服务器占用率"""
        return await self._request_all_servers(EventType.SERVER_OCCUPATION)
    
    async def broadcast(self, source: str, player: str = None, message: str = None, except_server: str = None):
        """并发广播消息到所有服务器"""
        message_data = [{'color': config.message_color_source, 'text': F'[{source}] '}]
        if player:
            message_data.append({'color': config.message_color_player, 'text': F'<{player}> '})
        if message:
            message_data.append({'color': config.message_color_content, 'text': message})
        
        tasks = []
        for name, conn in connection_manager.connections.items():
            if conn.status and name != except_server:
                tasks.append(conn.send(EventType.MESSAGE, message_data))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


server_manager = ServerManager()
