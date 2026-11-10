"""Shahar Arena — Mini App ichidagi o'yin: server tomoni.

Tangalar, tajriba (XP), yaxshilashlar va oylik VIP obuna shu yerda hisoblanadi.
Mukofot vaqtini server o'zi o'lchaydi (start → reward), shuning uchun mijoz tomonidan
soxta natija yuborib cheksiz tanga yig'ib bo'lmaydi.
"""
import json
import math
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
    "f_speed":  ("Futbolchilar tezligi", 5, 150),
    "f_shot":   ("Zarba kuchi", 5, 150),
    "f_keeper": ("Darvozabon", 5, 150),
}
CARS = {
    # kalit: (nomi, narxi tangada, faqat VIP)
    "sedan": ("Shahar sedani", 0, False),
    "taxi":  ("Taksi", 800, False),
    "suv":   ("Yo'ltanlamas", 1500, False),
    "sport": ("Sport kupe", 3000, False),
    "super": ("Oltin superkar", 0, True),
}
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
    d.setdefault("cars", ["sedan"])
    d.setdefault("car", "sedan")
    return d


def view(uid):
    p = db.game_profile(uid)
    d = _data(p)
    vip = is_vip(p)
    if d["car"] not in d["cars"] and not (d["car"] == "super" and vip):
        d["car"] = "sedan"
    now = int(time.time())
    return {
        "coins": p["coins"], "xp": p["xp"], "level": level(p["xp"]),
        "next_xp": (level(p["xp"])) ** 2 * 100,
        "games": p["games"], "wins": p["wins"],
        "vip": vip, "vip_until": p["vip_until"],
        "daily_in": max(0, (p["last_daily"] or 0) + DAILY_EVERY - now),
        "up": d["up"], "cars": d["cars"] + (["super"] if vip else []), "car": d["car"],
        "balance": db.balance(uid),
    }


def shop():
    return {
        "vip_price": GAME_VIP_PRICE, "vip_days": GAME_VIP_DAYS, "vip_mult": VIP_MULT,
        "daily": DAILY, "daily_vip": DAILY_VIP,
        "upgrades": {k: {"name": n, "max": m, "costs": [b * (i + 1) for i in range(m)]}
                     for k, (n, m, b) in UPGRADES.items()},
        "cars": {k: {"name": n, "price": pr, "vip": v} for k, (n, pr, v) in CARS.items()},
    }


def calc_reward(mode, body, elapsed, vip):
    """(tanga, xp, g'alaba) — server o'lchagan vaqt bo'yicha cheklangan."""
    win = 0
    if mode == "city":
        missions = min(max(int(body.get("missions") or 0), 0), int(elapsed // 8))
        pickups = min(max(int(body.get("pickups") or 0), 0), int(elapsed))
        coins = missions * 60 + pickups * 3
        coins = min(coins, int(elapsed * 6) + 30, 3000)
        xp = missions * 25 + min(int(elapsed // 10), 120)
    elif mode == "football":
        if elapsed < 30:
            return 0, 0, 0
        gf = min(max(int(body.get("gf") or 0), 0), int(elapsed // 6))
        ga = min(max(int(body.get("ga") or 0), 0), 30)
        full = elapsed >= 100
        if gf > ga and full:
            coins, xp, win = 60, 70, 1
        elif gf == ga and full:
            coins, xp = 25, 40
        else:
            coins, xp = 10, 20
        coins += gf * 10
    else:
        return 0, 0, 0
    if vip:
        coins *= VIP_MULT
    return coins, xp, win


# ── HTTP ──
def setup(r, auth, ok, err, on_vip=None):
    async def me(request):
        user, _ = await auth(request)
        return ok(profile=view(user["id"]), shop=shop())

    async def start(request):
        user, body = await auth(request)
        mode = body.get("mode")
        if mode not in ("city", "football"):
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
        coins, xp, win = calc_reward(s[1], body, elapsed, is_vip(p))
        old_lvl = level(p["xp"])
        db.game_add(user["id"], coins=coins, xp=xp, games=1, wins=win)
        v = view(user["id"])
        return ok(coins=coins, xp=xp, win=win, level_up=v["level"] > old_lvl, profile=v)

    async def daily(request):
        user, _ = await auth(request)
        p = db.game_profile(user["id"])
        now = int(time.time())
        if (p["last_daily"] or 0) + DAILY_EVERY > now:
            return err("Kunlik bonus hali tayyor emas")
        amount = DAILY_VIP if is_vip(p) else DAILY
        db.game_save(user["id"], last_daily=now)
        db.game_add(user["id"], coins=amount)
        return ok(coins=amount, profile=view(user["id"]))

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
        if not db.game_spend(user["id"], cost, json.dumps(d)):
            return err("Tanga yetarli emas")
        return ok(profile=view(user["id"]))

    async def car(request):
        user, body = await auth(request)
        key = body.get("key")
        if key not in CARS:
            return err("Noma'lum mashina")
        p = db.game_profile(user["id"])
        d = _data(p)
        name, price, vip_only = CARS[key]
        if vip_only:
            if not is_vip(p):
                return err("Bu mashina faqat VIP uchun")
            d["car"] = key
            db.game_save(user["id"], data=json.dumps(d))
        elif key in d["cars"]:
            d["car"] = key
            db.game_save(user["id"], data=json.dumps(d))
        else:
            d["cars"].append(key)
            d["car"] = key
            if not db.game_spend(user["id"], price, json.dumps(d)):
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
    r.add_get("/api/game/top", top)
    r.add_get("/api/game/shop", shop_h)
