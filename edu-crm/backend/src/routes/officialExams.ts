import { Router } from 'express';
import { authenticate } from '../middleware/auth';
import officialExams from '../lib/official-exams.json';

// Rasmiy imtihon ma'lumotlari (DTM/UZBMB, CEFR, IELTS). Manba va tekshirilgan sana har bir yozuvda.
const router = Router();
router.use(authenticate);

router.get('/', (_req, res) => {
  res.json(officialExams);
});

export { router as officialExamsRouter };
