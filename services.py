"""Bot va admin sayt birga ishlatadigan biznes-logika."""
import logging
import re
import time
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardButton as Btn, InlineKeyboardMarkup as Kb

import db
from config import ADMIN_IDS, CASHBACK, COMMISSION, SHOP_ACCOUNT

DAY = 86400

# Ijara paketlari: (kun, chegirma %) — GiftXona uslubida
PACKAGES = [(1, 0), (3, 3), (7, 17), (14, 23), (30, 29), (60, 35), (90, 38)]
PACKAGE_NAMES = {1: "1 kun", 3: "3 kun", 7: "1 hafta", 14: "2 hafta", 30: "1 oy", 60: "2 oy", 90: "3 oy"}


def rent_total(daily: int, days: int) -> int:
    disc = dict(PACKAGES).get(days, 0)
    raw = daily * days * (100 - disc) / 100
    step = 500 if raw >= 5000 else 100
    return max(step, int(round(raw / step)) * step)


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


def extract_tc_link(text: str):
    """Fragment'dagi 'Connect TON' havolasini ajratib oladi (tc://... yoki ...?v=2&id=...)."""
    if not text:
        return None
    m = re.search(r"(tc://\S+|https?://\S*[?&]v=2&id=\S+|\S*ton-connect\S*)", text)
    return m.group(1) if m else None


async def send(bot: Bot, chat_id, text, **kw):
    try:
        return await bot.send_message(chat_id, text, **kw)
    except Exception as e:  # foydalanuvchi botni bloklagan bo'lishi mumkin
        logging.warning("send %s: %s", chat_id, e)


async def notify_admins(bot: Bot, text, **kw):
    for a in ADMIN_IDS:
        await send(bot, a, text, **kw)


BTN = {"deliver": "📦 Yetkazildi", "linked": "✅ Ulandi", "relink": "🔁 Yangi havola",
       "cancel": "❌ Bekor (pul qaytadi)", "end": "⏹ Tugatish"}


def kb_order(oid, *buttons):
    return Kb(inline_keyboard=[[Btn(text=BTN[b], callback_data=f"o:{b}:{oid}") for b in buttons]])


def kb_topup(tid):
    return Kb(inline_keyboard=[[Btn(text="✅ Tasdiqlash", callback_data=f"t:ok:{tid}"),
                                Btn(text="❌ Rad etish", callback_data=f"t:no:{tid}")]])


def kb_listing(gid):
    return Kb(inline_keyboard=[[Btn(text="✅ Qabul", callback_data=f"g:approve:{gid}"),
                                Btn(text="❌ Rad", callback_data=f"g:reject:{gid}")]])


def order_text(o, g):
    if o["kind"] == "rent":
        return (f"🔑 <b>Ijara #{o['id']}</b> — {gname(g)}\n"
                f"📅 {PACKAGE_NAMES.get(o['days'], str(o['days']) + ' kun')} · {som(o['price'])}")
    return f"🛒 <b>Xarid #{o['id']}</b> — {gname(g)}\n💰 {som(o['price'])}"


LINK_HELP = (
    "🔗 <b>Oxirgi qadam — sovg'ani profilingizga ulash</b>\n\n"
    "1️⃣ <a href=\"https://fragment.com\">fragment.com</a> ni oching va <b>Log in</b> orqali Telegram bilan kiring\n"
    "2️⃣ Yuqori o'ngdagi ko'k <b>Connect TON</b> tugmasini bosing\n"
    "3️⃣ Chiqqan oynada <b>havolani nusxalang</b> (<code>tc://…</code> bilan boshlanadi)\n"
    "4️⃣ Havolani shu yerga yuboring\n\n"
    "⚠️ Admin ulaguncha Fragment sahifasini yopmang.\n"
    "🔒 Bu xavfsiz: biz faqat sovg'ani profilingizda <b>ko'rsatish</b> uchun ulaymiz. "
    "Akkauntingiz, pulingiz yoki boshqa sovg'alaringizga kirish berilmaydi."
)


# ───────────── Xarid / ijara ─────────────
# Har biri (ok: bool, xabar: str) qaytaradi

async def buy(bot, uid, gid):
    g = db.get_gift(gid)
    if not g:
        return False, "Sovg'a topilmadi"
    if g["seller_id"] == uid:
        return False, "O'z sovg'angizni ololmaysiz"
    oid, err = db.pay_order("buy", gid, uid, g["price"])
    if err:
        return False, err
    o = db.get_order(oid)
    await send(bot, uid, f"✅ {order_text(o, g)}\n\nTo'lov balansdan yechildi. Sovg'a tez orada profilingizga yuboriladi.")
    extra = ""
    if g["seller_id"]:
        extra = f"\n💸 Sotuvchiga: {som(o['price'] * (1 - COMMISSION / 100))} → <code>{g['seller_card'] or '-'}</code>"
    await notify_admins(bot, f"🛒 {order_text(o, g)}\n👤 <code>{uid}</code>\n\n"
                             f"<b>{gname(g)}</b> ni shu foydalanuvchiga o'tkazing.\n🔗 {g['link']}{extra}",
                        reply_markup=kb_order(oid, "deliver", "cancel"))
    return True, "Sotib olindi"


