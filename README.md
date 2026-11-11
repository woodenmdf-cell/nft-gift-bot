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

## 🏢 Ko'chmas mulk (`props.py`)
- Shahardagi **979 ta bino** sotiladi (kichik uylar, do'konlar, ofislar, osmono'parlar + noyob: 2 ta yoqilg'i shoxobchasi,
  bo'yash ustaxonasi, teleminora). Narx bino turi, balandligi va markazga yaqinligiga qarab: 600 … 60 000 tanga.
- Har bir bino **soatiga narxining ~1.2%** tanga olib keladi (VIP +20%), 12 soatgacha yig'iladi — «Yig'ish» tugmasi.
- **Xavfsiz savdo (escrow):** egasi binoni ochiq bozorga yoki aniq bir o'yinchiga (@username / ID) sotuvga qo'yadi;
  xarid bitta SQLite tranzaksiyasida: tanga yechiladi, sotuvchiga (−5% komissiya) o'tadi, egalik o'zgaradi. Narx
  o'zgarsa, e'lon bekor qilinsa yoki bino boshqa qo'lga o'tsa — eski e'lon bilan sotib bo'lmaydi; bir vaqtdagi
  xaridlardan faqat bittasi o'tadi. Sotuvchiga va shaxsiy taklif egasiga botda xabar keladi. Bir o'yinchida eng ko'pi 30 ta bino.
- Ko'rinishi: menyuda «🏢 Mulklarim» paneli (daromad, yig'ish), bo'limlar: Mulklarim / Bozor / Shahar;
  shaharda yaqin binolar ustida narx yoki egasi, bino yonida **🏢 BINO** tugmasi, mini-xaritada o'z binolaringiz.
- Binolar ro'yxati server (`props.py`) va o'yin (`city3d.js`) da bir xil generator bilan quriladi; mos kelishi nazorat
  summasi (`layout`) bilan tekshiriladi.

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
