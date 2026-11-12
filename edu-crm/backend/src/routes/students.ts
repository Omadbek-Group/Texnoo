import { Router } from 'express';
import prisma from '../lib/prisma';
import { authenticate, authorize } from '../middleware/auth';

const router = Router();

router.use(authenticate);

router.get('/', authorize(['ADMIN', 'MANAGER', 'TEACHER', 'CASHIER']), async (req, res) => {
  const query = req.query.q ? String(req.query.q) : undefined;
  const group = req.query.group ? String(req.query.group) : undefined;
  const course = req.query.course ? String(req.query.course) : undefined;
  const teacher = req.query.teacher ? String(req.query.teacher) : undefined;
  const where: any = {};

  if (query) {
    where.OR = [
      { firstName: { contains: query, mode: 'insensitive' } },
      { lastName: { contains: query, mode: 'insensitive' } },
      { phone: { contains: query, mode: 'insensitive' } },
      { parentPhone: { contains: query, mode: 'insensitive' } },
      { studentId: { contains: query, mode: 'insensitive' } }
    ];
  }

  if (group) {
    where.group = { name: { contains: group, mode: 'insensitive' } };
  }

  // Subject (course) and teacher filters apply through the student's group.
  if (course || teacher) {
    where.group = {
      ...where.group,
      ...(course && { course: { OR: [{ title: { contains: course, mode: 'insensitive' } }, { code: { contains: course, mode: 'insensitive' } }] } }),
      ...(teacher && { teacher: { name: { contains: teacher, mode: 'insensitive' } } })
    };
  }

  const students = await prisma.student.findMany({
    where,
    include: {
      group: { include: { course: true, teacher: true } }
    },
    orderBy: [{ updatedAt: 'desc' }]
  });

  res.json(students);
});

router.post('/', authorize(['ADMIN', 'MANAGER', 'CASHIER']), async (req, res) => {
  const {
    firstName,
    lastName,
    gender,
    dateOfBirth,
    phone,
    parentName,
    parentPhone,
    address,
    notes,
    photoUrl,
    groupId,
    studentId,
    status
  } = req.body;

  if (!firstName || !lastName || !gender || !dateOfBirth || !phone || !groupId || !studentId) {
    return res.status(400).json({ error: 'Missing required student fields' });
  }

  const group = await prisma.group.findUnique({ where: { id: Number(groupId) } });
  if (!group) {
    return res.status(404).json({ error: 'Group not found' });
  }

  const currentCount = await prisma.student.count({ where: { groupId: group.id } });
  if (currentCount >= group.capacity) {
    return res.status(422).json({ error: 'Group is full' });
  }

  const student = await prisma.student.create({
    data: {
      studentId,
      firstName,
      lastName,
      gender,
      dateOfBirth: new Date(dateOfBirth),
      phone,
      parentName,
      parentPhone,
      address,
      notes,
      photoUrl,
      status,
      groupId: group.id
    }
  });

  res.status(201).json(student);
});

router.get('/:id', authorize(['ADMIN', 'MANAGER', 'TEACHER', 'CASHIER']), async (req, res) => {
  const id = Number(req.params.id);
  const student = await prisma.student.findUnique({
    where: { id },
    include: { group: true, attendances: true, payments: true }
  });

  if (!student) {
    return res.status(404).json({ error: 'Student not found' });
  }

  res.json(student);
});

router.put('/:id', authorize(['ADMIN', 'MANAGER', 'CASHIER']), async (req, res) => {
  const id = Number(req.params.id);
  const payload = req.body;

  const student = await prisma.student.update({
    where: { id },
    data: {
      ...payload,
      dateOfBirth: payload.dateOfBirth ? new Date(payload.dateOfBirth) : undefined,
      groupId: payload.groupId ? Number(payload.groupId) : undefined
    }
  });

  res.json(student);
});

router.delete('/:id', authorize(['ADMIN', 'MANAGER']), async (req, res) => {
  const id = Number(req.params.id);
  await prisma.student.delete({ where: { id } });
  res.status(204).send();
});

export { router as studentsRouter };
