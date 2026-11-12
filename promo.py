"""Promo bot — Telegram guruh/kanalga o'yinga qiziqtiradigan postlar chiqaradi.

O'yin boti bilan bir jarayonda ishlaydi (alohida token: PROMO_BOT_TOKEN), bir xil bazadan foydalanadi:
  • 🎬 o'yindan avtomatik yozilgan videolar (promo/clips/*.mp4 — tools/record_promo.js yozadi);
  • 🏆 reyting, 🏢 mulk yangiliklari, 📊 so'rovnomalar, 🎁 haftalik konkurs (g'oliblarga tanga avtomatik);
  • 👋 guruhga yangi qo'shilganlarni kutib oladi.
Botni guruhga qo'shish kifoya — u guruhni o'zi eslab qoladi va adminlarga xabar beradi.
"""
import asyncio
import datetime as dt
import json
import logging
import random
import re
import time
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import (ChatMemberUpdated, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message)

import db
import props

log = logging.getLogger("promo")
CLIPS = Path(__file__).parent / "promo" / "clips"
TZ = dt.timezone(dt.timedelta(hours=5))                     # Toshkent vaqti

# Kunlik post vaqtlari va navbat (har vaqtda navbatdagi tur chiqadi)
ROTATION = ["video", "top", "video", "props", "poll", "video", "contest", "video", "tip"]
CONTEST_DAY, CONTEST_HOUR = 6, 20                          # yakshanba 20:00 — haftalik konkurs yakuni

CAPTIONS = {
    "supercar": ["🌇 Quyosh botishi, bo'sh ko'cha va <b>Oltin Burgut Superkar</b>…\nSiz ham shunday haydashni xohlaysizmi? 🔥",
                 "🏎 Nitro bosildi — shahar ortda qoldi!\n<b>Shahar Arena</b>da tanga yig'ing va orzuingizdagi mashinani oling."],
    "chase": ["🚓🚓🚓 Uch yulduz — butun politsiya ortingizda!\nQochib qutula olasizmi? 😈",
              "🌃 Tungi shahar, sirenalar va siz.\n<b>Shahar Arena</b> — politsiyadan qochib ko'ring!"],
    "ambulance": ["🚑 Bugun siz — tez yordam haydovchisi!\nBemorni urilmasdan klinikaga yetkazing va <b>110 tanga</b> oling.",
                  "🩺 Har bir soniya muhim… Tez yordam, avtobus, yuk mashinasi, politsiya — <b>5 xil kasb</b> sizni kutmoqda!"],
    "scooter": ["🛴 Hamma narsa elektr skuterdan boshlanadi…\nTanga yig'ing → mashina oling → shaharni zabt eting! 🏙",
                "☀️ Tonggi shahar, skuter va siz.\nBoshlash <b>bepul</b> — birinchi skuter sovg'a!"],
    "flyover": ["🏙 <b>975 ta bino, 16 ta tuman</b> — bu sizning shahringiz.\nUlardan 20 tasini sotib olib, har soat daromad oling! 🏢",
                "🌅 Tong otdi. Shahar uyg'ondi.\nSiz qachon kirasiz? 👇"],
}
POLLS = [
    ("Qaysi mashina eng zo'r? 🏎", ["⚡ Volt skuter", "🚕 Afrosiyob Taksi", "🚙 Pomir 4x4", "🏎 Samarqand GT", "🦅 Oltin Burgut Superkar"]),
    ("Shahar Arena'da qaysi kasb sizga yoqadi? 👷", ["🚑 Tez yordam", "🚌 Avtobus", "🚚 Yuk tashish", "🚓 Politsiya", "💐 To'y korteji"]),
    ("Qaysi tumanda bino sotib olgan bo'lardingiz? 🏢", ["Markaz", "Yunusobod", "Chilonzor", "Mirzo Ulug'bek", "Yakkasaroy"]),
    ("O'yinga nima qo'shaylik? 🤔", ["🏍 Mototsikllar", "🛩 Aeroport", "⚽ Stadion", "🏦 Bank o'g'irligi", "🌧 Yomg'ir va qor"]),
    ("Kunda necha soat o'ynaysiz? ⏱", ["10 daqiqa", "30 daqiqa", "1 soat", "2 soatdan ko'p"]),
]
TIPS = [
    "💡 <b>Maslahat:</b> binolar daromadi 12 soatgacha yig'iladi — kuniga 2 marta kirib yig'ib oling!",
    "💡 <b>Maslahat:</b> ⛽ yoqilg'i shoxobchasiga kirsangiz nitro bepul to'ladi.",
    "💡 <b>Maslahat:</b> politsiyadan qochish uchun tor ko'chalarga buriling — 10 soniya ko'rinmasangiz yulduz kamayadi.",
    "💡 <b>Maslahat:</b> har kuni kiring — 7 kunlik seriya bonusida 600 tangagacha beriladi.",
    "💡 <b>Maslahat:</b> to'y kortejida kelin mashinasidan 50 m dan uzoqlashmang, aks holda kortej sizsiz ketadi 💐",
    "💡 <b>Maslahat:</b> 🏢 Mulk → Bozor bo'limida binoni boshqa o'yinchiga xavfsiz sotishingiz mumkin — pul faqat bitim bo'lganda o'tadi.",
]
WELCOME = ("👋 Xush kelibsiz, {name}!\n\n🏙 Bu guruh — <b>Shahar Arena</b> 3D o'yini muxlislari uchun.\n"
           "Mashinalar, binolar, politsiya ta'qibi va onlayn poygalar — hammasi Telegram ichida, <b>bepul</b>.")


