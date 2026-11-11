import sqlite3
import time
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT, full_name TEXT, created INTEGER,
  banned INTEGER DEFAULT 0, balance INTEGER DEFAULT 0
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
    return _all("SELECT u.*, g.coins, g.xp, g.vip_until, "
                "(SELECT COALESCE(SUM(amount),0) FROM game_payments p WHERE p.user_id=u.id) AS spent "
                "FROM users u LEFT JOIN game_profiles g ON g.user_id=u.id ORDER BY u.created DESC LIMIT ?", (limit,))


def all_user_ids():
    return [r["id"] for r in _all("SELECT id FROM users WHERE banned=0")]


def set_banned(uid, v):
    _exec("UPDATE users SET banned=? WHERE id=?", (1 if v else 0, uid))


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
    one = lambda q: _one(q)["v"]
    now = int(time.time())
    return {
        "users": one("SELECT COUNT(*) v FROM users"),
        "players": one("SELECT COUNT(*) v FROM game_profiles"),
        "active_day": one(f"SELECT COUNT(*) v FROM game_profiles WHERE last_daily>{now - 86400}"),
        "vip_active": one(f"SELECT COUNT(*) v FROM game_profiles WHERE vip_until>{now}"),
        "topups_checking": one("SELECT COUNT(*) v FROM topups WHERE status='checking'"),
        "topped": one("SELECT COALESCE(SUM(amount),0) v FROM topups WHERE status='ok'"),
        "balances": one("SELECT COALESCE(SUM(balance),0) v FROM users"),
        "game_revenue": one("SELECT COALESCE(SUM(amount),0) v FROM game_payments"),
        "vip_revenue": one("SELECT COALESCE(SUM(amount),0) v FROM game_payments WHERE kind='vip'"),
        "coin_revenue": one("SELECT COALESCE(SUM(amount),0) v FROM game_payments WHERE kind='coins'"),
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