GUIDE_VIDEO = Path(__file__).parent / "webapp" / "ijara_qollanma.mp4"
_guide_file_id = None


async def send_guide(bot, uid):
    """Ijarani profilga ulash bo'yicha video qo'llanma (birinchi marta yuklanadi, keyin file_id qayta ishlatiladi)."""
    global _guide_file_id
    if not GUIDE_VIDEO.exists():
        return
    try:
        msg = await bot.send_video(uid, _guide_file_id or FSInputFile(GUIDE_VIDEO),
                                   caption="🎬 <b>Video qo'llanma:</b> sovg'ani profilingizga 1 daqiqada ulang",
                                   supports_streaming=True)
        if msg and msg.video:
            _guide_file_id = msg.video.file_id
    except Exception as e:
        logging.warning("guide video %s: %s", uid, e)


async def rent(bot, uid, gid, days):
    g = db.get_gift(gid)
    if not g or not g["for_rent"]:
        return False, "Sovg'a ijarada emas"
    if days not in dict(PACKAGES):
        return False, "Muddat noto'g'ri"
    price = rent_total(g["rent_price"], days)
    oid, err = db.pay_order("rent", gid, uid, price, days)
    if err:
        return False, err
    o = db.get_order(oid)
    await send(bot, uid, f"✅ {order_text(o, g)}\nTo'lov balansdan yechildi.\n\n" + LINK_HELP,
               disable_web_page_preview=True)
    await send_guide(bot, uid)
    await notify_admins(bot, f"🔑 Yangi {order_text(o, g)}\n👤 <code>{uid}</code>\n"
                             f"Ijarachi Fragment havolasini yuborishini kutyapmiz.")
    return True, "Ijaraga olindi"


async def receive_tc_link(bot, uid, link):
    """Ijarachi Fragment 'Connect TON' havolasini yubordi."""
    o = db.user_order_needing_link(uid)
    if not o:
        return False
    g = db.get_gift(o["gift_id"])
    db.set_order(o["id"], status="linking", tc_link=link)
    await send(bot, uid, "⏳ Havola qabul qilindi! Admin sovg'ani ulayapti, odatda 1–10 daqiqa. "
                         "Fragment sahifasini yopmang.")
    await notify_admins(
        bot,
        f"🔗 {order_text(o, g)}\n👤 <code>{uid}</code>\n\n"
        f"<b>Marketapp'da:</b> My Gifts → Rented → <b>{gname(g)}</b> → <b>Assign to Telegram</b> → "
        f"quyidagi havolani qo'ying:\n\n<code>{link}</code>\n\nUlagach «✅ Ulandi» ni bosing.",
        reply_markup=kb_order(o["id"], "linked", "relink", "cancel"))
    return True


async def mark_linked(bot, oid):
    o = db.get_order(oid)
    if not o or o["status"] != "linking":
        return False, "Holat mos emas"
    g = db.get_gift(o["gift_id"])
    ends = int(time.time()) + o["days"] * DAY
    db.set_order(oid, status="rented", ends_at=ends, reminded=0)
    await send(bot, o["buyer_id"],
               f"🎉 <b>{gname(g)}</b> ulandi!\n\n"
               f"Endi <a href=\"https://fragment.com/my/assets\">fragment.com → My Assets</a> da sovg'ani toping, "
               f"<b>⋯ → Display in Telegram</b> ni bosing — sovg'a profilingizda chiqadi.\n\n"
               f"⏰ Ijara tugashi: <b>{time.strftime('%d.%m.%Y %H:%M', time.localtime(ends))}</b>",
               disable_web_page_preview=True)
    return True, "Ulandi"


async def ask_relink(bot, oid):
    o = db.get_order(oid)
    if not o or o["status"] not in ("linking", "need_link"):
        return False, "Holat mos emas"
    db.set_order(oid, status="need_link", tc_link=None)
    await send(bot, o["buyer_id"], "🔁 Havola eskirib qolgan. Iltimos, yangisini yuboring.\n\n" + LINK_HELP,
               disable_web_page_preview=True)
    return True, "Yangi havola so'raldi"


