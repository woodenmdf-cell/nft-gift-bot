import asyncio
import hashlib
import hmac
import json
import re
import uuid
import os
import sqlite3
import logging
import time
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import ClientSession, ClientTimeout, web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import (BotCommand, CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup,
                           MenuButtonWebApp, Message, WebAppInfo)

import db
import game
import pricing
import services as S
from config import (DATA_DIR, DB_PATH, ADMIN_IDS, ADMIN_PASSWORD, BOT_TOKEN, CARD_NUMBER, CARD_OWNER, CASHBACK,
                    COMMISSION, GAME_VIP_DAYS, GAME_VIP_PRICE, HOST, MIN_TOPUP, PORT, SHOP_ACCOUNT,
                    WEBAPP_URL)

logging.basicConfig(level=logging.INFO)
if not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{30,}", BOT_TOKEN or ""):
    logging.error("BOT_TOKEN topilmadi yoki noto'g'ri (uzunligi: %s). Railway → Variables → BOT_TOKEN ga "
                  "@BotFather bergan tokenni qo'ying (masalan 1234567890:AAH...).", len(BOT_TOKEN or ""))
    raise SystemExit(1)
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
WEB = Path(__file__).parent / "webapp"
som = S.som


def is_admin(uid):
    return uid in ADMIN_IDS


def webapp_kb():
    if not WEBAPP_URL.startswith("https://"):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Bozorni ochish", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text="🎮 Shahar Arena o'yini", web_app=WebAppInfo(url=WEBAPP_URL + "/game"))]])


def game_kb():
    if not WEBAPP_URL.startswith("https://"):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎮 O'ynash", web_app=WebAppInfo(url=WEBAPP_URL + "/game"))]])


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
    await m.answer(text, reply_markup=webapp_kb())
    if is_admin(m.from_user.id):
        await m.answer("👮 Siz adminsiz. Admin panel uchun /admin yozing.")


@dp.message(Command("qollanma", "guide"))
async def guide_cmd(m: Message):
    await S.send_guide(m.bot, m.chat.id)


@dp.message(Command("oyin", "game"))
async def game_cmd(m: Message):
    db.upsert_user(m.from_user.id, m.from_user.username, m.from_user.full_name)
    await m.answer(
        "🎮 <b>Shahar Arena</b>\n\n"
        "🏙 3D ochiq shahar: piyoda yuring, istalgan mashinaga o'tiring, topshiriqlar bajaring, "
        "politsiyadan qoching, tanga yig'ing\n"
        "👥 Do'stlaringiz bilan bir shaharda onlayn o'ynang\n"
        "🧍 Personajingizni kiyintiring, 🛠 mashina va yaxshilashlar sotib oling\n\n"
        "O'yin <b>bepul</b>. 👑 <b>VIP</b> obuna (ixtiyoriy, "
        f"{som(GAME_VIP_PRICE)} / {GAME_VIP_DAYS} kun): ×2 tanga, +15% kuch, oltin superkar, "
        "VIP kiyimlar va katta kunlik bonus.", reply_markup=game_kb())


@dp.message(Command("balans", "balance"))
async def balance_cmd(m: Message):
    await m.answer(f"💰 Balansingiz: <b>{som(db.balance(m.from_user.id))}</b>", reply_markup=webapp_kb())


def admin_login_url():
    ts = str(int(time.time()))
    sig = hmac.new(ADMIN_TOKEN.encode(), ts.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{WEBAPP_URL}/admin/auto?ts={ts}&sig={sig}"


def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="👮 Admin panelga kirish", url=admin_login_url())]])


@dp.message(Command("admin"))
async def admin_cmd(m: Message):
    if is_admin(m.from_user.id):
        s = db.stats()
        await m.answer(
            "👮 <b>Admin panel</b> — pastdagi tugmani bosing (havola 10 daqiqa amal qiladi, "
            "brauzer sizni 30 kun eslab qoladi).\n\n"
            f"👥 Foydalanuvchilar: {s['users']}\n🎁 Bozorda: {s['active']} · 🔑 Ijarada: {s['rented']}\n"
            f"💳 Chek tekshiruvi: {s['topups_checking']} · 🔗 Ulash kerak: {s['to_link']} · "
            f"📦 Yuborish kerak: {s['to_deliver']}\n💰 Aylanma: {som(s['revenue'])}",
            reply_markup=admin_kb())


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


