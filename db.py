import sqlite3
import time
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT, full_name TEXT, created INTEGER,
  banned INTEGER DEFAULT 0, balance INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS gifts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL, number TEXT, link TEXT, image TEXT,
  for_sale INTEGER DEFAULT 1, price INTEGER DEFAULT 0,        -- sotuv narxi (so'm)
  for_rent INTEGER DEFAULT 0, rent_price INTEGER DEFAULT 0,   -- 1 kunlik ijara narxi
  deposit INTEGER DEFAULT 0,                                  -- (eski, ishlatilmaydi)
  seller_id INTEGER, seller_card TEXT,                        -- NULL = do'kon sovg'asi
  status TEXT DEFAULT 'pending',  -- pending | active | reserved | rented | sold | rejected
  created INTEGER
);
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT DEFAULT 'buy',          -- buy | rent
  gift_id INTEGER, buyer_id INTEGER,
  price INTEGER, days INTEGER DEFAULT 0, deposit INTEGER DEFAULT 0, card TEXT,
  status TEXT DEFAULT 'paid',
  -- buy:  paid -> delivered | cancelled
  -- rent: need_link -> linking -> rented -> ended | cancelled
  tc_link TEXT, receipt_file TEXT, ends_at INTEGER, reminded INTEGER DEFAULT 0, created INTEGER
);
CREATE TABLE IF NOT EXISTS topups(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER, amount INTEGER, bonus INTEGER DEFAULT 0,
  status TEXT DEFAULT 'waiting',    -- waiting | checking | ok | rejected
  receipt_file TEXT, created INTEGER
);
CREATE TABLE IF NOT EXISTS game_profiles(
  user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0, xp INTEGER DEFAULT 0,
  data TEXT DEFAULT '{}',            -- JSON: upgrades, cars, car
  vip_until INTEGER DEFAULT 0, last_daily INTEGER DEFAULT 0,
  games INTEGER DEFAULT 0, wins INTEGER DEFAULT 0, created INTEGER
);
CREATE TABLE IF NOT EXISTS game_payments(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER, days INTEGER, created INTEGER
);
"""

# Eski bazaga yangi ustunlar qo'shish
MIGRATIONS = [
    ("users", "balance", "INTEGER DEFAULT 0"),
    ("orders", "tc_link", "TEXT"),
    ("game_payments", "kind", "TEXT DEFAULT 'vip'"),
    ("game_payments", "coins", "INTEGER DEFAULT 0"),
]


def conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init():
    with conn() as c:
        c.executescript(SCHEMA)
        for table, col, typ in MIGRATIONS:
            cols = [r["name"] for r in c.execute(f"PRAGMA table_info({table})")]
            if col not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


def _all(sql, args=()):
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def _one(sql, args=()):
    with conn() as c:
        r = c.execute(sql, args).fetchone()
        return dict(r) if r else None


def _exec(sql, args=()):
    with conn() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid, cur.rowcount


# ── users ──
def upsert_user(uid, username, full_name):
    _exec("INSERT INTO users(id,username,full_name,created) VALUES(?,?,?,?) "
          "ON CONFLICT(id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name",
          (uid, username, full_name, int(time.time())))


def get_user(uid):
    return _one("SELECT * FROM users WHERE id=?", (uid,))


def balance(uid):
    u = get_user(uid)
    return u["balance"] if u else 0


def add_balance(uid, amount):
    _exec("UPDATE users SET balance=balance+? WHERE id=?", (amount, uid))


def set_balance(uid, amount):
    _exec("UPDATE users SET balance=? WHERE id=?", (amount, uid))


def list_users(limit=1000):
    return _all("SELECT u.*, (SELECT COUNT(*) FROM orders o WHERE o.buyer_id=u.id) AS orders "
                "FROM users u ORDER BY created DESC LIMIT ?", (limit,))


def all_user_ids():
    return [r["id"] for r in _all("SELECT id FROM users WHERE banned=0")]


def set_banned(uid, v):
    _exec("UPDATE users SET banned=? WHERE id=?", (1 if v else 0, uid))


def top_users(limit=50):
    return _all("SELECT u.id, u.username, u.full_name, COUNT(o.id) AS cnt, COALESCE(SUM(o.price),0) AS total "
                "FROM orders o JOIN users u ON u.id=o.buyer_id "
                "WHERE o.status NOT IN ('cancelled') GROUP BY u.id ORDER BY total DESC LIMIT ?", (limit,))


# ── gifts ──
GIFT_FIELDS = ("title", "number", "link", "image", "for_sale", "price", "for_rent",
               "rent_price", "deposit", "seller_id", "seller_card", "status")


def add_gift(**f):
    f.setdefault("status", "active")
    keys = [k for k in GIFT_FIELDS if k in f]
    gid, _ = _exec(f"INSERT INTO gifts({','.join(keys)},created) VALUES({','.join('?' * len(keys))},?)",
                   (*[f[k] for k in keys], int(time.time())))
    return gid


def update_gift(gid, **f):
    f = {k: v for k, v in f.items() if k in GIFT_FIELDS}
    if f:
        _exec(f"UPDATE gifts SET {', '.join(k + '=?' for k in f)} WHERE id=?", (*f.values(), gid))


def get_gift(gid):
    return _one("SELECT * FROM gifts WHERE id=?", (gid,))


def list_gifts(q="", sort="new", mode="all", statuses=("active",)):
    order = {"cheap": "price ASC", "expensive": "price DESC",
             "rent_cheap": "rent_price ASC"}.get(sort, "id DESC")
    cond = {"sale": "AND for_sale=1", "rent": "AND for_rent=1"}.get(mode, "")
    ph = ",".join("?" * len(statuses))
    return _all(f"SELECT * FROM gifts WHERE status IN ({ph}) {cond} "
                f"AND (title LIKE ? OR number LIKE ?) ORDER BY {order} LIMIT 1000",
                (*statuses, f"%{q}%", f"%{q}%"))


# ── orders (balansdan to'lanadi) ──
def pay_order(kind, gid, buyer_id, price, days=0):
    """Balansdan yechib, sovg'ani band qiladi. (order_id, xato) qaytaradi."""
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")
        g = c.execute("SELECT * FROM gifts WHERE id=? AND status='active'", (gid,)).fetchone()
        if not g or (kind == "buy" and not g["for_sale"]) or (kind == "rent" and not g["for_rent"]):
            return None, "Bu sovg'a hozir band"
        bal = c.execute("SELECT balance FROM users WHERE id=?", (buyer_id,)).fetchone()
        if not bal or bal["balance"] < price:
            return None, "Balans yetarli emas"
        c.execute("UPDATE users SET balance=balance-? WHERE id=?", (price, buyer_id))
        c.execute("UPDATE gifts SET status=? WHERE id=?", ("reserved" if kind == "buy" else "rented", gid))
        status = "paid" if kind == "buy" else "need_link"
        cur = c.execute("INSERT INTO orders(kind,gift_id,buyer_id,price,days,status,created) VALUES(?,?,?,?,?,?,?)",
                        (kind, gid, buyer_id, price, days, status, int(time.time())))
        return cur.lastrowid, None


