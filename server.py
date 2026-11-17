"""Shar Yutar — shared-arena game server + Telegram bot, standard library only.

One process does everything:
  * HTTP: serves public/index.html (the Telegram Mini App) and /health
  * WebSocket /ws: every player is in one arena; the server owns mass, tokens, stars and KIL
  * Telegram Bot API (long polling): /start button, Stars invoices, withdraw requests to the admin
  * SQLite in DATA_DIR (mount a Railway volume at /data so accounts survive redeploys)

Environment: BOT_TOKEN (required in production), ADMIN_ID (optional; otherwise the first
user to send /admin becomes admin), PUBLIC_URL (optional; RAILWAY_PUBLIC_DOMAIN is used),
DATA_DIR, PORT, DEV=1 (local testing: accepts {"dev_uid": n} instead of Telegram initData).
"""
import asyncio
import base64
import hashlib
import hmac
import html as htmlmod
import json
import logging
import math
import os
import random
import re
import secrets
import sqlite3
import struct
import time
import urllib.parse
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("shar")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_ENV = os.environ.get("ADMIN_ID", "").strip()
PORT = int(os.environ.get("PORT", "8080"))
DEV = os.environ.get("DEV") == "1"
DATA_DIR = os.environ.get("DATA_DIR") or ("/data" if os.path.isdir("/data") else os.path.dirname(os.path.abspath(__file__)))
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
if not PUBLIC_URL and os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
    PUBLIC_URL = "https://" + os.environ["RAILWAY_PUBLIC_DOMAIN"]
HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- game rules
S = 130.0
FOOD_N = 1800             # keeps the old food density
MAX_M = 8000.0            # 80K tokens
BANK_STEP = 50000         # whole 50K chunks of a round go to the account
TOKEN_GOAL = 1000000      # every 1M account tokens -> 100 stars (same rate: 10K tokens = 1 star)
GOAL_STARS = 100
WITHDRAW_MIN = 50        # smallest withdraw request in stars
SPEED_COST = 1000         # round tokens for 30 s of 2x speed
KILL_COST = ANTI_COST = REVIVE_COST = 10
KILL_TIME = 10.0
BOT_LIMIT = 50000         # a bot reaching this many tokens leaves the arena
TOTAL_PLAYERS = 18        # arena is topped up with bots to this many
MIN_BOTS = 6
TICK = 1 / 20
SKIN_PRICES = {"yashil": 0, "tarvuz": 15, "konfet": 15, "leopard": 20, "gulli": 25, "kamalak": 25,
               "muz": 30, "olov": 35, "lava": 45, "chaqmoq": 45, "galaktika": 50, "oltin": 75}
SKIN_NAMES = {"yashil": "Silliq yashil", "tarvuz": "Tarvuz", "konfet": "Konfet", "leopard": "Leopard",
              "gulli": "Gulli", "kamalak": "Kamalak", "muz": "Muz", "olov": "Olov", "lava": "Lava",
              "chaqmoq": "Chaqmoq", "galaktika": "Galaktika", "oltin": "Oltin"}
BOT_COLORS = ["#ffd21f", "#3f7bff", "#ff4d5e", "#2fd06a", "#b05cff", "#ff8a1f", "#1fd0d0", "#ff5cc8"]
BOT_NAMES = ["Sardor", "Jasur", "Malika", "Dilnoza", "ProGamer", "Shoxrux", "Aziza", "Bekzod", "NinjaUz",
             "Kamola", "Temur", "Lola", "Akmal", "Zarina", "Ulug'bek", "Nodir", "Madina", "Bobur", "Farrux",
             "Sevara", "Doston", "Xurshid", "Gulnoza", "Otabek", "King777", "Bahrom", "Javohir", "Sitora"]


EAT_RATIO = 1.01       # 1% bigger is enough to swallow
EAT_OVERLAP = 1.0      # swallowed the moment the balls touch (edge to edge)


def rad(m):
    return 0.45 * math.sqrt(m)


def speed_of(m):
    return 9 * (m / 10) ** -0.2


