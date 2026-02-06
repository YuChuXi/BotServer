"""
服务器管理器 - 使用事件路由和并发处理
"""
import asyncio
from typing import Union, Optional, Callable, Any, List
from nonebot.log import logger

from ..Core.Connection import connection_manager
from ..Core.EventRouter import event_router
from ..Core.Message import EventType
from ..Config import config, ServerDetailConfig
# from .Data import data_manager # DataManager may need update or bypass if Config handles it


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
        pass
    
    async def _handle_mcdr_command_response(self, data: Any, echo: Optional[str] = None):
        """处理MCDR命令响应"""
        pass
    
    async def _handle_player_list_response(self, data: list, echo: Optional[str] = None):
        """处理玩家列表响应"""
        pass
    
    async def _handle_occupation_response(self, data: tuple, echo: Optional[str] = None):
        """处理占用率响应"""
        pass
    
    def get_server(self, server_name: str) -> Optional:
        """获取服务器连接"""
        return connection_manager.get(server_name)
    
    def get_server_config(self, group_id: str, server_name: str) -> Optional[ServerDetailConfig]:
        """获取指定群组下某服务器的配置"""
        group_id = str(group_id)
        if group_id in config.group_servers:
            return config.group_servers[group_id].get(server_name)
        return None

    def get_groups_for_server(self, server_name: str) -> List[str]:
        """获取包含该服务器的所有群组ID"""
        groups = []
        for group_id, servers in config.group_servers.items():
            if server_name in servers:
                groups.append(group_id)
        return groups

    async def _request_all_servers(
        self,
        event_type: EventType,
        data: Any = None,
        filter_func: Optional[Callable[[str, Any], bool]] = None,
        callback_extra: Optional[Callable[[str, Any], None]] = None,
        timeout: float = 5.0,
        target_servers: Optional[List[str]] = None
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
            
            # 过滤目标服务器
            if target_servers is not None and name not in target_servers:
                continue

            if filter_func and not filter_func(name, conn):
                continue
            
            future = asyncio.Future()
            futures[name] = future
            echo_id = event_router.request(make_callback(name), timeout=timeout)
            tasks.append(conn.send(event_type, data, echo=echo_id))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            # 等待所有future完成，或者超时（request里已有timeout，这里主要用于future同步）
            # 注意：如果request超时，callback不会被调用，future可能一直pending
            # 所以这里不能死等future，应该依赖request的超时机制
            # 但request是同步的吗？request只是注册。
            # 实际上，上面的 gather(*tasks) 只是发送完成。
            # 我们需要等待回复。
            try:
                if futures:
                    await asyncio.wait_for(asyncio.gather(*futures.values(), return_exceptions=True), timeout=timeout + 0.5)
            except asyncio.TimeoutError:
                pass
        
        return result
    
    async def execute(self, command: str, group_id: Optional[str] = None) -> dict[str, Any]:
        """并发执行命令到服务器，可指定群组"""
        targets = None
        if group_id:
            group_id = str(group_id)
            if group_id in config.group_servers:
                targets = list(config.group_servers[group_id].keys())
            else:
                return {} # 群组不存在
                
        return await self._request_all_servers(EventType.COMMAND, command, target_servers=targets)
    
    async def execute_mcdr(self, command: str) -> dict[str, Any]:
        """并发执行MCDR命令到所有服务器"""
        return await self._request_all_servers(
            EventType.MCDR_COMMAND,
            command,
            filter_func=lambda name, conn: conn.type == 'McdReforged'
        )
    
    async def get_player_list(self, group_id: Optional[str] = None) -> dict[str, list[str]]:
        """并发获取服务器玩家列表，可指定群组"""
        def update_player_list(server_name: str, data: list):
            if conn := connection_manager.get(server_name):
                conn.player_list = data if data else []
        
        targets = None
        if group_id:
            group_id = str(group_id)
            if group_id in config.group_servers:
                targets = list(config.group_servers[group_id].keys())
            else:
                return {}

        return await self._request_all_servers(
            EventType.PLAYER_LIST,
            callback_extra=update_player_list,
            target_servers=targets
        )
    
    async def get_server_occupation(self) -> dict[str, tuple[float, float]]:
        """并发获取所有服务器占用率"""
        return await self._request_all_servers(EventType.SERVER_OCCUPATION)
    
    async def broadcast(self, source: str, player: str = None, message: str = None, group_id: Optional[str] = None, except_server: str = None):
        """并发广播消息到服务器"""
        # 构建消息数据
        message_data = [{'color': config.message_color_source, 'text': F'[{source}] '}]
        if player:
            message_data.append({'color': config.message_color_player, 'text': F'<{player}> '})
        if message:
            message_data.append({'color': config.message_color_content, 'text': message})
        
        targets = None
        if group_id:
            group_id = str(group_id)
            if group_id in config.group_servers:
                targets = config.group_servers[group_id].keys()
            else:
                # 群组未配置服务器
                return

        tasks = []
        for name, conn in connection_manager.connections.items():
            if not conn.status:
                continue
            if name == except_server:
                continue
            if targets is not None and name not in targets:
                continue
            
            # 检查该服务器在该群组的配置是否允许转发聊天
            # (如果指定了group_id，说明是从群里来的消息)
            if group_id:
                server_conf = self.get_server_config(group_id, name)
                if server_conf and not server_conf.enable_sync_group_player_chat:
                     continue
            
            tasks.append(conn.send(EventType.MESSAGE, message_data))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


server_manager = ServerManager()
