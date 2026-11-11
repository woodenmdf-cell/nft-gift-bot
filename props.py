"""Shahar Arena — ko'chmas mulk: binolarni sotib olish, soatlik daromad va xavfsiz savdo (escrow).

Binolar ro'yxati shahar generatori bilan bir xil (webapp/city3d.js dagi gen() ning aniq nusxasi):
bir xil urug' (seed) va bir xil tasodifiy sonlar ketma-ketligi — har bir bino id si `i-j-k`
(kvartal ustuni, qatori va kvartal ichidagi tartib raqami). Mos kelishi tests/test_props_layout.js da tekshiriladi.

Savdo xavfsizligi: har bir bitim bitta SQLite tranzaksiyasida (BEGIN IMMEDIATE) bajariladi —
tanga yechilishi, sotuvchiga o'tishi va egalik o'zgarishi birga bo'ladi yoki umuman bo'lmaydi.
Sotuvchi e'lonni bekor qilsa yoki bino boshqa qo'lga o'tsa, eski e'lon bilan sotib bo'lmaydi.
"""
import math
import time

from aiohttp import web

import db

# ── shahar o'lchamlari (city3d.js bilan bir xil) ──
N, BL, RD = 14, 46, 14
CELL = BL + RD
WORLD = N * CELL + RD
SW = 2.6
SEED = 90210
KB_H = [0.95, 1.25, 1.75, 1.25, 0.55]                 # Kenney binolari balandligi (model birligida)
KB_NAME = ["Kichik uy", "Do'kon", "Ofis binosi", "Turar-joy", "Garaj"]
KB_PRICE = [1200, 1800, 3000, 1800, 600]
SPECIAL_BLOCKS = {(6, 6), (10, 3), (4, 9), (9, 9), (11, 11)}
DISTRICTS = [["Olmazor", "Shayxontohur", "Yunusobod", "Qoraqamish"], ["Chilonzor", "Markaz", "Mirzo Ulug'bek", "Yashnobod"],
             ["Uchtepa", "Yakkasaroy", "Mirobod", "Bektemir"], ["Sergeli", "Chorsu", "Beshyog'och", "Qo'yliq"]]

INCOME_RATE = 0.012          # soatiga narxning 1.2% i
INCOME_CAP_H = 12            # daromad 12 soatgacha yig'iladi
VIP_INCOME = 0.2             # VIP: +20% daromad
MAX_OWNED = 30
FEE = 0.05                   # bozor komissiyasi (tanga yo'qoladi — iqtisodni barqaror tutadi)
MIN_K, MAX_K = 0.5, 10       # e'lon narxi: asosiy narxning 50% ... 10 barobari


def _imul(a, b):
    return (a * b) & 0xFFFFFFFF


class _Rnd:
    """JS dagi srnd() (mulberry32) ning aniq nusxasi."""

    def __init__(self, seed):
        self.sd = seed & 0xFFFFFFFF

    def __call__(self):
        self.sd = (self.sd + 0x6D2B79F5) & 0xFFFFFFFF
        sd = self.sd
        t = _imul(sd ^ (sd >> 15), 1 | sd)
        t = ((t + _imul(t ^ (t >> 7), 61 | t)) & 0xFFFFFFFF) ^ t
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296


def district(x, z):
    gi = min(3, max(0, int(x / WORLD * 4)))
    gj = min(3, max(0, int(z / WORLD * 4)))
    return DISTRICTS[gj][gi]


def _r50(v):
    return int(round(v / 50.0)) * 50


