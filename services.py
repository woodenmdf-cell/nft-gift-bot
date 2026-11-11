"""Bot va admin sayt birga ishlatadigan yordamchi funksiyalar: xabar yuborish, balans to'ldirish."""
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Kb

import db
from config import ADMIN_IDS, CASHBACK


def som(n) -> str:
    return f"{int(n or 0):,}".replace(",", " ") + " so'm"


async def send(bot: Bot, chat_id, text, **kw):
    try:
        return await bot.send_message(chat_id, text, **kw)
    except Exception as e:  # foydalanuvchi botni bloklagan bo'lishi mumkin
        logging.warning("send %s: %s", chat_id, e)


async def notify_admins(bot: Bot, text, **kw):
    for a in ADMIN_IDS:
        await send(bot, a, text, **kw)


def kb_topup(tid):
    return Kb(inline_keyboard=[[Btn(text="✅ Tasdiqlash", callback_data=f"t:ok:{tid}"),
                                Btn(text="❌ Rad etish", callback_data=f"t:no:{tid}")]])


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
    text += f"\n💰 Joriy balans: <b>{som(db.balance(t['user_id']))}</b>\n\nEndi o'yinda VIP yoki tanga sotib olishingiz mumkin 🎮"
    await send(bot, t["user_id"], text)
    return True, "Balans to'ldirildi"


async def reject_topup(bot, tid):
    t = db.get_topup(tid)
    if not t or t["status"] not in ("checking", "waiting"):
        return False, "Allaqachon ko'rib chiqilgan"
    db.set_topup(tid, status="rejected")
    await send(bot, t["user_id"], f"❌ {som(t['amount'])} to'lov tasdiqlanmadi. Savol bo'lsa adminga yozing.")
    return True, "Rad etildi"


async def background_tick(bot):
    for t in db.expired_topups(2 * 3600):  # 2 soatda chek yuborilmagan arizalar bekor qilinadi
        db.set_topup(t["id"], status="rejected")
