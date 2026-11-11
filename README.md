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
- Admin hisoblari darajasi: `platform_admin`, `school_admin`, `cashier` (kassir faqat moliya bo'limini ko'radi).
- Moliya (`/api/finance/*`): to'lov, xarajat, oylik tarif, qarzdorlik, kassa, CSV eksport, audit log.
  Yozuvlar o'chirilmaydi — faqat sabab bilan bekor qilinadi. `DATABASE_URL` bo'lsa PostgreSQL'da, aks holda SQLite'da.
- CRM (`/api/crm/*`, admin menyusida "O'quvchilar (CRM)"): qabul, guruhga ko'chirish, muzlatish,
  qayta faollashtirish, bitiruvchilar va ketganlar arxivi, o'quvchi tarixi. Talaba o'chirilmaydi — "Ketgan"
  arxiviga o'tadi. Butun oy davomida faol bo'lmagan (muzlatilgan/arxivdagi) oylar uchun to'lov hisoblanmaydi.
- Testlar: `pip install pytest && python -m pytest tests -q`

Gunicorn bitta worker bilan ishga tushadi, chunki Telegram polling bitta bot token bilan faqat bitta workerda ishlashi kerak.
