"""Shahar Arena — Mini App ichidagi o'yin: server tomoni.

Tangalar, tajriba (XP), yaxshilashlar va oylik VIP obuna shu yerda hisoblanadi.
Mukofot vaqtini server o'zi o'lchaydi (start → reward), shuning uchun mijoz tomonidan
soxta natija yuborib cheksiz tanga yig'ib bo'lmaydi.
"""
import asyncio
import json
import logging
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
# Personaj: har bir qism uchun variantlar narxi (0 = bepul, "vip" = faqat VIP uchun)
LOOK = {
    "skin": [0, 0, 0, 0, 0],                       # teri rangi
    "hair": [0, 0, 0, 0, 300, 250],                # qisqa, uzun, kepka, kal, irokez, jingalak
    "hc":   [0, 0, 0, 0, 0, 0, 150, 150],          # soch rangi (oxirgi 2 — yorqin)
    "top":  [0, 400, 300, "vip"],                  # futbolka, kurtka, xudi, oltin pidjak
    "tc":   [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "vip"],  # kiyim rangi (oxirgisi — oltin)
    "pc":   [0, 0, 0, 0, 0, 0],                    # shim rangi
    "acc":  [0, 200, 350, "vip", "vip"],           # yo'q, ko'zoynak, quyosh ko'zoynagi, toj, oltin zanjir
}
LOOK_DEFAULT = {"skin": 1, "hair": 0, "hc": 0, "top": 0, "tc": 1, "pc": 0, "acc": 0}
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
    d.setdefault("owned", [])
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
        "look": clean_look(d, vip), "owned": d["owned"],
        "balance": db.balance(uid),
    }


def shop():
    return {
        "vip_price": GAME_VIP_PRICE, "vip_days": GAME_VIP_DAYS, "vip_mult": VIP_MULT,
        "daily": DAILY, "daily_vip": DAILY_VIP,
        "upgrades": {k: {"name": n, "max": m, "costs": [b * (i + 1) for i in range(m)]}
                     for k, (n, m, b) in UPGRADES.items()},
        "cars": {k: {"name": n, "price": pr, "vip": v} for k, (n, pr, v) in CARS.items()},
        "look": LOOK,
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
def setup(r, auth, ok, err, on_vip=None, verify=None):
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

    async def look(request):
        user, body = await auth(request)
        new = body.get("look") or {}
        p = db.game_profile(user["id"])
        d = _data(p)
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
            if not db.game_spend(user["id"], cost, json.dumps(d)):
                return err("Tanga yetarli emas")
        else:
            db.game_save(user["id"], data=json.dumps(d))
        return ok(profile=view(user["id"]), spent=cost)

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
WORLD = 494
CAR_TYPES = {"", "sedan", "taxi", "suv", "sport", "super", "van"}
CHAT = 8                     # tayyor iboralar soni (mijozda)
_rooms = []                  # [{cid: Client}]
_by_uid = {}
_next_id = [1]
_loop = [None]


class Client:
    __slots__ = ("id", "uid", "name", "look", "vip", "ws", "state", "room", "chat_t", "msg_t", "msgs")

    def __init__(self, uid, name, look, vip, ws):
        self.id = _next_id[0]
        _next_id[0] += 1
        self.uid, self.name, self.look, self.vip, self.ws = uid, name, look, vip, ws
        self.state, self.room, self.chat_t, self.msg_t, self.msgs = None, None, 0.0, time.time(), 0

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
        if c and c.room is not None:
            c.room.pop(c.id, None)
            if _by_uid.get(c.uid) is c:
                _by_uid.pop(c.uid, None)
            if not c.room and c.room in _rooms:
                _rooms.remove(c.room)
            else:
                await _bcast(c.room, {"t": "l", "id": c.id})
    return ws
