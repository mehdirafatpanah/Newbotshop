# -*- coding: utf-8 -*-
"""
توابع مشترک بین هندلر ادمین و هندلر کاربر برای «تحویل سفارش» (چه با تایید دستی
ادمین، چه به‌صورت خودکار وقتی کل مبلغ از کیف پول پوشش داده می‌شود) و ساخت QR کد
برای لینک کانفیگ/ساب، تا لینک بدون بازنویسی منطق در دو جا تکراری نشود.
"""

import html
import io
import random
import string

from aiogram import Bot
from aiogram.types import BufferedInputFile

import database as db


def generate_unique_discount_code(prefix: str) -> str:
    """یه کد تخفیف رندوم و تکراری‌نشده (با یه پیشوند مشخص) می‌سازد."""
    while True:
        suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        code = f"{prefix}{suffix}"
        if not db.get_discount_code(code):
            return code


def generate_qr_png(data: str) -> bytes:
    """تصویر QR کد را به‌صورت بایت PNG برمی‌گرداند. اگر پکیج qrcode نصب نباشد،
    استثنا می‌دهد تا فراخوان بتواند به ارسال متنی برگردد (fallback)."""
    import qrcode  # وارد کردن تنبل تا اگر نصب نشده، فقط QR کار نکند نه کل بات

    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def send_config_delivery(bot: Bot, chat_id: int, product_name: str, link: str, header: str = "✅ خرید شما تایید شد!"):
    """کانفیگ/لینک ساب را به‌صورت جذاب (عکس QR + کپشن با متن قابل کپی) برای
    خریدار ارسال می‌کند. اگر ساخت QR به هر دلیلی شکست بخورد، همان پیام متنی
    قبلی به‌عنوان fallback ارسال می‌شود تا هیچ‌وقت خریدار بدون کانفیگ نماند."""
    caption = (
        f"{header}\n"
        f"📦 محصول: {html.escape(product_name)}\n\n"
        f"🔗 لینک اتصال شما:\n<code>{html.escape(link)}</code>\n\n"
        "📱 برای اتصال سریع، فقط کافیه توی اپلیکیشن کلاینتت (v2rayNG، Streisand، "
        "Shadowrocket، Hiddify و مشابه) گزینه‌ی «اسکن QR» یا «Scan QR code» رو بزنی "
        "و همین تصویر رو اسکن کنی — نیازی به کپی دستی لینک نیست.\n"
        "اگه هم دوست داشتی خودِ لینک رو کپی و Import کنی، همون متن بالا رو نگه دار."
    )
    try:
        qr_bytes = generate_qr_png(link)
        photo = BufferedInputFile(qr_bytes, filename="config-qr.png")
        await bot.send_photo(chat_id, photo, caption=caption)
    except Exception:
        # اگه qrcode نصب نبود یا هر خطای دیگه‌ای پیش اومد، حداقل خودِ لینک رو متنی بفرست
        await bot.send_message(chat_id, caption)


async def deliver_order(bot: Bot, order_id: int) -> bool:
    """کانفیگ را از مخزن به سفارش اختصاص می‌دهد، سفارش را تایید می‌کند، پورسانت
    زیرمجموعه‌گیری (در صورت وجود) را واریز و کانفیگ را برای خریدار ارسال می‌کند.
    در صورت موفقیت True و در صورت نبود موجودی False برمی‌گرداند."""
    order = db.get_order(order_id)
    if not order or order["status"] != "pending":
        return False

    product = db.get_product(order["product_id"])
    result = db.take_unused_config(order["product_id"], order["user_id"])
    if not result:
        return False

    db.approve_order(order_id, result["id"])

    reward_info = db.reward_referrer_if_first_purchase(order["user_id"], order["final_price"] or product["price"])
    if reward_info:
        reward_amount, referrer_id = reward_info
        try:
            await bot.send_message(
                referrer_id,
                f"🤝 تبریک! یکی از زیرمجموعه‌های شما اولین خرید خود را انجام داد.\n"
                f"💰 {reward_amount:,} تومان به کیف پول شما اضافه شد.",
            )
        except Exception:
            pass

    try:
        await send_config_delivery(bot, order["user_id"], product["name"], result["link"])
    except Exception:
        pass

    return True
