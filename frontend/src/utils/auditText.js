// Turns a raw audit row (action code + JSON snapshots) into words an HR person can read.
// Nothing here touches the database: every sentence is derived from the row that is already shown.

const ACTIONS = {
  SUBMIT: 'submitted a leave request',
  CANCEL: 'cancelled a leave request',
  APPROVE: 'approved a leave request',
  REJECT: 'rejected a leave request',
  CREATE: 'added a new record',
  UPDATE: 'changed a record',
  DELETE: 'deleted a record',
  ROLES_CHANGED: 'changed which roles somebody has',
  PASSWORD_RESET: "reset somebody else's password",
  PASSWORD_CHANGED: 'changed their own password',
  LOGIN_SUCCESS: 'signed in',
  LOGIN_FAILED: 'tried to sign in with a wrong password',
  SESSION_REVOKED: 'signed one device out',
  SESSIONS_REVOKED: 'signed every device out',
  CLOSE_YEAR: 'closed a leave year and carried the remaining days forward',
  BALANCE_ADJUSTED: 'changed a leave balance by hand',
  APPROVERS_SET: 'changed who approves for somebody',
  LEAVE_TYPES_ASSIGNED: 'assigned leave types',
  HOLIDAYS_IMPORTED: 'imported holidays from a file',
  REPORT_EXPORTED: 'downloaded a report',
}

const FIELDS = {
  status: 'Status',
  balances: 'Leave balance',
  allocated: 'Days given for the year',
  used: 'Days taken',
  pending: 'Days reserved (waiting for approval)',
  available: 'Days still available',
  carried_forward: 'Days carried from last year',
  is_active: 'Active?',
  roles: 'Roles',
  name: 'Name',
  full_name: 'Full name',
  employee_code: 'Employee ID',
  email: 'Email',
  leave_year: 'Leave year',
  leave_type: 'Leave type',
  allocated_days: 'Days given to this employee',
  reason: 'Reason',
  is_closed: 'Closed?',
}

const VALUES = {
  PENDING: 'Waiting for approval',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  CANCELLED: 'Cancelled',
  SKIPPED: 'Skipped (somebody else decided first)',
  true: 'Yes',
  false: 'No',
}

const prettify = (code) =>
  String(code ?? '')
    .toLowerCase()
    .replace(/_/g, ' ')
    .replace(/^\w/, (character) => character.toUpperCase())

const days = (value) => {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  return Number.isFinite(number) ? String(number) : String(value)
}

const valueText = (key, value) => {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) return value.length ? value.join(', ') : 'none'
  if (typeof value === 'object') return Object.keys(value).length ? '—' : 'none'
  if (key === 'status' || key === 'is_active' || key === 'is_closed') {
    const word = VALUES[value] ?? VALUES[String(value)]
    if (word) return word
  }
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value)
}

/** One short line: who did what. */
export function describeAction(action) {
  return ACTIONS[action] ?? prettify(action).toLowerCase()
}

/** The same row in developer words, kept for the "technical details" line. */
export function technicalLine(row) {
  const id =
    row?.entity_id === null || row?.entity_id === undefined ? '' : ` #${row.entity_id}`
  return `${row?.action ?? ''} · ${row?.entity_type ?? ''}${id}`
}

/**
 * What changed, in HR language: [{ label, before, after }].
 * Balance snapshots are expanded into one line per changed number.
 */
export function describeChanges(row) {
  const before = row?.old_value ?? {}
  const after = row?.new_value ?? {}
  const keys = row?.changed?.length ? row.changed : Object.keys(after)
  const lines = []

  for (const key of keys) {
    if (key === 'balances') {
      const ids = Object.keys(after.balances ?? before.balances ?? {})
      for (const id of ids) {
        const oldBalance = before.balances?.[id] ?? {}
        const newBalance = after.balances?.[id] ?? {}
        for (const field of ['allocated', 'used', 'pending', 'available']) {
          if (String(oldBalance[field]) === String(newBalance[field])) continue
          lines.push({
            label: FIELDS[field] ?? prettify(field),
            before: days(oldBalance[field]),
            after: days(newBalance[field]),
          })
        }
      }
      continue
    }
    lines.push({
      label: FIELDS[key] ?? prettify(key),
      before: valueText(key, before[key]),
      after: valueText(key, after[key]),
    })
  }
  return lines
}