def _int_list(raw, default):
    try:
        v = [int(x) for x in re.split(r"[,\s]+", raw or "") if x.strip()]
        return v or default
    except ValueError:
        return default


class Promo:
    def __init__(self, token, admins, times, prizes, notify_admins):
        self.bot = Bot(token, default=DefaultBotProperties(parse_mode="HTML"))
        self.dp = Dispatcher()
        self.admins = admins
        self.times = times
        self.prizes = prizes
        self.notify_admins = notify_admins                  # o'yin boti orqali adminlarga xabar
        self.game_username = None
        self._routes()

    # ── yordamchilar ──
    def chats(self):
        try:
            return json.loads(db.get_setting("promo_chats") or "{}")
        except ValueError:
            return {}

    def _save_chats(self, c):
        db.set_setting("promo_chats", json.dumps(c, ensure_ascii=False))

    def kb(self, text="🎮 Bepul o'ynash"):
        if not self.game_username:
            return None
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=f"https://t.me/{self.game_username}?start=promo")]])

    @staticmethod
    def clips():
        return sorted(CLIPS.glob("*.mp4")) if CLIPS.exists() else []

    async def _send_all(self, fn):
        sent = 0
        for cid in list(self.chats()):
            try:
                await fn(int(cid)); sent += 1
            except Exception as e:                           # guruhdan chiqarilgan yoki huquq yo'q
                log.warning("promo %s: %s", cid, e)
        return sent

    # ── post turlari ──
    async def post_video(self, name=None):
        files = self.clips()
        if not files:
            return await self.post_tip()
        if name:
            files = [f for f in files if f.stem == name] or files
        i = int(db.get_setting("promo_vi") or 0)
        f = files[i % len(files)]
        db.set_setting("promo_vi", str(i + 1))
        cap = random.choice(CAPTIONS.get(f.stem, ["🏙 <b>Shahar Arena</b> — Telegram ichidagi 3D shahar!"]))
        players = db.stats().get("players", 0)
        if players >= 20:
            cap += f"\n\n👥 {players} o'yinchi allaqachon shaharda!"

        async def send(cid):
            fid = db.get_setting("promo_fid_" + f.stem)
            m = await self.bot.send_video(cid, fid or FSInputFile(f), caption=cap, reply_markup=self.kb(),
                                          width=720, height=1280, supports_streaming=True)
            if not fid and m.video:
                db.set_setting("promo_fid_" + f.stem, m.video.file_id)   # keyingi safar qayta yuklanmaydi
        return await self._send_all(send)

    async def post_top(self):
        rows = db._all("SELECT g.xp, g.coins, u.full_name, u.username FROM game_profiles g LEFT JOIN users u ON u.id=g.user_id "
                       "WHERE g.xp>0 ORDER BY g.xp DESC LIMIT 10")
        if len(rows) < 3:
            return await self.post_tip()
        medals = ["🥇", "🥈", "🥉"] + [f"{i}." for i in range(4, 11)]
        lines = [f"{medals[i]} {_name(r)} — {_level(r['xp'])}-daraja" for i, r in enumerate(rows)]
        text = "🏆 <b>Shahar Arena — eng kuchli o'yinchilar</b>\n\n" + "\n".join(lines) + "\n\nSiz ham ro'yxatga kiring! 👇"
        return await self._send_all(lambda cid: self.bot.send_message(cid, text, reply_markup=self.kb("🎮 Reytingga chiqish")))

    async def post_props(self):
        with db.conn() as c:
            owned = {r["id"]: r for r in c.execute("SELECT p.id, u.full_name, u.username FROM props p LEFT JOIN users u ON u.id=p.owner "
                                                    "WHERE p.owner IS NOT NULL").fetchall()}
            sold = c.execute("SELECT l.prop_id, l.price FROM prop_listings l WHERE l.status='sold' AND l.closed>? "
                             "ORDER BY l.closed DESC LIMIT 3", (int(time.time()) - 7 * 86400,)).fetchall()
        cat = props.CATALOG
        free = [k for k in cat if k not in owned]
        text = f"🏢 <b>Shahar mulklari</b>\n\nJami {len(cat)} ta mulk: <b>{len(owned)}</b> tasi egali, <b>{len(free)}</b> tasi bo'sh.\n"
        if free:
            best = max(free, key=lambda k: cat[k]["price"])
            b = cat[best]
            text += f"\n💎 Eng qimmat bo'sh bino: <b>{b['name']}</b> ({b['district']}) — {b['price']:,} tanga, soatiga +{b['income']} 🪙\n".replace(",", " ")
        for s in sold:
            if s["prop_id"] in cat:
                text += f"\n🤝 {cat[s['prop_id']]['name']} — {s['price']:,} tangaga sotildi".replace(",", " ")
        if owned:
            text += "\n\n👑 Egalar: " + ", ".join(f"{_name(r)} ({cat[k]['name']})" for k, r in list(owned.items())[:5] if k in cat)
        text += "\n\nBino egasining ismi uning tomida yoziladi. Sizniki qaysi bo'ladi? 👇"
        return await self._send_all(lambda cid: self.bot.send_message(cid, text, reply_markup=self.kb("🏢 Bino tanlash")))

    async def post_poll(self):
        i = int(db.get_setting("promo_pi") or 0)
        db.set_setting("promo_pi", str(i + 1))
        q, opts = POLLS[i % len(POLLS)]
        return await self._send_all(lambda cid: self.bot.send_poll(cid, q, opts, is_anonymous=True))

    async def post_tip(self):
        i = int(db.get_setting("promo_ti") or 0)
        db.set_setting("promo_ti", str(i + 1))
        text = TIPS[i % len(TIPS)]
        return await self._send_all(lambda cid: self.bot.send_message(cid, text, reply_markup=self.kb()))

    def week_leaders(self, since, limit=10):
        return db._all("SELECT l.user_id, SUM(l.delta) earned, u.full_name, u.username FROM game_ledger l "
                       "LEFT JOIN users u ON u.id=l.user_id WHERE l.created>=? AND l.delta>0 AND l.kind IN ('game','race') "
                       "GROUP BY l.user_id ORDER BY earned DESC LIMIT ?", (since, limit))

    async def post_contest(self):
        rows, prizes = self.week_leaders(_week_start()), self.prizes
        text = ("🎁 <b>Haftalik konkurs</b>\n\nYakshanba soat 20:00 da shu haftada o'yinda eng ko'p tanga topgan 3 kishi yutadi:\n"
                + "\n".join(f"{m} {p:,} tanga".replace(",", " ") for m, p in zip(["🥇", "🥈", "🥉"], prizes)) + "\n")
        if rows:
            text += "\n📊 Hozirgi holat:\n" + "\n".join(f"{i + 1}. {_name(r)} — {r['earned']:,} 🪙".replace(",", " ") for i, r in enumerate(rows[:5]))
        else:
            text += "\nHali hech kim tanga topmadi — birinchi bo'ling!"
        return await self._send_all(lambda cid: self.bot.send_message(cid, text, reply_markup=self.kb("🎮 Konkursda qatnashish")))

    async def finish_contest(self, now):
        """Hafta yakuni: g'oliblarga tanga (bir marta), natijani guruhlarga chiqarish."""
        week = now.strftime("%G-%V")
        if db.get_setting("promo_contest") == week:
            return
        db.set_setting("promo_contest", week)
        rows = self.week_leaders(_week_start(now))
        if not rows:
            return
        lines = []
        for medal, prize, r in zip(["🥇", "🥈", "🥉"], self.prizes, rows):
            with db.conn() as c:
                c.execute("INSERT OR IGNORE INTO game_profiles(user_id,created) VALUES(?,?)", (r["user_id"], int(time.time())))
            db.game_add(r["user_id"], coins=prize, kind="contest", note=f"haftalik konkurs {week}")
            lines.append(f"{medal} {_name(r)} — {r['earned']:,} tanga topdi → <b>+{prize:,}</b> sovg'a".replace(",", " "))
        text = "🏆 <b>Haftalik konkurs yakunlandi!</b>\n\n" + "\n".join(lines) + "\n\nSovg'a tangalar hisobga tushdi. Yangi hafta boshlandi — omad! 🍀"
        await self._send_all(lambda cid: self.bot.send_message(cid, text, reply_markup=self.kb()))
        if self.notify_admins:
            await self.notify_admins("🎁 Haftalik konkurs g'oliblariga tanga berildi:\n" + "\n".join(lines))

    async def post(self, kind=None):
        if not kind:
            i = int(db.get_setting("promo_ri") or 0)
            db.set_setting("promo_ri", str(i + 1))
            kind = ROTATION[i % len(ROTATION)]
        fn = {"video": self.post_video, "top": self.post_top, "props": self.post_props, "poll": self.post_poll,
              "tip": self.post_tip, "contest": self.post_contest}.get(kind, self.post_video)
        return kind, await fn()

    # ── jadval ──
    async def loop(self):
        while True:
            try:
                now = dt.datetime.now(TZ)
                hm = now.strftime("%H:%M")
                stamp = now.strftime("%Y-%m-%d ") + hm
                if db.get_setting("promo_on", "1") == "1" and self.chats():
                    if hm in self.times and db.get_setting("promo_last") != stamp:
                        db.set_setting("promo_last", stamp)
                        await self.post()
                    if now.weekday() == CONTEST_DAY and now.hour == CONTEST_HOUR:
                        await self.finish_contest(now)
            except Exception as e:
                log.exception("promo loop: %s", e)
            await asyncio.sleep(30)

    # ── buyruqlar ──
    def _routes(self):
        dp = self.dp

        @dp.my_chat_member()
        async def added(u: ChatMemberUpdated):
            if u.chat.type == "private":
                return
            c = self.chats()
            if u.new_chat_member.status in ("member", "administrator"):
                c[str(u.chat.id)] = u.chat.title or str(u.chat.id)
                self._save_chats(c)
                if self.notify_admins:
                    await self.notify_admins(f"📣 Promo bot «{u.chat.title}» guruhiga qo'shildi. Postlar kuniga "
                                             f"{len(self.times)} marta chiqadi ({', '.join(self.times)}).")
                try:
                    await self.bot.send_message(u.chat.id, "🏙 Salom! Men <b>Shahar Arena</b> o'yinidan yangiliklar, videolar va konkurslar "
                                                           "olib kelaman. Birinchi video tez orada! 🎬", reply_markup=self.kb())
                except Exception:
                    pass
            elif u.new_chat_member.status in ("left", "kicked"):
                c.pop(str(u.chat.id), None)
                self._save_chats(c)

        @dp.message(F.new_chat_members)
        async def welcome(m: Message):
            people = [u for u in m.new_chat_members if not u.is_bot]
            if not people:
                return
            names = ", ".join(_esc(u.first_name) for u in people[:5])
            try:
                await m.reply(WELCOME.format(name=names), reply_markup=self.kb())
            except Exception:
                pass

        @dp.message(CommandStart(), F.chat.type == "private")
        async def start(m: Message):
            if m.from_user.id in self.admins:
                await m.answer(self.help_text())
            else:
                await m.answer("🏙 Men <b>Shahar Arena</b> guruhlari uchun yangiliklar botiman.\nO'ynash uchun 👇", reply_markup=self.kb())

        @dp.message(Command("post"), F.chat.type == "private")
        async def post_now(m: Message):
            if m.from_user.id not in self.admins:
                return
            arg = (m.text or "").split(maxsplit=1)[1:] or [None]
            kind = arg[0]
            if not self.chats():
                return await m.answer("Hali guruh yo'q. Botni guruhga qo'shing (kanal bo'lsa — admin qiling).")
            name = None
            if kind and kind.startswith("video:"):
                kind, name = "video", kind.split(":", 1)[1]
            if name:
                n = await self.post_video(name)
            else:
                kind, n = await self.post(kind)
            await m.answer(f"✅ «{kind}» {n} ta guruhga yuborildi.")

        @dp.message(Command("guruhlar"), F.chat.type == "private")
        async def groups(m: Message):
            if m.from_user.id not in self.admins:
                return
            c = self.chats()
            on = db.get_setting("promo_on", "1") == "1"
            await m.answer(("🟢 Postlar yoqilgan" if on else "🔴 Postlar o'chirilgan") + "\n\n" +
                           ("\n".join(f"• {t} (<code>{k}</code>)" for k, t in c.items()) or "Guruh yo'q"))

        @dp.message(Command("on", "off"), F.chat.type == "private")
        async def toggle(m: Message):
            if m.from_user.id not in self.admins:
                return
            on = m.text.startswith("/on")
            db.set_setting("promo_on", "1" if on else "0")
            await m.answer("🟢 Avtomatik postlar yoqildi" if on else "🔴 Avtomatik postlar to'xtatildi")

    def help_text(self):
        clips = ", ".join(f.stem for f in self.clips()) or "yo'q"
        return ("📣 <b>Promo bot — admin</b>\n\n"
                "1) Botni guruhingizga qo'shing (kanal bo'lsa — admin qiling). U guruhni o'zi eslab qoladi.\n"
                f"2) Har kuni {', '.join(self.times)} da (Toshkent) navbat bilan: video, reyting, mulklar, so'rovnoma, konkurs, maslahat.\n"
                f"3) Har yakshanba 20:00 — haftalik konkurs: eng ko'p tanga topgan 3 kishiga {', '.join(map(str, self.prizes))} tanga.\n\n"
                "Buyruqlar:\n/post — navbatdagi postni hozir chiqarish\n/post video | top | props | poll | contest | tip\n"
                "/post video:chase — aniq video\n/guruhlar — guruhlar ro'yxati\n/off, /on — avtomatik postlarni to'xtatish/yoqish\n\n"
                f"🎬 Videolar: {clips}")

    async def run(self):
        me = await self.bot.get_me()
        log.info("Promo bot: @%s", me.username)
        if not getattr(self, "_loop", None):
            self._loop = asyncio.create_task(self.loop())
        await self.dp.start_polling(self.bot, handle_signals=False)


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _name(r):
    return _esc((r["full_name"] or r["username"] or "O'yinchi").strip()[:18])


def _level(xp):
    try:
        import game
        return game.level(xp)
    except Exception:
        return 1


def _week_start(now=None):
    now = now or dt.datetime.now(TZ)
    start = (now - dt.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp())


def make(token, admins, times_raw, prizes_raw, notify_admins):
    times = [t.strip().zfill(5) for t in re.split(r"[,\s]+", times_raw or "") if re.fullmatch(r"\d{1,2}:\d{2}", t.strip())]
    return Promo(token, admins, times or ["10:00", "13:30", "17:00", "20:30"], _int_list(prizes_raw, [3000, 2000, 1000])[:3], notify_admins)