def build_catalog():
    """id -> {name, price, income, x, z, w, d, h, district}"""
    rnd, mid, cat = _Rnd(SEED), WORLD / 2, {}
    _raw.clear()
    for j in range(N):
        for i in range(N):
            x, z, r = i * CELL + RD, j * CELL + RD, rnd()
            df = 1 - min(1, math.hypot(x + BL / 2 - mid, z + BL / 2 - mid) / (WORLD * 0.5))
            typ = "park" if r < 0.11 else "plaza" if r < 0.16 else "lot" if r < 0.23 else "build"
            solids = []
            if typ == "build" and df < 0.42:
                m = SW + 0.4
                tile = (BL - 2 * m) / 3
                for a in range(3):
                    for c in range(3):
                        if a == 1 and c == 1:
                            continue
                        mi = 4 if rnd() < 0.12 else int(rnd() * 4)
                        rnd()                                         # rang (PAL)
                        f, h = tile * 0.8, KB_H[mi] * tile
                        cx, cz = x + m + tile * (a + 0.5), z + m + tile * (c + 0.5)
                        base = KB_PRICE[mi]
                        solids.append((KB_NAME[mi], cx - f / 2, cz - f / 2, f, f, h, base * (1 + 0.5 * df)))
            elif typ == "build":
                m, g = SW + 0.8, 3
                S = BL - 2 * m
                sp = int(rnd() * 4)
                Hh = (S - g) / 2
                rects = ([[0, 0, S, S]] if sp == 0 else [[0, 0, S, Hh], [0, Hh + g, S, Hh]] if sp == 1 else
                         [[0, 0, Hh, S], [Hh + g, 0, Hh, S]] if sp == 2 else
                         [[0, 0, Hh, Hh], [Hh + g, 0, Hh, Hh], [0, Hh + g, Hh, Hh], [Hh + g, Hh + g, Hh, Hh]])
                for q in rects:
                    h = 7 + rnd() * 12 + df * df * rnd() * 75
                    rnd()                                             # rang (PAL)
                    name = "Osmono'par" if h > 45 else "Biznes markaz" if h > 22 else "Ofis binosi"
                    area = q[2] * q[3] / (S * S)
                    solids.append((name, x + m + q[0], z + m + q[1], q[2], q[3], h, (1500 + h * 110) * (0.6 + area) * (1 + 0.5 * df)))
            elif typ == "park":
                for _ in range(9):
                    rnd(); rnd()
            if (i, j) in SPECIAL_BLOCKS:
                continue
            for k, (name, sx, sz, w, d, h, price) in enumerate(solids):
                _raw[f"{i}-{j}-{k}"] = (sx + w / 2, sz + d / 2, h)
                price = _r50(price)
                cat[f"{i}-{j}-{k}"] = {"name": name, "price": price, "income": max(5, round(price * INCOME_RATE)),
                                       "x": round(sx + w / 2, 1), "z": round(sz + d / 2, 1), "w": round(w, 1), "d": round(d, 1),
                                       "h": round(h, 1), "district": district(sx + w / 2, sz + d / 2)}
    # noyob binolar
    for pid, name, (bi, bj), price, (ox, oz, w, d) in [
            ("S-fuel", "⛽ Yoqilg'i shoxobchasi", (4, 9), 20000, (9, 5, 28, 8)),
            ("S-fuel2", "⛽ Yoqilg'i shoxobchasi", (11, 11), 20000, (9, 5, 28, 8)),
            ("S-paint", "🎨 Bo'yash ustaxonasi", (9, 9), 25000, (7, 4, 32, 13)),
            ("S-tower", "📡 Teleminora", (10, 3), 60000, (BL / 2 - 5, BL / 2 - 5, 10, 10))]:
        bx, bz = bi * CELL + RD, bj * CELL + RD
        cat[pid] = {"name": name, "price": price, "income": round(price * INCOME_RATE * 1.25),
                    "x": bx + ox + w / 2, "z": bz + oz + d / 2, "w": w, "d": d, "h": 8, "district": district(bx + ox, bz + oz),
                    "special": True}
    return cat


_raw = {}


def layout_hash():
    """Binolar joylashuvining nazorat summasi — o'yindagi (city3d.js) bilan solishtiriladi."""
    acc = 0
    for k in sorted(_raw):
        x, z, h = _raw[k]
        acc = (acc * 31 + math.floor(x * 10) + math.floor(z * 10) * 7 + math.floor(h * 10) * 13) % 1000000007
    return f"{len(_raw)}:{acc}"


CATALOG = build_catalog()
LAYOUT = layout_hash()

SCHEMA = """
CREATE TABLE IF NOT EXISTS props(
  id TEXT PRIMARY KEY, owner INTEGER, bought_at INTEGER, last_collect INTEGER, paid INTEGER
);
CREATE INDEX IF NOT EXISTS ix_props_owner ON props(owner);
CREATE TABLE IF NOT EXISTS prop_listings(
  id INTEGER PRIMARY KEY AUTOINCREMENT, prop_id TEXT, seller INTEGER, price INTEGER, to_user INTEGER,
  status TEXT DEFAULT 'open',       -- open | sold | cancelled
  buyer INTEGER, created INTEGER, closed INTEGER
);
CREATE INDEX IF NOT EXISTS ix_listings_open ON prop_listings(status, prop_id);
"""


