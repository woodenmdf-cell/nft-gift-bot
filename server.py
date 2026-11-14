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
import json
import logging
import math
import os
import random
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
S = 130.0                 # half-size of the arena
FOOD_N = 1800
MAX_M = 8000.0            # 80K tokens
BANK_STEP = 50000         # whole 50K chunks of a round go to the account
TOKEN_GOAL = 500000       # every 500K account tokens -> 50 stars
GOAL_STARS = 50
SPEED_COST = 1000         # round tokens for 30 s of 2x speed
KILL_COST = ANTI_COST = REVIVE_COST = 10
KILL_TIME = 10.0
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


def setting(k, default=None):
    r = db.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def set_setting(k, v):
    db.execute("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)", (k, str(v)))
    db.commit()


def admin_id():
    return int(ADMIN_ENV) if ADMIN_ENV.isdigit() else (int(setting("admin")) if setting("admin") else None)


class Account:
    """A player's persistent wallet. Guests (no Telegram login) live only in memory."""
    cache = {}

    def __init__(self, uid, name, username=""):
        self.uid = uid
        self.name = name
        if uid is None:
            self.tokens, self.stars, self.owned, self.skin, self.best = 0, 0, ["yashil"], "yashil", 0
            return
        r = db.execute("SELECT * FROM users WHERE uid=?", (uid,)).fetchone()
        if not r:
            db.execute("INSERT INTO users(uid,name,username,created) VALUES(?,?,?,?)", (uid, name, username, int(time.time())))
            db.commit()
            r = db.execute("SELECT * FROM users WHERE uid=?", (uid,)).fetchone()
        else:
            db.execute("UPDATE users SET name=?, username=? WHERE uid=?", (name, username, uid))
        self.tokens, self.stars, self.best = r["tokens"], r["stars"], r["best"]
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
            a = cls.cache[uid] = cls(uid, name or str(uid), username)
        elif name:
            a.name = name
        return a

    def save(self):
        if self.uid is None:
            return
        db.execute("UPDATE users SET tokens=?, stars=?, owned=?, skin=?, best=?, name=? WHERE uid=?",
                   (self.tokens, self.stars, json.dumps(self.owned), self.skin, self.best, self.name, self.uid))
        db.commit()

    def add_tokens(self, n):
        """Returns how many stars were credited by crossing 500K."""
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
        rows = db.execute("SELECT stars, status, created FROM reqs WHERE uid=? ORDER BY id DESC LIMIT 10", (self.uid,))
        return [{"stars": r["stars"], "status": STATUS.get(r["status"], r["status"]), "date": time.strftime("%d.%m.%Y", time.localtime(r["created"]))} for r in rows]

    def public(self):
        return {"t": "acc", "tokens": self.tokens, "stars": self.stars, "owned": self.owned, "skin": self.skin,
                "best": self.best, "reqs": self.reqs(), "guest": self.uid is None, "name": self.name}


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
    return {"inline_keyboard": [[{"text": "🎮 O'ynash", "web_app": {"url": PUBLIC_URL}}]]}


