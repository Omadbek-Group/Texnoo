import { Router } from 'express';
import { authenticate } from '../middleware/auth';
import officialExams from '../lib/official-exams.json';

// Rasmiy imtihon ma'lumotlari (DTM/UZBMB, CEFR, IELTS). Manba va tekshirilgan sana har bir yozuvda.
// Manbalar kuniga bir marta tekshiriladi (ulanish holati). Sanalar/narxlar avtomatik o'zgarmaydi,
// ularni faqat rasmiy manbadan qo'lda tasdiqlab JSON faylida yangilash kerak.
const router = Router();
router.use(authenticate);

const DAY_MS = 24 * 60 * 60 * 1000;
let lastCheck = 0;
let sourceStatus: Record<string, { ok: boolean; status?: number; checkedAt: string }> = {};

async function checkSources() {
  if (Date.now() - lastCheck < DAY_MS) return;
  lastCheck = Date.now();
  const urls = Array.from(new Set(officialExams.entries.map(e => e.source)));
  const results = await Promise.all(
    urls.map(async url => {
      try {
        const r = await fetch(url, { method: 'HEAD', signal: AbortSignal.timeout(8000) });
        return [url, { ok: r.ok, status: r.status, checkedAt: new Date().toISOString() }] as const;
      } catch {
        return [url, { ok: false, checkedAt: new Date().toISOString() }] as const;
      }
    })
  );
  sourceStatus = Object.fromEntries(results);
}

router.get('/', async (_req, res) => {
  await checkSources().catch(() => undefined);
  res.json({ ...officialExams, sourceStatus });
});

export { router as officialExamsRouter };