# ---------------------------------------------------------------- storage
db = sqlite3.connect(os.path.join(DATA_DIR, "shar.db"), check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE IF NOT EXISTS users(uid INTEGER PRIMARY KEY, name TEXT, username TEXT, tokens INTEGER DEFAULT 0,
  stars INTEGER DEFAULT 0, owned TEXT DEFAULT '["yashil"]', skin TEXT DEFAULT 'yashil', best INTEGER DEFAULT 0,
  created INTEGER);
CREATE TABLE IF NOT EXISTS reqs(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, stars INTEGER, status TEXT,
  created INTEGER, admin_chat INTEGER, admin_msg INTEGER);
CREATE TABLE IF NOT EXISTS payments(charge_id TEXT PRIMARY KEY, uid INTEGER, item TEXT, stars INTEGER, created INTEGER);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
""")
db.commit()
for col in ("ref INTEGER", "ref_earned INTEGER DEFAULT 0", "sub_bonus INTEGER DEFAULT 0", "rp INTEGER DEFAULT 0", "prefs TEXT"):
    try:
        db.execute(f"ALTER TABLE users ADD COLUMN {col}")
    except sqlite3.OperationalError:
        pass                                       # column already there
try:
    db.execute("ALTER TABLE reqs ADD COLUMN gift TEXT")
except sqlite3.OperationalError:
    pass
db.executescript("""
CREATE TABLE IF NOT EXISTS ads(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, title TEXT, body TEXT, url TEXT,
  photo TEXT, views_bought INTEGER DEFAULT 0, views INTEGER DEFAULT 0, clicks INTEGER DEFAULT 0, status TEXT,
  stars INTEGER DEFAULT 0, charge TEXT, reason TEXT, created INTEGER, started INTEGER, finished INTEGER);
CREATE TABLE IF NOT EXISTS ad_seen(ad INTEGER, uid INTEGER, clicked INTEGER DEFAULT 0, PRIMARY KEY(ad, uid));
CREATE TABLE IF NOT EXISTS advertisers(uid INTEGER PRIMARY KEY, phone TEXT, name TEXT, username TEXT, created INTEGER);
""")
db.commit()
# payouts are Telegram gifts (no plain Stars any more): id -> (title, price in ⭐, emoji Telegram uses for it)
PAY_GIFTS = {"tort": ("Tort", 50, "🎂"), "raketa": ("Raketa", 50, "🚀"),
             "kubok": ("Kubok", 100, "🏆"), "uzuk": ("Uzuk", 100, "💍")}


def gift_label(g, stars=0):
    if g in PAY_GIFTS:
        t, _, e = PAY_GIFTS[g]
        return f"{e} {t}"
    return f"{stars} ⭐"
db.commit()
CHANNEL = os.environ.get("CHANNEL", "@VIZUAL_OTZIF").strip()   # channel with the live pinned leaderboard
SUB_BONUS = 20000                                 # tokens for subscribing to the channel (once)
REF_PCT = 10                                       # inviter gets 10% of every 50K a friend banks
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")


def setting(k, default=None):
    r = db.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def set_setting(k, v):
    db.execute("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)", (k, str(v)))
    db.commit()


def admin_id():
    return int(ADMIN_ENV) if ADMIN_ENV.isdigit() else (int(setting("admin")) if setting("admin") else None)


# ---------------------------------------------------------------- ranks (PUBG style)
# (name, RP needed per division); every tier has 5 divisions: 5 -> 1
RANK_TIERS = [("Bronza", 60), ("Kumush", 80), ("Oltin", 100), ("Platina", 120),
              ("Olmos", 150), ("As", 180), ("As Master", 220)]
RANK_DIVS = 5
RANK_EMOJI = ["🥉", "🥈", "🥇", "💠", "💎", "👑", "🔥"]


def tier_start(t):
    return sum(c * RANK_DIVS for _, c in RANK_TIERS[:t])


def rank_info(rp):
    rp = max(0, int(rp))
    left = rp
    for t, (name, cost) in enumerate(RANK_TIERS):
        for d in range(RANK_DIVS):
            last = t == len(RANK_TIERS) - 1 and d == RANK_DIVS - 1
            if left < cost or last:
                return {"rp": rp, "tier": t, "div": RANK_DIVS - d, "name": f"{name} {RANK_DIVS - d}",
                        "into": left if not last else min(left, cost), "need": cost, "max": last and left >= cost}
            left -= cost


def round_rp(p, tier):
    """RP for one finished round: playing, score, players eaten, best place."""
    secs = time.monotonic() - p.t0
    score = max(p.peak, p.round_bank + int(p.m * 10))
    parts = []
    if secs < 20:                                   # instant leave: nothing either way
        return 0, [["Juda qisqa o'yin", 0]]
    parts.append(["O'yin", 3])
    if score >= 2000:
        parts.append([f"Ochko {score // 1000}K", min(40, score // 2000)])
    if p.eaten:
        parts.append([f"Yutilgan o'yinchi ×{p.eaten}", min(30, p.eaten * 6)])
    pl = p.best_place
    if pl == 1:
        parts.append(["TOP-1 ga chiqdingiz", 25])
    elif pl <= 3:
        parts.append([f"TOP-{pl} ga chiqdingiz", 15])
    elif pl <= 10:
        parts.append([f"TOP-10 ichida", 6])
    total = sum(v for _, v in parts)
    # high ranks have to earn it: a weak round costs points (never drops a whole tier)
    if tier >= 5 and score < 3000:
        parts, total = [["Kuchsiz o'yin", -8]], -8
    elif tier >= 4 and score < 1500:
        parts, total = [["Kuchsiz o'yin", -4]], -4
    return total, parts


class Account:
    """A player's persistent wallet. Guests (no Telegram login) live only in memory."""
    cache = {}

    def __init__(self, uid, name, username=""):
        self.uid = uid
        self.name = name
        if uid is None:
            self.tokens, self.stars, self.owned, self.skin, self.best = 0, 0, ["yashil"], "yashil", 0
            self.ref, self.ref_earned, self.sub_bonus = None, 0, 0
            self.rp = 0
            self.prefs = ""
            return
        r = db.execute("SELECT * FROM users WHERE uid=?", (uid,)).fetchone()
        if not r:
            self.name = name or str(uid)
            db.execute("INSERT INTO users(uid,name,username,created) VALUES(?,?,?,?)", (uid, self.name, username, int(time.time())))
            db.commit()
            r = db.execute("SELECT * FROM users WHERE uid=?", (uid,)).fetchone()
        elif name and name != str(uid):                 # only a real login updates the name
            db.execute("UPDATE users SET name=?, username=? WHERE uid=?", (name, username or r["username"], uid))
        else:
            self.name = r["name"] or name                 # internal lookups keep the stored name
        self.tokens, self.stars, self.best = r["tokens"], r["stars"], r["best"]
        self.ref, self.ref_earned = r["ref"], r["ref_earned"] or 0
        self.sub_bonus = r["sub_bonus"] or 0
        self.rp = r["rp"] or 0
        self.prefs = r["prefs"] or ""
        self.owned = [s for s in json.loads(r["owned"] or "[]") if s in SKIN_PRICES] or ["yashil"]
        if "yashil" not in self.owned:
            self.owned.insert(0, "yashil")
        self.skin = r["skin"] if r["skin"] in self.owned else "yashil"

    @classmethod
    def get(cls, uid, name="", username=""):
        if uid is None:
            return cls(None, name)
        a = cls.cache.get(uid)
        if not a:
            a = cls.cache[uid] = cls(uid, name, username)
        elif name:
            a.name = name
        return a

    def save(self):
        if self.uid is None:
            return
        db.execute("UPDATE users SET tokens=?, stars=?, owned=?, skin=?, best=?, name=?, ref_earned=?, sub_bonus=?, rp=? WHERE uid=?",
                   (self.tokens, self.stars, json.dumps(self.owned), self.skin, self.best, self.name, self.ref_earned, self.sub_bonus, self.rp, self.uid))
        db.commit()

    def add_tokens(self, n):
        """Returns how many stars were credited by crossing TOKEN_GOAL."""
        self.tokens += n
        conv = 0
        while self.tokens >= TOKEN_GOAL:
            self.tokens -= TOKEN_GOAL
            self.stars += GOAL_STARS
            conv += GOAL_STARS
        self.save()
        return conv

    def reqs(self):
        if self.uid is None:
            return []
        rows = db.execute("SELECT stars, status, created, gift FROM reqs WHERE uid=? ORDER BY id DESC LIMIT 10", (self.uid,))
        return [{"stars": r["stars"], "gift": gift_label(r["gift"], r["stars"]), "status": STATUS.get(r["status"], r["status"]), "date": time.strftime("%d.%m.%Y", time.localtime(r["created"]))} for r in rows]

    def finish_round(self, p):
        """Adds the round's RP and returns what the client animates."""
        old = rank_info(self.rp)
        delta, parts = round_rp(p, old["tier"])
        self.rp = max(tier_start(old["tier"]), self.rp + delta)
        self.save()
        return {"old": old, "new": rank_info(self.rp), "delta": self.rp - old["rp"], "parts": parts}

    def ref_count(self):
        if self.uid is None:
            return 0
        return db.execute("SELECT COUNT(*) c FROM users WHERE ref=?", (self.uid,)).fetchone()["c"]

    def ref_link(self):
        if self.uid is None or not BOT_USERNAME:
            return ""
        return f"https://t.me/{BOT_USERNAME}?start=ref_{self.uid}"

    def public(self):
        return {"t": "acc", "tokens": self.tokens, "stars": self.stars, "owned": self.owned, "skin": self.skin,
                "best": self.best, "rank": rank_info(self.rp), "prefs": self.prefs, "reqs": self.reqs(), "guest": self.uid is None, "name": self.name, "wmin": WITHDRAW_MIN, "bot": BOT_USERNAME, "gifts": [{"id": k, "title": v[0], "price": v[1], "emoji": v[2]} for k, v in PAY_GIFTS.items()], "goal": TOKEN_GOAL, "goal_stars": GOAL_STARS,
                "ref": {"link": self.ref_link(), "count": self.ref_count(), "earned": self.ref_earned, "pct": REF_PCT},
                "sub": {"claimed": bool(self.sub_bonus), "bonus": SUB_BONUS,
                        "link": f"https://t.me/{CHANNEL.lstrip('@')}" if CHANNEL.startswith("@") else ""}}


STATUS = {"pending": "⏳ Kutilmoqda", "sent": "✅ Yuborildi", "rejected": "❌ Rad etildi"}

# ---------------------------------------------------------------- Telegram Bot API


def tg_call(method, **params):
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")
    req = urllib.request.Request(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
                                 data=json.dumps(params).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        out = json.loads(r.read())
    if not out.get("ok"):
        raise RuntimeError(f"{method}: {out}")
    return out["result"]


async def tg(method, **params):
    try:
        return await asyncio.to_thread(tg_call, method, **params)
    except Exception as e:                       # never let a Telegram hiccup break the game
        log.warning("telegram %s failed: %s", method, str(e).replace(BOT_TOKEN, "***") if BOT_TOKEN else e)
        return None


def check_init_data(init_data):
    """Validates Telegram Mini App initData; returns the user dict or None."""
    if not BOT_TOKEN or not init_data:
        return None
    try:
        pairs = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        got = pairs.pop("hash", "")
        dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, got):
            return None
        if time.time() - int(pairs.get("auth_date", "0")) > 86400:
            return None
        return json.loads(pairs["user"])
    except Exception:
        return None


def play_keyboard():
    if not PUBLIC_URL:
        return None
    return {"inline_keyboard": [[{"text": "🎮 O'ynash", "web_app": {"url": PUBLIC_URL}}],
                                [{"text": "🏆 Rank TOP", "web_app": {"url": PUBLIC_URL + "/?tops=1"}},
                                 {"text": "👁 Kuzatish", "web_app": {"url": PUBLIC_URL + "/?watch=1"}}]]}


async def bot_loop():
    if not BOT_TOKEN:
        log.warning("BOT_TOKEN not set: Telegram bot is off")
        return
    global BOT_USERNAME
    me = await tg("getMe")
    if me and me.get("username"):
        BOT_USERNAME = me["username"]
    log.info("bot @%s started, web app: %s", me and me.get("username"), PUBLIC_URL or "(no PUBLIC_URL yet)")
    await tg("setMyCommands", commands=[{"command": "start", "description": "O'yinni ochish"},
                                        {"command": "top", "description": "🏆 Rank TOP"},
                                        {"command": "reklama", "description": "📢 Reklama berish"},
                                        {"command": "reklamalarim", "description": "📊 Reklamalarim statistikasi"},
                                        {"command": "ref", "description": "Do'stlarni taklif qilish"},
                                        {"command": "admin", "description": "Admin panel"}])
    if PUBLIC_URL:
        await tg("setChatMenuButton", menu_button={"type": "web_app", "text": "O'ynash", "web_app": {"url": PUBLIC_URL}})
    offset = 0
    while True:
        ups = await tg("getUpdates", offset=offset, timeout=25,
                       allowed_updates=["message", "callback_query", "pre_checkout_query"])
        if ups is None:
            await asyncio.sleep(3)
            continue
        for u in ups:
            offset = u["update_id"] + 1
            try:
                await handle_update(u)
            except Exception:
                log.exception("update failed")


async def handle_update(u):
    if "pre_checkout_query" in u:
        q = u["pre_checkout_query"]
        ok = q.get("currency") == "XTR" and q.get("invoice_payload", "").count("|") == 2
        await tg("answerPreCheckoutQuery", pre_checkout_query_id=q["id"], ok=ok,
                 **({} if ok else {"error_message": "Xato to'lov"}))
        return
    if "callback_query" in u:
        await handle_callback(u["callback_query"])
        return
    m = u.get("message")
    if not m:
        return
    chat, frm = m["chat"]["id"], m.get("from", {})
    if "successful_payment" in m:
        await handle_payment(frm["id"], m["successful_payment"])
        return
    text = (m.get("text") or "").strip()
    if await ad_dialog(m, chat, frm, text):          # advertiser is in the middle of creating an ad
        return
    if text.startswith("/start"):
        arg = text.split(maxsplit=1)[1] if " " in text else ""
        if arg.startswith("ref_") and arg[4:].isdigit():
            await register_ref(frm, int(arg[4:]))
        if arg == "reklama":
            return await ad_start(chat, frm)
        await tg("sendMessage", chat_id=chat, reply_markup=play_keyboard(),
                 text="🎮 <b>Shar Yutar</b>\n\nDonachalarni ye, kattalash, kichiklarni yut!\n"
                      "• Har 50K token hisobingizga o'tadi\n• Har 1M token = 100 ⭐\n• ⭐ larni 🎂🚀🏆💍 Telegram sovg'alariga almashtiring\n"
                      "• 🎯 KIL bilan TOP-3 dagilarning tokenini oling\n"
                      f"• 📢 Kanalimiz {CHANNEL}: obuna bo'lsangiz +{SUB_BONUS // 1000}K token 🎁\n\nBoshlash uchun pastdagi tugmani bosing 👇",
                 parse_mode="HTML")
    elif text.startswith("/reklamalarim"):
        await ad_my_stats(chat, frm["id"])
    elif text.startswith("/reklama"):
        await ad_start(chat, frm)
    elif text.startswith("/top"):
        lines = ["🏆 <b>Rank TOP</b>\n"]
        for ti, (name, _) in enumerate(RANK_TIERS[::-1]):
            ti = len(RANK_TIERS) - 1 - ti
            lo, hi = tier_start(ti), tier_start(ti + 1) if ti + 1 < len(RANK_TIERS) else 10 ** 9
            rows = db.execute("SELECT name, rp FROM users WHERE rp>=? AND rp<? AND rp>0 ORDER BY rp DESC LIMIT 3", (lo, hi)).fetchall()
            if rows:
                lines.append(f"{RANK_EMOJI[ti]} <b>{name}</b>")
                lines += [f"   {i + 1}. {htmlmod.escape((r['name'] or 'O`yinchi')[:16])} — {rank_info(r['rp'])['name']} · {r['rp']} RP" for i, r in enumerate(rows)]
        if len(lines) == 1:
            lines.append("Hali hech kim rank olmagan. Birinchi bo'ling! 💪")
        kb = {"inline_keyboard": [[{"text": "🏆 To'liq TOP", "web_app": {"url": PUBLIC_URL + "/?tops=1"}}]]} if PUBLIC_URL else None
        await tg("sendMessage", chat_id=chat, text="\n".join(lines), parse_mode="HTML", reply_markup=kb)
    elif text.startswith("/ref"):
        acc = Account.get(frm["id"], frm.get("first_name", ""), frm.get("username", ""))
        await tg("sendMessage", chat_id=chat, disable_web_page_preview=True,
                 text=f"👥 <b>Do'stlarni taklif qiling</b>\n\nDo'stingiz o'yinda har 50K token yig'ganda, "
                      f"sizga +{BANK_STEP * REF_PCT // 100 // 1000}K token tushadi ({REF_PCT}%).\n\n"
                      f"🔗 Sizning havolangiz:\n{acc.ref_link()}\n\n"
                      f"👤 Taklif qilinganlar: {acc.ref_count()}\n💰 Topilgan: {fmt(acc.ref_earned)} token",
                 parse_mode="HTML",
                 reply_markup={"inline_keyboard": [[{"text": "📤 Do'stlarga yuborish",
                                                     "url": "https://t.me/share/url?" + urllib.parse.urlencode(
                                                         {"url": acc.ref_link(), "text": "Shar Yutar o'ynaymiz! Sharlar jangi va Telegram yulduzlari 🎮⭐"})}]]})
    elif text.startswith("/admin"):
        adm = admin_id()
        if adm is None:
            set_setting("admin", frm["id"])
            await tg("sendMessage", chat_id=chat, text="✅ Siz admin bo'ldingiz. Yulduz so'rovlari shu yerga keladi.\n/admin — statistika va admin panel")
        elif adm == frm["id"]:
            users = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
            pend = db.execute("SELECT COUNT(*) c, COALESCE(SUM(stars),0) s FROM reqs WHERE status='pending'").fetchone()
            paid = db.execute("SELECT COALESCE(SUM(stars),0) s FROM payments").fetchone()["s"]
            refs = db.execute("SELECT COUNT(*) c FROM users WHERE ref IS NOT NULL").fetchone()["c"]
            online = sum(1 for c in conns if c.player and c.player.alive)
            kb = {"inline_keyboard": [[{"text": "📊 Admin panel", "web_app": {"url": PUBLIC_URL + "/admin"}}]]} if PUBLIC_URL else None
            await tg("sendMessage", chat_id=chat, reply_markup=kb,
                     text=f"📊 O'yinchilar: {users}\n🟢 Hozir o'ynayapti: {online}\n"
                          f"⏳ Kutilayotgan so'rovlar: {pend['c']} ta ({pend['s']} ⭐)\n💰 Jami Stars to'lovlari: {paid} ⭐\n👥 Taklif orqali kelganlar: {refs}")
        else:
            await tg("sendMessage", chat_id=chat, text="Bu buyruq faqat admin uchun.")


async def register_ref(frm, inviter):
    """Only brand-new players can be invited, and nobody can invite themselves."""
    uid = frm["id"]
    if inviter == uid or db.execute("SELECT 1 FROM users WHERE uid=?", (uid,)).fetchone():
        return
    if not db.execute("SELECT 1 FROM users WHERE uid=?", (inviter,)).fetchone():
        return
    db.execute("INSERT INTO users(uid,name,username,created,ref) VALUES(?,?,?,?,?)",
               (uid, frm.get("first_name", "") or str(uid), frm.get("username", ""), int(time.time()), inviter))
    db.commit()
    name = frm.get("first_name") or "Yangi o'yinchi"
    await tg("sendMessage", chat_id=inviter,
             text=f"🎉 {name} sizning havolangiz orqali o'yinga qo'shildi!\n"
                  f"U har 50K token yig'ganda sizga +{BANK_STEP * REF_PCT // 100 // 1000}K token tushadi.")
    inv = Account.cache.get(inviter)
    if inv:
        push_acc(inv)


async def post_payout_proof(acc, stars, gift=None):
    """Real payouts are the best advert: announce each one in the channel."""
    if not CHANNEL:
        return
    total = db.execute("SELECT COALESCE(SUM(stars),0) FROM reqs WHERE status='sent'").fetchone()[0]
    name = html(acc.name if acc.name and acc.name != str(acc.uid) else "O'yinchi")
    await tg("sendMessage", chat_id=CHANNEL, parse_mode="HTML",
             text=f"✅ <b>TO'LOV ISBOTI</b>\n\n👤 {name} o'ynab <b>{gift_label(gift, stars)}</b> Telegram sovg'asini yutib oldi!\n"
                  f"💫 Jami berilgan sovg'alar: {total} ⭐\n\n🎮 Siz ham o'ynang va yutib oling 👇",
             reply_markup={"inline_keyboard": [[{"text": "🎮 O'ynash", "url": f"https://t.me/{BOT_USERNAME}?start=kanal"}]]})


async def bot_send_gift(rid):
    """Sends the requested gift from the bot's own Star balance. Returns (ok, message)."""
    r = db.execute("SELECT * FROM reqs WHERE id=?", (rid,)).fetchone()
    if not r or r["status"] != "pending":
        return False, "So'rov allaqachon ko'rib chiqilgan"
    if r["gift"] not in PAY_GIFTS:
        return False, "Bu eski yulduz so'rovi — qo'lda yuboring"
    title, price, emoji = PAY_GIFTS[r["gift"]]
    gifts = await tg("getAvailableGifts")
    pick = None
    for g in (gifts or {}).get("gifts", []):
        if g.get("star_count") == price and (g.get("sticker") or {}).get("emoji") == emoji:
            pick = g
            break
    if not pick:
        return False, f"{emoji} {title} sovg'asi Telegram ro'yxatida topilmadi — qo'lda yuboring"
    res = await tg("sendGift", user_id=r["uid"], gift_id=pick["id"], text="Shar Yutar o'yinidan sovg'a 🎮")
    if res is None:
        return False, "Bot sovg'ani yubora olmadi (botda ⭐ yetmasligi mumkin) — qo'lda yuboring"
    await resolve_request(rid, True)
    return True, f"🤖 {emoji} {title} bot orqali yuborildi"


async def resolve_request(rid, ok):
    """Marks a withdraw request sent or rejected (rejected stars go back). Returns a note or None."""
    r = db.execute("SELECT * FROM reqs WHERE id=?", (rid,)).fetchone()
    if not r or r["status"] != "pending":
        return None
    acc = Account.get(r["uid"])
    if ok:
        db.execute("UPDATE reqs SET status='sent' WHERE id=?", (rid,))
        lbl = gift_label(r["gift"], r["stars"])
        note, user_msg = "✅ Yuborildi", f"✅ {lbl} sovg'asi sizga yuborildi! Telegram profilingizni tekshiring 🎁\nO'ynashda davom eting 🎮"
        asyncio.create_task(post_payout_proof(acc, r["stars"], r["gift"]))
    else:
        db.execute("UPDATE reqs SET status='rejected' WHERE id=?", (rid,))
        acc.stars += r["stars"]
        acc.save()
        note, user_msg = "❌ Rad etildi (⭐ balansga qaytarildi)", f"❌ {gift_label(r['gift'], r['stars'])} so'rovingiz rad etildi, {r['stars']} ⭐ balansingizga qaytarildi."
    db.commit()
    if r["admin_chat"] and r["admin_msg"]:
        await tg("editMessageReplyMarkup", chat_id=r["admin_chat"], message_id=r["admin_msg"], reply_markup={"inline_keyboard": []})
        await tg("sendMessage", chat_id=r["admin_chat"], reply_to_message_id=r["admin_msg"], text=f"#{rid}: {note}")
    await tg("sendMessage", chat_id=r["uid"], text=user_msg)
    push_acc(acc)
    return note


async def handle_callback(q):
    data, frm = q.get("data", ""), q.get("from", {})
    if data.startswith("adpkg:"):
        await ad_choose_package(q, frm)
        return
    if data.startswith("adnew:"):
        await tg("answerCallbackQuery", callback_query_id=q["id"])
        await ad_start(frm["id"], frm)
        return
    if frm.get("id") != admin_id() or ":" not in data:
        await tg("answerCallbackQuery", callback_query_id=q["id"], text="Faqat admin")
        return
    action, rid = data.split(":", 1)
    if action in ("adok", "adno"):
        msg = await ad_review(int(rid), action == "adok")
        await tg("answerCallbackQuery", callback_query_id=q["id"], text=msg)
        return
    if action == "bot":
        okk, msg = await bot_send_gift(int(rid))
        await tg("answerCallbackQuery", callback_query_id=q["id"], text=msg, show_alert=not okk)
        return
    note = await resolve_request(int(rid), action == "ok")
    await tg("answerCallbackQuery", callback_query_id=q["id"], text=note or "Allaqachon ko'rib chiqilgan")


async def handle_payment(uid, sp):
    charge = sp.get("telegram_payment_charge_id", "")
    try:
        item, puid, _ = sp["invoice_payload"].split("|")
        puid = int(puid)
    except Exception:
        log.warning("bad payload %s", sp)
        return
    if db.execute("SELECT 1 FROM payments WHERE charge_id=?", (charge,)).fetchone():
        return                                   # already applied
    db.execute("INSERT INTO payments VALUES(?,?,?,?,?)", (charge, puid, item, sp.get("total_amount", 0), int(time.time())))
    db.commit()
    if item.startswith("ad:"):
        await ad_paid(int(item[3:]), puid, charge, sp.get("total_amount", 0))
        return
    acc = Account.get(puid)
    conn = next((c for c in conns if c.acc is acc), None)
    if item.startswith("skin:"):
        sid = item[5:]
        if sid in SKIN_PRICES and sid not in acc.owned:
            acc.owned.append(sid)
        acc.skin = sid
        acc.save()
        if conn:
            conn.toast(f"🎨 {SKIN_NAMES.get(sid, sid)} sizniki!")
            if conn.player:
                conn.player.skin = sid
                game.meta_dirty = True
    elif item == "anti":
        if not (conn and game.resolve_anti(conn.player)):
            acc.stars += ANTI_COST               # paid too late: keep the stars on the balance
            acc.save()
            if conn:
                conn.toast(f"KIL tugagan edi — {ANTI_COST} ⭐ balansingizga qo'shildi")
    elif item == "revive":
        if not (conn and game.revive(conn)):
            acc.stars += REVIVE_COST
            acc.save()
            if conn:
                conn.toast(f"{REVIVE_COST} ⭐ balansingizga qo'shildi")
    push_acc(acc)


def push_acc(acc):
    for c in conns:
        if c.acc is acc:
            c.send(acc.public())


async def notify_admin_request(rid, acc, stars, gift=None):
    adm = admin_id()
    if not adm:
        log.warning("withdraw request %s but no admin set (send /admin to the bot)", rid)
        return
    who = acc.name
    r = db.execute("SELECT username FROM users WHERE uid=?", (acc.uid,)).fetchone()
    if r and r["username"]:
        who += f" (@{r['username']})"
    sent = await tg("sendMessage", chat_id=adm,
             text=f"🎁 Sovg'a so'rovi #{rid}\n👤 {who}\n🆔 {acc.uid}\n🎁 {gift_label(gift, stars)} ({stars} ⭐)\n\n"
                  f"Shu sovg'ani o'yinchiga yuboring, keyin «Yuborildi»ni bosing.\n"
                  f"«🤖 Bot yuborsin» — sovg'ani bot o'z ⭐ balansidan avtomatik yuboradi.",
             reply_markup={"inline_keyboard": [[{"text": "🤖 Bot yuborsin", "callback_data": f"bot:{rid}"}],
                                               [{"text": "✅ Yuborildi", "callback_data": f"ok:{rid}"},
                                                {"text": "❌ Rad etish", "callback_data": f"no:{rid}"}]]})
    if sent:
        db.execute("UPDATE reqs SET admin_chat=?, admin_msg=? WHERE id=?", (adm, sent["message_id"], rid))
        db.commit()


# ---------------------------------------------------------------- self-service advertising
# Advertisers create a banner in the bot, the bot checks it against the advertising law, they pay in Stars,
# the banner is shown in the game and they can follow views / clicks live with /reklamalarim.
AD_PACKAGES = [(1000, 50), (5000, 200), (20000, 700)]        # (views, ⭐)
AD_SEEN_GAP = 1800                                          # one person counts as a new view at most every 30 min
AD_FORBIDDEN = [
    (r"kazino|casino|казино|slot|слот|jackpot|джекпот|ruletka|рулетк|poker|покер", "qimor (kazino) reklamasi taqiqlangan — «Reklama to'g'risida»gi qonun, 46-modda"),
    (r"stavka|ставк|\bbet\b|1xbet|melbet|mostbet|pin-?up|bukmek|букмек|tikish|tikib|прогноз на матч|ekspress\b", "stavka / bukmeker reklamasi taqiqlangan (46-modda)"),
    (r"lotereya|лотере|lotto|лото\b", "lotereya reklamasi faqat litsenziya bilan mumkin"),
    (r"kripto|crypto|крипт|bitcoin|биткоин|\busdt\b|\bton\b|airdrop|mining|майнинг|nft\b", "kripto-aktivlar reklamasi cheklangan"),
    (r"aroq|araq|vino\b|pivo|alkogol|алкогол|водк|пиво|вино\b|виски|konyak|коньяк|shampan", "alkogol reklamasi taqiqlangan"),
    (r"sigaret|сигарет|tamaki|табак|vape|вейп|elektron sigaret|nos\b|кальян|kalyan|iqos", "tamaki / vape reklamasi taqiqlangan"),
    (r"dori\b|dorilar|tabletka|таблетк|лекарств|kapsula|biologik faol|бад\b|ozdirish|похуде", "dori va BFQ reklamasi alohida ruxsat talab qiladi"),
    (r"kredit|кредит|qarz|займ|zaym|mikroqarz|nasiya|рассрочк|investitsiya|инвестиц|daromad kafolat|tez boyi|pul ishlash|заработ", "moliyaviy xizmatlar reklamasi litsenziya talab qiladi"),
    (r"porno|порно|seks|секс|intim|интим|18\+|eskort|эскорт", "axloqsiz reklama taqiqlangan"),
    (r"\$|dollar|доллар|\busd\b|€|euro\b|евро|rubl|рубл|₽", "narx faqat so'mda ko'rsatilishi kerak (16-modda)"),
    (r"qurol|оружи|pichoq sotiladi|narkot|нарко|giyoh", "taqiqlangan mahsulot"),
]
AD_UZ_MARKERS = re.compile(r"o['ʻ‘’`]|g['ʻ‘’`]|ў|ғ|қ|ҳ|\b(va|uchun|bilan|bor|yangi|eng|sizga|siz|biz|bizning|chegirma|buyurtma|bepul|"
                           r"qiling|bo['ʻ‘’`]ling|kanal|obuna|endi|hozir|faqat|sotuv|narx|so['ʻ‘’`]m|ва|учун|билан|янги|энг|сизга|ҳозир|нарх|сўм)\b", re.I)
AD_UZ_SUFFIX = re.compile(r"\b[a-z]{2,}(lar|larga|larni|larda|ga|da|dan|ni|ning|miz|imiz|ingiz|siz|lik|chi|moqda|yapmiz|yapti|ing|ish|gan|ib)\b", re.I)
AD_RU = re.compile(r"[ыщ]|\b(и|в|на|для|это|как|все|только|наш|ваш|купить|скидка|бесплатно|заказ|подпишись|подписывайтесь|лучший|новый|новые|канал|сейчас)\b", re.I)
AD_EN = re.compile(r"\b(the|and|for|your|our|now|free|get|buy|best|new|with|join|subscribe|sale|off|only|today)\b", re.I)


def ad_is_uzbek(text):
    """Uzbek (Latin or Cyrillic, with or without apostrophes) passes; clearly Russian or English text does not."""
    words = re.findall(r"[^\W\d_]+", text)
    if not words:
        return False
    uz = len(AD_UZ_MARKERS.findall(text)) + len(AD_UZ_SUFFIX.findall(text))
    foreign = len(AD_RU.findall(text)) + len(AD_EN.findall(text))
    return uz >= 1 and uz >= foreign * 0.5


ad_drafts = {}               # uid -> {"step":..., ...} while an ad is being written in the bot
ad_shown = {}                # (ad, uid) -> last time it counted as a view


def ad_check(title, body, url):
    """Automatic law check. Returns a list of problems (empty = fine)."""
    text = f"{title}\n{body}\n{url}".lower()
    probs = [why for rx, why in AD_FORBIDDEN if re.search(rx, text)]
    if not ad_is_uzbek(f"{title} {body}"):
        probs.append("reklama davlat tilida (o'zbek tilida) bo'lishi shart — «Reklama to'g'risida»gi qonun, 6-modda")
    if not re.match(r"^(https://[\w.-]+\.[a-z]{2,}(/\S*)?|https?://t\.me/\S+|t\.me/\S+|@\w{4,})$", url.strip(), re.I):
        probs.append("havola noto'g'ri: https://... , t.me/... yoki @username bo'lsin")
    return list(dict.fromkeys(probs))


def ad_norm_url(u):
    u = u.strip()
    if u.startswith("@"):
        return "https://t.me/" + u[1:]
    if u.startswith("t.me/"):
        return "https://" + u
    return u


def ad_trusted(uid):
    """Advertisers with an earlier approved ad go live right after the automatic check."""
    return db.execute("SELECT 1 FROM ads WHERE uid=? AND status IN ('active','done')", (uid,)).fetchone() is not None


async def ad_start(chat, frm):
    uid = frm["id"]
    adv = db.execute("SELECT * FROM advertisers WHERE uid=?", (uid,)).fetchone()
    if not adv:
        ad_drafts[uid] = {"step": "phone"}
        await tg("sendMessage", chat_id=chat, parse_mode="HTML",
                 text="📢 <b>Shar Yutar'da reklama</b>\n\nReklamangiz o'yin menyusida va o'yin tugaganda banner bo'lib chiqadi. "
                      "Necha kishi ko'rgani va bosgani /reklamalarim da doim ko'rinadi.\n\n"
                      "🔐 Ishonchli reklama beruvchi bo'lish uchun avval telefon raqamingizni tasdiqlang 👇",
                 reply_markup={"keyboard": [[{"text": "📱 Raqamni yuborish", "request_contact": True}]],
                               "resize_keyboard": True, "one_time_keyboard": True})
        return
    ad_drafts[uid] = {"step": "title"}
    await tg("sendMessage", chat_id=chat, parse_mode="HTML",
             text="✍️ <b>1/4. Sarlavha</b> (40 belgigacha, o'zbek tilida)\n\nMasalan: <i>Yangi telefonlar — 20% chegirma!</i>\n\nBekor qilish: /bekor",
             reply_markup={"remove_keyboard": True})


async def ad_dialog(m, chat, frm, text):
    uid = frm.get("id")
    d = ad_drafts.get(uid)
    if not d:
        return False
    if text in ("/bekor", "/cancel"):
        ad_drafts.pop(uid, None)
        await tg("sendMessage", chat_id=chat, text="❌ Bekor qilindi.", reply_markup={"remove_keyboard": True})
        return True
    if text.startswith("/") and text not in ("/otkaz", "/o'tkaz"):
        ad_drafts.pop(uid, None)
        return False
    step = d["step"]
    if step == "phone":
        ct = m.get("contact")
        if not ct or ct.get("user_id") != uid:
            await tg("sendMessage", chat_id=chat, text="Iltimos, pastdagi «📱 Raqamni yuborish» tugmasini bosing (o'zingizning raqamingiz).")
            return True
        db.execute("INSERT OR REPLACE INTO advertisers VALUES(?,?,?,?,?)",
                   (uid, ct.get("phone_number", ""), frm.get("first_name", ""), frm.get("username", ""), int(time.time())))
        db.commit()
        await tg("sendMessage", chat_id=chat, text="✅ Raqam tasdiqlandi.", reply_markup={"remove_keyboard": True})
        await ad_start(chat, frm)
        return True
    if step == "title":
        if not 3 <= len(text) <= 40:
            await tg("sendMessage", chat_id=chat, text="Sarlavha 3–40 belgi bo'lsin. Qaytadan yozing:")
            return True
        d.update(title=text, step="body")
        await tg("sendMessage", chat_id=chat, parse_mode="HTML",
                 text="✍️ <b>2/4. Matn</b> (200 belgigacha, o'zbek tilida, narxlar faqat so'mda)")
        return True
    if step == "body":
        if not 5 <= len(text) <= 200:
            await tg("sendMessage", chat_id=chat, text="Matn 5–200 belgi bo'lsin. Qaytadan yozing:")
            return True
        d.update(body=text, step="url")
        await tg("sendMessage", chat_id=chat, parse_mode="HTML",
                 text="🔗 <b>3/4. Havola</b> — banner bosilganda qayerga o'tsin?\n<code>https://sayt.uz</code>, <code>t.me/kanal</code> yoki <code>@kanal</code>")
        return True
    if step == "url":
        d.update(url=text.strip(), step="photo")
        await tg("sendMessage", chat_id=chat, parse_mode="HTML",
                 text="🖼 <b>4/4. Rasm</b> — banner uchun rasm yuboring (ixtiyoriy).\nRasmsiz davom etish: /otkaz")
        return True
    if step == "photo":
        if m.get("photo"):
            d["photo"] = m["photo"][-1]["file_id"]
        elif text not in ("/otkaz", "/o'tkaz"):
            await tg("sendMessage", chat_id=chat, text="Rasm yuboring yoki /otkaz deb yozing.")
            return True
        probs = ad_check(d["title"], d["body"], d["url"])
        if probs:
            ad_drafts[uid] = {"step": "title"}
            await tg("sendMessage", chat_id=chat, parse_mode="HTML",
                     text="⚠️ <b>Reklama qonun talablariga to'g'ri kelmadi:</b>\n\n" + "\n".join("• " + html(p) for p in probs) +
                          "\n\nTuzatib, qaytadan boshlang. <b>1/4. Sarlavha</b>:")
            return True
        cur = db.execute("INSERT INTO ads(uid,title,body,url,photo,status,created) VALUES(?,?,?,?,?,?,?)",
                         (uid, d["title"], d["body"], ad_norm_url(d["url"]), d.get("photo"), "draft", int(time.time())))
        db.commit()
        ad_drafts.pop(uid, None)
        aid = cur.lastrowid
        prev = f"📢 <b>{html(d['title'])}</b>\n{html(d['body'])}\n🔗 {html(ad_norm_url(d['url']))}"
        await tg("sendMessage", chat_id=chat, parse_mode="HTML", disable_web_page_preview=True,
                 text="✅ <b>Avtomatik tekshiruvdan o'tdi!</b>\n\n" + prev + "\n\n👇 Necha marta ko'rsatilsin?",
                 reply_markup={"inline_keyboard": [[{"text": f"👁 {v:,} ko'rish — {st} ⭐".replace(",", " "), "callback_data": f"adpkg:{aid}:{i}"}]
                                                   for i, (v, st) in enumerate(AD_PACKAGES)]})
        return True
    return False


async def ad_choose_package(q, frm):
    try:
        _, aid, i = q["data"].split(":")
        aid, i = int(aid), int(i)
        views, stars = AD_PACKAGES[i]
    except (ValueError, IndexError):
        return await tg("answerCallbackQuery", callback_query_id=q["id"])
    ad = db.execute("SELECT * FROM ads WHERE id=? AND uid=?", (aid, frm.get("id"))).fetchone()
    if not ad or ad["status"] != "draft":
        return await tg("answerCallbackQuery", callback_query_id=q["id"], text="Bu reklama allaqachon to'langan")
    db.execute("UPDATE ads SET views_bought=?, stars=? WHERE id=?", (views, stars, aid))
    db.commit()
    await tg("answerCallbackQuery", callback_query_id=q["id"])
    await tg("sendInvoice", chat_id=frm["id"], title=f"Reklama: {views} ko'rish",
             description=f"«{ad['title'][:40]}» banneri Shar Yutar o'yinida {views} marta ko'rsatiladi",
             payload=f"ad:{aid}|{frm['id']}|{int(time.time())}", currency="XTR",
             prices=[{"label": f"{views} ko'rish", "amount": stars}])


async def ad_paid(aid, uid, charge, amount):
    ad = db.execute("SELECT * FROM ads WHERE id=?", (aid,)).fetchone()
    if not ad or ad["status"] != "draft":
        return
    trusted = ad_trusted(uid)
    status = "active" if trusted else "review"
    db.execute("UPDATE ads SET status=?, charge=?, stars=?, started=? WHERE id=?",
               (status, charge, amount, int(time.time()) if trusted else None, aid))
    db.commit()
    if trusted:
        await tg("sendMessage", chat_id=uid, text=f"✅ To'lov qabul qilindi. Reklama #{aid} hozirdan ko'rsatilmoqda!\n📊 Statistika: /reklamalarim")
    else:
        await tg("sendMessage", chat_id=uid, text=f"✅ To'lov qabul qilindi. Reklama #{aid} admin tasdig'iga yuborildi (birinchi reklama uchun).\n"
                                                    f"Rad etilsa, ⭐ to'liq qaytariladi. 📊 /reklamalarim")
    adm = admin_id()
    if adm:
        adv = db.execute("SELECT * FROM advertisers WHERE uid=?", (uid,)).fetchone()
        who = f"{html(adv['name'] or '')} {'@' + adv['username'] if adv and adv['username'] else ''} 📱 {adv['phone'] if adv else '?'}"
        txt = (f"📢 <b>Reklama #{aid}</b> {'(ishonchli — avtomatik yoqildi)' if trusted else '— tasdiqlang'}\n👤 {who}\n"
               f"💫 {amount} ⭐ · {ad['views_bought']} ko'rish\n\n<b>{html(ad['title'])}</b>\n{html(ad['body'])}\n🔗 {html(ad['url'])}")
        kb = {"inline_keyboard": [[{"text": "✅ Tasdiqlash", "callback_data": f"adok:{aid}"}, {"text": "❌ Rad (⭐ qaytadi)", "callback_data": f"adno:{aid}"}]]} \
            if not trusted else {"inline_keyboard": [[{"text": "⛔ To'xtatish (⭐ qaytadi)", "callback_data": f"adno:{aid}"}]]}
        if ad["photo"]:
            await tg("sendPhoto", chat_id=adm, photo=ad["photo"], caption=txt[:1000], parse_mode="HTML", reply_markup=kb)
        else:
            await tg("sendMessage", chat_id=adm, text=txt, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)


async def ad_review(aid, ok):
    ad = db.execute("SELECT * FROM ads WHERE id=?", (aid,)).fetchone()
    if not ad or ad["status"] not in ("review", "active"):
        return "Allaqachon ko'rib chiqilgan"
    if ok:
        if ad["status"] == "active":
            return "Allaqachon faol"
        db.execute("UPDATE ads SET status='active', started=? WHERE id=?", (int(time.time()), aid))
        db.commit()
        await tg("sendMessage", chat_id=ad["uid"], text=f"✅ Reklama #{aid} tasdiqlandi va ko'rsatilmoqda!\n📊 /reklamalarim")
        return "✅ Tasdiqlandi"
    # rejected or stopped: give back the stars for the views that were not shown
    left = max(0, ad["views_bought"] - ad["views"])
    back = ad["stars"] if ad["views"] == 0 else ad["stars"] * left // max(1, ad["views_bought"])
    refunded = False
    if back and ad["charge"] and back == ad["stars"]:
        refunded = await tg("refundStarPayment", user_id=ad["uid"], telegram_payment_charge_id=ad["charge"]) is not None
    db.execute("UPDATE ads SET status='rejected', finished=? WHERE id=?", (int(time.time()), aid))
    db.commit()
    note = f"{back} ⭐ qaytarildi" if refunded else (f"{back} ⭐ — admin qo'lda qaytaradi" if back else "")
    await tg("sendMessage", chat_id=ad["uid"], text=f"❌ Reklama #{aid} qonun yoki qoidalarga mos kelmagani uchun to'xtatildi. {note}")
    return "❌ Rad etildi. " + note


def ad_pick(uid):
    rows = db.execute("SELECT * FROM ads WHERE status='active' AND views < views_bought").fetchall()
    if not rows:
        return None
    now = time.time()
    # people see a banner they haven't just seen; the more views are left, the more often it is picked
    fresh = [r for r in rows if now - ad_shown.get((r["id"], uid), 0) > AD_SEEN_GAP] or rows
    ad = random.choices(fresh, weights=[r["views_bought"] - r["views"] for r in fresh])[0]
    if uid is not None and now - ad_shown.get((ad["id"], uid), 0) > AD_SEEN_GAP:
        ad_shown[(ad["id"], uid)] = now
        db.execute("UPDATE ads SET views=views+1 WHERE id=?", (ad["id"],))
        db.execute("INSERT OR IGNORE INTO ad_seen(ad, uid) VALUES(?,?)", (ad["id"], uid))
        if ad["views"] + 1 >= ad["views_bought"]:
            db.execute("UPDATE ads SET status='done', finished=? WHERE id=?", (int(now), ad["id"]))
            asyncio.get_event_loop().create_task(ad_finished(ad["id"]))
        db.commit()
    return ad


def ad_click(aid, uid):
    if not aid or uid is None:
        return
    r = db.execute("SELECT clicked FROM ad_seen WHERE ad=? AND uid=?", (aid, uid)).fetchone()
    if r and not r["clicked"]:                  # one click per person
        db.execute("UPDATE ad_seen SET clicked=1 WHERE ad=? AND uid=?", (aid, uid))
        db.execute("UPDATE ads SET clicks=clicks+1 WHERE id=?", (aid,))
        db.commit()


def ad_stats_text(ad):
    uniq = db.execute("SELECT COUNT(*) FROM ad_seen WHERE ad=?", (ad["id"],)).fetchone()[0]
    ctr = ad["clicks"] / ad["views"] * 100 if ad["views"] else 0
    st = {"draft": "📝 To'lov kutilmoqda", "review": "⏳ Admin tekshiruvida", "active": "🟢 Ko'rsatilmoqda",
          "done": "✅ Tugadi", "rejected": "❌ To'xtatilgan"}.get(ad["status"], ad["status"])
    bar = "▓" * int(10 * ad["views"] / max(1, ad["views_bought"])) + "░" * (10 - int(10 * ad["views"] / max(1, ad["views_bought"])))
    return (f"<b>#{ad['id']} · {html(ad['title'])}</b>\n{st}\n{bar} {ad['views']}/{ad['views_bought']}\n"
            f"👁 Ko'rishlar: <b>{ad['views']}</b> · 👤 Turli odamlar: <b>{uniq}</b>\n👆 Bosishlar: <b>{ad['clicks']}</b> · CTR {ctr:.1f}%")


async def ad_my_stats(chat, uid):
    rows = db.execute("SELECT * FROM ads WHERE uid=? AND status!='draft' ORDER BY id DESC LIMIT 10", (uid,)).fetchall()
    if not rows:
        return await tg("sendMessage", chat_id=chat, text="Sizda hali reklama yo'q. Boshlash: /reklama")
    await tg("sendMessage", chat_id=chat, parse_mode="HTML", text="📊 <b>Reklamalaringiz</b> (jonli)\n\n" + "\n\n".join(ad_stats_text(r) for r in rows),
             reply_markup={"inline_keyboard": [[{"text": "➕ Yangi reklama", "callback_data": "adnew:0"}]]})


async def ad_finished(aid):
    ad = db.execute("SELECT * FROM ads WHERE id=?", (aid,)).fetchone()
    if ad:
        await tg("sendMessage", chat_id=ad["uid"], parse_mode="HTML",
                 text="🏁 <b>Reklamangiz yakunlandi!</b>\n\n" + ad_stats_text(ad) + "\n\nYana reklama: /reklama")


AD_IMG = {}


async def ad_image(aid):
    hit = AD_IMG.get(aid)
    if hit:
        return hit
    ad = db.execute("SELECT photo FROM ads WHERE id=? AND status IN ('active','done','review')", (aid,)).fetchone()
    if not ad or not ad["photo"] or not BOT_TOKEN:
        return None
    def fetch(fid):
        f = tg_call("getFile", file_id=fid)
        with urllib.request.urlopen(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{f['file_path']}", timeout=20) as r:
            return r.read()
    try:
        img = await asyncio.to_thread(fetch, ad["photo"])
    except Exception:
        return None
    if len(AD_IMG) > 50:
        AD_IMG.clear()
    AD_IMG[aid] = img
    return img


# ---------------------------------------------------------------- the arena
class Player:
    _next = 1

    def __init__(self, name, skin, bot=False, conn=None, m=10.0):
        self.id = Player._next
        Player._next += 1
        self.name, self.skin, self.bot, self.conn = name, skin, bot, conn
        self.x = self.z = self.vx = self.vz = 0.0
        self.m = m
        self.alive = True
        self.dx = self.dz = 0.0
        self.k = 0.8
        self.think = 0.0
        self.speed_t = 0.0
        self.last_pos = time.monotonic()
        self.round_bank = 0
        self.respawn_at = 0.0
        self.t0 = time.monotonic()      # round stats for rank points
        self.peak = 0
        self.eaten = 0
        self.best_place = 99


class Game:
    CELL = 8.0

    def __init__(self):
        self.fx, self.fz, self.fbig, self.fc = [0.0] * FOOD_N, [0.0] * FOOD_N, [0] * FOOD_N, [0] * FOOD_N
        self.grid = {}
        self.fchanges = []
        for i in range(FOOD_N):
            self.place_food(i, initial=True)
        self.fchanges = []
        self.players = []
        self.kills = []             # pending KIL: dict(frm, tgt, end, anti_at)
        self.meta_dirty = True
        self.ticks = 0

    # food lives in a coarse grid so eating is cheap
    def cell(self, x, z):
        return int((x + S) // self.CELL), int((z + S) // self.CELL)

    def place_food(self, i, initial=False):
        if not initial:
            self.grid.get(self.cell(self.fx[i], self.fz[i]), set()).discard(i)
        self.fx[i], self.fz[i] = random.uniform(-S + 1, S - 1), random.uniform(-S + 1, S - 1)
        self.fbig[i] = 1 if random.random() < 0.04 else 0
        self.fc[i] = random.randrange(8)
        self.grid.setdefault(self.cell(self.fx[i], self.fz[i]), set()).add(i)
        self.fchanges.append([i, round(self.fx[i], 1), round(self.fz[i], 1), self.fbig[i], self.fc[i]])

    def food_snapshot(self):
        return [[round(self.fx[i], 1), round(self.fz[i], 1), self.fbig[i], self.fc[i]] for i in range(FOOD_N)]

    def alive(self):
        return [p for p in self.players if p.alive]

    def top3(self):
        return sorted(self.alive(), key=lambda p: -p.m)[:3]

    def safe_spot(self, r):
        for _ in range(40):
            x, z = random.uniform(-S + 10, S - 10), random.uniform(-S + 10, S - 10)
            if all(p.m < 15 or math.hypot(p.x - x, p.z - z) > rad(p.m) + r + 25 for p in self.alive()):
                return x, z
        return random.uniform(-S + 10, S - 10), random.uniform(-S + 10, S - 10)

    def new_bot(self):
        used = {p.name for p in self.players}
        name = random.choice([n for n in BOT_NAMES if n not in used] or ["Bot"])
        skin = random.choice(list(SKIN_PRICES)[1:]) if random.random() < 0.25 else random.choice(BOT_COLORS)
        b = Player(name, skin, bot=True, m=random.uniform(60, 260) if random.random() < 0.25 else random.uniform(10, 50))
        b.x, b.z = self.safe_spot(rad(b.m))
        self.players.append(b)
        self.meta_dirty = True

    def balance_bots(self):
        humans = sum(1 for p in self.players if not p.bot)
        want = max(MIN_BOTS, TOTAL_PLAYERS - humans)
        bots = [p for p in self.players if p.bot]
        if len(bots) < want:
            self.new_bot()
        elif len(bots) > want:
            extra = next((b for b in bots if not b.alive), None) or min(bots, key=lambda b: b.m)
            self.players.remove(extra)
            self.meta_dirty = True

    def spawn_human(self, conn):
        p = Player(conn.acc.name, conn.acc.skin, conn=conn)
        p.x, p.z = self.safe_spot(2)
        self.players.append(p)
        self.meta_dirty = True
        return p

    def remove(self, p):
        if p in self.players:
            self.players.remove(p)
        self.kills = [k for k in self.kills if k["tgt"] is not p and k["frm"] is not p]
        self.meta_dirty = True

    # --- movement
    def steer(self, p, dt):
        sp = speed_of(p.m) * p.k
        a = min(1.0, dt * 6)
        p.vx += (p.dx * sp - p.vx) * a
        p.vz += (p.dz * sp - p.vz) * a
        p.x += p.vx * dt
        p.z += p.vz * dt
        self.clamp(p)

    def clamp(self, p):
        lim = S - rad(p.m) * 0.6
        p.x = max(-lim, min(lim, p.x))
        p.z = max(-lim, min(lim, p.z))

    def human_pos(self, p, x, z):
        """Clients move their own blob; the server only accepts what the speed allows."""
        now = time.monotonic()
        dt = min(1.0, now - p.last_pos)
        p.last_pos = now
        # movement allowance builds up over time, so packets that arrive bunched together
        # on a shaky mobile network are not clipped (clipping made blobs jump back = "lag")
        v = speed_of(p.m) * (2 if p.speed_t > 0 else 1)
        p.mbudget = min(v * 1.5 + 3, getattr(p, "mbudget", v) + v * dt * 1.3)
        dx, dz = x - p.x, z - p.z
        d = math.hypot(dx, dz)
        corrected = False
        maxd = p.mbudget
        if d > maxd:
            dx, dz = dx / d * maxd, dz / d * maxd
            corrected = d > maxd + 6
        p.mbudget = max(0.0, p.mbudget - min(d, maxd))
        if dt > 0:
            p.vx, p.vz = dx / dt, dz / dt
        p.x += dx
        p.z += dz
        self.clamp(p)
        return corrected

    def bot_think(self, b):
        r = rad(b.m)
        flee = prey = None
        fd = pd = 1e9
        for o in self.players:
            if o is b or not o.alive:
                continue
            d = math.hypot(o.x - b.x, o.z - b.z)
            if o.m > b.m * EAT_RATIO and d < 12 + rad(o.m) * 2.2 and d < fd:
                flee, fd = o, d
            elif b.m > o.m * EAT_RATIO and d < 22 + r * 2 and d < pd:
                prey, pd = o, d
        if flee:
            dx, dz = b.x - flee.x, b.z - flee.z
            if abs(b.x) > S - 15:
                dx -= math.copysign(15, b.x)
            if abs(b.z) > S - 15:
                dz -= math.copysign(15, b.z)
            l = math.hypot(dx, dz) or 1
            b.dx, b.dz, b.k = dx / l, dz / l, 1.0
            return
        if prey and random.random() < 0.85:
            dx, dz = prey.x + prey.vx * 0.4 - b.x, prey.z + prey.vz * 0.4 - b.z
            l = math.hypot(dx, dz) or 1
            b.dx, b.dz, b.k = dx / l, dz / l, 1.0
            return
        cx, cz = self.cell(b.x, b.z)
        best, bd = None, 1e9
        for ring in range(4):
            for i in range(cx - ring, cx + ring + 1):
                for j in range(cz - ring, cz + ring + 1):
                    for f in self.grid.get((i, j), ()):
                        d = abs(self.fx[f] - b.x) + abs(self.fz[f] - b.z)
                        if d < bd:
                            best, bd = f, d
            if best is not None:
                break
        if best is not None:
            dx, dz = self.fx[best] - b.x, self.fz[best] - b.z
            l = math.hypot(dx, dz) or 1
            b.dx, b.dz = dx / l + random.uniform(-.25, .25), dz / l + random.uniform(-.25, .25)
        else:
            b.dx, b.dz = random.uniform(-1, 1), random.uniform(-1, 1)
        b.k = 0.8

    # --- one simulation step
    def step(self, dt):
        now = time.monotonic()
        for p in self.players:
            if p.bot:
                if not p.alive:
                    if now >= p.respawn_at:
                        used = {q.name for q in self.players if q is not p}
                        p.name = random.choice([n for n in BOT_NAMES if n not in used] or ["Bot"])
                        p.m = random.uniform(10, 50)
                        p.x, p.z = self.safe_spot(rad(p.m))
                        p.vx = p.vz = 0
                        p.alive = True
                        self.meta_dirty = True
                    continue
                p.think -= dt
                if p.think <= 0:
                    self.bot_think(p)
                    p.think = random.uniform(0.2, 0.4)
                self.steer(p, dt)
            elif p.speed_t > 0:
                p.speed_t = max(0.0, p.speed_t - dt)
        # food
        for p in self.players:
            if not p.alive:
                continue
            r = rad(p.m)
            c0x, c0z = self.cell(p.x - r, p.z - r)
            c1x, c1z = self.cell(p.x + r, p.z + r)
            for i in range(c0x, c1x + 1):
                for j in range(c0z, c1z + 1):
                    cellset = self.grid.get((i, j))
                    if not cellset:
                        continue
                    for f in list(cellset):
                        dx, dz = self.fx[f] - p.x, self.fz[f] - p.z
                        if dx * dx + dz * dz < r * r:
                            p.m = min(MAX_M, p.m + (5 if self.fbig[f] else 1))
                            self.place_food(f)
        # blobs touching: the bigger one swallows the smaller one whole
        alive = self.alive()
        for a in alive:
            if not a.alive:
                continue
            ra = rad(a.m)
            for b in alive:
                # the clearly bigger ball (10%+) swallows the smaller one as soon as they touch
                if a is b or not b.alive or a.m < b.m * EAT_RATIO - 1e-6:
                    continue
                if math.hypot(a.x - b.x, a.z - b.z) < ra + rad(b.m) * EAT_OVERLAP:
                    a.m = min(MAX_M, a.m + b.m)
                    if not b.bot:
                        a.eaten += 1
                    self.kill_blob(b, a)
        for p in self.players:
            if p.alive and p.m > 150:
                p.m -= p.m * 0.0015 * dt
            if p.bot and p.alive and p.m * 10 >= BOT_LIMIT:      # bots never outgrow real players
                p.alive = False
                p.respawn_at = now + 3
                for k in [k for k in self.kills if k["tgt"] is p]:
                    self.kills.remove(k)
                    if k["frm"].conn:
                        k["frm"].conn.send({"t": "killEnd", "msg": f"{p.name} maydondan chiqib ketdi"})
        for p in self.players:
            if p.alive and not p.bot:
                self.bank(p)
                p.peak = max(p.peak, p.round_bank + int(p.m * 10))
        if self.ticks % 10 == 0:
            for i, p in enumerate(sorted(self.alive(), key=lambda q: -q.m)):
                if not p.bot and i + 1 < p.best_place:
                    p.best_place = i + 1
        self.tick_kills(now)
        self.ticks += 1
        if self.ticks % 10 == 0:
            self.balance_bots()

    def kill_blob(self, b, by):
        b.alive = False
        for k in list(self.kills):
            if k["tgt"] is b:
                self.kills.remove(k)
                if k["frm"].conn:
                    k["frm"].conn.send({"t": "killEnd", "msg": f"{b.name} allaqachon yutildi"})
        if b.bot:
            b.respawn_at = time.monotonic() + 1.5
            return
        c = b.conn
        if c:
            c.death = {"m": b.m, "at": time.monotonic()}
            sc = b.round_bank + int(b.m * 10)
            if sc > c.acc.best:
                c.acc.best = sc
                c.acc.save()
            c.send({"t": "dead", "killer": by.name, "score": sc, "best": c.acc.best, "banked": b.round_bank,
                    "rank": c.acc.finish_round(b)})
            push_acc(c.acc)
        self.remove(b)
        if c:
            c.player = None

    def bank(self, p):  # noqa: E301
        while p.m * 10 >= BANK_STEP:
            p.m -= BANK_STEP / 10
            p.round_bank += BANK_STEP
            if p.round_bank > p.conn.acc.best:
                p.conn.acc.best = p.round_bank
            conv = p.conn.acc.add_tokens(BANK_STEP)
            pay_referrer(p.conn.acc, BANK_STEP)
            p.conn.toast("💰 50K token hisobingizga o'tdi!", fx="bank")
            if conv:
                p.conn.toast(f"🎉 1M token → {conv} ⭐ balansga tushdi!", fx="stars")
            push_acc(p.conn.acc)
        if p.m < 10:
            p.m = 10

    # --- KIL / ANTI-KIL
    def start_kill(self, p, target_id):
        c = p.conn
        if c.acc.uid is None and not DEV:
            return c.toast("KIL faqat Telegram orqali kirganda ishlaydi")
        if c.acc.stars < KILL_COST:
            return c.toast(f"KIL uchun balansda kamida {KILL_COST} ⭐ bo'lishi kerak")
        if p not in self.top3():
            return c.toast("KIL faqat TOP-3 ga chiqqaningizda ochiladi")
        if any(k["frm"] is p for k in self.kills):
            return c.toast("KIL allaqachon ishlayapti")
        t = next((q for q in self.players if q.id == target_id and q.alive), None)
        if not t or t is p or t not in self.top3():
            return c.toast("Faqat TOP-3 dagilarga KIL ishlatish mumkin")
        if any(k["tgt"] is t for k in self.kills):
            return c.toast("Bu o'yinchiga allaqachon KIL yuborilgan")
        c.acc.stars -= KILL_COST
        c.acc.save()
        push_acc(c.acc)
        anti_at = random.uniform(2, 8) if t.bot and random.random() < 0.35 else -1
        self.kills.append({"frm": p, "tgt": t, "end": time.monotonic() + KILL_TIME, "anti_at": time.monotonic() + anti_at if anti_at > 0 else -1})
        c.send({"t": "killOut", "to": t.name, "sec": KILL_TIME})
        if t.conn:
            t.conn.send({"t": "killIn", "from": p.name, "sec": KILL_TIME, "stars": t.conn.acc.stars})

    def resolve_anti(self, p):
        k = next((k for k in self.kills if p is not None and k["tgt"] is p), None)
        if not k:
            return False
        self.kills.remove(k)
        if k["frm"].conn:
            k["frm"].conn.send({"t": "killEnd", "msg": f"🛡 {p.name} Anti-Kil ishlatdi! {KILL_COST} ⭐ qaytarilmaydi"})
        if p.conn:
            p.conn.send({"t": "killEnd", "msg": f"🛡 Himoyalandingiz! {k['frm'].name}ning ⭐ lari qaytmaydi", "safe": True})
        return True

    def tick_kills(self, now):
        for k in list(self.kills):
            frm, tgt = k["frm"], k["tgt"]
            if k["anti_at"] > 0 and now >= k["anti_at"]:
                self.resolve_anti(tgt)
                continue
            if now < k["end"]:
                continue
            self.kills.remove(k)
            got = max(0.0, tgt.m - 10) if tgt.alive else 0.0
            tgt.m = 10.0
            if frm.alive and frm in self.players:
                frm.m += got
                if frm.conn:
                    frm.conn.send({"t": "killEnd", "msg": f"💀 KIL! {tgt.name}ning {fmt(got * 10)} tokeni sizniki", "gain": int(got * 10)})
            if tgt.conn:
                tgt.conn.send({"t": "killEnd", "msg": f"💀 {frm.name} tokenlaringizni olib ketdi", "lost": True})

    def revive(self, c):
        d = getattr(c, "death", None)
        if c.player or not d or time.monotonic() - d["at"] > 180:
            return False
        p = self.spawn_human(c)
        p.m = d["m"]
        p.x, p.z = self.safe_spot(rad(p.m))
        c.player = p
        c.death = None
        c.send({"t": "spawn", "id": p.id, "x": p.x, "z": p.z, "m": p.m})
        return True

    def state_msg(self):
        msg = {"t": "s", "p": [[p.id, round(p.x, 1), round(p.z, 1), round(p.m, 1), int(p.speed_t + 0.99)] for p in self.players if p.alive],
               "f": self.fchanges, "ts": int(time.monotonic() * 1000) % 100000000}   # server clock for smooth playback
        self.fchanges = []
        return json.dumps(msg, separators=(",", ":"))

    def meta_msg(self):
        return json.dumps({"t": "meta", "p": {p.id: [p.name, p.skin, 0 if p.bot else 1, (p.id * 7) % 5 if p.bot or not p.conn else rank_info(p.conn.acc.rp)["tier"]] for p in self.players}},
                          separators=(",", ":"), ensure_ascii=False)


def pay_referrer(acc, banked):
    if not acc.ref:
        return
    inv = Account.get(acc.ref)
    bonus = banked * REF_PCT // 100
    inv.ref_earned += bonus
    conv = inv.add_tokens(bonus)
    for c in conns:
        if c.acc is inv:
            c.toast(f"👥 {acc.name} 50K yig'di — sizga +{fmt(bonus)} token!")
            if conv:
                c.toast(f"🎉 1M token → {conv} ⭐ balansga tushdi!", fx="stars")
    push_acc(inv)


def fmt(n):
    return (f"{n / 1000:.0f}K" if n >= 10000 else f"{n / 1000:.1f}K") if n >= 1000 else str(int(n))


game = Game()
conns = set()

# ---------------------------------------------------------------- WebSocket plumbing (RFC 6455)
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def ws_frame(data, op=1):
    n = len(data)
    if n < 126:
        head = struct.pack("!BB", 0x80 | op, n)
    elif n < 65536:
        head = struct.pack("!BBH", 0x80 | op, 126, n)
    else:
        head = struct.pack("!BBQ", 0x80 | op, 127, n)
    return head + data


async def ws_read(reader):
    """Returns (opcode, payload) of one complete message."""
    buf, first_op = b"", None
    while True:
        b1, b2 = await reader.readexactly(2)
        op, ln = b1 & 0x0F, b2 & 0x7F
        if ln == 126:
            ln = struct.unpack("!H", await reader.readexactly(2))[0]
        elif ln == 127:
            ln = struct.unpack("!Q", await reader.readexactly(8))[0]
        if ln > 1 << 20:
            raise ConnectionError("frame too big")
        mask = await reader.readexactly(4) if b2 & 0x80 else b"\0\0\0\0"
        data = await reader.readexactly(ln)
        if b2 & 0x80:
            m = int.from_bytes((mask * (ln // 4 + 1))[:ln], "big") if ln else 0
            data = (int.from_bytes(data, "big") ^ m).to_bytes(ln, "big") if ln else b""
        if op >= 8:                                  # control frames may arrive between fragments
            return op, data
        if first_op is None:
            first_op = op
        buf += data
        if b1 & 0x80:
            return first_op, buf


class Conn:
    def __init__(self, writer):
        self.w = writer
        self.acc = None
        self.player = None
        self.death = None
        self.closed = False

    def send_raw(self, text):
        if self.closed:
            return
        try:
            if self.w.transport.get_write_buffer_size() > 2_000_000:     # hopelessly slow client
                self.closed = True
                self.w.close()
                return
            self.w.write(ws_frame(text.encode()))
        except Exception:
            self.closed = True

    def send(self, obj):
        self.send_raw(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))

    def toast(self, msg, fx=None):
        self.send({"t": "toast", "msg": msg, **({"fx": fx} if fx else {})})


async def ws_session(reader, writer):
    c = Conn(writer)
    conns.add(c)
    try:
        while True:
            op, data = await ws_read(reader)
            if op == 8:
                break
            if op == 9:
                writer.write(ws_frame(data, 10))
                continue
            if op != 1:
                continue
            try:
                msg = json.loads(data)
            except ValueError:
                continue
            await on_message(c, msg)
    except (asyncio.IncompleteReadError, ConnectionError, OSError):
        pass
    finally:
        conns.discard(c)
        c.closed = True
        if c.player:
            remember(c)
            game.remove(c.player)
        try:
            writer.close()
        except Exception:
            pass


RESUME = {}           # uid -> what their blob had when the connection dropped
RESUME_TTL = 600      # seconds a dropped game can be picked up again


def remember(c):
    p = c.player
    if p and p.alive and c.acc and c.acc.uid is not None and p.m > 12:
        RESUME[c.acc.uid] = {"m": p.m, "rb": p.round_bank, "t": time.time()}


def save_resume_on_exit():
    """Railway stops the old container on every deploy: keep everyone's game for the new one."""
    for c in list(conns):
        remember(c)
    for a in Account.cache.values():
        a.save()
    set_setting("resume", json.dumps(RESUME))
    log.info("saved %d games for resuming", len(RESUME))


def load_resume():
    try:
        data = json.loads(setting("resume", "{}") or "{}")
    except ValueError:
        data = {}
    now = time.time()
    for uid, r in data.items():
        if now - r.get("t", 0) < RESUME_TTL:
            RESUME[int(uid)] = r
    set_setting("resume", "{}")


VOICE_BPS = 30000       # base64 chars per second one speaker may send (16 kHz mu-law is ~21k)


BLANK_CH = set("\u3164\u115f\u1160\uffa0\u2800\u180e\u17b4\u17b5")


def clean_name(s, default):
    import unicodedata
    s = "".join(ch for ch in (s or "") if ch.isprintable() and ch not in BLANK_CH
                and unicodedata.category(ch) not in ("Cf", "Zl", "Zp")).strip()[:14]
    # names made only of spaces/combining marks show up as nothing on screen
    if not any(unicodedata.category(ch)[0] in "LNSP" for ch in s):
        return default if default == "O'yinchi" else clean_name(default, "O'yinchi")
    return s


async def on_message(c, m):
    t = m.get("t")
    if t == "hello":
        user = check_init_data(m.get("initData", ""))
        if user:
            uid, uname = int(user["id"]), user.get("username", "")
            default = user.get("first_name") or uname or "O'yinchi"
        elif DEV and isinstance(m.get("dev_uid"), int):
            uid, uname, default = m["dev_uid"], "", f"Dev{m['dev_uid']}"
        else:
            uid, uname, default = None, "", "Mehmon"
        c.acc = Account.get(uid, clean_name(m.get("name"), default), uname)
        if uid is not None and m.get("name"):
            c.acc.name = clean_name(m.get("name"), default)
            c.acc.save()
        c.send({"t": "init", "food": game.food_snapshot(), "skins": SKIN_PRICES, "S": S})
        c.send_raw(game.meta_msg())
        c.send(c.acc.public())
        return
    if not c.acc:
        return
    p = c.player
    if t == "play":
        if p:
            return
        if m.get("name"):
            c.acc.name = clean_name(m["name"], c.acc.name)
            c.acc.save()
        c.player = p = game.spawn_human(c)
        r = RESUME.pop(c.acc.uid, None) if c.acc.uid is not None else None
        if r and time.time() - r["t"] < RESUME_TTL:
            p.m, p.round_bank = r["m"], r["rb"]
            p.x, p.z = game.safe_spot(rad(p.m))
            c.toast(f"♻️ O'yiningiz tiklandi: {fmt(p.m * 10)} token")
        near = m.get("near")
        if near and c.acc.uid is not None and c.acc.uid == admin_id():
            friend = next((q for q in game.players if q.conn and q.conn.acc.uid == int(near) and q.alive), None)
            if friend:
                a = random.uniform(0, 2 * math.pi)
                d = rad(friend.m) + rad(p.m) + 10
                p.x, p.z = friend.x + math.cos(a) * d, friend.z + math.sin(a) * d
                game.clamp(p)
                c.toast(f"👋 {friend.name} yonidasiz")
            else:
                c.toast("Bu o'yinchi hozir maydonda emas")
        c.death = None
        c.send({"t": "spawn", "id": p.id, "x": p.x, "z": p.z, "m": p.m})
    elif t == "pos" and p and p.alive:
        try:
            x, z = float(m["x"]), float(m["z"])
        except (KeyError, TypeError, ValueError):
            return
        if math.isfinite(x) and math.isfinite(z) and game.human_pos(p, x, z):
            c.send({"t": "fix", "x": p.x, "z": p.z})
    elif t == "dev" and DEV and p:                  # local testing only
        if "m" in m:
            p.m = float(m["m"])
        if "x" in m:
            p.x, p.z = float(m["x"]), float(m["z"])
            c.send({"t": "fix", "x": p.x, "z": p.z})
        if "rp" in m:
            c.acc.rp = int(m["rp"])
        if "t0" in m:
            p.t0 -= float(m["t0"])
        if "stars" in m:
            c.acc.stars = int(m["stars"])
            c.acc.save()
            push_acc(c.acc)
    elif t == "leave":
        if p:
            life = p.round_bank + int(p.m * 10)
            if life > c.acc.best:
                c.acc.best = life
                c.acc.save()
            game.remove(p)
            c.player = None
            c.send({"t": "left", "banked": p.round_bank, "rank": c.acc.finish_round(p)})
            push_acc(c.acc)
    elif t == "v" and c.acc:                      # voice chat: 16 kHz mu-law, base64, heard by everyone online
        d = m.get("d")
        if not isinstance(d, str) or not 0 < len(d) <= 7000:
            return
        now = time.monotonic()
        c.vbudget = min(VOICE_BPS * 2, getattr(c, "vbudget", VOICE_BPS * 2) + (now - getattr(c, "vlast", now)) * VOICE_BPS)
        c.vlast = now
        if c.vbudget < len(d):
            return
        c.vbudget -= len(d)
        out = json.dumps({"t": "v", "id": p.id if p else 0, "n": (p.name if p else c.acc.name)[:14], "d": d},
                         separators=(",", ":"), ensure_ascii=False)
        for o in list(conns):
            if o is not c and o.acc:
                o.send_raw(out)
    elif t == "speed" and p and p.alive:
        if p.speed_t > 0:
            return
        if p.m * 10 < SPEED_COST + 100:
            return c.toast("2x tezlik uchun kamida 1.1K token kerak")
        p.m -= SPEED_COST / 10
        p.speed_t = 30.0
        c.send({"t": "speedOn", "sec": 30})
    elif t == "kill" and p and p.alive:
        game.start_kill(p, m.get("target"))
    elif t == "anti":
        if c.acc.stars < ANTI_COST:
            return c.toast("Balansda yetarli ⭐ yo'q")
        if game.resolve_anti(p):
            c.acc.stars -= ANTI_COST
            c.acc.save()
            push_acc(c.acc)
    elif t == "prefs" and c.acc.uid is not None:   # graphics / FPS settings follow the player to any phone
        p = m.get("p")
        if isinstance(p, dict):
            c.acc.prefs = json.dumps({k: p[k] for k in ("gfx", "fps", "showFps") if k in p})[:200]
            db.execute("UPDATE users SET prefs=? WHERE uid=?", (c.acc.prefs, c.acc.uid))
            db.commit()
    elif t == "ad":                                 # a banner for the menu / death screen
        ad = ad_pick(c.acc.uid)
        if ad:
            c.send({"t": "ad", "id": ad["id"], "title": ad["title"], "body": ad["body"], "url": ad["url"],
                    "img": f"/api/adimg?id={ad['id']}" if ad["photo"] else "", "where": m.get("where", "")})
    elif t == "adclick":
        ad_click(int(m.get("id", 0) or 0), c.acc.uid)
    elif t == "tops":                               # leaderboard of every rank tier
        tiers = []
        for ti in range(len(RANK_TIERS)):
            lo, hi = tier_start(ti), tier_start(ti + 1) if ti + 1 < len(RANK_TIERS) else 10 ** 9
            rows = db.execute("SELECT uid, name, rp FROM users WHERE rp>=? AND rp<? AND rp>0 ORDER BY rp DESC, uid LIMIT 30", (lo, hi)).fetchall()
            cnt = db.execute("SELECT COUNT(*) c FROM users WHERE rp>=? AND rp<? AND rp>0", (lo, hi)).fetchone()["c"]
            tiers.append({"count": cnt, "list": [{"me": r["uid"] == c.acc.uid, "name": (r["name"] or "O'yinchi")[:16],
                                                    "rp": r["rp"], "div": rank_info(r["rp"])["div"]} for r in rows]})
        mine = None
        if c.acc.uid is not None and c.acc.rp > 0:
            ri = rank_info(c.acc.rp)
            hi = tier_start(ri["tier"] + 1) if ri["tier"] + 1 < len(RANK_TIERS) else 10 ** 9
            place = db.execute("SELECT COUNT(*) c FROM users WHERE rp>? AND rp<?", (c.acc.rp, hi)).fetchone()["c"] + 1
            mine = {"tier": ri["tier"], "place": place}
        c.send({"t": "tops", "tiers": tiers, "mine": mine})
    elif t == "skin":
        sid = m.get("id")
        if sid not in SKIN_PRICES:
            return
        if sid not in c.acc.owned:
            if not m.get("buy"):
                return
            price = SKIN_PRICES[sid]
            if c.acc.stars < price:
                return c.toast("Balansda yetarli ⭐ yo'q")
            c.acc.stars -= price
            c.acc.owned.append(sid)
            c.toast(f"🎨 {SKIN_NAMES[sid]} sizniki!")
        c.acc.skin = sid
        c.acc.save()
        if p:
            p.skin = sid
            game.meta_dirty = True
        push_acc(c.acc)
    elif t == "invoice":
        item = m.get("item", "")
        if c.acc.uid is None:
            return c.toast("To'lov faqat Telegram ichida ishlaydi")
        if item.startswith("skin:") and item[5:] in SKIN_PRICES and SKIN_PRICES[item[5:]] > 0:
            price, title = SKIN_PRICES[item[5:]], f"{SKIN_NAMES[item[5:]]} skini"
        elif item == "anti":
            price, title = ANTI_COST, "ANTI-KIL"
        elif item == "revive":
            price, title = REVIVE_COST, "Davom etish"
        else:
            return
        link = await tg("createInvoiceLink", title=title, description=f"Shar Yutar: {title}",
                        payload=f"{item}|{c.acc.uid}|{secrets.token_hex(4)}", currency="XTR",
                        prices=[{"label": title, "amount": price}], provider_token="")
        if link:
            c.send({"t": "invoice", "link": link, "item": item})
        else:
            c.toast("To'lovni ochib bo'lmadi, keyinroq urinib ko'ring")
    elif t == "subcheck":
        if c.acc.uid is None:
            return c.toast("Telegram orqali kiring")
        if c.acc.sub_bonus:
            return c.toast("Bonus allaqachon olingan ✅")
        if not CHANNEL:
            return
        member = await tg("getChatMember", chat_id=CHANNEL, user_id=c.acc.uid)
        if member is None:
            return c.toast("Tekshirib bo'lmadi, birozdan keyin urinib ko'ring")
        if member.get("status") in ("member", "administrator", "creator") or member.get("is_member"):
            c.acc.sub_bonus = 1
            conv = c.acc.add_tokens(SUB_BONUS)
            c.toast(f"🎁 Rahmat! +{fmt(SUB_BONUS)} token hisobingizga tushdi")
            if conv:
                c.toast(f"🎉 1M token → {conv} ⭐ balansga tushdi!")
            push_acc(c.acc)
        else:
            c.toast("Avval kanalga obuna bo'ling, keyin tekshiring")
    elif t == "withdraw":
        if c.acc.uid is None:
            return c.toast("Telegram orqali kiring")
        gift = m.get("gift")
        if gift not in PAY_GIFTS:
            return c.toast("Sovg'ani tanlang")
        title, price, emoji = PAY_GIFTS[gift]
        if c.acc.stars < price:
            return c.toast(f"{emoji} {title} uchun balansda {price} ⭐ kerak")
        c.acc.stars -= price
        c.acc.save()
        cur = db.execute("INSERT INTO reqs(uid,stars,status,created,gift) VALUES(?,?,?,?,?)",
                         (c.acc.uid, price, "pending", int(time.time()), gift))
        db.commit()
        push_acc(c.acc)
        c.toast(f"So'rov yuborildi! {emoji} {title} tez orada Telegram'ingizga keladi")
        asyncio.create_task(notify_admin_request(cur.lastrowid, c.acc, price, gift))


# ---------------------------------------------------------------- admin app API
def admin_user(init_data):
    if DEV and init_data.startswith("dev:"):
        return int(init_data[4:])
    u = check_init_data(init_data)
    return int(u["id"]) if u else None


def online_uids():
    return {c.acc.uid for c in conns if c.acc and c.acc.uid is not None and c.player and c.player.alive}


def admin_overview(q=""):
    now = int(time.time())
    day0 = (now + 5 * 3600) // 86400 * 86400 - 5 * 3600     # midnight in Tashkent
    one = lambda sql, *a: db.execute(sql, a).fetchone()[0]
    for a in Account.cache.values():          # include unsaved online changes
        a.save()
    on = online_uids()
    stats = {
        "users": one("SELECT COUNT(*) FROM users"),
        "new_today": one("SELECT COUNT(*) FROM users WHERE created>=?", day0),
        "online": len(on),
        "bots": sum(1 for p in game.players if p.bot),
        "tokens": one("SELECT COALESCE(SUM(tokens),0) FROM users"),
        "stars_balance": one("SELECT COALESCE(SUM(stars),0) FROM users"),
        "pending_n": one("SELECT COUNT(*) FROM reqs WHERE status='pending'"),
        "pending_stars": one("SELECT COALESCE(SUM(stars),0) FROM reqs WHERE status='pending'"),
        "sent_stars": one("SELECT COALESCE(SUM(stars),0) FROM reqs WHERE status='sent'"),
        "paid_total": one("SELECT COALESCE(SUM(stars),0) FROM payments"),
        "paid_today": one("SELECT COALESCE(SUM(stars),0) FROM payments WHERE created>=?", day0),
        "payments_n": one("SELECT COUNT(*) FROM payments"),
        "refs": one("SELECT COUNT(*) FROM users WHERE ref IS NOT NULL"),
    }
    sql = ("SELECT u.uid, u.name, u.username, u.tokens, u.stars, u.best, u.created, u.ref_earned, "
           "(SELECT COUNT(*) FROM users r WHERE r.ref=u.uid) refs, "
           "(SELECT COALESCE(SUM(stars),0) FROM payments p WHERE p.uid=u.uid) paid FROM users u")
    args = ()
    if q:
        sql += " WHERE u.name LIKE ? OR u.username LIKE ? OR CAST(u.uid AS TEXT) LIKE ?"
        args = (f"%{q}%",) * 3
    sql += " ORDER BY u.stars DESC, u.tokens DESC LIMIT 300"
    users = [dict(r) | {"online": r["uid"] in on} for r in db.execute(sql, args)]
    reqs = [dict(r) for r in db.execute(
        "SELECT q.id, q.uid, q.stars, q.gift, q.status, q.created, u.name, u.username FROM reqs q LEFT JOIN users u ON u.uid=q.uid "
        "ORDER BY (q.status='pending') DESC, q.id DESC LIMIT 50")]
    pays = [dict(r) for r in db.execute(
        "SELECT p.uid, p.item, p.stars, p.created, u.name FROM payments p LEFT JOIN users u ON u.uid=p.uid ORDER BY p.created DESC LIMIT 30")]
    return {"ok": True, "stats": stats, "users": users, "reqs": reqs, "payments": pays, "now": now}


AVATARS = {}          # uid -> (time, bytes or None)


def fetch_avatar(uid):
    photos = tg_call("getUserProfilePhotos", user_id=uid, limit=1)
    if not photos or not photos.get("photos"):
        return None
    sizes = photos["photos"][0]
    pick = next((s for s in sizes if s.get("width", 0) >= 160), sizes[-1])
    f = tg_call("getFile", file_id=pick["file_id"])
    with urllib.request.urlopen(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{f['file_path']}", timeout=20) as r:
        return r.read()


async def avatar(uid):
    hit = AVATARS.get(uid)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    try:
        img = await asyncio.to_thread(fetch_avatar, uid)
    except Exception as e:
        log.info("avatar %s: %s", uid, str(e).replace(BOT_TOKEN, "***") if BOT_TOKEN else e)
        img = None
    AVATARS[uid] = (time.time(), img)
    return img


async def admin_api(body):
    try:
        m = json.loads(body or b"{}")
    except ValueError:
        return {"ok": False, "error": "bad json"}
    uid = admin_user(m.get("initData", ""))
    adm = admin_id()
    if adm is None:
        return {"ok": False, "error": "Admin hali belgilanmagan: botga /admin yozing"}
    if uid != adm:
        return {"ok": False, "error": "Bu panel faqat admin uchun"}
    act = m.get("action", "overview")
    if act == "botgift":
        okk, msg = await bot_send_gift(int(m.get("id", 0)))
        if not okk:
            return {"ok": False, "error": msg}
    elif act == "req":
        note = await resolve_request(int(m.get("id", 0)), bool(m.get("ok")))
        if not note:
            return {"ok": False, "error": "So'rov allaqachon ko'rib chiqilgan"}
    elif act == "stars":
        target = int(m.get("uid", 0))
        if not db.execute("SELECT 1 FROM users WHERE uid=?", (target,)).fetchone():
            return {"ok": False, "error": "O'yinchi topilmadi"}
        acc = Account.get(target)
        delta = int(m.get("delta", 0))
        acc.stars = max(0, acc.stars + delta)
        acc.save()
        push_acc(acc)
        log.info("admin changed stars of %s by %s", target, delta)
        for c in conns:
            if c.acc is acc:
                c.toast(f"⭐ Admin balansingizni o'zgartirdi: {'+' if delta > 0 else ''}{delta} ⭐")
    return admin_overview(str(m.get("q", ""))[:40])


# ---------------------------------------------------------------- HTTP
INDEX = os.path.join(HERE, "public", "index.html")


async def http_handler(reader, writer):
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 15)
    except Exception:
        writer.close()
        return
    lines = head.decode("latin-1").split("\r\n")
    try:
        method, path, _ = lines[0].split(" ", 2)
    except ValueError:
        writer.close()
        return
    hdr = {}
    for ln in lines[1:]:
        if ":" in ln:
            k, v = ln.split(":", 1)
            hdr[k.strip().lower()] = v.strip()
    full_path = path
    path = path.split("?", 1)[0]
    if path == "/ws" and "websocket" in hdr.get("upgrade", "").lower():
        key = hdr.get("sec-websocket-key", "")
        acc = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Accept: {acc}\r\n\r\n").encode())
        await writer.drain()
        await ws_session(reader, writer)
        return
    if path == "/api/adimg":
        qs = dict(urllib.parse.parse_qsl(full_path.split("?", 1)[1] if "?" in full_path else ""))
        img = await ad_image(int(qs["id"])) if qs.get("id", "").isdigit() else None
        if img:
            writer.write(f"HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\nContent-Length: {len(img)}\r\nCache-Control: public, max-age=86400\r\nConnection: close\r\n\r\n".encode() + img)
        else:
            writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        try:
            await writer.drain()
        finally:
            writer.close()
        return
    if path == "/api/avatar":
        qs = dict(urllib.parse.parse_qsl(full_path.split("?", 1)[1] if "?" in full_path else ""))
        img = None
        if admin_id() is not None and admin_user(qs.get("a", "")) == admin_id() and qs.get("uid", "").isdigit():
            img = await avatar(int(qs["uid"]))
        if img:
            head_ = f"HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\nContent-Length: {len(img)}\r\nCache-Control: private, max-age=3600\r\nConnection: close\r\n\r\n"
            writer.write(head_.encode() + img)
        else:
            writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        try:
            await writer.drain()
        finally:
            writer.close()
        return
    if path == "/api/admin" and method == "POST":
        try:
            n = min(int(hdr.get("content-length", "0")), 65536)
            body = await asyncio.wait_for(reader.readexactly(n), 15) if n else b""
            out = await admin_api(body)
        except Exception:
            log.exception("admin api failed")
            out = {"ok": False, "error": "server xatosi"}
        data = json.dumps(out, ensure_ascii=False).encode()
        writer.write(f"HTTP/1.1 200 OK\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: {len(data)}\r\n"
                     "Cache-Control: no-store\r\nConnection: close\r\n\r\n".encode() + data)
        try:
            await writer.drain()
        finally:
            writer.close()
        return
    if path in ("/admin", "/admin.html"):
        with open(os.path.join(HERE, "public", "admin.html"), "rb") as f:
            body, ctype = f.read(), "text/html; charset=utf-8"
        status = "200 OK"
    elif path in ("/", "/index.html"):
        with open(INDEX, "rb") as f:
            body, ctype = f.read(), "text/html; charset=utf-8"
        status = "200 OK"
    elif path == "/favicon.ico":
        body, ctype, status = b"", "image/x-icon", "204 No Content"
    elif path == "/health":
        body, ctype, status = b"ok", "text/plain", "200 OK"
    else:
        body, ctype, status = b"not found", "text/plain", "404 Not Found"
    writer.write(f"HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\nContent-Length: {len(body)}\r\n"
                 "Cache-Control: no-cache\r\nConnection: close\r\n\r\n".encode() + (body if method != "HEAD" else b""))
    try:
        await writer.drain()
    finally:
        writer.close()


# ---------------------------------------------------------------- live leaderboard in the channel
def html(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def leaderboard_text():
    for a in Account.cache.values():
        a.save()
    live = sorted((p for p in game.players if p.alive and not p.bot and p.conn and p.conn.acc.uid is not None),
                  key=lambda p: -(p.round_bank + p.m * 10))
    on = {p.conn.acc.uid for p in live}
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    t = time.strftime("%H:%M:%S", time.gmtime(time.time() + 5 * 3600))
    out = ["🎮 <b>SHAR YUTAR — JONLI REYTING</b>", f"⏱ {t} (Toshkent) · har 30 soniyada yangilanadi", ""]
    out.append(f"🔴 <b>HOZIR MAYDONDA: {len(live)} kishi</b>")
    if live:
        for i, p in enumerate(live[:10], 1):
            out.append(f"{medals.get(i, f'{i}.')} {html(p.name)} — <b>{fmt(p.round_bank + int(p.m * 10))}</b>")
    else:
        out.append("Hozir hech kim yo'q — birinchi bo'ling! 🚀")
    out += ["", "🏆 <b>TOP-30 · bitta o'yindagi rekord</b>"]
    rows = db.execute("SELECT uid, name, best FROM users WHERE best>0 ORDER BY best DESC LIMIT 30").fetchall()
    for i, r in enumerate(rows, 1):
        out.append(f"{medals.get(i, f'{i}.')} {html(r['name'] or r['uid'])} — {fmt(r['best'])}{' 🟢' if r['uid'] in on else ''}")
    if not rows:
        out.append("Hali rekord yo'q")
    out += ["", "🟢 — hozir o'ynayapti"]
    return "\n".join(out)


def play_url_button():
    return {"inline_keyboard": [[{"text": "🎮 O'ynash", "url": f"https://t.me/{BOT_USERNAME}?start=kanal"}]]}


async def channel_loop():
    if not BOT_TOKEN or not CHANNEL:
        return
    await asyncio.sleep(8)                         # let the bot learn its username first
    last = None
    while True:
        try:
            text = leaderboard_text()
            msg_id = setting("top_msg")
            if text != last:
                ok = False
                if msg_id:
                    try:
                        await asyncio.to_thread(tg_call, "editMessageText", chat_id=CHANNEL, message_id=int(msg_id),
                                                text=text, parse_mode="HTML", reply_markup=play_url_button())
                        ok = True
                    except Exception as e:
                        err = str(e)
                        ok = "not modified" in err
                        if not ok:
                            log.warning("leaderboard edit failed: %s", err.replace(BOT_TOKEN, "***"))
                if not ok:
                    sent = await tg("sendMessage", chat_id=CHANNEL, text=text, parse_mode="HTML",
                                    reply_markup=play_url_button(), disable_notification=True)
                    if sent:
                        set_setting("top_msg", sent["message_id"])
                        await tg("pinChatMessage", chat_id=CHANNEL, message_id=sent["message_id"], disable_notification=True)
                        log.info("leaderboard posted and pinned in %s", CHANNEL)
                last = text
        except Exception:
            log.exception("leaderboard loop")
        await asyncio.sleep(30)


# ---------------------------------------------------------------- 24/7 live stream to the channel
async def stream_feed():
    """Runs streamer.py (draws the arena, ffmpeg -> Telegram RTMP) and keeps it fed with the game state."""
    if not os.environ.get("STREAM_URL"):
        return
    import sys as _sys
    while True:
        proc = await asyncio.create_subprocess_exec(_sys.executable, os.path.join(HERE, "streamer.py"),
                                                    stdin=asyncio.subprocess.PIPE, env={**os.environ, "ARENA_S": str(S)})
        log.info("live stream started")
        n = 0
        top = []
        try:
            while proc.returncode is None:
                if n % 100 == 0:
                    top = [[r["name"], r["best"]] for r in db.execute("SELECT name, best FROM users WHERE best>0 ORDER BY best DESC LIMIT 5")]
                msg = {"p": [[p.id, p.name, p.skin, round(p.x, 1), round(p.z, 1), round(p.m, 1), 0 if p.bot else 1]
                             for p in game.players if p.alive],
                       "n": sum(1 for p in game.players if p.alive and not p.bot), "top": top}
                if n % 10 == 0:
                    msg["f"] = [[round(game.fx[i], 1), round(game.fz[i], 1), game.fbig[i], game.fc[i]] for i in range(FOOD_N)]
                proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode())
                await proc.stdin.drain()
                n += 1
                await asyncio.sleep(0.1)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            log.exception("stream feed")
        log.warning("live stream process ended, restarting in 10 s")
        try:
            proc.kill()
        except Exception:
            pass
        await asyncio.sleep(10)


async def game_loop():
    last = time.monotonic()
    n = 0
    while True:
        await asyncio.sleep(TICK)
        now = time.monotonic()
        dt, last = min(0.1, now - last), now
        try:
            game.step(dt)
            n += 1
            if game.meta_dirty:
                game.meta_dirty = False
                meta = game.meta_msg()
                for c in list(conns):
                    if c.acc:
                        c.send_raw(meta)
            if n % 2 == 0:                       # 10 snapshots per second
                st = game.state_msg()
                for c in list(conns):
                    if c.acc:
                        c.send_raw(st)
        except Exception:
            log.exception("tick failed")


async def main():
    import signal
    load_resume()
    for _ in range(MIN_BOTS + 6):
        game.new_bot()

    def on_term():
        try:
            save_resume_on_exit()
        finally:
            os._exit(0)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, on_term)
        except (NotImplementedError, RuntimeError):
            pass
    server = await asyncio.start_server(http_handler, "0.0.0.0", PORT)
    log.info("listening on :%s, data in %s, admin=%s", PORT, DATA_DIR, admin_id())
    await asyncio.gather(server.serve_forever(), game_loop(), bot_loop(), channel_loop(), stream_feed())


if __name__ == "__main__":
    asyncio.run(main())
