import asyncio
import hashlib
import hmac
import json
import logging
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           MenuButtonWebApp, Message, WebAppInfo)

import db
import services as S
from config import (ADMIN_IDS, ADMIN_PASSWORD, BOT_TOKEN, CARD_NUMBER, CARD_OWNER,
                    COMMISSION, HOST, PORT, SHOP_ACCOUNT, WEBAPP_URL)

logging.basicConfig(level=logging.INFO)
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
WEB = Path(__file__).parent / "webapp"
som = S.som


def is_admin(uid):
    return uid in ADMIN_IDS


def webapp_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎁 Bozorni ochish", web_app=WebAppInfo(url=WEBAPP_URL))]])


# ═══════════════════════ BOT ═══════════════════════

@dp.message(CommandStart())
async def start(m: Message):
    db.upsert_user(m.from_user.id, m.from_user.username, m.from_user.full_name)
    text = (f"Assalomu alaykum, <b>{m.from_user.first_name}</b>! 👋\n\n"
            "🎁 <b>NFT sovg'alar bozori</b>\n"
            "🛒 Sotib olish — o'zbek so'mida\n"
            "🔑 Ijaraga olish — kunlik narxda\n"
            "💸 O'z sovg'angizni sotish yoki ijaraga berish\n"
            "⚡️ Tez yetkazib berish\n\nPastdagi tugmani bosing 👇")
    if is_admin(m.from_user.id):
        text += f"\n\n👮 Admin panel: {WEBAPP_URL}/admin"
    await m.answer(text, reply_markup=webapp_kb())


@dp.message(Command("admin"))
async def admin_cmd(m: Message):
    if is_admin(m.from_user.id):
        await m.answer(f"👮 Admin panel: {WEBAPP_URL}/admin\n\n" + stats_text())


def stats_text():
    s = db.stats()
    return (f"👥 Foydalanuvchilar: {s['users']}\n🎁 Bozorda: {s['active']}\n"
            f"✅ Sotilgan: {s['sold']} · 🔑 Ijarada: {s['rented']}\n"
            f"🔎 Chek tekshiruvi: {s['checking']} · 📦 Yetkazish: {s['to_deliver']}\n"
            f"💰 Daromad: {som(s['revenue'])}")


@dp.message(F.photo | F.document)
async def receipt(m: Message):
    """To'lov cheki."""
    o = db.user_waiting_order(m.from_user.id)
    if not o:
        return await m.answer("Sizda to'lov kutilayotgan buyurtma yo'q.")
    file_id = m.photo[-1].file_id if m.photo else m.document.file_id
    db.set_order(o["id"], status="checking", receipt_file=file_id)
    g = db.get_gift(o["gift_id"])
    await m.answer("✅ Chek qabul qilindi. Admin tekshirgach xabar beramiz (odatda 5–15 daqiqa).")
    u = m.from_user
    cap = f"💳 {S.order_text(o, g)}\n👤 {u.full_name} (@{u.username or '-'}) <code>{u.id}</code>"
    kb = S.kb_order(o["id"], "confirm", "reject")
    for a in ADMIN_IDS:
        try:
            if m.photo:
                await bot.send_photo(a, file_id, caption=cap, reply_markup=kb)
            else:
                await bot.send_document(a, file_id, caption=cap, reply_markup=kb)
        except Exception as e:
            logging.warning("admin %s: %s", a, e)


@dp.callback_query(F.data.startswith(("o:", "g:")))
async def admin_cb(c: CallbackQuery):
    if not is_admin(c.from_user.id):
        return await c.answer("Ruxsat yo'q", show_alert=True)
    kind, action, _id = c.data.split(":")
    if kind == "o":
        ok, msg = await S.ORDER_ACTIONS[action](bot, int(_id))
    else:
        ok, msg = await S.approve_listing(bot, int(_id), action == "approve")
    if ok:
        try:
            await c.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await c.answer(msg, show_alert=not ok)


