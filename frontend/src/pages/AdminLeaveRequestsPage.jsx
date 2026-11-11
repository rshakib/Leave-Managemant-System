import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Col, Form, Row, Spinner, Table } from 'react-bootstrap'
import { useNavigate } from 'react-router-dom'

import api, { errorMessage } from '../api/client'
import DateFilter, { getLastMonthRange } from '../components/DateFilter'
import Icon from '../components/Icon.jsx'
import RequestStatusBadge from '../components/RequestStatusBadge'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

const STATUSES = ['PENDING', 'APPROVED', 'REJECTED', 'CANCELLED']
const PAGE_SIZE = 20

function days(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : '-'
}

export default function AdminLeaveRequestsPage() {
  const navigate = useNavigate()
  const defaultDates = useMemo(() => getLastMonthRange(), [])
  const [requests, setRequests] = useState([])
  const [employees, setEmployees] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [status, setStatus] = useState('')
  const [employeeId, setEmployeeId] = useState('')
  const [dateFrom, setDateFrom] = useState(defaultDates.from)
  const [dateTo, setDateTo] = useState(defaultDates.to)
  const [offset, setOffset] = useState(0)
  const [exporting, setExporting] = useState(false)

  const loadEmployees = useCallback(async () => {
    try {
      const { data } = await api.get('/employees')
      setEmployees(data)
    } catch (err) {
      setError(errorMessage(err, 'Could not load employees.'))
    }
  }, [])

  const loadRequests = useCallback(async () => {
    try {
      const params = { limit: PAGE_SIZE, offset }
      if (status) params.status = status
      if (employeeId) params.employee_id = employeeId
      if (dateFrom) params.date_from = dateFrom
      if (dateTo) params.date_to = dateTo
      const { data } = await api.get('/leave-requests', { params })
      setRequests(data)
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load requests.'))
    } finally {
      setLoading(false)
    }
  }, [status, employeeId, dateFrom, dateTo, offset])

  useEffect(() => {
    loadEmployees()
  }, [loadEmployees])

  useEffect(() => {
    loadRequests()
  }, [loadRequests])

  // Live view: reload after any change, when the tab returns, or on the poll.
  useAutoRefresh(() => {
    loadRequests()
  })

  const downloadCsv = useCallback(async () => {
    setExporting(true)
    setError('')
    try {
      const params = {
        include_reason: true,
      }
      if (status) params.status = status
      if (employeeId) params.employee_id = employeeId
      if (dateFrom) params.date_from = dateFrom
      if (dateTo) params.date_to = dateTo

      const response = await api.get('/reports/history/export', {
        params,
        responseType: 'blob',
      })
      const disposition = response.headers['content-disposition'] ?? ''
      const match = /filename="?([^";]+)"?/.exec(disposition)
      const filename = match ? match[1] : 'all-leave-requests.csv'
      const url = window.URL.createObjectURL(response.data)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      let message = 'Could not export requests to CSV.'
      const blob = err.response?.data
      if (blob instanceof Blob) {
        try {
          const parsed = JSON.parse(await blob.text())
          if (parsed?.detail) message = parsed.detail
        } catch {
          message = 'Could not export requests to CSV.'
        }
      } else {
        message = errorMessage(err, 'Could not export requests to CSV.')
      }
      setError(message)
    } finally {
      setExporting(false)
    }
  }, [status, employeeId, dateFrom, dateTo])

  return (
    <>
      <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3">
        <div>
          <h1 className="h3 mb-0">All leave requests</h1>
          <div className="text-muted small mt-1">
            Browse, filter, and inspect leave requests across all staff.
          </div>
        </div>
        <Button
          variant="outline-primary"
          size="sm"
          className="d-flex align-items-center gap-2 shadow-xs"
          disabled={exporting}
          onClick={downloadCsv}
          title="Download filtered leave requests as a CSV spreadsheet"
        >
          {exporting ? (
            <Spinner animation="border" size="sm" />
          ) : (
            <Icon name="download" size={16} />
          )}
          <span>{exporting ? 'Exporting…' : 'Download CSV'}</span>
        </Button>
      </div>

      {error && (
        <Alert variant="danger" dismissible onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      <Row className="g-2 mb-3 align-items-end">
        <Col md={3}>
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
        <Col md={3}>
          <Form.Label className="small text-muted mb-1">Employee</Form.Label>
          <Form.Select
            size="sm"
            aria-label="Filter by employee"
            value={employeeId}
            onChange={(event) => {
              setEmployeeId(event.target.value)
              setOffset(0)
            }}
          >
            <option value="">All employees</option>
            {employees.map((employee) => (
              <option key={employee.id} value={employee.id}>
                {employee.full_name} ({employee.employee_code})
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
        {(!dateFrom || !dateTo || dateFrom !== defaultDates.from || dateTo !== defaultDates.to) && (
          <Col md="auto" sm={6} xs={12}>
            <Button
              variant="link"
              size="sm"
              className="p-0 text-decoration-none small text-muted pb-1"
              onClick={() => {
                setDateFrom(defaultDates.from)
                setDateTo(defaultDates.to)
                setOffset(0)
              }}
              title="Reset date filter to default last 1 month"
            >
              Reset to last 1 month
            </Button>
          </Col>
        )}
      </Row>

      {loading ? (
        <div className="text-center py-5">
          <Spinner animation="border" role="status" />
        </div>
      ) : requests.length === 0 ? (
        <div className="empty-state">
          No requests match these filters.
        </div>
      ) : (
        <Table striped bordered hover responsive>
          <thead>
            <tr>
              <th>Employee</th>
              <th>Leave type</th>
              <th>Dates</th>
              <th className="text-end">Days</th>
              <th>Status</th>
              <th>Submitted</th>
            </tr>
          </thead>
          <tbody>
            {requests.map((request) => (
              <tr
                key={request.id}
                role="button"
                onClick={() => navigate(`/leave-requests/${request.id}`)}
              >
                <td>
                  {request.employee_name} ({request.employee_code})
                </td>
                <td>
                  {request.leave_type_code} — {request.leave_type_name}
                </td>
                <td>
                  {request.start_date} → {request.end_date}
                </td>
                <td className="text-end">{days(request.chargeable_days)}</td>
                <td>
                  <RequestStatusBadge status={request.status} />
                </td>
                <td>{new Date(request.submitted_at).toLocaleString()}</td>
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
          Showing {requests.length} row(s) from #{offset + 1}
        </span>
        <Button
          variant="outline-secondary"
          size="sm"
          disabled={requests.length < PAGE_SIZE}
          onClick={() => setOffset(offset + PAGE_SIZE)}
        >
          Next
        </Button>
      </div>
    </>
  )
}
