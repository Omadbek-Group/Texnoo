import { Router } from 'express';
import prisma from '../lib/prisma';
import { authenticate, authorize } from '../middleware/auth';

const router = Router();
router.use(authenticate);

router.get('/', authorize(['ADMIN', 'MANAGER', 'CASHIER']), async (req, res) => {
  const studentId = req.query.studentId ? Number(req.query.studentId) : undefined;
  const groupId = req.query.groupId ? Number(req.query.groupId) : undefined;
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
  if (search) {
    where.OR = [
      { reference: { contains: search, mode: 'insensitive' } },
      { method: { contains: search, mode: 'insensitive' } },
      { note: { contains: search, mode: 'insensitive' } },
      { student: { firstName: { contains: search, mode: 'insensitive' } } },
      { student: { lastName: { contains: search, mode: 'insensitive' } } },
      { student: { studentId: { contains: search, mode: 'insensitive' } } },
      { group: { name: { contains: search, mode: 'insensitive' } } }
    ];
  }

  const [payments, total] = await Promise.all([
    prisma.payment.findMany({
      where,
      include: { student: true, group: true },
      orderBy: [{ paidAt: 'desc' }],
      skip,
      take: limit
    }),
    prisma.payment.count({ where })
  ]);

  res.json({ data: payments, meta: { page, limit, total } });
});

// Qarzdorlar: joriy oyda to'lovi guruh oylik to'lovidan kam bo'lgan faol o'quvchilar.
router.get('/debtors', authorize(['ADMIN', 'MANAGER', 'CASHIER']), async (_req, res) => {
  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
  const students = await prisma.student.findMany({
    where: { status: 'ACTIVE', group: { monthlyFee: { gt: 0 } } },
    include: { group: { include: { course: true, teacher: true } }, payments: { where: { paidAt: { gte: monthStart } } } }
  });
  const debtors = students
    .map(s => {
      const paid = s.payments.reduce((sum, p) => sum + Number(p.amount), 0);
      return { id: s.id, studentId: s.studentId, firstName: s.firstName, lastName: s.lastName, phone: s.phone, parentPhone: s.parentPhone, group: s.group, paid, owed: s.group.monthlyFee - paid };
    })
    .filter(d => d.owed > 0);
  res.json({ data: debtors, meta: { total: debtors.length, month: monthStart.toISOString().slice(0, 7) } });
});

router.post('/', authorize(['ADMIN', 'MANAGER', 'CASHIER']), async (req, res) => {
  const { studentId, groupId, amount, method, paidAt, reference, note } = req.body;
  if (!studentId || !groupId || !amount || !method) {
    return res.status(400).json({ error: 'Missing payment fields' });
  }
  const payment = await prisma.payment.create({
    data: {
      studentId: Number(studentId),
      groupId: Number(groupId),
      amount: Number(amount),
      method,
      paidAt: paidAt ? new Date(paidAt) : new Date(),
      reference,
      note
    },
    include: { student: true, group: true }
  });
  res.status(201).json(payment);
});

router.get('/receipt/:id', authorize(['ADMIN', 'MANAGER', 'CASHIER']), async (req, res) => {
  const id = Number(req.params.id);
  const payment = await prisma.payment.findUnique({
    where: { id },
    include: { student: true, group: true }
  });
  if (!payment) {
    return res.status(404).json({ error: 'Payment receipt not found' });
  }
  res.json(payment);
});

router.get('/balance/:studentId', authorize(['ADMIN', 'MANAGER', 'CASHIER']), async (req, res) => {
  const studentId = Number(req.params.studentId);
  const student = await prisma.student.findUnique({
    where: { id: studentId },
    include: { payments: true, group: true }
  });

  if (!student) {
    return res.status(404).json({ error: 'Student not found' });
  }

  const totalPaid = student.payments.reduce((sum, payment) => sum + Number(payment.amount), 0);
  const now = new Date();
  const start = new Date(student.group.startDate);
  const end = student.group.endDate ? new Date(student.group.endDate) : now;
  const effectiveEnd = now < end ? now : end;
  const months = Math.max(
    1,
    (effectiveEnd.getFullYear() - start.getFullYear()) * 12 + (effectiveEnd.getMonth() - start.getMonth()) + 1
  );
  const expectedTotal = months * student.group.monthlyFee;

  res.json({
    studentId: student.id,
    monthlyFee: student.group.monthlyFee,
    totalPaid,
    expectedTotal,
    balance: Number(totalPaid) - expectedTotal
  });
});

router.delete('/:id', authorize(['ADMIN', 'MANAGER', 'CASHIER']), async (req, res) => {
  const id = Number(req.params.id);
  await prisma.payment.delete({ where: { id } });
  res.status(204).send();
});

export { router as paymentRouter };
