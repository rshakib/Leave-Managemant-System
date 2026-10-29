import { useCallback, useEffect, useState } from 'react'
import { Alert, Badge, Button, Card, Col, Form, Row, Spinner, Table } from 'react-bootstrap'
import { Link, useNavigate } from 'react-router-dom'

import api, { errorMessage } from '../api/client'
import DateField from '../components/DateField.jsx'
import DayPreview from '../components/DayPreview'
import NoOptions from '../components/NoOptions.jsx'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

const DAY_TYPES = [
  { value: 'FULL_DAY', label: 'Full day' },
  { value: 'FIRST_HALF', label: 'First half (half day)' },
  { value: 'SECOND_HALF', label: 'Second half (half day)' },
]

function days(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : '0.00'
}

export default function LeaveRequestFormPage() {
  const navigate = useNavigate()

  const [leaveTypes, setLeaveTypes] = useState([])
  const [availableByType, setAvailableByType] = useState({})
  const [activeYear, setActiveYear] = useState(null)
  const [approvers, setApprovers] = useState([])
  const [loadingTypes, setLoadingTypes] = useState(true)
  const [error, setError] = useState('')

  const [leaveTypeId, setLeaveTypeId] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [dayType, setDayType] = useState('FULL_DAY')
  const [reason, setReason] = useState('')

  const [check, setCheck] = useState(null)
  const [checking, setChecking] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const loadLeaveTypes = useCallback(async () => {
    try {
      const [balances, types, years, approverList] = await Promise.all([
        api.get('/leave-balances/me'),
        api.get('/leave-types'),
        api.get('/leave-years'),
        api.get('/approvers/me'),
      ])
      setActiveYear(years.data.find((year) => year.is_active) ?? null)
      setApprovers(approverList.data)
      const mine = new Set(balances.data.map((row) => row.leave_type_id))
      setLeaveTypes(types.data.filter((type) => mine.has(type.id)))
      setAvailableByType(
        Object.fromEntries(
          balances.data.map((row) => [String(row.leave_type_id), row.available]),
        ),
      )
    } catch (err) {
      setError(errorMessage(err, 'Could not load your leave types.'))
    } finally {
      setLoadingTypes(false)
    }
  }, [])

  useEffect(() => {
    loadLeaveTypes()
  }, [loadLeaveTypes])

  useAutoRefresh(loadLeaveTypes)

  const selectedType = leaveTypes.find(
    (type) => String(type.id) === String(leaveTypeId),
  )
  const halfDayAllowed = Boolean(selectedType?.allow_half_day)
  const selectedAvailable = selectedType
    ? availableByType[String(selectedType.id)]
    : undefined

  // Live preview: debounced 400 ms, and stale responses are ignored.
  useEffect(() => {
    if (!leaveTypeId || !startDate || !endDate) {
      setCheck(null)
      return undefined
    }
    let cancelled = false
    const timer = setTimeout(async () => {
      setChecking(true)
      try {
        const { data } = await api.get('/leave-requests/check', {
          params: {
            leave_type_id: leaveTypeId,
            start_date: startDate,
            end_date: endDate,
            day_type: dayType,
          },
        })
        if (!cancelled) setCheck(data)
      } catch (err) {
        if (!cancelled) setError(errorMessage(err, 'Could not check the request.'))
      } finally {
        if (!cancelled) setChecking(false)
      }
    }, 400)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [leaveTypeId, startDate, endDate, dayType])

  const onLeaveTypeChange = (value) => {
    setLeaveTypeId(value)
    const typeObj = leaveTypes.find((t) => String(t.id) === String(value))
    if (typeObj && !typeObj.allow_half_day && dayType !== 'FULL_DAY') {
      setDayType('FULL_DAY')
    }
  }

  const onStartChange = (value) => {
    setStartDate(value)
    if (dayType !== 'FULL_DAY') setEndDate(value)
  }

  const onEndChange = (value) => {
    setEndDate(value)
    if (dayType !== 'FULL_DAY' && value && value !== startDate) setDayType('FULL_DAY')
  }

  const onDayTypeChange = (value) => {
    setDayType(value)
    if (value !== 'FULL_DAY') {
      if (startDate) {
        setEndDate(startDate)
      } else if (endDate) {
        setStartDate(endDate)
      }
    }
  }

  const submit = async (event) => {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      const formData = new FormData()
      formData.append('leave_type_id', leaveTypeId)
      formData.append('start_date', startDate)
      formData.append('end_date', endDate)
      formData.append('day_type', dayType)
      formData.append('reason', reason)

      const { data } = await api.post('/leave-requests', formData)
      navigate(`/leave-requests/${data.id}`)
    } catch (err) {
      setError(errorMessage(err, 'Could not submit the request.'))
    } finally {
      setSubmitting(false)
    }
  }

  const blocked = checking || !check || !check.can_submit || submitting
  const problemCount = check?.problems?.length ?? 0

  const blockedReason = submitting
    ? 'Submitting…'
    : checking
      ? 'Checking the dates…'
      : !leaveTypeId
        ? 'Choose a leave type to start.'
        : !startDate || !endDate
          ? 'Pick a start and an end date.'
          : problemCount > 0
            ? `${problemCount} thing(s) need fixing — see the panel on the right.`
            : ''

  return (
    <>
      <div className="mb-3">
        <h1 className="h3 mb-1">Request leave</h1>
        <p className="text-muted mb-0">
          Pick a leave type and the dates — the panel updates as you choose.
        </p>
      </div>

      {error && (
        <Alert variant="danger" dismissible onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      {loadingTypes ? (
        <div className="text-center py-5">
          <Spinner animation="border" role="status" />
        </div>
      ) : leaveTypes.length === 0 ? (
        <Card>
          <Card.Body>
            <Card.Title className="h5 mb-1">You cannot request leave yet</Card.Title>
            <p className="text-muted mb-3">
              The form is hidden until the setup below is finished.
            </p>
            <ul className="mb-3">
              {!activeYear && (
                <li className="mb-2">
                  <strong>No active leave year.</strong> Assignments and balances only
                  exist inside an active year. <Link to="/leave-years">Leave years</Link>
                </li>
              )}
              <li className="mb-2">
                <strong>
                  No leave type is assigned to you
                  {activeYear ? ` for ${activeYear.name}` : ''}.
                </strong>
              </li>
              {approvers.length === 0 && (
                <li>
                  <strong>No approver is assigned to you.</strong>
                </li>
              )}
            </ul>
            <Button size="sm" variant="outline-secondary" onClick={loadLeaveTypes}>
              Reload
            </Button>
          </Card.Body>
        </Card>
      ) : (
        <>
          {approvers.length === 0 && (
            <Alert variant="warning">
              You have no approver assigned, so the request would be refused. Ask an
              admin to set one on the Approvers page.
            </Alert>
          )}

          <Row className="g-3">
            {/* --- the form ------------------------------------------------ */}
            <Col lg={5}>
              <Card>
                <Card.Body>
                  <Form onSubmit={submit}>
                    <Form.Group className="mb-3" controlId="requestType">
                      <Form.Label>Leave type</Form.Label>
                      <Form.Select
                        value={leaveTypeId}
                        onChange={(event) => onLeaveTypeChange(event.target.value)}
                        required
                      >
                        <option value="">Select a leave type…</option>
                        <NoOptions
                          when={leaveTypes.length === 0}
                          label="No leave types are assigned to you yet"
                        />
                        {leaveTypes.map((type) => (
                          <option key={type.id} value={type.id}>
                            {type.code} — {type.name}
                          </option>
                        ))}
                      </Form.Select>
                      {selectedType && selectedAvailable !== undefined && (
                        <Form.Text className="text-muted">
                          {days(selectedAvailable)} day(s) available for{' '}
                          {activeYear?.name ?? 'this year'}
                        </Form.Text>
                      )}
                    </Form.Group>

                    <Row className="g-2 mb-3">
                      <Col>
                        <Form.Label>Start date</Form.Label>
                        <DateField
                          id="requestStart"
                          value={startDate}
                          max={dayType === 'FULL_DAY' ? (endDate || undefined) : undefined}
                          onChange={onStartChange}
                        />
                      </Col>
                      <Col>
                        <Form.Label>
                          End date {dayType !== 'FULL_DAY' && <span className="text-muted small">(Single day)</span>}
                        </Form.Label>
                        <DateField
                          id="requestEnd"
                          value={dayType !== 'FULL_DAY' ? startDate : endDate}
                          min={startDate || undefined}
                          disabled={dayType !== 'FULL_DAY'}
                          onChange={onEndChange}
                        />
                      </Col>
                    </Row>

                    <Form.Group className="mb-3" controlId="requestDayType">
                      <Form.Label>Day type</Form.Label>
                      <Form.Select
                        value={dayType}
                        onChange={(event) => onDayTypeChange(event.target.value)}
                        disabled={!selectedType || !halfDayAllowed}
                      >
                        {DAY_TYPES.filter(
                          (option) =>
                            option.value === 'FULL_DAY' || halfDayAllowed,
                        ).map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </Form.Select>
                      <Form.Text className="text-muted">
                        {!selectedType
                          ? 'Select a leave type above to see day type options.'
                          : halfDayAllowed
                            ? dayType !== 'FULL_DAY'
                              ? 'Half day selected (start date and end date are the same single day).'
                              : 'Half days are allowed for this leave type.'
                            : 'This leave type does not allow half days.'}
                      </Form.Text>
                    </Form.Group>

                    <Form.Group className="mb-3" controlId="requestReason">
                      <Form.Label>Reason</Form.Label>
                      <Form.Control
                        as="textarea"
                        rows={3}
                        value={reason}
                        onChange={(event) => setReason(event.target.value)}
                        maxLength={1000}
                        placeholder="Why do you need this leave?"
                        required
                      />
                      <Form.Text className="text-muted">
                        {reason.length}/1000 characters
                      </Form.Text>
                    </Form.Group>

                    <div className="lms-submit-bar">
                      {blockedReason && (
                        <div className="small text-muted mb-2">{blockedReason}</div>
                      )}
                      <Button
                        type="submit"
                        size="lg"
                        className="w-100"
                        disabled={blocked}
                      >
                        {submitting ? 'Submitting…' : 'Submit request'}
                      </Button>
                    </div>
                  </Form>
                </Card.Body>
              </Card>
            </Col>

            {/* --- the live check ----------------------------------------- */}
            <Col lg={7}>
              <div className="lms-panel-sticky">
                {check ? (
                  <>
                    <Card className="mb-3">
                      <Card.Body className="d-flex flex-wrap align-items-center gap-3">
                        <div>
                          <div className="lms-summary__label">Chargeable days</div>
                          <div className="lms-balance__value mb-0">
                            {days(check.chargeable_days)}
                            <span>days</span>
                          </div>
                        </div>
                        <div className="ms-auto text-end">
                          <div className="lms-summary__label">Status</div>
                          {check.can_submit ? (
                            <Badge bg="success">Ready to submit</Badge>
                          ) : (
                            <Badge bg="warning" text="dark">
                              Needs attention
                            </Badge>
                          )}
                        </div>
                      </Card.Body>
                    </Card>

                    {problemCount > 0 && (
                      <Alert variant="warning">
                        <strong>This request cannot be submitted yet:</strong>
                        <ul className="mb-0 mt-2">
                          {check.problems.map((problem) => (
                            <li key={problem.code}>{problem.message}</li>
                          ))}
                        </ul>
                      </Alert>
                    )}

                    {check.balances?.length > 0 && (
                      <Card className="mb-3">
                        <Card.Header>Balance impact</Card.Header>
                        <Card.Body className="p-0">
                          <Table size="sm" className="mb-0">
                            <thead>
                              <tr>
                                <th>Leave year</th>
                                <th className="text-end">Available now</th>
                                <th className="text-end">This request</th>
                                <th className="text-end">After</th>
                              </tr>
                            </thead>
                            <tbody>
                              {check.balances.map((row) => (
                                <tr key={row.leave_year_id}>
                                  <td>{row.leave_year_name}</td>
                                  <td className="text-end">
                                    {days(row.available_before)}
                                  </td>
                                  <td className="text-end">−{days(row.days)}</td>
                                  <td className="text-end fw-semibold">
                                    {days(row.available_after)}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </Table>
                        </Card.Body>
                      </Card>
                    )}

                    <DayPreview preview={check} />
                  </>
                ) : (
                  <Card>
                    <Card.Body className="text-center py-5">
                      <div className="text-muted mb-2">
                        <strong>Nothing to check yet.</strong>
                      </div>
                      <div className="text-muted small">
                        Choose a leave type and a date range — the chargeable days, your
                        remaining balance and the day-by-day breakdown appear here.
                      </div>
                    </Card.Body>
                  </Card>
                )}
              </div>
            </Col>
          </Row>
        </>
      )}
    </>
  )
}