def init():
    with db.conn() as c:
        c.executescript(SCHEMA)


def _ledger(c, uid, delta, kind, note):
    if not delta:
        return
    row = c.execute("SELECT coins FROM game_profiles WHERE user_id=?", (uid,)).fetchone()
    c.execute("INSERT INTO game_ledger(user_id,delta,coins_after,kind,note,created) VALUES(?,?,?,?,?,?)",
              (uid, delta, row["coins"] if row else 0, kind, note, int(time.time())))


def _is_vip(c, uid):
    r = c.execute("SELECT vip_until FROM game_profiles WHERE user_id=?", (uid,)).fetchone()
    return bool(r and (r["vip_until"] or 0) > time.time())


def pending(prop, now, vip):
    hours = min(INCOME_CAP_H, max(0.0, (now - (prop["last_collect"] or now)) / 3600))
    return int(CATALOG[prop["id"]]["income"] * hours * (1 + (VIP_INCOME if vip else 0)))


def _settle(c, pid, now):
    """Bino egasiga yig'ilmagan daromadni o'tkazish (sotishdan oldin — hech kim zarar ko'rmaydi)."""
    p = c.execute("SELECT * FROM props WHERE id=?", (pid,)).fetchone()
    if not p or not p["owner"]:
        return 0
    amount = pending(dict(p), now, _is_vip(c, p["owner"]))
    if amount:
        c.execute("UPDATE game_profiles SET coins=coins+? WHERE user_id=?", (amount, p["owner"]))
        _ledger(c, p["owner"], amount, "prop_income", CATALOG[pid]["name"])
    c.execute("UPDATE props SET last_collect=? WHERE id=?", (now, pid))
    return amount


def short_name(u):
    return ((u.get("full_name") or u.get("username") or "O'yinchi") if u else "O'yinchi").strip()[:16]


