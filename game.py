"""Shahar Arena — Mini App ichidagi o'yin: server tomoni.

Tangalar, tajriba (XP), yaxshilashlar va oylik VIP obuna shu yerda hisoblanadi.
Mukofot vaqtini server o'zi o'lchaydi (start → reward), shuning uchun mijoz tomonidan
soxta natija yuborib cheksiz tanga yig'ib bo'lmaydi.
"""
import asyncio
import json
import logging
import math
import random
import secrets
import time

from aiohttp import web

import db
from config import GAME_VIP_DAYS, GAME_VIP_PRICE

# ── O'yin balansi ──
UPGRADES = {
    # kalit: (nomi, maksimal daraja, birinchi daraja narxi)
    "engine":   ("Dvigatel", 5, 150),
    "nitro":    ("Nitro", 5, 200),
    "handling": ("Boshqaruv", 5, 120),
}
CARS = {
    # kalit: (marka va model, narxi tangada, VIP uchun bepul). Markalar o'ylab topilgan (haqiqiy brendlar emas).
    "scooter": ("⚡ Volt elektr skuteri", 0, False),       # har bir yangi o'yinchiga
    "hatch":   ("Turon Mini", 1500, False),
    "sedan":   ("Afrosiyob Sedan", 3000, False),
    "taxi":    ("Afrosiyob Taksi", 3500, False),
    "van":     ("Ipak Yo'li Van", 4500, False),
    "suv":     ("Pomir 4x4", 7000, False),
    "suvlux":  ("Registon Luxe", 12000, False),
    "sport":   ("Samarqand GT", 22000, False),
    "super":   ("Oltin Burgut Superkar", 60000, True),
}
# Bu vaqtdan oldin o'ynay boshlaganlar oldin bepul berilgan sedanni saqlab qoladi
CARS_CUTOFF = 1794371218
STARTER_CAR = "scooter"
# Personaj: har bir qism uchun variantlar narxi (0 = bepul, "vip" = faqat VIP uchun)
LOOK = {
    # Kenney personajlari (city3d.js dagi CHAR_FILES tartibida): 6 erkak, 6 ayol
    "char": [0, 0, 300, 400, 600, "vip", 0, 0, 300, 400, 600, "vip"],
    "acc":  [0, 200, 350, "vip", "vip"],           # yo'q, ko'zoynak, quyosh ko'zoynagi, toj, oltin zanjir
}
# Eski garderob (soch/kiyim) uchun sotib olingan buyumlar narxi — yangi tizimga o'tganda qaytariladi
OLD_LOOK_PRICES = {"hair:4": 300, "hair:5": 250, "hc:6": 150, "hc:7": 150, "top:1": 400, "top:2": 300}
# Mashina bo'yoqlari (city3d.js dagi PAINTS bilan bir xil tartib): oxirgi ikkitasi — oltin va xrom, faqat VIP
PAINT_PRICE = 150
PAINT_VIP = {12, 13}
PAINT_COUNT = 14
LOOK_DEFAULT = {"char": 0, "acc": 0}
# Topshiriq turlari bo'yicha mukofot (tanga) va tajriba
MISSION_REWARD = {"deliver": 50, "taxi": 70, "race": 90,
                  "ambulance": 110, "bus": 120, "truck": 100, "police": 140, "wedding": 120}
MISSION_XP = {"deliver": 20, "taxi": 28, "race": 35,
              "ambulance": 40, "bus": 45, "truck": 38, "police": 50, "wedding": 45}
PICKUP_COINS = 3
LEVEL_BONUS = 0.03           # har daraja uchun +3% tanga (maks. +60%)
# Kunlik bonus seriyasi: ketma-ket kunlar (48 soat ichida qaytsangiz seriya davom etadi)
DAILY_STREAK = [100, 150, 200, 250, 300, 400, 600]
# Donat: (narx so'mda, tanga). Birinchi xaridga +50%, VIP'ga +10%
COIN_PACKS = [(10000, 2200), (25000, 6000), (50000, 13000), (100000, 30000)]
FIRST_BUY_BONUS = 0.5
VIP_COIN_BONUS = 0.1
VIP_MULT = 2                 # VIP tanga ko'paytiruvchisi
DAILY = 100                  # kunlik bonus
DAILY_VIP = 300
DAILY_EVERY = 20 * 3600
SESSION_MAX = 2 * 3600
_sessions = {}               # sid -> (uid, mode, started)


