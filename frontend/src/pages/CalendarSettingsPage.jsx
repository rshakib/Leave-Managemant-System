import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Col,
  Form,
  ListGroup,
  Modal,
  Row,
  Tab,
  Table,
  Tabs,
} from 'react-bootstrap'

import api, { errorMessage } from '../api/client'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

// Sunday=0 ... Saturday=6, matching the API.
const DAYS = [
  { value: 0, label: 'Sunday' },
  { value: 1, label: 'Monday' },
  { value: 2, label: 'Tuesday' },
  { value: 3, label: 'Wednesday' },
  { value: 4, label: 'Thursday' },
  { value: 5, label: 'Friday' },
  { value: 6, label: 'Saturday' },
]

const HOLIDAY_TYPES = ['PUBLIC', 'COMPANY', 'OPTIONAL']

const EMPTY_HOLIDAY = {
  mode: 'single',
  date: '',
  date_from: '',
  date_to: '',
  title: '',
  type: 'PUBLIC',
  scope: 'all',
  division_id: '',
  department_id: '',
}

function dayNames(values) {
  return DAYS.filter((day) => values.includes(day.value))
    .map((day) => day.label.slice(0, 3))
    .join(', ')
}

function DayCheckboxes({ selected, onToggle }) {
  return (
    <div>
      {DAYS.map((day) => (
        <Form.Check
          key={day.value}
          inline
          type="checkbox"
          label={day.label}
          checked={selected.includes(day.value)}
          onChange={(event) => onToggle(day.value, event.target.checked)}
        />
      ))}
    </div>
  )
}

