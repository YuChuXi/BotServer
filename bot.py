from pathlib import Path

import nonebot
from nonebot.adapters.onebot.v11 import Adapter
from nonebot.log import logger

nonebot.init()

nonebot.load_plugins('Plugins')
app = nonebot.get_asgi()
driver = nonebot.get_driver()
driver.register_adapter(Adapter)


def main():
    log_path = Path('./Logs/')
    if not log_path.exists():
        log_path.mkdir()
    logger.add((log_path / '{time}.log'), rotation='1 day')

    nonebot.run(app="__mp_main__:app", )


@driver.on_startup
async def startup():
    from Scripts.Servers import Websocket
    from Scripts.Managers import data_manager

    data_manager.load()
    Websocket.setup_websocket_server()


@driver.on_bot_connect
async def on_bot_connect():
    """Bot连接时启动称呼缓存更新任务"""
    import asyncio
    from Scripts.Managers import nickname_manager
    from Scripts.Config import config

    # 合并目标群和同步群，去重
    groups = list(config.target_qq_groups)
    if config.sync_qq_group and config.sync_qq_group not in groups:
        groups.append(config.sync_qq_group)
    
    if not groups:
        logger.warning('没有配置需要更新称呼的群')
        return
    
    async def update_nickname_cache_task():
        """每5分钟从上游更新称呼缓存的后台任务"""
        logger.info('称呼缓存更新任务已启动')
        
        while True:
            try:
                await nickname_manager.update_from_upstream(groups)
            except Exception as e:
                logger.error(f'称呼缓存更新任务出错: {e}')
            
            await asyncio.sleep(300)  # 等待5分钟
    
    # 启动后台任务
    asyncio.create_task(update_nickname_cache_task())



@driver.on_shutdown
async def shutdown():
    from Scripts.Managers import data_manager

    data_manager.save()


if __name__ == '__main__':
    main()
