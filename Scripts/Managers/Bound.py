"""
绑定管理器 - 管理QQ绑定、黑名单和白名单
"""
import asyncio
import json
from pathlib import Path
from typing import Optional, List
from pydantic import BaseModel, ValidationError
from nonebot.log import logger

from ..Config import config
from ..Core.Connection import connection_manager
from ..Core.Message import EventType


class PlayerBindings(BaseModel):
    """玩家绑定数据"""
    bedrock: List[str] = []
    java: List[str] = []


class BoundData(BaseModel):
    """绑定数据模型"""
    bounds: dict[str, PlayerBindings] = {}
    blacklist: list[str] = []


class BoundManager:
    """绑定管理器"""
    
    def __init__(self):
        self.data_path = Path('./Data/Player.json')
        self.data: BoundData = BoundData()
        self._load()
    
    @staticmethod
    def escape_player_id(player_id: str) -> str:
        """转义玩家ID用于命令（处理空格和特殊字符）"""
        # 如果包含空格或特殊字符，用引号包裹
        if ' ' in player_id or any(c in player_id for c in ['"', "'", '\\', '$', '`']):
            # 转义引号，然后用引号包裹
            escaped = player_id.replace('"', '\\"')
            return f'"{escaped}"'
        return player_id
    
    def _load(self):
        """加载数据"""
        if not self.data_path.exists():
            self.data = BoundData()
            return
        
        try:
            with open(self.data_path, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)
                self.data = BoundData(**raw_data)
        except (json.JSONDecodeError, ValidationError, OSError) as e:
            logger.error(f'加载绑定数据失败: {e}')
            self.data = BoundData()
    
    def save(self):
        """保存数据"""
        try:
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.data_path, 'w', encoding='utf-8') as f:
                json.dump(self.data.model_dump(), f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error(f'保存绑定数据失败: {e}')
    
    def is_blacklisted(self, qq: str) -> bool:
        """检查是否在黑名单中"""
        return qq in self.data.blacklist
    
    def add_blacklist(self, qq: str):
        """添加黑名单"""
        if qq not in self.data.blacklist:
            self.data.blacklist.append(qq)
            self.save()
            logger.info(f'已将QQ {qq} 加入黑名单')
    
    def remove_blacklist(self, qq: str):
        """移除黑名单"""
        if qq in self.data.blacklist:
            self.data.blacklist.remove(qq)
            self.save()
            logger.info(f'已将QQ {qq} 从黑名单移除')
    
    def get_bound_count(self, qq: str) -> int:
        """获取绑定数量"""
        if qq not in self.data.bounds:
            return 0
        bindings = self.data.bounds[qq]
        return len(bindings.bedrock) + len(bindings.java)
    
    def can_bind(self, qq: str) -> bool:
        """检查是否可以绑定"""
        if self.is_blacklisted(qq):
            return False
        return self.get_bound_count(qq) < config.max_bindings_per_qq
    
    async def add_binding(self, qq: str, player_id: str, version: str):
        """添加绑定（version: 'bedrock' 或 'java'），如果不在黑名单则自动加白名单"""
        if qq not in self.data.bounds:
            self.data.bounds[qq] = PlayerBindings()
        
        bindings = self.data.bounds[qq]
        target_list = bindings.bedrock if version == 'bedrock' else bindings.java
        
        if player_id not in target_list:
            target_list.append(player_id)
            self.save()
            logger.info(f'QQ {qq} 绑定{version}玩家 {player_id}')
            
            # 如果用户不在黑名单，自动加白名单
            if not self.is_blacklisted(qq):
                await self.add_whitelist(player_id, version)
    
    async def remove_binding(self, qq: str, player_id: Optional[str] = None, version: Optional[str] = None):
        """移除绑定，同时移除对应的白名单"""
        if qq not in self.data.bounds:
            return
        
        bindings = self.data.bounds[qq]
        
        if player_id and version:
            # 移除特定绑定
            target_list = bindings.bedrock if version == 'bedrock' else bindings.java
            if player_id in target_list:
                # 先移除白名单
                await self.remove_whitelist_by_player(player_id, version)
                # 再移除绑定记录
                target_list.remove(player_id)
                self.save()
                logger.info(f'移除QQ {qq} 的{version}玩家 {player_id} 绑定')
        else:
            # 移除所有绑定
            # 先移除所有白名单
            await self.remove_whitelist(qq, remove_binding=False)
            # 再移除绑定记录
            del self.data.bounds[qq]
            self.save()
            logger.info(f'移除QQ {qq} 的所有绑定')
    
    def get_bindings(self, qq: str) -> PlayerBindings:
        """获取QQ的所有绑定"""
        return self.data.bounds.get(qq, PlayerBindings())
    
    def is_player_id_occupied(self, player_id: str, version: str, exclude_qq: Optional[str] = None) -> Optional[str]:
        """检查玩家ID是否已被占用
        返回占用该ID的QQ号，如果未被占用则返回None
        version: 'bedrock' 或 'java'
        exclude_qq: 排除的QQ号（用于检查自己是否已绑定该ID）
        """
        target_list_name = 'bedrock' if version == 'bedrock' else 'java'
        
        for qq, bindings in self.data.bounds.items():
            if exclude_qq and qq == exclude_qq:
                continue
            
            target_list = bindings.bedrock if version == 'bedrock' else bindings.java
            if player_id in target_list:
                return qq
        
        return None
    
    async def sync_whitelist(self, player_id: str, version: str):
        """同步白名单"""
        import subprocess
        import sys
        # $ syncwhitelist
        process = subprocess.run(
            ['syncwhitelist'],
            stdout=sys.stdout,
            stderr=sys.stderr,
            shell=True
        )
        return process.returncode == 0
    
    async def add_whitelist(self, player_id: str, version: str):
        """添加白名单（version: 'bedrock' 或 'java'）"""
        tasks = []
        # 转义玩家ID以处理空格和特殊字符
        escaped_player_id = self.escape_player_id(player_id)
        command = f'{config.bedrock_whitelist_command} add {escaped_player_id}' if version == 'bedrock' else f'{config.java_whitelist_command} add {escaped_player_id}'
        
        for name, conn in connection_manager.connections.items():
            if conn.status:
                tasks.append(conn.send(EventType.COMMAND, command))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        # 同步白名单
        await self.sync_whitelist(player_id, version)
    
    async def remove_whitelist_by_player(self, player_id: str, version: str):
        """移除特定玩家的白名单（version: 'bedrock' 或 'java'）"""
        tasks = []
        # 转义玩家ID以处理空格和特殊字符
        escaped_player_id = self.escape_player_id(player_id)
        command = f'{config.bedrock_whitelist_command} remove {escaped_player_id}' if version == 'bedrock' else f'{config.java_whitelist_command} remove {escaped_player_id}'
        
        for name, conn in connection_manager.connections.items():
            if conn.status:
                tasks.append(conn.send(EventType.COMMAND, command))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def remove_whitelist(self, qq: str, remove_binding: bool = False):
        """移除QQ绑定的所有白名单"""
        bindings = self.get_bindings(qq)
        
        # 移除基岩版白名单
        tasks = []
        for player_id in bindings.bedrock:
            # 转义玩家ID以处理空格和特殊字符
            escaped_player_id = self.escape_player_id(player_id)
            for name, conn in connection_manager.connections.items():
                if conn.status:
                    tasks.append(conn.send(EventType.COMMAND, f'{config.bedrock_whitelist_command} remove {escaped_player_id}'))
        
        # 移除Java版白名单
        for player_id in bindings.java:
            # 转义玩家ID以处理空格和特殊字符
            escaped_player_id = self.escape_player_id(player_id)
            for name, conn in connection_manager.connections.items():
                if conn.status:
                    tasks.append(conn.send(EventType.COMMAND, f'{config.java_whitelist_command} remove {escaped_player_id}'))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        # 可选：移除绑定记录（退群时不移除，拉黑时移除）
        if remove_binding:
            await self.remove_binding(qq)


bound_manager = BoundManager()

