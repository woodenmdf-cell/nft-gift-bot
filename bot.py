"""Shahar Arena — Telegram o'yin boti: Mini App (3D o'yin), balans to'ldirish va admin panel."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import (BotCommand, CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup,
                           MenuButtonWebApp, Message, WebAppInfo)

import db
import game
import props
import services as S
from config import (DATA_DIR, DB_PATH, ADMIN_IDS, ADMIN_PASSWORD, BOT_TOKEN, CARD_NUMBER, CARD_OWNER, CASHBACK,
                    GAME_VIP_DAYS, GAME_VIP_PRICE, HOST, MIN_TOPUP, PORT, WEBAPP_URL)

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


PLACEHOLDER_CARDS = {"", "8600 0000 0000 0000", "8600 1234 5678 9012"}


def card():
    """To'lov kartasi: avval bazadagi sozlama (/karta buyrug'i yoki admin panel), keyin Railway Variables."""
    num = (db.get_setting("card_number") or CARD_NUMBER or "").strip()
    owner = (db.get_setting("card_owner") or CARD_OWNER or "").strip()
    if num in PLACEHOLDER_CARDS or len(re.sub(r"\D", "", num)) < 16:
        return None, None
    return num, owner


def fmt_card(digits):
    return " ".join(digits[i:i + 4] for i in range(0, len(digits), 4))


def game_kb(text="🎮 O'ynash"):
    if not WEBAPP_URL.startswith("https://"):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, web_app=WebAppInfo(url=WEBAPP_URL))]])


# ═══════════════════════ BOT ═══════════════════════

@dp.message(CommandStart())
async def start(m: Message):
    db.upsert_user(m.from_user.id, m.from_user.username, m.from_user.full_name)
    await m.answer(
        f"Assalomu alaykum, <b>{m.from_user.first_name}</b>! 👋\n\n"
        "🎮 <b>Shahar Arena</b> — 3D ochiq shahar o'yini\n\n"
        "🛴 Elektr skuterda boshlang, tanga yig'ib Samarqand GT gacha mashina sotib oling\n🏢 Binolar sotib oling — har soatda daromad keltiradi\n"
        "🚓 Politsiyadan qoching, 🏁 do'stlaringiz bilan onlayn poyga qiling\n"
        "🧍 Personaj tanlang, 🛠 mashina va yaxshilashlar sotib oling\n\n"
        "O'yin <b>bepul</b>. 👑 <b>VIP</b> (ixtiyoriy, "
        f"{som(GAME_VIP_PRICE)} / {GAME_VIP_DAYS} kun): ×2 tanga, +15% kuch, oltin superkar va VIP kiyimlar.\n\n"
        "Pastdagi tugmani bosing 👇", reply_markup=game_kb())
    if is_admin(m.from_user.id):
        await m.answer("👮 Siz adminsiz. Admin panel uchun /admin yozing.")


@dp.message(Command("oyin", "game", "play"))
async def game_cmd(m: Message):
    db.upsert_user(m.from_user.id, m.from_user.username, m.from_user.full_name)
    await m.answer("🎮 O'yinni ochish uchun pastdagi tugmani bosing 👇", reply_markup=game_kb())


@dp.message(Command("balans", "balance"))
async def balance_cmd(m: Message):
    await m.answer(f"💰 Balansingiz: <b>{som(db.balance(m.from_user.id))}</b>\n"
                   "To'ldirish: o'yin → 🪙 Tanga → 💳 Balansni to'ldirish", reply_markup=game_kb())


def admin_login_url():
    ts = str(int(time.time()))
    sig = hmac.new(ADMIN_TOKEN.encode(), ts.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{WEBAPP_URL}/admin/auto?ts={ts}&sig={sig}"


@dp.message(Command("admin"))
async def admin_cmd(m: Message):
    if not is_admin(m.from_user.id):
        return
    s = db.stats()
    await m.answer(
        "👮 <b>Admin panel</b> — pastdagi tugmani bosing (havola 10 daqiqa amal qiladi, "
        "brauzer sizni 30 kun eslab qoladi).\n\n"
        f"👥 Foydalanuvchilar: {s['users']} · 🎮 O'yinchilar: {s['players']}\n"
        f"👑 Faol VIP: {s['vip_active']} · 💳 Chek tekshiruvi: {s['topups_checking']}\n"
        f"💰 O'yin daromadi: {som(s['game_revenue'])}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="👮 Admin panelga kirish", url=admin_login_url())]]))


@dp.message(Command("karta", "card"))
async def card_cmd(m: Message):
    """Admin: to'lov kartasini o'rnatish — /karta 8600 1234 5678 9012 Ism Familiya"""
    if not is_admin(m.from_user.id):
        return
    arg = (m.text or "").split(maxsplit=1)[1] if len((m.text or "").split(maxsplit=1)) > 1 else ""
    mt = re.match(r"^\s*([\d\s-]{16,23})\s+(.+)$", arg)
    digits = re.sub(r"\D", "", mt.group(1)) if mt else ""
    if not mt or len(digits) != 16:
        num, owner = card()
        return await m.answer("💳 To'lov kartasini o'rnatish:\n<code>/karta 8600 1234 5678 9012 Ism Familiya</code>\n\n"
                              + (f"Hozirgi karta: <code>{num}</code> — {owner}" if num else "⚠️ Hozir karta sozlanmagan."))
    db.set_setting("card_number", fmt_card(digits))
    db.set_setting("card_owner", mt.group(2).strip()[:60])
    num, owner = card()
    try:
        await m.delete()                                   # karta raqami chatda qolmasin
    except Exception:
        pass
    await m.answer(f"✅ To'lov kartasi o'rnatildi:\n💳 <code>{num}</code>\n👤 {owner}\n\n"
                   f"Endi o'yinchilar «💳 Balans» orqali (eng kami {som(MIN_TOPUP)}) to'ldira oladi, cheklar sizga keladi.")


@dp.message(F.photo | F.document)
async def receipt(m: Message):
    """Balans to'ldirish cheki."""
    t = db.waiting_topup(m.from_user.id)
    if not t:
        return await m.answer("Avval o'yinda <b>🪙 Tanga → 💳 Balansni to'ldirish</b> ni bosib, summani kiriting.",
                              reply_markup=game_kb())
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
    await m.answer("O'yinni ochish uchun pastdagi tugmani bosing 👇", reply_markup=game_kb())