@dp.message(F.text & ~F.text.startswith("/"))
async def text_msg(m: Message):
    link = S.extract_tc_link(m.text)
    if link and await S.receive_tc_link(bot, m.from_user.id, link):
        return
    if link:
        return await m.answer("Sizda ulanishni kutayotgan ijara yo'q.")
    if db.user_order_needing_link(m.from_user.id):
        return await m.answer("Bu havola emas. Fragment'dagi <b>Connect TON</b> oynasida "
                              "<b>Copy Link</b> ni bosib, nusxalangan havolani yuboring.")
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
        return err("Havola noto'g'ri. Fragment'dagi Connect TON oynasida «Copy Link» ni bosib nusxalang")
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


def link_quote(link):
    m = re.search(r"t\.me/nft/([A-Za-z0-9]+)-\d+", link or "")
    return pricing.quote(m.group(1)) if m else None


async def api_quote(request):
    body = await request.json()
    link = body.get("link", "")
    if not S.parse_nft_link(link):
        return err("Havola noto'g'ri. Misol: https://t.me/nft/PlushPepe-1234")
    q = link_quote(link)
    if not q:
        return err("Bu kolleksiya narxi hozircha topilmadi — narxni o'zingiz yozing, admin ko'rib chiqadi")
    return ok(**q, buy_pct=pricing.BUY_PCT)


async def a_quote(request):
    q = link_quote(request.query.get("link", ""))
    return ok(**q) if q else err("Bozor narxi topilmadi")


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
    q = link_quote(p["link"])
    market = (f"📊 Bozor (floor): {som(q['floor_uzs'])} ({q['floor_gram']} GRAM, {q['date']})\n"
              f"🤖 Avto-taklif ({pricing.BUY_PCT:g}%): {som(q['offer_uzs'])}\n") if q else "📊 Bozor narxi topilmadi\n"
    await S.notify_admins(
        bot, f"📥 <b>Sotish arizasi #{gid}</b>\n🎁 {S.gname(p)}\n🔗 {p['link']}\n💰 So'ralgan narx: {som(price)}\n{market}"
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


async def game_page(request):
    return web.FileResponse(WEB / "game.html", headers={"Cache-Control": "no-cache"})


async def game_asset(request):
    name = request.match_info["name"]
    cache = "public, max-age=2592000" if name == "three.min.js" else "no-cache"
    return web.FileResponse(WEB / name, headers={"Cache-Control": cache})


async def on_vip(user, until):
    await S.notify_admins(bot, f"👑 <b>Yangi VIP obuna</b> (Shahar Arena)\n"
                               f"👤 @{user.get('username') or '-'} <code>{user['id']}</code>\n"
                               f"💰 {som(GAME_VIP_PRICE)} · {time.strftime('%d.%m.%Y', time.localtime(until))} gacha")
    await S.send(bot, user["id"], f"👑 VIP faollashtirildi! {time.strftime('%d.%m.%Y', time.localtime(until))} gacha "
                                  f"×2 tanga, +15% kuch va oltin superkar sizniki. Omad! 🎮")


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


async def admin_auto(request):
    ts, sig = request.query.get("ts", ""), request.query.get("sig", "")
    good = ts.isdigit() and abs(time.time() - int(ts)) < 600 and hmac.compare_digest(
        hmac.new(ADMIN_TOKEN.encode(), ts.encode(), hashlib.sha256).hexdigest()[:32], sig)
    if not good:
        return web.Response(text="Havola eskirgan. Botga /admin yozib yangisini oling.",
                            content_type="text/plain", charset="utf-8")
    r = web.HTTPFound("/admin")
    r.set_cookie("adm", ADMIN_TOKEN, max_age=30 * 86400, httponly=True, samesite="Lax", secure=True)
    raise r


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


MEDIA_DIR = Path(DATA_DIR) / "media"
IMG_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


def save_media(data: bytes, ext: str) -> str:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex[:16] + ext
    (MEDIA_DIR / name).write_bytes(data)
    return f"/media/{name}"


async def resolve_image(url: str, link: str = "") -> str:
    """Rasm maydonini to'g'rilaydi: bo'sh -> NFT rasmi; t.me post -> rasmini yuklab saqlaydi."""
    url = (url or "").strip()
    if not url or "t.me/nft/" in url:
        p = S.parse_nft_link(url or link)
        return p["image"] if p else url
    if url.startswith("/media/"):
        return url
    try:
        async with ClientSession(timeout=ClientTimeout(total=15), headers={"User-Agent": "Mozilla/5.0"}) as s:
            m = re.match(r"https?://t\.me/(s/)?([A-Za-z0-9_]+)/(\d+)", url)
            if m:  # Telegram kanal posti -> undagi rasmni topamiz
                async with s.get(f"https://t.me/{m.group(2)}/{m.group(3)}?embed=1&mode=tme") as r:
                    html = await r.text()
                found = (re.search(r"tgme_widget_message_photo_wrap[^>]*background-image:url\('([^']+)'\)", html)
                         or re.search(r'<meta property="og:image" content="([^"]+)"', html))
                if not found:
                    raise ValueError("postda rasm topilmadi")
                url = found.group(1)
            async with s.get(url) as r:
                ct = r.headers.get("Content-Type", "").split(";")[0]
                if ct in IMG_TYPES:
                    return save_media(await r.read(), IMG_TYPES[ct])
    except Exception as e:
        logging.warning("rasm olinmadi %s: %s", url, e)
    return url


async def a_upload(request):
    """Admin telefondan rasm yuklaydi."""
    reader = await request.multipart()
    part = await reader.next()
    if not part or part.name != "file":
        return err("Fayl topilmadi")
    ct = (part.headers.get("Content-Type") or "").split(";")[0]
    ext = IMG_TYPES.get(ct) or (Path(part.filename or "").suffix.lower() if Path(part.filename or "").suffix.lower() in IMG_TYPES.values() else None)
    if not ext:
        return err("Faqat rasm yuklash mumkin (jpg, png, webp)")
    data = await part.read(decode=False)
    if len(data) > 8 * 1024 * 1024:
        return err("Rasm 8 MB dan katta")
    return ok(url=save_media(bytes(data), ext))


async def guide_video(request):
    return web.FileResponse(WEB / "ijara_qollanma.mp4", headers={"Cache-Control": "public, max-age=86400"})


async def media(request):
    name = request.match_info["name"]
    path = MEDIA_DIR / name
    if "/" in name or ".." in name or not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "public, max-age=31536000"})


