import { describeAction, describeChanges, technicalLine } from '../utils/auditText'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Col,
  Form,
  Modal,
  Row,
  Spinner,
  Table,
} from 'react-bootstrap'
import { useSearchParams } from 'react-router-dom'

import api, { errorMessage } from '../api/client'
import DateFilter from '../components/DateFilter'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

const PAGE_SIZE = 50

const ENTITY_TYPES = [
  'division',
  'department',
  'employee',
  'employee_approver',
  'leave_year',
  'leave_type',
  'leave_assignment',
  'leave_balance',
  'weekend_setting',
  'holiday',
  'leave_request',
  'report',
  'email',
]

const FILTER_KEYS = ['entity_type', 'entity_id', 'actor_id', 'action', 'date_from', 'date_to']

function emptyForm() {
  return {
    entity_type: '',
    entity_id: '',
    actor_id: '',
    action: '',
    date_from: '',
    date_to: '',
  }
}

function formFromParams(searchParams) {
  const form = emptyForm()
  FILTER_KEYS.forEach((key) => {
    const value = searchParams.get(key)
    if (value !== null) form[key] = value
  })
  return form
}

function paramsFromForm(form, offset) {
  const params = { offset: String(offset) }
  FILTER_KEYS.forEach((key) => {
    if (form[key] !== '') params[key] = form[key]
  })
  return params
}

function keyOfLine(line) {
  const match = /^\s*"([^"]+)":/.exec(line)
  return match ? match[1] : null
}

function JsonBlock({ label, value, changed }) {
  const text =
    value === null || value === undefined ? '(none)' : JSON.stringify(value, null, 2)
  const lines = text.split('\n')
  return (
    <div>
      <div className="small text-muted mb-1">{label}</div>
      <pre
        className="small border rounded p-2 mb-0"
        style={{ maxHeight: 320, overflow: 'auto' }}
      >
        {lines.map((line, index) => {
          const key = keyOfLine(line)
          const highlight = key !== null && changed.includes(key)
          return (
            <span
              key={index}
              style={highlight ? { backgroundColor: 'var(--bs-warning-bg-subtle)' } : undefined}
            >
              {line}
              {'\n'}
            </span>
          )
        })}
      </pre>
    </div>
  )
}

