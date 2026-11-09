"""Bozor narxlari: Fragment kolleksiya floor narxlari (GRAM) -> so'm.

Manbalar:
  • Floor narxlar: Baltic Assets ochiq ma'lumotlari (CC BY 4.0)
    https://github.com/Atlannn/telegram-gifts-floor-price
  • GRAM/USD kursi: o'sha to'plamdagi rates.csv, bo'lmasa CoinGecko
  • USD/UZS kursi: O'zbekiston Markaziy banki (cbu.uz)
"""
import csv
import io
import logging
import os
import time

from aiohttp import ClientSession, ClientTimeout

FLOORS_CSV = "https://raw.githubusercontent.com/Atlannn/telegram-gifts-floor-price/main/data/floor_prices.csv"
RATES_CSV = "https://raw.githubusercontent.com/Atlannn/telegram-gifts-floor-price/main/data/rates.csv"
COINGECKO = "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network,gram&vs_currencies=usd"
CBU_USD = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/"

BUY_PCT = float(os.environ.get("BUY_PCT", "80"))  # foydalanuvchidan sotib olish: floor narxning necha foizi

STATE = {"floors": {}, "date": None, "gram_usd": None, "usd_uzs": None, "updated": 0, "error": None}


def _f(x):
    try:
        return float(str(x).strip().replace(",", ".")) if str(x).strip() else None
    except ValueError:
        return None


def parse_floors(text: str):
    """CSV -> (eng so'nggi sana, {slug: floor_gram}). Qat'iy narxli floor afzal, bo'lmasa auksion."""
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        return None, {}
    last = max(r.get("date", "") for r in rows)
    floors = {}
    for r in rows:
        if r.get("date") != last:
            continue
        v = _f(r.get("floor_fixed_gram")) or _f(r.get("floor_gram"))
        if v:
            floors[(r.get("collection") or "").strip().lower()] = v
    return last, floors


def parse_rate(text: str):
    """rates.csv dan oxirgi GRAM/USD kursini topadi (ustun nomida 'usd' bo'ladi)."""
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        return None
    col = next((c for c in rows[0].keys() if c and "usd" in c.lower()), None)
    if not col:
        return None
    rows.sort(key=lambda r: r.get("date", ""))
    for r in reversed(rows):
        v = _f(r.get(col))
        if v:
            return v
    return None


async def refresh():
    try:
        async with ClientSession(timeout=ClientTimeout(total=30), headers={"User-Agent": "nft-bozor-bot"}) as s:
            async with s.get(FLOORS_CSV) as r:
                r.raise_for_status()
                date, floors = parse_floors(await r.text())
            gram_usd = None
            try:
                async with s.get(RATES_CSV) as r:
                    if r.status == 200:
                        gram_usd = parse_rate(await r.text())
            except Exception:
                pass
            if not gram_usd:
                async with s.get(COINGECKO) as r:
                    j = await r.json(content_type=None)
                    gram_usd = (j.get("the-open-network") or j.get("gram") or {}).get("usd")
            async with s.get(CBU_USD) as r:
                j = await r.json(content_type=None)
                usd_uzs = _f(j[0]["Rate"])
        if floors and gram_usd and usd_uzs:
            STATE.update(floors=floors, date=date, gram_usd=float(gram_usd), usd_uzs=usd_uzs,
                         updated=int(time.time()), error=None)
            logging.info("Narxlar yangilandi: %s kolleksiya, %s, 1 GRAM = %.2f$, 1$ = %.0f so'm",
                         len(floors), date, gram_usd, usd_uzs)
        else:
            STATE["error"] = "ma'lumot to'liq emas"
    except Exception as e:
        STATE["error"] = str(e)
        logging.warning("narxlarni yangilab bo'lmadi: %s", e)


def gram_to_uzs(g):
    if not (STATE["gram_usd"] and STATE["usd_uzs"]):
        return None
    return g * STATE["gram_usd"] * STATE["usd_uzs"]


def round_to(x, step):
    return int(round(x / step)) * step


def suggest_daily_rent(price_uzs: int) -> int:
    """Kunlik ijara taklifi: arzon sovg'alarda foiz yuqori, qimmatlarida past (bozor amaliyotiga mos)."""
    if price_uzs <= 200_000:
        pct = 1.5
    elif price_uzs <= 2_000_000:
        pct = 0.5
    elif price_uzs <= 20_000_000:
        pct = 0.15
    else:
        pct = 0.05
    return max(1000, round_to(price_uzs * pct / 100, 100))


def quote(slug: str):
    """Kolleksiya uchun narx ma'lumoti yoki None."""
    slug = (slug or "").lower().replace(" ", "").replace("'", "").replace("-", "")
    g = STATE["floors"].get(slug)
    uzs = gram_to_uzs(g) if g else None
    if not uzs:
        return None
    step = 1000 if uzs < 1_000_000 else 10_000
    floor_uzs = round_to(uzs, step)
    return {
        "slug": slug, "date": STATE["date"], "floor_gram": round(g, 2),
        "floor_uzs": floor_uzs,
        "offer_uzs": round_to(uzs * BUY_PCT / 100, step),
        "rent_daily": suggest_daily_rent(floor_uzs),
        "gram_usd": STATE["gram_usd"], "usd_uzs": STATE["usd_uzs"],
    }


async def loop():
    while True:
        await refresh()
        await __import__("asyncio").sleep(6 * 3600 if not STATE["error"] else 900)