def level(xp):
    return int(math.sqrt(max(xp, 0) / 100)) + 1


def upgrade_cost(key, lvl):
    return UPGRADES[key][2] * (lvl + 1)


def is_vip(p):
    return (p.get("vip_until") or 0) > time.time()


def _data(p):
    try:
        d = json.loads(p.get("data") or "{}")
    except ValueError:
        d = {}
    d.setdefault("up", {})
    old = (p.get("created") or 0) < CARS_CUTOFF
    d.setdefault("cars", [STARTER_CAR] + (["sedan"] if old else []))
    if STARTER_CAR not in d["cars"]:
        d["cars"].insert(0, STARTER_CAR)
    d.setdefault("car", "sedan" if old else STARTER_CAR)
    d.setdefault("owned", [])
    d.setdefault("paint", {})
    d["look"] = {**LOOK_DEFAULT, **{k: v for k, v in (d.get("look") or {}).items() if k in LOOK}}
    return d


def clean_look(d, vip):
    """Saqlangan ko'rinish — VIP tugagan bo'lsa VIP buyumlari standartga qaytadi."""
    out = {}
    for k, opts in LOOK.items():
        v = d["look"].get(k, LOOK_DEFAULT[k])
        if not isinstance(v, int) or not 0 <= v < len(opts) or (opts[v] == "vip" and not vip):
            v = LOOK_DEFAULT[k]
        out[k] = v
    return out


def migrate_look(uid, p, d):
    """Eski garderob buyumlari tangasini bir marta qaytarish (look_v=2)."""
    if d.get("look_v") == 2:
        return p, d
    refund = sum(OLD_LOOK_PRICES.get(k, 0) for k in d["owned"])
    d["owned"] = [k for k in d["owned"] if k.startswith("acc:")]
    d["look"] = {"char": 0, "acc": d["look"].get("acc", 0)}
    d["look_v"] = 2
    db.game_save(uid, data=json.dumps(d))
    if refund:
        db.game_add(uid, coins=refund, kind="refund", note="eski garderob")
        p = db.game_profile(uid)
    return p, d


def view(uid):
    p = db.game_profile(uid)
    d = _data(p)
    p, d = migrate_look(uid, p, d)
    vip = is_vip(p)
    if d["car"] not in d["cars"] and not (d["car"] == "super" and vip):
        d["car"] = STARTER_CAR
    now = int(time.time())
    return {
        "coins": p["coins"], "xp": p["xp"], "level": level(p["xp"]),
        "next_xp": (level(p["xp"])) ** 2 * 100,
        "games": p["games"], "wins": p["wins"],
        "vip": vip, "vip_until": p["vip_until"],
        "daily_in": max(0, (p["last_daily"] or 0) + DAILY_EVERY - now),
        "up": d["up"], "cars": d["cars"] + (["super"] if vip else []), "car": d["car"],
        "look": clean_look(d, vip), "owned": d["owned"],
        "paint": {k: v for k, v in d["paint"].items() if vip or v not in PAINT_VIP},
        "balance": db.balance(uid),
        "daily_day": daily_next(d, p, vip, now)[0], "daily_amount": daily_next(d, p, vip, now)[1],
        "level_bonus": round(level_bonus(p["xp"]) * 100),
        "first_buy": db.game_coin_purchases(uid) == 0,
    }


def shop():
    return {
        "vip_price": GAME_VIP_PRICE, "vip_days": GAME_VIP_DAYS, "vip_mult": VIP_MULT,
        "daily": DAILY, "daily_vip": DAILY_VIP,
        "upgrades": {k: {"name": n, "max": m, "costs": [b * (i + 1) for i in range(m)]}
                     for k, (n, m, b) in UPGRADES.items()},
        "cars": {k: {"name": n, "price": pr, "vip": v} for k, (n, pr, v) in CARS.items()},
        "look": LOOK, "paint_price": PAINT_PRICE, "paint_vip": sorted(PAINT_VIP),
        "missions": MISSION_REWARD, "pickup": PICKUP_COINS, "daily_streak": DAILY_STREAK,
        "packs": [{"price": pr, "coins": c} for pr, c in COIN_PACKS],
        "first_bonus": FIRST_BUY_BONUS, "vip_coin_bonus": VIP_COIN_BONUS,
    }


