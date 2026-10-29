import { useEffect, useState } from 'react'
import { Alert, Button, Form, Modal, Spinner } from 'react-bootstrap'

import api, { errorMessage } from '../api/client'

export default function EarlyReturnModal({ show, onHide, request, onSuccess }) {
  const [curtailedEndDate, setCurtailedEndDate] = useState('')
  const [reason, setReason] = useState('')
  const [preview, setPreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')

  // Compute maximum allowed curtailment end date (day before original end date)
  const getMaxEndDate = () => {
    if (!request?.end_date) return ''
    const d = new Date(request.end_date + 'T00:00:00')
    d.setDate(d.getDate() - 1)
    return d.toISOString().split('T')[0]
  }

  useEffect(() => {
    if (show && request) {
      setReason('')
      setSubmitError('')
      setPreviewError('')
      setPreview(null)
      // Default to start_date or day before end_date
      const maxDate = getMaxEndDate()
      const initialDate = request.start_date <= maxDate ? request.start_date : maxDate
      setCurtailedEndDate(initialDate)
    }
  }, [show, request])

  useEffect(() => {
    if (!show || !request || !curtailedEndDate) {
      setPreview(null)
      return
    }

    let active = true
    setPreviewLoading(true)
    setPreviewError('')

    api
      .get(`/leave-requests/${request.id}/curtail/preview`, {
        params: { curtailed_end_date: curtailedEndDate },
      })
      .then(({ data }) => {
        if (!active) return
        setPreview(data)
        if (!data.can_curtail && data.error) {
          setPreviewError(data.error)
        }
      })
      .catch((err) => {
        if (!active) return
        setPreviewError(errorMessage(err, 'Could not calculate refund preview.'))
        setPreview(null)
      })
      .finally(() => {
        if (active) setPreviewLoading(false)
      })

    return () => {
      active = false
    }
  }, [show, request, curtailedEndDate])

  const submit = async (event) => {
    event.preventDefault()
    if (!preview?.can_curtail || reason.trim().length < 3) return

    setSubmitting(true)
    setSubmitError('')
    try {
      await api.post(`/leave-requests/${request.id}/curtail`, {
        curtailed_end_date: curtailedEndDate,
        reason: reason.trim(),
      })
      onSuccess?.()
      onHide()
    } catch (err) {
      setSubmitError(errorMessage(err, 'Failed to submit early return request.'))
    } finally {
      setSubmitting(false)
    }
  }

  const minDate = request?.start_date || ''
  const maxDate = getMaxEndDate()

  return (
    <Modal show={show} onHide={onHide} centered>
      <Form onSubmit={submit}>
        <Modal.Header closeButton>
          <Modal.Title>Report Early Return</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {submitError && <Alert variant="danger">{submitError}</Alert>}

          <p className="text-muted small mb-3">
            If you returned to work before your approved leave ended, request an early return.
            Once approved by your supervisor, unused leave days will be refunded back to your balance.
          </p>

          <div className="mb-3 p-2 bg-light rounded border small">
            <div>
              <strong>Original leave period:</strong> {request?.start_date} → {request?.end_date} (
              {Number(request?.chargeable_days || 0).toFixed(2)} days)
            </div>
          </div>

          <Form.Group className="mb-3" controlId="curtailedEndDate">
            <Form.Label>New Actual End Date</Form.Label>
            <Form.Control
              type="date"
              value={curtailedEndDate}
              min={minDate}
              max={maxDate}
              onChange={(e) => setCurtailedEndDate(e.target.value)}
              required
            />
            <Form.Text className="text-muted">
              Must be between {minDate} and {maxDate}.
            </Form.Text>
          </Form.Group>

          {previewLoading ? (
            <div className="text-center py-2">
              <Spinner animation="border" size="sm" className="me-2" />
              <span className="small text-muted">Calculating days to refund...</span>
            </div>
          ) : previewError ? (
            <Alert variant="warning" className="small py-2">
              {previewError}
            </Alert>
          ) : preview?.can_curtail ? (
            <Alert variant="info" className="small py-2 mb-3">
              <div className="fw-semibold">
                Refund Preview: +{Number(preview.days_to_refund).toFixed(2)} days
              </div>
              <div className="text-muted">
                New leave duration: {Number(preview.new_days).toFixed(2)} days (reduced from{' '}
                {Number(preview.original_days).toFixed(2)} days).
              </div>
            </Alert>
          ) : null}

          <Form.Group className="mb-3" controlId="curtailReason">
            <Form.Label>Reason for Early Return (3+ characters)</Form.Label>
            <Form.Control
              as="textarea"
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Work resumed earlier than planned / personal matters resolved."
              maxLength={1000}
              required
            />
          </Form.Group>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={onHide} disabled={submitting}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            disabled={
              submitting ||
              previewLoading ||
              !preview?.can_curtail ||
              reason.trim().length < 3
            }
          >
            {submitting ? 'Submitting...' : 'Submit Early Return'}
          </Button>
        </Modal.Footer>
      </Form>
    </Modal>
  )
}
