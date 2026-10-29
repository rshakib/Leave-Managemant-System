import { useEffect, useState } from 'react'
import { Alert, Button, Form, Modal, Spinner } from 'react-bootstrap'

import api, { errorMessage } from '../api/client'

export default function EarlyReturnModal({ show, onHide, request, onSuccess }) {
  const isSingleDay = request?.start_date === request?.end_date

  const [curtailedEndDate, setCurtailedEndDate] = useState('')
  const [curtailedDayType, setCurtailedDayType] = useState('FULL_DAY')
  const [reason, setReason] = useState('')
  const [preview, setPreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')

  useEffect(() => {
    if (show && request) {
      setReason('')
      setSubmitError('')
      setPreviewError('')
      setPreview(null)

      if (isSingleDay) {
        setCurtailedEndDate(request.start_date)
        setCurtailedDayType('FIRST_HALF')
      } else {
        // Default to start date or day before end date
        const d = new Date(request.end_date + 'T00:00:00')
        d.setDate(d.getDate() - 1)
        const maxPrev = d.toISOString().split('T')[0]
        setCurtailedEndDate(request.start_date <= maxPrev ? maxPrev : request.start_date)
        setCurtailedDayType('FULL_DAY')
      }
    }
  }, [show, request, isSingleDay])

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
        params: {
          curtailed_end_date: curtailedEndDate,
          curtailed_day_type: curtailedDayType,
        },
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
  }, [show, request, curtailedEndDate, curtailedDayType])

  const submit = async (event) => {
    event.preventDefault()
    if (!preview?.can_curtail || reason.trim().length < 3) return

    setSubmitting(true)
    setSubmitError('')
    try {
      await api.post(`/leave-requests/${request.id}/curtail`, {
        curtailed_end_date: curtailedEndDate,
        curtailed_day_type: curtailedDayType,
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
  const maxDate = request?.end_date || ''

  return (
    <Modal show={show} onHide={onHide} centered>
      <Form onSubmit={submit}>
        <Modal.Header closeButton>
          <Modal.Title>
            {isSingleDay ? 'Reduce Leave to Half Day' : 'Report Early Return'}
          </Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {submitError && <Alert variant="danger">{submitError}</Alert>}

          <p className="text-muted small mb-3">
            {isSingleDay
              ? 'You had taken a 1-day leave. If you returned early or only need half a day, select the half-day option. The remaining 0.5 day will be refunded to your balance.'
              : 'If you returned to work before your approved leave ended, request an early return. Once approved, unused leave days will be refunded back to your balance.'}
          </p>

          <div className="mb-3 p-2 bg-light rounded border small">
            <div>
              <strong>Original leave period:</strong> {request?.start_date}
              {request?.start_date !== request?.end_date && ` → ${request?.end_date}`} (
              {Number(request?.chargeable_days || 0).toFixed(2)} days, {request?.day_type})
            </div>
          </div>

          {!isSingleDay && (
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
          )}

          {/* Day Type Option (Half day vs Full day) */}
          <Form.Group className="mb-3" controlId="curtailedDayType">
            <Form.Label>
              {isSingleDay ? 'Select Half Day Breakdown' : 'Day Type for End Date'}
            </Form.Label>
            {isSingleDay ? (
              <div className="d-flex flex-column gap-2">
                <Form.Check
                  type="radio"
                  id="radioFirstHalf"
                  name="dayType"
                  label="First Half (Morning) — 0.5 Day Leave (Returned afternoon)"
                  checked={curtailedDayType === 'FIRST_HALF'}
                  onChange={() => setCurtailedDayType('FIRST_HALF')}
                />
                <Form.Check
                  type="radio"
                  id="radioSecondHalf"
                  name="dayType"
                  label="Second Half (Afternoon) — 0.5 Day Leave (Worked morning)"
                  checked={curtailedDayType === 'SECOND_HALF'}
                  onChange={() => setCurtailedDayType('SECOND_HALF')}
                />
              </div>
            ) : (
              <Form.Select
                value={curtailedDayType}
                onChange={(e) => setCurtailedDayType(e.target.value)}
              >
                <option value="FULL_DAY">Full Day</option>
                {curtailedEndDate === request?.start_date && (
                  <>
                    <option value="FIRST_HALF">First Half (Morning only - 0.5 Day)</option>
                    <option value="SECOND_HALF">Second Half (Afternoon only - 0.5 Day)</option>
                  </>
                )}
              </Form.Select>
            )}
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
              <div className="fw-semibold text-success">
                Refund Preview: +{Number(preview.days_to_refund).toFixed(2)} day(s) back to balance
              </div>
              <div className="text-muted">
                New leave duration: {Number(preview.new_days).toFixed(2)} days (reduced from{' '}
                {Number(preview.original_days).toFixed(2)} days).
              </div>
            </Alert>
          ) : null}

          <Form.Group className="mb-3" controlId="curtailReason">
            <Form.Label>Reason for Early Return / Half Day (3+ characters)</Form.Label>
            <Form.Control
              as="textarea"
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Worked half day in office / Returned to work early."
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
            {submitting ? 'Submitting...' : 'Submit Request'}
          </Button>
        </Modal.Footer>
      </Form>
    </Modal>
  )
}
