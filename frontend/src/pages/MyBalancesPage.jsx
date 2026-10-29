import { useEffect, useState } from 'react'
import { Alert, Card, Col, Row, Spinner, Table } from 'react-bootstrap'

import api, { errorMessage } from '../api/client'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

// Decimals arrive as strings; format for display only.
function days(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : '0.00'
}

const FIELD_LABELS = {
  ALLOCATED: 'Allocated',
  CARRIED_FORWARD: 'Carried forward',
  USED: 'Used',
}

function pct(part, whole) {
  if (!whole || whole <= 0) return 0
  return Math.max(0, Math.min(100, (part / whole) * 100))
}

function Figure({ label, value, tone }) {
  return (
    <div className="lms-figure">
      <span className="lms-figure__label">{label}</span>
      <strong className={`lms-figure__value${tone ? ` is-${tone}` : ''}`}>
        {value}
      </strong>
    </div>
  )
}

function BalanceBar({ used, pending, available, entitlement, label }) {
  return (
    <div
      className="lms-bar"
      role="img"
      aria-label={
        label ??
        `Used ${days(used)}, pending ${days(pending)}, available ${days(available)}`
      }
    >
      <span className="lms-bar__seg is-used" style={{ width: `${pct(used, entitlement)}%` }} />
      <span
        className="lms-bar__seg is-pending"
        style={{ width: `${pct(pending, entitlement)}%` }}
      />
      <span
        className="lms-bar__seg is-free"
        style={{ width: `${pct(available, entitlement)}%` }}
      />
    </div>
  )
}

