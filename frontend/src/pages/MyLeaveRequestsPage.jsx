import { useCallback, useEffect, useState } from 'react'
import { Alert, Col, Form, Row, Spinner, Table } from 'react-bootstrap'
import { useNavigate } from 'react-router-dom'

import api, { errorMessage } from '../api/client'
import DateFilter from '../components/DateFilter'
import RequestStatusBadge from '../components/RequestStatusBadge'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

const STATUSES = ['PENDING', 'APPROVED', 'REJECTED', 'CANCELLED']

function days(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : '-'
}

export default function MyLeaveRequestsPage() {
  const navigate = useNavigate()
  const [requests, setRequests] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const loadRequests = useCallback(async () => {
    try {
      const params = {}
      if (status) params.status = status
      if (dateFrom) params.date_from = dateFrom
      if (dateTo) params.date_to = dateTo
      const { data } = await api.get('/leave-requests/me', { params })
      setRequests(data)
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load your requests.'))
    } finally {
      setLoading(false)
    }
  }, [status, dateFrom, dateTo])

  useEffect(() => {
    loadRequests()
  }, [loadRequests])

  // Live view: reload after any change, when the tab returns, or on the poll.
  useAutoRefresh(() => {
      loadRequests()
    })

  return (
    <>
      <h1 className="h3 mb-3">My leave requests</h1>

      {error && (
        <Alert variant="danger" dismissible onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      <Row className="mb-3 g-2 align-items-end">
        <Col md={3}>
          <Form.Label className="small text-muted mb-1">Status</Form.Label>
          <Form.Select
            size="sm"
            aria-label="Filter by status"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
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
          }}
        />
      </Row>

      {loading ? (
        <div className="text-center py-5">
          <Spinner animation="border" role="status" />
        </div>
      ) : requests.length === 0 ? (
        <div className="empty-state">
          You have no leave requests{status ? ` with status ${status}` : ''} yet.
        </div>
      ) : (
        <Table striped bordered hover responsive>
          <thead>
            <tr>
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
    </>
  )
}
