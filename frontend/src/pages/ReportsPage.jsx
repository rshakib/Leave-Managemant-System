import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Col,
  Form,
  Nav,
  Row,
  Spinner,
  Table,
} from 'react-bootstrap'
import { useSearchParams } from 'react-router-dom'

import api, { errorMessage } from '../api/client'
import DateFilter, { getLastMonthRange } from '../components/DateFilter.jsx'
import NoOptions from '../components/NoOptions.jsx'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

const PAGE_SIZE = 50

const STATUSES = ['PENDING', 'APPROVED', 'REJECTED', 'CANCELLED']

const STATUS_COLOURS = {
  PENDING: 'warning',
  APPROVED: 'success',
  REJECTED: 'danger',
  CANCELLED: 'secondary',
}

const FILTER_KEYS = [
  'leave_year_id',
  'division_id',
  'department_id',
  'employee_id',
  'leave_type_id',
  'status',
  'date_from',
  'date_to',
  'include_inactive',
  'include_reason',
]

function emptyForm(defaultDates = getLastMonthRange()) {
  return {
    leave_year_id: '',
    division_id: '',
    department_id: '',
    employee_id: '',
    leave_type_id: '',
    status: '',
    date_from: defaultDates ? defaultDates.from : '',
    date_to: defaultDates ? defaultDates.to : '',
    include_inactive: false,
    include_reason: false,
  }
}

function formFromParams(searchParams) {
  const defaultDates = getLastMonthRange()
  const isDateAll = searchParams.get('date_all') === 'true'
  const form = emptyForm(isDateAll ? null : defaultDates)
  FILTER_KEYS.forEach((key) => {
    const value = searchParams.get(key)
    if (value === null) return
    if (key === 'include_inactive' || key === 'include_reason') {
      form[key] = value === 'true'
    } else {
      form[key] = value
    }
  })
  return form
}

function paramsFromForm(tab, form, offset) {
  const params = { offset }
  FILTER_KEYS.forEach((key) => {
    if (key === 'include_inactive' || key === 'include_reason') {
      if (form[key]) params[key] = 'true'
      return
    }
    if (form[key] !== '') params[key] = form[key]
  })
  if (!form.date_from && !form.date_to) {
    params.date_all = 'true'
  }
  return params
}

