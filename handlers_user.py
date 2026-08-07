# -*- coding: utf-8 -*-
"""
هندلرهای مربوط به کاربر عادی
"""

import html
import random
import string
from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

import database as db
import keyboards as kb
from states import BuyFlow, ContactFlow, DiscountEntry, WalletTopup, AgentBotRequest
from config import MAX_TEST_PER_USER

router = Router()


# ---------------------------------------------------------------------------
# شروع
# ---------------------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, fixed_reseller_id: int = None, is_agent_bot: bool = False):
    await state.clear()
    db.add_or_update_user(
        message.from_user.id, message.from_user.username or "", message.from_user.first_name or ""
    )

    shop_notice = ""
    # داخل بات اختصاصی یک نماینده، همیشه فقط فروشگاه خودِ همان نماینده نمایش داده می‌شود
    # و نیازی به پردازش لینک‌های دعوت/فروشگاه بات اصلی نیست.
    if not is_agent_bot:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) > 1:
            payload = parts[1]
            # لینک دعوت (زیرمجموعه‌گیری): /start ref123456789
            if payload.startswith("ref"):
                ref_part = payload[3:]
                if ref_part.isdigit():
                    db.set_referred_by(message.from_user.id, int(ref_part))
            # لینک فروشگاه یک نماینده: /start agent123456789
            elif payload.startswith("agent"):
                agent_part = payload[5:]
                if agent_part.isdigit():
                    agent_id = int(agent_part)
                    reseller = db.get_reseller(agent_id)
                    if reseller and reseller["is_active"]:
                        db.set_active_reseller(message.from_user.id, agent_id)
                        shop_notice = f"\n\n🏪 شما وارد فروشگاه «{html.escape(reseller['name'])}» شدید."

    welcome = db.get_setting("welcome_text")
    await message.answer(
        welcome + shop_notice,
        reply_markup=kb.menu_for_user(message.from_user.id, is_agent_bot=is_agent_bot),
    )


def _is_button(message: Message, key: str) -> bool:
    return message.text == db.get_setting(key)


# ---------------------------------------------------------------------------
# خرید کانفیگ
# ---------------------------------------------------------------------------

@router.message(F.text.func(lambda t: t == db.get_setting("btn_buy")))
async def show_categories(message: Message, state: FSMContext, fixed_reseller_id: int = None):
    await state.clear()
    active_reseller = fixed_reseller_id if fixed_reseller_id is not None else db.get_active_reseller(message.from_user.id)
    categories = db.get_categories(reseller_id=active_reseller, active_only=True)
    if not categories:
        await message.answer("در حال حاضر دسته‌بندی فعالی وجود ندارد.")
        return
    await message.answer("یک دسته‌بندی را انتخاب کنید:", reply_markup=kb.categories_kb(categories))


@router.callback_query(F.data == "back_main")
async def cb_back_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.delete()
    await call.answer()


@router.callback_query(F.data == "back_categories")
async def cb_back_categories(call: CallbackQuery, fixed_reseller_id: int = None):
    active_reseller = fixed_reseller_id if fixed_reseller_id is not None else db.get_active_reseller(call.from_user.id)
    categories = db.get_categories(reseller_id=active_reseller, active_only=True)
    await call.message.edit_text("یک دسته‌بندی را انتخاب کنید:", reply_markup=kb.categories_kb(categories))
    await call.answer()


@router.callback_query(F.data.startswith("cat:"))
async def cb_category(call: CallbackQuery):
    cat_id = int(call.data.split(":")[1])
    products = db.get_products(cat_id, active_only=True)
    if not products:
        await call.answer("محصولی در این دسته‌بندی موجود نیست.", show_alert=True)
        return
    await call.message.edit_text("یک محصول را انتخاب کنید:", reply_markup=kb.products_kb(products, cat_id))
    await call.answer()


