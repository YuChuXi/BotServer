"""
群组配置管理器
"""
import json
from pathlib import Path
from typing import Dict
from nonebot.log import logger

from ..Config import config, GroupConfig


class GroupManager:
    def __init__(self):
        self.data_path = Path('./Data/Group.json')
        self._load()

    def _load(self):
        if not self.data_path.exists():
            config.group_configs.clear()
            return
        try:
            with open(self.data_path, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)
            config.group_configs.clear()
            for group_id, group_conf in raw_data.items():
                if isinstance(group_conf, dict):
                    config.group_configs[group_id] = GroupConfig(**group_conf)
                else:
                    config.group_configs[group_id] = group_conf
        except Exception as e:
            logger.error(f'加载群组配置失败: {e}')
            config.group_configs.clear()

    def load(self):
        self._load()

    def save(self):
        try:
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            dump_data: Dict[str, dict] = {}
            for group_id, group_conf in config.group_configs.items():
                dump_data[group_id] = group_conf.model_dump()
            with open(self.data_path, 'w', encoding='utf-8') as f:
                json.dump(dump_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f'保存群组配置失败: {e}')


group_manager = GroupManager()
