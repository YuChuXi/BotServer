"""
主机资源监控插件：Driver 启动后常驻后台轮询；有在线 Bot 且开启插件时才采样；超阈值则每轮私聊告警。
"""
import asyncio
import os
import traceback
from contextlib import suppress
from typing import Optional

import psutil
from nonebot import get_driver, get_bots, get_plugin_config
from nonebot.log import logger
from pydantic import BaseModel, ConfigDict, Field

from Scripts.Config import config


class ResourceMonitorPluginConfig(BaseModel):
    """本插件专用配置，与全局 Scripts.Config 分离；环境变量名见各字段 alias。"""

    model_config = ConfigDict(populate_by_name=True)

    enabled: bool = Field(default=True, alias='RESOURCE_MONITOR_ENABLED')
    interval_seconds: int = Field(default=300, alias='RESOURCE_MONITOR_INTERVAL_SECONDS')
    alert_cpu_percent: float = Field(default=90.0, alias='RESOURCE_ALERT_CPU_PERCENT')
    alert_memory_percent: float = Field(default=90.0, alias='RESOURCE_ALERT_MEMORY_PERCENT')
    alert_disk_percent: float = Field(default=90.0, alias='RESOURCE_ALERT_DISK_PERCENT')
    # 与 HOST_ADMINS 相同：.env 里写 JSON 数组，例如 ["/","/home"]；空列表则监控默认根分区或系统盘
    disk_paths: list[str] = Field(default_factory=list, alias='RESOURCE_MONITOR_DISK_PATH')


plugin_config = get_plugin_config(ResourceMonitorPluginConfig)


def _resolved_disk_paths() -> list[str]:
    items = [p.strip() for p in plugin_config.disk_paths if isinstance(p, str) and p.strip()]
    if items:
        return items
    if os.name == 'nt':
        return [os.environ.get('SystemDrive', 'C:') + '\\']
    return ['/']


class ResourceMonitorManager:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._start_lock: Optional[asyncio.Lock] = None

    def _ensure_start_lock(self) -> asyncio.Lock:
        if self._start_lock is None:
            self._start_lock = asyncio.Lock()
        return self._start_lock

    async def start_background_loop(self) -> None:
        async with self._ensure_start_lock():
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run_loop())
                logger.info('主机资源监控后台任务已启动')

    async def stop_background_loop(self) -> None:
        t = self._task
        self._task = None
        if t:
            if not t.done():
                t.cancel()
            await asyncio.gather(t, return_exceptions=True)
        logger.info('主机资源监控任务已停止')

    @staticmethod
    async def _sample_cpu_percent() -> float:
        def read() -> float:
            return float(psutil.cpu_percent(interval=0.2))

        return await asyncio.to_thread(read)

    def _disk_percent(self, path: str) -> Optional[float]:
        with suppress(OSError):
            return float(psutil.disk_usage(path).percent)
        logger.warning(f'资源监控无法读取磁盘使用率 path={path}')
        return None

    async def _notify(self, lines: list[str]) -> None:
        if not config.host_admins:
            logger.warning('资源监控触发告警但未配置主机管理员，无法发送私聊')
            return
        bots = get_bots()
        if not bots:
            logger.warning('资源监控触发告警但当前无在线 Bot，无法发送私聊')
            return
        text = '【主机资源预警】\n' + '\n'.join(lines)
        bot_list = list(bots.values())
        for uid in config.host_admins:
            cors = [b.send_private_msg(user_id=int(uid), message=text) for b in bot_list]
            outcomes = await asyncio.gather(*cors, return_exceptions=True)
            if any(not isinstance(r, BaseException) for r in outcomes):
                continue
            for b, r in zip(bot_list, outcomes):
                if isinstance(r, BaseException):
                    logger.warning(
                        f'资源监控私聊失败 bot={getattr(b, "self_id", "?")} user_id={uid}: {r}'
                    )

    async def _tick(self) -> None:
        if not plugin_config.enabled or not get_bots():
            return

        cpu = await self._sample_cpu_percent()
        mem = float(psutil.virtual_memory().percent)

        cpu_bad = cpu >= plugin_config.alert_cpu_percent
        mem_bad = mem >= plugin_config.alert_memory_percent

        new_lines: list[str] = []
        if cpu_bad:
            new_lines.append(
                f'CPU 使用率 {cpu:.1f}%（阈值 {plugin_config.alert_cpu_percent:g}%）'
            )
        if mem_bad:
            new_lines.append(
                f'内存使用率 {mem:.1f}%（阈值 {plugin_config.alert_memory_percent:g}%）'
            )

        for dpath in _resolved_disk_paths():
            disk = self._disk_percent(dpath)
            if disk is None:
                continue
            if disk >= plugin_config.alert_disk_percent:
                new_lines.append(
                    f'磁盘 [{dpath}] 使用率 {disk:.1f}%（阈值 {plugin_config.alert_disk_percent:g}%）'
                )

        if new_lines:
            await self._notify(new_lines)

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception:
                traceback.print_exc()
                logger.exception('资源监控 _tick 异常')
            await asyncio.sleep(max(30, int(plugin_config.interval_seconds)))


resource_monitor = ResourceMonitorManager()

_driver = get_driver()


@_driver.on_startup
async def _plugin_resource_monitor_on_startup():
    await resource_monitor.start_background_loop()


@_driver.on_shutdown
async def _plugin_resource_monitor_on_shutdown():
    await resource_monitor.stop_background_loop()
