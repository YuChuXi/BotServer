"""
绑定管理器 - 管理QQ绑定、黑名单和白名单
"""
import asyncio
import json
import re
from pathlib import Path
from typing import Optional, List, Dict
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
                
            # 数据迁移：如果bounds是直接的QQ->Bindings，说明是旧数据
            # 检查raw_data['bounds']的第一个值
            if 'bounds' in raw_data and raw_data['bounds']:
                first_key = next(iter(raw_data['bounds']))
                first_val = raw_data['bounds'][first_key]
                # 旧数据：values是{'bedrock': [], 'java': []}
                # 新数据：values是 Dict[qq, Bindings]
                # 简单判断：看key是不是QQ号（通常长度较长），但群号也是数字。
                # 更准确：看value结构。旧版value有bedrock/java字段。
                if 'bedrock' in first_val or 'java' in first_val:
                    logger.info("检测到旧版绑定数据，正在迁移到群组 711159914...")
                    old_bounds = raw_data['bounds']
                    new_bounds = {"711159914": old_bounds}
                    raw_data['bounds'] = new_bounds
                    # 立即保存迁移后的结构
                    self.data = BoundData(**raw_data)
                    self.save()
                    return

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
    
    async def add_binding(self, qq: str, player_id: str, version: str, group_id: str):
        """添加绑定（version: 'bedrock' 或 'java'），并同步白名单"""
        group_id = str(group_id)
        qq = str(qq)
        
        if group_id not in self.data.bounds:
            self.data.bounds[group_id] = {}
            
        group_bindings = self.data.bounds[group_id]
        if qq not in group_bindings:
            group_bindings[qq] = PlayerBindings()
        
        bindings = group_bindings[qq]
        target_list = bindings.bedrock if version == 'bedrock' else bindings.java
        
        if player_id not in target_list:
            target_list.append(player_id)
            self.save()
            logger.info(f'群 {group_id} QQ {qq} 绑定{version}玩家 {player_id}')
            await self.add_whitelist(player_id, version, group_id)
    
    async def remove_binding(self, qq: str, group_id: str):
        """移除绑定，同时移除对应的白名单"""
        group_id = str(group_id)
        qq = str(qq)
        bindings = self.get_bindings(qq, group_id)
        
        # 移除基岩版白名单
        tasks = []
        for player_id in bindings.bedrock:
            tasks.append(self.remove_whitelist(player_id, 'bedrock', group_id))
        
        # 移除Java版白名单
        for player_id in bindings.java:
            tasks.append(self.remove_whitelist(player_id, 'java', group_id))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # 移除绑定记录
        group_bindings = self.get_group_bindings(group_id)
        if qq in group_bindings:
            del group_bindings[qq]
            self.save()
            logger.info(f'群 {group_id} 移除QQ {qq} 的所有绑定')
    
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
    
    def _format_command(self, template: str, java_id: str, bedrock_id: str) -> str:
        """格式化命令"""
        bedrock_id_to_java = self.bedrock_to_java_id(bedrock_id)
        # 简单的替换
        cmd = template.replace("{java_id}", java_id)
        cmd = cmd.replace("{bedrock_id}", bedrock_id)
        cmd = cmd.replace("{bedrock_id_to_java_id}", bedrock_id_to_java)
        return cmd

    async def add_whitelist(self, player_id: str, version: str, group_id: str):
        """添加白名单"""
        group_id = str(group_id)
        if group_id not in config.group_servers:
            logger.warning(f"群 {group_id} 未配置服务器，无法添加白名单")
            return

        tasks = []
        servers_config = config.group_servers[group_id]
        
        # 准备ID
        java_id = player_id
        bedrock_id = player_id
        
        for server_name, server_conf in servers_config.items():
            conn = connection_manager.get(server_name)
            if not conn or not conn.status:
                continue
            
            # 根据版本选择命令模板
            cmd_template = ""
            if version == 'bedrock':
                cmd_template = server_conf.bedrock_whitelist_command
            else:
                cmd_template = server_conf.java_whitelist_command
            
            final_cmd = cmd_template.replace("{java_id}", player_id) \
                                    .replace("{bedrock_id}", player_id) \
                                    .replace("{bedrock_id_to_java_id}", self.bedrock_to_java_id(player_id))
            
            tasks.append(conn.send(EventType.COMMAND, final_cmd))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def remove_whitelist(self, player_id: str, version: str, group_id: str):
        """移除白名单"""
        group_id = str(group_id)
        if group_id not in config.group_servers:
            return

        tasks = []
        servers_config = config.group_servers[group_id]
        
        for server_name, server_conf in servers_config.items():
            conn = connection_manager.get(server_name)
            if not conn or not conn.status:
                continue
            
            # 尝试从添加命令推导移除命令
            cmd_template = ""
            if version == 'bedrock':
                cmd_template = server_conf.bedrock_whitelist_command
            else:
                cmd_template = server_conf.java_whitelist_command
            
            # 推导逻辑:
            # 1. 如果包含 " add "，替换为 " remove "
            # 2. 如果不包含 " add "，但在开头是 "whitelist" 或 "easywhitelist" 或 "fwhitelist"，则插入 " remove"
            
            remove_cmd = ""
            if " add " in cmd_template:
                remove_cmd = cmd_template.replace(" add ", " remove ")
            else:
                # 尝试智能插入
                first_word = cmd_template.split(' ')[0]
                if first_word in ['whitelist', 'easywhitelist', 'fwhitelist', 'lp']:
                     remove_cmd = cmd_template.replace(first_word, f"{first_word} remove", 1)
                else:
                    # 无法推导，默认尝试在命令词后加 remove
                    # 比如 "mycmd {id}" -> "mycmd remove {id}"
                    remove_cmd = cmd_template.replace(first_word, f"{first_word} remove", 1)

            final_cmd = remove_cmd.replace("{java_id}", player_id) \
                                  .replace("{bedrock_id}", player_id) \
                                  .replace("{bedrock_id_to_java_id}", self.bedrock_to_java_id(player_id))
            
            tasks.append(conn.send(EventType.COMMAND, final_cmd))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

bound_manager = BoundManager()