# ═══════════════════════ MINI APP API ═══════════════════════

def check_init_data(init_data: str):
    try:
        data = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None
    received = data.pop("hash", None)
    if not received:
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), received):
        return None
    return json.loads(data.get("user", "{}"))


async def auth(request):
    body = await request.json()
    user = check_init_data(body.get("initData", ""))
    if not user:
        raise web.HTTPUnauthorized(text="bad initData")
    db.upsert_user(user["id"], user.get("username"), user.get("first_name", ""))
    u = db.get_user(user["id"])
    if u and u["banned"]:
        raise web.HTTPForbidden(text="banned")
    return user, body


def err(msg):
    return web.json_response({"ok": False, "error": msg})


async def api_config(request):
    return web.json_response({"commission": COMMISSION, "shop": SHOP_ACCOUNT})


async def api_gifts(request):
    q = request.query
    return web.json_response(db.list_gifts(q.get("q", ""), q.get("sort", "new"), q.get("mode", "all")))


async def api_order(request):
    user, body = await auth(request)
    kind = "rent" if body.get("kind") == "rent" else "buy"
    gid = int(body.get("gift_id", 0))
    days = int(body.get("days", 0) or 0)
    card = (body.get("card") or "").strip()
    g = db.get_gift(gid)
    if not g:
        return err("Sovg'a topilmadi")
    if g["seller_id"] == user["id"]:
        return err("O'z sovg'angizni ololmaysiz")
    if kind == "rent" and not (1 <= days <= 30):
        return err("Ijara muddati 1–30 kun")
    if kind == "rent" and len(card.replace(" ", "")) < 16:
        return err("Garov qaytarilishi uchun karta raqamini kiriting")
    if db.user_waiting_order(user["id"]):
        return err("Avvalgi buyurtmani to'lang yoki 30 daqiqa kuting")
    oid = db.create_order(kind, gid, user["id"], days, card)
    if not oid:
        return err("Bu sovg'a hozir band")
    o = db.get_order(oid)
    await S.send(bot, user["id"],
                 f"🧾 {S.order_text(o, g)}\n\n"
                 f"💳 Karta: <code>{CARD_NUMBER}</code>\n👤 {CARD_OWNER}\n\n"
                 f"To'lovdan so'ng <b>chek skrinshotini</b> shu yerga yuboring.\n"
                 f"⏳ Sovg'a 30 daqiqaga siz uchun band qilindi.")
    return web.json_response({"ok": True, "order_id": oid})


async def api_orders(request):
    user, _ = await auth(request)
    return web.json_response(db.user_orders(user["id"]))


async def api_list(request):
    """Foydalanuvchi o'z sovg'asini sotuvga / ijaraga qo'yadi."""
    user, body = await auth(request)
    p = S.parse_nft_link(body.get("link", ""))
    if not p:
        return err("Havola noto'g'ri. Misol: https://t.me/nft/PlushPepe-1234")
    for_sale, for_rent = bool(body.get("for_sale")), bool(body.get("for_rent"))
    price, rent_price, deposit = (int(body.get(k) or 0) for k in ("price", "rent_price", "deposit"))
    card = (body.get("card") or "").strip()
    if not (for_sale or for_rent):
        return err("Sotish yoki ijarani tanlang")
    if for_sale and price < 1000:
        return err("Sotuv narxini kiriting")
    if for_rent and (rent_price < 1000 or deposit < 1000):
        return err("Kunlik ijara narxi va garovni kiriting")
    if len(card.replace(" ", "")) < 16:
        return err("Pul tushadigan karta raqamini kiriting")
    gid = db.add_gift(**p, for_sale=int(for_sale), price=price, for_rent=int(for_rent),
                      rent_price=rent_price, deposit=deposit, seller_id=user["id"],
                      seller_card=card, status="pending")
    lines = []
    if for_sale:
        lines.append(f"🛒 Sotuv: {som(price)}")
    if for_rent:
        lines.append(f"🔑 Ijara: {som(rent_price)}/kun, garov {som(deposit)}")
    info = "\n".join(lines)
    await S.notify_admins(
        bot, f"📥 <b>Yangi e'lon #{gid}</b>\n🎁 {S.gname(p)}\n🔗 {p['link']}\n{info}\n"
             f"👤 @{user.get('username') or '-'} <code>{user['id']}</code>\n\n"
             f"Sovg'a {SHOP_ACCOUNT} ga o'tkazilganini tekshirib qabul qiling.",
        reply_markup=S.kb_listing(gid))
    await S.send(bot, user["id"],
                 f"📥 E'loningiz qabul qilindi: <b>{S.gname(p)}</b>\n{info}\n\n"
                 f"👉 Sovg'ani <b>{SHOP_ACCOUNT}</b> ga o'tkazing — admin tekshirgach bozorga chiqadi.\n"
                 f"Har bir sotuv/ijaradan {COMMISSION:g}% komissiya olinadi.")
    return web.json_response({"ok": True})


