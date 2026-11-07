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
from config import (ADMIN_IDS, ADMIN_PASSWORD, BOT_TOKEN, CARD_NUMBER, CARD_OWNER, CASHBACK,
                    COMMISSION, HOST, MIN_TOPUP, PORT, SHOP_ACCOUNT, WEBAPP_URL)

logging.basicConfig(level=logging.INFO)
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
WEB = Path(__file__).parent / "webapp"
som = S.som


def is_admin(uid):
    return uid in ADMIN_IDS


def webapp_kb():
    if not WEBAPP_URL.startswith("https://"):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎁 Bozorni ochish", web_app=WebAppInfo(url=WEBAPP_URL))]])


# ═══════════════════════ BOT ═══════════════════════

@dp.message(CommandStart())
async def start(m: Message):
    db.upsert_user(m.from_user.id, m.from_user.username, m.from_user.full_name)
    text = (f"Assalomu alaykum, <b>{m.from_user.first_name}</b>! 👋\n\n"
            "🎁 <b>NFT sovg'alar bozori</b>\n"
            "🛒 Sotib olish — o'zbek so'mida\n"
            "🔑 Ijaraga olish — garovsiz, 1 kundan 3 oygacha\n"
            "💳 Balansni karta orqali to'ldiring"
            + (f" — {CASHBACK:g}% cashback" if CASHBACK else "") + "\n"
            "⚡️ Tez yetkazib berish\n\n"
            f"💰 Balansingiz: <b>{som(db.balance(m.from_user.id))}</b>\n\nPastdagi tugmani bosing 👇")
    if is_admin(m.from_user.id):
        text += f"\n\n👮 Admin panel: {WEBAPP_URL}/admin"
    await m.answer(text, reply_markup=webapp_kb())


@dp.message(Command("balans", "balance"))
async def balance_cmd(m: Message):
    await m.answer(f"💰 Balansingiz: <b>{som(db.balance(m.from_user.id))}</b>", reply_markup=webapp_kb())


@dp.message(Command("admin"))
async def admin_cmd(m: Message):
    if is_admin(m.from_user.id):
        s = db.stats()
        await m.answer(
            f"👮 Admin panel: {WEBAPP_URL}/admin\n\n"
            f"👥 Foydalanuvchilar: {s['users']}\n🎁 Bozorda: {s['active']} · 🔑 Ijarada: {s['rented']}\n"
            f"💳 Chek tekshiruvi: {s['topups_checking']} · 🔗 Ulash kerak: {s['to_link']} · "
            f"📦 Yuborish kerak: {s['to_deliver']}\n💰 Aylanma: {som(s['revenue'])}")


@dp.message(F.photo | F.document)
async def receipt(m: Message):
    """Balans to'ldirish cheki."""
    t = db.waiting_topup(m.from_user.id)
    if not t:
        return await m.answer("Avval Mini App'da <b>Profil → Balansni to'ldirish</b> ni bosing va summani kiriting.",
                              reply_markup=webapp_kb())
    file_id = m.photo[-1].file_id if m.photo else m.document.file_id
    db.set_topup(t["id"], status="checking", receipt_file=file_id)
    await m.answer("✅ Chek qabul qilindi. Admin tekshirgach balansingiz to'ldiriladi (odatda 5–15 daqiqa).")
    u = m.from_user
    cap = (f"💳 <b>Balans to'ldirish #{t['id']}</b>\n💰 {som(t['amount'])}\n"
           f"👤 {u.full_name} (@{u.username or '-'}) <code>{u.id}</code>")
    for a in ADMIN_IDS:
        try:
            if m.photo:
                await bot.send_photo(a, file_id, caption=cap, reply_markup=S.kb_topup(t["id"]))
            else:
                await bot.send_document(a, file_id, caption=cap, reply_markup=S.kb_topup(t["id"]))
        except Exception as e:
            logging.warning("admin %s: %s", a, e)


@dp.message(F.text)
async def text_msg(m: Message):
    link = S.extract_tc_link(m.text)
    if link and await S.receive_tc_link(bot, m.from_user.id, link):
        return
    if link:
        return await m.answer("Sizda ulanishni kutayotgan ijara yo'q.")
    if db.user_order_needing_link(m.from_user.id):
        return await m.answer("Bu havola emas. Fragment'dagi <b>Connect TON</b> oynasidan "
                              "<code>tc://</code> bilan boshlanadigan havolani nusxalab yuboring.")
    await m.answer("Bozorni ochish uchun pastdagi tugmani bosing 👇", reply_markup=webapp_kb())


@dp.callback_query(F.data.startswith(("o:", "g:", "t:")))
async def admin_cb(c: CallbackQuery):
    if not is_admin(c.from_user.id):
        return await c.answer("Ruxsat yo'q", show_alert=True)
    kind, action, _id = c.data.split(":")
    _id = int(_id)
    if kind == "o":
        ok, msg = await S.ORDER_ACTIONS[action](bot, _id)
    elif kind == "t":
        ok, msg = await (S.confirm_topup(bot, _id) if action == "ok" else S.reject_topup(bot, _id))
    else:
        ok, msg = await S.approve_listing(bot, _id, action == "approve")
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


