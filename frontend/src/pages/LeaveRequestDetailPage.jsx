import { useCallback, useEffect, useState } from 'react'
import { Alert, Badge, Button, Card, Col, Form, Modal, Row, Spinner, Table } from 'react-bootstrap'
import { useNavigate, useParams } from 'react-router-dom'

import api, { errorMessage } from '../api/client'
import { useAuth } from '../auth/AuthContext.jsx'
import DecisionModal from '../components/DecisionModal'
import RequestStatusBadge from '../components/RequestStatusBadge'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

function days(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : '-'
}

export default function LeaveRequestDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const isAdmin = user?.roles?.includes('ADMIN')

  const [request, setRequest] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [downloading, setDownloading] = useState(false)
  const [decision, setDecision] = useState(null)

  const [cancelOpen, setCancelOpen] = useState(false)
  const [cancelComment, setCancelComment] = useState('')
  const [cancelling, setCancelling] = useState(false)
  const [cancelError, setCancelError] = useState('')

  const [historyOpen, setHistoryOpen] = useState(false)
  const [history, setHistory] = useState(null)
  const [historyLoading, setHistoryLoading] = useState(false)

  const toggleHistory = async () => {
    const next = !historyOpen
    setHistoryOpen(next)
    if (!next || history !== null) return
    setHistoryLoading(true)
    try {
      const { data } = await api.get('/admin/audit-log', {
        params: { entity_type: 'leave_request', entity_id: id, limit: 100 },
      })
      setHistory(data)
    } catch (err) {
      setError(errorMessage(err, 'Could not load the request history.'))
    } finally {
      setHistoryLoading(false)
    }
  }

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/leave-requests/${id}`)
      setRequest(data)
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load this leave request.'))
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  // Live view: reload after any change, when the tab returns, or on the poll.
  useAutoRefresh(() => {
      load()
    })

  const decided = ({ conflict }) => {
    setDecision(null)
    setNotice(
      conflict
        ? 'That request changed while you were deciding, so it was reloaded.'
        : 'Decision saved.',
    )
    load()
    window.dispatchEvent(new Event('approvals-changed'))
  }

  const submitCancel = async (event) => {
    event.preventDefault()
    setCancelling(true)
    setCancelError('')
    try {
      await api.post(`/leave-requests/${id}/cancel`, {
        comment: cancelComment.trim() || null,
      })
      setCancelOpen(false)
      setNotice('Request cancelled.')
      load()
      window.dispatchEvent(new Event('approvals-changed'))
    } catch (err) {
      setCancelError(errorMessage(err, 'Could not cancel the request.'))
    } finally {
      setCancelling(false)
    }
  }

  const downloadAttachment = async () => {
    setDownloading(true)
    setError('')
    try {
      // A plain <a href> cannot send the Bearer token, so fetch it through
      // axios (which adds the header) as a blob, then open a temporary URL.
      const response = await api.get(`/leave-requests/${id}/attachment`, {
        responseType: 'blob',
      })
      const url = window.URL.createObjectURL(response.data)
      const link = document.createElement('a')
      link.href = url
      link.target = '_blank'
      link.rel = 'noopener'
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      setError(errorMessage(err, 'Could not download the attachment.'))
    } finally {
      setDownloading(false)
    }
  }

  if (loading) {
    return (
      <div className="text-center py-5">
        <Spinner animation="border" role="status" />
      </div>
    )
  }

  if (!request) {
    return (
      <>
        <Alert variant="danger">{error || 'Leave request not found.'}</Alert>
        <Button variant="secondary" onClick={() => navigate(-1)}>
          Back
        </Button>
      </>
    )
  }

  const rejecting = request.approvals.find((row) => row.status === 'REJECTED')

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h1 className="h3 mb-0">Leave request #{request.id}</h1>
        <div className="d-flex align-items-center gap-2">
          <RequestStatusBadge status={request.status} />
          {request.can_cancel && (
            <Button
              size="sm"
              variant="outline-danger"
              onClick={() => {
                setCancelComment('')
                setCancelError('')
                setCancelOpen(true)
              }}
            >
              {request.status === 'APPROVED'
                ? 'Cancel approved request'
                : 'Cancel request'}
            </Button>
          )}
        </div>
      </div>

      {error && (
        <Alert variant="danger" dismissible onClose={() => setError('')}>
          {error}
        </Alert>
      )}
      {notice && (
        <Alert variant="success" dismissible onClose={() => setNotice('')}>
          {notice}
        </Alert>
      )}

      {request.my_pending_approval && (
        <Card className="mb-3 border-success">
          <Card.Body className="d-flex justify-content-between align-items-center flex-wrap gap-2">
            <div>
              <Card.Title className="h5 mb-1">Your decision is needed</Card.Title>
              <span className="text-muted">
                This request stays pending until every approver has approved.
              </span>
            </div>
            <div>
              <Button
                variant="success"
                className="me-2"
                onClick={() => setDecision({ action: 'approve', requestId: request.id })}
              >
                Approve
              </Button>
              <Button
                variant="danger"
                onClick={() => setDecision({ action: 'reject', requestId: request.id })}
              >
                Reject
              </Button>
            </div>
          </Card.Body>
        </Card>
      )}

      {request.status === 'REJECTED' && rejecting && (
        <Alert variant="danger">
          <strong>Rejected by {rejecting.approver_name}</strong>
          {rejecting.comment ? ` — “${rejecting.comment}”` : ''}
          {rejecting.acted_at && (
            <div className="small">
              {new Date(rejecting.acted_at).toLocaleString()}
            </div>
          )}
        </Alert>
      )}

      {request.touches_closed_year && (
        <Alert variant="warning" className="py-2">
          This request touches a <strong>closed</strong> leave year (
          {(request.closed_year_names ?? []).join(', ')}). Its balance can no longer
          change automatically — repair it with a manual balance adjustment on the
          Assignments page if needed.
        </Alert>
      )}

      {request.status === 'CANCELLED' && (
        <Alert variant="secondary">
          <strong>
            Cancelled by {request.cancelled_by_name ?? 'an administrator'}
          </strong>
          {request.cancelled_at && (
            <span> on {new Date(request.cancelled_at).toLocaleString()}</span>
          )}
          {request.cancel_reason && <div>Reason: “{request.cancel_reason}”</div>}
        </Alert>
      )}

      <Row className="g-3">
        <Col lg={7}>
          <Card>
            <Card.Body>
              <Row className="g-3">
                <Col sm={6}>
                  <div className="text-muted small">Employee</div>
                  {request.employee_name} ({request.employee_code})
                </Col>
                <Col sm={6}>
                  <div className="text-muted small">Leave type</div>
                  {request.leave_type_code} — {request.leave_type_name}
                </Col>
                <Col sm={6}>
                  <div className="text-muted small">Dates</div>
                  {request.start_date} → {request.end_date}
                </Col>
                <Col sm={6}>
                  <div className="text-muted small">Day type</div>
                  {request.day_type}
                </Col>
                <Col sm={6}>
                  <div className="text-muted small">Chargeable days</div>
                  <strong>{days(request.chargeable_days)}</strong>
                </Col>
                <Col sm={6}>
                  <div className="text-muted small">Submitted</div>
                  {new Date(request.submitted_at).toLocaleString()}
                </Col>
                <Col xs={12}>
                  <div className="text-muted small">Reason</div>
                  {request.reason}
                </Col>
                {request.has_attachment && (
                  <Col xs={12}>
                    <Button
                      size="sm"
                      variant="outline-primary"
                      onClick={downloadAttachment}
                      disabled={downloading}
                    >
                      {downloading ? 'Opening...' : 'Open attachment'}
                    </Button>
                  </Col>
                )}
              </Row>
            </Card.Body>
          </Card>

          {request.allocations.length > 0 && (
            <Card className="mt-3">
              <Card.Body>
                <Card.Title className="h5">Days per leave year</Card.Title>
                <Table size="sm" bordered className="mb-0">
                  <thead>
                    <tr>
                      <th>Leave year</th>
                      <th className="text-end">Days</th>
                    </tr>
                  </thead>
                  <tbody>
                    {request.allocations.map((row) => (
                      <tr key={row.leave_year_id}>
                        <td>{row.leave_year_name}</td>
                        <td className="text-end">{days(row.days)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Card.Body>
            </Card>
          )}
        </Col>

        <Col lg={5}>
          <Card>
            <Card.Body>
              <Card.Title className="h5">Approvals</Card.Title>
              {request.approvals.length === 0 ? (
                <p className="text-muted mb-0">No approvers recorded.</p>
              ) : (
                <ul className="list-unstyled mb-0">
                  {request.approvals.map((approval) => (
                    <li key={approval.approver_id} className="mb-2">
                      <div className="d-flex justify-content-between align-items-center">
                        <span>
                          {approval.approver_name} ({approval.approver_code})
                        </span>
                        <RequestStatusBadge status={approval.status} />
                      </div>
                      {approval.comment && (
                        <div className="text-muted small">{approval.comment}</div>
                      )}
                      {approval.acted_at && (
                        <div className="text-muted small">
                          {new Date(approval.acted_at).toLocaleString()}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              <Badge bg="light" text="dark" className="mt-2">
                Approvers are recorded when the request is submitted.
              </Badge>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <DecisionModal
        show={decision !== null}
        action={decision?.action}
        requestId={decision?.requestId}
        onHide={() => setDecision(null)}
        onDecided={decided}
      />

      <Modal show={cancelOpen} onHide={() => setCancelOpen(false)} centered>
        <Form onSubmit={submitCancel}>
          <Modal.Header closeButton>
            <Modal.Title>
              {request.status === 'APPROVED'
                ? 'Cancel this approved request?'
                : 'Cancel request'}
            </Modal.Title>
          </Modal.Header>
          <Modal.Body>
            {cancelError && <Alert variant="danger">{cancelError}</Alert>}
            {request.status === 'APPROVED' ? (
              <Alert variant="warning">
                This request is already <strong>approved</strong>. Cancelling it puts{' '}
                <strong>{days(request.chargeable_days)} used day(s)</strong> back into
                the employee&apos;s available balance, and the leave is removed from
                their record. Only an administrator can do this — the employee cannot
                cancel an approved request, and the approvers&apos; decisions stay in
                the history.
              </Alert>
            ) : (
              <Alert variant="info">
                Cancelling releases{' '}
                <strong>{days(request.chargeable_days)} reserved day(s)</strong> back
                to the available balance.
              </Alert>
            )}
            <Form.Group controlId="cancelComment">
              <Form.Label>
                {isAdmin
                  ? 'Reason (required, 3+ characters)'
                  : 'Comment (optional)'}
              </Form.Label>
              <Form.Control
                as="textarea"
                rows={3}
                value={cancelComment}
                onChange={(event) => setCancelComment(event.target.value)}
                maxLength={1000}
                required={isAdmin}
              />
            </Form.Group>
          </Modal.Body>
          <Modal.Footer>
            <Button
              variant="secondary"
              onClick={() => setCancelOpen(false)}
              disabled={cancelling}
            >
              Keep request
            </Button>
            <Button
              type="submit"
              variant="danger"
              disabled={cancelling || (isAdmin && cancelComment.trim().length < 3)}
            >
              {cancelling ? 'Cancelling...' : 'Cancel request'}
            </Button>
          </Modal.Footer>
        </Form>
      </Modal>

      {isAdmin && (
        <Card className="mt-3">
          <Card.Body>
            <div className="d-flex justify-content-between align-items-center">
              <div>
                <Card.Title className="h6 mb-0">History</Card.Title>
                <div className="text-muted small">
                  Audit entries are append-only: nobody can edit or delete them.
                </div>
              </div>
              <Button size="sm" variant="outline-secondary" onClick={toggleHistory}>
                {historyOpen ? 'Hide' : 'Show'}
              </Button>
            </div>
            {historyOpen && (
              <div className="mt-3">
                {historyLoading ? (
                  <Spinner size="sm" animation="border" />
                ) : !history || history.rows.length === 0 ? (
                  <div className="text-muted small">No audit entries yet.</div>
                ) : (
                  <Table size="sm" bordered responsive className="mb-0">
                    <thead>
                      <tr>
                        <th>Time (local)</th>
                        <th>Actor</th>
                        <th>Action</th>
                        <th>Changed keys</th>
                      </tr>
                    </thead>
                    <tbody>
                      {history.rows.map((row) => (
                        <tr key={row.id}>
                          <td>{new Date(row.created_at).toLocaleString()}</td>
                          <td>{row.actor_name ?? '(system)'}</td>
                          <td>
                            <Badge bg="secondary">{row.action}</Badge>
                          </td>
                          <td className="small">{row.changed.join(', ')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                )}
              </div>
            )}
          </Card.Body>
        </Card>
      )}
    </>
  )
}