@router.callback_query(F.data.startswith("prod:"))
async def cb_product(call: CallbackQuery):
    product_id = int(call.data.split(":")[1])
    product = db.get_product(product_id)
    if not product:
        await call.answer("محصول یافت نشد.", show_alert=True)
        return
    stock = db.count_available_configs(product_id)
    wallet_credit = db.get_wallet_credit(call.from_user.id)
    text = (
        f"📦 {html.escape(product['name'])}\n"
        f"💰 قیمت: {product['price']:,} تومان\n"
        f"📝 توضیحات: {html.escape(product['description']) if product['description'] else '---'}\n"
        f"📊 موجودی: {stock} عدد\n"
    )
    if wallet_credit > 0:
        text += f"\n👛 موجودی کیف پول شما: {wallet_credit:,} تومان (به‌صورت خودکار در پرداخت اعمال می‌شود)\n"
    if stock <= 0:
        text += "\n⛔️ در حال حاضر موجودی این محصول تمام شده است."
        await call.message.edit_text(text)
        await call.answer()
        return
    await call.message.edit_text(text, reply_markup=kb.product_confirm_kb(product_id))
    await call.answer()


@router.callback_query(F.data.startswith("enter_code:"))
async def cb_enter_code(call: CallbackQuery, state: FSMContext):
    product_id = int(call.data.split(":")[1])
    await state.update_data(discount_product_id=product_id)
    await state.set_state(DiscountEntry.waiting_code)
    await call.message.edit_text("🎟 کد تخفیف را ارسال کنید:", reply_markup=kb.cancel_kb())
    await call.answer()


@router.message(DiscountEntry.waiting_code)
async def process_discount_code(message: Message, state: FSMContext):
    data = await state.get_data()
    product_id = data.get("discount_product_id")
    product = db.get_product(product_id) if product_id else None
    if not product:
        await message.answer("محصول معتبر نیست. لطفاً دوباره از منو شروع کنید.")
        await state.clear()
        return

    code_row = db.get_discount_code(message.text.strip())
    if not db.is_discount_code_valid(code_row):
        await message.answer(
            "❌ این کد تخفیف نامعتبر، غیرفعال یا به سقف استفاده رسیده است. دوباره تلاش کنید یا بدون کد ادامه دهید.",
            reply_markup=kb.cancel_kb(),
        )
        return

    discount_amount = db.compute_discount_amount(code_row, product["price"])
    await state.update_data(discount_code_id=code_row["id"], discount_amount=discount_amount)
    await state.set_state(None)

    stock = db.count_available_configs(product_id)
    wallet_credit = db.get_wallet_credit(message.from_user.id)
    price_after_code = product["price"] - discount_amount
    wallet_used_preview = min(wallet_credit, price_after_code)
    final_preview = price_after_code - wallet_used_preview

    text = (
        f"✅ کد تخفیف اعمال شد!\n\n"
        f"📦 {html.escape(product['name'])}\n"
        f"💰 قیمت اصلی: {product['price']:,} تومان\n"
        f"🎟 تخفیف کد: {discount_amount:,} تومان\n"
    )
    if wallet_used_preview > 0:
        text += f"👛 اعمال کیف پول: {wallet_used_preview:,} تومان\n"
    text += f"💵 مبلغ نهایی قابل پرداخت: {final_preview:,} تومان\n"
    text += f"📊 موجودی: {stock} عدد"

    await message.answer(text, reply_markup=kb.product_confirm_kb(product_id))


async def _notify_admins_of_order(bot: Bot, order_id: int, receipt_file_id: str = None):
    order = db.get_order(order_id)
    product = db.get_product(order["product_id"])
    user_row = db.get_user(order["user_id"])
    username = user_row["username"] if user_row else ""
    first_name = user_row["first_name"] if user_row else ""

    caption = (
        f"🧾 سفارش #{order_id}\n"
        f"👤 کاربر: {html.escape(first_name or '')} (@{html.escape(username or '---')})\n"
        f"🆔 آیدی عددی: <code>{order['user_id']}</code>\n"
        f"📦 محصول: {html.escape(product['name'])}\n"
        f"💰 قیمت پایه: {order['base_price']:,} تومان\n"
    )
    if order["discount_amount"]:
        caption += f"🎟 تخفیف کد: {order['discount_amount']:,} تومان\n"
    if order["wallet_used"]:
        caption += f"👛 استفاده از کیف پول: {order['wallet_used']:,} تومان\n"
    caption += f"💵 مبلغ قابل پرداخت: {order['final_price']:,} تومان"

    # مسیریابی: اگر محصول متعلق به یک نماینده باشد، رسید فقط برای خودِ همان نماینده ارسال می‌شود
    reseller_id = db.get_product_reseller_id(order["product_id"])
    targets = [reseller_id] if reseller_id else db.list_admins()

    for admin_id in targets:
        try:
            if receipt_file_id:
                sent = await bot.send_photo(
                    admin_id, receipt_file_id, caption=caption,
                    reply_markup=kb.order_review_kb(order_id),
                )
            else:
                caption += "\n\n(بدون نیاز به رسید - مبلغ کاملاً از کیف پول/تخفیف پوشش داده شده)"
                sent = await bot.send_message(
                    admin_id, caption, reply_markup=kb.order_review_kb(order_id),
                )
            db.set_order_admin_message(order_id, admin_id, sent.message_id)
        except Exception:
            pass


