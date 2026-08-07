# -*- coding: utf-8 -*-
"""
نقطه ورود بات - اجرا با: python main.py

این فایل، بات اصلی فروشگاه را همراه با بات‌های اختصاصی نمایندگانی که مالک
تایید کرده اجرا می‌کند (هر نماینده با توکن بات تلگرام خودش، هم‌زمان و روی
همین سرور). به‌صورت دوره‌ای دیتابیس را چک می‌کند: نمایندهٔ تازه‌تاییدشده را
به‌صورت خودکار استارت می‌کند و نمایندهٔ غیرفعال/حذف‌شده را متوقف می‌کند،
بدون نیاز به ری‌استارت دستی کل سرویس.
"""

import asyncio
import logging
from typing import Optional, Dict

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
import database as db
import handlers_user
import handlers_admin

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot_manager")

# فاصله (ثانیه) بین هر بار بررسیِ دیتابیس برای بات‌های نمایندگی تازه‌تاییدشده/غیرفعال‌شده
CHECK_INTERVAL_SECONDS = 20


def build_dispatcher() -> Dispatcher:
    """یک Dispatcher مشترک می‌سازد که همه‌ی بات‌ها (اصلی + نمایندگان) از آن استفاده
    می‌کنند؛ چون هر Router فقط یک‌بار مجاز است به یک Dispatcher وصل شود، این تابع
    فقط یک‌بار در کل برنامه فراخوانی می‌شود. اطلاعات مخصوص هر بات (fixed_reseller_id،
    is_agent_bot) به‌جای workflow_data ثابت، از طریق میان‌افزار زیر و بر اساس شناسه‌ی
    همان بات که آپدیت را دریافت کرده تزریق می‌شود."""
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(handlers_admin.router)
    dp.include_router(handlers_user.router)

    @dp.update.outer_middleware()
    async def inject_agent_context(handler, event, data):
        bot: Bot = data["bot"]
        ctx = BOT_CONTEXT.get(bot.id, {})
        data["fixed_reseller_id"] = ctx.get("fixed_reseller_id")
        data["is_agent_bot"] = ctx.get("is_agent_bot", False)
        return await handler(event, data)

    return dp


# شناسه‌ی هر بات (bot.id) → اطلاعات مخصوص همان بات؛ چون Dispatcher مشترک است،
# این دیکشنری جایگزینِ workflow_data ثابت قبلی شده است.
BOT_CONTEXT: Dict[int, dict] = {}
DISPATCHER = build_dispatcher()


async def run_bot(token: str, fixed_reseller_id: Optional[int], is_agent_bot: bool, label: str):
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    BOT_CONTEXT[bot.id] = {"fixed_reseller_id": fixed_reseller_id, "is_agent_bot": is_agent_bot}
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("در حال اجرا: %s", label)
        await DISPATCHER.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("متوقف شد: %s", label)
        raise
    except Exception as exc:
        logger.error("خطا در اجرای %s: %s", label, exc)
    finally:
        BOT_CONTEXT.pop(bot.id, None)
        await bot.session.close()


async def bot_manager():
    db.init_db()

    # کلید دیکشنری = توکن بات؛ مقدار = asyncio.Task در حال اجرای آن بات
    running_tasks: Dict[str, asyncio.Task] = {
        BOT_TOKEN: asyncio.create_task(
            run_bot(BOT_TOKEN, fixed_reseller_id=None, is_agent_bot=False, label="بات اصلی")
        )
    }

    try:
        while True:
            try:
                active_bots = db.list_active_agent_bots()
                active_tokens = {b["bot_token"] for b in active_bots}

                # ۱) استارت بات‌های نمایندگانی که تازه تایید/فعال شده‌اند
                for b in active_bots:
                    token = b["bot_token"]
                    task = running_tasks.get(token)
                    if task is None or task.done():
                        running_tasks[token] = asyncio.create_task(
                            run_bot(
                                token,
                                fixed_reseller_id=b["admin_id"],
                                is_agent_bot=True,
                                label=f"بات نماینده #{b['id']} (@{b['bot_username']})",
                            )
                        )

                # ۲) توقف بات‌هایی که غیرفعال یا حذف شده‌اند
                for token in list(running_tasks.keys()):
                    if token != BOT_TOKEN and token not in active_tokens:
                        running_tasks[token].cancel()
                        del running_tasks[token]
            except Exception as exc:
                logger.error("خطا در بررسی دوره‌ای بات‌های نمایندگی: %s", exc)

            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
    finally:
        for task in running_tasks.values():
            task.cancel()
        await asyncio.gather(*running_tasks.values(), return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(bot_manager())
    except KeyboardInterrupt:
        print("\nبات با Ctrl+C متوقف شد.")