export default function AdminAuditLogPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [reloadKey, setReloadKey] = useState(0)
  const offset = Number(searchParams.get('offset') ?? 0)

  const [form, setForm] = useState(() => formFromParams(searchParams))
  const [page, setPage] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [detail, setDetail] = useState(null)
  const [employees, setEmployees] = useState([])

  useEffect(() => {
    const loadOptions = async () => {
      try {
        const { data } = await api.get('/employees')
        setEmployees(data)
      } catch {
        setEmployees([])
      }
    }
    loadOptions()
  }, [])

  const apiParams = useMemo(
    () => paramsFromForm(formFromParams(searchParams), offset),
    [searchParams, offset],
  )

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      if (!page) {
        setLoading(true)
      }
      try {
        const { data } = await api.get('/admin/audit-log', {
          params: { ...apiParams, limit: PAGE_SIZE },
        })
        if (cancelled) return
        setPage(data)
        setError('')
      } catch (err) {
        if (cancelled) return
        setPage(null)
        setError(errorMessage(err, 'Could not load the audit log.'))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [apiParams, reloadKey])

  // Live real-time update (event-driven, silent background update with no spinner)
  useAutoRefresh(() => setReloadKey((k) => k + 1))

  const apply = () => {
    setSearchParams(paramsFromForm(form, 0))
  }

  const reset = () => {
    setForm(emptyForm())
    setSearchParams({})
  }

  const goToOffset = (next) => {
    setSearchParams({ ...apiParams, offset: String(next) })
  }

  const openDetail = useCallback(async (row) => {
    setDetail(row)
    try {
      const { data } = await api.get(`/admin/audit-log/${row.id}`)
      setDetail(data)
    } catch (err) {
      setError(errorMessage(err, 'Could not load that audit entry.'))
    }
  }, [])

  return (
    <>
      <h1 className="h3 mb-1">Audit log</h1>
      <p className="text-muted small">
        Audit entries are append-only: nobody can edit or delete them.
      </p>

      {error && (
        <Alert variant="danger" dismissible onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      <Row className="g-2 mb-3">
        <Col md={2}>
          <Form.Label className="small">Entity type</Form.Label>
          <Form.Select
            size="sm"
            value={form.entity_type}
            onChange={(event) => setForm({ ...form, entity_type: event.target.value })}
          >
            <option value="">Any</option>
            {ENTITY_TYPES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </Form.Select>
        </Col>
        <Col md={2}>
          <Form.Label className="small">Entity id</Form.Label>
          <Form.Control
            size="sm"
            type="number"
            value={form.entity_id}
            onChange={(event) => setForm({ ...form, entity_id: event.target.value })}
          />
        </Col>
        <Col md={3}>
          <Form.Label className="small">Actor</Form.Label>
          <Form.Select
            size="sm"
            value={form.actor_id}
            onChange={(event) => setForm({ ...form, actor_id: event.target.value })}
          >
            <option value="">Anyone</option>
            {employees.map((employee) => (
              <option key={employee.id} value={employee.id}>
                {employee.employee_code} — {employee.full_name}
              </option>
            ))}
          </Form.Select>
        </Col>
        <Col md={2}>
          <Form.Label className="small">Action contains</Form.Label>
          <Form.Control
            size="sm"
            value={form.action}
            onChange={(event) => setForm({ ...form, action: event.target.value })}
            placeholder="UPDATE"
          />
        </Col>
        <DateFilter
          dateFrom={form.date_from}
          dateTo={form.date_to}
          onChange={({ dateFrom, dateTo }) =>
            setForm((prev) => ({ ...prev, date_from: dateFrom, date_to: dateTo }))
          }
        />
      </Row>

      <div className="d-flex gap-2 mb-3">
        <Button size="sm" variant="primary" onClick={apply}>
          Apply
        </Button>
        <Button size="sm" variant="outline-secondary" onClick={reset}>
          Reset
        </Button>
      </div>

      {loading ? (
        <div className="text-center py-5">
          <Spinner animation="border" role="status" />
        </div>
      ) : !page || page.rows.length === 0 ? (
        <div className="empty-state">No audit entries match these filters.</div>
      ) : (
        <>
          <p className="text-muted small">{page.total} entr(y/ies) in total</p>
          <Table striped bordered hover responsive size="sm">
            <thead>
              <tr>
                <th>Time (local)</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Entity</th>
                <th>Reason</th>
                <th className="text-end"></th>
              </tr>
            </thead>
            <tbody>
              {page.rows.map((row) => (
                <tr key={row.id}>
                  <td>{new Date(row.created_at).toLocaleString()}</td>
                  <td>{row.actor_name ?? '(system)'}</td>
                  <td>
                    <Badge bg="secondary">{row.action}</Badge>
                  </td>
                  <td>
                    {row.entity_type}
                    {row.entity_id !== null ? ` #${row.entity_id}` : ''}
                  </td>
                  <td className="small">{row.reason ?? ''}</td>
                  <td className="text-end">
                    <Button
                      size="sm"
                      variant="outline-secondary"
                      onClick={() => openDetail(row)}
                    >
                      Details
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>

          <div className="d-flex justify-content-between align-items-center">
            <Button
              size="sm"
              variant="outline-secondary"
              disabled={offset === 0}
              onClick={() => goToOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Previous
            </Button>
            <span className="text-muted small">
              {offset + 1}–{offset + page.rows.length} of {page.total}
            </span>
            <Button
              size="sm"
              variant="outline-secondary"
              disabled={offset + page.rows.length >= page.total}
              onClick={() => goToOffset(offset + PAGE_SIZE)}
            >
              Next
            </Button>
          </div>
        </>
      )}

      <Modal show={detail !== null} onHide={() => setDetail(null)} size="lg" centered>
        <Modal.Header closeButton>
          <Modal.Title>
            {describeAction(detail?.action)}
            <span className="text-muted small fw-normal"> ({technicalLine(detail)})</span>
          </Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {detail && (
            <>
              <p className="mb-1 small">
                <strong>{detail.actor_name ?? 'The system'}</strong> at{' '}
                {new Date(detail.created_at).toLocaleString()}
              </p>
              {detail.reason && (
                <p className="small text-muted">Reason: {detail.reason}</p>
              )}
              <p className="mb-0">
                <strong>{detail.actor_name ?? 'The system'}</strong>{' '}
                {describeAction(detail.action)}
                {detail.entity_type
                  ? ` — ${detail.entity_type}${
                      detail.entity_id !== null && detail.entity_id !== undefined
                        ? ` #${detail.entity_id}`
                        : ''
                    }`
                  : ''}
                .
              </p>
              {describeChanges(detail).map((row, idx) => (
                <tr key={row.label + idx}>
                  <td>{row.label}</td>
                  <td className="text-end">{row.before}</td>
                  <td className="text-end">{row.after}</td>
                </tr>
              ))}
              {describeChanges(detail).length > 0 && (
                <table className="table table-sm small mt-3 mb-0">
                  <thead>
                    <tr>
                      <th>Changed</th>
                      <th className="text-end">Before</th>
                      <th className="text-end">After</th>
                    </tr>
                  </thead>
                  <tbody>
                    {describeChanges(detail).map((row, idx) => (
                      <tr key={row.label + idx}>
                        <td>{row.label}</td>
                        <td className="text-end">{row.before}</td>
                        <td className="text-end">{row.after}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <details className="mt-3">
                <summary className="small text-muted">Technical details (for developers)</summary>
                <Row className="g-3 mt-1">
                  <Col md={6}>
                    <JsonBlock label="Before" value={detail.old_value} changed={detail.changed} />
                  </Col>
                  <Col md={6}>
                    <JsonBlock label="After" value={detail.new_value} changed={detail.changed} />
                  </Col>
                </Row>
              </details>
              <p className="small text-muted mt-3 mb-0">
                Audit entries are append-only: nobody can edit or delete them.
              </p>
            </>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setDetail(null)}>
            Close
          </Button>
        </Modal.Footer>
      </Modal>
    </>
  )
}