def ok(**kw):
    return web.json_response({"ok": True, **kw})


def err(msg):
    return web.json_response({"ok": False, "error": msg})


async def api_config(request):
    return web.json_response({"commission": COMMISSION, "shop": SHOP_ACCOUNT, "cashback": CASHBACK,
                              "min_topup": MIN_TOPUP, "card": CARD_NUMBER, "card_owner": CARD_OWNER,
                              "packages": [{"days": d, "disc": p, "name": S.PACKAGE_NAMES[d]} for d, p in S.PACKAGES]})


async def api_gifts(request):
    q = request.query
    statuses = ("rented",) if q.get("status") == "rented" else ("active",)
    return web.json_response(db.list_gifts(q.get("q", ""), q.get("sort", "new"), q.get("mode", "all"), statuses))


async def api_me(request):
    user, _ = await auth(request)
    u = db.get_user(user["id"])
    return ok(balance=u["balance"], name=u["full_name"], username=u["username"],
              orders=db.user_orders(user["id"]))


async def api_buy(request):
    user, body = await auth(request)
    good, msg = await S.buy(bot, user["id"], int(body.get("gift_id", 0)))
    return ok(msg=msg, balance=db.balance(user["id"])) if good else err(msg)


async def api_rent(request):
    user, body = await auth(request)
    good, msg = await S.rent(bot, user["id"], int(body.get("gift_id", 0)), int(body.get("days", 0)))
    return ok(msg=msg, balance=db.balance(user["id"])) if good else err(msg)


async def api_link(request):
    """Ijarachi Fragment havolasini Mini App ichidan yuboradi."""
    user, body = await auth(request)
    link = S.extract_tc_link(body.get("link", ""))
    if not link:
        return err("Havola noto'g'ri. U tc:// bilan boshlanishi kerak")
    if not await S.receive_tc_link(bot, user["id"], link):
        return err("Ulanishni kutayotgan ijara yo'q")
    return ok()


async def api_topup(request):
    user, body = await auth(request)
    amount = int(body.get("amount") or 0)
    if amount < MIN_TOPUP:
        return err(f"Eng kam summa: {som(MIN_TOPUP)}")
    tid = db.create_topup(user["id"], amount)
    await S.send(bot, user["id"],
                 f"💳 <b>Balansni to'ldirish #{tid}</b>\n\n"
                 f"💰 Summa: <b>{som(amount)}</b>\n"
                 f"💳 Karta: <code>{CARD_NUMBER}</code>\n👤 {CARD_OWNER}\n\n"
                 f"To'lovdan so'ng <b>chek skrinshotini</b> shu yerga yuboring."
                 + (f"\n🎁 Cashback: +{som(amount * CASHBACK / 100)}" if CASHBACK else ""))
    return ok(id=tid)


async def api_sell(request):
    """Foydalanuvchi sovg'asini bizga sotadi."""
    user, body = await auth(request)
    p = S.parse_nft_link(body.get("link", ""))
    price = int(body.get("price") or 0)
    card = (body.get("card") or "").strip()
    if not p:
        return err("Havola noto'g'ri. Misol: https://t.me/nft/PlushPepe-1234")
    if price < 1000:
        return err("Narxni kiriting")
    if len(card.replace(" ", "")) < 16:
        return err("Pul tushadigan karta raqamini kiriting")
    gid = db.add_gift(**p, for_sale=1, price=price, seller_id=user["id"], seller_card=card, status="pending")
    await S.notify_admins(
        bot, f"📥 <b>Sotish arizasi #{gid}</b>\n🎁 {S.gname(p)}\n🔗 {p['link']}\n💰 So'ralgan narx: {som(price)}\n"
             f"💳 {card}\n👤 @{user.get('username') or '-'} <code>{user['id']}</code>\n\n"
             f"Kelishilgach sovg'ani {SHOP_ACCOUNT} ga o'tkazishini so'rang va pulni kartaga o'tkazing. "
             f"Qabul qilinsa sovg'a shu narxda bozorga chiqadi (narxni admin panelda o'zgartirsa bo'ladi).",
        reply_markup=S.kb_listing(gid))
    await S.send(bot, user["id"],
                 f"📥 Arizangiz qabul qilindi: <b>{S.gname(p)}</b> — {som(price)}\n"
                 f"Admin tez orada siz bilan bog'lanadi.")
    return ok()


async def api_top(request):
    rows = db.top_users(30)
    for r in rows:
        r["full_name"] = (r["full_name"] or "")[:20]
        r.pop("id", None)
    return web.json_response(rows)


async def index(request):
    return web.FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


# ═══════════════════════ ADMIN SAYT ═══════════════════════

ADMIN_TOKEN = hmac.new(ADMIN_PASSWORD.encode(), BOT_TOKEN.encode(), hashlib.sha256).hexdigest()


