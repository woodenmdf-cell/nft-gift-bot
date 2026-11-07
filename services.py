"""Bot va admin sayt birga ishlatadigan biznes-logika."""
import logging
import re
import time

from aiogram import Bot
from aiogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Kb

import db
from config import ADMIN_IDS, COMMISSION, SHOP_ACCOUNT

DAY = 86400


def som(n) -> str:
    return f"{int(n or 0):,}".replace(",", " ") + " so'm"


def gname(g) -> str:
    return f"{g['title']} {g.get('number') or ''}".strip()


def parse_nft_link(link: str):
    """https://t.me/nft/PlushPepe-1234 -> dict(title, number, image, link)"""
    m = re.search(r"t\.me/nft/([A-Za-z0-9]+)-(\d+)", link or "")
    if not m:
        return None
    slug, num = m.groups()
    return {
        "title": re.sub(r"(?<=[a-z])(?=[A-Z])", " ", slug),
        "number": f"#{num}",
        "image": f"https://nft.fragment.com/gift/{slug.lower()}-{num}.webp",
        "link": f"https://t.me/nft/{slug}-{num}",
    }


async def send(bot: Bot, chat_id, text, **kw):
    try:
        return await bot.send_message(chat_id, text, **kw)
    except Exception as e:  # foydalanuvchi botni bloklagan bo'lishi mumkin
        logging.warning("send %s: %s", chat_id, e)


async def notify_admins(bot: Bot, text, **kw):
    for a in ADMIN_IDS:
        await send(bot, a, text, **kw)


def kb_order(oid, *buttons):
    names = {"confirm": "✅ Tasdiqlash", "reject": "❌ Rad etish",
             "deliver": "📦 Yetkazildi", "returned": "↩️ Qaytarildi"}
    return Kb(inline_keyboard=[[Btn(text=names[b], callback_data=f"o:{b}:{oid}") for b in buttons]])


def kb_listing(gid):
    return Kb(inline_keyboard=[[Btn(text="✅ Qabul", callback_data=f"g:approve:{gid}"),
                                Btn(text="❌ Rad", callback_data=f"g:reject:{gid}")]])


def order_text(o, g):
    if o["kind"] == "rent":
        rent = o["price"] - o["deposit"]
        return (f"🔑 <b>Ijara #{o['id']}</b> — {gname(g)}\n"
                f"📅 {o['days']} kun · ijara {som(rent)} + garov {som(o['deposit'])}\n"
                f"💰 Jami: <b>{som(o['price'])}</b>")
    return f"🛒 <b>Xarid #{o['id']}</b> — {gname(g)}\n💰 <b>{som(o['price'])}</b>"


# ───────────── Buyurtma amallari ─────────────
# Har biri (ok: bool, xabar: str) qaytaradi

async def confirm_payment(bot, oid):
    o = db.get_order(oid)
    if not o or o["status"] not in ("checking", "waiting_payment"):
        return False, "Holat mos emas"
    g = db.get_gift(o["gift_id"])
    db.set_order(oid, status="paid")
    if o["kind"] == "buy":
        db.update_gift(g["id"], status="sold")
    await send(bot, o["buyer_id"], f"✅ To'lov tasdiqlandi!\n<b>{gname(g)}</b> tez orada profilingizga yuboriladi.")
    extra = ""
    if g["seller_id"] and o["kind"] == "buy":
        extra = (f"\n💸 Sotuvchiga: {som(o['price'] * (1 - COMMISSION / 100))} → "
                 f"<code>{g['seller_card'] or '-'}</code>")
    await notify_admins(
        bot, f"👉 {order_text(o, g)}\n\n<b>{gname(g)}</b> ni <code>{o['buyer_id']}</code> ga o'tkazing.\n"
             f"🔗 {g['link']}{extra}", reply_markup=kb_order(oid, "deliver"))
    return True, "Tasdiqlandi"


async def reject_payment(bot, oid):
    o = db.get_order(oid)
    if not o or o["status"] not in ("checking", "waiting_payment", "paid"):
        return False, "Holat mos emas"
    db.set_order(oid, status="cancelled")
    db.update_gift(o["gift_id"], status="active")
    await send(bot, o["buyer_id"], f"❌ Buyurtma #{oid} bekor qilindi. Savollar bo'lsa adminga yozing.")
    return True, "Bekor qilindi"


