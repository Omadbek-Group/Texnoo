import { Outlet, NavLink } from 'react-router-dom';
import { useAuth } from '../stores/auth';

export function Layout() {
  const { logout } = useAuth();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">Edu CRM</div>
        <nav>
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/users">Foydalanuvchilar</NavLink>
          <NavLink to="/students">Students</NavLink>
          <NavLink to="/groups">Groups</NavLink>
          <NavLink to="/teachers">Teachers</NavLink>
          <NavLink to="/courses">Courses</NavLink>
          <NavLink to="/classrooms">Classrooms</NavLink>
          <NavLink to="/payments">Payments</NavLink>
          <NavLink to="/attendance">Attendance</NavLink>
          <NavLink to="/schedule">Schedule</NavLink>
          <NavLink to="/practice">Mashq testi</NavLink>
        </nav>
        <button className="outline-button" onClick={logout}>Logout</button>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
