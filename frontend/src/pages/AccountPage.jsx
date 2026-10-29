import { useCallback, useEffect, useState } from 'react'
import { Alert, Badge, Button, Card, Col, Form, Modal, Row } from 'react-bootstrap'
import { useNavigate } from 'react-router-dom'

import api, { errorMessage } from '../api/client'
import { useAuth } from '../auth/AuthContext.jsx'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

export default function AccountPage() {
  const { user, logoutAll, mustChangePassword, refreshUser } = useAuth()
  const navigate = useNavigate()

  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [problems, setProblems] = useState([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [saving, setSaving] = useState(false)
  const [confirmingSignOut, setConfirmingSignOut] = useState(false)
  const [sessions, setSessions] = useState([])
  const [sessionsError, setSessionsError] = useState('')
  const [endingId, setEndingId] = useState(null)

  // Where is this account signed in? One row per signed-in browser. The server
  // derives it from the token, so it can only ever be your own sessions.
  const loadSessions = useCallback(async () => {
    try {
      const { data } = await api.get('/auth/sessions')
      setSessions(data)
      setSessionsError('')
    } catch (err) {
      setSessionsError(errorMessage(err, 'Could not load your signed-in devices.'))
    }
  }, [])

  useEffect(() => {
    // While a password change is required the API refuses this call, and the card
    // is hidden anyway, so do not even ask.
    if (!mustChangePassword) loadSessions()
  }, [mustChangePassword, loadSessions])

  // Live, like every other screen: signing a device out, signing in somewhere
  // else, or a change made anywhere in the app re-reads this list, and so does
  // coming back to the tab — no manual reload (D-154/D-200).
  const refreshSessions = useCallback(() => {
    if (!mustChangePassword) loadSessions()
  }, [mustChangePassword, loadSessions])

  useAutoRefresh(refreshSessions)

  const endSession = async (id) => {
    setEndingId(id)
    setSessionsError('')
    try {
      await api.delete(`/auth/sessions/${id}`)
      setSessions((rows) => rows.filter((row) => row.id !== id))
    } catch (err) {
      setSessionsError(errorMessage(err, 'Could not end that session.'))
    } finally {
      setEndingId(null)
    }
  }

  // Start empty, and empty again whenever the screen switches between the forced
  // first change and a normal one. On the forced screen there is no "current
  // password" field at all (D-198); this makes sure a value the browser filled in
  // can never linger in one of them either (D-201).
  useEffect(() => {
    setCurrent('')
    setNext('')
    setConfirm('')
  }, [mustChangePassword])

  const when = (value) => (value ? new Date(value).toLocaleString() : '—')

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    setNotice('')
    setProblems([])

    if (next !== confirm) {
      setError('The two new passwords do not match.')
      return
    }

    setSaving(true)
    try {
      // The server rotates THIS browser's refresh cookie in the response, and the
      // access token already in memory stays valid until it expires — so the
      // session simply continues; no extra refresh call is needed here.
      // Forced first change: the current password was just typed at sign-in, so
      // only the new one is sent (D-198).
      await api.post(
        '/auth/change-password',
        mustChangePassword
          ? { new_password: next }
          : { current_password: current, new_password: next },
      )
      setCurrent('')
      setNext('')
      setConfirm('')
      setNotice('Password changed. Your other devices were signed out.')
      // The change is committed in the database, so re-read the user BEFORE
      // navigating: while the "must change" flag is still cached the shell would
      // bounce us straight back here. Once it is clear, Home is reachable (D-199).
      await refreshUser()
      navigate('/', { replace: true })
    } catch (err) {
      const detail = err?.response?.data?.detail
      if (Array.isArray(detail)) {
        setProblems(detail)
      } else {
        setError(errorMessage(err, 'Could not change the password.'))
      }
    } finally {
      setSaving(false)
    }
  }

  const signOutEverywhere = async () => {
    setConfirmingSignOut(false)
    await logoutAll()
  }

  return (
    <>
      <h1 className="h3 mb-3">My account</h1>

      <Row className="g-3">
        <Col lg={5}>
          <Card className="h-100">
            <Card.Header>Profile</Card.Header>
            <Card.Body>
              <div className="lms-balance__value mb-1">
                {user?.full_name}
                <span>you</span>
              </div>
              <p className="text-muted mb-2">{user?.email}</p>
              <div className="d-flex flex-wrap gap-1">
                {(user?.roles ?? []).map((role) => (
                  <Badge key={role} bg="secondary" className="fw-normal">
                    {role}
                  </Badge>
                ))}
              </div>
            </Card.Body>
          </Card>
        </Col>

        <Col lg={7}>
          <Card>
            <Card.Header>Change password</Card.Header>
            <Card.Body>
              {notice && <Alert variant="success">{notice}</Alert>}
              {error && <Alert variant="danger">{error}</Alert>}
              {problems.length > 0 && (
                <Alert variant="danger">
                  <strong>Please fix this:</strong>
                  <ul className="mb-0 mt-2">
                    {problems.map((problem, index) => (
                      <li key={index}>{typeof problem === 'string' ? problem : problem.msg}</li>
                    ))}
                  </ul>
                </Alert>
              )}

              {/* autoComplete="off": nothing here may be pre-filled by the
                  browser's password manager (D-201). */}
              <Form onSubmit={submit} autoComplete="off">
                {mustChangePassword ? (
                  <Alert variant="info">
                    You signed in with the password an administrator chose for you.
                    Pick your own now — you do not need to type the old one again.
                  </Alert>
                ) : (
                  <Form.Group className="mb-3" controlId="currentPassword">
                    <Form.Label>Current password</Form.Label>
                    <Form.Control
                      type="password"
                      value={current}
                      onChange={(event) => setCurrent(event.target.value)}
                      autoComplete="current-password"
                      required
                    />
                  </Form.Group>
                )}
                <Form.Group className="mb-3" controlId="newPassword">
                  <Form.Label>New password</Form.Label>
                  <Form.Control
                    type="password"
                    value={next}
                    onChange={(event) => setNext(event.target.value)}
                    autoComplete="new-password"
                    maxLength={128}
                    required
                  />
                  <Form.Text className="text-muted">
                    At least 10 characters, not a common password, not your email name.
                  </Form.Text>
                </Form.Group>
                <Form.Group className="mb-3" controlId="confirmPassword">
                  <Form.Label>Repeat the new password</Form.Label>
                  <Form.Control
                    type="password"
                    value={confirm}
                    onChange={(event) => setConfirm(event.target.value)}
                    autoComplete="new-password"
                    maxLength={128}
                    required
                  />
                </Form.Group>
                <Button type="submit" disabled={saving}>
                  {saving ? 'Saving…' : 'Change password'}
                </Button>
              </Form>
            </Card.Body>
          </Card>
        </Col>

        {!mustChangePassword && (
          <Col xs={12}>
            <Card>
              <Card.Header>Where you are signed in</Card.Header>
              <Card.Body>
                {sessionsError && <Alert variant="danger">{sessionsError}</Alert>}

                {sessions.length === 0 && !sessionsError && (
                  <p className="text-muted mb-3">Nothing else is signed in right now.</p>
                )}

                {sessions.map((session) => (
                  <div
                    key={session.id}
                    className="d-flex flex-wrap justify-content-between align-items-center gap-2 border-bottom py-2"
                  >
                    <div>
                      <div className="fw-semibold">
                        {session.device}{' '}
                        {session.current && (
                          <Badge bg="success" className="fw-normal">
                            This device
                          </Badge>
                        )}
                      </div>
                      <div className="text-muted small">
                        Signed in {when(session.created_at)} · last used{' '}
                        {when(session.last_used_at)} · ends {when(session.expires_at)}
                      </div>
                    </div>
                    {session.current ? (
                      <Button variant="outline-secondary" size="sm" disabled>
                        Use Logout above
                      </Button>
                    ) : (
                      <Button
                        variant="outline-danger"
                        size="sm"
                        disabled={endingId === session.id}
                        onClick={() => endSession(session.id)}
                      >
                        {endingId === session.id ? 'Ending…' : 'Sign out this device'}
                      </Button>
                    )}
                  </div>
                ))}

                <div className="d-flex flex-wrap justify-content-between align-items-center gap-3 mt-3">
                  <div className="text-muted small">
                    Signing out everywhere ends every browser session of this account,
                    including this one.
                  </div>
                  <Button variant="outline-danger" onClick={() => setConfirmingSignOut(true)}>
                    Sign out of all devices
                  </Button>
                </div>
              </Card.Body>
            </Card>
          </Col>
        )}
      </Row>

      <Modal show={confirmingSignOut} onHide={() => setConfirmingSignOut(false)} centered>
        <Modal.Header closeButton>
          <Modal.Title>Sign out of all devices?</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          Every browser where you are signed in will be signed out, including this one.
          You will need to sign in again.
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setConfirmingSignOut(false)}>
            Cancel
          </Button>
          <Button variant="danger" onClick={signOutEverywhere}>
            Sign out everywhere
          </Button>
        </Modal.Footer>
      </Modal>
    </>
  )
}
