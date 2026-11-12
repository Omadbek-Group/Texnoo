import { Route, Routes, Navigate } from 'react-router-dom';
import { DashboardPage } from './pages/DashboardPage';
import { StudentsPage } from './pages/StudentsPage';
import { GroupsPage } from './pages/GroupsPage';
import { TeachersPage } from './pages/TeachersPage';
import { CoursesPage } from './pages/CoursesPage';
import { ClassroomsPage } from './pages/ClassroomsPage';
import { PaymentsPage } from './pages/PaymentsPage';
import { AttendancePage } from './pages/AttendancePage';
import { SchedulePage } from './pages/SchedulePage';
import { PracticePage } from './pages/PracticePage';
import { UsersPage } from './pages/UsersPage';
import { LoginPage } from './pages/LoginPage';
import { AuthProvider, useAuth, UserRole } from './stores/auth';
import { Layout } from './components/Layout';

interface PrivateRouteProps {
  children: JSX.Element;
  roles?: UserRole[];
}

function PrivateRoute({ children, roles = [] }: PrivateRouteProps) {
  const { isAuthenticated, loading, user } = useAuth();

  if (loading) {
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--color-text-primary, #e6eafc)',
          fontFamily: 'var(--font-body, system-ui)',
        }}
      >
        Yuklanmoqda...
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (roles.length > 0 && user && !roles.includes(user.role)) {
    return <Navigate to="/" replace />;
  }

  return children;
}

function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <PrivateRoute>
              <Layout />
            </PrivateRoute>
          }
        >
          <Route index element={<DashboardPage />} />
          <Route path="students" element={<StudentsPage />} />
          <Route path="groups" element={<GroupsPage />} />
          <Route path="teachers" element={<TeachersPage />} />
          <Route path="users" element={<UsersPage />} />
          <Route path="courses" element={<CoursesPage />} />
          <Route path="classrooms" element={<ClassroomsPage />} />
          <Route path="payments" element={<PaymentsPage />} />
          <Route path="attendance" element={<AttendancePage />} />
          <Route path="schedule" element={<SchedulePage />} />
          <Route path="practice" element={<PracticePage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}

export default App;

