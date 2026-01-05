"""
数据管理器
"""
from pathlib import Path
from typing import List
from pydantic import BaseModel
from nonebot.log import logger


class ServerData(BaseModel):
    """服务器数据模型"""
    servers: List[str] = []


class DataManager:
    def __init__(self):
        self.data_path = Path('./Data/Server.json')
        self.data: ServerData = ServerData()
        self._load()
    
    def _load(self):
        """加载数据"""
        if self.data_path.exists():
            try:
                import json
                with open(self.data_path, 'r', encoding='utf-8') as f:
                    raw_data = json.load(f)
                    self.data = ServerData(**raw_data)
            except Exception as e:
                logger.error(f'加载数据失败: {e}')
                self.data = ServerData()
        else:
            self.data = ServerData()
    
    def load(self):
        """公开的加载方法"""
        self._load()
    
    def save(self):
        """保存数据"""
        try:
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            import json
            with open(self.data_path, 'w', encoding='utf-8') as f:
                json.dump(self.data.model_dump(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f'保存数据失败: {e}')
    
    def append_server(self, name: str):
        """添加服务器"""
        if name not in self.data.servers:
            self.data.servers.append(name)
            self.save()
    
    @property
    def servers(self) -> List[str]:
        """获取服务器列表"""
        return self.data.servers


data_manager = DataManager()

