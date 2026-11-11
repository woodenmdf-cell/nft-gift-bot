# 🎮 Shahar Arena — Telegram o'yin boti

Telegram Mini App ichidagi bepul **3D ochiq shahar** o'yini. Bot `/start` da «🎮 O'ynash» tugmasini beradi,
o'yin bot domenining o'zida (`/`) ochiladi.

## O'yinda nimalar bor
- 🏙 **3D shahar** (14×14 kvartal, ~850 m, 16 tuman): piyoda yurish, yugurish, sakrash; faqat o'z mashinangizga o'tirish
  (yangi o'yinchiga ⚡ elektr skuter, qolganlari tangaga — 🛠 garaj; uzoqda qolsa «📲 Chaqirish»); transport, piyodalar, svetoforlar, avtobuslar, kun/tun.
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
- Har bir binoning **nomi va manzili** bor (masalan, *Kafe «Navro'z» — Amir Temur ko'chasi, 12-uy, Chilonzor*):
  biznes turi, nom va eng yaqin ko'cha bo'yicha uy raqami id dan hisoblanadi (15 gorizontal + 15 vertikal ko'cha).
- Bino oynasida **xarita** (bino qizil, boshqa egali binolar sariq/ko'k) va **🧭 Yo'l ko'rsatish** — o'yinda ko'k
  ko'rsatkich va mini-xarita binoga olib boradi. Egasi bor binolar **tomida egasining ismi** (o'ziniki — sariq ⭐,
  boshqalarniki — ko'k 👑), menyu ortidagi shahar manzarasida ham.
- «Shahar» bo'limida turi (do'kon, uy, ofis, garaj, plaza, tower, noyob), tuman va narx/daromad bo'yicha saralash.
- Ko'rinishi: menyuda «🏢 Mulklarim» paneli (daromad, yig'ish), bo'limlar: Mulklarim / Bozor / Shahar;
  shaharda yaqin binolar ustida narx yoki egasi, bino yonida **🏢 BINO** tugmasi, mini-xaritada o'z binolaringiz.
- Binolar ro'yxati server (`props.py`) va o'yin (`city3d.js`) da bir xil generator bilan quriladi; mos kelishi nazorat
  summasi (`layout`) bilan tekshiriladi.

## 🚗 Mashinalar (o'ylab topilgan markalar)
Yangi o'yinchi **⚡ Volt elektr skuteri** bilan boshlaydi; boshqa mashinalar tangaga: Turon Mini 1 500, Afrosiyob Sedan 3 000,
Afrosiyob Taksi 3 500, Ipak Yo'li Van 4 500, Pomir 4x4 7 000, Registon Luxe 12 000, Samarqand GT 22 000,
Oltin Burgut Superkar 60 000 (VIP'ga bepul). Faqat o'z mashinangizga o'tirasiz — yo'ldagi va boshqalarning mashinasini minib
bo'lmaydi. Oldin o'ynaganlarga avval bepul berilgan sedan saqlanadi.

## Pul tizimi
- **Balans** (so'm, eng kami `MIN_TOPUP` = 10 000): o'yin → 💳 Balans → summa → botga karta raqami keladi → chek skrinshoti botga →
  admin tasdiqlaydi (bot xabaridagi tugma yoki admin panel) → balans + `CASHBACK` %.
- 👑 **VIP** (`GAME_VIP_PRICE` / `GAME_VIP_DAYS`): ×2 tanga, +15% kuch, oltin superkar, VIP kiyimlar, kunlik bonus ×2.
- 🪙 **Tanga do'koni**: 10 000 → 2 200, 25 000 → 6 000, 50 000 → 13 000, 100 000 so'm → 30 000 tanga; birinchi xarid +50%, VIP +10%.
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
