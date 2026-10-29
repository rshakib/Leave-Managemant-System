import { Badge } from 'react-bootstrap'

const COLOURS = {
  PENDING: 'warning',
  APPROVED: 'success',
  REJECTED: 'danger',
  CANCELLED: 'secondary',
  SKIPPED: 'secondary',
}

export default function RequestStatusBadge({ status }) {
  return (
    <Badge bg={COLOURS[status] ?? 'secondary'} text={status === 'PENDING' ? 'dark' : undefined}>
      {status}
    </Badge>
  )
}
