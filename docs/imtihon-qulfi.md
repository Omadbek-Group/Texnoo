# Qabul imtihoni: sahifani qat'iy qulflash

Veb-sahifa o'zi foydalanuvchini to'liq qulflay olmaydi. Qat'iy qulf uchun quyidagi usullardan birini qo'llang.

## 1. Chrome kiosk rejimi (eng oddiy)

Imtihon kompyuterida Chrome'ni to'liq ekranda, manzil satrisiz ochish:

```bash
chrome --kiosk --incognito "https://SAYT-MANZILI/practice"
```

Foydalanuvchi boshqa sahifaga o'tolmaydi (Alt+F4 va Ctrl+W bundan mustasno). Buni to'liq to'xtatish uchun imtihon kompyuterida Windows Assigned Access (faqat bitta ilova) yoqiladi.

## 2. Windows Assigned Access

Sozlamalar > Hisoblar > Boshqa foydalanuvchilar > Kiosk (Assigned access) orqali faqat Chrome yoki Edge ni bitta sayt bilan ishlatish mumkin.

## 3. Alohida ilova

Mashq sahifasini Electron yoki Capacitor ilovasi sifatida o'rab, faqat shu sahifani ochadigan qilish mumkin. Bu eng ishonchli variant.

## Dasturiy cheklovlar (allaqachon bor)

- Imtihon boshlanganda sahifadan chiqishda ogohlantirish chiqadi.
- Vaqt tugasa, javoblar avtomatik topshiriladi.

## Eslatma

Qabul imtihonida o'quvchi natijasi serverda saqlanmaydi. Buni qo'shish uchun bazaga yangi model kerak.
