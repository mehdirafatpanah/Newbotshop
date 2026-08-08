# -*- coding: utf-8 -*-
"""
Telegram Mini App API for Shopvpn.
Run together with main.py. The API uses the existing SQLite Database class.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import BOT_TOKEN, DB_PATH
from database import Database

BASE_DIR = Path(__file__).resolve().parent
WEBAPP_DIR = BASE_DIR / "webapp"
db = Database(DB_PATH)

app = FastAPI(title="Shopvpn Mini App API")
app.mount("/assets", StaticFiles(directory=str(WEBAPP_DIR)), name="assets")


def validate_telegram_init_data(init_data: str) -> dict:
    """Validate Telegram WebApp initData according to Telegram's HMAC scheme."""
    if not init_data:
        raise HTTPException(401, "Telegram initData is required")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise HTTPException(401, "Invalid Telegram initData")

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(pairs.items())
    )
    secret_key = hmac.new(
        b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256
    ).digest()
    calculated = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated, received_hash):
        raise HTTPException(401, "Invalid Telegram initData")

    # Prevent replay of very old initData.
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        raise HTTPException(401, "Invalid auth_date")
    import time
    if abs(int(time.time()) - auth_date) > 86400:
        raise HTTPException(401, "Expired Telegram initData")

    try:
        user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError:
        raise HTTPException(401, "Invalid Telegram user data")
    if not user.get("id"):
        raise HTTPException(401, "Telegram user not found")
    return user


def current_user(init_data: str):
    user = validate_telegram_init_data(init_data)
    db.add_or_update_user(
        int(user["id"]),
        user.get("username", "") or "",
        user.get("first_name", "") or "",
    )
    return user


def public_product(p):
    stock = db.count_available_configs(p["id"])
    return {
        "id": p["id"],
        "category_id": p["category_id"],
        "name": p["name"],
        "price": p["price"],
        "description": p["description"] or "",
        "duration_days": p["duration_days"] or 30,
        "stock": stock,
    }


class OrderRequest(BaseModel):
    product_id: int
    discount_code: str | None = None


class TopupRequest(BaseModel):
    amount: int


class DiscountRequest(BaseModel):
    code: str


@app.get("/")
async def index():
    return FileResponse(WEBAPP_DIR / "index.html")


@app.get("/api/me")
async def me(x_telegram_init_data: str = Header(default="")):
    user = current_user(x_telegram_init_data)
    row = db.get_user(int(user["id"]))
    stats = db.get_referral_stats(int(user["id"]))
    return {
        "user": {
            "id": user["id"],
            "first_name": user.get("first_name", ""),
            "last_name": user.get("last_name", ""),
            "username": user.get("username", ""),
        },
        "wallet": db.get_wallet_credit(int(user["id"])),
        "referral": {
            "enabled": db.get_setting("referral_enabled", "1") == "1",
            "count": stats["count"],
            "credit": stats["credit"],
        },
        "test": {
            "enabled": db.get_setting("test_enabled", "1") == "1",
            "used": row["test_used"] if row else 0,
        },
        "settings": {
            "welcome_text": db.get_setting("welcome_text"),
            "card_number": db.get_setting("card_number"),
            "card_holder": db.get_setting("card_holder"),
            "contact_text": db.get_setting("contact_text"),
        },
    }


@app.get("/api/catalog")
async def catalog(x_telegram_init_data: str = Header(default="")):
    current_user(x_telegram_init_data)
    categories = []
    for c in db.get_categories(active_only=True):
        products = [public_product(p) for p in db.get_products(c["id"], active_only=True)]
        categories.append({"id": c["id"], "name": c["name"], "products": products})
    return {"categories": categories}


@app.get("/api/products/{product_id}")
async def product(product_id: int, x_telegram_init_data: str = Header(default="")):
    current_user(x_telegram_init_data)
    p = db.get_product(product_id)
    if not p or not p["is_active"]:
        raise HTTPException(404, "Product not found")
    return public_product(p)


@app.post("/api/discount/check")
async def check_discount(
    body: DiscountRequest,
    x_telegram_init_data: str = Header(default=""),
):
    current_user(x_telegram_init_data)
    code = db.get_discount_code(body.code.strip())
    if not db.is_discount_code_valid(code):
        raise HTTPException(400, "کد تخفیف معتبر نیست")
    return {
        "code": code["code"],
        "discount": db.compute_discount_amount(code, 0) if code["fixed_amount"] else None,
        "percent": code["percent"],
        "fixed_amount": code["fixed_amount"],
    }