# ═════════════ HTTP ═════════════
def setup(r, auth, ok, err, notify=None):
    init()

    async def catalog(request):
        return web.json_response({"props": {k: [v["price"], v["income"], v["name"], v["district"]] for k, v in CATALOG.items()},
                                  "rate": INCOME_RATE, "cap_h": INCOME_CAP_H, "vip_bonus": VIP_INCOME,
                                  "max_owned": MAX_OWNED, "layout": LAYOUT, "fee": FEE, "min_k": MIN_K, "max_k": MAX_K})

    async def state(request):
        user, _ = await auth(request)
        uid, now = user["id"], int(time.time())
        with db.conn() as c:
            vip = _is_vip(c, uid)
            owned = c.execute("SELECT p.id, p.owner, u.full_name, u.username FROM props p LEFT JOIN users u ON u.id=p.owner "
                              "WHERE p.owner IS NOT NULL").fetchall()
            mine = [dict(x) for x in c.execute("SELECT * FROM props WHERE owner=?", (uid,)).fetchall()]
            lst = c.execute("SELECT l.*, u.full_name, u.username FROM prop_listings l LEFT JOIN users u ON u.id=l.seller "
                            "WHERE l.status='open' ORDER BY l.id DESC LIMIT 300").fetchall()
        listing_of = {x["prop_id"]: x for x in lst}
        out_owned = {x["id"]: [short_name(dict(x)), 1 if x["owner"] == uid else 0,
                               listing_of[x["id"]]["price"] if x["id"] in listing_of and not listing_of[x["id"]]["to_user"] else 0]
                     for x in owned}
        out_mine = [{"id": p["id"], "pending": pending(p, now, vip), "paid": p["paid"],
                     "listing": ({"id": listing_of[p["id"]]["id"], "price": listing_of[p["id"]]["price"], "to": listing_of[p["id"]]["to_user"]}
                                 if p["id"] in listing_of else None)} for p in mine]
        out_list = [{"id": x["id"], "prop": x["prop_id"], "price": x["price"], "seller": short_name(dict(x)),
                     "private": bool(x["to_user"]), "for_me": x["to_user"] == uid}
                    for x in lst if x["seller"] != uid and (not x["to_user"] or x["to_user"] == uid)]
        return ok(owned=out_owned, mine=out_mine, listings=out_list, vip=vip,
                  income_h=int(sum(CATALOG[p["id"]]["income"] for p in mine) * (1 + (VIP_INCOME if vip else 0))))

    async def buy(request):
        """Hech kimga tegishli bo'lmagan binoni shahardan sotib olish."""
        user, body = await auth(request)
        pid, uid, now = str(body.get("id") or ""), user["id"], int(time.time())
        info = CATALOG.get(pid)
        if not info:
            return err("Bunday bino yo'q")
        with db.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("INSERT OR IGNORE INTO game_profiles(user_id,created) VALUES(?,?)", (uid, now))
            row = c.execute("SELECT owner FROM props WHERE id=?", (pid,)).fetchone()
            if row and row["owner"]:
                return err("Bu bino allaqachon sotilgan")
            if c.execute("SELECT COUNT(*) n FROM props WHERE owner=?", (uid,)).fetchone()["n"] >= MAX_OWNED:
                return err(f"Eng ko'pi {MAX_OWNED} ta bino bo'lishi mumkin")
            cur = c.execute("UPDATE game_profiles SET coins=coins-? WHERE user_id=? AND coins>=?", (info["price"], uid, info["price"]))
            if cur.rowcount != 1:
                return err("Tanga yetarli emas")
            c.execute("INSERT INTO props(id,owner,bought_at,last_collect,paid) VALUES(?,?,?,?,?) "
                      "ON CONFLICT(id) DO UPDATE SET owner=excluded.owner, bought_at=excluded.bought_at, "
                      "last_collect=excluded.last_collect, paid=excluded.paid", (pid, uid, now, now, info["price"]))
            _ledger(c, uid, -info["price"], "prop_buy", f"{info['name']} ({pid})")
        return ok(msg=f"🏢 {info['name']} endi sizniki!")

    async def collect(request):
        user, _ = await auth(request)
        uid, now = user["id"], int(time.time())
        with db.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            vip = _is_vip(c, uid)
            total = 0
            for p in c.execute("SELECT * FROM props WHERE owner=?", (uid,)).fetchall():
                total += pending(dict(p), now, vip)
            if total <= 0:
                return err("Hozircha yig'iladigan daromad yo'q")
            c.execute("UPDATE props SET last_collect=? WHERE owner=?", (now, uid))
            c.execute("UPDATE game_profiles SET coins=coins+? WHERE user_id=?", (total, uid))
            _ledger(c, uid, total, "prop_income", "binolar daromadi")
        return ok(coins=total)

    async def list_(request):
        """Binoni sotuvga qo'yish (ochiq bozorga yoki aniq bir o'yinchiga)."""
        user, body = await auth(request)
        pid, uid, now = str(body.get("id") or ""), user["id"], int(time.time())
        info = CATALOG.get(pid)
        try:
            price = int(body.get("price") or 0)
        except (TypeError, ValueError):
            price = 0
        if not info:
            return err("Bunday bino yo'q")
        lo, hi = _r50(info["price"] * MIN_K), _r50(info["price"] * MAX_K)
        if not lo <= price <= hi:
            return err(f"Narx {lo} … {hi} tanga oralig'ida bo'lishi kerak")
        to = None
        target = str(body.get("to") or "").strip().lstrip("@")
        with db.conn() as c:
            if target:
                q = (c.execute("SELECT id FROM users WHERE id=?", (int(target),)) if target.isdigit()
                     else c.execute("SELECT id FROM users WHERE lower(username)=lower(?)", (target,))).fetchone()
                if not q:
                    return err("Bunday o'yinchi topilmadi (u botga kamida bir marta /start yozgan bo'lishi kerak)")
                if q["id"] == uid:
                    return err("O'zingizga sota olmaysiz")
                to = q["id"]
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT owner FROM props WHERE id=?", (pid,)).fetchone()
            if not row or row["owner"] != uid:
                return err("Bu bino sizniki emas")
            c.execute("UPDATE prop_listings SET status='cancelled', closed=? WHERE prop_id=? AND status='open'", (now, pid))
            c.execute("INSERT INTO prop_listings(prop_id,seller,price,to_user,created) VALUES(?,?,?,?,?)", (pid, uid, price, to, now))
        if to and notify:
            await notify(to, f"🏢 <b>{short_name(user)}</b> sizga <b>{info['name']}</b> ({info['district']}) binosini "
                             f"<b>{price}</b> tangaga taklif qildi.\nO'yin → 🏢 Mulk → Bozor bo'limida sotib olishingiz mumkin.")
        return ok(msg="🏷 Sotuvga qo'yildi" + (" — faqat siz tanlagan o'yinchi sotib oladi" if to else ""))

    async def cancel(request):
        user, body = await auth(request)
        lid = int(body.get("listing") or 0)
        with db.conn() as c:
            cur = c.execute("UPDATE prop_listings SET status='cancelled', closed=? WHERE id=? AND seller=? AND status='open'",
                            (int(time.time()), lid, user["id"]))
        return ok(msg="E'lon bekor qilindi") if cur.rowcount else err("E'lon topilmadi")

    async def buy_listing(request):
        """O'yinchidan sotib olish — escrow: hammasi bitta tranzaksiyada."""
        user, body = await auth(request)
        lid, uid, now = int(body.get("listing") or 0), user["id"], int(time.time())
        seen_price = body.get("price")
        with db.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("INSERT OR IGNORE INTO game_profiles(user_id,created) VALUES(?,?)", (uid, now))
            L = c.execute("SELECT * FROM prop_listings WHERE id=? AND status='open'", (lid,)).fetchone()
            if not L:
                return err("E'lon endi mavjud emas")
            if seen_price is not None and int(seen_price) != L["price"]:
                return err("Narx o'zgargan — ro'yxatni yangilab qayta ko'ring")
            if L["seller"] == uid:
                return err("O'z binongizni sotib ola olmaysiz")
            if L["to_user"] and L["to_user"] != uid:
                return err("Bu taklif boshqa o'yinchi uchun")
            p = c.execute("SELECT owner FROM props WHERE id=?", (L["prop_id"],)).fetchone()
            if not p or p["owner"] != L["seller"]:
                c.execute("UPDATE prop_listings SET status='cancelled', closed=? WHERE id=?", (now, lid))
                return err("Sotuvchi bu binoga endi egalik qilmaydi")
            if c.execute("SELECT COUNT(*) n FROM props WHERE owner=?", (uid,)).fetchone()["n"] >= MAX_OWNED:
                return err(f"Eng ko'pi {MAX_OWNED} ta bino bo'lishi mumkin")
            price, info = L["price"], CATALOG[L["prop_id"]]
            cur = c.execute("UPDATE game_profiles SET coins=coins-? WHERE user_id=? AND coins>=?", (price, uid, price))
            if cur.rowcount != 1:
                return err("Tanga yetarli emas")
            _ledger(c, uid, -price, "prop_buy", f"{info['name']} ({L['prop_id']}) — o'yinchidan")
            _settle(c, L["prop_id"], now)                     # sotuvchining yig'ilmagan daromadi o'ziga
            fee = int(price * FEE)
            c.execute("UPDATE game_profiles SET coins=coins+? WHERE user_id=?", (price - fee, L["seller"]))
            _ledger(c, L["seller"], price - fee, "prop_sell", f"{info['name']} ({L['prop_id']}), komissiya {fee}")
            c.execute("UPDATE props SET owner=?, bought_at=?, last_collect=?, paid=? WHERE id=?", (uid, now, now, price, L["prop_id"]))
            c.execute("UPDATE prop_listings SET status='sold', buyer=?, closed=? WHERE id=?", (uid, now, lid))
            c.execute("UPDATE prop_listings SET status='cancelled', closed=? WHERE prop_id=? AND status='open'", (now, L["prop_id"]))
            seller = L["seller"]
        if notify:
            await notify(seller, f"✅ <b>{info['name']}</b> ({info['district']}) <b>{short_name(user)}</b> ga sotildi.\n"
                                 f"🪙 +{price - fee} tanga (komissiya {fee}) hisobingizga tushdi.")
        return ok(msg=f"🏢 {info['name']} endi sizniki!")

    r.add_get("/api/game/props/catalog", catalog)
    r.add_post("/api/game/props/state", state)
    r.add_post("/api/game/props/buy", buy)
    r.add_post("/api/game/props/collect", collect)
    r.add_post("/api/game/props/list", list_)
    r.add_post("/api/game/props/cancel", cancel)
    r.add_post("/api/game/props/buy_listing", buy_listing)