@web.middleware
async def admin_guard(request, handler):
    if request.path.startswith("/admin/api/") and request.cookies.get("adm") != ADMIN_TOKEN:
        raise web.HTTPUnauthorized(text="login")
    return await handler(request)


async def admin_page(request):
    return web.FileResponse(WEB / "admin.html", headers={"Cache-Control": "no-cache"})


async def admin_login(request):
    body = await request.json()
    if not hmac.compare_digest(str(body.get("password", "")), ADMIN_PASSWORD):
        await asyncio.sleep(1)
        return err("Parol noto'g'ri")
    r = ok()
    r.set_cookie("adm", ADMIN_TOKEN, max_age=30 * 86400, httponly=True, samesite="Lax",
                 secure=request.secure or request.headers.get("X-Forwarded-Proto") == "https")
    return r


async def admin_logout(request):
    r = ok()
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
        return ok(id=db.add_gift(**f))
    db.update_gift(gid, **f)
    return ok()


async def a_gift_action(request):
    gid, act = int(request.match_info["id"]), request.match_info["act"]
    if act in ("approve", "reject"):
        good, msg = await S.approve_listing(bot, gid, act == "approve")
    elif act == "hide":
        db.update_gift(gid, status="rejected"); good, msg = True, "Yashirildi"
    elif act == "activate":
        db.update_gift(gid, status="active"); good, msg = True, "Faollashtirildi"
    else:
        good, msg = False, "Noma'lum amal"
    return ok(msg=msg) if good else err(msg)


async def a_orders(request):
    q = request.query
    return web.json_response(db.list_orders(q.get("kind") or None, q.get("status") or None))


async def a_order_action(request):
    oid, act = int(request.match_info["id"]), request.match_info["act"]
    fn = S.ORDER_ACTIONS.get(act)
    if not fn:
        return err("Noma'lum amal")
    good, msg = await fn(bot, oid)
    return ok(msg=msg) if good else err(msg)


async def a_topups(request):
    return web.json_response(db.list_topups(request.query.get("status") or None))


async def a_topup_action(request):
    tid, act = int(request.match_info["id"]), request.match_info["act"]
    try:
        body = await request.json()
    except Exception:
        body = {}
    if act == "ok":
        good, msg = await S.confirm_topup(bot, tid, body.get("amount"))
    else:
        good, msg = await S.reject_topup(bot, tid)
    return ok(msg=msg) if good else err(msg)


async def a_users(request):
    return web.json_response(db.list_users())


async def a_ban(request):
    body = await request.json()
    db.set_banned(int(request.match_info["id"]), bool(body.get("banned")))
    return ok()


async def a_balance(request):
    uid = int(request.match_info["id"])
    body = await request.json()
    delta = int(body.get("delta") or 0)
    if not delta:
        return err("Summani kiriting")
    db.add_balance(uid, delta)
    new = db.balance(uid)
    await S.send(bot, uid, f"💰 Balansingiz {'+' if delta > 0 else ''}{som(delta)} ga o'zgartirildi.\n"
                           f"Joriy balans: <b>{som(new)}</b>")
    return ok(msg=f"Yangi balans: {som(new)}")


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
    return ok(msg="Yuborish boshlandi")


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


async def health(request):
    return web.Response(text="ok")


def make_app():
    app = web.Application(middlewares=[admin_guard])
    r = app.router
    r.add_get("/", index)
    r.add_get("/health", health)
    r.add_get("/api/config", api_config)
    r.add_get("/api/gifts", api_gifts)
    r.add_get("/api/top", api_top)
    r.add_post("/api/me", api_me)
    r.add_post("/api/buy", api_buy)
    r.add_post("/api/rent", api_rent)
    r.add_post("/api/link", api_link)
    r.add_post("/api/topup", api_topup)
    r.add_post("/api/sell", api_sell)
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
    r.add_get("/admin/api/topups", a_topups)
    r.add_post("/admin/api/topups/{id:\\d+}/{act}", a_topup_action)
    r.add_get("/admin/api/users", a_users)
    r.add_post("/admin/api/users/{id:\\d+}/ban", a_ban)
    r.add_post("/admin/api/users/{id:\\d+}/balance", a_balance)
    r.add_post("/admin/api/broadcast", a_broadcast)
    r.add_get("/admin/api/file/{fid}", a_file)
    return app


async def main():
    db.init()
    runner = web.AppRunner(make_app())
    await runner.setup()
    await web.TCPSite(runner, HOST, PORT).start()
    logging.info("Server: %s:%s | Mini App: %s | Admin: %s/admin", HOST, PORT, WEBAPP_URL, WEBAPP_URL)
    logging.info("Adminlar: %s", ADMIN_IDS or "YO'Q — ADMIN_IDS ni tekshiring")
    if WEBAPP_URL.startswith("https://"):
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="🎁 Bozor", web_app=WebAppInfo(url=WEBAPP_URL)))
    asyncio.create_task(ticker())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
