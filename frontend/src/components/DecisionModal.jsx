import { useEffect, useState } from 'react'
import { Alert, Button, Form, Modal } from 'react-bootstrap'

import api, { errorMessage } from '../api/client'

// One small shared modal used by both the inbox and the detail page, so
// "Approve" and "Reject" behave identically everywhere.
export default function DecisionModal({ show, action, requestId, onHide, onDecided }) {
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (show) {
      setComment('')
      setError('')
    }
  }, [show, action])

  const isReject = action === 'reject'

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const body = isReject
        ? { comment: comment.trim() }
        : { comment: comment.trim() || null }
      await api.post(`/leave-requests/${requestId}/${action}`, body)
      onDecided({ conflict: false })
    } catch (err) {
      setError(errorMessage(err, 'Could not save your decision.'))
      if (err.response?.status === 409) {
        // Somebody else already decided: show the message and refresh the page.
        onDecided({ conflict: true })
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal show={show} onHide={onHide} centered>
      <Form onSubmit={submit}>
        <Modal.Header closeButton>
          <Modal.Title>{isReject ? 'Reject request' : 'Approve request'}</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {error && <Alert variant="danger">{error}</Alert>}
          <Form.Group controlId="decisionComment">
            <Form.Label>
              {isReject ? 'Reason (required, 3+ characters)' : 'Comment (optional)'}
            </Form.Label>
            <Form.Control
              as="textarea"
              rows={3}
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              maxLength={1000}
              required={isReject}
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
            disabled={busy || (isReject && comment.trim().length < 3)}
          >
            {busy ? 'Saving...' : isReject ? 'Reject' : 'Approve'}
          </Button>
        </Modal.Footer>
      </Form>
    </Modal>
  )
}