export default function MyBalancesPage() {
  const [balances, setBalances] = useState([])
  const [adjustments, setAdjustments] = useState([])
  const [reloadKey, setReloadKey] = useState(0)
  const [activeYear, setActiveYear] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      try {
        const [years, mine, ledger] = await Promise.all([
          api.get('/leave-years'),
          api.get('/leave-balances/me'),
          api.get('/leave-balances/me/adjustments', { params: { limit: 10 } }),
        ])
        if (cancelled) return
        setActiveYear(years.data.find((year) => year.is_active) ?? null)
        setBalances(mine.data)
        setAdjustments(ledger.data.rows)
      } catch (err) {
        if (!cancelled) {
          setError(errorMessage(err, 'Could not load your balances.'))
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [reloadKey])

  // Live view: reload after any change, when the tab returns, or on the poll.
  useAutoRefresh(() => setReloadKey((key) => key + 1))

  const totals = balances.reduce(
    (sum, balance) => ({
      allocated: sum.allocated + Number(balance.allocated ?? 0),
      carried: sum.carried + Number(balance.carried_forward ?? 0),
      used: sum.used + Number(balance.used ?? 0),
      pending: sum.pending + Number(balance.pending ?? 0),
      available: sum.available + Number(balance.available ?? 0),
    }),
    { allocated: 0, carried: 0, used: 0, pending: 0, available: 0 },
  )
  const totalEntitlement = totals.allocated + totals.carried

  return (
    <>
      <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3">
        <h1 className="h3 mb-0">My balances</h1>
        {activeYear && (
          <span className="lms-year-chip">Leave year {activeYear.name}</span>
        )}
      </div>

      {error && <Alert variant="danger">{error}</Alert>}

      {loading ? (
        <div className="text-center py-5">
          <Spinner animation="border" role="status" />
        </div>
      ) : !activeYear ? (
        <div className="empty-state">
          There is no active leave year yet, so no balance exists. Please ask an
          admin to activate one.
        </div>
      ) : balances.length === 0 ? (
        <div className="empty-state">
          You have no leave assigned for {activeYear.name} yet.
        </div>
      ) : (
        <>
          {/* --- the total, broken into its parts ------------------------- */}
          <Card className="mb-3">
            <Card.Body>
              <Row className="g-4 align-items-start">
                <Col lg={4}>
                  <div className="lms-summary__label">Total available</div>
                  <div className="lms-balance__value mb-2">
                    {days(totals.available)}
                    <span>days</span>
                  </div>
                  <BalanceBar
                    used={totals.used}
                    pending={totals.pending}
                    available={totals.available}
                    entitlement={totalEntitlement}
                    label={`Total: used ${days(totals.used)}, pending ${days(totals.pending)}, available ${days(totals.available)}`}
                  />
                  <div className="lms-figure-row">
                    <Figure label="Allocated" value={days(totals.allocated)} />
                    <Figure label="Carried" value={days(totals.carried)} />
                    <Figure label="Used" value={days(totals.used)} tone="brand" />
                    <Figure label="Pending" value={days(totals.pending)} tone="warn" />
                  </div>
                </Col>

                <Col lg={8}>
                  <div className="lms-summary__label mb-2">
                    The same total, split by leave type
                  </div>
                  <div className="table-responsive">
                    <table className="table table-sm align-middle mb-0">
                      <thead>
                        <tr>
                          <th>Leave type</th>
                          <th className="text-end">Allocated</th>
                          <th className="text-end">Carried</th>
                          <th className="text-end">Used</th>
                          <th className="text-end">Pending</th>
                          <th className="text-end">Available</th>
                        </tr>
                      </thead>
                      <tbody>
                        {balances.map((balance) => (
                          <tr key={balance.id}>
                            <td>
                              <span className="fw-semibold">
                                {balance.leave_type_code}
                              </span>
                              <span className="text-muted">
                                {' '}
                                · {balance.leave_type_name}
                              </span>
                            </td>
                            <td className="text-end text-muted">
                              {days(balance.allocated)}
                            </td>
                            <td className="text-end text-muted">
                              {days(balance.carried_forward)}
                            </td>
                            <td className="text-end">{days(balance.used)}</td>
                            <td className="text-end">{days(balance.pending)}</td>
                            <td className="text-end fw-semibold">
                              {days(balance.available)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                      <tfoot>
                        <tr>
                          <th>Total</th>
                          <th className="text-end">{days(totals.allocated)}</th>
                          <th className="text-end">{days(totals.carried)}</th>
                          <th className="text-end">{days(totals.used)}</th>
                          <th className="text-end">{days(totals.pending)}</th>
                          <th className="text-end">{days(totals.available)}</th>
                        </tr>
                      </tfoot>
                    </table>
                  </div>
                </Col>
              </Row>
            </Card.Body>
          </Card>

          {/* --- one card per leave type --------------------------------- */}
          <Row className="g-3">
            {balances.map((balance) => {
              const allocated = Number(balance.allocated ?? 0)
              const carried = Number(balance.carried_forward ?? 0)
              const used = Number(balance.used ?? 0)
              const pending = Number(balance.pending ?? 0)
              const available = Number(balance.available ?? 0)

              return (
                <Col key={balance.id} md={6} xl={4}>
                  <Card className="h-100">
                    <Card.Body>
                      <div className="d-flex justify-content-between align-items-start mb-2">
                        <div>
                          <div className="lms-balance__code">
                            {balance.leave_type_code}
                          </div>
                          <div className="lms-balance__name">
                            {balance.leave_type_name}
                          </div>
                        </div>
                        {carried > 0 && (
                          <span className="lms-balance__chip">
                            +{days(carried)} carried
                          </span>
                        )}
                      </div>

                      <div className="lms-balance__value">
                        {days(available)}
                        <span>days available</span>
                      </div>

                      <BalanceBar
                        used={used}
                        pending={pending}
                        available={available}
                        entitlement={allocated + carried}
                      />

                      <div className="lms-figure-row">
                        <Figure label="Allocated" value={days(allocated)} />
                        <Figure label="Carried" value={days(carried)} />
                        <Figure label="Used" value={days(used)} tone="brand" />
                        <Figure label="Pending" value={days(pending)} tone="warn" />
                      </div>
                    </Card.Body>
                  </Card>
                </Col>
              )
            })}
          </Row>

          <Card className="mt-3">
            <Card.Header>Adjustments made to my balance</Card.Header>
            <Card.Body className={adjustments.length === 0 ? '' : 'p-0'}>
              {adjustments.length === 0 ? (
                <div className="text-muted small">
                  Nobody has adjusted your balance — it only changes through your
                  assigned days and your leave requests.
                </div>
              ) : (
                <div className="table-responsive">
                  <Table size="sm" className="mb-0">
                    <thead>
                      <tr>
                        <th>When</th>
                        <th>Leave type</th>
                        <th>Which number</th>
                        <th className="text-end">Change</th>
                        <th className="text-end">Before → After</th>
                        <th>Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {adjustments.map((row) => (
                        <tr key={row.id}>
                          <td className="small">
                            {new Date(row.created_at).toLocaleDateString()}
                          </td>
                          <td>{row.leave_type_code}</td>
                          <td>{FIELD_LABELS[row.field] ?? row.field}</td>
                          <td className="text-end">
                            {Number(row.delta) > 0 ? '+' : ''}
                            {days(row.delta)}
                          </td>
                          <td className="text-end small">
                            {days(row.value_before)} → {days(row.value_after)}
                          </td>
                          <td className="small">{row.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </div>
              )}
            </Card.Body>
          </Card>
        </>
      )}
    </>
  )
}
