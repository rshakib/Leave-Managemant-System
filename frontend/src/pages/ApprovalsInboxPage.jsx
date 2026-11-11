import { useCallback, useEffect, useState } from 'react'
import { Alert, Badge, Button, Spinner, Tab, Table, Tabs } from 'react-bootstrap'
import { useNavigate } from 'react-router-dom'

import api, { errorMessage } from '../api/client'
import CurtailmentDecisionModal from '../components/CurtailmentDecisionModal'
import DecisionModal from '../components/DecisionModal'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

const PAGE_SIZE = 20

function days(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : '-'
}

export default function ApprovalsInboxPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState('PENDING')
  const [offset, setOffset] = useState(0)
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [decision, setDecision] = useState(null)
  const [curtailmentDecision, setCurtailmentDecision] = useState(null)
  const [counts, setCounts] = useState({ pending: 0, early_returns: 0, total: 0 })

  const loadCounts = useCallback(async () => {
    try {
      const { data } = await api.get('/approvals/inbox/count')
      setCounts(data)
    } catch {
      // count failure doesn't block the list
    }
  }, [])

  const load = useCallback(async () => {
    try {
      loadCounts()
      if (tab === 'EARLY_RETURNS') {
        const { data } = await api.get('/curtailments/inbox', { params: { status: 'PENDING' } })
        setItems(data)
      } else {
        const { data } = await api.get('/approvals/inbox', { params: { status: tab, limit: PAGE_SIZE, offset } })
        setItems(data)
      }
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load your inbox.'))
    } finally {
      setLoading(false)
    }
  }, [tab, offset, loadCounts])

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
        ? 'That request changed while you were deciding, so the list was refreshed.'
        : 'Decision saved.',
    )
    load()
    // Tells the navbar to refresh its badge.
    window.dispatchEvent(new Event('approvals-changed'))
  }

  return (
    <>
      <h1 className="h3 mb-3">Approvals</h1>

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

      <Tabs
        activeKey={tab}
        onSelect={(key) => {
          setTab(key ?? 'PENDING')
          setOffset(0)
        }}
        className="mb-3"
      >
        <Tab
          eventKey="PENDING"
          title={
            <span>
              Pending Requests
              {counts.pending > 0 && (
                <Badge bg="danger" pill className="ms-2">
                  {counts.pending}
                </Badge>
              )}
            </span>
          }
        />
        <Tab
          eventKey="EARLY_RETURNS"
          title={
            <span>
              Early Returns
              {counts.early_returns > 0 && (
                <Badge bg="danger" pill className="ms-2">
                  {counts.early_returns}
                </Badge>
              )}
            </span>
          }
        />
        <Tab eventKey="DECIDED" title="Decided Requests" />
      </Tabs>

      {loading ? (
        <div className="text-center py-5">
          <Spinner animation="border" role="status" />
        </div>
      ) : items.length === 0 ? (
        <div className="empty-state">
          {tab === 'EARLY_RETURNS'
            ? 'No pending early return requests.'
            : tab === 'PENDING'
              ? 'Nothing is waiting for you.'
              : 'You have not decided on any requests yet.'}
        </div>
      ) : (
        <>
          <Table striped bordered hover responsive>
          <thead>
            {tab === 'EARLY_RETURNS' ? (
              <tr>
                <th>Employee</th>
                <th>Leave Type</th>
                <th>Original End</th>
                <th>New End Date</th>
                <th className="text-end">Refunded Days</th>
                <th>Reason</th>
                <th>Submitted</th>
                <th className="text-end">Actions</th>
              </tr>
            ) : (
              <tr>
                <th>Employee</th>
                <th>Leave type</th>
                <th>Dates</th>
                <th className="text-end">Days</th>
                <th>Submitted</th>
                <th>Progress</th>
                <th className="text-end">Actions</th>
              </tr>
            )}
          </thead>
          <tbody>
            {items.map((item) =>
              tab === 'EARLY_RETURNS' ? (
                <tr key={item.id}>
                  <td>
                    {item.employee_name} ({item.employee_code})
                  </td>
                  <td>{item.leave_type_name}</td>
                  <td>{item.original_end_date}</td>
                  <td>
                    <strong>{item.curtailed_end_date}</strong>
                  </td>
                  <td className="text-end">
                    <Badge bg="success">+{days(item.days_to_refund)} days</Badge>
                  </td>
                  <td>{item.reason}</td>
                  <td>{new Date(item.submitted_at).toLocaleString()}</td>
                  <td className="text-end">
                    <Button
                      size="sm"
                      variant="outline-secondary"
                      className="me-2"
                      onClick={() => navigate(`/leave-requests/${item.leave_request_id}`)}
                    >
                      View
                    </Button>
                    <Button
                      size="sm"
                      variant="success"
                      className="me-2"
                      onClick={() =>
                        setCurtailmentDecision({ action: 'approve', curtailment: item })
                      }
                    >
                      Approve
                    </Button>
                    <Button
                      size="sm"
                      variant="danger"
                      onClick={() =>
                        setCurtailmentDecision({ action: 'reject', curtailment: item })
                      }
                    >
                      Reject
                    </Button>
                  </td>
                </tr>
              ) : (
                <tr key={item.approval_id}>
                  <td>
                    {item.employee_name} ({item.employee_code})
                  </td>
                  <td>
                    {item.leave_type_code} — {item.leave_type_name}
                  </td>
                  <td>
                    {item.start_date} → {item.end_date}
                    {item.day_type !== 'FULL_DAY' && (
                      <div className="small text-muted">{item.day_type}</div>
                    )}
                  </td>
                  <td className="text-end">{days(item.chargeable_days)}</td>
                  <td>{new Date(item.submitted_at).toLocaleString()}</td>
                  <td>
                    <Badge bg="secondary">{item.summary}</Badge>
                  </td>
                  <td className="text-end">
                    <Button
                      size="sm"
                      variant="outline-secondary"
                      className="me-2"
                      onClick={() => navigate(`/leave-requests/${item.request_id}`)}
                    >
                      View
                    </Button>
                    {tab === 'PENDING' && (
                      <>
                        <Button
                          size="sm"
                          variant="success"
                          className="me-2"
                          onClick={() =>
                            setDecision({ action: 'approve', requestId: item.request_id })
                          }
                        >
                          Approve
                        </Button>
                        <Button
                          size="sm"
                          variant="danger"
                          onClick={() =>
                            setDecision({ action: 'reject', requestId: item.request_id })
                          }
                        >
                          Reject
                        </Button>
                      </>
                    )}
                  </td>
                </tr>
              )
            )}
          </tbody>
        </Table>

        {(offset > 0 || items.length === PAGE_SIZE) && tab !== 'EARLY_RETURNS' && (
          <div className="d-flex justify-content-between align-items-center mt-3">
            <Button
              variant="outline-secondary"
              size="sm"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              ← Previous
            </Button>
            <span className="small text-muted">
              Showing {items.length} row(s) from #{offset + 1}
            </span>
            <Button
              variant="outline-secondary"
              size="sm"
              disabled={items.length < PAGE_SIZE}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Next →
            </Button>
          </div>
        )}
      </>
      )}

      <DecisionModal
        show={decision !== null}
        action={decision?.action}
        requestId={decision?.requestId}
        onHide={() => setDecision(null)}
        onDecided={decided}
      />

      <CurtailmentDecisionModal
        show={curtailmentDecision !== null}
        action={curtailmentDecision?.action}
        curtailment={curtailmentDecision?.curtailment}
        onHide={() => setCurtailmentDecision(null)}
        onDecided={decided}
      />
    </>
  )
}
