import { Router } from 'express';
import practice from '../lib/practice-coding.json';

// Bepul mashq testi (dasturlash). Javoblar faqat tekshirishda ishlatiladi, savollar bilan yuborilmaydi.
const router = Router();

router.get('/coding', (_req, res) => {
  res.json({
    subject: practice.subject,
    questions: practice.questions.map(({ id, text, options }) => ({ id, text, options }))
  });
});

router.post('/coding/check', (req, res) => {
  const answers: Record<string, number> = req.body?.answers ?? {};
  const results = practice.questions.map(q => ({
    id: q.id,
    correct: answers[String(q.id)] === q.answer,
    answer: q.answer
  }));
  const score = results.filter(r => r.correct).length;
  res.json({ score, total: practice.questions.length, results });
});

export { router as practiceRouter };
