import { useState } from 'react'
import { Alert, Button, Form, Spinner } from 'react-bootstrap'
import { Link, Navigate } from 'react-router-dom'

import api, { errorMessage } from '../api/client'
import { useAuth } from '../auth/AuthContext.jsx'
import Icon from '../components/Icon.jsx'

export default function ForgotPasswordPage() {
  const { user } = useAuth()
  const [email, setEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [sent, setSent] = useState(false)

  if (user) {
    return <Navigate to="/" replace />
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await api.post('/auth/forgot-password', { email })
      setSent(true)
    } catch (err) {
      setError(errorMessage(err, 'Could not request a password reset link. Please try again.'))
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

        <h1 className="h5 mb-1">Forgot password</h1>
        <p className="text-muted small mb-4">
          Enter your account email and we'll send you a link to reset your password.
        </p>

        {error && <Alert variant="danger">{error}</Alert>}

        {sent ? (
          <div>
            <Alert variant="success" className="mb-4">
              <strong>Check your email!</strong>
              <div className="small mt-1">
                If an active account exists for <strong>{email}</strong>, a password reset link has been sent. The link expires in 30 minutes.
              </div>
            </Alert>
            <div className="text-center">
              <Link to="/login" className="btn btn-outline-secondary w-100">
                Back to sign in
              </Link>
            </div>
          </div>
        ) : (
          <Form onSubmit={handleSubmit}>
            <Form.Group className="mb-3" controlId="forgotEmail">
              <Form.Label className="small fw-semibold">E-mail address</Form.Label>
              <Form.Control
                type="email"
                size="lg"
                placeholder="you@company.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
                autoFocus
                required
              />
            </Form.Group>

            <Button
              type="submit"
              size="lg"
              className="w-100 mt-2"
              disabled={submitting || !email.trim()}
            >
              {submitting ? (
                <Spinner size="sm" animation="border" />
              ) : (
                'Send reset link'
              )}
            </Button>

            <div className="text-center mt-4">
              <Link to="/login" className="small text-decoration-none text-muted">
                ← Back to sign in
              </Link>
            </div>
          </Form>
        )}
      </div>
    </div>
  )
}
