import { useCallback, useEffect, useState } from 'react'
import { Alert, Badge, Button, Form, Modal, Spinner, Table } from 'react-bootstrap'

import api, { errorMessage } from '../api/client'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

const EMPTY_FORM = { name: '', start_date: '', end_date: '' }
const PREVIEW_PAGE = 50
const LOG_PAGE = 25

function days(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : '-'
}

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

export default function LeaveYearsPage() {
  const [years, setYears] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState(null)

  const [showCreate, setShowCreate] = useState(false)
  const [showRange, setShowRange] = useState(false)
  const [rangeStart, setRangeStart] = useState(
    () => `${new Date().getFullYear() + 1}-01-01`,
  )
  const [rangeEnd, setRangeEnd] = useState(
    () => `${new Date().getFullYear() + 1}-12-31`,
  )
  const [rangeCount, setRangeCount] = useState(3)
  const [rangeBusy, setRangeBusy] = useState(false)
  const [rangeLog, setRangeLog] = useState([])
  const [showEdit, setShowEdit] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [saving, setSaving] = useState(false)

  // Closing wizard
  const [closing, setClosing] = useState(null)
  const [step, setStep] = useState(1)
  const [preview, setPreview] = useState(null)
  const [previewOffset, setPreviewOffset] = useState(0)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [doingClose, setDoingClose] = useState(false)
  const [result, setResult] = useState(null)

  // Carry-forward log
  const [logYear, setLogYear] = useState(null)
  const [log, setLog] = useState(null)
  const [logOffset, setLogOffset] = useState(0)

  const load = useCallback(async () => {
    try {
      const { data } = await api.get('/leave-years')
      setYears(data)
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load leave years.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // Live view: reload after any change, when the tab returns, or on the poll.
  useAutoRefresh(() => {
      load()
    })

  const openCreate = () => {
    setForm(EMPTY_FORM)
    setError('')
    setShowCreate(true)
  }

  const openEdit = (year) => {
    setEditing(year)
    setForm({
      name: year.name,
      start_date: year.start_date,
      end_date: year.end_date,
    })
    setError('')
    setShowEdit(true)
  }

  const createYear = async (event) => {
    event.preventDefault()
    setSaving(true)
    try {
      await api.post('/leave-years', form)
      setShowCreate(false)
      await load()
    } catch (err) {
      setError(errorMessage(err, 'Could not create the leave year.'))
    } finally {
      setSaving(false)
    }
  }

  // "2027-02-28" + 1 year -> "2028-02-29" (a 29 Feb is clamped to 28 Feb)
  const shiftDate = (isoDate, years) => {
    const [year, month, day] = isoDate.split('-').map(Number)
    const shifted = new Date(Date.UTC(year + years, month - 1, day))
    if (shifted.getUTCMonth() !== month - 1) shifted.setUTCDate(0)
    return shifted.toISOString().slice(0, 10)
  }

  const rangePreview = (() => {
    const count = Number(rangeCount)
    if (!rangeStart || !rangeEnd || !Number.isInteger(count) || count < 1 || count > 10) {
      return []
    }
    return Array.from({ length: count }, (_, index) => {
      const start = shiftDate(rangeStart, index)
      return { name: start.slice(0, 4), start_date: start, end_date: shiftDate(rangeEnd, index) }
    })
  })()

  const createRange = async (event) => {
    event.preventDefault()
    const count = Number(rangeCount)
    if (!rangeStart || !rangeEnd) {
      setRangeLog(['Pick the start date and the end date of the first year.'])
      return
    }
    if (rangeStart > rangeEnd) {
      setRangeLog(['The first year must start on or before the day it ends.'])
      return
    }
    if (!Number.isInteger(count) || count < 1 || count > 10) {
      setRangeLog(['How many years? Enter a whole number from 1 to 10.'])
      return
    }

    setRangeBusy(true)
    const lines = []
    for (const year of rangePreview) {
      try {
        await api.post('/leave-years', year)
        lines.push(`${year.name}: ${year.start_date} to ${year.end_date} — created (inactive, activate one)`)
      } catch (err) {
        lines.push(`${year.name}: skipped — ${errorMessage(err, 'could not create')}`)
      }
    }
    setRangeLog(lines)
    setRangeBusy(false)
    await load()
  }

  const updateYear = async (event) => {
    event.preventDefault()
    setSaving(true)
    try {
      await api.patch(`/leave-years/${editing.id}`, form)
      setShowEdit(false)
      await load()
    } catch (err) {
      setError(errorMessage(err, 'Could not update the leave year.'))
    } finally {
      setSaving(false)
    }
  }

  const activate = async (year) => {
    setError('')
    setBusyId(year.id)
    try {
      await api.post(`/leave-years/${year.id}/activate`)
      await load()
    } catch (err) {
      setError(errorMessage(err, 'Could not activate the leave year.'))
    } finally {
      setBusyId(null)
    }
  }

  const loadPreview = useCallback(async (yearId, offset) => {
    setPreviewLoading(true)
    try {
      const { data } = await api.get(
        `/leave-years/${yearId}/closing-preview`,
        { params: { offset, limit: PREVIEW_PAGE } },
      )
      setPreview(data)
    } catch (err) {
      setError(errorMessage(err, 'Could not load the closing preview.'))
      setClosing(null)
    } finally {
      setPreviewLoading(false)
    }
  }, [])

  const openClosing = (year) => {
    setClosing(year)
    setStep(1)
    setPreview(null)
    setPreviewOffset(0)
    setConfirmText('')
    setResult(null)
    setError('')
    loadPreview(year.id, 0)
  }

  const doClose = async () => {
    setDoingClose(true)
    setError('')
    try {
      const { data } = await api.post(`/leave-years/${closing.id}/close`, {
        confirm_name: confirmText,
        expected_fingerprint: preview.fingerprint,
      })
      setResult(data)
      await load()
    } catch (err) {
      setError(errorMessage(err, 'Could not close the leave year.'))
    } finally {
      setDoingClose(false)
    }
  }

  const openLog = async (year, offset) => {
    setLogYear(year)
    setLogOffset(offset)
    setLog(null)
    try {
      const { data } = await api.get(`/leave-years/${year.id}/carry-forwards`, {
        params: { offset, limit: LOG_PAGE },
      })
      setLog(data)
    } catch (err) {
      setError(errorMessage(err, 'Could not load the carry-forward log.'))
      setLogYear(null)
    }
  }

  const formBody = (
    <>
      <Form.Group className="mb-3" controlId="yearName">
        <Form.Label>Name</Form.Label>
        <Form.Control
          value={form.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
          placeholder="2026"
          maxLength={20}
          required
        />
      </Form.Group>
      <Form.Group className="mb-3" controlId="yearStart">
        <Form.Label>Start date</Form.Label>
        <Form.Control
          type="date"
          value={form.start_date}
          onChange={(event) =>
            setForm({ ...form, start_date: event.target.value })
          }
          required
        />
      </Form.Group>
      <Form.Group controlId="yearEnd">
        <Form.Label>End date</Form.Label>
        <Form.Control
          type="date"
          value={form.end_date}
          onChange={(event) => setForm({ ...form, end_date: event.target.value })}
          required
        />
      </Form.Group>
    </>
  )

  const blockers = preview?.blockers ?? []
  const warnings = preview?.warnings ?? []

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h1 className="h3 mb-0">Leave years</h1>
        <div className="d-flex flex-wrap gap-2">
          <Button onClick={openCreate}>Add leave year</Button>
          <Button
            variant="outline-primary"
            onClick={() => {
              setRangeLog([])
              setShowRange(true)
            }}
          >
            Add several years
          </Button>
        </div>
      </div>

      {error && (
        <Alert variant="danger" dismissible onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      {loading ? (
        <div className="text-center py-5">
          <Spinner animation="border" role="status" />
        </div>
      ) : years.length === 0 ? (
        <div className="empty-state">
          No leave years yet. Click "Add leave year" to create the first one.
        </div>
      ) : (
        <Table striped bordered hover responsive>
          <thead>
            <tr>
              <th>Name</th>
              <th>Start</th>
              <th>End</th>
              <th>Status</th>
              <th className="text-end">Actions</th>
            </tr>
          </thead>
          <tbody>
            {years.map((year) => {
              const ended = year.end_date < todayIso()
              return (
                <tr key={year.id}>
                  <td>{year.name}</td>
                  <td>{year.start_date}</td>
                  <td>{year.end_date}</td>
                  <td>
                    {year.is_active && (
                      <Badge bg="success" className="me-1">
                        Active
                      </Badge>
                    )}
                    {year.is_closed && <Badge bg="dark">Closed</Badge>}
                    {!year.is_active && !year.is_closed && (
                      <Badge bg="secondary">Inactive</Badge>
                    )}
                    {year.is_closed && year.closed_at && (
                      <div className="text-muted small mt-1">
                        Closed on {new Date(year.closed_at).toLocaleDateString()}
                        {year.closed_by_name ? ` by ${year.closed_by_name}` : ''}
                      </div>
                    )}
                  </td>
                  <td className="text-end">
                    <Button
                      size="sm"
                      variant="outline-secondary"
                      className="me-2"
                      onClick={() => openEdit(year)}
                    >
                      Edit
                    </Button>
                    <Button
                      size="sm"
                      variant="outline-success"
                      className="me-2"
                      disabled={
                        year.is_active || year.is_closed || busyId === year.id
                      }
                      onClick={() => activate(year)}
                    >
                      Activate
                    </Button>
                    {year.is_closed ? (
                      <Button
                        size="sm"
                        variant="outline-dark"
                        onClick={() => openLog(year, 0)}
                      >
                        Carry-forward log
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline-danger"
                        disabled={!ended}
                        onClick={() => openClosing(year)}
                      >
                        Close year
                      </Button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </Table>
      )}

      <Modal show={showRange} onHide={() => setShowRange(false)} centered>
        <Form onSubmit={createRange}>
          <Modal.Header closeButton>
            <Modal.Title>Add several leave years</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <p className="text-muted small">
              Pick the dates of the <strong>first</strong> year and how many years you
              need. Every following year repeats the same dates, one year later (1 Jan
              to 31 Dec stays 1 Jan to 31 Dec). An existing or overlapping year is
              skipped.
            </p>
            <div className="d-flex gap-2">
              <Form.Group className="flex-fill" controlId="rangeStart">
                <Form.Label>First start date</Form.Label>
                <Form.Control
                  type="date"
                  value={rangeStart}
                  onChange={(event) => setRangeStart(event.target.value)}
                  required
                />
              </Form.Group>
              <Form.Group className="flex-fill" controlId="rangeEnd">
                <Form.Label>First end date</Form.Label>
                <Form.Control
                  type="date"
                  value={rangeEnd}
                  onChange={(event) => setRangeEnd(event.target.value)}
                  required
                />
              </Form.Group>
            </div>
            <Form.Group className="mt-3" controlId="rangeCount">
              <Form.Label>How many years</Form.Label>
              <Form.Control
                type="number"
                min="1"
                max="10"
                value={rangeCount}
                onChange={(event) => setRangeCount(event.target.value)}
                required
              />
            </Form.Group>
            {rangePreview.length > 0 && (
              <div className="small text-muted mt-3">
                <div className="fw-semibold">Will be created:</div>
                {rangePreview.map((year) => (
                  <div key={year.name}>
                    {year.name}: {year.start_date} → {year.end_date}
                  </div>
                ))}
              </div>
            )}
            {rangeLog.length > 0 && (
              <Alert variant="secondary" className="mt-3 small">
                {rangeLog.map((line) => (
                  <div key={line}>{line}</div>
                ))}
              </Alert>
            )}
          </Modal.Body>
          <Modal.Footer>
            <Button variant="secondary" onClick={() => setShowRange(false)}>
              Close
            </Button>
            <Button type="submit" disabled={rangeBusy}>
              {rangeBusy ? 'Creating…' : 'Create the years'}
            </Button>
          </Modal.Footer>
        </Form>
      </Modal>

      <Modal show={showCreate} onHide={() => setShowCreate(false)} centered>
        <Form onSubmit={createYear}>
          <Modal.Header closeButton>
            <Modal.Title>Add leave year</Modal.Title>
          </Modal.Header>
          <Modal.Body>{formBody}</Modal.Body>
          <Modal.Footer>
            <Button variant="secondary" onClick={() => setShowCreate(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? 'Saving...' : 'Save'}
            </Button>
          </Modal.Footer>
        </Form>
      </Modal>

      <Modal show={showEdit} onHide={() => setShowEdit(false)} centered>
        <Form onSubmit={updateYear}>
          <Modal.Header closeButton>
            <Modal.Title>Edit leave year</Modal.Title>
          </Modal.Header>
          <Modal.Body>{formBody}</Modal.Body>
          <Modal.Footer>
            <Button variant="secondary" onClick={() => setShowEdit(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? 'Saving...' : 'Save'}
            </Button>
          </Modal.Footer>
        </Form>
      </Modal>

      {/* --- closing wizard --------------------------------------------- */}
      <Modal
        show={closing !== null}
        onHide={() => setClosing(null)}
        size="lg"
        centered
      >
        <Modal.Header closeButton>
          <Modal.Title>
            Close leave year {closing?.name}
            {result ? ' — done' : ` — step ${step} of 2`}
          </Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {result ? (
            <>
              <Alert variant="success">
                Leave year <strong>{result.leave_year_name}</strong> is closed.
              </Alert>
              <ul className="mb-0">
                <li>
                  {result.rows_carried} row(s) carried days forward,{' '}
                  {result.rows_forfeited_only} forfeited only
                </li>
                <li>
                  {days(result.total_carried)} day(s) carried,{' '}
                  {days(result.total_forfeited)} day(s) forfeited
                </li>
                <li>
                  {result.balances_created} balance row(s) created,{' '}
                  {result.balances_updated} updated
                </li>
                <li>{result.skipped_inactive} inactive employee(s) skipped</li>
                <li>
                  Active leave year is now{' '}
                  <strong>{result.active_year_name ?? 'none'}</strong>
                </li>
              </ul>
            </>
          ) : step === 1 ? (
            previewLoading ? (
              <div className="text-center py-4">
                <Spinner animation="border" role="status" />
              </div>
            ) : (
              <>
                {blockers.map((blocker) => (
                  <Alert key={blocker.code} variant="danger" className="py-2">
                    {blocker.message}
                  </Alert>
                ))}
                {warnings.map((warning) => (
                  <Alert key={warning} variant="warning" className="py-2">
                    {warning}
                  </Alert>
                ))}
                {blockers.length === 0 && (
                  <Alert variant="light" className="py-2">
                    {preview?.fingerprint?.rows ?? 0} row(s) will be written
                    {preview?.next_leave_year_name
                      ? ` into ${preview.next_leave_year_name}`
                      : ''}
                    .
                  </Alert>
                )}

                <h6>Totals per leave type</h6>
                <Table size="sm" bordered>
                  <thead>
                    <tr>
                      <th>Leave type</th>
                      <th className="text-end">Employees</th>
                      <th className="text-end">Remaining</th>
                      <th className="text-end">Carried</th>
                      <th className="text-end">Forfeited</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(preview?.totals_by_type ?? []).map((total) => (
                      <tr key={total.leave_type_id}>
                        <td>
                          {total.leave_type_code} — {total.leave_type_name}
                        </td>
                        <td className="text-end">{total.employees}</td>
                        <td className="text-end">{days(total.remaining)}</td>
                        <td className="text-end">{days(total.carried)}</td>
                        <td className="text-end">{days(total.forfeited)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>

                <h6>Rows</h6>
                <Table size="sm" bordered responsive>
                  <thead>
                    <tr>
                      <th>Employee</th>
                      <th>Leave type</th>
                      <th className="text-end">Remaining</th>
                      <th className="text-end">Carried</th>
                      <th className="text-end">Forfeited</th>
                      <th>Next year</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(preview?.rows ?? []).map((row) => (
                      <tr key={`${row.employee_id}-${row.leave_type_id}`}>
                        <td>
                          {row.employee_code} — {row.employee_name}
                        </td>
                        <td>{row.leave_type_code}</td>
                        <td className="text-end">{days(row.remaining)}</td>
                        <td className="text-end">{days(row.carried)}</td>
                        <td className="text-end">{days(row.forfeited)}</td>
                        <td>
                          {row.has_next_year_assignment ? 'assigned' : 'not assigned'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
                <div className="d-flex justify-content-between align-items-center">
                  <Button
                    size="sm"
                    variant="outline-secondary"
                    disabled={previewOffset === 0}
                    onClick={() => {
                      const next = Math.max(0, previewOffset - PREVIEW_PAGE)
                      setPreviewOffset(next)
                      loadPreview(closing.id, next)
                    }}
                  >
                    Previous
                  </Button>
                  <span className="text-muted small">
                    {previewOffset + 1}–
                    {previewOffset + (preview?.rows?.length ?? 0)} of{' '}
                    {preview?.total_rows ?? 0}
                  </span>
                  <Button
                    size="sm"
                    variant="outline-secondary"
                    disabled={
                      previewOffset + (preview?.rows?.length ?? 0) >=
                      (preview?.total_rows ?? 0)
                    }
                    onClick={() => {
                      const next = previewOffset + PREVIEW_PAGE
                      setPreviewOffset(next)
                      loadPreview(closing.id, next)
                    }}
                  >
                    Next
                  </Button>
                </div>
              </>
            )
          ) : (
            <>
              <Alert variant="danger">
                This cannot be undone. There is no "un-close" button and no undo.
                Days above the leave type's carry-forward cap are <strong>lost</strong>,
                and the balances of every employee change at once.
              </Alert>
              <p>
                Closing <strong>{closing?.name}</strong> will write{' '}
                {preview?.fingerprint?.rows ?? 0} log row(s) and move the remaining
                days into <strong>{preview?.next_leave_year_name}</strong>.
              </p>
              <p className="mb-2">
                {closing?.is_active
                  ? `Because ${closing?.name} is the active leave year, ${preview?.next_leave_year_name} becomes the active one.`
                  : `${closing?.name} is not the active leave year, so the active year does not change.`}
              </p>
              <Form.Group controlId="confirmName">
                <Form.Label>
                  Type <code>{closing?.name}</code> to confirm
                </Form.Label>
                <Form.Control
                  value={confirmText}
                  onChange={(event) => setConfirmText(event.target.value)}
                  placeholder={closing?.name}
                  autoComplete="off"
                />
              </Form.Group>
            </>
          )}
        </Modal.Body>
        <Modal.Footer>
          {result ? (
            <Button variant="secondary" onClick={() => setClosing(null)}>
              Close
            </Button>
          ) : (
            <>
              <Button
                variant="secondary"
                onClick={() => (step === 1 ? setClosing(null) : setStep(1))}
              >
                {step === 1 ? 'Cancel' : 'Back'}
              </Button>
              {step === 1 ? (
                <Button
                  variant="danger"
                  disabled={!preview?.can_close || previewLoading}
                  onClick={() => setStep(2)}
                >
                  Continue
                </Button>
              ) : (
                <Button
                  variant="danger"
                  disabled={confirmText !== closing?.name || doingClose}
                  onClick={doClose}
                >
                  {doingClose ? 'Closing...' : `Close ${closing?.name} now`}
                </Button>
              )}
            </>
          )}
        </Modal.Footer>
      </Modal>

      {/* --- carry-forward log ------------------------------------------ */}
      <Modal
        show={logYear !== null}
        onHide={() => setLogYear(null)}
        size="lg"
        centered
      >
        <Modal.Header closeButton>
          <Modal.Title>Carry-forward log — {logYear?.name}</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {log === null ? (
            <div className="text-center py-4">
              <Spinner animation="border" role="status" />
            </div>
          ) : log.rows.length === 0 ? (
            <div className="empty-state">No carry-forward rows for this year.</div>
          ) : (
            <>
              <Table size="sm" bordered responsive>
                <thead>
                  <tr>
                    <th>Employee</th>
                    <th>Leave type</th>
                    <th className="text-end">Remaining</th>
                    <th className="text-end">Carried</th>
                    <th className="text-end">Forfeited</th>
                    <th>To</th>
                  </tr>
                </thead>
                <tbody>
                  {log.rows.map((row) => (
                    <tr key={row.id}>
                      <td>
                        {row.employee_code} — {row.employee_name}
                      </td>
                      <td>{row.leave_type_code}</td>
                      <td className="text-end">{days(row.remaining_at_close)}</td>
                      <td className="text-end">{days(row.carried_days)}</td>
                      <td className="text-end">{days(row.forfeited_days)}</td>
                      <td>{row.to_leave_year_name}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <div className="d-flex justify-content-between align-items-center">
                <Button
                  size="sm"
                  variant="outline-secondary"
                  disabled={logOffset === 0}
                  onClick={() => openLog(logYear, Math.max(0, logOffset - LOG_PAGE))}
                >
                  Previous
                </Button>
                <span className="text-muted small">
                  {logOffset + 1}–{logOffset + log.rows.length} of {log.total}
                </span>
                <Button
                  size="sm"
                  variant="outline-secondary"
                  disabled={logOffset + log.rows.length >= log.total}
                  onClick={() => openLog(logYear, logOffset + LOG_PAGE)}
                >
                  Next
                </Button>
              </div>
            </>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setLogYear(null)}>
            Close
          </Button>
        </Modal.Footer>
      </Modal>
    </>
  )
}
