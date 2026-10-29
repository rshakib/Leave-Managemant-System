import { Badge } from 'react-bootstrap'

// Small shared status pill: green when active, grey when not.
export default function StatusBadge({
  active,
  activeLabel = 'Active',
  inactiveLabel = 'Inactive',
}) {
  return (
    <Badge bg={active ? 'success' : 'secondary'}>
      {active ? activeLabel : inactiveLabel}
    </Badge>
  )
}
