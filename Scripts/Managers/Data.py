"""
数据管理器
"""
from pathlib import Path
from typing import List, Dict, Union
import json
from nonebot.log import logger

from ..Config import config, ServerDetailConfig


class DataManager:
    def __init__(self):
        self.data_path = Path('./Data/Server.json')
        # 我们不再维护独立的 self.data，而是直接操作 config.group_servers
        # 但为了兼容旧代码调用，可能需要保留一些接口
        self._load()
    
    def _load(self):
        """加载数据"""
        if self.data_path.exists():
            try:
                with open(self.data_path, 'r', encoding='utf-8') as f:
                    raw_data = json.load(f)
                self._update_config(raw_data)
                
            except Exception as e:
                logger.error(f'加载数据失败: {e}')
                # 如果加载失败，保持 config 中的默认值（可能是空的）
        else:
            # 文件不存在，初始化为空
            pass
    
    def _update_config(self, data: Dict):
        """更新全局配置 config.group_servers"""
        config.group_servers.clear()
        for group_id, servers in data.items():
            config.group_servers[group_id] = {}
            for server_name, server_conf in servers.items():
                # 兼容：如果server_conf是字典，转为对象；如果是对象直接使用
                if isinstance(server_conf, dict):
                    config.group_servers[group_id][server_name] = ServerDetailConfig(**server_conf)
                else:
                    config.group_servers[group_id][server_name] = server_conf

    def load(self):
        """公开的加载方法"""
        self._load()
    
    def save(self):
        """保存数据"""
        try:
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 将 config.group_servers 转换为可序列化的字典
            dump_data = {}
            for group_id, servers in config.group_servers.items():
                dump_data[group_id] = {}
                for server_name, server_conf in servers.items():
                    dump_data[group_id][server_name] = server_conf.model_dump()

            with open(self.data_path, 'w', encoding='utf-8') as f:
                json.dump(dump_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f'保存数据失败: {e}')
    
    def append_server(self, name: str):
        """
        自动添加服务器
        如果服务器在任何群组中都不存在，则添加到默认群组
        """
        # 1. 检查是否存在
        exists = False
        for servers in config.group_servers.values():
            if name in servers:
                exists = True
                break
        
        if exists:
            return

        # 2. 决定添加到哪个群组：用 group_servers 里已有的第一个群，没有则跳过
        if not config.group_servers:
            logger.warning("未配置任何群组，无法自动添加新服务器，请先在 Server.json 中配置群组")
            return
        target_group = next(iter(config.group_servers))
        logger.info(f"发现新服务器 [{name}]，自动添加到群组 [{target_group}]")
        config.group_servers[target_group][name] = ServerDetailConfig()
        
        # 4. 保存
        self.save()
    
    @property
    def servers(self) -> List[str]:
        """获取所有服务器列表（扁平化，用于兼容旧接口）"""
        all_servers = set()
        for servers in config.group_servers.values():
            all_servers.update(servers.keys())
        return list(all_servers)


data_manager = DataManager()
