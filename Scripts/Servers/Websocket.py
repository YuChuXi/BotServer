"""
WebSocket服务器 - 使用事件路由处理消息
"""
import asyncio
from nonebot import get_driver
from nonebot.drivers import WebSocketServerSetup, WebSocket, ASGIMixin, URL
from nonebot.exception import WebSocketClosed
from nonebot.log import logger

from ..Core.EventRouter import event_router
from ..Core.Handlers import register_handlers
from ..Managers import server_manager
from ..Core.Auth import AuthInfo
from ..Core.Message import Message
from ..Utils import decode_header, strip_format_in_response
from ..Config import config
from ..Managers import data_manager

# 初始化事件处理器
register_handlers()


async def verify(websocket: WebSocket):
    """验证连接"""
    logger.info('检测到 WebSocket 链接，正在验证身份……')
    if info_header := websocket.request.headers.get('info'):
        try:
            raw_info = decode_header(info_header)
            auth_info = AuthInfo(**raw_info)
            
            if auth_info.token != config.token or not auth_info.name:
                await websocket.close(1008, 'Error token or name.')
                logger.warning('身份验证失败！')
                return None
            
            logger.success(f'身份验证成功，服务器 [{auth_info.name}] 已连接！')
            await websocket.accept()
            return auth_info.name
        except Exception as e:
            logger.error(f'解析认证信息失败: {e}')
            await websocket.close(1008, 'Error parsing auth info.')
            return None
    return None


async def handle_websocket(websocket: WebSocket):
    """处理WebSocket连接"""
    if not (name := await verify(websocket)):
        return
    
    data_manager.append_server(name)
    server_manager.register_server_connection(name, websocket)

    try:
        while True:
            try:
                # 接收消息
                raw_message = await websocket.receive_text()
                # 直接使用Pydantic解析JSON
                message = Message.model_validate_json(raw_message)
                # 响应在 Server.request 的 callback 里清理；仅对事件在入口清理 § 格式
                if not message.echo:
                    server = server_manager.get_server(name)
                    if server and server.should_strip_format() and message.data is not None:
                        message = message.model_copy(update={"data": strip_format_in_response(message.data)})
                await event_router.handle_message(message, server_name=name)
            except WebSocketClosed:
                break
            except Exception as e:
                logger.error(F'处理来自 [{name}] 的消息时出错: {e}')
    except (ConnectionError, WebSocketClosed):
        logger.info(F'WebSocket 连接与 [{name}] 已关闭！')
    finally:
        server_manager.unregister_server_connection(name)
        logger.info(F'已清理服务器 [{name}] 的连接状态')


def setup_websocket_server():
    """设置WebSocket服务器"""
    if isinstance((driver := get_driver()), ASGIMixin):
        server = WebSocketServerSetup(URL('/websocket/server'), 'server', handle_websocket)
        driver.setup_websocket_server(server)
        logger.success('装载 WebSocket 服务器成功！')
        return None
    logger.error('装载 WebSocket 服务器失败！')
    exit(1)
