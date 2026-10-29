import { useEffect, useState } from 'react'
import { Alert, Badge, Button, Card, Col, Row, Spinner } from 'react-bootstrap'
import { Link } from 'react-router-dom'

import api, { errorMessage } from '../api/client'
import { useAuth } from '../auth/AuthContext.jsx'
import Icon from '../components/Icon.jsx'
import MonthCalendar from '../components/MonthCalendar.jsx'
import RequestStatusBadge from '../components/RequestStatusBadge.jsx'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

function days(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : '0.00'
}

function greetingFor(date) {
  const hour = date.getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
}

function Stat({ icon, tint, label, value, hint, to }) {
  const body = (
    <div className="lms-stat">
      <span className="lms-stat__icon" style={{ background: tint }}>
        <Icon name={icon} size={20} />
      </span>
      <div>
        <div className="lms-stat__label">{label}</div>
        <div className="lms-stat__value">{value}</div>
        {hint && <div className="lms-stat__hint">{hint}</div>}
      </div>
    </div>
  )
  return to ? (
    <Link to={to} className="lms-stat-link">
      {body}
    </Link>
  ) : (
    body
  )
}

export default function HomePage() {
  const { user } = useAuth()
  const roles = user?.roles ?? []
  const isAdmin = roles.includes('ADMIN')
  const isApprover = roles.includes('APPROVER')
  const isEmployee = roles.includes('EMPLOYEE')

  // Date text is built once in an effect (never during render).
  const [clock, setClock] = useState({ greeting: '', today: '' })
  const [reloadKey, setReloadKey] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [balances, setBalances] = useState([])
  const [myRequests, setMyRequests] = useState([])
  const [approvers, setApprovers] = useState([])
  const [activeYear, setActiveYear] = useState(null)
  const [pendingApprovals, setPendingApprovals] = useState(0)
  const [openRequests, setOpenRequests] = useState([])

  useEffect(() => {
    const now = new Date()
    setClock({
      greeting: greetingFor(now),
      today: now.toLocaleDateString(undefined, {
        weekday: 'long',
        day: 'numeric',
        month: 'long',
        year: 'numeric',
      }),
    })
  }, [])

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      // allSettled: one failing call must not blank the whole dashboard.
      const [balanceRes, requestRes, approverRes, yearRes, countRes] =
        await Promise.allSettled([
          api.get('/leave-balances/me'),
          api.get('/leave-requests/me', { params: { limit: 5 } }),
          api.get('/approvers/me'),
          api.get('/leave-years'),
          isApprover ? api.get('/approvals/inbox/count') : Promise.resolve(null),
        ])
      if (cancelled) return

      if (balanceRes.status === 'fulfilled') setBalances(balanceRes.value.data)
      if (requestRes.status === 'fulfilled') setMyRequests(requestRes.value.data)
      if (approverRes.status === 'fulfilled') setApprovers(approverRes.value.data)
      if (yearRes.status === 'fulfilled') {
        setActiveYear(yearRes.value.data.find((year) => year.is_active) ?? null)
      }
      if (countRes.status === 'fulfilled' && countRes.value) {
        setPendingApprovals(countRes.value.data.pending)
      }

      if (isAdmin) {
        try {
          const { data } = await api.get('/leave-requests', {
            params: { status: 'PENDING', limit: 5 },
          })
          if (!cancelled) setOpenRequests(data)
        } catch {
          // the dashboard is still useful without this list
        }
      }

      const failed = [balanceRes, requestRes].find((r) => r.status === 'rejected')
      if (failed) {
        setError(errorMessage(failed.reason, 'Could not load your dashboard.'))
      }
      setLoading(false)
    }

    load()
    return () => {
      cancelled = true
    }
  }, [isAdmin, isApprover, reloadKey])

  const totalAvailable = balances.reduce(
    (sum, balance) => sum + Number(balance.available ?? 0),
    0,
  )
  const totalUsed = balances.reduce(
    (sum, balance) => sum + Number(balance.used ?? 0),
    0,
  )
  const pendingMine = myRequests.filter((r) => r.status === 'PENDING').length

  // Live view: reload after any change, when the tab returns, or on the poll.
  // (Declared before the early return, so hooks always run in the same order.)
  useAutoRefresh(() => setReloadKey((key) => key + 1), { intervalMs: 60000 })

  if (loading) {
    return (
      <div className="text-center py-5">
        <Spinner animation="border" role="status" />
      </div>
    )
  }


  return (
    <>
      {error && (
        <Alert variant="danger" dismissible onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      {/* --- greeting ---------------------------------------------------- */}
      <Card className="mb-3 lms-hero">
        <Card.Body className="d-flex flex-wrap justify-content-between align-items-center gap-3">
          <div>
            <div className="text-muted small">
              {clock.today}
              {activeYear ? ` · leave year ${activeYear.name}` : ' · no active leave year'}
            </div>
            <h2 className="h4 mb-1">
              {clock.greeting}, {user?.full_name?.split(' ')[0] ?? 'there'}
            </h2>
            <div className="d-flex flex-wrap gap-1">
              {roles.map((role) => (
                <Badge key={role} bg="secondary" className="fw-normal">
                  {role}
                </Badge>
              ))}
            </div>
          </div>
          <div className="d-flex flex-wrap gap-2">
            {isEmployee && (
              <Button as={Link} to="/leave-requests/new">
                <Icon name="plus" size={16} className="me-1" />
                Request leave
              </Button>
            )}
            {isApprover && (
              <Button as={Link} to="/approvals" variant="outline-primary">
                <Icon name="check" size={16} className="me-1" />
                Approvals
                {pendingApprovals > 0 && (
                  <Badge bg="danger" className="ms-2">
                    {pendingApprovals}
                  </Badge>
                )}
              </Button>
            )}
            {isAdmin && (
              <Button as={Link} to="/reports" variant="outline-secondary">
                <Icon name="chart" size={16} className="me-1" />
                Reports
              </Button>
            )}
          </div>
        </Card.Body>
      </Card>

      {/* --- numbers ------------------------------------------------------ */}
      <Row className="g-3 mb-3">
        <Col sm={6} xl={3}>
          <Stat
            icon="balance"
            tint="#f79020"
            label="Available days"
            value={days(totalAvailable)}
            hint={`${balances.length} leave type(s)`}
            to="/my-balances"
          />
        </Col>
        <Col sm={6} xl={3}>
          <Stat
            icon="calendar"
            tint="#131313"
            label="Days used"
            value={days(totalUsed)}
            hint={activeYear ? `in ${activeYear.name}` : 'no active year'}
          />
        </Col>
        <Col sm={6} xl={3}>
          <Stat
            icon="list"
            tint="#b45309"
            label="My pending requests"
            value={pendingMine}
            hint="waiting for an approver"
            to="/my-requests"
          />
        </Col>
        {isApprover ? (
          <Col sm={6} xl={3}>
            <Stat
              icon="check"
              tint="#cc3300"
              label="Waiting for me"
              value={pendingApprovals}
              hint="requests to decide"
              to="/approvals"
            />
          </Col>
        ) : (
          <Col sm={6} xl={3}>
            <Stat
              icon="users"
              tint="#0f766e"
              label="My approvers"
              value={approvers.length}
              hint="people who decide my leave"
            />
          </Col>
        )}
      </Row>

      <Row className="g-3 mb-3">
        {/* --- the running month, at a glance ---------------------------- */}
        <Col xl={7}>
          <MonthCalendar />
        </Col>

        {/* --- my balances ------------------------------------------------ */}
        <Col xl={5}>
          <Card className="h-100">
            <Card.Header className="d-flex justify-content-between align-items-center">
              <span>My balances</span>
              <Button as={Link} to="/my-balances" size="sm" variant="outline-secondary">
                Open
              </Button>
            </Card.Header>
            <Card.Body>
              {balances.length === 0 ? (
                <div className="empty-state">
                  No leave assigned for the active year yet.
                </div>
              ) : (
                <table className="table table-sm align-middle mb-0">
                  <thead>
                    <tr>
                      <th>Leave type</th>
                      <th className="text-end">Available</th>
                      <th className="text-end">Used</th>
                      <th className="text-end">Pending</th>
                    </tr>
                  </thead>
                  <tbody>
                    {balances.map((balance) => (
                      <tr key={balance.id}>
                        <td>
                          <span className="fw-semibold">{balance.leave_type_code}</span>
                          <span className="text-muted"> · {balance.leave_type_name}</span>
                        </td>
                        <td className="text-end fw-semibold">
                          {days(balance.available)}
                        </td>
                        <td className="text-end text-muted">{days(balance.used)}</td>
                        <td className="text-end text-muted">{days(balance.pending)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card.Body>
          </Card>
        </Col>

        {/* --- my recent requests ---------------------------------------- */}
        <Col xl={6}>
          <Card className="h-100">
            <Card.Header className="d-flex justify-content-between align-items-center">
              <span>My recent requests</span>
              <Button as={Link} to="/my-requests" size="sm" variant="outline-secondary">
                All
              </Button>
            </Card.Header>
            <Card.Body>
              {myRequests.length === 0 ? (
                <div className="empty-state">You have not requested leave yet.</div>
              ) : (
                <ul className="lms-feed">
                  {myRequests.map((request) => (
                    <li key={request.id}>
                      <Link to={`/leave-requests/${request.id}`} className="lms-feed__link">
                        <div className="lms-feed__main">
                          <span className="fw-semibold">{request.leave_type_code}</span>
                          <span className="text-muted small">
                            {request.start_date} → {request.end_date} ·{' '}
                            {days(request.chargeable_days)} d
                          </span>
                        </div>
                        <RequestStatusBadge status={request.status} />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card.Body>
          </Card>
        </Col>

        {/* --- who approves my leave ------------------------------------- */}
        <Col xl={6}>
          <Card className="h-100">
            <Card.Header>Who approves my leave</Card.Header>
            <Card.Body>
              {approvers.length === 0 ? (
                <div className="text-muted small">
                  No approver assigned yet — an admin has to add one, otherwise you
                  cannot submit a request.
                </div>
              ) : (
                <div className="d-flex flex-wrap gap-2">
                  {approvers.map((approver) => (
                    <Badge
                      key={approver.id}
                      bg={approver.is_supervisor ? 'info' : 'primary'}
                      className="fw-normal py-2 px-3"
                    >
                      {approver.full_name}
                      {approver.is_supervisor ? ' · supervisor' : ''}
                    </Badge>
                  ))}
                </div>
              )}
            </Card.Body>
          </Card>
        </Col>

        {/* --- admin: the approval queue --------------------------------- */}
        {isAdmin && (
          <>
            <Col xl={12}>
              <Card className="h-100">
                <Card.Header className="d-flex justify-content-between align-items-center">
                  <span>Requests waiting for approval</span>
                  <Button
                    as={Link}
                    to="/admin/leave-requests"
                    size="sm"
                    variant="outline-secondary"
                  >
                    All requests
                  </Button>
                </Card.Header>
                <Card.Body>
                  {openRequests.length === 0 ? (
                    <div className="empty-state">Nothing is pending right now.</div>
                  ) : (
                    <table className="table table-sm align-middle mb-0">
                      <thead>
                        <tr>
                          <th>Employee</th>
                          <th>Type</th>
                          <th>Dates</th>
                          <th className="text-end">Days</th>
                        </tr>
                      </thead>
                      <tbody>
                        {openRequests.map((request) => (
                          <tr key={request.id}>
                            <td>{request.employee_name ?? request.employee_code}</td>
                            <td>{request.leave_type_code}</td>
                            <td className="small">
                              {request.start_date} → {request.end_date}
                            </td>
                            <td className="text-end">{days(request.chargeable_days)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </Card.Body>
              </Card>
            </Col>
          </>
        )}
      </Row>
    </>
  )
}
