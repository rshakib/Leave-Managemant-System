import { useEffect, useRef, useState } from 'react'
import { Button, Form, Spinner } from 'react-bootstrap'
import { Link, useSearchParams } from 'react-router-dom'

import api, { errorMessage } from '../api/client'

function formatDate(dateStr) {
  if (!dateStr) return ''
  try {
    const parts = String(dateStr).split('T')[0].split('-')
    if (parts.length === 3) {
      const d = new Date(Date.UTC(+parts[0], +parts[1] - 1, +parts[2]))
      return d.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        timeZone: 'UTC',
      })
    }
  } catch {
    // fallback
  }
  return dateStr
}

function formatDateRange(startDate, endDate, days) {
  if (!startDate) return ''
  const startFmt = formatDate(startDate)
  const endFmt = endDate && endDate !== startDate ? formatDate(endDate) : ''
  const daysNum = days !== null && days !== undefined ? Number(days) : null
  const daysText = daysNum !== null ? ` (${daysNum === 1 ? '1 day' : `${daysNum} days`})` : ''
  if (!endFmt || startFmt === endFmt) {
    return `${startFmt}${daysText}`
  }
  return `${startFmt} – ${endFmt}${daysText}`
}

export default function QuickApprovalPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''
  const initialAction = (searchParams.get('action') || 'APPROVE').toUpperCase()

  const [loading, setLoading] = useState(true)
  const [preview, setPreview] = useState(null)
  const [loadError, setLoadError] = useState('')

  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')
  const [result, setResult] = useState(null)
  const executedRef = useRef(false)

  useEffect(() => {
    if (!token) {
      setLoading(false)
      setLoadError('This link appears to be incomplete or invalid.')
      return
    }

    // Instant 1-click approval: if clicked from email "Approve", process decision immediately!
    if (initialAction === 'APPROVE') {
      if (executedRef.current) return
      executedRef.current = true

      setSubmitting(true)
      api
        .post('/approvals/quick-decide', {
          token,
          action: 'APPROVE',
        })
        .then(({ data }) => {
          setResult(data)
        })
        .catch((err) => {
          const msg = errorMessage(err, '')
          if (msg.toLowerCase().includes('already approved')) {
            setResult({
              status: 'APPROVED',
              already_decided: true,
              message: 'This leave request has already been approved.',
            })
            return
          }
          if (msg.toLowerCase().includes('already rejected')) {
            setResult({
              status: 'REJECTED',
              already_decided: true,
              message: 'This leave request has already been declined.',
            })
            return
          }
          setLoadError(
            errorMessage(
              err,
              'This link is no longer valid or has already been used.'
            )
          )
        })
        .finally(() => {
          setSubmitting(false)
          setLoading(false)
        })
      return
    }

    // For REJECT, fetch preview so approver can review details and enter rejection reason
    const verifyToken = async () => {
      try {
        const { data } = await api.get('/approvals/quick-verify', {
          params: { token, action: 'REJECT' },
        })
        if (data.request_status === 'APPROVED' || data.approval_status === 'APPROVED') {
          setResult({
            status: 'APPROVED',
            already_decided: true,
            employee_name: data.employee_name,
            leave_type_name: data.leave_type_name,
            start_date: data.start_date,
            end_date: data.end_date,
            chargeable_days: data.chargeable_days,
            message: 'This leave request has already been approved.',
          })
          return
        }
        if (data.request_status === 'REJECTED' || data.approval_status === 'REJECTED') {
          setResult({
            status: 'REJECTED',
            already_decided: true,
            employee_name: data.employee_name,
            leave_type_name: data.leave_type_name,
            start_date: data.start_date,
            end_date: data.end_date,
            chargeable_days: data.chargeable_days,
            message: 'This leave request has already been declined.',
          })
          return
        }
        setPreview(data)
      } catch (err) {
        const msg = errorMessage(err, '')
        if (msg.toLowerCase().includes('already approved')) {
          setResult({
            status: 'APPROVED',
            already_decided: true,
            message: 'This leave request has already been approved.',
          })
          return
        }
        if (msg.toLowerCase().includes('already rejected')) {
          setResult({
            status: 'REJECTED',
            already_decided: true,
            message: 'This leave request has already been declined.',
          })
          return
        }
        setLoadError(
          errorMessage(
            err,
            'This link is no longer valid or has already been used.'
          )
        )
      } finally {
        setLoading(false)
      }
    }

    verifyToken()
  }, [token, initialAction])

  const handleRejectSubmit = async (e) => {
    e.preventDefault()
    setSubmitError('')

    if (!comment || comment.trim().length < 3) {
      setSubmitError('Please enter a brief reason for declining (at least 3 characters).')
      return
    }

    setSubmitting(true)
    try {
      const { data } = await api.post('/approvals/quick-decide', {
        token,
        action: 'REJECT',
        comment: comment.trim(),
      })
      setResult({
        ...data,
        employee_name: data.employee_name || preview?.employee_name,
        leave_type_name: data.leave_type_name || preview?.leave_type_name,
        start_date: data.start_date || preview?.start_date,
        end_date: data.end_date || preview?.end_date,
        chargeable_days: data.chargeable_days ?? preview?.chargeable_days,
      })
    } catch (err) {
      const msg = errorMessage(err, '')
      if (msg.toLowerCase().includes('already approved')) {
        setResult({
          status: 'APPROVED',
          already_decided: true,
          message: 'This leave request has already been approved.',
        })
        return
      }
      if (msg.toLowerCase().includes('already rejected')) {
        setResult({
          status: 'REJECTED',
          already_decided: true,
          message: 'This leave request has already been declined.',
        })
        return
      }
      setSubmitError(
        errorMessage(err, 'Unable to decline request at this time. Please try again.')
      )
    } finally {
      setSubmitting(false)
    }
  }

  const handleCloseTab = () => {
    window.close()
  }

  const isAlreadyApproved =
    Boolean(result?.already_decided && result?.status === 'APPROVED') ||
    Boolean(loadError && loadError.toLowerCase().includes('already approved'))
  const isAlreadyRejected =
    Boolean(result?.already_decided && result?.status === 'REJECTED') ||
    Boolean(loadError && loadError.toLowerCase().includes('already rejected'))

  const effectiveResult =
    result ||
    (isAlreadyApproved
      ? {
          status: 'APPROVED',
          already_decided: true,
          message: 'This leave request has already been approved.',
        }
      : isAlreadyRejected
        ? {
            status: 'REJECTED',
            already_decided: true,
            message: 'This leave request has already been declined.',
          }
        : null)

  const employeeName = effectiveResult?.employee_name || preview?.employee_name || ''
  const leaveTypeName = effectiveResult?.leave_type_name || preview?.leave_type_name || ''
  const startDate = effectiveResult?.start_date || preview?.start_date || ''
  const endDate = effectiveResult?.end_date || preview?.end_date || ''
  const chargeableDays = effectiveResult?.chargeable_days ?? preview?.chargeable_days
  const datesFormatted = formatDateRange(startDate, endDate, chargeableDays)

  return (
    <div
      className="min-vh-100 d-flex flex-column align-items-center justify-content-center p-3"
      style={{ background: '#f8fafc' }}
    >
      <div
        className="w-100 bg-white"
        style={{
          maxWidth: '540px',
          borderRadius: '16px',
          boxShadow: '0 20px 45px rgba(15, 23, 42, 0.08), 0 4px 12px rgba(15, 23, 42, 0.03)',
          border: '1px solid #e2e8f0',
          padding: '2.5rem 2.25rem',
        }}
      >
        {/* Brand header */}
        <div className="text-center mb-4">
          <div
            className="fw-bold"
            style={{ fontSize: '1.45rem', letterSpacing: '-0.02em', color: '#0f172a' }}
          >
            SOL<span style={{ color: '#f79020' }}>share</span>
          </div>
          <div
            className="text-uppercase fw-semibold"
            style={{ color: '#64748b', letterSpacing: '0.08em', fontSize: '0.72rem' }}
          >
            Leave Management
          </div>
        </div>

        {/* Loading state */}
        {loading && (
          <div className="text-center py-5">
            <Spinner animation="border" variant="success" style={{ width: '3rem', height: '3rem' }} />
            <div className="h5 mt-4 mb-2 fw-semibold text-dark">
              {initialAction === 'APPROVE' ? 'Approving leave request…' : 'Loading request details…'}
            </div>
            <div className="text-muted small">
              Please wait a moment while we update the records.
            </div>
          </div>
        )}

        {/* Invalid / Expired Link Error */}
        {!loading && !effectiveResult && loadError && (
          <div className="text-center py-2">
            <div
              className="d-inline-flex align-items-center justify-content-center rounded-circle mb-3"
              style={{ width: '64px', height: '64px', background: '#fffbeb', color: '#d97706' }}
            >
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </div>
            <h2 className="h4 fw-bold text-dark mb-2">Link No Longer Active</h2>
            <p className="text-muted small mb-4 px-2" style={{ lineHeight: '1.6' }}>
              {loadError || 'This link has already been used or has expired. If you still need to review this request, please sign in to the leave portal.'}
            </p>
            <div className="d-flex flex-column gap-2">
              <Link
                to="/login"
                className="btn btn-primary fw-semibold py-2"
                style={{ background: '#f79020', borderColor: '#f79020', borderRadius: '8px' }}
              >
                Sign In to Leave Portal
              </Link>
              <Button variant="link" className="text-decoration-none text-muted small" onClick={handleCloseTab}>
                Close this window
              </Button>
            </div>
          </div>
        )}

        {/* Success / Decided Result (Approved or Rejected) */}
        {!loading && effectiveResult && (
          <div className="text-center py-2">
            {effectiveResult.status === 'APPROVED' ? (
              <div
                className="d-inline-flex align-items-center justify-content-center rounded-circle mb-3"
                style={{ width: '64px', height: '64px', background: '#ecfdf5', color: '#059669' }}
              >
                <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </div>
            ) : (
              <div
                className="d-inline-flex align-items-center justify-content-center rounded-circle mb-3"
                style={{ width: '64px', height: '64px', background: '#fef2f2', color: '#dc2626' }}
              >
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </div>
            )}

            <h2 className="h4 fw-bold text-dark mb-2">
              {effectiveResult.status === 'APPROVED'
                ? effectiveResult.already_decided
                  ? 'Already Approved'
                  : 'Leave Request Approved!'
                : effectiveResult.already_decided
                  ? 'Already Declined'
                  : 'Leave Request Declined'}
            </h2>

            <p className="text-muted small mb-3 px-2" style={{ lineHeight: '1.6' }}>
              {effectiveResult.status === 'APPROVED'
                ? effectiveResult.already_decided
                  ? 'This leave request was already approved earlier. No further action is required.'
                  : 'The leave request has been approved. The team member has been notified by email.'
                : effectiveResult.already_decided
                  ? 'This leave request was already declined earlier. No further action is required.'
                  : 'The leave request has been declined. The team member has been notified with your reason.'}
            </p>

            {/* Request Summary Card */}
            {(employeeName || leaveTypeName || datesFormatted) && (
              <div
                className="text-start rounded-3 p-3 mb-4"
                style={{ background: '#f8fafc', border: '1px solid #e2e8f0' }}
              >
                <div className="row g-2 small">
                  {employeeName && (
                    <>
                      <div className="col-4 text-muted">Team member</div>
                      <div className="col-8 fw-semibold text-dark">{employeeName}</div>
                    </>
                  )}
                  {leaveTypeName && (
                    <>
                      <div className="col-4 text-muted">Leave type</div>
                      <div className="col-8 fw-semibold text-dark">{leaveTypeName}</div>
                    </>
                  )}
                  {datesFormatted && (
                    <>
                      <div className="col-4 text-muted">Dates</div>
                      <div className="col-8 fw-semibold text-dark">{datesFormatted}</div>
                    </>
                  )}
                </div>
              </div>
            )}

            <div className="text-muted small mb-4">
              You can safely close this window now.
            </div>

            <div className="d-flex flex-column gap-2">
              <Button
                variant="outline-secondary"
                size="lg"
                className="fw-semibold"
                style={{ borderRadius: '8px', fontSize: '0.95rem' }}
                onClick={handleCloseTab}
              >
                Close This Window
              </Button>
              <Link
                to="/login"
                className="btn btn-link text-decoration-none text-muted small text-center mt-1"
              >
                Go to Leave Portal →
              </Link>
            </div>
          </div>
        )}

        {/* Decline (Reject) Form State */}
        {!loading && !loadError && !effectiveResult && preview && (
          <div>
            <div className="text-center mb-4">
              <div
                className="d-inline-flex align-items-center justify-content-center rounded-circle mb-3"
                style={{ width: '56px', height: '56px', background: '#fef2f2', color: '#dc2626' }}
              >
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="9" y1="15" x2="15" y2="15" />
                </svg>
              </div>
              <h2 className="h4 fw-bold text-dark mb-1">Decline Leave Request</h2>
              <div className="text-muted small">
                Review request details and provide a reason before declining.
              </div>
            </div>

            {/* Request Summary */}
            <div
              className="rounded-3 p-3 mb-4"
              style={{ background: '#f8fafc', border: '1px solid #e2e8f0' }}
            >
              <div className="row g-2 small">
                <div className="col-4 text-muted">Team member</div>
                <div className="col-8 fw-semibold text-dark">{preview.employee_name}</div>

                <div className="col-4 text-muted">Leave type</div>
                <div className="col-8 fw-semibold text-dark">{preview.leave_type_name}</div>

                <div className="col-4 text-muted">Dates</div>
                <div className="col-8 fw-semibold text-dark">
                  {formatDateRange(preview.start_date, preview.end_date, preview.chargeable_days)}
                </div>

                {preview.reason && (
                  <>
                    <div className="col-4 text-muted">Reason</div>
                    <div className="col-8 text-dark fst-italic">
                      &ldquo;{preview.reason}&rdquo;
                    </div>
                  </>
                )}
              </div>
            </div>

            {submitError && (
              <div
                className="alert alert-danger py-2 px-3 small mb-3 border-0 rounded-2"
                style={{ background: '#fef2f2', color: '#991b1b' }}
              >
                {submitError}
              </div>
            )}

            <Form onSubmit={handleRejectSubmit}>
              <Form.Group className="mb-4" controlId="declineReason">
                <Form.Label className="small fw-semibold text-dark mb-1">
                  Reason for declining <span className="text-danger">*</span>
                </Form.Label>
                <Form.Control
                  as="textarea"
                  rows={3}
                  placeholder="Please share a brief note explaining why this request cannot be approved…"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  required
                  minLength={3}
                  maxLength={1000}
                  autoFocus
                  style={{ borderRadius: '8px', fontSize: '0.9rem' }}
                />
                <div className="form-text text-muted small mt-1">
                  This note will be included in the email notification sent to the team member.
                </div>
              </Form.Group>

              <div className="d-flex flex-column gap-2">
                <Button
                  type="submit"
                  variant="danger"
                  size="lg"
                  className="w-100 fw-semibold"
                  style={{ borderRadius: '8px', fontSize: '0.95rem' }}
                  disabled={submitting || !comment || comment.trim().length < 3}
                >
                  {submitting ? (
                    <>
                      <Spinner size="sm" animation="border" className="me-2" />
                      Declining request…
                    </>
                  ) : (
                    'Decline Leave Request'
                  )}
                </Button>
                <Button
                  type="button"
                  variant="link"
                  className="text-decoration-none text-muted small text-center"
                  onClick={handleCloseTab}
                >
                  Cancel and close
                </Button>
              </div>
            </Form>
          </div>
        )}
      </div>
    </div>
  )
}
