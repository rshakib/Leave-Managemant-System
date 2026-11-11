import { useCallback, useEffect, useState } from 'react'
import { Alert, Badge, Modal, Spinner, Table } from 'react-bootstrap'

import api, { errorMessage } from '../api/client'

// The ledger of one balance: every adjustment, oldest correction chain included.

const FIELD_LABELS = {
  ALLOCATED: 'Allocated',
  CARRIED_FORWARD: 'Carried forward',
  USED: 'Used',
}

function days(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : '0.00'
}

export default function AdjustmentHistoryModal({
  balance,
  show = true,
  onHide,
  onClose,
}) {
  const isVisible = show !== undefined ? Boolean(show) : true
  const handleClose = onHide || onClose || (() => {})
  const [page, setPage] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    if (!balance) return
    setLoading(true)
    try {
      const params = {
        limit: 100,
      }
      if (balance.id) params.balance_id = balance.id
      if (balance.employee_id) params.employee_id = balance.employee_id
      if (balance.leave_type_id) params.leave_type_id = balance.leave_type_id
      if (balance.leave_year_id) params.leave_year_id = balance.leave_year_id

      const { data } = await api.get('/leave-balance-adjustments', { params })
      setPage(data)
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load the history.'))
    } finally {
      setLoading(false)
    }
  }, [balance])

  useEffect(() => {
    if (isVisible) {
      setPage(null)
      load()
    }
  }, [isVisible, load])

  return (
    <Modal show={isVisible} onHide={handleClose} centered size="lg">
      <Modal.Header closeButton>
        <Modal.Title>
          Adjustment history
          {balance ? ` — ${balance.employee_code} · ${balance.leave_type_code}` : ''}
        </Modal.Title>
      </Modal.Header>
      <Modal.Body>
        {balance && (
          <div className="p-3 mb-3 bg-light rounded border">
            <div className="d-flex justify-content-between align-items-center mb-2 flex-wrap gap-2">
              <div>
                <strong className="text-dark">{balance.employee_name || balance.employee_code}</strong>
                <span className="text-muted ms-2 small font-monospace">({balance.employee_code})</span>
              </div>
              <Badge bg="secondary">
                {balance.leave_type_code} — {balance.leave_type_name}
              </Badge>
            </div>
            <div className="d-flex flex-wrap gap-3 small font-monospace">
              <div>Allocated: <strong>{days(balance.allocated)}</strong></div>
              <div>Carried: <strong>{days(balance.carried_forward)}</strong></div>
              <div>Used: <strong className="text-secondary">{days(balance.used)}</strong></div>
              <div>Pending: <strong className="text-warning">{days(balance.pending)}</strong></div>
              <div>Available: <strong className="text-success">{days(balance.available)} days</strong></div>
            </div>
          </div>
        )}

        {error && <Alert variant="danger">{error}</Alert>}
        {loading ? (
          <div className="text-center py-4">
            <Spinner animation="border" role="status" />
          </div>
        ) : !page || page.rows.length === 0 ? (
          <div className="text-center py-4 text-muted bg-light rounded border border-dashed">
            <div className="mb-2 fs-5">📋</div>
            <div className="fw-semibold text-dark">No Manual Adjustments Recorded</div>
            <div className="small mt-1 text-secondary px-3">
              This balance is currently at its standard allocation.
              Any adjustments applied via the <strong>Adjust</strong> button will be recorded here with complete audit trail details (timestamp, field, delta, reason, and admin).
            </div>
          </div>
        ) : (
          <Table size="sm" bordered responsive className="mb-0">
            <thead>
              <tr>
                <th>When</th>
                <th>Field</th>
                <th className="text-end">Change</th>
                <th className="text-end">Before → After</th>
                <th>Reason</th>
                <th>By</th>
              </tr>
            </thead>
            <tbody>
              {page.rows.map((row) => (
                <tr key={row.id}>
                  <td className="small">
                    {new Date(row.created_at).toLocaleString()}
                  </td>
                  <td>
                    {FIELD_LABELS[row.field] ?? row.field}
                    {row.year_was_closed && (
                      <Badge bg="dark" className="ms-1">
                        closed year
                      </Badge>
                    )}
                  </td>
                  <td className="text-end">
                    {Number(row.delta) > 0 ? '+' : ''}
                    {days(row.delta)}
                  </td>
                  <td className="text-end small">
                    {days(row.value_before)} → {days(row.value_after)}
                  </td>
                  <td className="small">{row.reason}</td>
                  <td className="small">{row.actor_name ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Modal.Body>
    </Modal>
  )
}