async def deliver(bot, oid):
    o = db.get_order(oid)
    if not o or o["status"] != "paid":
        return False, "Avval to'lov tasdiqlansin"
    g = db.get_gift(o["gift_id"])
    if o["kind"] == "buy":
        db.set_order(oid, status="delivered")
        await send(bot, o["buyer_id"], f"🎉 <b>{gname(g)}</b> yetkazildi! Xaridingiz uchun rahmat.")
    else:
        ends = int(time.time()) + o["days"] * DAY
        db.set_order(oid, status="rented", ends_at=ends)
        db.update_gift(g["id"], status="rented")
        await send(bot, o["buyer_id"],
                   f"🎉 <b>{gname(g)}</b> sizga {o['days']} kunga berildi!\n"
                   f"⏰ Muddat: <b>{time.strftime('%d.%m.%Y %H:%M', time.localtime(ends))}</b>\n\n"
                   f"Muddat tugagach sovg'ani <b>{SHOP_ACCOUNT}</b> ga qaytaring — garov "
                   f"({som(o['deposit'])}) kartangizga qaytariladi.")
    return True, "Yetkazildi"


async def mark_returned(bot, oid):
    o = db.get_order(oid)
    if not o or o["kind"] != "rent" or o["status"] not in ("rented", "overdue"):
        return False, "Holat mos emas"
    g = db.get_gift(o["gift_id"])
    was_overdue = o["status"] == "overdue"
    db.set_order(oid, status="returned")
    db.update_gift(g["id"], status="active")
    if was_overdue:
        await send(bot, o["buyer_id"], f"↩️ <b>{gname(g)}</b> qaytarildi. Muddat o'tgani uchun garov masalasini admin hal qiladi.")
    else:
        await send(bot, o["buyer_id"], f"↩️ <b>{gname(g)}</b> qaytarildi, rahmat! Garov ({som(o['deposit'])}) tez orada kartangizga o'tkaziladi.")
    msg = f"↩️ Ijara #{oid} yopildi.\n💳 Garovni qaytaring: {som(o['deposit'])} → <code>{o['card'] or '-'}</code>"
    if g["seller_id"]:
        rent = o["price"] - o["deposit"]
        msg += f"\n💸 Egasiga ijara ulushi: {som(rent * (1 - COMMISSION / 100))} → <code>{g['seller_card'] or '-'}</code>"
    await notify_admins(bot, msg)
    return True, "Qaytarildi"


ORDER_ACTIONS = {"confirm": confirm_payment, "reject": reject_payment,
                 "deliver": deliver, "returned": mark_returned, "cancel": reject_payment}


# ───────────── E'lon (foydalanuvchi sovg'asi) ─────────────

async def approve_listing(bot, gid, ok=True):
    g = db.get_gift(gid)
    if not g or g["status"] != "pending":
        return False, "Allaqachon ko'rib chiqilgan"
    db.update_gift(gid, status="active" if ok else "rejected")
    if g["seller_id"]:
        await send(bot, g["seller_id"],
                   f"✅ <b>{gname(g)}</b> bozorga chiqarildi!" if ok else f"❌ <b>{gname(g)}</b> arizasi rad etildi.")
    return True, "Bajarildi"


# ───────────── Fon tekshiruvlari ─────────────

async def background_tick(bot, pay_timeout=30 * 60):
    for o in db.expired_unpaid(pay_timeout):
        db.set_order(o["id"], status="cancelled")
        db.update_gift(o["gift_id"], status="active")
        await send(bot, o["buyer_id"], f"⌛ Buyurtma #{o['id']} vaqtida to'lanmadi va bekor qilindi.")

    for o in db.rentals_ending(DAY):  # 1 kun qolganda eslatma
        db.set_order(o["id"], reminded=1)
        g = db.get_gift(o["gift_id"])
        await send(bot, o["buyer_id"],
                   f"⏰ <b>{gname(g)}</b> ijarasi 24 soatdan kam vaqtda tugaydi.\n"
                   f"Muddat tugagach sovg'ani <b>{SHOP_ACCOUNT}</b> ga qaytaring.")

    for o in db.rentals_overdue(12 * 3600):  # 12 soat kechikish
        db.set_order(o["id"], status="overdue")
        g = db.get_gift(o["gift_id"])
        await send(bot, o["buyer_id"],
                   f"⚠️ <b>{gname(g)}</b> ijara muddati o'tdi! Zudlik bilan {SHOP_ACCOUNT} ga qaytaring, "
                   f"aks holda garov qaytarilmaydi.")
        await notify_admins(bot, f"⚠️ Ijara #{o['id']} muddati o'tdi ({gname(g)}). "
                                 f"Ijarachi: <code>{o['buyer_id']}</code>", reply_markup=kb_order(o["id"], "returned"))
