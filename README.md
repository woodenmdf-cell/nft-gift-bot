# NFT Bozor — Telegram bot + Mini App + Admin panel

## Nimalar bor
**Foydalanuvchi uchun (Mini App):**
- 🛍 Bozor: qidiruv, saralash, «Hammasi / Sotuv / Ijara» filtri
- 🛒 Sotib olish — so'mda, karta orqali, chek botga yuboriladi
- 🔑 Ijaraga olish — 1–30 kun, kunlik narx + garov (sovg'a qaytarilgach garov qaytariladi)
- 💸 E'lon berish — o'z sovg'asini sotish va/yoki ijaraga berish (komissiya bilan)
- 🧾 Buyurtmalarim — holat va ijara tugash vaqti

**Admin panel (`https://domeningiz/admin`):**
- 📊 Statistika va daromad
- 🛒 Xaridlar / 🔑 Ijaralar — chekni ko'rish, tasdiqlash, «Yetkazildi», «Qaytarildi»
- 🎁 Sovg'alar — qo'shish (faqat NFT havola + narx), tahrirlash, yashirish
- 📥 E'lonlar — foydalanuvchi sovg'alarini qabul/rad qilish
- 👥 Foydalanuvchilar — bloklash
- 📢 Hammaga xabar yuborish

Barcha amallarni bot ichidagi tugmalar orqali ham qilish mumkin.

**Avtomatik:**
- To'lanmagan buyurtma 30 daqiqadan keyin bekor bo'ladi
- Ijara tugashiga 24 soat qolganda eslatma
- Muddatdan 12 soat o'tsa — «Muddati o'tgan», adminga xabar

## 🎮 Shahar Arena — o'yin (`/game`, botda `/oyin`)
Mini App ichidagi bepul o'yin, ikki rejim:
- 🏙 **Shahar** — mashinada katta shaharni kezish: yetkazib berish, taksi va poyga topshiriqlari,
  yo'lda tanga yig'ish, avariya qilsangiz politsiya quvadi (⭐ qidiruv darajasi), qo'lga tushsangiz jarima.
- ⚽ **Futbol** — 4×4 tezkor o'yin (2 daqiqa), sun'iy intellektga qarshi. Joystik + ZARBA / PAS tugmalari.

Tangalarga garajda mashinalar (Taksi, Yo'ltanlamas, Sport kupe) va yaxshilashlar
(dvigatel, nitro, boshqaruv, futbolchilar tezligi, zarba, darvozabon) sotib olinadi. Kunlik bonus, XP/daraja, reyting bor.

**👑 VIP obuna — ixtiyoriy** (`GAME_VIP_PRICE` so'm / `GAME_VIP_DAYS` kun, bot balansidan to'lanadi):
×2 tanga, +15% kuch (mashina va futbol jamoasi), oltin superkar, oltin forma, tezroq nitro, kunlik bonus 300 tanga.
VIP sotib olinganda adminga xabar keladi; admin panelda o'yinchilar soni, faol VIP va VIP daromadi ko'rinadi.

Mukofot vaqti serverda o'lchanadi (`/api/game/start` → `/api/game/reward`), shuning uchun soxta natija bilan
cheksiz tanga yig'ib bo'lmaydi. Telegram'dan tashqarida ochilsa — mehmon rejimi (natija saqlanmaydi).

## Balans
Foydalanuvchi Mini App → Profil → «Balansni to'ldirish» → summa → bot karta raqamini yuboradi →
chek rasmini botga jo'natadi → admin tasdiqlaydi → balans + cashback (`CASHBACK`, standart 2%).
Xarid va ijara balansdan bir zumda to'lanadi.

## Garovsiz ijara (GiftXona uslubida)
Narx: kunlik narx × kun, chegirma bilan: 3 kun -3%, 1 hafta -17%, 2 hafta -23%, 1 oy -29%, 2 oy -35%, 3 oy -38%.

**Sovg'a sizning TON hamyoningizda qoladi** — ijarachi uni o'tkaza yoki sota olmaydi, shuning uchun garov kerak emas.

### Bir martalik tayyorgarlik (admin)
1. Ijaraga beriladigan sovg'ani TON blokcheynga chiqaring (Telegram: sovg'a → Transfer → Send via blockchain → Fragment).
2. https://marketapp.ws da hamyoningizni ulang → sovg'a → **Rent out** → eng kichik narx (masalan 0.01 TON/kun),
   «avtomatik qayta qo'yish» ni yoqing.
3. Ijaraga olish uchun Marketapp'da **ikkinchi hamyon** kerak (unda ozgina TON: har ijara ~0.2 TON + ijara haqi o'zingizga qaytadi).
4. Admin panel → Sovg'alar → sovg'ani qo'shing, «🔑 Ijarada» + kunlik narx (so'm).

