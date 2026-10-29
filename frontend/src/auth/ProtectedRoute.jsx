import { Alert, Container, Spinner } from 'react-bootstrap'
import { Navigate, Outlet } from 'react-router-dom'

import { useAuth } from './AuthContext.jsx'

// Blocks a route until the user is known to be logged in. With a `roles` prop
// it also blocks users who do not hold at least one of those roles.
export default function ProtectedRoute({ roles }) {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <Container className="text-center py-5">
        <Spinner animation="border" role="status" />
        <div className="text-muted mt-3">Restoring session…</div>
      </Container>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  if (roles?.length && !roles.some((role) => user.roles?.includes(role))) {
    return (
      <Alert variant="danger">
        <Alert.Heading>Not allowed</Alert.Heading>
        <p className="mb-0">You do not have permission to view this page.</p>
      </Alert>
    )
  }

  return <Outlet />
}
