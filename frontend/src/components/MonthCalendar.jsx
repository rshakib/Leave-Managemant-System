import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Form, Spinner } from 'react-bootstrap'

import api, { errorMessage } from '../api/client'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

// A full month at a glance: weekends, holidays and the chargeable days, for the
// signed-in employee. Sunday = 0 … Saturday = 6, matching the API.

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

function iso(date) {
  return date.toISOString().slice(0, 10)
}

function monthInfo(year, month) {
  const first = new Date(Date.UTC(year, month - 1, 1))
  const last = new Date(Date.UTC(year, month, 0))
  return {
    start: iso(first),
    end: iso(last),
    firstWeekday: first.getUTCDay(),
    daysInMonth: last.getUTCDate(),
  }
}

export default function MonthCalendar() {
  const [todayIso] = useState(() => iso(new Date()))
  const [cursor, setCursor] = useState(() => {
    const now = new Date()
    return { year: now.getFullYear(), month: now.getMonth() + 1 }
  })
  const [month, setMonth] = useState(null)
  const [byDate, setByDate] = useState({})
  const [holidayTitles, setHolidayTitles] = useState({})
  const [myLeave, setMyLeave] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reloadKey, setReloadKey] = useState(0)

  useAutoRefresh(() => setReloadKey((key) => key + 1))

  const load = useCallback(async () => {
    const bounds = monthInfo(cursor.year, cursor.month)
    try {
      const [preview, holidays, mine] = await Promise.all([
        api.get('/calendar/preview', {
          params: {
            start_date: bounds.start,
            end_date: bounds.end,
            day_type: 'FULL_DAY',
          },
        }),
        api.get('/holidays', { params: { leave_year_id: undefined } }),
        api.get('/leave-requests/me', { params: { limit: 100 } }),
      ])

      const index = {}
      preview.data.days.forEach((day) => {
        index[day.date] = day
      })

      const titles = {}
      holidays.data.forEach((row) => {
        titles[row.date] = [...(titles[row.date] ?? []), row]
      })

      const leaveIndex = {}
      mine.data.forEach((row) => {
        if (row.status !== 'PENDING' && row.status !== 'APPROVED') return
        if (row.end_date < bounds.start || row.start_date > bounds.end) return
        const cursor = new Date(`${row.start_date}T00:00:00Z`)
        const last = new Date(`${row.end_date}T00:00:00Z`)
        while (cursor <= last) {
          const key = iso(cursor)
          if (index[key]?.kind === 'WORKING') {
            leaveIndex[key] = {
              status: row.status,
              label: row.leave_type_name ?? row.leave_type_code ?? 'Leave',
            }
          }
          cursor.setUTCDate(cursor.getUTCDate() + 1)
        }
      })

      setMonth({ ...bounds, summary: preview.data })
      setMyLeave(leaveIndex)
      setByDate(index)
      setHolidayTitles(titles)
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load the calendar.'))
    } finally {
      setLoading(false)
    }
  }, [cursor.year, cursor.month])

  useEffect(() => {
    load()
  }, [load, reloadKey])

  const shift = (delta) => {
    setCursor((current) => {
      const next = new Date(Date.UTC(current.year, current.month - 1 + delta, 1))
      return { year: next.getUTCFullYear(), month: next.getUTCMonth() + 1 }
    })
  }

  const thisYear = cursor.year
  const years = [thisYear - 1, thisYear, thisYear + 1, thisYear + 2]

  const cells = []
  if (month) {
    for (let blank = 0; blank < month.firstWeekday; blank += 1) {
      cells.push(null)
    }
    for (let day = 1; day <= month.daysInMonth; day += 1) {
      cells.push(day)
    }
  }

  const isoForDay = (day) =>
    month ? iso(new Date(Date.UTC(cursor.year, cursor.month - 1, day))) : ''

  const weekendSet = new Set(month?.summary?.weekend_days ?? [])

  const myLeaveCounts = Object.values(myLeave).reduce(
    (acc, row) => ({ ...acc, [row.status]: (acc[row.status] ?? 0) + 1 }),
    { APPROVED: 0, PENDING: 0 },
  )

  const counts = { WORKING: 0, WEEKEND: 0, HOLIDAY: 0 }
  Object.values(byDate).forEach((entry) => {
    counts[entry.kind] = (counts[entry.kind] ?? 0) + 1
  })

  return (
    <Card className="h-100">
      <Card.Header className="d-flex flex-wrap justify-content-between align-items-center gap-2">
        <span>Calendar</span>
        <div className="d-flex align-items-center gap-1">
          <Button
            size="sm"
            variant="outline-secondary"
            onClick={() => shift(-1)}
            aria-label="Previous month"
          >
            ‹
          </Button>
          <Form.Select
            size="sm"
            aria-label="Month"
            style={{ width: 130 }}
            value={cursor.month}
            onChange={(event) =>
              setCursor({ ...cursor, month: Number(event.target.value) })
            }
          >
            {MONTHS.map((label, index) => (
              <option key={label} value={index + 1}>
                {label}
              </option>
            ))}
          </Form.Select>
          <Form.Select
            size="sm"
            aria-label="Year"
            style={{ width: 96 }}
            value={cursor.year}
            onChange={(event) =>
              setCursor({ ...cursor, year: Number(event.target.value) })
            }
          >
            {years.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </Form.Select>
          <Button
            size="sm"
            variant="outline-secondary"
            onClick={() => shift(1)}
            aria-label="Next month"
          >
            ›
          </Button>
        </div>
      </Card.Header>

      <Card.Body>
        {error && <Alert variant="danger">{error}</Alert>}

        {loading && !month ? (
          <div className="text-center py-4">
            <Spinner animation="border" role="status" />
          </div>
        ) : (
          <>
            <div className="lms-month__legend mb-2">
              <span>
                <span className="lms-month__dot" style={{ background: '#fff' }} />
                Working {counts.WORKING}
              </span>
              <span>
                <span className="lms-month__dot" style={{ background: '#f7f3ec' }} />
                Weekend {counts.WEEKEND}
              </span>
              <span>
                <span className="lms-month__dot" style={{ background: '#cc3300' }} />
                Holiday {counts.HOLIDAY}
              </span>
              <span>
                <span className="lms-month__dot" style={{ background: '#1f9d55' }} />
                My leave {myLeaveCounts.APPROVED}
              </span>
              <span>
                <span className="lms-month__dot" style={{ background: '#f79020' }} />
                Pending {myLeaveCounts.PENDING}
              </span>
              <span className="ms-auto lms-month__charge">
                Chargeable this month:{' '}
                <strong>{Number(month?.summary?.chargeable_days ?? 0).toFixed(2)}</strong>
              </span>
            </div>

            <div className="lms-month">
              {WEEKDAYS.map((label, index) => (
                <div
                  className={`lms-month__dow${weekendSet.has(index) ? ' is-weekend' : ''}`}
                  key={label}
                >
                  {label}
                </div>
              ))}

              {cells.map((day, index) => {
                if (day === null) {
                  return <div className="lms-month__cell is-empty" key={`blank-${index}`} />
                }
                const dayIso = isoForDay(day)
                const entry = byDate[dayIso]
                const kind = entry?.kind ?? 'WORKING'
                const titles = holidayTitles[dayIso] ?? []
                const leave = myLeave[dayIso]
                const isToday = dayIso === todayIso
                return (
                  <div
                    key={dayIso}
                    className={[
                      'lms-month__cell',
                      kind === 'WEEKEND' ? 'is-weekend' : '',
                      kind === 'HOLIDAY' ? 'is-holiday' : '',
                      isToday ? 'is-today' : '',
                      leave?.status === 'APPROVED' ? 'is-leave-approved' : '',
                      leave?.status === 'PENDING' ? 'is-leave-pending' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    title={
                      [
                        titles.map((row) => row.title).join(', '),
                        leave
                          ? `${leave.status === 'APPROVED' ? 'Leave' : 'Pending leave'}: ${leave.label}`
                          : '',
                      ]
                        .filter(Boolean)
                        .join(' · ') || undefined
                    }
                  >
                    <span
                      className={[
                        'lms-month__num',
                        kind === 'WEEKEND' ? 'is-weekend' : '',
                        kind === 'HOLIDAY' ? 'is-holiday' : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                    >
                      {day}
                    </span>
                    {titles.slice(0, 2).map((row) => (
                      <span
                        key={row.id}
                        className={`lms-month__tag${row.type === 'OPTIONAL' ? ' is-optional' : ''}`}
                      >
                        {row.title}
                      </span>
                    ))}
                  </div>
                )
              })}
            </div>
          </>
        )}
      </Card.Body>
    </Card>
  )
}