@router.callback_query(F.data.startswith("buy_start:"))
async def cb_buy_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    product_id = int(call.data.split(":")[1])
    product = db.get_product(product_id)
    if not product or db.count_available_configs(product_id) <= 0:
        await call.answer("این محصول در حال حاضر موجود نیست.", show_alert=True)
        return

    data = await state.get_data()
    discount_code_id = data.get("discount_code_id")
    discount_amount = data.get("discount_amount", 0) or 0

    wallet_credit = db.get_wallet_credit(call.from_user.id)
    price_after_code = max(product["price"] - discount_amount, 0)
    wallet_used = min(wallet_credit, price_after_code)

    # رزرو فوری کیف پول و مصرف کد تخفیف تا در طول بررسی رسید دوباره قابل استفاده نباشند
    if wallet_used > 0:
        db.add_wallet_credit(call.from_user.id, -wallet_used)
    if discount_code_id:
        db.increment_discount_usage(discount_code_id)

    order_id = db.create_order(
        call.from_user.id,
        product_id,
        base_price=product["price"],
        wallet_used=wallet_used,
        discount_code_id=discount_code_id,
        discount_amount=discount_amount,
    )
    order = db.get_order(order_id)
    await state.update_data(order_id=order_id)
    await state.update_data(discount_code_id=None, discount_amount=0, discount_product_id=None)

    if order["final_price"] <= 0:
        # کاملاً از کیف پول/تخفیف پوشش داده شده؛ نیازی به رسید نیست، مستقیم برای ادمین ارسال می‌شود
        await state.clear()
        await _notify_admins_of_order(bot, order_id)
        await call.message.edit_text(
            "✅ مبلغ سفارش شما به‌طور کامل از کیف پول/تخفیف پوشش داده شد.\n"
            "سفارش برای تایید نهایی ادمین ارسال شد و کانفیگ به‌زودی برایتان ارسال می‌شود."
        )
        await call.answer()
        return

    await state.set_state(BuyFlow.waiting_receipt)

    reseller_id = db.get_product_reseller_id(product_id)
    if reseller_id:
        reseller = db.get_reseller(reseller_id)
        card_number = reseller["card_number"] or "تنظیم نشده - با پشتیبانی تماس بگیرید"
        card_holder = reseller["card_holder"] or "---"
    else:
        card_number = db.get_setting("card_number")
        card_holder = db.get_setting("card_holder")
    after_buy_text = db.get_setting("after_buy_text")

    text = f"{after_buy_text}\n\n"
    text += f"💳 شماره کارت: <code>{html.escape(card_number)}</code>\n"
    text += f"👤 به نام: {html.escape(card_holder)}\n"
    if discount_amount:
        text += f"🎟 تخفیف کد: {discount_amount:,} تومان\n"
    if wallet_used:
        text += f"👛 استفاده از کیف پول: {wallet_used:,} تومان\n"
    text += f"💰 مبلغ نهایی قابل پرداخت: {order['final_price']:,} تومان\n\n"
    text += "لطفاً عکس رسید پرداخت را همینجا ارسال کنید."

    await call.message.edit_text(text, reply_markup=kb.cancel_kb())
    await call.answer()


