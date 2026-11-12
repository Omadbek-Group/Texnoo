import { Router } from 'express';
import prisma from '../lib/prisma';
import { authenticate, authorize } from '../middleware/auth';

const router = Router();
router.use(authenticate);

router.get('/', authorize(['ADMIN', 'MANAGER', 'TEACHER']), async (req, res) => {
  const studentId = req.query.studentId ? Number(req.query.studentId) : undefined;
  const groupId = req.query.groupId ? Number(req.query.groupId) : undefined;
  const status = req.query.status ? String(req.query.status) : undefined;
  const search = req.query.q ? String(req.query.q) : undefined;
  const page = Number(req.query.page || 1);
  const limit = Math.min(Number(req.query.limit || 20), 100);
  const skip = (page - 1) * limit;
  const where: any = {};

  if (studentId) {
    where.studentId = studentId;
  }
  if (groupId) {
    where.groupId = groupId;
  }
  if (status) {
    where.status = status;
  }
  if (search) {
    where.OR = [
      { note: { contains: search, mode: 'insensitive' } },
      { status: { contains: search, mode: 'insensitive' } },
      { student: { firstName: { contains: search, mode: 'insensitive' } } },
      { student: { lastName: { contains: search, mode: 'insensitive' } } },
      { student: { studentId: { contains: search, mode: 'insensitive' } } },
      { group: { name: { contains: search, mode: 'insensitive' } } }
    ];
  }

  const [attendances, total] = await Promise.all([
    prisma.attendance.findMany({
      where,
      include: { student: true, group: true },
      orderBy: [{ date: 'desc' }],
      skip,
      take: limit
    }),
    prisma.attendance.count({ where })
  ]);

  res.json({ data: attendances, meta: { page, limit, total } });
});

router.post('/', authorize(['ADMIN', 'MANAGER', 'TEACHER']), async (req, res) => {
  const { studentId, groupId, date, status, note } = req.body;
  if (!studentId || !groupId || !date || !status) {
    return res.status(400).json({ error: 'Missing attendance fields' });
  }

  const attendance = await prisma.attendance.create({
    data: {
      studentId: Number(studentId),
      groupId: Number(groupId),
      date: new Date(date),
      status,
      note
    },
    include: { student: true, group: true }
  });

  // "Keldi" xabari: o'quvchi darsga kelganda ekranda ko'rsatiladi.
  const arrived = status === 'PRESENT' || status === 'LATE';
  const message = arrived ? `${attendance.student.firstName} ${attendance.student.lastName} keldi` : undefined;
  res.status(201).json({ ...attendance, message });
});

router.get('/student/:studentId', authorize(['ADMIN', 'MANAGER', 'TEACHER']), async (req, res) => {
  const studentId = Number(req.params.studentId);
  const attendances = await prisma.attendance.findMany({
    where: { studentId },
    include: { group: true },
    orderBy: [{ date: 'desc' }]
  });
  res.json(attendances);
});

router.delete('/:id', authorize(['ADMIN', 'MANAGER']), async (req, res) => {
  const id = Number(req.params.id);
  await prisma.attendance.delete({ where: { id } });
  res.status(204).send();
});

export { router as attendanceRouter };
