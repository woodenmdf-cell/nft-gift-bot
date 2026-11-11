# 🎮 Shahar Arena — Telegram o'yin boti

Telegram Mini App ichidagi bepul **3D ochiq shahar** o'yini. Bot `/start` da «🎮 O'ynash» tugmasini beradi,
o'yin bot domenining o'zida (`/`) ochiladi.

## O'yinda nimalar bor
- 🏙 **3D shahar** (14×14 kvartal, ~850 m, 16 tuman): piyoda yurish, yugurish, sakrash; istalgan mashinaga o'tirish
  (yo'ldagisini olsangiz — politsiya qidiradi); transport, piyodalar, svetoforlar, avtobuslar, kun/tun.
- 🕌 Toshkent uslubi: tumanlar nomi, do'kon peshtaxtalari, madrasa, teleminora; ⛽ yoqilg'i (nitro), 🎨 bo'yash ustaxonasi.
- 📦 Topshiriqlar: yetkazish (50), taksi (70), poyga (90 tanga) + daraja bonusi; yo'lda tangalar; ⭐ politsiya ta'qibi.
- 👥 **Onlayn**: `/ws/city` — 25 kishilik xonalar, chat, 🏁 server hakamlik qiladigan onlayn poyga (g'olibga 150 tanga).
- 🧍 12 ta personaj + aksessuarlar, 🛠 garaj (mashinalar, yaxshilashlar), 📻 radio, signal, sirena.
- 🎨 Grafika: Kenney (kenney.nl, CC0) modellari — `webapp/assets/`, LOD bilan telefonda tez ishlaydi.

## Pul tizimi
- **Balans** (so'm): o'yin → 💳 Balans → summa → botga karta raqami keladi → chek skrinshoti botga →
  admin tasdiqlaydi (bot xabaridagi tugma yoki admin panel) → balans + `CASHBACK` %.
- 👑 **VIP** (`GAME_VIP_PRICE` / `GAME_VIP_DAYS`): ×2 tanga, +15% kuch, oltin superkar, VIP kiyimlar, kunlik bonus ×2.
- 🪙 **Tanga do'koni**: 5 000 → 1 000 ... 100 000 so'm → 30 000 tanga; birinchi xarid +50%, VIP +10%.
- 🎁 Kunlik bonus seriyasi: 100 → 150 → 200 → 250 → 300 → 400 → 600 tanga.
- Mukofot vaqti serverda o'lchanadi, soxta natija kesiladi; poyga nuqtalarini server tekshiradi (teleportga qarshi).

## Admin panel (`https://domeningiz/admin`, botda `/admin`)
📊 o'yin statistikasi va daromad · 💳 balans to'ldirish (chek, tasdiqlash) · 👥 foydalanuvchilar (balans, tanga, VIP,
bloklash) · 📢 hammaga xabar · 💾 zaxira nusxa. Har soatda zaxira adminlarga yuboriladi, `/restore` bilan tiklanadi.

## O'rnatish (Railway)
1. @BotFather → `/newbot` → token.
2. Railway → Variables: `BOT_TOKEN`, `ADMIN_IDS`, `ADMIN_PASSWORD`, `CARD_NUMBER`, `CARD_OWNER` (qolganlari — `.env.example`).
3. Settings → Networking → **Generate Domain** (port 8080).
4. **Volume** qo'shing, Mount path: `/data` — aks holda har yangilanishda ma'lumotlar o'chadi.
