import { Badge, Card } from 'react-bootstrap'

// Sunday=0 ... Saturday=6, matching the API.
const WEEKDAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

const KIND_STYLES = {
  WORKING: { bg: 'success', label: 'Working' },
  WEEKEND: { bg: 'secondary', label: 'Weekend' },
  HOLIDAY: { bg: 'danger', label: 'Holiday' },
}

function formatDay(iso) {
  const [year, month, day] = iso.split('-').map(Number)
  // Build the date in UTC and read it back in UTC, so the label never shifts
  // by a day depending on the browser's timezone.
  const value = new Date(Date.UTC(year, month - 1, day))
  return `${WEEKDAY_NAMES[value.getUTCDay()]} ${day} ${MONTHS[month - 1]}`
}

export default function DayPreview({ preview }) {
  if (!preview) {
    return null
  }

  const working = preview.days.filter((day) => day.kind === 'WORKING').length
  const weekend = preview.days.filter((day) => day.kind === 'WEEKEND').length
  const holiday = preview.days.filter((day) => day.kind === 'HOLIDAY').length
  const optionalDays = preview.days.filter((day) => day.optional_holidays.length > 0)

  return (
    <Card>
      <Card.Body>
        <div className="d-flex justify-content-between align-items-center flex-wrap mb-2">
          <Card.Title className="mb-0">
            Chargeable days: {Number(preview.chargeable_days).toFixed(2)}
          </Card.Title>
          <div className="text-muted small">
            {preview.days.length} calendar day(s): {working} working, {weekend} weekend,{' '}
            {holiday} holiday
          </div>
        </div>

        <div className="mb-3 small">
          {Object.entries(KIND_STYLES).map(([kind, style]) => (
            <Badge key={kind} bg={style.bg} className="me-2">
              {style.label}
            </Badge>
          ))}
          <span className="text-muted">
            optional holidays are shown but not subtracted
          </span>
        </div>

        <div className="d-flex flex-wrap gap-2">
          {preview.days.map((day) => {
            const style = KIND_STYLES[day.kind] ?? KIND_STYLES.WORKING
            return (
              <div
                key={day.date}
                className={`border rounded px-2 py-1 text-center bg-${style.bg} bg-opacity-10`}
                style={{ minWidth: 92 }}
                title={
                  day.optional_holidays.length > 0
                    ? `Optional: ${day.optional_holidays.join(', ')}`
                    : style.label
                }
              >
                <div className="small">{formatDay(day.date)}</div>
                <Badge bg={style.bg}>{style.label}</Badge>
                {day.optional_holidays.length > 0 && (
                  <div className="small text-muted">optional holiday</div>
                )}
              </div>
            )
          })}
        </div>

        {optionalDays.length > 0 && (
          <div className="text-muted small mt-3">
            Optional holidays in this range:{' '}
            {optionalDays
              .map((day) => `${day.date} (${day.optional_holidays.join(', ')})`)
              .join('; ')}
          </div>
        )}
      </Card.Body>
    </Card>
  )
}