export default function CalendarSettingsPage() {
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  // --- weekends -----------------------------------------------------------
  const [globalDays, setGlobalDays] = useState([])
  const [overrides, setOverrides] = useState([])
  const [employees, setEmployees] = useState([])
  const [savingGlobal, setSavingGlobal] = useState(false)
  const [showOverride, setShowOverride] = useState(false)
  const [overrideForm, setOverrideForm] = useState({ employee_id: '', days: [] })
  const [confirmRemove, setConfirmRemove] = useState(null)

  // --- holidays -----------------------------------------------------------
  const [leaveYears, setLeaveYears] = useState([])
  const [yearId, setYearId] = useState('')
  const [divisions, setDivisions] = useState([])
  const [departments, setDepartments] = useState([])
  const [holidays, setHolidays] = useState([])
  const [showHoliday, setShowHoliday] = useState(false)
  const [editingHoliday, setEditingHoliday] = useState(null)
  const [holidayForm, setHolidayForm] = useState(EMPTY_HOLIDAY)
  const [savingHoliday, setSavingHoliday] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(null)
  const [importFile, setImportFile] = useState(null)
  const [importErrors, setImportErrors] = useState([])
  const [importing, setImporting] = useState(false)

  const loadLookups = useCallback(async () => {
    try {
      const [years, divisionList, departmentList, employeeList] = await Promise.all([
        api.get('/leave-years'),
        api.get('/divisions'),
        api.get('/departments'),
        api.get('/employees', { params: { is_active: true } }),
      ])
      setLeaveYears(years.data)
      setDivisions(divisionList.data)
      setDepartments(departmentList.data)
      setEmployees(employeeList.data)
      setYearId(
        (current) =>
          current || String(years.data.find((year) => year.is_active)?.id ?? ''),
      )
    } catch (err) {
      setError(errorMessage(err, 'Could not load reference data.'))
    }
  }, [])

  const loadWeekends = useCallback(async () => {
    try {
      const { data } = await api.get('/weekends/global')
      setGlobalDays(data.days_of_week)
    } catch (err) {
      // 404 simply means "not configured yet" — show nothing ticked.
      if (err.response?.status !== 404) {
        setError(errorMessage(err, 'Could not load the global weekend.'))
      } else {
        setGlobalDays([])
      }
    }
    try {
      const { data } = await api.get('/weekends/employees')
      setOverrides(data)
    } catch (err) {
      setError(errorMessage(err, 'Could not load the employee overrides.'))
    }
  }, [])

  const loadHolidays = useCallback(async () => {
    if (!yearId) {
      setHolidays([])
      return
    }
    try {
      const { data } = await api.get('/holidays', { params: { leave_year_id: yearId } })
      setHolidays(data)
    } catch (err) {
      setError(errorMessage(err, 'Could not load holidays.'))
    }
  }, [yearId])

  useEffect(() => {
    loadLookups()
  }, [loadLookups])

  useEffect(() => {
    loadWeekends()
  }, [loadWeekends])

  useEffect(() => {
    loadHolidays()
  }, [loadHolidays])

  // Live view: reload after any change, when the tab returns, or on the poll.
  useAutoRefresh(() => {
      loadLookups()
      loadWeekends()
      loadHolidays()
    })

  const toggleDay = (list, value, checked) =>
    checked
      ? [...list, value].sort((a, b) => a - b)
      : list.filter((item) => item !== value)

  const saveGlobalWeekend = async () => {
    setError('')
    setNotice('')
    setSavingGlobal(true)
    try {
      const { data } = await api.put('/weekends/global', { days_of_week: globalDays })
      setGlobalDays(data.days_of_week)
      setNotice('Global weekend saved.')
    } catch (err) {
      setError(errorMessage(err, 'Could not save the global weekend.'))
    } finally {
      setSavingGlobal(false)
    }
  }

  const saveOverride = async (event) => {
    event.preventDefault()
    setError('')
    setNotice('')
    try {
      await api.put(`/weekends/employees/${overrideForm.employee_id}`, {
        days_of_week: overrideForm.days,
      })
      setShowOverride(false)
      setNotice('Override saved.')
      await loadWeekends()
    } catch (err) {
      setError(errorMessage(err, 'Could not save the override.'))
    }
  }

  const removeOverride = async (employeeId) => {
    setError('')
    setNotice('')
    try {
      await api.delete(`/weekends/employees/${employeeId}`)
      setConfirmRemove(null)
      setNotice('Override removed; the global weekend applies again.')
      await loadWeekends()
    } catch (err) {
      setError(errorMessage(err, 'Could not remove the override.'))
    }
  }

  const divisionName = (id) =>
    divisions.find((division) => division.id === id)?.name ?? `#${id}`
  const departmentName = (id) =>
    departments.find((department) => department.id === id)?.name ?? `#${id}`

  const scopeLabel = (holiday) => {
    if (holiday.department_id) {
      return `Department: ${departmentName(holiday.department_id)}`
    }
    if (holiday.division_id) {
      return `Division: ${divisionName(holiday.division_id)}`
    }
    return 'All'
  }

  const openHolidayCreate = () => {
    setEditingHoliday(null)
    setHolidayForm(EMPTY_HOLIDAY)
    setError('')
    setNotice('')
    setShowHoliday(true)
  }

  const openHolidayEdit = (holiday) => {
    setEditingHoliday(holiday)
    setHolidayForm({
      mode: 'single',
      date: holiday.date,
      date_from: '',
      date_to: '',
      title: holiday.title,
      type: holiday.type,
      scope: holiday.department_id
        ? 'department'
        : holiday.division_id
          ? 'division'
          : 'all',
      division_id: holiday.division_id ?? '',
      department_id: holiday.department_id ?? '',
    })
    setError('')
    setNotice('')
    setShowHoliday(true)
  }

  const submitHoliday = async (event) => {
    event.preventDefault()
    setSavingHoliday(true)
    setError('')
    setNotice('')

    const scope =
      holidayForm.scope === 'division'
        ? { division_id: Number(holidayForm.division_id), department_id: null }
        : holidayForm.scope === 'department'
          ? { division_id: null, department_id: Number(holidayForm.department_id) }
          : { division_id: null, department_id: null }

    try {
      if (editingHoliday) {
        await api.patch(`/holidays/${editingHoliday.id}`, {
          date: holidayForm.date,
          title: holidayForm.title,
          type: holidayForm.type,
          ...scope,
        })
        setNotice('Holiday updated.')
      } else {
        const payload = {
          leave_year_id: Number(yearId),
          title: holidayForm.title,
          type: holidayForm.type,
          ...scope,
        }
        if (holidayForm.mode === 'single') {
          payload.date = holidayForm.date
        } else {
          payload.date_from = holidayForm.date_from
          payload.date_to = holidayForm.date_to
        }
        const { data } = await api.post('/holidays', payload)
        setNotice(`Created ${data.length} holiday row(s).`)
      }
      setShowHoliday(false)
      await loadHolidays()
    } catch (err) {
      setError(errorMessage(err, 'Could not save the holiday.'))
    } finally {
      setSavingHoliday(false)
    }
  }

  const deleteHoliday = async (holiday) => {
    setError('')
    setNotice('')
    try {
      await api.delete(`/holidays/${holiday.id}`)
      setConfirmDelete(null)
      setNotice('Holiday deleted.')
      await loadHolidays()
    } catch (err) {
      setError(errorMessage(err, 'Could not delete the holiday.'))
    }
  }

  const submitImport = async (event) => {
    event.preventDefault()
    setError('')
    setNotice('')
    setImportErrors([])
    setImporting(true)
    try {
      const formData = new FormData()
      formData.append('leave_year_id', yearId)
      formData.append('file', importFile)
      const { data } = await api.post('/holidays/import', formData)
      setNotice(`Imported ${data.created} holiday row(s).`)
      setImportFile(null)
      await loadHolidays()
    } catch (err) {
      const detail = err.response?.data?.detail
      if (detail?.errors) {
        setImportErrors(detail.errors)
      } else {
        setError(errorMessage(err, 'Import failed.'))
      }
    } finally {
      setImporting(false)
    }
  }

  return (
    <>
      <h1 className="h3 mb-3">Calendar settings</h1>

      {error && (
        <Alert variant="danger" dismissible onClose={() => setError('')}>
          {error}
        </Alert>
      )}
      {notice && (
        <Alert variant="success" dismissible onClose={() => setNotice('')}>
          {notice}
        </Alert>
      )}

      <Tabs defaultActiveKey="weekends" className="mb-3">
        <Tab eventKey="weekends" title="Weekends">
          <h2 className="h5">Global weekend</h2>
          <p className="text-muted">
            Applies to everyone who has no personal override.
          </p>
          <DayCheckboxes
            selected={globalDays}
            onToggle={(value, checked) =>
              setGlobalDays(toggleDay(globalDays, value, checked))
            }
          />
          <div className="mt-3 mb-4">
            <Button
              onClick={saveGlobalWeekend}
              disabled={savingGlobal || globalDays.length === 0}
            >
              {savingGlobal ? 'Saving...' : 'Save global weekend'}
            </Button>
          </div>

          <div className="d-flex justify-content-between align-items-center mb-2">
            <h2 className="h5 mb-0">Per-employee overrides</h2>
            <Button
              size="sm"
              variant="outline-primary"
              onClick={() => {
                setOverrideForm({ employee_id: '', days: [] })
                setShowOverride(true)
              }}
            >
              Add override
            </Button>
          </div>

          {overrides.length === 0 ? (
            <div className="empty-state">
              No overrides. Everyone uses the global weekend.
            </div>
          ) : (
            <Table striped bordered hover responsive>
              <thead>
                <tr>
                  <th>Employee</th>
                  <th>Weekend days</th>
                  <th className="text-end">Actions</th>
                </tr>
              </thead>
              <tbody>
                {overrides.map((row) => (
                  <tr key={row.id}>
                    <td>
                      {row.employee_name} ({row.employee_code})
                    </td>
                    <td>{dayNames(row.days_of_week)}</td>
                    <td className="text-end">
                      <Button
                        size="sm"
                        variant="outline-secondary"
                        className="me-2"
                        onClick={() => {
                          setOverrideForm({
                            employee_id: String(row.employee_id),
                            days: row.days_of_week,
                          })
                          setShowOverride(true)
                        }}
                      >
                        Change
                      </Button>
                      <Button
                        size="sm"
                        variant="outline-danger"
                        onClick={() => setConfirmRemove(row)}
                      >
                        Remove
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Tab>

        <Tab eventKey="holidays" title="Holidays">
          <Row className="g-2 mb-3">
            <Col md={4}>
              <Form.Select
                aria-label="Leave year"
                value={yearId}
                onChange={(event) => setYearId(event.target.value)}
              >
                <option value="">Select a leave year...</option>
                {leaveYears.map((year) => (
                  <option key={year.id} value={year.id}>
                    {year.name}
                    {year.is_active ? ' (active)' : ''}
                  </option>
                ))}
              </Form.Select>
            </Col>
            <Col md={8} className="text-md-end">
              <Button
                className="me-2"
                onClick={openHolidayCreate}
                disabled={!yearId}
              >
                Add holiday
              </Button>
            </Col>
          </Row>

          {!yearId ? (
            <div className="empty-state">Pick a leave year to see its holidays.</div>
          ) : holidays.length === 0 ? (
            <div className="empty-state">No holidays for this leave year yet.</div>
          ) : (
            <Table striped bordered hover responsive>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Title</th>
                  <th>Type</th>
                  <th>Scope</th>
                  <th className="text-end">Actions</th>
                </tr>
              </thead>
              <tbody>
                {holidays.map((holiday) => (
                  <tr key={holiday.id}>
                    <td>{holiday.date}</td>
                    <td>{holiday.title}</td>
                    <td>{holiday.type}</td>
                    <td>{scopeLabel(holiday)}</td>
                    <td className="text-end">
                      <Button
                        size="sm"
                        variant="outline-secondary"
                        className="me-2"
                        onClick={() => openHolidayEdit(holiday)}
                      >
                        Edit
                      </Button>
                      <Button
                        size="sm"
                        variant="outline-danger"
                        onClick={() => setConfirmDelete(holiday)}
                      >
                        Delete
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}

          <h2 className="h5 mt-4">Import CSV</h2>
          <p className="text-muted mb-2">
            Columns: <code>date,title,type,division,department</code> (division and
            department are optional names). Nothing is imported unless every row is
            valid.
          </p>
          <Form onSubmit={submitImport} className="d-flex flex-wrap gap-2">
            <Form.Control
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => setImportFile(event.target.files?.[0] ?? null)}
              style={{ maxWidth: 380 }}
              required
            />
            <Button type="submit" disabled={importing || !importFile || !yearId}>
              {importing ? 'Importing...' : 'Import'}
            </Button>
          </Form>

          {importErrors.length > 0 && (
            <Alert variant="danger" className="mt-3">
              <strong>{importErrors.length} row(s) could not be imported.</strong>{' '}
              Nothing was saved.
              <ListGroup variant="flush" className="mt-2">
                {importErrors.map((item) => (
                  <ListGroup.Item key={item.row} className="px-0 py-1 bg-transparent">
                    Row {item.row}: {item.message}
                  </ListGroup.Item>
                ))}
              </ListGroup>
            </Alert>
          )}
        </Tab>
      </Tabs>

      <Modal show={showOverride} onHide={() => setShowOverride(false)} centered>
        <Form onSubmit={saveOverride}>
          <Modal.Header closeButton>
            <Modal.Title>Employee weekend override</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <Form.Group className="mb-3" controlId="overrideEmployee">
              <Form.Label>Employee</Form.Label>
              <Form.Select
                value={overrideForm.employee_id}
                onChange={(event) =>
                  setOverrideForm({ ...overrideForm, employee_id: event.target.value })
                }
                required
              >
                <option value="">Select an employee...</option>
                {employees.map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.full_name} ({employee.employee_code})
                  </option>
                ))}
              </Form.Select>
            </Form.Group>
            <Form.Group controlId="overrideDays">
              <Form.Label className="d-block">Weekend days</Form.Label>
              <DayCheckboxes
                selected={overrideForm.days}
                onToggle={(value, checked) =>
                  setOverrideForm({
                    ...overrideForm,
                    days: toggleDay(overrideForm.days, value, checked),
                  })
                }
              />
            </Form.Group>
          </Modal.Body>
          <Modal.Footer>
            <Button variant="secondary" onClick={() => setShowOverride(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={overrideForm.days.length === 0}>
              Save
            </Button>
          </Modal.Footer>
        </Form>
      </Modal>

      <Modal show={showHoliday} onHide={() => setShowHoliday(false)} centered>
        <Form onSubmit={submitHoliday}>
          <Modal.Header closeButton>
            <Modal.Title>
              {editingHoliday ? 'Edit holiday' : 'Add holiday'}
            </Modal.Title>
          </Modal.Header>
          <Modal.Body>
            {!editingHoliday && (
              <Form.Group className="mb-3">
                <Form.Check
                  inline
                  type="radio"
                  name="holidayMode"
                  label="Single date"
                  checked={holidayForm.mode === 'single'}
                  onChange={() => setHolidayForm({ ...holidayForm, mode: 'single' })}
                />
                <Form.Check
                  inline
                  type="radio"
                  name="holidayMode"
                  label="Date range"
                  checked={holidayForm.mode === 'range'}
                  onChange={() => setHolidayForm({ ...holidayForm, mode: 'range' })}
                />
              </Form.Group>
            )}

            {holidayForm.mode === 'single' || editingHoliday ? (
              <Form.Group className="mb-3" controlId="holidayDate">
                <Form.Label>Date</Form.Label>
                <Form.Control
                  type="date"
                  value={holidayForm.date}
                  onChange={(event) =>
                    setHolidayForm({ ...holidayForm, date: event.target.value })
                  }
                  required
                />
              </Form.Group>
            ) : (
              <>
                <Form.Group className="mb-3" controlId="holidayFrom">
                  <Form.Label>From</Form.Label>
                  <Form.Control
                    type="date"
                    value={holidayForm.date_from}
                    onChange={(event) =>
                      setHolidayForm({ ...holidayForm, date_from: event.target.value })
                    }
                    required
                  />
                </Form.Group>
                <Form.Group className="mb-3" controlId="holidayTo">
                  <Form.Label>To</Form.Label>
                  <Form.Control
                    type="date"
                    value={holidayForm.date_to}
                    onChange={(event) =>
                      setHolidayForm({ ...holidayForm, date_to: event.target.value })
                    }
                    required
                  />
                </Form.Group>
              </>
            )}

            <Form.Group className="mb-3" controlId="holidayTitle">
              <Form.Label>Title</Form.Label>
              <Form.Control
                value={holidayForm.title}
                onChange={(event) =>
                  setHolidayForm({ ...holidayForm, title: event.target.value })
                }
                maxLength={150}
                required
              />
            </Form.Group>

            <Form.Group className="mb-3" controlId="holidayType">
              <Form.Label>Type</Form.Label>
              <Form.Select
                value={holidayForm.type}
                onChange={(event) =>
                  setHolidayForm({ ...holidayForm, type: event.target.value })
                }
              >
                {HOLIDAY_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </Form.Select>
              <Form.Text className="text-muted">
                OPTIONAL holidays are shown in previews but not subtracted.
              </Form.Text>
            </Form.Group>

            <Form.Group className="mb-3">
              <Form.Label className="d-block">Scope</Form.Label>
              <Form.Check
                inline
                type="radio"
                name="holidayScope"
                label="All"
                checked={holidayForm.scope === 'all'}
                onChange={() => setHolidayForm({ ...holidayForm, scope: 'all' })}
              />
              <Form.Check
                inline
                type="radio"
                name="holidayScope"
                label="Division"
                checked={holidayForm.scope === 'division'}
                onChange={() => setHolidayForm({ ...holidayForm, scope: 'division' })}
              />
              <Form.Check
                inline
                type="radio"
                name="holidayScope"
                label="Department"
                checked={holidayForm.scope === 'department'}
                onChange={() => setHolidayForm({ ...holidayForm, scope: 'department' })}
              />
            </Form.Group>

            {holidayForm.scope === 'division' && (
              <Form.Group controlId="holidayDivision">
                <Form.Label>Division</Form.Label>
                <Form.Select
                  value={holidayForm.division_id}
                  onChange={(event) =>
                    setHolidayForm({ ...holidayForm, division_id: event.target.value })
                  }
                  required
                >
                  <option value="">Select a division...</option>
                  {divisions.map((division) => (
                    <option key={division.id} value={division.id}>
                      {division.name}
                    </option>
                  ))}
                </Form.Select>
              </Form.Group>
            )}

            {holidayForm.scope === 'department' && (
              <Form.Group controlId="holidayDepartment">
                <Form.Label>Department</Form.Label>
                <Form.Select
                  value={holidayForm.department_id}
                  onChange={(event) =>
                    setHolidayForm({
                      ...holidayForm,
                      department_id: event.target.value,
                    })
                  }
                  required
                >
                  <option value="">Select a department...</option>
                  {departments.map((department) => (
                    <option key={department.id} value={department.id}>
                      {department.name}
                    </option>
                  ))}
                </Form.Select>
              </Form.Group>
            )}
          </Modal.Body>
          <Modal.Footer>
            <Button variant="secondary" onClick={() => setShowHoliday(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={savingHoliday}>
              {savingHoliday ? 'Saving...' : 'Save'}
            </Button>
          </Modal.Footer>
        </Form>
      </Modal>

      <Modal show={confirmDelete !== null} onHide={() => setConfirmDelete(null)} centered>
        <Modal.Header closeButton>
          <Modal.Title>Delete holiday</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          Delete <strong>{confirmDelete?.title}</strong> on {confirmDelete?.date}?
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setConfirmDelete(null)}>
            Cancel
          </Button>
          <Button variant="danger" onClick={() => deleteHoliday(confirmDelete)}>
            Delete
          </Button>
        </Modal.Footer>
      </Modal>

      <Modal show={confirmRemove !== null} onHide={() => setConfirmRemove(null)} centered>
        <Modal.Header closeButton>
          <Modal.Title>Remove weekend override</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          Remove the override for <strong>{confirmRemove?.employee_name}</strong>? The
          global weekend will apply again.
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setConfirmRemove(null)}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={() => removeOverride(confirmRemove.employee_id)}
          >
            Remove
          </Button>
        </Modal.Footer>
      </Modal>
    </>
  )
}