async def index(request):
    return web.FileResponse(WEB / "index.html")


# ═══════════════════════ ADMIN SAYT ═══════════════════════

ADMIN_TOKEN = hmac.new(ADMIN_PASSWORD.encode(), BOT_TOKEN.encode(), hashlib.sha256).hexdigest()


@web.middleware
async def admin_guard(request, handler):
    if request.path.startswith("/admin/api/") and request.cookies.get("adm") != ADMIN_TOKEN:
        raise web.HTTPUnauthorized(text="login")
    return await handler(request)


async def admin_page(request):
    return web.FileResponse(WEB / "admin.html")


async def admin_login(request):
    body = await request.json()
    if not hmac.compare_digest(str(body.get("password", "")), ADMIN_PASSWORD):
        await asyncio.sleep(1)
        return err("Parol noto'g'ri")
    r = web.json_response({"ok": True})
    r.set_cookie("adm", ADMIN_TOKEN, max_age=30 * 86400, httponly=True, samesite="Lax",
                 secure=request.secure or request.headers.get("X-Forwarded-Proto") == "https")
    return r


async def admin_logout(request):
    r = web.json_response({"ok": True})
    r.del_cookie("adm")
    return r


async def a_stats(request):
    return web.json_response(db.stats())


async def a_gifts(request):
    st = request.query.get("status")
    statuses = (st,) if st else ("pending", "active", "reserved", "rented", "sold")
    return web.json_response(db.list_gifts(request.query.get("q", ""), "new", "all", statuses))


async def a_gift_save(request):
    body = await request.json()
    gid = int(request.match_info.get("id", 0))
    f = {k: body[k] for k in db.GIFT_FIELDS if k in body}
    for k in ("price", "rent_price", "deposit", "for_sale", "for_rent"):
        if k in f:
            f[k] = int(f[k] or 0)
    if not gid:
        p = S.parse_nft_link(body.get("link", ""))
        if p:
            for k, v in p.items():
                if not f.get(k):
                    f[k] = v
        if not f.get("title"):
            return err("Havola yoki nom kiriting")
        f["status"] = f.get("status") or "active"
        return web.json_response({"ok": True, "id": db.add_gift(**f)})
    db.update_gift(gid, **f)
    return web.json_response({"ok": True})


async def a_gift_action(request):
    gid, act = int(request.match_info["id"]), request.match_info["act"]
    if act in ("approve", "reject"):
        ok, msg = await S.approve_listing(bot, gid, act == "approve")
    elif act == "hide":
        db.update_gift(gid, status="rejected"); ok, msg = True, "Yashirildi"
    elif act == "activate":
        db.update_gift(gid, status="active"); ok, msg = True, "Faollashtirildi"
    else:
        ok, msg = False, "Noma'lum amal"
    return web.json_response({"ok": ok, "error": None if ok else msg, "msg": msg})


