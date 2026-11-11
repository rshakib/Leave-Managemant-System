import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  ButtonGroup,
  Card,
  Col,
  Form,
  Modal,
  Row,
  Spinner,
  Table,
} from 'react-bootstrap'
import { useNavigate } from 'react-router-dom'

import api, { errorMessage } from '../api/client'
import Icon from '../components/Icon.jsx'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

function days(value) {
  const num = Number(value)
  return Number.isFinite(num) ? num.toFixed(2) : '0.00'
}

function pct(part, whole) {
  if (!whole || whole <= 0) return 0
  return Math.max(0, Math.min(100, (part / whole) * 100))
}

function getInitials(name) {
  if (!name) return '?'
  const parts = name.trim().split(/\s+/)
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

// Order of preference for core / everyday leave types
const CORE_TYPE_CODES = ['AL', 'CL', 'SL', 'WFH']

function BalanceBar({ used, pending, available, entitlement }) {
  const total =
    Number(entitlement) ||
    Number(used) + Number(pending) + Number(available) ||
    1
  return (
    <div className="lms-bar" style={{ minWidth: '70px', height: '6px' }}>
      <span
        className="lms-bar__seg is-used"
        style={{ width: `${pct(used, total)}%` }}
        title={`Used: ${days(used)}`}
      />
      <span
        className="lms-bar__seg is-pending"
        style={{ width: `${pct(pending, total)}%` }}
        title={`Pending: ${days(pending)}`}
      />
      <span
        className="lms-bar__seg is-free"
        style={{ width: `${pct(available, total)}%` }}
        title={`Available: ${days(available)}`}
      />
    </div>
  )
}

export default function TeamBalancesPage() {
  const navigate = useNavigate()
  const [balances, setBalances] = useState([])
  const [stats, setStats] = useState(null)
  const [years, setYears] = useState([])
  const [selectedYearId, setSelectedYearId] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [leaveTypeFilter, setLeaveTypeFilter] = useState('')
  const [viewMode, setViewMode] = useState('cards') // 'cards' (default) or 'table'
  const [selectedEmployeeModal, setSelectedEmployeeModal] = useState(null)
  const [eventsModal, setEventsModal] = useState(null) // { title: '...', items: [...] }
  const [reloadKey, setReloadKey] = useState(0)

  // 1. Fetch leave years
  useEffect(() => {
    api
      .get('/leave-years')
      .then(({ data }) => {
        setYears(data)
        const active = data.find((y) => y.is_active)
        if (active) {
          setSelectedYearId(String(active.id))
        } else if (data.length > 0) {
          setSelectedYearId(String(data[0].id))
        }
      })
      .catch((err) => {
        setError(errorMessage(err, 'Failed to load leave years.'))
      })
  }, [])

  // 2. Fetch team leave balances and presence stats
  useEffect(() => {
    let cancelled = false
    if (!balances.length) {
      setLoading(true)
    }

    const params = {}
    if (selectedYearId) params.leave_year_id = selectedYearId

    Promise.all([
      api.get('/leave-balances/team', { params }),
      api.get('/leave-balances/team/stats'),
    ])
      .then(([balRes, statsRes]) => {
        if (!cancelled) {
          setBalances(balRes.data)
          setStats(statsRes.data)
          setError('')
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(errorMessage(err, 'Could not load team leave data.'))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [selectedYearId, reloadKey])

  // Live real-time updates (event-driven: fires when real data changes, silent background update with no spinner)
  useAutoRefresh(() => setReloadKey((k) => k + 1))

  // Unique leave types present in loaded balances
  const availableLeaveTypes = useMemo(() => {
    const map = new Map()
    for (const b of balances) {
      if (!map.has(b.leave_type_id)) {
        map.set(b.leave_type_id, {
          id: b.leave_type_id,
          code: b.leave_type_code,
          name: b.leave_type_name,
        })
      }
    }
    return Array.from(map.values()).sort((a, b) => a.name.localeCompare(b.name))
  }, [balances])

  // Group balances by employee
  const groupedEmployees = useMemo(() => {
    const map = new Map()
    for (const b of balances) {
      if (!map.has(b.employee_id)) {
        map.set(b.employee_id, {
          employee_id: b.employee_id,
          employee_name: b.employee_name,
          employee_code: b.employee_code,
          items: [],
          totalUsed: 0,
          totalPending: 0,
          // Specific core types mapped for quick matrix access
          typeMap: {},
        })
      }
      const entry = map.get(b.employee_id)
      entry.items.push(b)
      entry.typeMap[b.leave_type_code] = b
      entry.totalUsed += Number(b.used || 0)
      entry.totalPending += Number(b.pending || 0)
    }

    // Sort items within each employee: core types first, then alphabetical
    for (const emp of map.values()) {
      emp.items.sort((a, b) => {
        const idxA = CORE_TYPE_CODES.indexOf(a.leave_type_code)
        const idxB = CORE_TYPE_CODES.indexOf(b.leave_type_code)
        if (idxA !== -1 && idxB !== -1) return idxA - idxB
        if (idxA !== -1) return -1
        if (idxB !== -1) return 1
        return a.leave_type_name.localeCompare(b.leave_type_name)
      })
    }

    return Array.from(map.values()).sort((a, b) =>
      a.employee_name.localeCompare(b.employee_name),
    )
  }, [balances])

  // Filtered employees based on search & leave type filter
  const filteredEmployees = useMemo(() => {
    const q = search.trim().toLowerCase()
    return groupedEmployees.filter((emp) => {
      // Search filter
      if (q) {
        const matchesName = (emp.employee_name || '').toLowerCase().includes(q)
        const matchesCode = (emp.employee_code || '').toLowerCase().includes(q)
        if (!matchesName && !matchesCode) return false
      }
      // Leave type filter
      if (leaveTypeFilter) {
        const hasType = emp.items.some(
          (b) => String(b.leave_type_id) === String(leaveTypeFilter),
        )
        if (!hasType) return false
      }
      return true
    })
  }, [groupedEmployees, search, leaveTypeFilter])

  const selectedYear = years.find((y) => String(y.id) === String(selectedYearId))

  return (
    <div>
      {/* Header section */}
      <div className="d-flex flex-wrap align-items-center justify-content-between gap-3 mb-4">
        <div>
          <div className="d-flex align-items-center gap-2">
            <h1 className="h3 mb-0">Team Leave Balances</h1>
            <Badge bg="secondary" pill>
              Supervisor View
            </Badge>
          </div>
          <div className="text-muted small mt-1">
            Track daily presence, upcoming leaves, and remaining quotas for your direct team.
          </div>
        </div>

        {/* Leave Year Selector */}
        <div className="d-flex align-items-center gap-2">
          <Form.Label htmlFor="year-select" className="small text-muted mb-0 fw-semibold">
            Leave Year:
          </Form.Label>
          <Form.Select
            id="year-select"
            size="sm"
            value={selectedYearId}
            onChange={(e) => setSelectedYearId(e.target.value)}
            style={{ width: 'auto', minWidth: '160px' }}
          >
            {years.map((y) => (
              <option key={y.id} value={y.id}>
                {y.name} {y.is_active ? ' (Active)' : ''}
              </option>
            ))}
          </Form.Select>
          <Button
            variant="outline-secondary"
            size="sm"
            onClick={() => setReloadKey((k) => k + 1)}
            title="Refresh team data"
          >
            <Icon name="refresh" size={14} className="me-1" />
            Refresh
          </Button>
        </div>
      </div>

      {error && (
        <Alert variant="danger" dismissible onClose={() => setError('')} className="mb-4">
          {error}
        </Alert>
      )}

      {/* 4 Actionable, Real-World Supervisor KPI Cards */}
      <Row className="g-3 mb-4">
        {/* Card 1: Team Members */}
        <Col sm={6} lg={3}>
          <Card className="h-100 border-0 shadow-sm bg-white">
            <Card.Body className="p-3">
              <div className="d-flex align-items-center justify-content-between mb-2">
                <span className="text-muted small text-uppercase fw-bold">Team Members</span>
                <span className="badge bg-light text-primary border p-2">
                  <Icon name="users" size={16} />
                </span>
              </div>
              <div className="h3 mb-0 fw-bold text-dark">
                {stats?.subordinates_count ?? groupedEmployees.length}
              </div>
              <div className="small text-muted mt-1">Direct subordinates</div>
            </Card.Body>
          </Card>
        </Col>

        {/* Card 2: On Leave Today */}
        <Col sm={6} lg={3}>
          <Card
            className={`h-100 border-0 shadow-sm ${
              (stats?.on_leave_today_count ?? 0) > 0
                ? 'bg-primary bg-opacity-10 border border-primary border-opacity-25'
                : 'bg-white'
            }`}
            style={{ cursor: (stats?.on_leave_today_count ?? 0) > 0 ? 'pointer' : 'default' }}
            onClick={() => {
              if ((stats?.on_leave_today_count ?? 0) > 0) {
                setEventsModal({
                  title: 'Team Members on Leave Today',
                  items: stats.on_leave_today,
                })
              }
            }}
          >
            <Card.Body className="p-3">
              <div className="d-flex align-items-center justify-content-between mb-2">
                <span
                  className={`${
                    (stats?.on_leave_today_count ?? 0) > 0
                      ? 'text-primary'
                      : 'text-muted'
                  } small text-uppercase fw-bold`}
                >
                  On Leave Today
                </span>
                <span
                  className={`badge ${
                    (stats?.on_leave_today_count ?? 0) > 0
                      ? 'bg-primary text-white'
                      : 'bg-light text-secondary border'
                  } p-2`}
                >
                  <Icon name="sun" size={16} />
                </span>
              </div>
              <div
                className={`h3 mb-0 fw-bold font-monospace ${
                  (stats?.on_leave_today_count ?? 0) > 0
                    ? 'text-primary'
                    : 'text-dark'
                }`}
              >
                {stats?.on_leave_today_count ?? 0}{' '}
                <span className="fs-6 fw-normal text-muted">out today</span>
              </div>
              <div className="small mt-1">
                {(stats?.on_leave_today_count ?? 0) > 0 ? (
                  <span className="text-primary fw-semibold">Click to view absent members</span>
                ) : (
                  <span className="text-muted">All team members present</span>
                )}
              </div>
            </Card.Body>
          </Card>
        </Col>

        {/* Card 3: Upcoming Leaves (Next 7 Days) */}
        <Col sm={6} lg={3}>
          <Card
            className={`h-100 border-0 shadow-sm ${
              (stats?.upcoming_leaves_count ?? 0) > 0
                ? 'bg-info bg-opacity-10 border border-info border-opacity-25'
                : 'bg-white'
            }`}
            style={{ cursor: (stats?.upcoming_leaves_count ?? 0) > 0 ? 'pointer' : 'default' }}
            onClick={() => {
              if ((stats?.upcoming_leaves_count ?? 0) > 0) {
                setEventsModal({
                  title: 'Upcoming Leaves (Next 7 Days)',
                  items: stats.upcoming_leaves,
                })
              }
            }}
          >
            <Card.Body className="p-3">
              <div className="d-flex align-items-center justify-content-between mb-2">
                <span
                  className={`${
                    (stats?.upcoming_leaves_count ?? 0) > 0
                      ? 'text-info-emphasis'
                      : 'text-muted'
                  } small text-uppercase fw-bold`}
                >
                  Upcoming Leaves
                </span>
                <span
                  className={`badge ${
                    (stats?.upcoming_leaves_count ?? 0) > 0
                      ? 'bg-info text-dark'
                      : 'bg-light text-secondary border'
                  } p-2`}
                >
                  <Icon name="calendar" size={16} />
                </span>
              </div>
              <div
                className={`h3 mb-0 fw-bold font-monospace ${
                  (stats?.upcoming_leaves_count ?? 0) > 0
                    ? 'text-info-emphasis'
                    : 'text-dark'
                }`}
              >
                {stats?.upcoming_leaves_count ?? 0}{' '}
                <span className="fs-6 fw-normal text-muted">next 7 days</span>
              </div>
              <div className="small mt-1">
                {(stats?.upcoming_leaves_count ?? 0) > 0 ? (
                  <span className="text-info-emphasis fw-semibold">Click to view schedule</span>
                ) : (
                  <span className="text-muted">No leaves scheduled</span>
                )}
              </div>
            </Card.Body>
          </Card>
        </Col>

        {/* Card 4: Pending Approvals */}
        <Col sm={6} lg={3}>
          <Card
            className={`h-100 border-0 shadow-sm ${
              (stats?.pending_approvals_count ?? 0) > 0
                ? 'bg-warning bg-opacity-10 border border-warning'
                : 'bg-white'
            }`}
            style={{ cursor: (stats?.pending_approvals_count ?? 0) > 0 ? 'pointer' : 'default' }}
            onClick={() => {
              if ((stats?.pending_approvals_count ?? 0) > 0) {
                navigate('/approvals')
              }
            }}
          >
            <Card.Body className="p-3">
              <div className="d-flex align-items-center justify-content-between mb-2">
                <span
                  className={`${
                    (stats?.pending_approvals_count ?? 0) > 0
                      ? 'text-warning-emphasis'
                      : 'text-muted'
                  } small text-uppercase fw-bold`}
                >
                  Pending Approvals
                </span>
                <span
                  className={`badge ${
                    (stats?.pending_approvals_count ?? 0) > 0
                      ? 'bg-warning text-dark'
                      : 'bg-light text-secondary border'
                  } p-2`}
                >
                  <Icon name="check" size={16} />
                </span>
              </div>
              <div
                className={`h3 mb-0 fw-bold font-monospace ${
                  (stats?.pending_approvals_count ?? 0) > 0
                    ? 'text-warning-emphasis'
                    : 'text-dark'
                }`}
              >
                {stats?.pending_approvals_count ?? 0}{' '}
                <span className="fs-6 fw-normal text-muted">requests</span>
              </div>
              <div className="small mt-1">
                {(stats?.pending_approvals_count ?? 0) > 0 ? (
                  <strong className="text-warning-emphasis">Review pending approvals</strong>
                ) : (
                  <span className="text-muted">No pending requests</span>
                )}
              </div>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      {/* Filter and View mode toolbar */}
      <Card className="mb-4 border-0 shadow-sm">
        <Card.Body className="p-3">
          <Row className="g-2 align-items-center">
            <Col md={5}>
              <div className="input-group input-group-sm">
                <span className="input-group-text bg-white border-end-0 text-muted">
                  <Icon name="search" size={15} />
                </span>
                <Form.Control
                  type="text"
                  placeholder="Search team member name or ID..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="border-start-0"
                />
                {search && (
                  <Button
                    variant="outline-secondary"
                    size="sm"
                    onClick={() => setSearch('')}
                  >
                    Clear
                  </Button>
                )}
              </div>
            </Col>

            <Col sm={6} md={4}>
              <Form.Select
                size="sm"
                value={leaveTypeFilter}
                onChange={(e) => setLeaveTypeFilter(e.target.value)}
              >
                <option value="">All Leave Types</option>
                {availableLeaveTypes.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({t.code})
                  </option>
                ))}
              </Form.Select>
            </Col>

            <Col sm={6} md={3} className="text-sm-end">
              <ButtonGroup size="sm">
                <Button
                  variant={viewMode === 'cards' ? 'primary' : 'outline-secondary'}
                  onClick={() => setViewMode('cards')}
                >
                  Card View
                </Button>
                <Button
                  variant={viewMode === 'table' ? 'primary' : 'outline-secondary'}
                  onClick={() => setViewMode('table')}
                >
                  Summary Table
                </Button>
              </ButtonGroup>
            </Col>
          </Row>
        </Card.Body>
      </Card>

      {/* Loading state */}
      {loading && (
        <div className="text-center py-5">
          <Spinner animation="border" variant="primary" />
          <div className="text-muted small mt-2">Loading team leave balances…</div>
        </div>
      )}

      {/* Empty states */}
      {!loading && groupedEmployees.length === 0 && (
        <Alert variant="info" className="py-4 text-center">
          <div className="mb-2">
            <Icon name="users" size={36} className="text-muted" />
          </div>
          <h2 className="h5 fw-bold mb-1">No Subordinates Found</h2>
          <p className="small text-muted mb-0">
            You do not currently have any active employees reporting to you in this leave year.
          </p>
        </Alert>
      )}

      {!loading && groupedEmployees.length > 0 && filteredEmployees.length === 0 && (
        <Alert variant="warning" className="text-center py-4">
          No team members matched your search &ldquo;{search}&rdquo;.
        </Alert>
      )}

      {/* VIEW 1: Clean Employee Cards (Default) */}
      {!loading && viewMode === 'cards' && filteredEmployees.length > 0 && (
        <div className="d-flex flex-column gap-4">
          {filteredEmployees.map((emp) => {
            // Partition into primary/everyday types and special types
            const primaryTypes = emp.items.filter(
              (item) =>
                CORE_TYPE_CODES.includes(item.leave_type_code) ||
                Number(item.used) > 0,
            )
            const specialTypes = emp.items.filter(
              (item) =>
                !CORE_TYPE_CODES.includes(item.leave_type_code) &&
                Number(item.used) === 0,
            )

            // Presence indicators
            const isOnLeaveToday = stats?.on_leave_today?.find(
              (ev) => ev.employee_id === emp.employee_id,
            )
            const upcomingEvent = stats?.upcoming_leaves?.find(
              (ev) => ev.employee_id === emp.employee_id,
            )

            return (
              <Card
                key={emp.employee_id}
                className="border-0 shadow-sm overflow-hidden"
              >
                {/* Employee Header */}
                <Card.Header className="bg-white py-3 border-bottom d-flex flex-wrap align-items-center justify-content-between gap-3">
                  <div className="d-flex align-items-center gap-3">
                    <div
                      className="rounded-circle d-flex align-items-center justify-content-center text-white fw-bold shadow-sm"
                      style={{
                        width: '42px',
                        height: '42px',
                        backgroundColor: '#f79020',
                        fontSize: '15px',
                        flexShrink: 0,
                      }}
                    >
                      {getInitials(emp.employee_name)}
                    </div>
                    <div>
                      <div className="d-flex align-items-center gap-2 flex-wrap">
                        <h2 className="h6 mb-0 fw-bold text-dark">
                          {emp.employee_name}
                        </h2>
                        <span className="badge bg-light text-secondary border font-monospace">
                          {emp.employee_code}
                        </span>

                        {isOnLeaveToday && (
                          <Badge bg="primary" className="px-2 py-1">
                            On Leave Today ({isOnLeaveToday.leave_type_code})
                          </Badge>
                        )}
                        {!isOnLeaveToday && upcomingEvent && (
                          <Badge bg="info" text="dark" className="px-2 py-1">
                            Leave from {upcomingEvent.start_date} ({upcomingEvent.leave_type_code})
                          </Badge>
                        )}
                      </div>
                      <div className="small text-muted mt-1">
                        Total leave used this year:{' '}
                        <strong className="text-dark">{days(emp.totalUsed)} days</strong>
                        {emp.totalPending > 0 && (
                          <span className="badge bg-warning text-dark ms-2">
                            {days(emp.totalPending)}d pending approval
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="d-flex align-items-center gap-2">
                    <Button
                      size="sm"
                      variant="outline-primary"
                      onClick={() => setSelectedEmployeeModal(emp)}
                    >
                      View Full Breakdown ({emp.items.length} types)
                    </Button>
                  </div>
                </Card.Header>

                {/* Primary Leave Balances Grid */}
                <Card.Body className="p-3 bg-light bg-opacity-50">
                  <Row className="g-3">
                    {primaryTypes.map((item) => {
                      const totalQuota =
                        Number(item.allocated) + Number(item.carried_forward)
                      return (
                        <Col xs={12} sm={6} md={3} key={item.id}>
                          <div className="p-3 rounded border bg-white h-100 shadow-xs">
                            <div className="d-flex justify-content-between align-items-center mb-1">
                              <span
                                className="small fw-bold text-dark text-truncate"
                                title={item.leave_type_name}
                              >
                                {item.leave_type_name}
                              </span>
                              <span
                                className="badge bg-light text-secondary border font-monospace"
                                style={{ fontSize: '10px' }}
                              >
                                {item.leave_type_code}
                              </span>
                            </div>
                            <div className="d-flex align-items-baseline gap-1 my-1">
                              <span className="fs-4 fw-bold text-success font-monospace">
                                {days(item.available)}
                              </span>
                              <span className="text-muted small">days left</span>
                            </div>
                            <div
                              className="small text-muted mb-2 d-flex justify-content-between"
                              style={{ fontSize: '12px' }}
                            >
                              <span>
                                Used: <strong>{days(item.used)}</strong> / {days(totalQuota)}
                              </span>
                              {Number(item.pending) > 0 && (
                                <span className="text-warning fw-semibold">
                                  {days(item.pending)} pnd
                                </span>
                              )}
                            </div>
                            <BalanceBar
                              used={item.used}
                              pending={item.pending}
                              available={item.available}
                              entitlement={totalQuota}
                            />
                          </div>
                        </Col>
                      )
                    })}
                  </Row>

                  {/* Special leave quotas condensed summary */}
                  {specialTypes.length > 0 && (
                    <div className="mt-3 pt-3 border-top d-flex flex-wrap align-items-center gap-2 small text-muted">
                      <span className="fw-semibold text-secondary">
                        Special quotas:
                      </span>
                      {specialTypes.map((st) => (
                        <span
                          key={st.id}
                          className="badge bg-white text-dark border font-monospace py-1 px-2"
                          title={`${st.leave_type_name}: ${days(st.available)} days available`}
                        >
                          {st.leave_type_code}: {days(st.available)} left
                        </span>
                      ))}
                      <Button
                        variant="link"
                        size="sm"
                        className="p-0 ms-1 text-decoration-none small"
                        onClick={() => setSelectedEmployeeModal(emp)}
                      >
                        view details
                      </Button>
                    </div>
                  )}
                </Card.Body>
              </Card>
            )
          })}
        </div>
      )}

      {/* VIEW 2: Summary Matrix Table (1 Row Per Employee) */}
      {!loading && viewMode === 'table' && filteredEmployees.length > 0 && (
        <Card className="border-0 shadow-sm overflow-hidden">
          <div className="table-responsive">
            <Table hover className="align-middle mb-0 small">
              <thead className="table-light text-muted text-uppercase" style={{ fontSize: '11px' }}>
                <tr>
                  <th style={{ minWidth: '180px' }}>Team Member</th>
                  <th style={{ minWidth: '130px' }}>Annual (AL)</th>
                  <th style={{ minWidth: '130px' }}>Casual (CL)</th>
                  <th style={{ minWidth: '130px' }}>Sick (SL)</th>
                  <th style={{ minWidth: '120px' }}>WFH</th>
                  <th className="text-center" style={{ minWidth: '100px' }}>Other Quotas</th>
                  <th className="text-end" style={{ minWidth: '90px' }}>Total Used</th>
                  <th className="text-end" style={{ minWidth: '90px' }}>Pending</th>
                  <th className="text-center" style={{ minWidth: '100px' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {filteredEmployees.map((emp) => {
                  const al = emp.typeMap['AL']
                  const cl = emp.typeMap['CL']
                  const sl = emp.typeMap['SL']
                  const wfh = emp.typeMap['WFH']

                  const renderQuotaCell = (quota) => {
                    if (!quota) return <span className="text-muted">—</span>
                    const total = Number(quota.allocated) + Number(quota.carried_forward)
                    return (
                      <div>
                        <div className="d-flex align-items-center gap-1">
                          <strong className="text-success font-monospace">
                            {days(quota.available)}
                          </strong>
                          <span className="text-muted small">/ {days(total)}</span>
                        </div>
                        <div style={{ maxWidth: '80px', marginTop: '2px' }}>
                          <BalanceBar
                            used={quota.used}
                            pending={quota.pending}
                            available={quota.available}
                            entitlement={total}
                          />
                        </div>
                      </div>
                    )
                  }

                  const otherCount = emp.items.filter(
                    (i) => !CORE_TYPE_CODES.includes(i.leave_type_code),
                  ).length

                  return (
                    <tr key={emp.employee_id}>
                      <td>
                        <div className="d-flex align-items-center gap-2">
                          <div
                            className="rounded-circle d-flex align-items-center justify-content-center text-white fw-bold"
                            style={{
                              width: '28px',
                              height: '28px',
                              backgroundColor: '#f79020',
                              fontSize: '11px',
                              flexShrink: 0,
                            }}
                          >
                            {getInitials(emp.employee_name)}
                          </div>
                          <div>
                            <div className="fw-bold text-dark">{emp.employee_name}</div>
                            <span className="font-monospace text-muted small">
                              {emp.employee_code}
                            </span>
                          </div>
                        </div>
                      </td>
                      <td>{renderQuotaCell(al)}</td>
                      <td>{renderQuotaCell(cl)}</td>
                      <td>{renderQuotaCell(sl)}</td>
                      <td>{renderQuotaCell(wfh)}</td>
                      <td className="text-center">
                        {otherCount > 0 ? (
                          <Badge
                            bg="light"
                            text="dark"
                            className="border font-monospace"
                            role="button"
                            onClick={() => setSelectedEmployeeModal(emp)}
                          >
                            +{otherCount} types
                          </Badge>
                        ) : (
                          <span className="text-muted">—</span>
                        )}
                      </td>
                      <td className="text-end font-monospace text-secondary fw-bold">
                        {days(emp.totalUsed)} d
                      </td>
                      <td className="text-end font-monospace">
                        {emp.totalPending > 0 ? (
                          <span className="badge bg-warning text-dark">
                            {days(emp.totalPending)} d
                          </span>
                        ) : (
                          <span className="text-muted">0.00</span>
                        )}
                      </td>
                      <td className="text-center">
                        <Button
                          size="sm"
                          variant="outline-secondary"
                          className="py-0 px-2"
                          style={{ fontSize: '12px' }}
                          onClick={() => setSelectedEmployeeModal(emp)}
                        >
                          Details
                        </Button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </Table>
          </div>
        </Card>
      )}

      {/* Team Presence Events Modal (On Leave Today or Upcoming Leaves) */}
      <Modal
        show={Boolean(eventsModal)}
        onHide={() => setEventsModal(null)}
        centered
      >
        <Modal.Header closeButton className="border-bottom">
          <Modal.Title className="h5 mb-0">{eventsModal?.title}</Modal.Title>
        </Modal.Header>
        <Modal.Body className="p-0">
          {eventsModal?.items?.length === 0 ? (
            <div className="p-4 text-center text-muted">
              No leave records found for this period.
            </div>
          ) : (
            <Table hover className="align-middle mb-0 small">
              <thead className="table-light text-muted text-uppercase" style={{ fontSize: '11px' }}>
                <tr>
                  <th>Team Member</th>
                  <th>Leave Type</th>
                  <th>Dates</th>
                  <th className="text-end">Days</th>
                </tr>
              </thead>
              <tbody>
                {eventsModal?.items?.map((item) => (
                  <tr key={item.request_id}>
                    <td>
                      <div className="fw-bold text-dark">{item.employee_name}</div>
                      <span className="font-monospace text-muted small">
                        {item.employee_code}
                      </span>
                    </td>
                    <td>
                      <span className="fw-semibold">{item.leave_type_name}</span>{' '}
                      <span className="badge bg-light text-secondary border font-monospace">
                        {item.leave_type_code}
                      </span>
                    </td>
                    <td>
                      <span className="font-monospace">
                        {item.start_date} {item.start_date !== item.end_date ? `→ ${item.end_date}` : ''}
                      </span>
                    </td>
                    <td className="text-end font-monospace fw-bold text-dark">
                      {days(item.chargeable_days)} d
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Modal.Body>
        <Modal.Footer className="py-2 border-top">
          <Button variant="secondary" size="sm" onClick={() => setEventsModal(null)}>
            Close
          </Button>
        </Modal.Footer>
      </Modal>

      {/* Full Breakdown Modal for an Employee */}
      <Modal
        show={Boolean(selectedEmployeeModal)}
        onHide={() => setSelectedEmployeeModal(null)}
        size="lg"
        centered
      >
        <Modal.Header closeButton className="border-bottom">
          <Modal.Title className="h5 mb-0">
            Leave Balances — {selectedEmployeeModal?.employee_name}
          </Modal.Title>
        </Modal.Header>
        <Modal.Body className="p-0">
          <div className="p-3 bg-light border-bottom d-flex flex-wrap justify-content-between align-items-center gap-2">
            <div>
              <span className="badge bg-white text-secondary border font-monospace me-2">
                {selectedEmployeeModal?.employee_code}
              </span>
              <span className="text-muted small">
                Leave Year: <strong>{selectedYear?.name || 'Active'}</strong>
              </span>
            </div>
            <div className="small">
              Total Used:{' '}
              <strong className="text-dark">
                {days(selectedEmployeeModal?.totalUsed)} days
              </strong>
            </div>
          </div>

          <div className="table-responsive">
            <Table hover className="align-middle mb-0 small">
              <thead className="table-light text-muted text-uppercase" style={{ fontSize: '11px' }}>
                <tr>
                  <th>Leave Type</th>
                  <th className="text-end">Allocated</th>
                  <th className="text-end">Carried Over</th>
                  <th className="text-end">Used</th>
                  <th className="text-end">Pending</th>
                  <th className="text-end">Remaining (Available)</th>
                  <th className="text-center" style={{ width: '100px' }}>Usage</th>
                </tr>
              </thead>
              <tbody>
                {selectedEmployeeModal?.items.map((row) => {
                  const totalQuota =
                    Number(row.allocated) + Number(row.carried_forward)
                  return (
                    <tr key={row.id}>
                      <td>
                        <div className="fw-semibold text-dark">{row.leave_type_name}</div>
                        <span className="badge bg-light text-secondary border font-monospace">
                          {row.leave_type_code}
                        </span>
                      </td>
                      <td className="text-end font-monospace">{days(row.allocated)}</td>
                      <td className="text-end font-monospace text-muted">
                        {days(row.carried_forward)}
                      </td>
                      <td className="text-end font-monospace text-secondary fw-semibold">
                        {days(row.used)}
                      </td>
                      <td className="text-end font-monospace text-warning fw-semibold">
                        {days(row.pending)}
                      </td>
                      <td className="text-end font-monospace">
                        <span className="fw-bold text-success fs-6">
                          {days(row.available)}
                        </span>{' '}
                        <span className="text-muted small">days</span>
                      </td>
                      <td className="text-center">
                        <BalanceBar
                          used={row.used}
                          pending={row.pending}
                          available={row.available}
                          entitlement={totalQuota}
                        />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </Table>
          </div>
        </Modal.Body>
        <Modal.Footer className="border-top py-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setSelectedEmployeeModal(null)}
          >
            Close
          </Button>
        </Modal.Footer>
      </Modal>
    </div>
  )
}
