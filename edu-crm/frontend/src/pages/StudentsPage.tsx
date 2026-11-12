import { FormEvent, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { Modal } from '../components/Modal';
import { Pagination } from '../components/Pagination';
import { unwrapListResponse } from '../utils/api';

interface Student {
  id: number;
  studentId: string;
  firstName: string;
  lastName: string;
  gender?: string;
  dateOfBirth?: string;
  phone: string;
  parentName?: string;
  parentPhone?: string;
  address?: string;
  notes?: string;
  photoUrl?: string | null;
  status: string;
  group: { id: number; name: string; course: { id?: number; title: string }; teacher?: { name: string } };
}

interface Course {
  id: number;
  title: string;
  code: string;
}

interface Group {
  id: number;
  name: string;
  availableSeats: number;
  course: { id: number; title: string };
}

export function StudentsPage() {
  const [students, setStudents] = useState<Student[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [courseQuery, setCourseQuery] = useState('');
  const [teacherQuery, setTeacherQuery] = useState('');
  const [page, setPage] = useState(1);
  const [meta, setMeta] = useState({ page: 1, limit: 20, total: 0 });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Student | null>(null);
  const [form, setForm] = useState({
    studentId: '',
    firstName: '',
    lastName: '',
    gender: 'MALE',
    dateOfBirth: '',
    phone: '',
    parentName: '',
    parentPhone: '',
    address: '',
    notes: '',
    photoUrl: '',
    groupId: 0,
    status: 'ACTIVE'
  });
  const [selectedCourseId, setSelectedCourseId] = useState<number | null>(null);

  useEffect(() => {
    loadStudents();
    loadLookups();
  }, [search, statusFilter, courseQuery, teacherQuery, page]);

  const filteredGroups = useMemo(() => {
    if (!selectedCourseId) return groups;
    return groups.filter(group => group.course.id === selectedCourseId);
  }, [groups, selectedCourseId]);

  async function loadStudents() {
    setLoading(true);
    setError('');
    try {
      const response = await axios.get('/api/students', {
        params: { q: search, status: statusFilter, course: courseQuery, teacher: teacherQuery, page, limit: meta.limit }
      });
      const payload = unwrapListResponse<Student[]>(response);
      setStudents(payload.data);
      setMeta(payload.meta);
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to load students.');
    } finally {
      setLoading(false);
    }
  }

  async function loadLookups() {
    try {
      const [coursesResponse, groupsResponse] = await Promise.all([
        axios.get('/api/courses', { params: { limit: 100 } }),
        axios.get('/api/groups', { params: { limit: 200 } })
      ]);
      setCourses(unwrapListResponse<Course[]>(coursesResponse).data);
      setGroups(unwrapListResponse<Group[]>(groupsResponse).data);
    } catch (err) {
      // ignore; lookup data is optional for the page to load
    }
  }

  function openCreateModal() {
    setEditing(null);
    setForm({
      studentId: '',
      firstName: '',
      lastName: '',
      gender: 'MALE',
      dateOfBirth: '',
      phone: '',
      parentName: '',
      parentPhone: '',
      address: '',
      notes: '',
      photoUrl: '',
      groupId: 0,
      status: 'ACTIVE'
    });
    setSelectedCourseId(null);
    setModalOpen(true);
  }

  function openEditModal(student: Student) {
    setEditing(student);
    setForm({
      studentId: student.studentId,
      firstName: student.firstName,
      lastName: student.lastName,
      gender: student.gender ?? 'MALE',
      dateOfBirth: '',
      phone: student.phone,
      parentName: student.parentName ?? '',
      parentPhone: student.parentPhone ?? '',
      address: student.address ?? '',
      notes: '',
      photoUrl: student.photoUrl ?? '',
      groupId: student.group.id,
      status: student.status
    });
    setSelectedCourseId(student.group.course.id ?? null);
    setModalOpen(true);
  }

  async function submitForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError('');

    const payload = {
      ...form,
      groupId: Number(form.groupId)
    };

    try {
      if (editing) {
        await axios.put(`/api/students/${editing.id}`, payload);
      } else {
        await axios.post('/api/students', payload);
      }
      setModalOpen(false);
      loadStudents();
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to save student.');
    } finally {
      setLoading(false);
    }
  }

  async function deleteStudent(id: number) {
    if (!window.confirm('Delete this student permanently?')) return;
    setLoading(true);
    setError('');
    try {
      await axios.delete(`/api/students/${id}`);
      loadStudents();
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to delete student.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="page-heading">
        <div>
          <h1>Students</h1>
          <p className="subtitle">Manage registrations, assignments, payments, and student profiles.</p>
        </div>
        <button className="primary-button" onClick={openCreateModal}>New Student</button>
      </div>

      <div className="toolbar-row">
        <input
          placeholder="Search by name, phone, ID or group"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          <option value="ACTIVE">Active</option>
          <option value="FROZEN">Frozen</option>
          <option value="FINISHED">Finished</option>
        </select>
      </div>

      <div className="toolbar-row">
        <input
          placeholder="Fan bo'yicha (subject)"
          value={courseQuery}
          onChange={e => { setCourseQuery(e.target.value); setPage(1); }}
        />
        <input
          placeholder="O'qituvchi bo'yicha (teacher)"
          value={teacherQuery}
          onChange={e => { setTeacherQuery(e.target.value); setPage(1); }}
        />
      </div>

      {error && <div className="alert">{error}</div>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Student ID</th>
              <th>Name</th>
              <th>Contact</th>
              <th>Group</th>
              <th>Status</th>
              <th>Course</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={7} className="loading-row">Loading students...</td></tr>
            ) : students.length ? (
              students.map(student => (
                <tr key={student.id}>
                  <td>{student.studentId}</td>
                  <td>{student.firstName} {student.lastName}</td>
                  <td>{student.phone}</td>
                  <td>{student.group.name}</td>
                  <td>{student.status}</td>
                  <td>{student.group.course.title}</td>
                  <td>
                    <button className="small-button" onClick={() => openEditModal(student)}>Edit</button>
                    <button className="outline-button small" onClick={() => deleteStudent(student.id)}>Delete</button>
                  </td>
                </tr>
              ))
            ) : (
              <tr><td colSpan={7} className="empty-row">No students found.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <Pagination page={meta.page} limit={meta.limit} total={meta.total} onPageChange={setPage} />

      <Modal title={editing ? 'Edit Student' : 'Register Student'} open={modalOpen} onClose={() => setModalOpen(false)}>
        <form className="entity-form" onSubmit={submitForm}>
          <div className="form-grid">
            <label>
              Student ID
              <input value={form.studentId} onChange={e => setForm({ ...form, studentId: e.target.value })} required />
            </label>
            <label>
              First name
              <input value={form.firstName} onChange={e => setForm({ ...form, firstName: e.target.value })} required />
            </label>
            <label>
              Last name
              <input value={form.lastName} onChange={e => setForm({ ...form, lastName: e.target.value })} required />
            </label>
            <label>
              Phone
              <input value={form.phone} onChange={e => setForm({ ...form, phone: e.target.value })} required />
            </label>
            <label>
              Gender
              <select value={form.gender} onChange={e => setForm({ ...form, gender: e.target.value })}>
                <option value="MALE">Male</option>
                <option value="FEMALE">Female</option>
                <option value="OTHER">Other</option>
              </select>
            </label>
            <label>
              Date of birth
              <input type="date" value={form.dateOfBirth} onChange={e => setForm({ ...form, dateOfBirth: e.target.value })} required />
            </label>
            <label>
              Status
              <select value={form.status} onChange={e => setForm({ ...form, status: e.target.value })}>
                <option value="ACTIVE">Active</option>
                <option value="FROZEN">Frozen</option>
                <option value="FINISHED">Finished</option>
              </select>
            </label>
            <label>
              Course
              <select value={selectedCourseId ?? ''} onChange={e => setSelectedCourseId(Number(e.target.value) || null)}>
                <option value="">Choose a course</option>
                {courses.map(course => (
                  <option key={course.id} value={course.id}>{course.title}</option>
                ))}
              </select>
            </label>
            <label>
              Group
              <select value={form.groupId} onChange={e => setForm({ ...form, groupId: Number(e.target.value) })} required>
                <option value={0}>Choose a group</option>
                {filteredGroups.map(group => (
                  <option key={group.id} value={group.id}>
                    {group.name} ({group.availableSeats} seats left)
                  </option>
                ))}
              </select>
            </label>
            <label>
              Parent name
              <input value={form.parentName} onChange={e => setForm({ ...form, parentName: e.target.value })} />
            </label>
            <label>
              Parent phone
              <input value={form.parentPhone} onChange={e => setForm({ ...form, parentPhone: e.target.value })} />
            </label>
            <label>
              Address
              <input value={form.address} onChange={e => setForm({ ...form, address: e.target.value })} />
            </label>
            <label className="full-width">
              Notes
              <textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} rows={3} />
            </label>
          </div>
          <div className="form-actions">
            <button type="submit" className="primary-button">Save student</button>
            <button type="button" className="outline-button" onClick={() => setModalOpen(false)}>Cancel</button>
          </div>
          {error && <div className="alert">{error}</div>}
        </form>
      </Modal>
    </div>
  );
}