@router.callback_query(F.data == "cancel_flow")
async def cb_cancel_flow(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    if order_id:
        order = db.get_order(order_id)
        if order and order["status"] == "pending":
            # لغو یعنی رد سفارش تا کیف پول/کد تخفیف مصرف‌شده به‌صورت خودکار برگردد
            db.reject_order(order_id)
    await state.clear()
    await call.message.edit_text("عملیات لغو شد.")
    await call.answer()


@router.message(BuyFlow.waiting_receipt, F.photo)
async def receive_receipt(message: Message, state: FSMContext, bot: Bot, is_agent_bot: bool = False):
    data = await state.get_data()
    order_id = data.get("order_id")
    order = db.get_order(order_id)
    if not order or order["status"] != "pending":
        await message.answer("سفارش معتبر یافت نشد. لطفاً دوباره از منو شروع کنید.")
        await state.clear()
        return

    file_id = message.photo[-1].file_id
    db.set_order_receipt(order_id, file_id)

    await _notify_admins_of_order(bot, order_id, receipt_file_id=file_id)

    await message.answer(
        "✅ رسید شما برای بررسی ارسال شد. پس از تایید ادمین، کانفیگ برای شما ارسال خواهد شد.",
        reply_markup=kb.menu_for_user(message.from_user.id, is_agent_bot=is_agent_bot),
    )
    await state.clear()


@router.message(BuyFlow.waiting_receipt)
async def receipt_wrong_type(message: Message):
    await message.answer("لطفاً فقط عکس رسید پرداخت را ارسال کنید.")


# ---------------------------------------------------------------------------
# کانفیگ تست
# ---------------------------------------------------------------------------

@router.message(F.text.func(lambda t: t == db.get_setting("btn_test")))
async def get_test_config(message: Message):
    if db.get_setting("test_enabled", "1") != "1":
        await message.answer("در حال حاضر امکان دریافت کانفیگ تست غیرفعال است.")
        return

    user = db.get_user(message.from_user.id)
    if user and user["test_used"] >= MAX_TEST_PER_USER:
        await message.answer("شما قبلاً کانفیگ تست خود را دریافت کرده‌اید. هر کاربر فقط یک بار مجاز به دریافت کانفیگ تست است.")
        return

    result = db.take_unused_test_config(message.from_user.id)
    if not result:
        await message.answer("متاسفانه موجودی کانفیگ تست تمام شده است. لطفاً بعداً مراجعه کنید.")
        return

    db.mark_test_used(message.from_user.id)
    await message.answer(f"🧪 کانفیگ تست شما:\n\n<code>{html.escape(result['link'])}</code>")


# ---------------------------------------------------------------------------
# گردونه شانس
# ---------------------------------------------------------------------------

def _generate_wheel_code() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"LUCK{suffix}"


@router.message(F.text.func(lambda t: t == db.get_setting("btn_wheel")))
async def spin_wheel(message: Message, is_agent_bot: bool = False):
    if is_agent_bot or db.get_setting("wheel_enabled", "0") != "1":
        return

    cooldown_hours = int(db.get_setting("wheel_cooldown_hours", "24") or 0)
    last_spin = db.get_last_wheel_spin(message.from_user.id)
    if last_spin and cooldown_hours > 0:
        last_time = datetime.strptime(last_spin["created_at"], "%Y-%m-%d %H:%M:%S")
        next_allowed = last_time + timedelta(hours=cooldown_hours)
        now = datetime.utcnow()
        if now < next_allowed:
            remaining = next_allowed - now
            hours, rem = divmod(int(remaining.total_seconds()), 3600)
            minutes = rem // 60
            await message.answer(
                f"⏳ فعلاً نوبت چرخوندن گردونه نیست. حدود {hours} ساعت و {minutes} دقیقه‌ی دیگر دوباره امتحان کن."
            )
            return

    spin_msg = await message.answer("🎡 گردونه در حال چرخیدن...")
    win_percent = int(db.get_setting("wheel_win_percent", "15") or 0)
    won = random.randint(1, 100) <= win_percent

    if not won:
        db.create_wheel_spin(message.from_user.id, won=False)
        await spin_msg.edit_text(
            "😔 این‌بار شانس باهات یار نبود!\n"
            f"دوباره بعد از {cooldown_hours} ساعت می‌تونی امتحان کنی. 🍀"
        )
        return

    discount_percent = int(db.get_setting("wheel_discount_percent", "10") or 0)
    code = _generate_wheel_code()
    while db.get_discount_code(code):
        code = _generate_wheel_code()
    code_id = db.create_discount_code(code, percent=discount_percent, max_uses=1)
    db.create_wheel_spin(message.from_user.id, won=True, discount_code_id=code_id)

    await spin_msg.edit_text(
        "🎉 تبریک! برنده شدی!\n\n"
        f"🎁 کد تخفیف {discount_percent}٪ درصدی مخصوص خودته:\n"
        f"<code>{html.escape(code)}</code>\n\n"
        "این کد فقط یک‌بار قابل استفاده‌ست. موقع خرید محصول، روی «🎟 وارد کردن کد تخفیف» بزن و واردش کن."
    )


# ---------------------------------------------------------------------------
# زیرمجموعه‌گیری (رفرال)
# ---------------------------------------------------------------------------

@router.message(F.text.func(lambda t: t == db.get_setting("btn_referral")))
async def referral_menu(message: Message, bot: Bot):
    if db.get_setting("referral_enabled", "1") != "1":
        await message.answer("در حال حاضر سیستم زیرمجموعه‌گیری غیرفعال است.")
        return

    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref{message.from_user.id}"
    stats = db.get_referral_stats(message.from_user.id)
    percent = db.get_setting("referral_percent", "10")

    text = (
        "🤝 سیستم زیرمجموعه‌گیری\n\n"
        f"لینک اختصاصی دعوت شما:\n{link}\n\n"
        f"هر کاربری که با این لینک وارد بات شود و اولین خریدش تایید شود، {percent}٪ از مبلغ پرداختی او "
        f"به‌صورت اعتبار کیف پول به شما تعلق می‌گیرد و به‌طور خودکار در خرید بعدی‌تان کسر می‌شود.\n\n"
        f"👥 تعداد زیرمجموعه‌های شما: {stats['count']}\n"
        f"👛 موجودی کیف پول شما: {stats['credit']:,} تومان"
    )
    await message.answer(text)


# ---------------------------------------------------------------------------
# کیف پول (جدا از زیرمجموعه‌گیری)
# ---------------------------------------------------------------------------

@router.message(F.text.func(lambda t: t == db.get_setting("btn_wallet")))
async def wallet_menu(message: Message):
    balance = db.get_wallet_credit(message.from_user.id)
    text = (
        "👛 کیف پول شما\n\n"
        f"موجودی فعلی: {balance:,} تومان\n\n"
        "این موجودی (چه از شارژ دستی، چه از پورسانت زیرمجموعه‌گیری) به‌صورت خودکار در خرید بعدی شما کسر می‌شود."
    )
    await message.answer(text, reply_markup=kb.wallet_menu_kb())


@router.callback_query(F.data == "start_topup")
async def cb_start_topup(call: CallbackQuery, state: FSMContext):
    await state.set_state(WalletTopup.waiting_amount)
    await call.message.edit_text(
        "💰 چه مبلغی (به تومان) می‌خواهید به کیف پول خود شارژ کنید؟ فقط عدد ارسال کنید (مثال: 100000):",
        reply_markup=kb.cancel_kb(),
    )
    await call.answer()


@router.message(WalletTopup.waiting_amount)
async def process_topup_amount(message: Message, state: FSMContext):
    text = message.text.strip().replace(",", "")
    if not text.isdigit() or int(text) < 1000:
        await message.answer("لطفاً یک عدد معتبر و حداقل 1000 تومان ارسال کنید.")
        return

    amount = int(text)
    await state.update_data(topup_amount=amount)
    await state.set_state(WalletTopup.waiting_receipt)

    card_number = db.get_setting("card_number")
    card_holder = db.get_setting("card_holder")

    text = (
        f"مبلغ {amount:,} تومان را به شماره کارت زیر واریز کرده و سپس عکس رسید را ارسال کنید:\n\n"
        f"💳 شماره کارت: <code>{html.escape(card_number)}</code>\n"
        f"👤 به نام: {html.escape(card_holder)}\n"
    )
    await message.answer(text, reply_markup=kb.cancel_kb())


@router.message(WalletTopup.waiting_receipt, F.photo)
async def receive_topup_receipt(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    amount = data.get("topup_amount")
    if not amount:
        await message.answer("درخواست معتبر یافت نشد. لطفاً دوباره از منو شروع کنید.")
        await state.clear()
        return

    file_id = message.photo[-1].file_id
    topup_id = db.create_topup(message.from_user.id, amount)
    db.set_topup_receipt(topup_id, file_id)

    user_row = db.get_user(message.from_user.id)
    caption = (
        f"👛 درخواست شارژ کیف پول #{topup_id}\n"
        f"👤 کاربر: {html.escape(user_row['first_name'] or '')} (@{html.escape(user_row['username'] or '---')})\n"
        f"🆔 آیدی عددی: <code>{message.from_user.id}</code>\n"
        f"💰 مبلغ: {amount:,} تومان"
    )
    for admin_id in db.list_admins():
        try:
            sent = await bot.send_photo(
                admin_id, file_id, caption=caption,
                reply_markup=kb.topup_review_kb(topup_id),
            )
            db.set_topup_admin_message(topup_id, admin_id, sent.message_id)
        except Exception:
            pass

    await message.answer(
        "✅ درخواست شارژ کیف پول شما برای بررسی ارسال شد. پس از تایید ادمین، مبلغ به کیف پول شما اضافه می‌شود.",
        reply_markup=kb.menu_for_user(message.from_user.id),
    )
    await state.clear()


@router.message(WalletTopup.waiting_receipt)
async def topup_receipt_wrong_type(message: Message):
    await message.answer("لطفاً فقط عکس رسید پرداخت را ارسال کنید.")


# ---------------------------------------------------------------------------
# سفارش‌های من
# ---------------------------------------------------------------------------

@router.message(F.text.func(lambda t: t == db.get_setting("btn_my_orders")))
async def my_orders(message: Message):
    orders = db.get_user_orders(message.from_user.id)
    if not orders:
        await message.answer("شما تاکنون سفارشی ثبت نکرده‌اید.")
        return

    status_map = {"pending": "⏳ در انتظار بررسی", "approved": "✅ تایید شده", "rejected": "❌ رد شده"}
    lines = []
    for o in orders:
        product = db.get_product(o["product_id"])
        pname = html.escape(product["name"]) if product else "نامشخص"
        line = f"#{o['id']} | {pname} | {status_map.get(o['status'], o['status'])}"
        if o["status"] == "approved" and o["config_id"]:
            cfg = db.get_config_by_id(o["config_id"])
            if cfg:
                line += f"\n🔗 <code>{html.escape(cfg['link'])}</code>"
        lines.append(line)
    await message.answer("\n\n".join(lines))


# ---------------------------------------------------------------------------
# ارتباط با پشتیبانی
# ---------------------------------------------------------------------------

@router.message(F.text.func(lambda t: t == db.get_setting("btn_contact")))
async def contact_start(message: Message, state: FSMContext):
    await state.set_state(ContactFlow.waiting_message)
    await message.answer(db.get_setting("contact_text"), reply_markup=kb.cancel_kb())


@router.message(ContactFlow.waiting_message)
async def contact_receive(message: Message, state: FSMContext, bot: Bot, fixed_reseller_id: int = None, is_agent_bot: bool = False):
    user = message.from_user
    text = (
        f"📩 پیام جدید از کاربر\n"
        f"👤 {html.escape(user.first_name or '')} (@{html.escape(user.username or '---')})\n"
        f"🆔 <code>{user.id}</code>\n\n"
        f"✉️ {html.escape(message.text or '(بدون متن / رسانه)')}"
    )
    # داخل بات اختصاصی یک نماینده، پیام پشتیبانی فقط برای خودِ همان نماینده ارسال می‌شود
    targets = [fixed_reseller_id] if fixed_reseller_id is not None else db.list_admins()
    for admin_id in targets:
        try:
            await bot.send_message(admin_id, text, reply_markup=kb.contact_reply_kb(user.id))
        except Exception:
            pass
    await message.answer(
        "پیام شما برای پشتیبانی ارسال شد. به زودی پاسخ داده می‌شود.",
        reply_markup=kb.menu_for_user(user.id, is_agent_bot=is_agent_bot),
    )
    await state.clear()


# ---------------------------------------------------------------------------
# درخواست ساخت بات نمایندگی مستقل (کاربر توکن بات خودش را می‌دهد)
# ---------------------------------------------------------------------------

@router.message(F.text.func(lambda t: t == db.get_setting("btn_agent_bot_request")))
async def agent_bot_request_start(message: Message, state: FSMContext, is_agent_bot: bool = False):
    if is_agent_bot:
        return  # داخل بات یک نماینده نباید این گزینه اصلاً دیده شود
    await state.set_state(AgentBotRequest.waiting_shop_name)
    await message.answer(
        "🚀 ساخت بات نمایندگی مستقل\n\n"
        "با این قابلیت می‌توانید با توکن بات تلگرام خودتان، یک فروشگاه کاملاً مستقل "
        "(روی همین سرور و همین سیستم) داشته باشید و کانفیگ‌های خودتان را بفروشید.\n\n"
        "مراحل:\n"
        "۱) یک بات جدید در @BotFather بسازید و توکنش را بگیرید\n"
        "۲) توکن را اینجا ارسال کنید\n"
        "۳) پس از تایید ادمین، بات شما فعال می‌شود و پنل نمایندگی (مدیریت دسته‌بندی/محصول/کانفیگ) را در همان بات خودتان می‌بینید\n\n"
        "ابتدا یک نام برای فروشگاه خود ارسال کنید:",
        reply_markup=kb.cancel_kb(),
    )


@router.message(AgentBotRequest.waiting_shop_name)
async def agent_bot_request_shop_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("لطفاً یک نام معتبر ارسال کنید.")
        return
    await state.update_data(agent_shop_name=name)
    await state.set_state(AgentBotRequest.waiting_token)
    await message.answer(
        "حالا توکن بات خودتان را ارسال کنید (چیزی شبیه: 123456789:AAExample...):",
        reply_markup=kb.cancel_kb(),
    )


@router.message(AgentBotRequest.waiting_token)
async def agent_bot_request_token(message: Message, state: FSMContext):
    token = message.text.strip()
    if ":" not in token or len(token) < 20:
        await message.answer("این متن شبیه توکن بات تلگرام نیست. دوباره تلاش کنید یا لغو کنید.", reply_markup=kb.cancel_kb())
        return
    if db.get_agent_bot_by_token(token):
        await message.answer("⛔️ این توکن قبلاً برای درخواست دیگری ثبت شده است.", reply_markup=kb.cancel_kb())
        return

    # اعتبارسنجی توکن با فراخوانی مستقیم تلگرام
    test_bot = Bot(token=token)
    try:
        me = await test_bot.get_me()
    except Exception:
        await message.answer(
            "⛔️ این توکن معتبر نیست یا بات با آن ساخته نشده. لطفاً توکن صحیح را از @BotFather بگیرید و دوباره ارسال کنید.",
            reply_markup=kb.cancel_kb(),
        )
        return
    finally:
        await test_bot.session.close()

    await state.update_data(agent_bot_token=token, agent_bot_username=me.username)
    await state.set_state(AgentBotRequest.waiting_admin_id)
    await message.answer(
        f"✅ بات @{html.escape(me.username)} شناسایی شد.\n\n"
        "حالا آیدی عددی تلگرام کسی که می‌خواهد ادمین/مالک این بات باشد را ارسال کنید.\n"
        f"اگر خودتان ادمین آن باشید، همین عدد را بفرستید: <code>{message.from_user.id}</code>",
        reply_markup=kb.cancel_kb(),
    )


@router.message(AgentBotRequest.waiting_admin_id)
async def agent_bot_request_admin_id(message: Message, state: FSMContext, bot: Bot):
    if not message.text.strip().isdigit():
        await message.answer("لطفاً فقط آیدی عددی تلگرام ارسال کنید.")
        return
    admin_id = int(message.text.strip())

    data = await state.get_data()
    shop_name = data.get("agent_shop_name")
    token = data.get("agent_bot_token")
    username = data.get("agent_bot_username")
    await state.clear()

    request_id = db.create_agent_bot_request(message.from_user.id, admin_id, token, username, shop_name)

    await message.answer(
        "✅ درخواست شما ثبت شد و برای بررسی برای مالک مجموعه ارسال شد.\n"
        "پس از تایید، بات شما به‌صورت خودکار روی سرور بالا می‌آید و شما (یا آیدی‌ای که دادید) به‌عنوان "
        "ادمین/نماینده در همان بات، پنل مدیریت دسته‌بندی، محصول، کانفیگ و سفارش‌ها را خواهید دید.",
        reply_markup=kb.menu_for_user(message.from_user.id),
    )

    review_text = (
        f"🤖 درخواست بات نمایندگی مستقل جدید #{request_id}\n\n"
        f"👤 درخواست‌دهنده: <code>{message.from_user.id}</code>\n"
        f"🆔 آیدی ادمین بات: <code>{admin_id}</code>\n"
        f"🏪 نام فروشگاه: {html.escape(shop_name or '')}\n"
        f"🤖 یوزرنیم بات: @{html.escape(username or '')}\n"
        f"🔑 توکن: <code>{html.escape(token or '')}</code>"
    )
    for owner_admin_id in db.list_admins():
        try:
            await bot.send_message(
                owner_admin_id, review_text,
                reply_markup=kb.agent_bot_review_kb(request_id),
            )
        except Exception:
            pass