def get_order(oid):
    return _one("SELECT * FROM orders WHERE id=?", (oid,))


def set_order(oid, **f):
    _exec(f"UPDATE orders SET {', '.join(k + '=?' for k in f)} WHERE id=?", (*f.values(), oid))


def user_order_needing_link(uid):
    return _one("SELECT * FROM orders WHERE buyer_id=? AND kind='rent' AND status='need_link' "
                "ORDER BY id DESC LIMIT 1", (uid,))


ORDER_JOIN = ("SELECT o.*, g.title, g.number, g.image, g.link, g.seller_id, g.seller_card, "
              "u.username, u.full_name FROM orders o JOIN gifts g ON g.id=o.gift_id "
              "LEFT JOIN users u ON u.id=o.buyer_id ")


def user_orders(uid):
    return _all(ORDER_JOIN + "WHERE o.buyer_id=? ORDER BY o.id DESC LIMIT 100", (uid,))


def list_orders(kind=None, status=None, limit=500):
    where, args = [], []
    if kind:
        where.append("o.kind=?"); args.append(kind)
    if status:
        where.append("o.status=?"); args.append(status)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    return _all(ORDER_JOIN + f"{w} ORDER BY o.id DESC LIMIT ?", (*args, limit))


def rentals_ending(within_sec):
    return _all("SELECT * FROM orders WHERE status='rented' AND reminded=0 AND ends_at<?",
                (int(time.time()) + within_sec,))


def rentals_expired():
    return _all("SELECT * FROM orders WHERE status='rented' AND ends_at<?", (int(time.time()),))


def stale_need_link(max_age):
    return _all("SELECT * FROM orders WHERE status='need_link' AND reminded=0 AND created<?",
                (int(time.time()) - max_age,))


# ── topups ──
def create_topup(uid, amount):
    with conn() as c:
        c.execute("UPDATE topups SET status='rejected' WHERE user_id=? AND status='waiting'", (uid,))
        return c.execute("INSERT INTO topups(user_id,amount,created) VALUES(?,?,?)",
                         (uid, amount, int(time.time()))).lastrowid


def waiting_topup(uid):
    return _one("SELECT * FROM topups WHERE user_id=? AND status='waiting' ORDER BY id DESC LIMIT 1", (uid,))


def get_topup(tid):
    return _one("SELECT * FROM topups WHERE id=?", (tid,))


def set_topup(tid, **f):
    _exec(f"UPDATE topups SET {', '.join(k + '=?' for k in f)} WHERE id=?", (*f.values(), tid))


def list_topups(status=None, limit=500):
    w, args = ("WHERE t.status=?", (status,)) if status else ("WHERE t.status!='waiting'", ())
    return _all("SELECT t.*, u.username, u.full_name FROM topups t LEFT JOIN users u ON u.id=t.user_id "
                f"{w} ORDER BY t.id DESC LIMIT ?", (*args, limit))


