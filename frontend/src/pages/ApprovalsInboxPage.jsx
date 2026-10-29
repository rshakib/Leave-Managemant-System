import { useCallback, useEffect, useState } from 'react'
import { Alert, Badge, Button, Spinner, Tab, Table, Tabs } from 'react-bootstrap'
import { useNavigate } from 'react-router-dom'

import api, { errorMessage } from '../api/client'
import DecisionModal from '../components/DecisionModal'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

function days(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : '-'
}

export default function ApprovalsInboxPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState('PENDING')
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [decision, setDecision] = useState(null)

  const load = useCallback(async () => {
    try {
      const { data } = await api.get('/approvals/inbox', { params: { status: tab } })
      setItems(data)
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load your inbox.'))
    } finally {
      setLoading(false)
    }
  }, [tab])

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

      <Tabs activeKey={tab} onSelect={(key) => setTab(key ?? 'PENDING')} className="mb-3">
        <Tab eventKey="PENDING" title="Pending" />
        <Tab eventKey="DECIDED" title="Decided" />
      </Tabs>

      {loading ? (
        <div className="text-center py-5">
          <Spinner animation="border" role="status" />
        </div>
      ) : items.length === 0 ? (
        <div className="empty-state">
          {tab === 'PENDING'
            ? 'Nothing is waiting for you.'
            : 'You have not decided on any requests yet.'}
        </div>
      ) : (
        <Table striped bordered hover responsive>
          <thead>
            <tr>
              <th>Employee</th>
              <th>Leave type</th>
              <th>Dates</th>
              <th className="text-end">Days</th>
              <th>Submitted</th>
              <th>Progress</th>
              <th className="text-end">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
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
            ))}
          </tbody>
        </Table>
      )}

      <DecisionModal
        show={decision !== null}
        action={decision?.action}
        requestId={decision?.requestId}
        onHide={() => setDecision(null)}
        onDecided={decided}
      />
    </>
  )
}
