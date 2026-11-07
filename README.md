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

## Ijara qanday ishlaydi
1. Ijarachi kunlar sonini tanlaydi va **ijara haqi + garov** to'laydi.
2. Admin chekni tasdiqlaydi va sovg'ani ijarachiga o'tkazadi → «Yetkazildi».
3. Muddat tugagach ijarachi sovg'ani `SHOP_ACCOUNT` ga qaytaradi → admin «Qaytarildi» bosadi.
4. Garov ijarachining kartasiga qaytariladi. Qaytarmasa, garov qolib ketadi (sovg'a egasiga beriladi).
   Garovni sovg'a qiymatiga teng yoki undan yuqori qo'ying!

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
