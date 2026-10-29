import { useEffect, useState } from 'react'
import { Alert, Button, Form, Spinner } from 'react-bootstrap'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import Icon from '../components/Icon.jsx'
import { errorMessage, retryAfterSeconds } from '../api/client'
import { useAuth } from '../auth/AuthContext.jsx'

export default function LoginPage() {
  const { user, login, sessionExpired } = useAuth()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [countdown, setCountdown] = useState(0)

  // A 429 carries Retry-After; count it down and keep the button disabled.
  useEffect(() => {
    if (countdown <= 0) return undefined
    const timer = setTimeout(() => setCountdown((value) => value - 1), 1000)
    return () => clearTimeout(timer)
  }, [countdown])

  if (user) {
    return <Navigate to="/" replace />
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (countdown > 0) return
    setError('')
    setSubmitting(true)
    try {
      const me = await login(email, password)
      // An admin-chosen password must be replaced before anything else (D-190).
      navigate(me?.must_change_password ? '/account' : '/', { replace: true })
    } catch (err) {
      setError(errorMessage(err, 'Could not log in. Please try again.'))
      const seconds = retryAfterSeconds(err)
      if (seconds) setCountdown(seconds)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="lms-login">
      <div className="lms-login__card">
        <div className="text-center mb-4">
          <span className="lms-brand-mark">
            <Icon name="sun" size={20} />
          </span>
          <div className="lms-brand-name mt-2">SOLshare</div>
          <div className="lms-brand-sub">Leave Management</div>
        </div>

        <h1 className="h5 mb-1">Sign in</h1>
        <p className="text-muted small mb-4">
          Use the e-mail and password your administrator set up for you.
        </p>

        {sessionExpired && (
          <Alert variant="warning">
            Your session has expired, please sign in again.
          </Alert>
        )}
        {error && <Alert variant="danger">{error}</Alert>}

        <Form onSubmit={handleSubmit}>
          <Form.Group className="mb-3" controlId="loginEmail">
            <Form.Label className="small fw-semibold">E-mail</Form.Label>
            <Form.Control
              type="email"
              size="lg"
              placeholder="you@company.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="username"
              autoFocus
              required
            />
          </Form.Group>

          <Form.Group className="mb-3" controlId="loginPassword">
            <div className="d-flex justify-content-between align-items-center mb-1">
              <Form.Label className="small fw-semibold mb-0">Password</Form.Label>
              <Link to="/forgot-password" className="small text-decoration-none text-muted">
                Forgot password?
              </Link>
            </div>
            <Form.Control
              type="password"
              size="lg"
              placeholder="Your password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              maxLength={128}
              required
            />
          </Form.Group>

          <Button
            type="submit"
            size="lg"
            className="w-100 mt-3"
            disabled={submitting || countdown > 0}
          >
            {submitting ? (
              <Spinner size="sm" animation="border" />
            ) : countdown > 0 ? (
              `Try again in ${countdown}s`
            ) : (
              'Sign in'
            )}
          </Button>
        </Form>

        <p className="text-center text-muted small mt-4 mb-0">
          Need an account or help? Contact your administrator.
        </p>
      </div>
    </div>
  )
}