def level_bonus(xp):
    return min(0.6, LEVEL_BONUS * (level(xp) - 1))


def calc_reward(mode, body, elapsed, vip, xp=0):
    """(tanga, xp, bajarilgan topshiriqlar) — server o'lchagan vaqt bo'yicha cheklangan."""
    if mode != "city":
        return 0, 0, 0
    m = body.get("missions") or {}
    if not isinstance(m, dict):                       # eski mijozlar: faqat son
        m = {"deliver": m}
    counts = {k: max(int(m.get(k) or 0), 0) for k in MISSION_REWARD}
    total, cap = sum(counts.values()), int(elapsed // 8)
    if total > cap:                                   # vaqtga sig'maydigan topshiriqlar kesiladi
        k = cap / total
        counts = {t: int(n * k) for t, n in counts.items()}
        total = sum(counts.values())
    pickups = min(max(int(body.get("pickups") or 0), 0), int(elapsed))
    coins = sum(MISSION_REWARD[t] * n for t, n in counts.items()) + pickups * PICKUP_COINS
    coins = int(coins * (1 + level_bonus(xp)))
    coins = min(coins, int(elapsed * 8) + 40, 4000)
    xp_ = sum(MISSION_XP[t] * n for t, n in counts.items()) + min(int(elapsed // 10), 120)
    if vip:
        coins *= VIP_MULT
    return coins, xp_, total


def coin_pack(i, first, vip):
    price, coins = COIN_PACKS[i]
    bonus = (FIRST_BUY_BONUS if first else 0) + (VIP_COIN_BONUS if vip else 0)
    return price, int(coins * (1 + bonus))


def daily_next(d, p, vip, now):
    """Keyingi kunlik bonus: (seriya kuni 1..7, tanga)."""
    last = p.get("last_daily") or 0
    streak = int(d.get("streak") or 0)
    day = streak % len(DAILY_STREAK) + 1 if last and now - last < 48 * 3600 else 1
    amount = DAILY_STREAK[day - 1] * (VIP_MULT if vip else 1)
    return day, amount


# ── HTTP ──
def setup(r, auth, ok, err, on_vip=None, verify=None, on_coins=None):
    async def me(request):
        user, _ = await auth(request)
        return ok(profile=view(user["id"]), shop=shop())

    async def start(request):
        user, body = await auth(request)
        mode = body.get("mode")
        if mode != "city":
            return err("Noma'lum rejim")
        now = time.time()
        for k in [k for k, v in _sessions.items() if v[0] == user["id"] or now - v[2] > SESSION_MAX]:
            _sessions.pop(k, None)
        sid = secrets.token_hex(12)
        _sessions[sid] = (user["id"], mode, now)
        return ok(sid=sid)

    async def reward(request):
        user, body = await auth(request)
        s = _sessions.pop(body.get("sid") or "", None)
        if not s or s[0] != user["id"]:
            return err("O'yin sessiyasi topilmadi")
        elapsed = min(time.time() - s[2], SESSION_MAX)
        p = db.game_profile(user["id"])
        coins, xp, win = calc_reward(s[1], body, elapsed, is_vip(p), p["xp"])
        old_lvl = level(p["xp"])
        db.game_add(user["id"], coins=coins, xp=xp, games=1, wins=win, kind="game", note=f"{win} topshiriq, {int(elapsed)} s")
        v = view(user["id"])
        return ok(coins=coins, xp=xp, win=win, level_up=v["level"] > old_lvl, profile=v)

    async def daily(request):
        user, _ = await auth(request)
        p = db.game_profile(user["id"])
        now = int(time.time())
        if (p["last_daily"] or 0) + DAILY_EVERY > now:
            return err("Kunlik bonus hali tayyor emas")
        d = _data(p)
        day, amount = daily_next(d, p, is_vip(p), now)
        d["streak"] = day
        db.game_save(user["id"], last_daily=now, data=json.dumps(d))
        db.game_add(user["id"], coins=amount, kind="daily", note=f"{day}-kun")
        return ok(coins=amount, day=day, profile=view(user["id"]))

    async def upgrade(request):
        user, body = await auth(request)
        key = body.get("key")
        if key not in UPGRADES:
            return err("Noma'lum yaxshilash")
        p = db.game_profile(user["id"])
        d = _data(p)
        lvl = int(d["up"].get(key, 0))
        if lvl >= UPGRADES[key][1]:
            return err("Maksimal daraja")
        cost = upgrade_cost(key, lvl)
        d["up"][key] = lvl + 1
        if not db.game_spend(user["id"], cost, json.dumps(d), "upgrade", f"{key} {lvl + 1}-daraja"):
            return err("Tanga yetarli emas")
        return ok(profile=view(user["id"]))

    async def car(request):
        user, body = await auth(request)
        key = body.get("key")
        if key not in CARS:
            return err("Noma'lum mashina")
        p = db.game_profile(user["id"])
        d = _data(p)
        name, price, vip_free = CARS[key]
        if key in d["cars"] or (vip_free and is_vip(p)):
            d["car"] = key
            db.game_save(user["id"], data=json.dumps(d))
        else:
            d["cars"].append(key)
            d["car"] = key
            if not db.game_spend(user["id"], price, json.dumps(d), "car", key):
                return err("Tanga yetarli emas")
        return ok(profile=view(user["id"]))

    async def vip(request):
        user, _ = await auth(request)
        until, e = db.game_buy_vip(user["id"], GAME_VIP_PRICE, GAME_VIP_DAYS)
        if e:
            return err(e)
        if on_vip:
            await on_vip(user, until)
        return ok(profile=view(user["id"]))

    async def look(request):
        user, body = await auth(request)
        new = body.get("look") or {}
        p = db.game_profile(user["id"])
        p, d = migrate_look(user["id"], p, _data(p))
        vip = is_vip(p)
        cost, buy, look_ = 0, [], {}
        for k, opts in LOOK.items():
            v = new.get(k, LOOK_DEFAULT[k])
            if not isinstance(v, int) or not 0 <= v < len(opts):
                return err("Noto'g'ri tanlov")
            price = opts[v]
            if price == "vip" and not vip:
                return err("Bu buyum faqat VIP uchun")
            if isinstance(price, int) and price > 0 and f"{k}:{v}" not in d["owned"]:
                cost += price
                buy.append(f"{k}:{v}")
            look_[k] = v
        d["look"] = look_
        d["owned"] += buy
        if cost:
            if not db.game_spend(user["id"], cost, json.dumps(d), "look", ",".join(buy)):
                return err("Tanga yetarli emas")
        else:
            db.game_save(user["id"], data=json.dumps(d))
        return ok(profile=view(user["id"]), spent=cost)

    async def paint(request):
        user, body = await auth(request)
        car, color = body.get("car"), body.get("color")
        p = db.game_profile(user["id"])
        d = _data(p)
        vip = is_vip(p)
        if car not in CARS or not (car in d["cars"] or (car == "super" and vip)):
            return err("Bu mashina sizda yo'q")
        if not isinstance(color, int) or not 0 <= color < PAINT_COUNT:
            return err("Noto'g'ri rang")
        if color in PAINT_VIP and not vip:
            return err("Bu rang faqat VIP uchun")
        d["paint"][car] = color
        cost = 0 if color in PAINT_VIP else PAINT_PRICE
        if cost:
            if not db.game_spend(user["id"], cost, json.dumps(d), "paint", f"{car} #{color}"):
                return err("Tanga yetarli emas")
        else:
            db.game_save(user["id"], data=json.dumps(d))
        return ok(profile=view(user["id"]), spent=cost)

    async def coins(request):
        user, body = await auth(request)
        i = body.get("pack")
        if not isinstance(i, int) or not 0 <= i < len(COIN_PACKS):
            return err("Noto'g'ri paket")
        p = db.game_profile(user["id"])
        price, amount = coin_pack(i, db.game_coin_purchases(user["id"]) == 0, is_vip(p))
        total, e = db.game_buy_coins(user["id"], price, amount)
        if e:
            return err(e)
        if on_coins:
            await on_coins(user, price, amount)
        return ok(coins=amount, profile=view(user["id"]))

    async def top(request):
        rows = db.game_top(30)
        now = time.time()
        return web.json_response([{"name": (x["full_name"] or x["username"] or "O'yinchi")[:20],
                                   "level": level(x["xp"]), "xp": x["xp"], "wins": x["wins"],
                                   "vip": (x["vip_until"] or 0) > now} for x in rows])

    async def shop_h(request):
        return web.json_response(shop())

    r.add_post("/api/game/me", me)
    r.add_post("/api/game/start", start)
    r.add_post("/api/game/reward", reward)
    r.add_post("/api/game/daily", daily)
    r.add_post("/api/game/upgrade", upgrade)
    r.add_post("/api/game/car", car)
    r.add_post("/api/game/vip", vip)
    r.add_post("/api/game/look", look)
    r.add_post("/api/game/paint", paint)
    r.add_post("/api/game/coins", coins)
    if verify:
        async def ws_h(request):
            return await ws_city(request, verify)
        r.add_get("/ws/city", ws_h)
    r.add_get("/api/game/top", top)
    r.add_get("/api/game/shop", shop_h)


# ═════════════ ONLAYN SHAHAR (WebSocket) ═════════════
# Bir xonada 25 tagacha o'yinchi bir-birini ko'radi. Har bir mijoz o'z holatini ~10 marta/soniya
# yuboradi, server esa xonadagi hamma holatlarni 10 marta/soniya tarqatadi.
ROOM_MAX = 25
WORLD = 14 * 60 + 14          # 854 m — city3d.js dagi N=14 bilan bir xil
CAR_TYPES = {"", "scooter", "sedan", "taxi", "suv", "sport", "super", "van", "bus", "police", "hatch", "suvlux", "delivery", "truck", "ambulance"}
CHAT = 8                     # tayyor iboralar soni (mijozda)
_rooms = []                  # [{cid: Client}]
_by_uid = {}
_next_id = [1]
_loop = [None]


RACE_COINS = 150             # g'olibga (VIP — ×2)
RACE_XP = 60
RACE_DAILY = 20              # sutkada tanga beriladigan g'alabalar soni
RACE_TIMEOUT = 240
_races = []
_invites = {}                # (kimdan, kimga) -> vaqt
_race_wins = {}              # uid -> [vaqtlar]


def _road_point(rng):
    k = rng.randint(0, 14)
    along, off = rng.uniform(15, WORLD - 15), rng.uniform(-3, 3)
    c = k * 60 + 7
    return [round(along, 1), round(c + off, 1)] if rng.random() < 0.5 else [round(c + off, 1), round(along, 1)]


def _race_points(x, z, n=5):
    rng, pts = random.Random(), []
    for _ in range(n):
        p = _road_point(rng)
        for _ in range(150):
            if 90 <= math.hypot(p[0] - x, p[1] - z) <= 160:
                break
            p = _road_point(rng)
        pts.append(p)
        x, z = p
    return pts


class Race:
    def __init__(self, a, b, pts):
        self.a, self.b, self.pts = a, b, pts
        self.start = time.time() + 4
        self.prog = {a.id: 0, b.id: 0}
        self.done = False


async def _race_end(race, winner=None, reason=""):
    if race.done:
        return
    race.done = True
    if race in _races:
        _races.remove(race)
    coins = 0
    if winner:
        now = time.time()
        wins = [t for t in _race_wins.get(winner.uid, []) if now - t < 86400]
        if len(wins) < RACE_DAILY:
            p = db.game_profile(winner.uid)
            coins = RACE_COINS * (VIP_MULT if is_vip(p) else 1)
            db.game_add(winner.uid, coins=coins, xp=RACE_XP, kind="race", note="onlayn poyga g'alabasi")
            wins.append(now)
        _race_wins[winner.uid] = wins
    msg = json.dumps({"t": "re", "winner": winner.id if winner else None, "name": winner.name if winner else "",
                      "coins": coins, "reason": reason})
    for c in (race.a, race.b):
        if c.race is race:
            c.race = None
        await _send(c, msg)


async def _race_progress(c, x, z):
    race = c.race
    now = time.time()
    if not race or race.done or now < race.start:
        return
    i = race.prog[c.id]
    if i >= len(race.pts):
        return
    px, pz = race.pts[i]
    if math.hypot(x - px, z - pz) < 12:
        race.prog[c.id] = i + 1
        await _send(c, json.dumps({"t": "rp", "i": i + 1}))
        other = race.b if c is race.a else race.a
        await _send(other, json.dumps({"t": "ro", "i": i + 1}))
        if i + 1 >= len(race.pts):
            await _race_end(race, c)


class Client:
    __slots__ = ("id", "uid", "name", "look", "vip", "ws", "state", "room", "chat_t", "msg_t", "msgs",
                 "race", "inv_t", "last_pos")

    def __init__(self, uid, name, look, vip, ws):
        self.id = _next_id[0]
        _next_id[0] += 1
        self.uid, self.name, self.look, self.vip, self.ws = uid, name, look, vip, ws
        self.state, self.room, self.chat_t, self.msg_t, self.msgs = None, None, 0.0, time.time(), 0
        self.race, self.inv_t, self.last_pos = None, 0.0, None

    def info(self):
        return {"id": self.id, "name": self.name, "look": self.look, "vip": self.vip}


async def _send(c, data):
    try:
        await c.ws.send_str(data)
    except Exception:
        pass


async def _bcast(room, msg, skip=None):
    data = json.dumps(msg, separators=(",", ":"))
    await asyncio.gather(*[_send(c, data) for c in list(room.values()) if c is not skip])


async def _tick():
    while True:
        await asyncio.sleep(0.1)
        now = time.time()
        for race in list(_races):
            if now - race.start > RACE_TIMEOUT:
                await _race_end(race, None, "timeout")
        for k in [k for k, t in _invites.items() if now - t > 30]:
            _invites.pop(k, None)
        for room in list(_rooms):
            if len(room) < 2:
                continue
            snap = [[c.id, *c.state] for c in room.values() if c.state]
            if snap:
                await _bcast(room, {"t": "w", "p": snap})


def _num(v, lo, hi):
    v = float(v)
    if not math.isfinite(v):
        raise ValueError
    return round(min(max(v, lo), hi), 2)


async def ws_city(request, verify):
    ws = web.WebSocketResponse(heartbeat=25, max_msg_size=4096)
    await ws.prepare(request)
    c = None
    try:
        first = await ws.receive(timeout=10)
        hello = json.loads(first.data) if first.type == web.WSMsgType.TEXT else {}
        user = verify(hello.get("initData", "")) if hello.get("t") == "hello" else None
        u = db.get_user(user["id"]) if user else None
        if not u or u["banned"]:
            await ws.close(code=4001, message=b"auth")
            return ws
        p = db.game_profile(u["id"])
        vip = is_vip(p)
        name = (u["full_name"] or u["username"] or "O'yinchi").strip()[:16]
        c = Client(u["id"], name, clean_look(_data(p), vip), vip, ws)
        old = _by_uid.get(u["id"])
        if old:
            await old.ws.close(code=4002, message=b"other")
        room = next((r for r in _rooms if len(r) < ROOM_MAX), None)
        if room is None:
            room = {}
            _rooms.append(room)
        others = [x.info() for x in room.values()]
        room[c.id] = c
        c.room = room
        _by_uid[u["id"]] = c
        if _loop[0] is None or _loop[0].done():
            _loop[0] = asyncio.create_task(_tick())
        await ws.send_str(json.dumps({"t": "welcome", "id": c.id, "players": others}))
        await _bcast(room, {"t": "j", **c.info()}, skip=c)
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            now = time.time()
            if now - c.msg_t > 1:
                c.msg_t, c.msgs = now, 0
            c.msgs += 1
            if c.msgs > 40:                 # sekundiga 40 dan ko'p xabar — e'tiborsiz
                continue
            try:
                m = json.loads(msg.data)
                if m.get("t") == "s":
                    x, z, y, yaw, sp, ct, cc, cy = m["p"]
                    ct = ct if ct in CAR_TYPES else ""
                    c.state = [_num(x, 0, WORLD), _num(z, 0, WORLD), _num(y, 0, 5), _num(yaw, -10, 10), _num(sp, 0, 80),
                               ct, int(cc) & 0xFFFFFF, _num(cy, -10, 10)]
                    # teleportni sezish: oxirgi ishonchli nuqtadan 65 m/s dan tez siljish qabul qilinmaydi
                    # (eng tez mashina nitro bilan ~62 m/s), ishonchli nuqta faqat qabul qilinganda yangilanadi
                    lp = c.last_pos
                    if not lp or math.hypot(c.state[0] - lp[0], c.state[1] - lp[1]) <= 65 * (now - lp[2]) + 2:
                        c.last_pos = (c.state[0], c.state[1], now)
                        await _race_progress(c, c.state[0], c.state[1])
                elif m.get("t") == "ri":                      # poygaga taklif
                    o = room.get(int(m.get("to", 0)))
                    if not o or o is c or now - c.inv_t < 3:
                        continue
                    c.inv_t = now
                    err_ = ("Siz poygadasiz" if c.race else "U hozir poygada" if o.race
                            else "Avval mashinaga o'tiring" if not (c.state and c.state[5]) else
                            "Juda uzoqdasiz (60 m dan yaqin keling)" if not o.state or
                            math.hypot(c.state[0] - o.state[0], c.state[1] - o.state[1]) > 60 else "")
                    if err_:
                        await _send(c, json.dumps({"t": "info", "m": err_}))
                        continue
                    _invites[(c.id, o.id)] = now
                    await _send(o, json.dumps({"t": "ri", "from": c.id, "name": c.name}))
                    await _send(c, json.dumps({"t": "info", "m": f"{o.name} ga taklif yuborildi"}))
                elif m.get("t") == "ra":                      # taklifni qabul qilish
                    o = room.get(int(m.get("to", 0)))
                    if not o or not _invites.pop((o.id, c.id), None):
                        await _send(c, json.dumps({"t": "info", "m": "Taklif eskirgan"}))
                        continue
                    if c.race or o.race or not (c.state and c.state[5]) or not (o.state and o.state[5]):
                        await _send(c, json.dumps({"t": "info", "m": "Ikkalangiz ham mashinada bo'lishingiz kerak"}))
                        continue
                    race = Race(o, c, _race_points(o.state[0], o.state[1]))
                    _races.append(race)
                    o.race = c.race = race
                    for me, vs in ((o, c), (c, o)):
                        await _send(me, json.dumps({"t": "rs", "pts": race.pts, "in": 4, "vs": vs.name, "vs_id": vs.id}))
                elif m.get("t") == "rq" and c.race:          # poygadan chiqish
                    other = c.race.b if c is c.race.a else c.race.a
                    await _race_end(c.race, None, "quit")
                    await _send(other, json.dumps({"t": "info", "m": f"{c.name} poygadan chiqdi"}))
                elif m.get("t") == "c":
                    i = int(m.get("m"))
                    if 0 <= i < CHAT and now - c.chat_t > 2:
                        c.chat_t = now
                        await _bcast(room, {"t": "c", "id": c.id, "m": i})
            except (ValueError, TypeError, KeyError):
                continue
    except (asyncio.TimeoutError, ValueError, TypeError):
        pass
    except Exception as e:
        logging.warning("ws_city: %s", e)
    finally:
        if c and c.race:
            await _race_end(c.race, None, "left")
        if c and c.room is not None:
            c.room.pop(c.id, None)
            if _by_uid.get(c.uid) is c:
                _by_uid.pop(c.uid, None)
            if not c.room and c.room in _rooms:
                _rooms.remove(c.room)
            else:
                await _bcast(c.room, {"t": "l", "id": c.id})
    return ws
