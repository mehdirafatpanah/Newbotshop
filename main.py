# -*- coding: utf-8 -*-
"""
نقطه ورود - اجرا با: python main.py

بات اصلی + بات‌های نمایندگی + Telegram Mini App API (در صورت فعال بودن)
"""
import asyncio
import logging
import os

from config import BOT_TOKEN, OWNER_ID, DB_PATH
from database import Database
from bot_manager import BotManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def miniapp_enabled() -> bool:
    return os.getenv("MINIAPP_ENABLED", "0").strip() == "1"


async def run_webapp():
    import uvicorn

    config = uvicorn.Config(
        "webapp_server:app",
        host=os.getenv("WEBAPP_HOST", "127.0.0.1"),
        port=int(os.getenv("WEBAPP_PORT", "8080")),
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def configure_miniapp_menu():
    """Configure the main bot's Telegram menu button when Mini App is enabled."""
    from aiogram import Bot
    from aiogram.types import MenuButtonDefault, MenuButtonWebApp, WebAppInfo

    bot = Bot(BOT_TOKEN)
    try:
        if miniapp_enabled():
            url = os.getenv("WEBAPP_URL", "").strip()
            if not url:
                logger.warning("Mini App enabled but WEBAPP_URL is empty.")
                return
            if not url.startswith("https://"):
                raise RuntimeError("WEBAPP_URL must use HTTPS.")
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="🛒 فروشگاه",
                    web_app=WebAppInfo(url=url),
                )
            )
            logger.info("Mini App menu button configured: %s", url)
        else:
            # Restore Telegram's normal menu button when disabled.
            await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
    finally:
        await bot.session.close()


async def main():
    manager = BotManager()
    web_task = None

    if miniapp_enabled():
        web_task = asyncio.create_task(run_webapp())
        logger.info(
            "Mini App API starting on %s:%s",
            os.getenv("WEBAPP_HOST", "127.0.0.1"),
            os.getenv("WEBAPP_PORT", "8080"),
        )

    try:
        await configure_miniapp_menu()

        # ۱. بات اصلی
        await manager.start_bot(BOT_TOKEN, DB_PATH, OWNER_ID, is_main_bot=True)
        logger.info("بات اصلی راه‌اندازی شد.")

        # ۲. تمام بات‌های نمایندگی فعال
        main_db = Database(DB_PATH)
        reseller_bots = main_db.list_reseller_bots(active_only=True)
        for rb in reseller_bots:
            started = await manager.start_bot(
                rb["bot_token"],
                rb["db_path"],
                rb["owner_telegram_id"],
                is_main_bot=False,
            )
            if started:
                logger.info("بات نمایندگی @%s راه‌اندازی شد.", rb["bot_username"])

        await manager.wait_all()
    finally:
        await manager.stop_all()
        if web_task:
            web_task.cancel()
            try:
                await web_task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nبرنامه با Ctrl+C متوقف شد.")
