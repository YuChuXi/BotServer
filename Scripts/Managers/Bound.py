"""
绑定管理器 - 管理QQ绑定、黑名单；白名单同步委托给服务器层
"""
import asyncio
import json
import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Union, Literal
from pydantic import BaseModel, ValidationError
from nonebot.log import logger

from ..Config import config
from .Server import server_manager


class PlayerBindings(BaseModel):
    """玩家绑定数据"""
    bedrock: List[str] = []
    java: List[str] = []


class BoundData(BaseModel):
    """绑定数据模型"""
    # GroupID -> QQ -> Bindings
    bounds: Dict[str, Dict[str, PlayerBindings]] = {}
    blacklist: list[str] = []


class BoundManager:
    """绑定管理器"""
    
    # ID校验正则
    JAVA_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_]{3,16}$")
    BEDROCK_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_ ]{1,14}[a-zA-Z0-9_]$")
    
    def __init__(self):
        self.data_path = Path('./Data/Player.json')
        self.data: BoundData = BoundData()
        self._load()
    
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
    
    def validate_id(self, player_id: str, version: str) -> bool:
        """校验玩家ID格式"""
        if version == 'java':
            return bool(self.JAVA_ID_PATTERN.match(player_id))
        elif version == 'bedrock':
            return bool(self.BEDROCK_ID_PATTERN.match(player_id))
        return False

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
    
    def get_group_bindings(self, group_id: str) -> Dict[str, PlayerBindings]:
        """获取指定群的所有绑定"""
        return self.data.bounds.get(str(group_id), {})

    def get_bindings(self, qq: str, group_id: str) -> PlayerBindings:
        """获取QQ在指定群的绑定"""
        group_bindings = self.get_group_bindings(str(group_id))
        return group_bindings.get(str(qq), PlayerBindings())
    
    def get_bound_count(self, qq: str, group_id: str) -> int:
        """获取绑定数量"""
        bindings = self.get_bindings(qq, group_id)
        return len(bindings.bedrock) + len(bindings.java)
    
    def can_bind(self, qq: str, group_id: str) -> bool:
        """检查是否可以绑定"""
        return self.get_bound_count(qq, group_id) < config.max_bindings_per_qq

    async def try_add_binding(
        self, qq: str, player_id: str, version: str, group_id: str
    ) -> Union[
        Tuple[Literal["new"], Dict[str, List[str]]],
        Tuple[Literal["resync"], Dict[str, List[str]]],
        Tuple[Literal["limit"], PlayerBindings],
        Tuple[Literal["occupied"], str],
    ]:
        """
        尝试添加绑定或重同步白名单。只返回状态与数据，文案由调用方负责。
        - ('new', wl): 新绑定
        - ('resync', wl): 已绑定该 ID，本次仅重同步白名单
        - ('limit', bindings): 已达上限且非当前已绑定 ID，带当前绑定数据供展示
        - ('occupied', qq): 该玩家 ID 已被其他 QQ 绑定
        """
        group_id = str(group_id)
        qq = str(qq)
        occupied = self.is_player_id_occupied(player_id, version, group_id, exclude_qq=qq)
        if occupied:
            return ("occupied", occupied)
        bindings = self.get_bindings(qq, group_id)
        target_list = bindings.bedrock if version == "bedrock" else bindings.java
        at_limit = not self.can_bind(qq, group_id)
        if at_limit and player_id not in target_list:
            return ("limit", bindings)

        if group_id not in self.data.bounds:
            self.data.bounds[group_id] = {}
        group_bindings = self.data.bounds[group_id]
        if qq not in group_bindings:
            group_bindings[qq] = PlayerBindings()
        bindings = group_bindings[qq]
        target_list = bindings.bedrock if version == "bedrock" else bindings.java
        is_new = player_id not in target_list
        if is_new:
            target_list.append(player_id)
            self.save()
            logger.info(f"群 {group_id} QQ {qq} 绑定{version}玩家 {player_id}")
        else:
            logger.info(f"群 {group_id} QQ {qq} 已绑定{version}玩家 {player_id}，重新同步白名单")
        wl = await server_manager.execute_whitelist(
            group_id, player_id, version, "add", self.bedrock_to_java_id
        )
        return ("new", wl) if is_new else ("resync", wl)
    
    @staticmethod
    def _merge_whitelist_results(
        results: List[Dict[str, List[str]]],
    ) -> Dict[str, List[str]]:
        """合并多次白名单执行结果（失败优先）。"""
        failed = set()
        success = set()
        skipped = set()
        for r in results:
            if not isinstance(r, dict):
                continue
            failed |= set(r.get('failed', []))
            success |= set(r.get('success', []))
            skipped |= set(r.get('skipped', []))
        return {
            'success': list(success - failed),
            'failed': list(failed),
            'skipped': list(skipped - failed - success),
        }

    async def remove_binding(self, qq: str, group_id: str) -> Dict[str, List[str]]:
        """移除绑定，同时移除对应的白名单，返回白名单同步结果。"""
        group_id = str(group_id)
        qq = str(qq)
        bindings = self.get_bindings(qq, group_id)

        tasks = [
            server_manager.execute_whitelist(group_id, pid, 'bedrock', 'remove', self.bedrock_to_java_id)
            for pid in bindings.bedrock
        ] + [
            server_manager.execute_whitelist(group_id, pid, 'java', 'remove', self.bedrock_to_java_id)
            for pid in bindings.java
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []

        group_bindings = self.get_group_bindings(group_id)
        if qq in group_bindings:
            del group_bindings[qq]
            self.save()
            logger.info(f'群 {group_id} 移除QQ {qq} 的所有绑定')

        return self._merge_whitelist_results([r for r in results if isinstance(r, dict)])
    
    def is_player_id_occupied(self, player_id: str, version: str, group_id: str, exclude_qq: Optional[str] = None) -> Optional[str]:
        """检查玩家ID是否已被占用 (在当前群)"""
        group_bindings = self.get_group_bindings(str(group_id))
        
        for qq, bindings in group_bindings.items():
            if exclude_qq and str(qq) == str(exclude_qq):
                continue
            
            target_list = bindings.bedrock if version == 'bedrock' else bindings.java
            if player_id in target_list:
                return qq
        
        return None

bound_manager = BoundManager()
