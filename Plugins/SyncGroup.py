"""
双向同步聊天群插件 - 监听聊天群消息并转发到所有服务器
"""
from nonebot import on_message, get_bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.log import logger

from Scripts.Config import config
from Scripts.Managers import server_manager, nickname_manager

matcher = on_message(priority=5, block=False)


def unescape(message: str) -> str:
    """反转义消息
    | 符号   | 转义为 |
    |-------|-------|
    | &#44; | ,    |
    | &#93; | ]    |
    | &#91; | [    |
    | &amp; | &    |
    """
    return message.replace('&#44;', ',').replace('&#93;', ']').replace('&#91;', '[').replace('&amp;', '&')

def escape(message: str) -> str:
    """转义消息
    | 符号   | 转义为 |
    |-------|-------|
    | &    | &amp; |
    | [    | &#91; |
    | ]    | &#93; |
    | ,    | &#44; |
    """
    return message.replace('&', '&amp;').replace('[', '&#91;').replace(']', '&#93;').replace(',', '&#44;')



def parse_cq_code(content: str) -> dict:
    """解析CQ码内容为字典"""
    kwargs = {}
    args = content.split(',')
    if not args:
        return kwargs
    
    kwargs['type'] = args[0]
    for arg in args[1:]:
        if '=' in arg:
            k, v = arg.split('=', 1)
            kwargs[unescape(k)] = unescape(v)
        else:
            kwargs[unescape(arg)] = None
    return kwargs


async def convert_cq_code(kwargs: dict, event: GroupMessageEvent) -> str:
    """将CQ码转换为目标格式"""
    cq_type = kwargs.get('type', '')
    
    if cq_type == 'at':
        qq = kwargs.get('qq')
        nickname = await nickname_manager.get_nickname(qq, event.group_id)
        return f"@{nickname}" 
    
    elif cq_type == 'image':
        url = kwargs.get('url', '')
        summary = kwargs.get('summary', '').replace('[', '').replace(']', '')
        filename = kwargs.get('file', '')
        name = summary or filename
        return f"[[CICode,url={url},name={name}]]"
    
    else:
        return f"[{cq_type}]"


def find_cq_code_end(message: str, start: int) -> int:
    """查找CQ码的结束位置，返回结束]的位置，未找到返回-1"""
    bracket_count = 1
    i = start + 4  # 跳过 '[CQ:'
    
    while i < len(message):
        if message[i] == '[':
            bracket_count += 1
        elif message[i] == ']':
            bracket_count -= 1
            if bracket_count == 0:
                return i
        i += 1
    
    return -1


async def handle_message(event: GroupMessageEvent) -> str:
    """处理CQ码消息"""
    message = str(event.message).strip()
    
    if not message or message.startswith('#'):
        return None

    # 分段处理：文本和CQ码交替出现
    result_parts = []
    i = 0
    
    while i < len(message):
        # 查找下一个CQ码
        cq_start = message.find('[CQ:', i)
        
        if cq_start == -1:
            # 没有更多CQ码，添加剩余文本
            result_parts.append(unescape(message[i:]))
            break
        
        # 添加CQ码之前的普通文本
        if cq_start > i:
            result_parts.append(unescape(message[i:cq_start]))
        
        # 查找CQ码结束位置
        cq_end = find_cq_code_end(message, cq_start)
        
        if cq_end == -1:
            # 未找到结束]，将剩余部分作为普通文本
            result_parts.append(unescape(message[cq_start:]))
            break
        
        # 提取并解析CQ码
        cq_content = message[cq_start + 4:cq_end]  # 跳过 '[CQ:' 和 ']'
        kwargs = parse_cq_code(cq_content)
        converted = await convert_cq_code(kwargs, event)
        result_parts.append(converted)
        
        i = cq_end + 1  # 继续处理下一个字符
    
    return ''.join(result_parts)
    

@matcher.handle()
async def handle_sync_group_message(event: GroupMessageEvent):
    """处理聊天群消息，转发到所有服务器"""
    # 只处理双向同步聊天群的消息
    if event.group_id != config.sync_qq_group:
        return
    
    # 过滤机器人自己的消息
    bot = get_bot()
    if event.user_id == bot.self_id:
        return
    
    message_text = await handle_message(event)
    
    if not message_text:
        return

    # 获取发送者信息
    sender_name = event.sender.card or event.sender.nickname or f'QQ{event.user_id}'
    
    logger.info(f'收到聊天群 [{event.group_id}] 消息，转发到所有服务器: {sender_name}: {message_text}')
    
    # 转发到所有服务器，包含发送者信息
    await server_manager.broadcast('QQ群', player=sender_name, message=message_text)

