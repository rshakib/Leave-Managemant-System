import { useEffect, useState } from 'react'
import { Button, Col, Form } from 'react-bootstrap'

/**
 * Reusable DateFilter component supporting both Single Date and Date Range filtering.
 *
 * @param {string} dateFrom - ISO string "YYYY-MM-DD" or ""
 * @param {string} dateTo - ISO string "YYYY-MM-DD" or ""
 * @param {function} onChange - ({ dateFrom, dateTo }) => void
 * @param {string} size - Bootstrap input size, e.g. "sm" (default "sm")
 * @param {boolean} showLabels - Whether to show input labels above inputs
 * @param {string} label - Label for the mode select (default "Date filter")
 */
export default function DateFilter({
  dateFrom = '',
  dateTo = '',
  onChange,
  size = 'sm',
  showLabels = true,
  label = 'Date filter',
}) {
  const [mode, setMode] = useState(() => {
    if (dateFrom && dateTo && dateFrom === dateTo) return 'single'
    return 'range'
  })

  // Synchronise mode if dateFrom / dateTo are externally reset to single or cleared
  useEffect(() => {
    if (dateFrom && dateTo && dateFrom === dateTo) {
      setMode('single')
    }
  }, [dateFrom, dateTo])

  const handleModeChange = (newMode) => {
    setMode(newMode)
    if (newMode === 'single') {
      const single = dateFrom || dateTo || ''
      onChange({ dateFrom: single, dateTo: single })
    }
  }

  const handleSingleDateChange = (val) => {
    onChange({ dateFrom: val, dateTo: val })
  }

  const handleFromChange = (val) => {
    onChange({ dateFrom: val, dateTo })
  }

  const handleToChange = (val) => {
    onChange({ dateFrom, dateTo: val })
  }

  const handleClear = () => {
    onChange({ dateFrom: '', dateTo: '' })
  }

  const hasValue = Boolean(dateFrom || dateTo)

  return (
    <>
      <Col md="auto" sm={6} xs={12}>
        {showLabels && <Form.Label className="small text-muted mb-1">{label}</Form.Label>}
        <Form.Select
          size={size}
          value={mode}
          onChange={(event) => handleModeChange(event.target.value)}
          aria-label="Date filter mode"
        >
          <option value="range">Date Range</option>
          <option value="single">Single Date</option>
        </Form.Select>
      </Col>

      {mode === 'single' ? (
        <Col md="auto" sm={6} xs={12}>
          {showLabels && <Form.Label className="small text-muted mb-1">Date</Form.Label>}
          <div className="d-flex align-items-center gap-1">
            <Form.Control
              size={size}
              type="date"
              value={dateFrom || ''}
              onChange={(event) => handleSingleDateChange(event.target.value)}
              aria-label="Single date filter"
            />
            {hasValue && (
              <Button
                variant="outline-secondary"
                size={size}
                onClick={handleClear}
                title="Clear date"
              >
                ✕
              </Button>
            )}
          </div>
        </Col>
      ) : (
        <>
          <Col md="auto" sm={6} xs={12}>
            {showLabels && <Form.Label className="small text-muted mb-1">From</Form.Label>}
            <Form.Control
              size={size}
              type="date"
              value={dateFrom || ''}
              onChange={(event) => handleFromChange(event.target.value)}
              aria-label="Date range from"
            />
          </Col>
          <Col md="auto" sm={6} xs={12}>
            {showLabels && <Form.Label className="small text-muted mb-1">To</Form.Label>}
            <div className="d-flex align-items-center gap-1">
              <Form.Control
                size={size}
                type="date"
                value={dateTo || ''}
                onChange={(event) => handleToChange(event.target.value)}
                aria-label="Date range to"
              />
              {hasValue && (
                <Button
                  variant="outline-secondary"
                  size={size}
                  onClick={handleClear}
                  title="Clear dates"
                >
                  ✕
                </Button>
              )}
            </div>
          </Col>
        </>
      )}
    </>
  )
}

