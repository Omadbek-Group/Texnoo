# sayt22

## Railway sozlamalari

Railway Variables ichida quyidagilar bo'lishi kerak:

```env
BOT_TOKEN=telegram_bot_token
RUN_TELEGRAM_BOT=1
DATA_DIR=/data
```

`DATA_DIR=/data` ishlashi uchun Railway'da Volume yarating va mount path sifatida `/data` ni tanlang. Aks holda `data/data.json` vaqtinchalik diskka yoziladi va restart/deploy paytida o'chib ketishi mumkin.

### Xavfsizlik va moliya (yangi)

```env
SECRET_KEY=uzun_tasodifiy_satr          # login tokenlarini imzolaydi; bo'lmasa DATA_DIR/.secret_key yaratiladi
INITIAL_ADMIN_LOGIN=+998901234567       # shu loginli admin paroli yangilanadi, admin bo'lmasa Platform Admin yaratiladi
INITIAL_ADMIN_PASSWORD=kamida8belgi     # kirgandan keyin ikkala o'zgaruvchini o'chiring
```

- Login token beradi; `/api/data` va boshqa API'lar tokensiz ishlamaydi. Rollar serverda tekshiriladi.
- Admin hisoblari darajasi: `platform_admin`, `school_admin`, `director` (boshliq, to'liq huquq),
  `manager` (menejer: CRM, jadval, davomat), `cashier` (kassir: faqat moliya).
- Jadval va davomat (`/api/school/*`): haftalik darslar (o'qituvchi/xona/guruh to'qnashuvi tekshiriladi),
  davomat (keldi/kechikdi/sababli/kelmadi), kunlik va oylik statistika. O'quvchi va ota-ona o'zinikini,
  o'qituvchi o'z guruhlarini ko'radi.
- O'qituvchi oyligi: qat'iy maosh, shu oyda qabul qilingan to'lovlardan foiz yoki har to'lagan o'quvchi uchun summa;
  o'qituvchi "Oyligim"da o'zinikini, "O'quvchilarim"da o'quvchilari telefoni, qarzi va davomatini ko'radi.
- Chegirma oylik tarifga sababi bilan qo'yiladi. Bir oy (davr) uchun ortiqcha yoki qayta to'lov qabul qilinmaydi.
- Qabul: yangi kelganlar fan bo'yicha yoziladi, guruh ochilganda bir bosishda o'quvchiga aylantiriladi. O'quvchi profilida to'lov va sertifikat.
- AI yordamchi (admin/menejer): `OPENAI_API_KEY` kerak; AI'ga faqat umumiy raqamlar yuboriladi (ism/telefon yo'q).
- O'quvchi profili: tug'ilgan sana va manzil (ixtiyoriy), qo'shimcha kurslar, davomat, test va vazifa natijalari.
- Yangi guruh: nom, fan, o'qituvchi va haftalik vaqt bir yo'la ("Dars jadvali"). Qabulda sinov darsi.
- Uy vazifasi: guruhga, barcha o'quvchilarga yoki bitta o'quvchiga, soat bilan muddat; ustoz baho qo'yadi.
- Tug'ilgan kun: o'quvchi tizimda tabrik ko'radi; Telegram ulangan bo'lsa o'quvchiga tabrik, ustozga eslatma yuboriladi (`BOT_TOKEN` kerak).
- O'qituvchiga avans/oylik berish: oylikdan ayiriladi va kassada "Ish haqi" xarajati bo'ladi.
- Ta'lim yangiliklari: `NEWS_RSS_URLS` (standart: kun.uz, gazeta.uz, daryo.uz, uza.uz), har 5 daqiqada yangilanadi.
- Moliya (`/api/finance/*`): to'lov, xarajat, oylik tarif, qarzdorlik, kassa, CSV eksport, audit log.
  Yozuvlar o'chirilmaydi — faqat sabab bilan bekor qilinadi. `DATABASE_URL` bo'lsa PostgreSQL'da, aks holda SQLite'da.
- CRM (`/api/crm/*`, admin menyusida "O'quvchilar (CRM)"): qabul, guruhga ko'chirish, muzlatish,
  qayta faollashtirish, bitiruvchilar va ketganlar arxivi, o'quvchi tarixi. Talaba o'chirilmaydi — "Ketgan"
  arxiviga o'tadi. Butun oy davomida faol bo'lmagan (muzlatilgan/arxivdagi) oylar uchun to'lov hisoblanmaydi.
- Testlar: `pip install pytest && python -m pytest tests -q`

Gunicorn bitta worker bilan ishga tushadi, chunki Telegram polling bitta bot token bilan faqat bitta workerda ishlashi kerak.
