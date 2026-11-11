import { Navigate, Route, Routes } from 'react-router-dom'

import ProtectedRoute from './auth/ProtectedRoute.jsx'
import Layout from './components/Layout.jsx'
import AccountPage from './pages/AccountPage.jsx'
import AdminAuditLogPage from './pages/AdminAuditLogPage.jsx'
import AdminEmailsPage from './pages/AdminEmailsPage.jsx'
import ReportsPage from './pages/ReportsPage.jsx'
import AdminLeaveRequestsPage from './pages/AdminLeaveRequestsPage.jsx'
import ApprovalsInboxPage from './pages/ApprovalsInboxPage.jsx'
import ApproversPage from './pages/ApproversPage.jsx'
import CalendarSettingsPage from './pages/CalendarSettingsPage.jsx'
import DepartmentsPage from './pages/DepartmentsPage.jsx'
import DivisionsPage from './pages/DivisionsPage.jsx'
import EmployeesPage from './pages/EmployeesPage.jsx'
import ForgotPasswordPage from './pages/ForgotPasswordPage.jsx'
import HomePage from './pages/HomePage.jsx'
import LeaveAssignmentsPage from './pages/LeaveAssignmentsPage.jsx'
import LeaveRequestDetailPage from './pages/LeaveRequestDetailPage.jsx'
import LeaveRequestFormPage from './pages/LeaveRequestFormPage.jsx'
import LeaveTypesPage from './pages/LeaveTypesPage.jsx'
import LeaveYearsPage from './pages/LeaveYearsPage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import MyBalancesPage from './pages/MyBalancesPage.jsx'
import MyLeaveRequestsPage from './pages/MyLeaveRequestsPage.jsx'
import QuickApprovalPage from './pages/QuickApprovalPage.jsx'
import ResetPasswordPage from './pages/ResetPasswordPage.jsx'
import TeamBalancesPage from './pages/TeamBalancesPage.jsx'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/quick-approval" element={<QuickApprovalPage />} />

      {/* Everything below requires a logged-in user. */}
      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="account" element={<AccountPage />} />
          <Route path="my-balances" element={<MyBalancesPage />} />
          <Route path="leave-requests/new" element={<LeaveRequestFormPage />} />
          <Route path="leave-requests/:id" element={<LeaveRequestDetailPage />} />
          <Route path="my-requests" element={<MyLeaveRequestsPage />} />

          {/* Supervisor / Admin team balances screen. */}
          <Route element={<ProtectedRoute requireSupervisor />}>
            <Route path="team-balances" element={<TeamBalancesPage />} />
          </Route>

          {/* Admin-only screens. */}
          {/* Approver-only screen. */}
          <Route element={<ProtectedRoute roles={['APPROVER']} />}>
            <Route path="approvals" element={<ApprovalsInboxPage />} />
          </Route>

          {/* Admin-only screens. */}
          <Route element={<ProtectedRoute roles={['ADMIN']} />}>
            <Route path="approvers" element={<ApproversPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="admin/emails" element={<AdminEmailsPage />} />
            <Route path="admin/audit-log" element={<AdminAuditLogPage />} />
            <Route path="admin/leave-requests" element={<AdminLeaveRequestsPage />} />
            <Route path="assignments" element={<LeaveAssignmentsPage />} />
            <Route path="calendar-settings" element={<CalendarSettingsPage />} />
            <Route path="divisions" element={<DivisionsPage />} />
            <Route path="departments" element={<DepartmentsPage />} />
            <Route path="employees" element={<EmployeesPage />} />
            <Route path="leave-years" element={<LeaveYearsPage />} />
            <Route path="leave-types" element={<LeaveTypesPage />} />
          </Route>
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
