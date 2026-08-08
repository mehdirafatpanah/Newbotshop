# -*- coding: utf-8 -*-
"""
نقطه ورود بات - اجرا با: python main.py

این فایل، بات اصلی فروشگاه را همراه با بات‌های اختصاصی نمایندگانی که مالک
تایید کرده اجرا می‌کند (هر نماینده با توکن بات تلگرام خودش، هم‌زمان و روی
همین سرور). همه‌ی بات‌ها روی یک Dispatcher/Router مشترک پولینگ می‌شوند
(روش رسمی aiogram برای اجرای چند بات هم‌زمان)، و یک middleware بر اساس
اینکه هر آپدیت از کدام بات (توکن) رسیده، داده‌ی مخصوص همان نماینده
(fixed_reseller_id / is_agent_bot) را به هندلرها تزریق می‌کند.

هر ۲۰ ثانیه دیتابیس چک می‌شود: اگر لیست بات‌های فعال تغییر کرده باشد
(نماینده‌ی جدید تایید شده یا یکی غیرفعال/حذف شده)، پولینگ با لیست جدید
بات‌ها ری‌استارت می‌شود؛ نیازی به ری‌استارت دستی کل سرویس نیست.
"""

import asyncio
import logging
import html
from datetime import datetime, timedelta
from typing import Optional, Dict

from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
import database as db
import handlers_user
import handlers_admin
import order_utils

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot_manager")

CHECK_INTERVAL_SECONDS = 20
EXPIRY_CHECK_INTERVAL_SECONDS = 3600  # هر یک ساعت چک برای یادآوری اتمام سرویس

# نگاشت توکن -> اطلاعات نماینده‌ی صاحب آن بات (برای بات اصلی مقدار None/False است)
BOT_CONTEXT: Dict[str, dict] = {}


class BotContextMiddleware(BaseMiddleware):
    """بر اساس توکن باتی که آپدیت از آن رسیده، fixed_reseller_id و is_agent_bot را
    به‌صورت دیتای در دسترسِ همه‌ی هندلرها (چه پیام، چه callback) تزریق می‌کند."""

    async def __call__(self, handler, event, data):
        bot = data.get("bot")
        ctx = BOT_CONTEXT.get(bot.token, {}) if bot else {}
        data["fixed_reseller_id"] = ctx.get("fixed_reseller_id")
        data["is_agent_bot"] = ctx.get("is_agent_bot", False)
        return await handler(event, data)


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(BotContextMiddleware())
    dp.include_router(handlers_admin.router)
    dp.include_router(handlers_user.router)
    return dp


def make_bot(token: str) -> Bot:
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def _bot_for_reseller(bots: Dict[str, Bot], reseller_id: Optional[int]) -> Bot:
    """بات مناسب برای پیام‌دادن به مشتریِ یک محصول را برمی‌گرداند: اگر آن نماینده
    بات اختصاصی فعال داشته باشد همان، وگرنه بات اصلی (چون آن مشتری از طریق بات
    اصلی خرید کرده، حتی اگر محصول متعلق به یک نماینده‌ی بدون بات مستقل باشد)."""
    token = db.get_agent_bot_token_for_reseller(reseller_id) if reseller_id else None
    if token and token in bots:
        return bots[token]
    return bots[BOT_TOKEN]