def expired_topups(max_age):
    return _all("SELECT * FROM topups WHERE status='waiting' AND created<?", (int(time.time()) - max_age,))


def stats():
    one = lambda s: _one(s)["v"]
    return {
        "users": one("SELECT COUNT(*) v FROM users"),
        "active": one("SELECT COUNT(*) v FROM gifts WHERE status='active'"),
        "sold": one("SELECT COUNT(*) v FROM gifts WHERE status='sold'"),
        "rented": one("SELECT COUNT(*) v FROM orders WHERE status='rented'"),
        "pending_gifts": one("SELECT COUNT(*) v FROM gifts WHERE status='pending'"),
        "topups_checking": one("SELECT COUNT(*) v FROM topups WHERE status='checking'"),
        "to_deliver": one("SELECT COUNT(*) v FROM orders WHERE status='paid'"),
        "to_link": one("SELECT COUNT(*) v FROM orders WHERE status='linking'"),
        "balances": one("SELECT COALESCE(SUM(balance),0) v FROM users"),
        "topped": one("SELECT COALESCE(SUM(amount),0) v FROM topups WHERE status='ok'"),
        "revenue": one("SELECT COALESCE(SUM(price),0) v FROM orders WHERE status NOT IN ('cancelled')"),
        "players": one("SELECT COUNT(*) v FROM game_profiles"),
        "vip_active": one(f"SELECT COUNT(*) v FROM game_profiles WHERE vip_until>{int(time.time())}"),
        "game_revenue": one("SELECT COALESCE(SUM(amount),0) v FROM game_payments"),
    }


# ── o'yin (Shahar Arena) ──
def game_profile(uid):
    _exec("INSERT OR IGNORE INTO game_profiles(user_id,created) VALUES(?,?)", (uid, int(time.time())))
    return _one("SELECT * FROM game_profiles WHERE user_id=?", (uid,))


def game_save(uid, **f):
    _exec(f"UPDATE game_profiles SET {', '.join(k + '=?' for k in f)} WHERE user_id=?", (*f.values(), uid))


def game_add(uid, coins=0, xp=0, games=0, wins=0):
    _exec("UPDATE game_profiles SET coins=coins+?, xp=xp+?, games=games+?, wins=wins+? WHERE user_id=?",
          (coins, xp, games, wins, uid))


def game_spend(uid, coins, data_json):
    """Tangani yechib, data ni saqlaydi. Yetmasa False."""
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")
        cur = c.execute("UPDATE game_profiles SET coins=coins-?, data=? WHERE user_id=? AND coins>=?",
                        (coins, data_json, uid, coins))
        return cur.rowcount == 1


def game_buy_vip(uid, price, days):
    """Bot balansidan VIP obuna. (yangi vip_until, xato) qaytaradi."""
    now = int(time.time())
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT OR IGNORE INTO game_profiles(user_id,created) VALUES(?,?)", (uid, now))
        bal = c.execute("SELECT balance FROM users WHERE id=?", (uid,)).fetchone()
        if not bal or bal["balance"] < price:
            return None, "Balans yetarli emas"
        c.execute("UPDATE users SET balance=balance-? WHERE id=?", (price, uid))
        cur = c.execute("SELECT vip_until FROM game_profiles WHERE user_id=?", (uid,)).fetchone()["vip_until"]
        until = max(now, cur or 0) + days * 86400
        c.execute("UPDATE game_profiles SET vip_until=? WHERE user_id=?", (until, uid))
        c.execute("INSERT INTO game_payments(user_id,amount,days,created) VALUES(?,?,?,?)", (uid, price, days, now))
        return until, None


def game_top(limit=30):
    return _all("SELECT g.xp, g.wins, g.games, g.vip_until, u.username, u.full_name FROM game_profiles g "
                "LEFT JOIN users u ON u.id=g.user_id ORDER BY g.xp DESC LIMIT ?", (limit,))


def game_buy_coins(uid, price, coins):
    """Bot balansidan tanga paketi (donat). (yangi tanga soni, xato) qaytaradi."""
    now = int(time.time())
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT OR IGNORE INTO game_profiles(user_id,created) VALUES(?,?)", (uid, now))
        bal = c.execute("SELECT balance FROM users WHERE id=?", (uid,)).fetchone()
        if not bal or bal["balance"] < price:
            return None, "Balans yetarli emas"
        c.execute("UPDATE users SET balance=balance-? WHERE id=?", (price, uid))
        c.execute("UPDATE game_profiles SET coins=coins+? WHERE user_id=?", (coins, uid))
        c.execute("INSERT INTO game_payments(user_id,amount,days,kind,coins,created) VALUES(?,?,0,'coins',?,?)",
                  (uid, price, coins, now))
        return c.execute("SELECT coins FROM game_profiles WHERE user_id=?", (uid,)).fetchone()["coins"], None


def game_coin_purchases(uid):
    return _one("SELECT COUNT(*) v FROM game_payments WHERE user_id=? AND kind='coins'", (uid,))["v"]