async def a_gift_save(request):
    body = await request.json()
    gid = int(request.match_info.get("id", 0))
    f = {k: body[k] for k in db.GIFT_FIELDS if k in body}
    for k in ("price", "rent_price", "deposit", "for_sale", "for_rent"):
        if k in f:
            f[k] = int(f[k] or 0)
    if "image" in f or not gid:
        f["image"] = await resolve_image(f.get("image", ""), body.get("link", ""))
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


# ═══════════════════════ ZAXIRA NUSXA ═══════════════════════

BACKUP_DIR = Path(DATA_DIR) / "backups"
BACKUP_CHAT = [int(x) for x in os.environ.get("BACKUP_CHAT_ID", "").replace(" ", "").split(",") if x.lstrip("-").isdigit()]
REQUIRED_TABLES = {"users", "gifts", "orders", "topups"}


def make_backup() -> Path:
    """Ishlayotgan bazaning izchil nusxasi (sqlite backup API)."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKUP_DIR / time.strftime("giftbozor_%Y-%m-%d_%H-%M.db")
    src, dst = sqlite3.connect(DB_PATH), sqlite3.connect(path)
    with dst:
        src.backup(dst)
    src.close(); dst.close()
    for old in sorted(BACKUP_DIR.glob("giftbozor_*.db"))[:-48]:  # oxirgi 48 tasi saqlanadi
        old.unlink(missing_ok=True)
    return path


async def send_backup(chats=None, silent=True):
    path = make_backup()
    s = db.stats()
    cap = (f"💾 <b>Zaxira nusxa</b> · {time.strftime('%d.%m.%Y %H:%M')}\n"
           f"👥 {s['users']} · 👛 balanslar {som(s['balances'])} · 🔑 ijarada {s['rented']}\n"
           f"Tiklash: shu faylga javob (reply) qilib /restore yozing.")
    for chat in chats or BACKUP_CHAT or list(ADMIN_IDS):
        try:
            await bot.send_document(chat, FSInputFile(path), caption=cap, disable_notification=silent)
        except Exception as e:
            logging.warning("backup -> %s: %s", chat, e)


async def backup_loop():
    await asyncio.sleep(120)
    while True:
        try:
            await send_backup()
        except Exception as e:
            logging.exception("backup: %s", e)
        await asyncio.sleep(3600)


@dp.message(Command("backup"))
async def backup_cmd(m: Message):
    if is_admin(m.from_user.id):
        await send_backup([m.chat.id], silent=False)


@dp.message(Command("restore"))
async def restore_cmd(m: Message):
    if not is_admin(m.from_user.id):
        return
    doc = m.reply_to_message.document if m.reply_to_message else None
    if not doc or not (doc.file_name or "").endswith(".db"):
        return await m.answer("Zaxira (.db) faylga <b>javob (reply)</b> qilib /restore yozing.")
    tmp = Path(DATA_DIR) / "restore_tmp.db"
    await bot.download(doc, destination=tmp)
    try:
        c = sqlite3.connect(tmp)
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        c.close()
        if not REQUIRED_TABLES <= tables:
            raise ValueError("bu bot bazasi emas")
    except Exception as e:
        tmp.unlink(missing_ok=True)
        return await m.answer(f"❌ Fayl yaroqsiz: {e}")
    safety = make_backup()  # tiklashdan oldingi holat ham saqlanadi
    src, dst = sqlite3.connect(tmp), sqlite3.connect(DB_PATH)
    with dst:
        src.backup(dst)
    src.close(); dst.close(); tmp.unlink(missing_ok=True)
    db.init()
    await m.answer(f"✅ Baza tiklandi. Oldingi holat ham saqlandi: <code>{safety.name}</code>")


async def a_backup(request):
    path = make_backup()
    return web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{path.name}"'})


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
    r.add_get("/game", game_page)
    r.add_get("/{name:three\\.min\\.js|city3d\\.js}", game_asset)
    game.setup(r, auth, ok, err, on_vip, verify=check_init_data)
    r.add_get("/api/config", api_config)
    r.add_get("/api/gifts", api_gifts)
    r.add_get("/api/top", api_top)
    r.add_post("/api/me", api_me)
    r.add_post("/api/buy", api_buy)
    r.add_post("/api/rent", api_rent)
    r.add_post("/api/link", api_link)
    r.add_post("/api/topup", api_topup)
    r.add_post("/api/sell", api_sell)
    r.add_post("/api/quote", api_quote)
    r.add_get("/admin/api/quote", a_quote)
    r.add_get("/admin", admin_page)
    r.add_post("/admin/login", admin_login)
    r.add_get("/admin/auto", admin_auto)
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
    r.add_get("/admin/api/backup", a_backup)
    r.add_post("/admin/api/upload", a_upload)
    r.add_get("/media/{name}", media)
    r.add_get("/ijara_qollanma.mp4", guide_video)
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
    try:
        await bot.set_my_commands([BotCommand(command="start", description="Bozorni ochish"),
                                   BotCommand(command="oyin", description="🎮 Shahar Arena o'yini"),
                                   BotCommand(command="balans", description="Balansim"),
                                   BotCommand(command="qollanma", description="Ijara bo'yicha video qo'llanma")])
    except Exception as e:
        logging.warning("commands: %s", e)
    asyncio.create_task(ticker())
    asyncio.create_task(backup_loop())
    asyncio.create_task(pricing.loop())
    if not os.path.ismount("/data") and str(DATA_DIR).startswith("/data"):
        await S.notify_admins(bot, "⚠️ <b>Diqqat:</b> Railway'da <code>/data</code> volume ulanmagan! "
                                   "Har yangilanishda ma'lumotlar o'chadi. Volume qo'shing (Mount path: /data).")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
