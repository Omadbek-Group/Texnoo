import express, { json, urlencoded } from 'express';
import cors from 'cors';
import helmet from 'helmet';
import cookieParser from 'cookie-parser';
import morgan from 'morgan';
import rateLimit from 'express-rate-limit';
import 'express-async-errors';
import { getConfig } from './config';
import { authRouter } from './routes/auth';
import { studentsRouter } from './routes/students';
import { groupsRouter } from './routes/groups';
import { teachersRouter } from './routes/teachers';
import { usersRouter } from './routes/users';
import { dashboardRouter } from './routes/dashboard';
import { paymentRouter } from './routes/payments';
import { attendanceRouter } from './routes/attendance';
import { coursesRouter } from './routes/courses';
import { classroomsRouter } from './routes/classrooms';
import { officialExamsRouter } from './routes/officialExams';
import { errorHandler } from './middleware/errorHandler';
import prisma from './lib/prisma';

const { corsOrigin, rateLimitWindowMs, rateLimitMax, nodeEnv } = getConfig();

const app = express();

// Security headers
app.use(
  helmet({
    contentSecurityPolicy: nodeEnv === 'production' ? undefined : false,
    crossOriginEmbedderPolicy: false,
  }),
);

// Trust proxy (Railway/Vercel kabi xizmatlar uchun)
app.set('trust proxy', 1);

// Global rate limiter (brute force oldini olish)
const limiter = rateLimit({
  windowMs: rateLimitWindowMs,
  max: rateLimitMax,
  standardHeaders: true,
  legacyHeaders: false,
  message: { error: 'So‘rovlar chegarasi etildi. Birozdan keyin qayta urinib ko‘ring.' },
});
app.use('/api/', limiter);

// Auth endpointlari uchun alohida qattiqroq limit (login brute force oldini olish)
const authLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 15,
  standardHeaders: true,
  legacyHeaders: false,
  message: { error: "Kirish urinishlari ko'p. 15 daqiqa kuting." },
});

// CORS
app.use(
  cors({
    origin: corsOrigin,
    credentials: true,
    methods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
    allowedHeaders: ['Content-Type', 'Authorization', 'X-Requested-With'],
  }),
);

// Body parsers
app.use(json({ limit: '1mb' }));
app.use(urlencoded({ extended: true, limit: '1mb' }));
app.use(cookieParser());

// HTTP logging
app.use(morgan(nodeEnv === 'production' ? 'combined' : 'dev'));

// Root health check
app.get('/health', async (_req, res) => {
  let dbStatus = 'connecting';
  let dbError: string | null = null;
  try {
    await prisma.$queryRaw`SELECT 1::int AS ping`.then(() => { dbStatus = 'online'; });
  } catch (err) {
    dbStatus = 'offline';
    dbError = (err as Error).message;
  }
  res.status(dbStatus === 'online' ? 200 : 503).json({
    status: dbStatus === 'online' ? 'ok' : 'degraded',
    uptime: process.uptime(),
    env: nodeEnv,
    services: {
      http: 'online',
      db: dbStatus,
    },
    ...(dbError && nodeEnv !== 'production' ? { dbError } : {}),
  });
});

// Routelar
app.use('/api/auth', authLimiter, authRouter);
app.use('/api/users', usersRouter);
app.use('/api/students', studentsRouter);
app.use('/api/groups', groupsRouter);
app.use('/api/teachers', teachersRouter);
app.use('/api/dashboard', dashboardRouter);
app.use('/api/payments', paymentRouter);
app.use('/api/attendance', attendanceRouter);
app.use('/api/courses', coursesRouter);
app.use('/api/classrooms', classroomsRouter);
app.use('/api/official-exams', officialExamsRouter);

// 404 for API
app.use('/api/*', (req, res) => {
  res.status(404).json({ error: `API endpoint topilmadi: ${req.method} ${req.originalUrl}` });
});

// Global xato handleri (eng oxirida bo'lishi kerak!)
app.use(errorHandler);

export default app;

