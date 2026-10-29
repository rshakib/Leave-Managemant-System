import { useEffect, useMemo, useRef, useState } from 'react'

import Icon from './Icon.jsx'

// A date input with a popup calendar, built here so the project stays free of
// extra dependencies. The value is always a "YYYY-MM-DD" string (or "").

const WEEKDAYS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

function pad(value) {
  return String(value).padStart(2, '0')
}

function toIso(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function parseIso(value) {
  if (!value) return null
  const parts = String(value).split('-').map(Number)
  if (parts.length !== 3 || parts.some((part) => Number.isNaN(part))) return null
  const [year, month, day] = parts
  return new Date(year, month - 1, day)
}

function pretty(value) {
  const date = parseIso(value)
  if (!date) return ''
  return `${date.getDate()} ${MONTHS[date.getMonth()]} ${date.getFullYear()}`
}

export default function DateField({
  id,
  value,
  onChange,
  min,
  max,
  placeholder = 'Pick a date',
  disabled = false,
}) {
  const [open, setOpen] = useState(false)
  // "Today" is read once through an initialiser, never during render.
  const [todayIso] = useState(() => toIso(new Date()))
  const [view, setView] = useState(() => {
    const date = parseIso(value) ?? new Date()
    return { year: date.getFullYear(), month: date.getMonth() }
  })
  const root = useRef(null)

  // Follow the value when it changes from outside (for example "use today").
  useEffect(() => {
    if (!open) return
    const date = parseIso(value)
    if (date) setView({ year: date.getFullYear(), month: date.getMonth() })
  }, [value, open])

  useEffect(() => {
    if (!open) return undefined
    const onPointerDown = (event) => {
      if (root.current && !root.current.contains(event.target)) setOpen(false)
    }
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])


  const cells = useMemo(() => {
    const first = new Date(view.year, view.month, 1)
    const offset = first.getDay() // 0 = Sunday, matching the backend
    const daysInMonth = new Date(view.year, view.month + 1, 0).getDate()
    const grid = Array.from({ length: offset }, () => null)
    for (let day = 1; day <= daysInMonth; day += 1) {
      grid.push(day)
    }
    return grid
  }, [view])

  const shift = (delta) => {
    setView((current) => {
      const next = new Date(current.year, current.month + delta, 1)
      return { year: next.getFullYear(), month: next.getMonth() }
    })
  }

  const disabledDay = (isoValue) =>
    (min && isoValue < min) || (max && isoValue > max)

  const pick = (day) => {
    const isoValue = toIso(new Date(view.year, view.month, day))
    if (disabledDay(isoValue)) return
    onChange(isoValue)
    setOpen(false)
  }

  return (
    <div className="lms-datefield" ref={root}>
      <button
        type="button"
        id={id}
        className={`lms-datefield__control${value ? '' : ' is-empty'}${disabled ? ' is-disabled' : ''}`}
        onClick={() => !disabled && setOpen((current) => !current)}
        aria-haspopup="dialog"
        aria-expanded={open}
        disabled={disabled}
      >
        <Icon name="calendar" size={16} />
        <span>{value ? pretty(value) : placeholder}</span>
      </button>
      {open && (
        <div className="lms-calendar" role="dialog" aria-label="Choose a date">
          <div className="lms-calendar__head">
            <button
              type="button"
              className="lms-calendar__nav"
              onClick={() => shift(-1)}
              aria-label="Previous month"
            >
              ‹
            </button>
            <div className="lms-calendar__title">
              {MONTHS[view.month]} {view.year}
            </div>
            <button
              type="button"
              className="lms-calendar__nav"
              onClick={() => shift(1)}
              aria-label="Next month"
            >
              ›
            </button>
          </div>

          <div className="lms-calendar__grid">
            {WEEKDAYS.map((label) => (
              <div className="lms-calendar__weekday" key={label}>
                {label}
              </div>
            ))}
            {cells.map((day, index) => {
              if (day === null) {
                return <div key={`blank-${index}`} />
              }
              const isoValue = toIso(new Date(view.year, view.month, day))
              const isSelected = isoValue === value
              const isToday = isoValue === todayIso
              const isDisabled = disabledDay(isoValue)
              return (
                <button
                  type="button"
                  key={isoValue}
                  className={[
                    'lms-calendar__day',
                    isSelected ? 'is-selected' : '',
                    isToday ? 'is-today' : '',
                    isDisabled ? 'is-disabled' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  onClick={() => pick(day)}
                  disabled={isDisabled}
                >
                  {day}
                </button>
              )
            })}
          </div>

          <div className="lms-calendar__footer">
            <button
              type="button"
              className="btn btn-sm btn-outline-secondary"
              onClick={() => {
                onChange(todayIso)
                setOpen(false)
              }}
              disabled={disabledDay(todayIso)}
            >
              Today
            </button>
            <button
              type="button"
              className="btn btn-sm btn-outline-secondary"
              onClick={() => {
                onChange('')
                setOpen(false)
              }}
            >
              Clear
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