@dp.callback_query(F.data.startswith("t:"))
async def admin_cb(c: CallbackQuery):
    if not is_admin(c.from_user.id):
        return await c.answer("Ruxsat yo'q", show_alert=True)
    _, action, tid = c.data.split(":")
    good, msg = await (S.confirm_topup(bot, int(tid)) if action == "ok" else S.reject_topup(bot, int(tid)))
    if good:
        try:
            await c.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await c.answer(msg, show_alert=not good)


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
    num, owner = card()
    return web.json_response({"cashback": CASHBACK, "min_topup": MIN_TOPUP, "card": num or "", "card_owner": owner or ""})


async def api_topup(request):
    user, body = await auth(request)
    amount = int(body.get("amount") or 0)
    if amount < MIN_TOPUP:
        return err(f"Eng kam summa: {som(MIN_TOPUP)}")
    num, owner = card()
    if not num:
        await S.notify_admins(bot, "⚠️ Kimdir balans to'ldirmoqchi, lekin to'lov kartasi sozlanmagan!\n"
                                   "Botga yozing: <code>/karta 8600 1234 5678 9012 Ism Familiya</code>")
        return err("To'lov vaqtincha ishlamayapti — admin kartani sozlamoqda. Birozdan keyin urinib ko'ring.")
    tid = db.create_topup(user["id"], amount)
    await S.send(bot, user["id"],
                 f"💳 <b>Balansni to'ldirish #{tid}</b>\n\n"
                 f"💰 Summa: <b>{som(amount)}</b>\n"
                 f"💳 Karta: <code>{num}</code>\n👤 {owner}\n\n"
                 f"To'lovdan so'ng <b>chek skrinshotini</b> shu yerga yuboring."
                 + (f"\n🎁 Cashback: +{som(amount * CASHBACK / 100)}" if CASHBACK else ""))
    return ok(id=tid)


