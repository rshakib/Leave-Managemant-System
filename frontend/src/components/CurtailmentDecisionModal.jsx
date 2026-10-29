import { useEffect, useState } from 'react'
import { Alert, Button, Form, Modal } from 'react-bootstrap'

import api, { errorMessage } from '../api/client'

export default function CurtailmentDecisionModal({
  show,
  action,
  curtailment,
  onHide,
  onDecided,
}) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (show) {
      setNote('')
      setError('')
    }
  }, [show, action])

  const isReject = action === 'reject'

  const submit = async (event) => {
    event.preventDefault()
    if (!curtailment) return
    setBusy(true)
    setError('')
    try {
      const body = { note: note.trim() || null }
      await api.post(`/curtailments/${curtailment.id}/${action}`, body)
      onDecided?.({ conflict: false })
      onHide()
    } catch (err) {
      setError(errorMessage(err, 'Could not save decision.'))
      if (err.response?.status === 409) {
        onDecided?.({ conflict: true })
        onHide()
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal show={show} onHide={onHide} centered>
      <Form onSubmit={submit}>
        <Modal.Header closeButton>
          <Modal.Title>
            {isReject ? 'Reject Early Return' : 'Approve Early Return'}
          </Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {error && <Alert variant="danger">{error}</Alert>}

          {curtailment && (
            <div className="mb-3 p-2 bg-light rounded border small">
              <div>
                <strong>Employee:</strong> {curtailment.employee_name} ({curtailment.employee_code})
              </div>
              <div>
                <strong>Curtailed End Date:</strong> {curtailment.curtailed_end_date}
                {curtailment.curtailed_day_type && curtailment.curtailed_day_type !== 'FULL_DAY' && (
                  <span className="ms-1 badge bg-info text-dark">
                    {curtailment.curtailed_day_type}
                  </span>
                )}
              </div>
              <div>
                <strong>Days to Refund:</strong> +{Number(curtailment.days_to_refund).toFixed(2)} days
              </div>
              <div>
                <strong>Reason:</strong> {curtailment.reason}
              </div>
            </div>
          )}

          {!isReject && (
            <p className="text-muted small">
              Approving this will update the leave end date to{' '}
              <strong>{curtailment?.curtailed_end_date}</strong> and refund{' '}
              <strong>+{Number(curtailment?.days_to_refund || 0).toFixed(2)} days</strong> back to the
              employee's leave balance.
            </p>
          )}

          <Form.Group controlId="curtailmentNote">
            <Form.Label>
              {isReject ? 'Rejection reason (required, 3+ characters)' : 'Note / Comment (optional)'}
            </Form.Label>
            <Form.Control
              as="textarea"
              rows={3}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={1000}
              required={isReject}
              placeholder={isReject ? 'Provide reason for rejection...' : 'Optional comment...'}
            />
          </Form.Group>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={onHide} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant={isReject ? 'danger' : 'success'}
            disabled={busy || (isReject && note.trim().length < 3)}
          >
            {busy ? 'Saving...' : isReject ? 'Reject Early Return' : 'Approve Early Return'}
          </Button>
        </Modal.Footer>
      </Form>
    </Modal>
  )
}

