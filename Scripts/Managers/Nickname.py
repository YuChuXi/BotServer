"""
称呼管理器 - 管理(QQ号, 群号) -> 称呼的映射缓存，含按 bot 的缓存更新任务
"""
import asyncio
import json
from pathlib import Path
from typing import Optional, Dict
from pydantic import BaseModel, ValidationError
from nonebot import get_bot, get_bots
from nonebot.log import logger
from nonebot.exception import ActionFailed, NetworkError


class NicknameData(BaseModel):
    """称呼数据模型"""
    # 键格式: "qq:group" -> 称呼
    nicknames: Dict[str, str] = {}


class NicknameManager:
    """称呼管理器"""

    _cache_tasks: Dict[str, asyncio.Task] = {}

    def __init__(self):
        self.data_path = Path('./Data/Nickname.json')
        self.data: NicknameData = NicknameData()
        self._load()

    @staticmethod
    def _get_groups() -> list[int]:
        """从 config.group_servers 读取当前需要更新称呼的群（每次调用取最新）"""
        from Scripts.Config import config
        groups = [int(g) for g in config.group_servers]
        if config.sync_qq_group and config.sync_qq_group not in groups:
            groups.append(config.sync_qq_group)
        return groups
    
    def _get_key(self, qq: str, group: str) -> str:
        """生成缓存键"""
        return f"{qq}:{group}"
    
    def _load(self):
        """加载数据"""
        if not self.data_path.exists():
            self.data = NicknameData()
            return
        
        try:
            with open(self.data_path, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)
                self.data = NicknameData(**raw_data)
        except (json.JSONDecodeError, ValidationError, OSError) as e:
            logger.error(f'加载称呼数据失败: {e}')
            self.data = NicknameData()
    
    def save(self):
        """保存数据"""
        try:
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.data_path, 'w', encoding='utf-8') as f:
                json.dump(self.data.model_dump(), f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error(f'保存称呼数据失败: {e}')
    
    async def get_nickname(self, qq: str, group: str) -> Optional[str]:
        """获取称呼
        返回 (QQ号, 群号) 对应的称呼，如果不存在则请求QQ API更新
        """
        key = self._get_key(qq, group)
        print(key, key in self.data.nicknames.keys())
        return self.data.nicknames.get(key, qq)

    
    def _parse_member_data(self, member) -> tuple[str, str, str]:
        """解析成员数据，返回 (qq, card, nickname)"""
        if isinstance(member, dict):
            qq = str(member.get('user_id', ''))
            card = member.get('card', '').strip()
            nickname = member.get('nickname', '').strip()
        else:
            qq = str(getattr(member, 'user_id', ''))
            card = getattr(member, 'card', '').strip() if hasattr(member, 'card') else ''
            nickname = getattr(member, 'nickname', '').strip() if hasattr(member, 'nickname') else ''
        return qq, card, nickname
    
    def _extract_member_list(self, result) -> list:
        """从API返回结果中提取成员列表"""
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            if 'data' in result:
                return result['data'] if isinstance(result['data'], list) else []
            return list(result.values()) if result else []
        return []
    
    async def update_from_upstream(self, group_ids: list[int], self_id: Optional[str] = None):
        """从上游（QQ API）更新称呼缓存。self_id 指定用哪个 bot，多 bot 时必传。"""
        bots = get_bots()
        bot = bots.get(str(self_id)) if self_id else (get_bot() if bots else None)
        if not bot:
            return
        for group_id in group_ids:
            result = await bot.get_group_member_list(group_id=group_id)
            member_list = self._extract_member_list(result)
            
            for member in member_list:
                qq, card, nickname = self._parse_member_data(member)
                if not qq:
                    continue
                
                display_name = card or nickname
                if not display_name:
                    continue
                
                self.data.nicknames[self._get_key(qq, str(group_id))] = display_name
        
            logger.debug(f'更新群 {group_id} 的称呼缓存，共 {len(member_list)} 个成员')

    async def start_cache_task(self, bot) -> None:
        """为当前 bot 启动称呼缓存更新任务（每轮从 config 取 groups，重连会先停旧任务）"""
        self_id = str(bot.self_id)
        if self_id in self._cache_tasks and not self._cache_tasks[self_id].done():
            self._cache_tasks[self_id].cancel()
            try:
                await self._cache_tasks[self_id]
            except asyncio.CancelledError:
                pass
            del self._cache_tasks[self_id]
        groups = self._get_groups()
        if not groups:
            logger.warning('没有配置需要更新称呼的群')
            return

        async def _loop():
            logger.info(f'称呼缓存更新任务已启动 (bot={self_id})')
            while True:
                try:
                    await self.update_from_upstream(self._get_groups(), self_id=self_id)
                except asyncio.CancelledError:
                    logger.info(f'称呼缓存更新任务已停止 (bot={self_id})')
                    raise
                except Exception as e:
                    logger.error(f'称呼缓存更新任务出错: {e}')
                await asyncio.sleep(300)

        self._cache_tasks[self_id] = asyncio.create_task(_loop())

    async def stop_cache_task(self, bot) -> None:
        """停止该 bot 的称呼缓存更新任务"""
        self_id = str(bot.self_id)
        task = self._cache_tasks.pop(self_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


nickname_manager = NicknameManager()