async def game_page(request):
    return web.FileResponse(WEB / "game.html", headers={"Cache-Control": "no-cache"})


async def game_asset(request):
    name = request.match_info["name"]
    cache = "public, max-age=2592000" if name in ("three.min.js", "gltf.js") else "no-cache"
    return web.FileResponse(WEB / name, headers={"Cache-Control": cache})


async def on_coins(user, price, coins):
    await S.notify_admins(bot, f"🪙 <b>Tanga xaridi</b>\n👤 @{user.get('username') or '-'} <code>{user['id']}</code>\n"
                               f"💰 {som(price)} → {coins} tanga")


async def on_vip(user, until):
    await S.notify_admins(bot, f"👑 <b>Yangi VIP obuna</b>\n"
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


def storage_info():
    """Baza doimiy diskda (Railway volume) turibdimi."""
    persistent = os.path.ismount("/data") if str(DATA_DIR).startswith("/data") else True
    try:
        size = os.path.getsize(DB_PATH)
    except OSError:
        size = 0
    backups = sorted(BACKUP_DIR.glob("*.db"), key=lambda p: p.stat().st_mtime) if BACKUP_DIR.exists() else []
    return {"persistent": persistent, "db_path": str(DB_PATH), "db_size": size,
            "last_backup": int(backups[-1].stat().st_mtime) if backups else 0, "backups": len(backups)}


async def a_stats(request):
    day = int(time.time()) - int(time.time()) % 86400 - 5 * 3600     # bugun 00:00 (Toshkent, UTC+5)
    if day + 86400 <= time.time():
        day += 86400
    return web.json_response({**db.stats(), "today": db.ledger_summary(day), "storage": storage_info()})


async def a_settings(request):
    if request.method == "POST":
        body = await request.json()
        digits = re.sub(r"\D", "", str(body.get("card_number") or ""))
        if len(digits) != 16:
            return err("Karta raqami 16 ta raqamdan iborat bo'lishi kerak")
        db.set_setting("card_number", fmt_card(digits))
        db.set_setting("card_owner", str(body.get("card_owner") or "").strip()[:60])
    num, owner = card()
    return ok(card_number=num or "", card_owner=owner or "", min_topup=MIN_TOPUP, cashback=CASHBACK)


async def a_ledger(request):
    uid = int(request.match_info["id"])
    p = db.game_profile(uid)
    return web.json_response({"coins": p["coins"], "rows": db.game_ledger(uid, 300)})


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


async def a_coins(request):
    uid = int(request.match_info["id"])
    delta = int((await request.json()).get("delta") or 0)
    if not delta:
        return err("Sonni kiriting")
    db.game_profile(uid)
    db.game_add(uid, coins=delta, kind="admin", note="admin panel")
    await S.send(bot, uid, f"🪙 Tanga hisobingiz {delta:+} ga o'zgartirildi.")
    return ok(msg="Bajarildi")


async def a_broadcast(request):
    text = ((await request.json()).get("text") or "").strip()
    if not text:
        return err("Matn bo'sh")

    async def run():
        sent = 0
        for uid in db.all_user_ids():
            if await S.send(bot, uid, text, reply_markup=game_kb()):
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
REQUIRED_TABLES = {"users", "topups"}


def make_backup() -> Path:
    """Ishlayotgan bazaning izchil nusxasi (sqlite backup API)."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKUP_DIR / time.strftime("shahar_%Y-%m-%d_%H-%M.db")
    src, dst = sqlite3.connect(DB_PATH), sqlite3.connect(path)
    with dst:
        src.backup(dst)
    src.close(); dst.close()
    for old in sorted(BACKUP_DIR.glob("*_20*.db"), key=lambda p: p.stat().st_mtime)[:-48]:  # oxirgi 48 tasi saqlanadi
        old.unlink(missing_ok=True)
    return path


async def send_backup(chats=None, silent=True):
    path = make_backup()
    s = db.stats()
    cap = (f"💾 <b>Zaxira nusxa</b> · {time.strftime('%d.%m.%Y %H:%M')}\n"
           f"👥 {s['users']} · 🎮 {s['players']} · 👛 balanslar {som(s['balances'])}\n"
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
    r.add_get("/", game_page)
    r.add_get("/game", game_page)
    r.add_get("/health", health)
    r.add_get("/{name:three\\.min\\.js|city3d\\.js|gltf\\.js}", game_asset)
    r.add_static("/assets", WEB / "assets")
    game.setup(r, auth, ok, err, on_vip, verify=check_init_data, on_coins=on_coins)
    props.setup(r, auth, ok, err, notify=lambda uid, text: S.send(bot, uid, text, reply_markup=game_kb("🏢 O'yinni ochish")))
    r.add_get("/api/config", api_config)
    r.add_post("/api/topup", api_topup)
    r.add_get("/admin", admin_page)
    r.add_post("/admin/login", admin_login)
    r.add_get("/admin/auto", admin_auto)
    r.add_post("/admin/logout", admin_logout)
    r.add_get("/admin/api/stats", a_stats)
    r.add_get("/admin/api/topups", a_topups)
    r.add_post("/admin/api/topups/{id:\\d+}/{act}", a_topup_action)
    r.add_get("/admin/api/users", a_users)
    r.add_post("/admin/api/users/{id:\\d+}/ban", a_ban)
    r.add_post("/admin/api/users/{id:\\d+}/balance", a_balance)
    r.add_post("/admin/api/users/{id:\\d+}/coins", a_coins)
    r.add_get("/admin/api/users/{id:\\d+}/ledger", a_ledger)
    r.add_get("/admin/api/settings", a_settings)
    r.add_post("/admin/api/settings", a_settings)
    r.add_post("/admin/api/broadcast", a_broadcast)
    r.add_get("/admin/api/file/{fid}", a_file)
    r.add_get("/admin/api/backup", a_backup)
    return app


async def main():
    db.init()
    runner = web.AppRunner(make_app())
    await runner.setup()
    await web.TCPSite(runner, HOST, PORT).start()
    logging.info("Server: %s:%s | O'yin: %s | Admin: %s/admin", HOST, PORT, WEBAPP_URL, WEBAPP_URL)
    logging.info("Adminlar: %s", ADMIN_IDS or "YO'Q — ADMIN_IDS ni tekshiring")
    if not WEBAPP_URL:
        logging.error("Mini App manzili yo'q: Railway → Settings → Networking → Generate Domain bosing "
                      "yoki Variables'ga WEBAPP_URL=https://domeningiz qo'ying. Tugmalar chiqmaydi!")
    if WEBAPP_URL.startswith("https://"):
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="🎮 O'ynash", web_app=WebAppInfo(url=WEBAPP_URL)))
    try:
        num, _ = card()
        if not num:
            await S.notify_admins(bot, "⚠️ To'lov kartasi sozlanmagan — o'yinchilar balans to'ldira olmaydi.\n"
                                       "Botga yozing: <code>/karta 8600 1234 5678 9012 Ism Familiya</code>")
        await bot.set_my_commands([BotCommand(command="start", description="🎮 O'yinni ochish"),
                                   BotCommand(command="balans", description="💰 Balansim")])
    except Exception as e:
        logging.warning("commands: %s", e)
    asyncio.create_task(ticker())
    asyncio.create_task(backup_loop())
    if not os.path.ismount("/data") and str(DATA_DIR).startswith("/data"):
        await S.notify_admins(bot, "⚠️ <b>Diqqat:</b> Railway'da <code>/data</code> volume ulanmagan! "
                                   "Har yangilanishda ma'lumotlar o'chadi. Volume qo'shing (Mount path: /data).")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