async def deliver(bot, oid):
    o = db.get_order(oid)
    if not o or o["kind"] != "buy" or o["status"] != "paid":
        return False, "Holat mos emas"
    g = db.get_gift(o["gift_id"])
    db.set_order(oid, status="delivered")
    db.update_gift(g["id"], status="sold")
    await send(bot, o["buyer_id"], f"🎉 <b>{gname(g)}</b> yetkazildi! Xaridingiz uchun rahmat.")
    return True, "Yetkazildi"


async def cancel(bot, oid):
    """Bekor qilish — pul balansga qaytadi."""
    o = db.get_order(oid)
    if not o or o["status"] not in ("paid", "need_link", "linking"):
        return False, "Bekor qilib bo'lmaydi"
    db.set_order(oid, status="cancelled")
    db.update_gift(o["gift_id"], status="active")
    db.add_balance(o["buyer_id"], o["price"])
    await send(bot, o["buyer_id"], f"↩️ Buyurtma #{oid} bekor qilindi, {som(o['price'])} balansingizga qaytarildi.")
    return True, "Bekor qilindi, pul qaytarildi"


async def end_rental(bot, oid, manual=True):
    o = db.get_order(oid)
    if not o or o["status"] != "rented":
        return False, "Holat mos emas"
    g = db.get_gift(o["gift_id"])
    db.set_order(oid, status="ended")
    db.update_gift(g["id"], status="active")
    await send(bot, o["buyer_id"], f"⏹ <b>{gname(g)}</b> ijarasi tugadi. Yana ijaraga olishingiz mumkin! 🎁")
    await notify_admins(bot, f"⏹ Ijara #{oid} tugadi ({gname(g)}). "
                             f"Marketapp'da sovg'a qaytganini va yana ijaraga qo'yilganini tekshiring.")
    return True, "Tugatildi"


ORDER_ACTIONS = {"deliver": deliver, "linked": mark_linked, "relink": ask_relink,
                 "cancel": cancel, "end": end_rental}


# ───────────── Balans to'ldirish ─────────────

async def confirm_topup(bot, tid, amount=None):
    t = db.get_topup(tid)
    if not t or t["status"] not in ("checking", "waiting"):
        return False, "Allaqachon ko'rib chiqilgan"
    amount = int(amount or t["amount"])
    bonus = int(amount * CASHBACK / 100)
    db.set_topup(tid, status="ok", amount=amount, bonus=bonus)
    db.add_balance(t["user_id"], amount + bonus)
    text = f"✅ <b>Hisobingiz {som(amount)} ga to'ldirildi!</b>"
    if bonus:
        text += f"\n🎁 Cashback: +{som(bonus)}"
    text += f"\n💰 Joriy balans: <b>{som(db.balance(t['user_id']))}</b>"
    await send(bot, t["user_id"], text)
    return True, "Balans to'ldirildi"


async def reject_topup(bot, tid):
    t = db.get_topup(tid)
    if not t or t["status"] not in ("checking", "waiting"):
        return False, "Allaqachon ko'rib chiqilgan"
    db.set_topup(tid, status="rejected")
    await send(bot, t["user_id"], f"❌ {som(t['amount'])} to'lov tasdiqlanmadi. Savol bo'lsa adminga yozing.")
    return True, "Rad etildi"


# ───────────── E'lon (foydalanuvchi sovg'asi) ─────────────

async def approve_listing(bot, gid, ok=True):
    g = db.get_gift(gid)
    if not g or g["status"] != "pending":
        return False, "Allaqachon ko'rib chiqilgan"
    db.update_gift(gid, status="active" if ok else "rejected")
    if g["seller_id"]:
        await send(bot, g["seller_id"],
                   f"✅ <b>{gname(g)}</b> qabul qilindi va bozorga chiqarildi!" if ok
                   else f"❌ <b>{gname(g)}</b> arizasi rad etildi.")
    return True, "Bajarildi"


# ───────────── Fon tekshiruvlari ─────────────

async def background_tick(bot):
    for t in db.expired_topups(2 * 3600):  # chek yuborilmagan to'ldirish arizalari
        db.set_topup(t["id"], status="rejected")

    for o in db.stale_need_link(30 * 60):  # 30 daqiqada havola yubormagan
        db.set_order(o["id"], reminded=1)
        await send(bot, o["buyer_id"], "⏰ Sovg'ani profilingizga ulash uchun Fragment havolasini yuboring.\n\n" + LINK_HELP,
                   disable_web_page_preview=True)

    for o in db.rentals_ending(DAY):  # 1 kun qolganda eslatma
        if o["days"] > 1:
            db.set_order(o["id"], reminded=1)
            g = db.get_gift(o["gift_id"])
            await send(bot, o["buyer_id"], f"⏰ <b>{gname(g)}</b> ijarasi 24 soatdan kam vaqtda tugaydi. "
                                           f"Uzaytirish uchun bozordan yana ijaraga oling.")

    for o in db.rentals_expired():
        await end_rental(bot, o["id"], manual=False)
