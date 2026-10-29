import { useMemo, useState } from 'react'
import { Alert, Button, Form, Modal, Spinner } from 'react-bootstrap'

import api, { errorMessage } from '../api/client'

// Manual balance adjustment. Every number is handled in INTEGER HUNDREDTHS
// ("cents") so the live preview can never drift from the server's Decimal maths.

const FIELDS = [
  {
    value: 'ALLOCATED',
    label: 'Allocated (entitlement)',
    hint: 'How many days the employee is entitled to this year.',
  },
  {
    value: 'CARRIED_FORWARD',
    label: 'Carried forward',
    hint: 'Days brought in from last year.',
  },
  {
    value: 'USED',
    label: 'Used (already taken)',
    hint: 'Days already taken — raise it when leave was taken but never recorded.',
  },
]

function toCents(value) {
  const number = Number(value)
  return Number.isFinite(number) ? Math.round(number * 100) : 0
}

function parseCents(text) {
  const trimmed = String(text).trim()
  if (!/^-?\d*\.?\d{0,2}$/.test(trimmed)) return null
  if (trimmed === '' || trimmed === '-' || trimmed === '.') return null
  const negative = trimmed.startsWith('-')
  const [whole, fraction = ''] = trimmed.replace('-', '').split('.')
  const cents = Number(whole || '0') * 100 + Number((fraction + '00').slice(0, 2))
  if (!Number.isFinite(cents)) return null
  return negative ? -cents : cents
}

function show(cents) {
  const negative = cents < 0
  const absolute = Math.abs(cents)
  const text = `${Math.floor(absolute / 100)}.${String(absolute % 100).padStart(2, '0')}`
  return negative ? `-${text}` : text
}

export default function AdjustBalanceModal({ balance, show: visible, yearClosed, onHide, onSaved }) {
  const [field, setField] = useState('ALLOCATED')
  const [deltaText, setDeltaText] = useState('')
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const preview = useMemo(() => {
    if (!balance) return null
    const delta = parseCents(deltaText)
    if (delta === null) return null

    const current = {
      allocated: toCents(balance.allocated),
      carried_forward: toCents(balance.carried_forward),
      used: toCents(balance.used),
      pending: toCents(balance.pending),
    }
    const attribute = field.toLowerCase()
    const before = current[attribute]
    const after = before + delta
    const availableBefore =
      current.allocated + current.carried_forward - current.used - current.pending
    const next = { ...current, [attribute]: after }
    const availableAfter =
      next.allocated + next.carried_forward - next.used - next.pending

    return { delta, before, after, availableBefore, availableAfter }
  }, [balance, field, deltaText])

  const blockedReasons = []
  if (!preview) blockedReasons.push('Enter a delta such as 5 or -2.5.')
  if (preview && preview.delta === 0) blockedReasons.push('The delta cannot be zero.')
  if (preview && preview.after < 0) blockedReasons.push('That field would become negative.')
  if (preview && preview.availableAfter < 0)
    blockedReasons.push('The available balance would become negative.')
  if (reason.trim().length < 5) blockedReasons.push('Give a reason of at least 5 characters.')

  const canSave = blockedReasons.length === 0 && !saving

  const reset = () => {
    setField('ALLOCATED')
    setDeltaText('')
    setReason('')
    setError('')
    setSaving(false)
  }

  const close = () => {
    reset()
    onHide()
  }

  const save = async (event) => {
    event.preventDefault()
    if (!canSave) return
    setSaving(true)
    setError('')
    try {
      const { data } = await api.post(`/leave-balances/${balance.id}/adjust`, {
        field,
        delta: show(preview.delta),
        reason: reason.trim(),
      })
      onSaved(data)
      close()
    } catch (err) {
      setError(errorMessage(err, 'Could not adjust the balance.'))
      setSaving(false)
    }
  }

  return (
    <Modal show={visible} onHide={close} centered>
      <Form onSubmit={save}>
        <Modal.Header closeButton>
          <Modal.Title>Adjust balance</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {error && <Alert variant="danger">{error}</Alert>}

          {balance && (
            <p className="small text-muted">
              {balance.employee_name} ({balance.employee_code}) ·{' '}
              {balance.leave_type_code} · {balance.leave_year_name}
            </p>
          )}

          {yearClosed && (
            <Alert variant="warning" className="py-2 small">
              This leave year is <strong>closed</strong>. The change is allowed, but the
              next year's carry-forward is <strong>not</strong> recalculated — make a
              separate “Carried forward” adjustment on the next year if days should move.
            </Alert>
          )}

          <Form.Group className="mb-3" controlId="adjustField">
            <Form.Label>Which number?</Form.Label>
            <Form.Select value={field} onChange={(event) => setField(event.target.value)}>
              {FIELDS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </Form.Select>
            <Form.Text className="text-muted">
              {FIELDS.find((item) => item.value === field)?.hint}
            </Form.Text>
          </Form.Group>

          <Form.Group className="mb-3" controlId="adjustDelta">
            <Form.Label>Change (+ adds, − subtracts)</Form.Label>
            <Form.Control
              value={deltaText}
              onChange={(event) => setDeltaText(event.target.value)}
              placeholder="e.g. 5 or -2.5"
              inputMode="decimal"
            />
          </Form.Group>

          {preview && (
            <div className="lms-adjust-preview mb-3">
              <div className="lms-figure">
                <span className="lms-figure__label">{field.replace('_', ' ')}</span>
                <strong className="lms-figure__value">
                  {show(preview.before)} → {show(preview.after)}
                </strong>
              </div>
              <div className="lms-figure">
                <span className="lms-figure__label">Available</span>
                <strong
                  className={`lms-figure__value${preview.availableAfter < 0 ? ' is-warn' : ''}`}
                >
                  {show(preview.availableBefore)} → {show(preview.availableAfter)}
                </strong>
              </div>
            </div>
          )}

          <Form.Group controlId="adjustReason">
            <Form.Label>Reason (the employee can see it)</Form.Label>
            <Form.Control
              as="textarea"
              rows={2}
              value={reason}
              maxLength={500}
              onChange={(event) => setReason(event.target.value)}
              placeholder="e.g. annual bonus days approved by HR"
            />
            <Form.Text className="text-muted">
              {reason.length}/500 · the employee can see this reason, do not write
              private information.
            </Form.Text>
          </Form.Group>

          {blockedReasons.length > 0 && !saving && (
            <div className="small text-muted mt-2">{blockedReasons[0]}</div>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={close} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" disabled={!canSave}>
            {saving ? <Spinner size="sm" animation="border" /> : 'Apply adjustment'}
          </Button>
        </Modal.Footer>
      </Form>
    </Modal>
  )
}
