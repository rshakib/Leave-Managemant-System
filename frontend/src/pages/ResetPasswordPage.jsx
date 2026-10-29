import { useEffect, useState } from 'react'
import { Alert, Button, Form, Spinner } from 'react-bootstrap'
import { Link, Navigate, useSearchParams } from 'react-router-dom'

import api, { errorMessage } from '../api/client'
import { useAuth } from '../auth/AuthContext.jsx'
import Icon from '../components/Icon.jsx'

export default function ResetPasswordPage() {
  const { user } = useAuth()
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''

  const [verifying, setVerifying] = useState(true)
  const [tokenValid, setTokenValid] = useState(false)
  const [tokenError, setTokenError] = useState('')
  const [accountEmail, setAccountEmail] = useState('')

  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  if (user) {
    return <Navigate to="/" replace />
  }

  useEffect(() => {
    if (!token) {
      setVerifying(false)
      setTokenValid(false)
      setTokenError('No reset token was provided in the link.')
      return
    }

    let active = true
    const checkToken = async () => {
      try {
        const { data } = await api.get('/auth/verify-reset-token', {
          params: { token },
        })
        if (active) {
          setTokenValid(true)
          setAccountEmail(data.email || '')
        }
      } catch (err) {
        if (active) {
          setTokenValid(false)
          setTokenError(
            errorMessage(
              err,
              'This password reset link is invalid or has expired. Please request a new one.'
            )
          )
        }
      } finally {
        if (active) setVerifying(false)
      }
    }
    checkToken()

    return () => {
      active = false
    }
  }, [token])

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')

    if (newPassword !== confirmPassword) {
      setError('The new passwords do not match.')
      return
    }

    if (newPassword.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }

    setSubmitting(true)
    try {
      await api.post('/auth/reset-password', {
        token,
        new_password: newPassword,
      })
      setSuccess(true)
    } catch (err) {
      setError(errorMessage(err, 'Could not reset password. Please try again.'))
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

        <h1 className="h5 mb-1">Set new password</h1>
        <p className="text-muted small mb-4">
          Choose a secure password for your Leave Management account.
        </p>

        {verifying ? (
          <div className="text-center py-4">
            <Spinner animation="border" variant="primary" />
            <div className="small text-muted mt-2">Verifying reset link…</div>
          </div>
        ) : !tokenValid ? (
          <div>
            <Alert variant="danger">
              {tokenError || 'Invalid or expired password reset link.'}
            </Alert>
            <div className="text-center mt-3">
              <Link to="/forgot-password" className="btn btn-primary w-100 mb-2">
                Request a new link
              </Link>
              <Link to="/login" className="btn btn-outline-secondary w-100">
                Back to sign in
              </Link>
            </div>
          </div>
        ) : success ? (
          <div>
            <Alert variant="success" className="mb-4">
              <strong>Password updated!</strong>
              <div className="small mt-1">
                Your password has been reset successfully. You can now sign in with your new password.
              </div>
            </Alert>
            <Link to="/login" className="btn btn-primary w-100">
              Sign in now
            </Link>
          </div>
        ) : (
          <Form onSubmit={handleSubmit}>
            {error && <Alert variant="danger">{error}</Alert>}

            {accountEmail && (
              <div className="small text-muted mb-3">
                Account: <strong>{accountEmail}</strong>
              </div>
            )}

            <Form.Group className="mb-3" controlId="resetNewPassword">
              <Form.Label className="small fw-semibold">New password</Form.Label>
              <Form.Control
                type="password"
                size="lg"
                placeholder="At least 8 characters"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                autoComplete="new-password"
                minLength={8}
                maxLength={128}
                required
                autoFocus
              />
            </Form.Group>

            <Form.Group className="mb-3" controlId="resetConfirmPassword">
              <Form.Label className="small fw-semibold">Confirm new password</Form.Label>
              <Form.Control
                type="password"
                size="lg"
                placeholder="Repeat new password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                autoComplete="new-password"
                minLength={8}
                maxLength={128}
                required
              />
            </Form.Group>

            <Button
              type="submit"
              size="lg"
              className="w-100 mt-2"
              disabled={submitting || !newPassword || !confirmPassword}
            >
              {submitting ? (
                <Spinner size="sm" animation="border" />
              ) : (
                'Save new password'
              )}
            </Button>

            <div className="text-center mt-4">
              <Link to="/login" className="small text-decoration-none text-muted">
                Cancel and back to sign in
              </Link>
            </div>
          </Form>
        )}
      </div>
    </div>
  )
}