export default function ReportsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const defaultDates = useMemo(() => getLastMonthRange(), [])
  const [reloadKey, setReloadKey] = useState(0)
  const tab = searchParams.get('tab') === 'history' ? 'history' : 'balances'
  const offset = Number(searchParams.get('offset') ?? 0)

  const [form, setForm] = useState(() => formFromParams(searchParams))
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState('')

  const [divisions, setDivisions] = useState([])
  const [departments, setDepartments] = useState([])
  const [employees, setEmployees] = useState([])
  const [leaveTypes, setLeaveTypes] = useState([])
  const [leaveYears, setLeaveYears] = useState([])

  const activeYearId = useMemo(
    () => String(leaveYears.find((year) => year.is_active)?.id ?? ''),
    [leaveYears],
  )

  useEffect(() => {
    const loadOptions = async () => {
      try {
        const [d, dep, e, t, y] = await Promise.all([
          api.get('/divisions'),
          api.get('/departments'),
          api.get('/employees'),
          api.get('/leave-types'),
          api.get('/leave-years'),
        ])
        setDivisions(d.data)
        setDepartments(dep.data)
        setEmployees(e.data)
        setLeaveTypes(t.data)
        setLeaveYears(y.data)

        const active = y.data.find((year) => year.is_active)
        const actId = active ? String(active.id) : ''
        if (active) {
          setForm((prev) => ({
            ...prev,
            leave_year_id: prev.leave_year_id || actId,
          }))
        }
        setSearchParams(
          (prevParams) => {
            const next = new URLSearchParams(prevParams)
            if (actId && !next.has('leave_year_id')) {
              next.set('leave_year_id', actId)
            }
            if (!next.has('date_from') && !next.has('date_to') && next.get('date_all') !== 'true') {
              next.set('date_from', defaultDates.from)
              next.set('date_to', defaultDates.to)
            }
            return next
          },
          { replace: true },
        )
      } catch (err) {
        setError(errorMessage(err, 'Could not load the filter options.'))
      }
    }
    loadOptions()
  }, [])

  // The department list follows the chosen division (see DECISIONS D-60).
  const formDepartments = useMemo(
    () =>
      departments.filter(
        (department) => String(department.division_id) === form.division_id,
      ),
    [departments, form.division_id],
  )

  const apiParams = useMemo(() => {
    const raw = formFromParams(searchParams)
    if (!raw.leave_year_id && activeYearId) {
      raw.leave_year_id = activeYearId
    }
    const params = paramsFromForm(tab, raw, offset)
    delete params.date_all
    return params
  }, [tab, searchParams, offset, activeYearId])

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      if (!report) {
        setLoading(true)
      }
      try {
        const { data } = await api.get(`/reports/${tab}`, {
          params: { ...apiParams, limit: PAGE_SIZE },
        })
        if (cancelled) return
        setReport(data)
        setError('')
      } catch (err) {
        if (cancelled) return
        setReport(null)
        setError(errorMessage(err, 'Could not load the report.'))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [tab, apiParams, reloadKey])

  // Live real-time update (event-driven, silent background update with no spinner)
  useAutoRefresh(() => setReloadKey((key) => key + 1))

  const update = (key, value) => setForm({ ...form, [key]: value })

  const apply = () => {
    const params = paramsFromForm(tab, form, 0)
    params.tab = tab
    setSearchParams(params)
  }

  const resetToLastMonth = () => {
    const range = getLastMonthRange()
    const nextForm = {
      ...form,
      date_from: range.from,
      date_to: range.to,
    }
    setForm(nextForm)
    const params = paramsFromForm(tab, nextForm, 0)
    params.tab = tab
    delete params.date_all
    setSearchParams(params)
  }

  const reset = () => {
    const range = getLastMonthRange()
    const newForm = {
      ...emptyForm(range),
      leave_year_id: activeYearId,
    }
    setForm(newForm)
    const nextParams = paramsFromForm(tab, newForm, 0)
    nextParams.tab = tab
    delete nextParams.date_all
    if (activeYearId) nextParams.leave_year_id = activeYearId
    setSearchParams(nextParams)
  }

  const changeTab = (next) => {
    const currentYear = form.leave_year_id || activeYearId
    const nextForm = {
      ...form,
      leave_year_id: currentYear,
    }
    if (next === 'balances') {
      nextForm.status = ''
      nextForm.include_reason = false
    }
    setForm(nextForm)
    const nextParams = paramsFromForm(next, nextForm, 0)
    nextParams.tab = next
    setSearchParams(nextParams)
  }

  const goToOffset = (next) => {
    const params = { ...apiParams, tab, offset: String(next) }
    setSearchParams(params)
  }

  const download = useCallback(async () => {
    setExporting(true)
    setError('')
    try {
      const response = await api.get(`/reports/${tab}/export`, {
        params: apiParams,
        responseType: 'blob',
      })
      const disposition = response.headers['content-disposition'] ?? ''
      const match = /filename="?([^";]+)"?/.exec(disposition)
      const filename = match ? match[1] : `leave-${tab}.csv`
      const url = window.URL.createObjectURL(response.data)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      // The error body came back as a blob too, so read it to show the message.
      let message = 'Could not export the report.'
      const blob = err.response?.data
      if (blob instanceof Blob) {
        try {
          const parsed = JSON.parse(await blob.text())
          if (parsed?.detail) message = parsed.detail
        } catch {
          message = 'Could not export the report.'
        }
      }
      setError(message)
    } finally {
      setExporting(false)
    }
  }, [tab, apiParams])

  const balanceColumns = [
    'SOLshare ID', 'Name', 'Division', 'Department', 'Type', 'Year',
    'Allocated', 'Carried', 'Used', 'Pending', 'Available',
  ]
  const historyColumns = [
    'Request', 'Employee', 'Division', 'Department', 'Type', 'Dates', 'Days',
    'Status', 'Submitted', 'Approvals',
  ]
  if (tab === 'history' && formFromParams(searchParams).include_reason) {
    historyColumns.push('Reason')
  }

  return (
    <>
      <h1 className="h3 mb-3">Reports</h1>

      <Nav variant="tabs" activeKey={tab} onSelect={changeTab} className="mb-3">
        <Nav.Item>
          <Nav.Link eventKey="balances">Balances</Nav.Link>
        </Nav.Item>
        <Nav.Item>
          <Nav.Link eventKey="history">History</Nav.Link>
        </Nav.Item>
      </Nav>

      {error && (
        <Alert variant="danger" dismissible onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      <Row className="g-2 mb-3">
        <Col md={3}>
          <Form.Label className="small">Leave year</Form.Label>
          <Form.Select
            size="sm"
            value={form.leave_year_id}
            onChange={(event) => update('leave_year_id', event.target.value)}
          >
            {tab === 'history' && <option value="">All years</option>}
            <NoOptions when={leaveYears.length === 0} label="No leave years yet" />
            {leaveYears.map((year) => (
              <option key={year.id} value={year.id}>
                {year.name}
                {year.is_active ? ' (active)' : ''}
              </option>
            ))}
          </Form.Select>
        </Col>

        <Col md={3}>
          <Form.Label className="small">Division</Form.Label>
          <Form.Select
            size="sm"
            value={form.division_id}
            onChange={(event) => {
              setForm({
                ...form,
                division_id: event.target.value,
                department_id: '',
              })
            }}
          >
            <option value="">All divisions</option>
            <NoOptions when={divisions.length === 0} label="No divisions yet" />
            {divisions.map((division) => (
              <option key={division.id} value={division.id}>
                {division.name}
              </option>
            ))}
          </Form.Select>
        </Col>

        <Col md={3}>
          <Form.Label className="small">Department</Form.Label>
          <Form.Select
            size="sm"
            value={form.department_id}
            disabled={form.division_id === ''}
            onChange={(event) => update('department_id', event.target.value)}
          >
            <option value="">
              {form.division_id === '' ? 'Pick a division first' : 'All departments'}
            </option>
            {formDepartments.map((department) => (
              <option key={department.id} value={department.id}>
                {department.name}
              </option>
            ))}
          </Form.Select>
        </Col>

        <Col md={3}>
          <Form.Label className="small">Employee</Form.Label>
          <Form.Select
            size="sm"
            value={form.employee_id}
            onChange={(event) => update('employee_id', event.target.value)}
          >
            <option value="">All employees</option>
            <NoOptions when={employees.length === 0} label="No employees yet" />
            {employees.map((employee) => (
              <option key={employee.id} value={employee.id}>
                {employee.employee_code} — {employee.full_name}
              </option>
            ))}
          </Form.Select>
        </Col>

        <Col md={3}>
          <Form.Label className="small">Leave type</Form.Label>
          <Form.Select
            size="sm"
            value={form.leave_type_id}
            onChange={(event) => update('leave_type_id', event.target.value)}
          >
            <option value="">All leave types</option>
            <NoOptions when={leaveTypes.length === 0} label="No leave types yet" />
            {leaveTypes.map((type) => (
              <option key={type.id} value={type.id}>
                {type.code} — {type.name}
              </option>
            ))}
          </Form.Select>
        </Col>

        {tab === 'history' && (
          <Col md={3}>
            <Form.Label className="small">Status</Form.Label>
            <Form.Select
              size="sm"
              value={form.status}
              onChange={(event) => update('status', event.target.value)}
            >
              <option value="">Any status</option>
              {STATUSES.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </Form.Select>
          </Col>
        )}

        <DateFilter
          dateFrom={form.date_from}
          dateTo={form.date_to}
          onChange={({ dateFrom, dateTo }) =>
            setForm((prev) => ({ ...prev, date_from: dateFrom, date_to: dateTo }))
          }
          label="Date filter"
        />
        {(!form.date_from || !form.date_to || form.date_from !== defaultDates.from || form.date_to !== defaultDates.to) && (
          <Col md="auto" sm={6} xs={12} className="d-flex align-items-end">
            <Button
              variant="link"
              size="sm"
              className="p-0 text-decoration-none small text-muted pb-1"
              onClick={resetToLastMonth}
              title="Reset date filter to default last 1 month"
            >
              Reset to last 1 month
            </Button>
          </Col>
        )}

        <Col md={12} className="d-flex align-items-center gap-4">
          <Form.Check
            type="checkbox"
            id="include-inactive"
            label="Include inactive employees"
            checked={form.include_inactive}
            onChange={(event) => update('include_inactive', event.target.checked)}
          />
          {tab === 'history' && (
            <Form.Check
              type="checkbox"
              id="include-reason"
              label="Include reason (may contain private information)"
              checked={form.include_reason}
              onChange={(event) => update('include_reason', event.target.checked)}
            />
          )}
        </Col>
      </Row>

      <div className="d-flex gap-2 mb-3">
        <Button size="sm" variant="primary" onClick={apply}>
          Apply
        </Button>
        <Button size="sm" variant="outline-secondary" onClick={reset}>
          Reset
        </Button>
        <Button
          size="sm"
          variant="outline-primary"
          onClick={download}
          disabled={exporting}
        >
          {exporting ? 'Preparing…' : 'Download CSV'}
        </Button>
      </div>

      {loading ? (
        <div className="text-center py-5">
          <Spinner animation="border" role="status" />
        </div>
      ) : !report || report.rows.length === 0 ? (
        <div className="empty-state">No rows match these filters.</div>
      ) : (
        <>
          <p className="text-muted small">{summaryLine(tab, report)}</p>
          <Table striped bordered hover responsive size="sm">
            <thead>
              <tr>
                {(tab === 'balances' ? balanceColumns : historyColumns).map(
                  (column) => (
                    <th key={column}>{column}</th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {report.rows.map((row) =>
                tab === 'balances' ? (
                  <tr key={`${row.employee_code}-${row.leave_type_code}`}>
                    <td>{row.employee_code}</td>
                    <td>{row.employee_name}</td>
                    <td>{row.division}</td>
                    <td>{row.department}</td>
                    <td>{row.leave_type_code}</td>
                    <td>{row.leave_year}</td>
                    <td className="text-end">{row.allocated}</td>
                    <td className="text-end">{row.carried_forward}</td>
                    <td className="text-end">{row.used}</td>
                    <td className="text-end">{row.pending}</td>
                    <td className="text-end">{row.available}</td>
                  </tr>
                ) : (
                  <tr key={row.request_id}>
                    <td>{row.request_id}</td>
                    <td>
                      {row.employee_code} — {row.employee_name}
                    </td>
                    <td>{row.division}</td>
                    <td>{row.department}</td>
                    <td>{row.leave_type_code}</td>
                    <td className="small">
                      {row.start_date} → {row.end_date}
                    </td>
                    <td className="text-end">{row.chargeable_days}</td>
                    <td>
                      <Badge bg={STATUS_COLOURS[row.status] ?? 'secondary'}>
                        {row.status}
                      </Badge>
                    </td>
                    <td className="small">
                      {new Date(row.submitted_at).toLocaleString()}
                    </td>
                    <td className="small">{row.approvals ?? ''}</td>
                    {historyColumns.length > 10 && (
                      <td className="small">{row.reason ?? ''}</td>
                    )}
                  </tr>
                ),
              )}
            </tbody>
          </Table>

          <div className="d-flex justify-content-between align-items-center">
            <Button
              size="sm"
              variant="outline-secondary"
              disabled={offset === 0}
              onClick={() => goToOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Previous
            </Button>
            <span className="text-muted small">
              {offset + 1}–{offset + report.rows.length} of {report.total}
            </span>
            <Button
              size="sm"
              variant="outline-secondary"
              disabled={offset + report.rows.length >= report.total}
              onClick={() => goToOffset(offset + PAGE_SIZE)}
            >
              Next
            </Button>
          </div>
        </>
      )}
    </>
  )
}

function summaryLine(tab, report) {
  const summary = report.summary ?? {}
  if (tab === 'balances') {
    return (
      `${summary.row_count ?? 0} row(s) · allocated ${summary.allocated ?? 0} · ` +
      `used ${summary.used ?? 0} · pending ${summary.pending ?? 0} · ` +
      `available ${summary.available ?? 0}`
    )
  }
  const perStatus = Object.entries(summary.by_status ?? {})
    .map(([status, item]) => `${status}: ${item.requests} (${item.days} days)`)
    .join(' · ')
  return `${summary.row_count ?? 0} request(s) · ${summary.total_days ?? 0} day(s)${perStatus ? ` — ${perStatus}` : ''}`
}
