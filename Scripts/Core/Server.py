"""
Core.Server - 单服操作、服务器信息与群绑定、批量执行，全部在此，仅接受 self。
"""
import asyncio
from typing import Optional, Any, Callable, List, Iterable, Union
from nonebot.drivers import WebSocket
from nonebot.exception import WebSocketClosed
from nonebot.log import logger

from .Message import Message, EventType
from .EventRouter import event_router
from ..Config import ServerDetailConfig, config
from ..Utils import strip_format_in_response


class Server:
    """单服操作 + 一服一群，内置 group_id / config。"""

    def __init__(self, name: str, websocket: WebSocket):
        self.name = name
        self.websocket = websocket
        self.type = websocket.request.headers.get("type", "Unknown")
        self.status = True
        self.player_list: list = []

    def _get_binding(self) -> Optional[tuple[str, ServerDetailConfig]]:
        return config.get_server_binding(self.name)

    @property
    def group_id(self) -> Optional[str]:
        binding = self._get_binding()
        return binding[0] if binding else None

    @property
    def config(self) -> Optional[ServerDetailConfig]:
        binding = self._get_binding()
        return binding[1] if binding else None

    def get_group(self) -> Optional[str]:
        """本服唯一所属群 ID。"""
        return self.group_id

    def should_strip_format(self) -> bool:
        """本服是否需要对返回内容清理 § 格式化代码。"""
        return self.config.strip_minecraft_format if self.config else False

    def clean_response(self, data: Any) -> Any:
        """若配置开启则递归清理 data 中的 § 格式化代码（命令返回、事件 payload 等）。"""
        # FIXME: 这里只能清理带echo的
        return strip_format_in_response(data) if self.should_strip_format() else data

    @staticmethod
    def escape_player_id(player_id: str) -> str:
        """转义玩家ID用于命令（处理空格和特殊字符）"""
        if ' ' in player_id or any(c in player_id for c in ['"', "'", '\\', '$', '`']):
            escaped = player_id.replace('"', '\\"')
            return f'"{escaped}"'
        return player_id

    @staticmethod
    def bedrock_to_java_id(bedrock_id: str) -> str:
        """基岩版ID转Java版ID (Offline Geyser)"""
        # 将空格替换为下划线, 在头部添加".", 然后截断到16个字符
        new_id = "." + bedrock_id.replace(" ", "_")
        return new_id[:16]

    def get_whitelist_command(self, player_id: str, version: str, action: str) -> Optional[str]:
        """本服白名单命令字符串，无 config 返回 None。"""
        if not self.config:
            return None
        template = self.config.bedrock_whitelist_command if version == 'bedrock' else self.config.java_whitelist_command
        return template.format(
            action=action,
            java_id=player_id,
            bedrock_id=player_id,
            bedrock_id_to_java_id=self.bedrock_to_java_id(player_id),
        )

    async def send_whitelist(self, player_id: str, version: str, action: str) -> bool:
        """单服：构建并发送白名单命令。"""
        cmd = self.get_whitelist_command(player_id, version, action)
        return await self.send_command(cmd) if cmd else False

    async def send(self, event_type: EventType | str, data: Any = None, echo: Optional[str] = None) -> bool:
        if not self.status or self.websocket.closed:
            return False
        if isinstance(event_type, str):
            try:
                event_type = EventType(event_type)
            except ValueError:
                logger.warning(f"未知事件类型: {event_type}")
                return False
        message = Message(type=event_type, data=data, echo=echo)
        try:
            await self.websocket.send(message.model_dump_json(exclude_none=True))
            logger.debug(f"[{self.name}] 发送消息: {event_type.value}, echo={echo}")
            return True
        except (WebSocketClosed, ConnectionError):
            self.status = False
            logger.warning(f"[{self.name}] 连接已断开")
            return False

    async def close(self):
        self.status = False
        if self.websocket and not self.websocket.closed:
            await self.websocket.close()

    async def send_command(self, command: str) -> bool:
        return await self.send(EventType.COMMAND, command)

    async def send_message(self, message_data: Any) -> bool:
        return await self.send(EventType.MESSAGE, message_data)

    async def request(
        self,
        event_type: EventType,
        data: Any,
        timeout: float = 5.0,
        on_response: Optional[Callable[[Any], None]] = None,
    ) -> Any:
        if not self.status:
            return None
        fut = asyncio.Future()

        async def cb(d: Any):
            d = self.clean_response(d)
            if on_response:
                on_response(d)
            if not fut.done():
                fut.set_result(d)

        echo_id = event_router.request(cb, timeout=timeout)
        await self.send(event_type, data, echo=echo_id)
        try:
            return await asyncio.wait_for(fut, timeout=timeout + 0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return None

    async def execute_batch(self, commands: Union[str, Iterable[str]], timeout: float = 5.0) -> List[Any]:
        """单服：顺序执行多条命令，返回每条的回包列表。"""
        out: List[Any] = []
        if isinstance(commands, str):
            commands = [commands]
        for cmd in commands:
            r = await self.request(EventType.COMMAND, cmd, timeout=timeout)
            out.append(r)
        return out

    def set_player_list(self, data: list) -> None:
        self.player_list = data or []

    async def request_player_list(self) -> Any:
        return await self.request(EventType.PLAYER_LIST, None, on_response=lambda d: self.set_player_list(d))

    async def request_server_occupation(self) -> Any:
        return await self.request(EventType.SERVER_OCCUPATION, None)

    async def request_mcdr(self, command: Union[str, Iterable[str]], timeout: float = 5.0) -> Any:
        """单服：发 MCDR 命令。单条返回 result，多条返回 [result, ...]。"""
        commands = [command] if isinstance(command, str) else list(command)
        if len(commands) == 1:
            return await self.request(EventType.MCDR_COMMAND, commands[0], timeout=timeout)
        return [await self.request(EventType.MCDR_COMMAND, cmd, timeout=timeout) for cmd in commands]