async def expiry_reminder_loop(bots: Dict[str, Bot]):
    """هر EXPIRY_CHECK_INTERVAL_SECONDS ثانیه چک می‌کند: سفارش‌هایی که به تاریخ
    انقضاشان نزدیک شده‌اند (طبق تنظیمات ادمین) و هنوز یادآوری نگرفته‌اند را پیدا
    کرده، برای هرکدام یک کد تخفیفِ زمان‌دار می‌سازد و پیام یادآوری ارسال می‌کند."""
    while True:
        try:
            if db.get_setting("expiry_reminder_enabled", "1") == "1":
                days_before = int(db.get_setting("expiry_reminder_days_before", "5") or 5)
                discount_percent = int(db.get_setting("expiry_reminder_discount_percent", "20") or 20)
                discount_hours = int(db.get_setting("expiry_reminder_discount_hours", "24") or 24)

                due_orders = db.get_orders_due_for_expiry_reminder(days_before)
                for order in due_orders:
                    try:
                        product = db.get_product(order["product_id"])
                        if not product:
                            db.mark_expiry_reminder_sent(order["id"])
                            continue

                        expires_at = datetime.strptime(order["expires_at"], "%Y-%m-%d %H:%M:%S")
                        days_left = max((expires_at - datetime.utcnow()).days, 0)

                        code = order_utils.generate_unique_discount_code("RENEW")
                        code_expires = (datetime.utcnow() + timedelta(hours=discount_hours)).strftime("%Y-%m-%d %H:%M:%S")
                        db.create_discount_code(code, percent=discount_percent, max_uses=1, expires_at=code_expires)

                        reseller_id = db.get_product_reseller_id(order["product_id"])
                        bot = _bot_for_reseller(bots, reseller_id)

                        await bot.send_message(
                            order["user_id"],
                            f"⏰ سرویس «{html.escape(product['name'])}» شما تا {days_left} روز دیگر تمام می‌شود!\n\n"
                            f"🎁 اگر همین امروز تمدید کنید، این کد تخفیف {discount_percent}٪ به شما تعلق می‌گیرد:\n"
                            f"<code>{code}</code>\n\n"
                            f"⏳ این کد فقط تا {discount_hours} ساعت دیگر معتبر است، پس دست نگه ندارید!\n"
                            "برای تمدید، از منوی «🛒 خرید کانفیگ» همین محصول را دوباره انتخاب و کد را وارد کنید.",
                        )
                        db.mark_expiry_reminder_sent(order["id"])
                    except Exception as exc:
                        logger.error("خطا در ارسال یادآوری برای سفارش #%s: %s", order["id"], exc)
        except Exception as exc:
            logger.error("خطا در حلقه‌ی یادآوری اتمام سرویس: %s", exc)

        await asyncio.sleep(EXPIRY_CHECK_INTERVAL_SECONDS)


async def bot_manager():
    db.init_db()
    dp = build_dispatcher()

    BOT_CONTEXT[BOT_TOKEN] = {"fixed_reseller_id": None, "is_agent_bot": False}
    bots: Dict[str, Bot] = {BOT_TOKEN: make_bot(BOT_TOKEN)}

    polling_task: Optional[asyncio.Task] = None

    async def start_polling_task():
        nonlocal polling_task
        bot_list = list(bots.values())
        for b in bot_list:
            try:
                await b.delete_webhook(drop_pending_updates=True)
            except Exception as exc:
                logger.error("خطا در حذف webhook یکی از بات‌ها: %s", exc)
        logger.info("شروع پولینگ برای %d بات (اصلی + نمایندگان)", len(bot_list))
        polling_task = asyncio.create_task(dp.start_polling(*bot_list))

    async def restart_polling():
        nonlocal polling_task
        if polling_task and not polling_task.done():
            await dp.stop_polling()
            try:
                await polling_task
            except Exception:
                pass
        await start_polling_task()

    await start_polling_task()
    reminder_task = asyncio.create_task(expiry_reminder_loop(bots))

    try:
        while True:
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            try:
                active_bots = db.list_active_agent_bots()
                desired_tokens = {BOT_TOKEN}
                changed = False

                for b in active_bots:
                    token = b["bot_token"]
                    desired_tokens.add(token)
                    if token not in bots:
                        bots[token] = make_bot(token)
                        BOT_CONTEXT[token] = {"fixed_reseller_id": b["admin_id"], "is_agent_bot": True}
                        changed = True
                    else:
                        # آیدی ادمین ممکنه بدون نیاز به ری‌استارت پولینگ به‌روزرسانی بشه
                        BOT_CONTEXT[token] = {"fixed_reseller_id": b["admin_id"], "is_agent_bot": True}

                # توقف/حذف بات‌هایی که دیگر تایید/فعال نیستند
                for token in list(bots.keys()):
                    if token != BOT_TOKEN and token not in desired_tokens:
                        try:
                            await bots[token].session.close()
                        except Exception:
                            pass
                        del bots[token]
                        BOT_CONTEXT.pop(token, None)
                        changed = True

                if changed:
                    await restart_polling()
            except Exception as exc:
                logger.error("خطا در بررسی دوره‌ای بات‌های نمایندگی: %s", exc)
    finally:
        reminder_task.cancel()
        try:
            await reminder_task
        except Exception:
            pass
        if polling_task and not polling_task.done():
            await dp.stop_polling()
            try:
                await polling_task
            except Exception:
                pass
        for b in bots.values():
            try:
                await b.session.close()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(bot_manager())
    except KeyboardInterrupt:
        print("\nبات با Ctrl+C متوقف شد.")