@app.get("/api/orders")
async def orders(x_telegram_init_data: str = Header(default="")):
    user = current_user(x_telegram_init_data)
    rows = db.get_user_orders(int(user["id"]))
    result = []
    for o in rows:
        p = db.get_product(o["product_id"])
        cfg = db.get_config_by_id(o["config_id"]) if o["config_id"] else None
        result.append({
            "id": o["id"],
            "product": p["name"] if p else "نامشخص",
            "status": o["status"],
            "base_price": o["base_price"],
            "discount_amount": o["discount_amount"],
            "wallet_used": o["wallet_used"],
            "final_price": o["final_price"],
            "created_at": o["created_at"],
            "config": cfg["link"] if cfg else None,
            "expires_at": cfg["expires_at"] if cfg else None,
        })
    return {"orders": result}


@app.post("/api/orders")
async def create_order(
    body: OrderRequest,
    x_telegram_init_data: str = Header(default=""),
):
    user = current_user(x_telegram_init_data)
    uid = int(user["id"])
    p = db.get_product(body.product_id)
    if not p or not p["is_active"]:
        raise HTTPException(404, "محصول یافت نشد")
    if db.count_available_configs(p["id"]) <= 0:
        raise HTTPException(409, "موجودی این محصول تمام شده است")

    discount_id = None
    discount_amount = 0
    if body.discount_code:
        code = db.get_discount_code(body.discount_code.strip())
        if not db.is_discount_code_valid(code):
            raise HTTPException(400, "کد تخفیف معتبر نیست")
        discount_id = code["id"]
        discount_amount = db.compute_discount_amount(code, p["price"])

    wallet = db.get_wallet_credit(uid)
    wallet_used = min(wallet, max(p["price"] - discount_amount, 0))

    if wallet_used:
        db.add_wallet_credit(uid, -wallet_used)
    if discount_id:
        db.increment_discount_usage(discount_id)

    order_id = db.create_order(
        uid, p["id"], p["price"],
        wallet_used=wallet_used,
        discount_code_id=discount_id,
        discount_amount=discount_amount,
    )
    order = db.get_order(order_id)

    # Full wallet/discount payment: allocate immediately, same business rule as bot.
    if order["final_price"] <= 0:
        result = db.take_unused_config(p["id"], uid)
        if not result:
            db.reject_order(order_id)
            raise HTTPException(409, "موجودی محصول تمام شد؛ مبلغ شما برگردانده شد")
        db.approve_order(order_id, result["id"])
        try:
            reward = db.reward_referrer_if_first_purchase(uid, order["base_price"])
            if reward:
                reward_amount, referrer_id = reward
                await telegram_send(
                    referrer_id,
                    f"🤝 تبریک! پورسانت خرید زیرمجموعه شما: {reward_amount:,} تومان"
                )
        except Exception:
            pass
        return {
            "order_id": order_id,
            "status": "approved",
            "final_price": 0,
            "config": result["link"],
            "expires_at": result.get("expires_at"),
        }

    return {
        "order_id": order_id,
        "status": "pending",
        "final_price": order["final_price"],
        "wallet_used": wallet_used,
        "discount_amount": discount_amount,
        "card_number": db.get_setting("card_number"),
        "card_holder": db.get_setting("card_holder"),
        "after_buy_text": db.get_setting("after_buy_text"),
    }


async def telegram_send(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(url, json={"chat_id": chat_id, "text": text})
        r.raise_for_status()


async def telegram_send_photo(chat_id: int, file_bytes: bytes, filename: str, caption: str, reply_markup: dict):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    files = {"photo": (filename, file_bytes, "image/jpeg")}
    data = {
        "chat_id": str(chat_id),
        "caption": caption,
        "parse_mode": "HTML",
        "reply_markup": json.dumps(reply_markup),
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, data=data, files=files)
        r.raise_for_status()


@app.post("/api/orders/{order_id}/receipt")
async def upload_receipt(
    order_id: int,
    receipt: UploadFile = File(...),
    x_telegram_init_data: str = Header(default=""),
):
    user = current_user(x_telegram_init_data)
    uid = int(user["id"])
    order = db.get_order(order_id)
    if not order or order["user_id"] != uid or order["status"] != "pending":
        raise HTTPException(404, "سفارش معتبر نیست")

    if receipt.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(400, "فقط تصویر قابل قبول است")

    data = await receipt.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "حجم تصویر بیش از حد مجاز است")

    db.set_order_receipt(order_id, f"miniapp:{uid}:{order_id}")

    p = db.get_product(order["product_id"])
    caption = (
        f"🧾 <b>سفارش #{order_id}</b>\n"
        f"👤 {user.get('first_name','')} (@{user.get('username','---')})\n"
        f"🆔 <code>{uid}</code>\n"
        f"📦 {p['name'] if p else '---'}\n"
        f"💰 مبلغ نهایی: {order['final_price']:,} تومان"
    )
    markup = {
        "inline_keyboard": [[
            {"text": "✅ تایید و ارسال کانفیگ", "callback_data": f"order_approve:{order_id}"},
            {"text": "❌ رد کردن", "callback_data": f"order_reject:{order_id}"},
        ]]
    }
    for admin_id in db.list_admins():
        try:
            await telegram_send_photo(admin_id, data, receipt.filename or "receipt.jpg", caption, markup)
        except Exception:
            pass

    return {"ok": True, "message": "رسید برای بررسی ارسال شد"}


