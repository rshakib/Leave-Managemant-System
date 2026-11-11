import { useEffect, useMemo, useState } from 'react'
import { Alert, Badge, Button } from 'react-bootstrap'
import { Link, Navigate, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import api from '../api/client'
import { useAuth } from '../auth/AuthContext.jsx'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'
import { getInitials } from '../utils/initials.js'
import Icon from './Icon.jsx'

// Navigation lives in the sidebar, grouped so it stays readable as the app
// grows. `roles` limits an entry to the people who can actually open it.
const SECTIONS = [
  {
    title: 'My leave',
    items: [
      { to: '/', label: 'Home', icon: 'home', end: true },
      { to: '/my-balances', label: 'My balances', icon: 'balance' },
      { to: '/leave-requests/new', label: 'Request leave', icon: 'plus', roles: ['EMPLOYEE'] },
      { to: '/my-requests', label: 'My requests', icon: 'list', roles: ['EMPLOYEE'] },
    ],
  },
  {
    title: 'Team & Approvals',
    items: [
      { to: '/approvals', label: 'Approvals', icon: 'check', roles: ['APPROVER'], showCount: true },
      { to: '/team-balances', label: 'Team balances', icon: 'users', supervisorOnly: true },
    ],
  },
  {
    title: 'Administration',
    items: [
      { to: '/admin/leave-requests', label: 'All requests', icon: 'list', roles: ['ADMIN'] },
      { to: '/reports', label: 'Reports', icon: 'chart', roles: ['ADMIN'] },
      { to: '/approvers', label: 'Approvers', icon: 'workflow', roles: ['ADMIN'] },
      { to: '/assignments', label: 'Assignments', icon: 'sliders', roles: ['ADMIN'] },
      { to: '/calendar-settings', label: 'Calendar settings', icon: 'calendar', roles: ['ADMIN'] },
      { to: '/divisions', label: 'Divisions', icon: 'building', roles: ['ADMIN'] },
      { to: '/departments', label: 'Departments', icon: 'layers', roles: ['ADMIN'] },
      { to: '/employees', label: 'Employees', icon: 'users', roles: ['ADMIN'] },
      { to: '/leave-years', label: 'Leave years', icon: 'calendar', roles: ['ADMIN'] },
      { to: '/leave-types', label: 'Leave types', icon: 'tag', roles: ['ADMIN'] },
    ],
  },
  {
    title: 'System',
    items: [
      { to: '/admin/emails', label: 'Email log', icon: 'mail', roles: ['ADMIN'] },
      { to: '/admin/audit-log', label: 'Audit log', icon: 'shield', roles: ['ADMIN'] },
    ],
  },
]

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [pendingApprovals, setPendingApprovals] = useState(0)
  const [reloadKey, setReloadKey] = useState(0)

  // A stable string keeps the memo below from re-running on every render.
  const roleKey = [...(user?.roles ?? [])].sort().join(', ')
  const roles = useMemo(() => (roleKey ? roleKey.split(', ') : []), [roleKey])
  const isApprover = roles.includes('APPROVER')
  const isSupervisor = Boolean(user?.is_supervisor || roles.includes('ADMIN'))

  const sections = useMemo(() => {
    const owned = roleKey ? roleKey.split(', ') : []
    return SECTIONS.map((section) => ({
      ...section,
      items: section.items.filter((item) => {
        if (item.supervisorOnly && !isSupervisor) return false
        if (item.roles && !item.roles.some((role) => owned.includes(role))) return false
        return true
      }),
    })).filter((section) => section.items.length > 0)
  }, [roleKey, isSupervisor])

  // Close the drawer whenever the route changes (it is a mobile-only concern).
  useEffect(() => {
    setSidebarOpen(false)
  }, [location.pathname])

  // Refresh the approvals badge after every navigation and after every decision.
  useEffect(() => {
    if (!isApprover) {
      setPendingApprovals(0)
      return undefined
    }
    let cancelled = false

    const load = () => {
      api
        .get('/approvals/inbox/count')
        .then(({ data }) => {
          if (!cancelled) {
            const count = data.total ?? ((data.pending ?? 0) + (data.early_returns ?? 0))
            setPendingApprovals(count)
          }
        })
        .catch(() => {})
    }

    load()
    window.addEventListener('approvals-changed', load)
    return () => {
      cancelled = true
      window.removeEventListener('approvals-changed', load)
    }
  }, [isApprover, location.pathname, reloadKey])

  // Keep the badge live (new requests, decisions elsewhere, tab returning).
  useAutoRefresh(() => setReloadKey((key) => key + 1))

  const activeLabel = useMemo(() => {
    for (const section of sections) {
      for (const item of section.items) {
        if (item.end ? location.pathname === item.to : location.pathname.startsWith(item.to)) {
          return item.label
        }
      }
    }
    if (location.pathname.startsWith('/leave-requests/')) return 'Request details'
    return 'Dashboard'
  }, [sections, location.pathname])

  // An administrator typed this password, so the person must choose their own
  // before using anything else. The API refuses every other route anyway; this
  // keeps the screen honest (D-190).
  const mustChangePassword = Boolean(user?.must_change_password)
  if (mustChangePassword && location.pathname !== '/account') {
    return <Navigate to="/account" replace />
  }

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="lms-shell">
      <aside className={`lms-sidebar${sidebarOpen ? ' is-open' : ''}`}>
        <Link to="/" className="lms-sidebar__brand">
          <span className="lms-brand-mark">
            <Icon name="sun" size={18} />
          </span>
          <span className="lms-brand-text">
            <span className="lms-brand-name">SOLshare</span>
            <span className="lms-brand-sub">Leave Management</span>
          </span>
        </Link>

        <nav className="lms-sidebar__nav">
          {sections.map((section) => (
            <div className="lms-sidebar__section" key={section.title}>
              <div className="lms-sidebar__label">{section.title}</div>
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `lms-navlink${isActive ? ' is-active' : ''}`
                  }
                >
                  <Icon name={item.icon} className="lms-navlink__icon" />
                  <span>{item.label}</span>
                  {item.showCount && pendingApprovals > 0 && (
                    <Badge bg="danger" pill className="lms-navlink__badge">
                      {pendingApprovals}
                    </Badge>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="lms-sidebar__footer lms-sidebar__user">
          <Link to="/account" className="lms-sidebar__account">
            <span className="lms-user__avatar">{getInitials(user?.full_name)}</span>
            <span className="lms-sidebar__who">
              <span className="lms-user__name">{user?.full_name}</span>
              <span className="lms-user__roles">{roles.join(' · ')}</span>
            </span>
          </Link>
          <Button variant="outline-light" size="sm" className="w-100 mt-2" onClick={handleLogout}>
            <Icon name="logout" size={16} className="me-1" />
            Logout
          </Button>
        </div>
      </aside>

      {sidebarOpen && (
        <button
          type="button"
          className="lms-scrim"
          aria-label="Close the menu"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <div className="lms-main">
        <header className="lms-topbar">
          <Button
            variant="outline-secondary"
            size="sm"
            className="lms-menu-button"
            onClick={() => setSidebarOpen((open) => !open)}
            aria-label="Toggle the menu"
          >
            <Icon name={sidebarOpen ? 'close' : 'menu'} />
          </Button>

          <h1 className="lms-topbar__title">{activeLabel}</h1>
          <div className="lms-topbar__spacer" />

        </header>

        <main className="lms-content">
          {mustChangePassword && (
            <Alert variant="warning">
              You must set your own password before using the application.
            </Alert>
          )}
          <Outlet />
        </main>
      </div>
    </div>
  )
}
