import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Col,
  Form,
  Modal,
  Nav,
  Row,
  Spinner,
  Table,
} from 'react-bootstrap'

import api, { errorMessage } from '../api/client'
import DateFilter from '../components/DateFilter'
import Icon from '../components/Icon'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

const STATUSES = ['PENDING', 'SENDING', 'SENT', 'FAILED']
const PAGE_SIZE = 20

const STATUS_COLOURS = {
  PENDING: 'warning',
  SENDING: 'info',
  SENT: 'success',
  FAILED: 'danger',
}

export default function AdminEmailsPage() {
  const [emails, setEmails] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const [status, setStatus] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [offset, setOffset] = useState(0)

  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [previewTab, setPreviewTab] = useState('html')

  // One manual pass of the worker, so a live demo never has to wait for the
  // background process (or open a second terminal).
  const [queueRunning, setQueueRunning] = useState(false)
  const [withReminders, setWithReminders] = useState(false)

  const loadEmails = useCallback(async () => {
    try {
      const params = { limit: PAGE_SIZE, offset }
      if (status) params.status = status
      if (dateFrom) params.date_from = dateFrom
      if (dateTo) params.date_to = dateTo
      const { data } = await api.get('/admin/emails', { params })
      setEmails(data)
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load the email log.'))
    } finally {
      setLoading(false)
    }
  }, [status, dateFrom, dateTo, offset])

  useEffect(() => {
    loadEmails()
  }, [loadEmails])

  // Live real-time update (event-driven, silent background update with no spinner)
  useAutoRefresh(loadEmails)

  const processQueue = async () => {
    setQueueRunning(true)
    setError('')
    setNotice('')
    try {
      const { data } = await api.post(
        `/admin/emails/process-queue?reminders=${withReminders}`,
      )
      const parts = [`${data.sent} sent`, `${data.failed} failed`]
      if (data.reminders_queued) {
        parts.push(`${data.reminders_queued} reminder(s) queued and sent`)
      }
      if (data.still_pending) parts.push(`${data.still_pending} still pending`)
      setNotice(`Queue processed: ${parts.join(', ')}.`)
      await loadEmails()
    } catch (err) {
      setError(errorMessage(err, 'Could not process the queue.'))
    } finally {
      setQueueRunning(false)
    }
  }

  const openDetail = async (email) => {
    setPreviewTab('html')
    setDetailLoading(true)
    try {
      const { data } = await api.get(`/admin/emails/${email.id}`)
      setDetail(data)
    } catch (err) {
      setError(errorMessage(err, 'Could not load this email.'))
    } finally {
      setDetailLoading(false)
    }
  }

  const retry = async (email) => {
    setError('')
    setNotice('')
    try {
      await api.post(`/admin/emails/${email.id}/retry`)
      setDetail(null)
      setNotice('Queued for another attempt.')
      await loadEmails()
    } catch (err) {
      setError(errorMessage(err, 'Could not retry this email.'))
    }
  }

  return (
    <>
      <h1 className="h3 mb-1">Email log</h1>

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

      <Row className="mb-3 align-items-end g-2">
        <Col md="auto">
          <Button size="sm" onClick={processQueue} disabled={queueRunning}>
            {queueRunning ? 'Processing…' : 'Process Queue Now'}
          </Button>
        </Col>
        <Col md="auto">
          <Button
            size="sm"
            variant="outline-secondary"
            onClick={loadEmails}
            title="Refresh email log"
          >
            <Icon name="refresh" size={14} className="me-1" />
            Refresh
          </Button>
        </Col>
        <Col md="auto">
          <Form.Check
            id="queueReminders"
            className="small"
            label="also send pending-approval reminders"
            checked={withReminders}
            onChange={(event) => setWithReminders(event.target.checked)}
          />
        </Col>
        <Col md={2}>
          <Form.Label className="small text-muted mb-1">Status</Form.Label>
          <Form.Select
            size="sm"
            aria-label="Filter by status"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value)
              setOffset(0)
            }}
          >
            <option value="">Any status</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </Form.Select>
        </Col>
        <DateFilter
          dateFrom={dateFrom}
          dateTo={dateTo}
          onChange={({ dateFrom: df, dateTo: dt }) => {
            setDateFrom(df)
            setDateTo(dt)
            setOffset(0)
          }}
        />
      </Row>

      {loading ? (
        <div className="text-center py-5">
          <Spinner animation="border" role="status" />
        </div>
      ) : emails.length === 0 ? (
        <div className="empty-state">No emails match these filters.</div>
      ) : (
        <Table striped bordered hover responsive>
          <thead>
            <tr>
              <th>Created</th>
              <th>Event</th>
              <th>To</th>
              <th>Status</th>
              <th
                className="text-end"
                title="Only a FAILED send counts here; every try is listed in the row's detail"
              >
                Failed tries
              </th>
              <th>Last error</th>
              <th className="text-end">Actions</th>
            </tr>
          </thead>
          <tbody>
            {emails.map((email) => (
              <tr key={email.id}>
                <td>{new Date(email.created_at).toLocaleString()}</td>
                <td>{email.event_type}</td>
                <td className="small">{email.to_emails.join(', ')}</td>
                <td>
                  <Badge bg={STATUS_COLOURS[email.status] ?? 'secondary'}>
                    {email.status}
                  </Badge>
                </td>
                <td className="text-end">
                  {email.attempts}/{email.max_attempts}
                </td>
                <td className="small text-danger">{email.last_error ?? ''}</td>
                <td className="text-end">
                  <Button
                    size="sm"
                    variant="outline-secondary"
                    className="me-2"
                    onClick={() => openDetail(email)}
                  >
                    Details
                  </Button>
                  {email.status === 'FAILED' && (
                    <Button size="sm" variant="outline-primary" onClick={() => retry(email)}>
                      Retry
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      <div className="d-flex justify-content-between align-items-center">
        <Button
          variant="outline-secondary"
          size="sm"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
        >
          Previous
        </Button>
        <span className="text-muted small">
          Showing {emails.length} row(s) from #{offset + 1}
        </span>
        <Button
          variant="outline-secondary"
          size="sm"
          disabled={emails.length < PAGE_SIZE}
          onClick={() => setOffset(offset + PAGE_SIZE)}
        >
          Next
        </Button>
      </div>

      <Modal
        show={detail !== null || detailLoading}
        onHide={() => setDetail(null)}
        size="lg"
        centered
      >
        <Modal.Header closeButton>
          <Modal.Title>Email #{detail?.id}</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {detailLoading && <Spinner size="sm" animation="border" />}
          {detail && (
            <>
              <p className="mb-1">
                <strong>{detail.event_type}</strong> · {detail.status} ·{' '}
                {detail.attempt_history.length} send attempt(s), {detail.attempts} failed of{' '}
                {detail.max_attempts} allowed
              </p>
              <p className="small text-muted">
                To: {detail.to_emails.join(', ')}
                {detail.cc_emails.length > 0 &&
                  ` · Cc: ${detail.cc_emails.join(', ')}`}
              </p>
              {detail.last_error && (
                <Alert variant="danger" className="small">
                  {detail.last_error}
                </Alert>
              )}
              {detail.subject && (
                <>
                  <hr className="my-3" />
                  <div className="text-muted small">Subject</div>
                  <div className="fw-semibold mb-2">{detail.subject}</div>
                  <Nav
                    variant="tabs"
                    activeKey={previewTab}
                    onSelect={(key) => setPreviewTab(key || 'html')}
                  >
                    <Nav.Item>
                      <Nav.Link eventKey="html">HTML preview</Nav.Link>
                    </Nav.Item>
                    <Nav.Item>
                      <Nav.Link eventKey="text">Plain text</Nav.Link>
                    </Nav.Item>
                  </Nav>
                  <div className="border border-top-0 p-2">
                    {previewTab === 'html' ? (
                      <iframe
                        title="Email preview"
                        sandbox=""
                        srcDoc={detail.body_html ?? ''}
                        style={{ width: '100%', height: '340px', border: 0 }}
                      />
                    ) : (
                      <pre className="small mb-0" style={{ whiteSpace: 'pre-wrap' }}>
                        {detail.body_text}
                      </pre>
                    )}
                  </div>
                  <p className="text-muted small mt-2">
                    Rendered from this row&apos;s stored facts. Opening it sends nothing.
                  </p>
                </>
              )}
              {!detail.subject && (
                <Alert variant="secondary" className="small">
                  This row has no renderable content (unknown event type).
                </Alert>
              )}

              <h6>Attempt history</h6>
              {detail.attempt_history.length === 0 ? (
                <p className="text-muted small mb-0">Nothing has tried to send this row yet.</p>
              ) : (
                <Table size="sm" bordered className="mb-2">
                  <thead>
                    <tr>
                      <th>When</th>
                      <th>Result</th>
                      <th>Backend</th>
                      <th>Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.attempt_history.map((attempt) => (
                      <tr key={attempt.id}>
                        <td>{new Date(attempt.attempted_at).toLocaleString()}</td>
                        <td>
                          <Badge bg={attempt.success ? 'success' : 'danger'}>
                            {attempt.success ? 'sent' : 'failed'}
                          </Badge>
                        </td>
                        <td>{attempt.backend}</td>
                        <td className="small">{attempt.error ?? ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
              <details>
                <summary className="small text-muted">Stored facts (payload)</summary>
                <pre className="small mt-2">{JSON.stringify(detail.payload, null, 2)}</pre>
              </details>
            </>
          )}
        </Modal.Body>
        <Modal.Footer>
          {detail?.status === 'FAILED' && (
            <Button variant="primary" onClick={() => retry(detail)}>
              Retry
            </Button>
          )}
          <Button variant="secondary" onClick={() => setDetail(null)}>
            Close
          </Button>
        </Modal.Footer>
      </Modal>
    </>
  )
}
