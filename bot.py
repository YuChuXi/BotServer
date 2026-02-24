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
async def on_bot_connect(bot):
    from Scripts.Managers import nickname_manager
    await nickname_manager.start_cache_task(bot)


@driver.on_bot_disconnect
async def on_bot_disconnect(bot):
    from Scripts.Managers import nickname_manager
    await nickname_manager.stop_cache_task(bot)


@driver.on_shutdown
async def shutdown():
    from Scripts.Managers import data_manager
    data_manager.save()


if __name__ == '__main__':
    main()
