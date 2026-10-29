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

export default function AdjustmentHistoryModal({ balance, show, onHide }) {
  const [page, setPage] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    if (!balance) return
    setLoading(true)
    try {
      const { data } = await api.get('/leave-balance-adjustments', {
        params: {
          employee_id: balance.employee_id,
          leave_type_id: balance.leave_type_id,
          leave_year_id: balance.leave_year_id,
          limit: 100,
        },
      })
      setPage(data)
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load the history.'))
    } finally {
      setLoading(false)
    }
  }, [balance])

  useEffect(() => {
    if (show) load()
  }, [show, load])

  return (
    <Modal show={show} onHide={onHide} centered size="lg">
      <Modal.Header closeButton>
        <Modal.Title>
          Adjustment history
          {balance ? ` — ${balance.employee_code} · ${balance.leave_type_code}` : ''}
        </Modal.Title>
      </Modal.Header>
      <Modal.Body>
        {error && <Alert variant="danger">{error}</Alert>}
        {loading ? (
          <div className="text-center py-4">
            <Spinner animation="border" role="status" />
          </div>
        ) : !page || page.rows.length === 0 ? (
          <div className="empty-state">No adjustments for this balance yet.</div>
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