### Har bir ijara
1. Mijoz balansdan to'laydi → bot unga ko'rsatma yuboradi: fragment.com → Connect TON → `tc://…` havolani yuborish.
2. Sizga havola keladi → Marketapp (2-hamyon) → sovg'ani mijoz tanlagan muddatga ijaraga oling →
   Rented → **Assign to Telegram** → havolani qo'ying → botda **✅ Ulandi**.
3. Mijoz fragment.com → My Assets → **Display in Telegram** — sovg'a profilida chiqadi.
4. Muddat tugaganda Marketapp sovg'ani qaytaradi, bot mijozga va sizga xabar beradi.

Havola eskirgan bo'lsa — **🔁 Yangi havola** tugmasi. Bekor qilinsa pul mijoz balansiga qaytadi.
Eslatma: Fragment bir sovg'ani kuniga ulash sonini cheklaydi.

## Serverga joylash (Railway — eng oson yo'l)
1. https://github.com da ro'yxatdan o'ting → **New repository** → shu papkadagi fayllarni yuklang
   (`Add file → Upload files`).
2. https://railway.com → GitHub bilan kiring → **New Project → Deploy from GitHub repo** → repongizni tanlang.
3. Loyiha → **Variables** bo'limiga quyidagilarni qo'shing:
   | Nomi | Qiymat |
   |---|---|
   | `BOT_TOKEN` | @BotFather bergan token |
   | `ADMIN_IDS` | Telegram ID'ingiz (@userinfobot dan bilib olasiz) |
   | `ADMIN_PASSWORD` | admin panel paroli |
   | `CARD_NUMBER` | to'lov qabul qilinadigan karta |
   | `CARD_OWNER` | karta egasi ismi |
   | `SHOP_ACCOUNT` | sovg'alar qaytariladigan akkaunt, masalan `@giftshop_admin` |
   | `COMMISSION` | komissiya foizi, masalan `5` |
   | `CASHBACK` | balans to'ldirishda bonus %, masalan `2` |
4. **Settings → Networking → Generate Domain** (domen avtomatik ulanadi).
5. **Settings → Volumes → Add Volume**, mount path: `/data` (ma'lumotlar o'chib ketmasligi uchun).
6. @BotFather → `/mybots` → botingiz → **Bot Settings → Configure Mini App** → Railway domenini kiriting.

Tayyor: botga `/start` yozing. Admin panel: `https://<domen>/admin`.

## O'z kompyuteringizda / VPS'da
```bash
pip install -r requirements.txt
cp .env.example .env   # to'ldiring, WEBAPP_URL ni ham yozing (HTTPS)
python bot.py
```

## Avtomatik narxlash
Bot har 6 soatda bozor narxlarini yangilaydi:
- Kolleksiya floor narxlari (GRAM): *Telegram gifts floor prices, Baltic Assets* — https://balticassets.eu (CC BY 4.0)
- GRAM → USD: o'sha to'plam yoki CoinGecko; USD → so'm: O'zbekiston Markaziy banki (cbu.uz)

`BUY_PCT` (standart 55, ya'ni bozordan 45% arzon) — foydalanuvchidan sovg'ani floor narxning necha foiziga sotib olishni taklif qilish.
Floor — eng arzon *sotuvga qo'yilgan* narx, sotilgan narx emas; noyob model/raqamlar qimmatroq turadi.