async def a_orders(request):
    q = request.query
    return web.json_response(db.list_orders(q.get("kind") or None, q.get("status") or None))


async def a_order_action(request):
    oid, act = int(request.match_info["id"]), request.match_info["act"]
    fn = S.ORDER_ACTIONS.get(act)
    if not fn:
        return err("Noma'lum amal")
    ok, msg = await fn(bot, oid)
    return web.json_response({"ok": ok, "error": None if ok else msg, "msg": msg})


async def a_users(request):
    return web.json_response(db.list_users())


async def a_ban(request):
    body = await request.json()
    db.set_banned(int(request.match_info["id"]), bool(body.get("banned")))
    return web.json_response({"ok": True})


async def a_broadcast(request):
    text = ((await request.json()).get("text") or "").strip()
    if not text:
        return err("Matn bo'sh")

    async def run():
        sent = 0
        for uid in db.all_user_ids():
            if await S.send(bot, uid, text, reply_markup=webapp_kb()):
                sent += 1
            await asyncio.sleep(0.05)
        await S.notify_admins(bot, f"📢 Xabar {sent} kishiga yuborildi.")

    asyncio.create_task(run())
    return web.json_response({"ok": True, "msg": "Yuborish boshlandi"})


async def a_file(request):
    """Chek rasmini Telegram'dan olib ko'rsatadi."""
    try:
        f = await bot.get_file(request.match_info["fid"])
        data = await bot.download_file(f.file_path)
        ct = "image/jpeg" if f.file_path.endswith((".jpg", ".jpeg")) else "application/octet-stream"
        return web.Response(body=data.read(), content_type=ct)
    except Exception:
        raise web.HTTPNotFound()


# ═══════════════════════ ISHGA TUSHIRISH ═══════════════════════

async def ticker():
    while True:
        try:
            await S.background_tick(bot)
        except Exception as e:
            logging.exception("tick: %s", e)
        await asyncio.sleep(60)


def make_app():
    app = web.Application(middlewares=[admin_guard])
    r = app.router
    r.add_get("/", index)
    r.add_get("/health", lambda _: web.Response(text="ok"))
    r.add_get("/api/config", api_config)
    r.add_get("/api/gifts", api_gifts)
    r.add_post("/api/order", api_order)
    r.add_post("/api/orders", api_orders)
    r.add_post("/api/list", api_list)
    r.add_get("/admin", admin_page)
    r.add_post("/admin/login", admin_login)
    r.add_post("/admin/logout", admin_logout)
    r.add_get("/admin/api/stats", a_stats)
    r.add_get("/admin/api/gifts", a_gifts)
    r.add_post("/admin/api/gifts", a_gift_save)
    r.add_post("/admin/api/gifts/{id:\\d+}", a_gift_save)
    r.add_post("/admin/api/gifts/{id:\\d+}/{act}", a_gift_action)
    r.add_get("/admin/api/orders", a_orders)
    r.add_post("/admin/api/orders/{id:\\d+}/{act}", a_order_action)
    r.add_get("/admin/api/users", a_users)
    r.add_post("/admin/api/users/{id:\\d+}/ban", a_ban)
    r.add_post("/admin/api/broadcast", a_broadcast)
    r.add_get("/admin/api/file/{fid}", a_file)
    return app


async def main():
    db.init()
    runner = web.AppRunner(make_app())
    await runner.setup()
    await web.TCPSite(runner, HOST, PORT).start()
    logging.info("Server: %s:%s | Mini App: %s | Admin: %s/admin", HOST, PORT, WEBAPP_URL, WEBAPP_URL)
    if WEBAPP_URL:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="🎁 Bozor", web_app=WebAppInfo(url=WEBAPP_URL)))
    asyncio.create_task(ticker())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
