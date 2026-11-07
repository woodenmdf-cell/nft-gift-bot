import sqlite3
import time
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT, full_name TEXT, created INTEGER, banned INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS gifts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL, number TEXT, link TEXT, image TEXT,
  for_sale INTEGER DEFAULT 1, price INTEGER DEFAULT 0,        -- sotuv narxi (so'm)
  for_rent INTEGER DEFAULT 0, rent_price INTEGER DEFAULT 0,   -- 1 kunlik ijara narxi
  deposit INTEGER DEFAULT 0,                                  -- ijara garovi
  seller_id INTEGER, seller_card TEXT,                        -- NULL = do'kon sovg'asi
  status TEXT DEFAULT 'pending',  -- pending | active | reserved | rented | sold | rejected
  created INTEGER
);
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT DEFAULT 'buy',          -- buy | rent
  gift_id INTEGER, buyer_id INTEGER,
  price INTEGER,                    -- jami to'lov (ijara uchun: ijara + garov)
  days INTEGER DEFAULT 0, deposit INTEGER DEFAULT 0,
  card TEXT,                        -- garov qaytariladigan karta (ijara)
  status TEXT DEFAULT 'waiting_payment',
  -- waiting_payment | checking | paid | delivered | rented | returned | overdue | cancelled
  receipt_file TEXT, ends_at INTEGER, reminded INTEGER DEFAULT 0, created INTEGER
);
"""


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with conn() as c:
        c.executescript(SCHEMA)


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


def list_users(limit=500):
    return _all("SELECT u.*, (SELECT COUNT(*) FROM orders o WHERE o.buyer_id=u.id) AS orders "
                "FROM users u ORDER BY created DESC LIMIT ?", (limit,))


def all_user_ids():
    return [r["id"] for r in _all("SELECT id FROM users WHERE banned=0")]


def set_banned(uid, v):
    _exec("UPDATE users SET banned=? WHERE id=?", (1 if v else 0, uid))


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
    order = {"cheap": "price ASC", "expensive": "price DESC"}.get(sort, "id DESC")
    cond = {"sale": "AND for_sale=1", "rent": "AND for_rent=1"}.get(mode, "")
    ph = ",".join("?" * len(statuses))
    return _all(f"SELECT * FROM gifts WHERE status IN ({ph}) {cond} "
                f"AND (title LIKE ? OR number LIKE ?) ORDER BY {order} LIMIT 500",
                (*statuses, f"%{q}%", f"%{q}%"))


# ── orders ──
def create_order(kind, gid, buyer_id, days=0, card=None):
    """Sovg'ani band qiladi va buyurtma ochadi. Band/noto'g'ri bo'lsa None."""
    with conn() as c:
        g = c.execute("SELECT * FROM gifts WHERE id=? AND status='active'", (gid,)).fetchone()
        if not g or (kind == "buy" and not g["for_sale"]) or (kind == "rent" and not g["for_rent"]):
            return None
        if c.execute("UPDATE gifts SET status='reserved' WHERE id=? AND status='active'", (gid,)).rowcount == 0:
            return None
        if kind == "rent":
            deposit = g["deposit"]
            price = g["rent_price"] * days + deposit
        else:
            deposit, price = 0, g["price"]
        cur = c.execute("INSERT INTO orders(kind,gift_id,buyer_id,price,days,deposit,card,created) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (kind, gid, buyer_id, price, days, deposit, card, int(time.time())))
        return cur.lastrowid


def get_order(oid):
    return _one("SELECT * FROM orders WHERE id=?", (oid,))


def set_order(oid, **f):
    _exec(f"UPDATE orders SET {', '.join(k + '=?' for k in f)} WHERE id=?", (*f.values(), oid))


def user_waiting_order(uid):
    return _one("SELECT * FROM orders WHERE buyer_id=? AND status='waiting_payment' ORDER BY id DESC LIMIT 1", (uid,))


ORDER_JOIN = ("SELECT o.*, g.title, g.number, g.image, g.link, g.seller_id, g.seller_card, "
              "u.username, u.full_name FROM orders o JOIN gifts g ON g.id=o.gift_id "
              "LEFT JOIN users u ON u.id=o.buyer_id ")


def user_orders(uid):
    return _all(ORDER_JOIN + "WHERE o.buyer_id=? ORDER BY o.id DESC LIMIT 50", (uid,))


def list_orders(kind=None, status=None, limit=300):
    where, args = [], []
    if kind:
        where.append("o.kind=?"); args.append(kind)
    if status:
        where.append("o.status=?"); args.append(status)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    return _all(ORDER_JOIN + f"{w} ORDER BY o.id DESC LIMIT ?", (*args, limit))


def expired_unpaid(max_age):
    return _all("SELECT * FROM orders WHERE status='waiting_payment' AND created<?", (int(time.time()) - max_age,))


def rentals_ending(within_sec):
    return _all("SELECT * FROM orders WHERE status='rented' AND reminded=0 AND ends_at<?",
                (int(time.time()) + within_sec,))


def rentals_overdue(grace_sec):
    return _all("SELECT * FROM orders WHERE status='rented' AND ends_at<?", (int(time.time()) - grace_sec,))


def stats():
    one = lambda s: _one(s)["v"]
    return {
        "users": one("SELECT COUNT(*) v FROM users"),
        "active": one("SELECT COUNT(*) v FROM gifts WHERE status='active'"),
        "sold": one("SELECT COUNT(*) v FROM gifts WHERE status='sold'"),
        "rented": one("SELECT COUNT(*) v FROM orders WHERE status='rented'"),
        "pending_gifts": one("SELECT COUNT(*) v FROM gifts WHERE status='pending'"),
        "checking": one("SELECT COUNT(*) v FROM orders WHERE status='checking'"),
        "to_deliver": one("SELECT COUNT(*) v FROM orders WHERE status='paid'"),
        "overdue": one("SELECT COUNT(*) v FROM orders WHERE status='overdue'"),
        "revenue": one("SELECT COALESCE(SUM(price-deposit),0) v FROM orders "
                       "WHERE status IN ('paid','delivered','rented','returned','overdue')"),
    }
