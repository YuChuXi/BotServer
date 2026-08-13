"""
ServerManager - get_server(name)；多服用 Callable[[Server], bool] 筛选；并发用 __getattribute__ 代理 Server 方法名。
"""

import asyncio
from typing import Optional, Callable, Any, List, Dict, Tuple, Iterable
from nonebot.drivers import WebSocket

from ..Core.Server import Server
from ..Config import config


ServerPredicate = Callable[[Server], bool]


class ServerManager:
    """注册表 + 筛选器 + __getattribute__ 代理 Server 的 async 方法做并发。"""

    def __init__(self):
        self._servers: Dict[str, Server] = {}

    def __getattribute__(self, name: str):
        attr = getattr(Server, name, None)
        if callable(attr) and asyncio.iscoroutinefunction(attr):
            _filter = self._filter_servers
            _method = name

            async def _proxy(
                predicate: ServerPredicate,
                *args,
                return_exceptions: bool = True,
                **kwargs,
            ) -> Dict[str, Any]:
                items = list(_filter(predicate))
                if not items:
                    return {}
                names = [n for n, _ in items]
                servers = [s for _, s in items]
                results = await asyncio.gather(
                    *[getattr(s, _method)(*args, **kwargs) for s in servers],
                    return_exceptions=return_exceptions,
                )
                return dict(zip(names, results))

            return _proxy
        return object.__getattribute__(self, name)

    def register_server_connection(self, name: str, websocket: WebSocket) -> None:
        if name in self._servers:
            s = self._servers[name]
            s.websocket = websocket
            s.status = True
        else:
            self._servers[name] = Server(name, websocket)

    def unregister_server_connection(self, name: str) -> None:
        if name in self._servers:
            self._servers[name].status = False
            del self._servers[name]

    def get_server(self, server_name: str) -> Optional[Server]:
        return self._servers.get(server_name)

    def _filter_servers(
        self, predicate: ServerPredicate
    ) -> Iterable[Tuple[str, Server]]:
        for name, s in self._servers.items():
            if not s.status or not predicate(s):
                continue
            yield name, s

    async def execute_whitelist(
        self,
        group_id: str,
        player_id: str,
        version: str,
        action: str,
        predicate: ServerPredicate,
    ) -> Dict[str, List[str]]:
        group_id = str(group_id)
        raw = await self.send_whitelist(predicate, player_id, version, action)
        result: Dict[str, List[str]] = {"success": [], "failed": [], "skipped": []}
        result["skipped"] = [
            n for n, s in self._servers.items()
            if s.group_id == group_id and n not in raw
        ]
        for name, ok in raw.items():
            result["success" if ok is True else "failed"].append(name)
        return result

    async def broadcast(
        self,
        source: str,
        player: str = None,
        message: str = None,
        predicate: ServerPredicate = lambda s: True,
    ):
        message_data = [{"color": config.message_color_source, "text": f"[{source}] "}]
        if player:
            message_data.append(
                {"color": config.message_color_player, "text": f"<{player}> "}
            )
        if message:
            message_data.append(
                {"color": config.message_color_content, "text": message}
            )
        await self.send_message(predicate, message_data)


server_manager = ServerManager()
