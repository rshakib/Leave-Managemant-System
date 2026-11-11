import { Container, Spinner } from 'react-bootstrap'
import { Navigate, Outlet, useLocation } from 'react-router-dom'

import AccessState from '../components/AccessState.jsx'
import { useAuth } from './AuthContext.jsx'
import { buildLoginUrl } from './redirectUtils.js'

// Blocks a route until the user is known to be logged in. With `roles` or
// `requireSupervisor`, blocks users who lack the required access.
export default function ProtectedRoute({ roles, requireSupervisor = false }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <Container className="text-center py-5">
        <Spinner animation="border" role="status" />
        <div className="text-muted mt-3">Restoring session…</div>
      </Container>
    )
  }

  if (!user) {
    return <Navigate to={buildLoginUrl(location)} replace />
  }

  const hasRole = !roles?.length || roles.some((role) => user.roles?.includes(role))
  const hasSupervisor =
    !requireSupervisor || Boolean(user.is_supervisor || user.roles?.includes('ADMIN'))

  if (!hasRole || !hasSupervisor) {
    return <AccessState variant="restricted" />
  }

  return <Outlet />
}
