import os
import re
from pathlib import Path

# .env faylni o'qish (qo'shimcha kutubxonasiz)
_env = Path(__file__).parent / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.split(" #")[0].strip())

_raw_token = os.environ.get("BOT_TOKEN", "")
# Token ba'zan qo'shtirnoq, bo'sh joy yoki "BOT_TOKEN=" bilan nusxalanadi — toza tokenni ajratib olamiz
_m = re.search(r"\d{5,}:[A-Za-z0-9_-]{30,}", _raw_token)
BOT_TOKEN = _m.group(0) if _m else _raw_token.strip().strip("'\"")
ADMIN_IDS = {int(x) for x in re.split(r"[,\s]+", os.environ.get("ADMIN_IDS", "")) if x.strip().lstrip("-").isdigit()}
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin12345")

# Mini App manzili. Railway / Render o'zi domen beradi — avtomatik olinadi.
_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or ""
WEBAPP_URL = (os.environ.get("WEBAPP_URL", "").strip().rstrip("/")
              or os.environ.get("RENDER_EXTERNAL_URL")
              or (f"https://{_domain}" if _domain else ""))

CARD_NUMBER = os.environ.get("CARD_NUMBER", "8600 0000 0000 0000")
CARD_OWNER = os.environ.get("CARD_OWNER", "Ism Familiya")
SHOP_ACCOUNT = os.environ.get("SHOP_ACCOUNT", "@admin")   # sovg'alar qaytariladigan akkaunt
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = os.environ.get("DB_PATH", str(DATA_DIR / "giftxona.db"))
COMMISSION = float(os.environ.get("COMMISSION", "5"))     # foydalanuvchi sovg'alaridan %
CASHBACK = float(os.environ.get("CASHBACK", "2"))           # balans to'ldirishda bonus %
MIN_TOPUP = int(os.environ.get("MIN_TOPUP", "5000"))      # eng kam to'ldirish (so'm)

# ── O'yin (Shahar Arena) ──
GAME_VIP_PRICE = int(os.environ.get("GAME_VIP_PRICE", "19000"))   # oylik VIP narxi (so'm)
GAME_VIP_DAYS = int(os.environ.get("GAME_VIP_DAYS", "30"))