@app.post("/api/topups")
async def create_topup(
    body: TopupRequest,
    x_telegram_init_data: str = Header(default=""),
):
    user = current_user(x_telegram_init_data)
    if body.amount < 1000 or body.amount > 100_000_000:
        raise HTTPException(400, "مبلغ شارژ نامعتبر است")

    topup_id = db.create_topup(int(user["id"]), body.amount)
    return {
        "topup_id": topup_id,
        "amount": body.amount,
        "card_number": db.get_setting("card_number"),
        "card_holder": db.get_setting("card_holder"),
    }


@app.post("/api/topups/{topup_id}/receipt")
async def upload_topup_receipt(
    topup_id: int,
    receipt: UploadFile = File(...),
    x_telegram_init_data: str = Header(default=""),
):
    user = current_user(x_telegram_init_data)
    uid = int(user["id"])

    # wallet_topups has no public getter in current Database, so use a narrow SQL lookup.
    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM wallet_topups WHERE id=? AND user_id=?",
            (topup_id, uid),
        ).fetchone()
    if not row or row["status"] != "pending":
        raise HTTPException(404, "درخواست شارژ معتبر نیست")

    if receipt.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(400, "فقط تصویر قابل قبول است")
    data = await receipt.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "حجم تصویر بیش از حد مجاز است")

    # Telegram file_id is not available from Mini App upload, so we notify admins
    # by uploading the image directly and keep a marker in SQLite.
    db.set_topup_receipt(topup_id, f"miniapp:{uid}:{topup_id}")
    caption = (
        f"👛 <b>درخواست شارژ کیف پول #{topup_id}</b>\n"
        f"👤 {user.get('first_name','')} (@{user.get('username','---')})\n"
        f"🆔 <code>{uid}</code>\n"
        f"💰 مبلغ: {row['amount']:,} تومان"
    )
    markup = {
        "inline_keyboard": [[
            {"text": "✅ تایید و شارژ کیف پول", "callback_data": f"topup_approve:{topup_id}"},
            {"text": "❌ رد کردن", "callback_data": f"topup_reject:{topup_id}"},
        ]]
    }
    for admin_id in db.list_admins():
        try:
            await telegram_send_photo(admin_id, data, receipt.filename or "receipt.jpg", caption, markup)
        except Exception:
            pass

    return {"ok": True, "message": "رسید برای بررسی ارسال شد"}


@app.get("/api/referral")
async def referral(x_telegram_init_data: str = Header(default="")):
    user = current_user(x_telegram_init_data)
    uid = int(user["id"])
    stats = db.get_referral_stats(uid)
    # Username is fetched from Bot API to create the same style of link as the bot.
    me_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(me_url)
        r.raise_for_status()
        username = r.json()["result"]["username"]
    return {
        "link": f"https://t.me/{username}?start=ref{uid}",
        "count": stats["count"],
        "credit": stats["credit"],
        "percent": int(db.get_setting("referral_percent", "10")),
    }


@app.post("/api/test")
async def test_config(x_telegram_init_data: str = Header(default="")):
    user = current_user(x_telegram_init_data)
    uid = int(user["id"])
    if db.get_setting("test_enabled", "1") != "1":
        raise HTTPException(400, "کانفیگ تست غیرفعال است")
    row = db.get_user(uid)
    if row and row["test_used"] >= 1:
        raise HTTPException(400, "کانفیگ تست شما قبلاً استفاده شده است")
    result = db.take_unused_test_config(uid)
    if not result:
        raise HTTPException(409, "موجودی کانفیگ تست تمام شده است")
    db.mark_test_used(uid)
    return {"config": result["link"]}


@app.post("/api/contact")
async def contact(
    payload: dict,
    x_telegram_init_data: str = Header(default=""),
):
    user = current_user(x_telegram_init_data)
    text = str(payload.get("message", "")).strip()
    if not text or len(text) > 4000:
        raise HTTPException(400, "متن پیام نامعتبر است")
    msg = (
        "📩 پیام جدید از Mini App\n"
        f"👤 {user.get('first_name','')} (@{user.get('username','---')})\n"
        f"🆔 {user['id']}\n\n{text}"
    )
    for admin_id in db.list_admins():
        try:
            await telegram_send(admin_id, msg)
        except Exception:
            pass
    return {"ok": True}