async def bot_loop():
    if not BOT_TOKEN:
        log.warning("BOT_TOKEN not set: Telegram bot is off")
        return
    me = await tg("getMe")
    log.info("bot @%s started, web app: %s", me and me.get("username"), PUBLIC_URL or "(no PUBLIC_URL yet)")
    await tg("setMyCommands", commands=[{"command": "start", "description": "O'yinni ochish"},
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
    if text.startswith("/start"):
        await tg("sendMessage", chat_id=chat, reply_markup=play_keyboard(),
                 text="🎮 <b>Shar Yutar</b>\n\nDonachalarni ye, kattalash, kichiklarni yut!\n"
                      "• Har 50K token hisobingizga o'tadi\n• Har 500K token = 50 ⭐\n"
                      "• 🎯 KIL bilan TOP-3 dagilarning tokenini oling\n\nBoshlash uchun pastdagi tugmani bosing 👇",
                 parse_mode="HTML")
    elif text.startswith("/admin"):
        adm = admin_id()
        if adm is None:
            set_setting("admin", frm["id"])
            await tg("sendMessage", chat_id=chat, text="✅ Siz admin bo'ldingiz. Yulduz so'rovlari shu yerga keladi.")
        elif adm == frm["id"]:
            users = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
            pend = db.execute("SELECT COUNT(*) c, COALESCE(SUM(stars),0) s FROM reqs WHERE status='pending'").fetchone()
            paid = db.execute("SELECT COALESCE(SUM(stars),0) s FROM payments").fetchone()["s"]
            online = sum(1 for c in conns if c.player and c.player.alive)
            await tg("sendMessage", chat_id=chat,
                     text=f"📊 O'yinchilar: {users}\n🟢 Hozir o'ynayapti: {online}\n"
                          f"⏳ Kutilayotgan so'rovlar: {pend['c']} ta ({pend['s']} ⭐)\n💰 Jami Stars to'lovlari: {paid} ⭐")
        else:
            await tg("sendMessage", chat_id=chat, text="Bu buyruq faqat admin uchun.")


async def handle_callback(q):
    data, frm = q.get("data", ""), q.get("from", {})
    if frm.get("id") != admin_id() or ":" not in data:
        await tg("answerCallbackQuery", callback_query_id=q["id"], text="Faqat admin")
        return
    action, rid = data.split(":", 1)
    r = db.execute("SELECT * FROM reqs WHERE id=?", (int(rid),)).fetchone()
    if not r or r["status"] != "pending":
        await tg("answerCallbackQuery", callback_query_id=q["id"], text="Allaqachon ko'rib chiqilgan")
        return
    acc = Account.get(r["uid"])
    if action == "ok":
        db.execute("UPDATE reqs SET status='sent' WHERE id=?", (r["id"],))
        note, user_msg = "✅ Yuborildi", f"✅ {r['stars']} ⭐ yulduz sizga sovg'a qilindi! O'ynashda davom eting 🎮"
    else:
        db.execute("UPDATE reqs SET status='rejected' WHERE id=?", (r["id"],))
        acc.stars += r["stars"]
        acc.save()
        note, user_msg = "❌ Rad etildi (⭐ balansga qaytarildi)", f"❌ {r['stars']} ⭐ so'rovingiz rad etildi, yulduzlar balansingizga qaytarildi."
    db.commit()
    await tg("answerCallbackQuery", callback_query_id=q["id"], text=note)
    msg = q.get("message")
    if msg:
        await tg("editMessageText", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                 text=msg.get("text", "") + f"\n\n{note}")
    await tg("sendMessage", chat_id=r["uid"], text=user_msg)
    push_acc(acc)


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


async def notify_admin_request(rid, acc, stars):
    adm = admin_id()
    if not adm:
        log.warning("withdraw request %s but no admin set (send /admin to the bot)", rid)
        return
    who = acc.name
    r = db.execute("SELECT username FROM users WHERE uid=?", (acc.uid,)).fetchone()
    if r and r["username"]:
        who += f" (@{r['username']})"
    await tg("sendMessage", chat_id=adm,
             text=f"⭐ Yulduz so'rovi #{rid}\n👤 {who}\n🆔 {acc.uid}\n💫 {stars} ⭐\n\n"
                  f"Yulduzlarni sovg'a qilib yuboring, keyin «Yuborildi»ni bosing.",
             reply_markup={"inline_keyboard": [[{"text": "✅ Yuborildi", "callback_data": f"ok:{rid}"},
                                                {"text": "❌ Rad etish", "callback_data": f"no:{rid}"}]]})


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
        dt = min(0.5, now - p.last_pos)
        p.last_pos = now
        maxd = speed_of(p.m) * (2 if p.speed_t > 0 else 1) * dt * 1.5 + 0.8
        dx, dz = x - p.x, z - p.z
        d = math.hypot(dx, dz)
        corrected = False
        if d > maxd:
            dx, dz = dx / d * maxd, dz / d * maxd
            corrected = d > maxd + 3
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
            if o.m > b.m and d < 12 + rad(o.m) * 2.2 and d < fd:
                flee, fd = o, d
            elif b.m > o.m * 1.05 and d < 22 + r * 2 and d < pd:
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
                if a is b or not b.alive or a.m <= b.m:
                    continue
                if math.hypot(a.x - b.x, a.z - b.z) < ra + rad(b.m):
                    a.m = min(MAX_M, a.m + b.m)
                    self.kill_blob(b, a)
        for p in self.players:
            if p.alive and p.m > 150:
                p.m -= p.m * 0.0015 * dt
        for p in self.players:
            if p.alive and not p.bot:
                self.bank(p)
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
            sc = int(b.m * 10)
            if sc > c.acc.best:
                c.acc.best = sc
                c.acc.save()
            c.send({"t": "dead", "killer": by.name, "score": sc, "best": c.acc.best, "banked": b.round_bank})
        self.remove(b)
        if c:
            c.player = None

    def bank(self, p):
        while p.m * 10 >= BANK_STEP:
            p.m -= BANK_STEP / 10
            p.round_bank += BANK_STEP
            conv = p.conn.acc.add_tokens(BANK_STEP)
            p.conn.toast("💰 50K token hisobingizga o'tdi!", fx="bank")
            if conv:
                p.conn.toast(f"🎉 500K token → {conv} ⭐ balansga tushdi!", fx="stars")
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
               "f": self.fchanges}
        self.fchanges = []
        return json.dumps(msg, separators=(",", ":"))

    def meta_msg(self):
        return json.dumps({"t": "meta", "p": {p.id: [p.name, p.skin, 0 if p.bot else 1] for p in self.players}},
                          separators=(",", ":"), ensure_ascii=False)


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
            game.remove(c.player)
        try:
            writer.close()
        except Exception:
            pass


def clean_name(s, default):
    s = "".join(ch for ch in (s or "") if ch.isprintable()).strip()[:14]
    return s or default


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
        c.send({"t": "init", "food": game.food_snapshot(), "skins": SKIN_PRICES})
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
        if "stars" in m:
            c.acc.stars = int(m["stars"])
            c.acc.save()
            push_acc(c.acc)
    elif t == "leave":
        if p:
            game.remove(p)
            c.player = None
            c.send({"t": "left", "banked": p.round_bank})
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
    elif t == "withdraw":
        if c.acc.uid is None:
            return c.toast("Telegram orqali kiring")
        if c.acc.stars < GOAL_STARS:
            return c.toast(f"Kamida {GOAL_STARS} ⭐ kerak")
        amount = c.acc.stars
        c.acc.stars = 0
        c.acc.save()
        cur = db.execute("INSERT INTO reqs(uid,stars,status,created) VALUES(?,?,?,?)",
                         (c.acc.uid, amount, "pending", int(time.time())))
        db.commit()
        push_acc(c.acc)
        c.toast("So'rov yuborildi! Admin tez orada yulduzlarni yuboradi")
        asyncio.create_task(notify_admin_request(cur.lastrowid, c.acc, amount))


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
    path = path.split("?", 1)[0]
    if path == "/ws" and "websocket" in hdr.get("upgrade", "").lower():
        key = hdr.get("sec-websocket-key", "")
        acc = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Accept: {acc}\r\n\r\n").encode())
        await writer.drain()
        await ws_session(reader, writer)
        return
    if path in ("/", "/index.html"):
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
    for _ in range(MIN_BOTS + 6):
        game.new_bot()
    server = await asyncio.start_server(http_handler, "0.0.0.0", PORT)
    log.info("listening on :%s, data in %s, admin=%s", PORT, DATA_DIR, admin_id())
    await asyncio.gather(server.serve_forever(), game_loop(), bot_loop())


if __name__ == "__main__":
    asyncio.run(main())
