import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  ButtonGroup,
  Card,
  Col,
  Form,
  ListGroup,
  Modal,
  Row,
  Spinner,
  Table,
} from 'react-bootstrap'

import api, { errorMessage } from '../api/client'
import AdjustBalanceModal from '../components/AdjustBalanceModal.jsx'
import AdjustmentHistoryModal from '../components/AdjustmentHistoryModal.jsx'
import Icon from '../components/Icon.jsx'
import NoOptions from '../components/NoOptions.jsx'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

// Decimals arrive from the API as strings (e.g. "20.00"). Format for display
// only — never do floating-point maths on day/money values in the browser.
function days(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : '-'
}

function pct(part, whole) {
  if (!whole || whole <= 0) return 0
  return Math.max(0, Math.min(100, (part / whole) * 100))
}

function getInitials(name) {
  if (!name) return '?'
  const parts = name.trim().split(/\s+/)
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

function BalanceBar({ used, pending, available, entitlement }) {
  const total =
    Number(entitlement) ||
    Number(used) + Number(pending) + Number(available) ||
    1
  return (
    <div className="lms-bar" style={{ minWidth: '70px', height: '6px' }}>
      <span
        className="lms-bar__seg is-used"
        style={{ width: `${pct(used, total)}%` }}
        title={`Used: ${days(used)}`}
      />
      <span
        className="lms-bar__seg is-pending"
        style={{ width: `${pct(pending, total)}%` }}
        title={`Pending: ${days(pending)}`}
      />
      <span
        className="lms-bar__seg is-free"
        style={{ width: `${pct(available, total)}%` }}
        title={`Available: ${days(available)}`}
      />
    </div>
  )
}

const EMPTY_ASSIGN = { employee_ids: [], leave_type_ids: [], allocated_days: '' }
const EMPTY_BULK = {
  scope: 'department',
  division_id: '',
  department_id: '',
  leave_type_ids: [],
  allocated_days: '',
}

export default function LeaveAssignmentsPage() {
  const [leaveYears, setLeaveYears] = useState([])
  const [divisions, setDivisions] = useState([])
  const [departments, setDepartments] = useState([])
  const [leaveTypes, setLeaveTypes] = useState([])
  const [employees, setEmployees] = useState([])

  const [yearId, setYearId] = useState('')
  const [filterDivision, setFilterDivision] = useState('')
  const [filterDepartment, setFilterDepartment] = useState('')
  const [filterLeaveType, setFilterLeaveType] = useState('')
  const [searchEmployee, setSearchEmployee] = useState('')

  const [balances, setBalances] = useState([])
  const [expandedEmployees, setExpandedEmployees] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const [showAssign, setShowAssign] = useState(false)
  const [assignForm, setAssignForm] = useState(EMPTY_ASSIGN)
  const [assignEmployeeSearch, setAssignEmployeeSearch] = useState('')
  const [showBulk, setShowBulk] = useState(false)
  const [bulkForm, setBulkForm] = useState(EMPTY_BULK)
  const [bulkResult, setBulkResult] = useState(null)
  const [adjusting, setAdjusting] = useState(null)
  const [historyFor, setHistoryFor] = useState(null)
  const [flash, setFlash] = useState('')

  const [showEdit, setShowEdit] = useState(false)
  const [editing, setEditing] = useState(null)
  const [editDays, setEditDays] = useState('')
  const [saving, setSaving] = useState(false)

  const [removing, setRemoving] = useState(null)
  const [removingSaving, setRemovingSaving] = useState(false)

  const confirmRemove = async () => {
    if (!removing) return
    setRemovingSaving(true)
    setError('')
    try {
      const { data } = await api.delete(`/leave-assignments/${removing.id}`)
      setNotice(data.message || 'Assignment removed successfully.')
      setRemoving(null)
      await loadBalances()
    } catch (err) {
      setError(errorMessage(err, 'Could not remove this leave assignment.'))
    } finally {
      setRemovingSaving(false)
    }
  }

  const loadLookups = useCallback(async () => {
    try {
      const [years, divisionList, departmentList, types] = await Promise.all([
        api.get('/leave-years'),
        api.get('/divisions'),
        api.get('/departments'),
        api.get('/leave-types'),
      ])
      setLeaveYears(years.data)
      setDivisions(divisionList.data)
      setDepartments(departmentList.data)
      setLeaveTypes(types.data)
      setYearId(
        (current) =>
          current ||
          String(years.data.find((year) => year.is_active)?.id ?? ''),
      )
    } catch (err) {
      setError(errorMessage(err, 'Could not load reference data.'))
    }
  }, [])

  const loadBalances = useCallback(async () => {
    if (!yearId) {
      setBalances([])
      setLoading(false)
      return
    }
    try {
      const params = { leave_year_id: yearId }
      if (filterDivision) params.division_id = filterDivision
      if (filterDepartment) params.department_id = filterDepartment
      if (filterLeaveType) params.leave_type_id = filterLeaveType
      const { data } = await api.get('/leave-balances', { params })
      setBalances(data)
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load balances.'))
    } finally {
      setLoading(false)
    }
  }, [yearId, filterDivision, filterDepartment, filterLeaveType])

  useEffect(() => {
    loadLookups()
  }, [loadLookups])

  useEffect(() => {
    loadBalances()
  }, [loadBalances])

  // Live view: reload after any change, when the tab returns, or on the poll.
  useAutoRefresh(() => {
    loadLookups()
    loadBalances()
  })

  const activeEmployees = async () => {
    const { data } = await api.get('/employees', { params: { is_active: true } })
    setEmployees(data)
    return data
  }

  const departmentOptions = (divisionId) =>
    departments.filter(
      (department) => !divisionId || String(department.division_id) === String(divisionId),
    )

  const openAssign = async () => {
    setAssignForm(EMPTY_ASSIGN)
    setAssignEmployeeSearch('')
    setError('')
    setNotice('')
    try {
      await activeEmployees()
    } catch (err) {
      setError(errorMessage(err, 'Could not load employees.'))
    }
    setShowAssign(true)
  }

  const openBulk = () => {
    setBulkForm(EMPTY_BULK)
    setBulkResult(null)
    setError('')
    setNotice('')
    setShowBulk(true)
  }

  const openEdit = (balance) => {
    setEditing(balance)
    setEditDays(String(balance.allocated))
    setError('')
    setNotice('')
    setShowEdit(true)
  }

  const toggleAssignEmployee = (id) =>
    setAssignForm((form) => ({
      ...form,
      employee_ids: form.employee_ids.includes(id)
        ? form.employee_ids.filter((item) => item !== id)
        : [...form.employee_ids, id],
    }))

  const toggleAssignType = (id) =>
    setAssignForm((form) => ({
      ...form,
      leave_type_ids: form.leave_type_ids.includes(id)
        ? form.leave_type_ids.filter((item) => item !== id)
        : [...form.leave_type_ids, id],
    }))

  const quotaOf = (leaveTypeId) =>
    leaveTypes.find((leaveType) => String(leaveType.id) === String(leaveTypeId))
      ?.default_quota

  const submitAssign = async (event) => {
    event.preventDefault()
    const employeeIds = assignForm.employee_ids
    const typeIds = assignForm.leave_type_ids
    if (employeeIds.length === 0 || typeIds.length === 0) {
      setError('Please select at least one employee and at least one leave type.')
      return
    }

    setSaving(true)
    setError('')
    try {
      const payload = {
        employee_ids: employeeIds.map(Number),
        leave_type_ids: typeIds.map(Number),
        leave_year_id: Number(yearId),
      }
      if (assignForm.allocated_days !== '') {
        payload.allocated_days = assignForm.allocated_days
      }
      const { data } = await api.post('/leave-assignments/bulk', payload)
      setShowAssign(false)
      let msg = `Leave types assigned: ${data.created} created, ${data.updated} updated.`
      if (data.skipped > 0) {
        msg += ` (${data.skipped} skipped)`
      }
      setNotice(msg)
      await loadBalances()
    } catch (err) {
      setError(errorMessage(err, 'Could not assign leave types.'))
    } finally {
      setSaving(false)
    }
  }

  const submitEdit = async (event) => {
    event.preventDefault()
    setSaving(true)
    try {
      await api.post('/leave-assignments', {
        employee_id: editing.employee_id,
        leave_type_id: editing.leave_type_id,
        leave_year_id: editing.leave_year_id,
        allocated_days: editDays === '' ? quotaOf(editing.leave_type_id) : editDays,
      })
      setShowEdit(false)
      setNotice('Allocation updated.')
      await loadBalances()
    } catch (err) {
      setError(errorMessage(err, 'Could not update this allocation.'))
    } finally {
      setSaving(false)
    }
  }

  const submitBulk = async (event) => {
    event.preventDefault()
    setSaving(true)
    setBulkResult(null)
    try {
      const payload = {
        leave_type_ids: bulkForm.leave_type_ids.map(Number),
        leave_year_id: Number(yearId),
      }
      if (bulkForm.scope === 'division') {
        payload.division_id = Number(bulkForm.division_id)
      } else if (bulkForm.scope === 'department') {
        payload.department_id = Number(bulkForm.department_id)
      } else {
        payload.employee_ids = employees
          .filter((employee) => employee.is_active !== false)
          .map((employee) => employee.id)
        if (payload.employee_ids.length === 0) {
          setError('There is no active employee to assign.')
          return
        }
      }
      if (bulkForm.allocated_days !== '') {
        payload.allocated_days = bulkForm.allocated_days
      }
      const { data } = await api.post('/leave-assignments/bulk', payload)
      setBulkResult(data)
      await loadBalances()
    } catch (err) {
      setError(errorMessage(err, 'Could not run the bulk assignment.'))
    } finally {
      setSaving(false)
    }
  }

  const toggleBulkType = (id, checked) => {
    setBulkForm({
      ...bulkForm,
      leave_type_ids: checked
        ? [...bulkForm.leave_type_ids, id]
        : bulkForm.leave_type_ids.filter((item) => item !== id),
    })
  }

  const totalOf = (rows, field) =>
    rows.reduce((sum, row) => sum + Number(row[field] ?? 0), 0)

  // Group balances by employee
  const byEmployee = useMemo(() => {
    const map = new Map()
    balances.forEach((balance) => {
      const key = String(balance.employee_id ?? balance.employee_code)
      if (!map.has(key)) {
        map.set(key, {
          key,
          name: balance.employee_name,
          code: balance.employee_code,
          rows: [],
        })
      }
      map.get(key).rows.push(balance)
    })
    return [...map.values()].map((group) => ({
      ...group,
      allocated: totalOf(group.rows, 'allocated'),
      carried: totalOf(group.rows, 'carried_forward'),
      used: totalOf(group.rows, 'used'),
      pending: totalOf(group.rows, 'pending'),
      available: totalOf(group.rows, 'available'),
    }))
  }, [balances])

  // Instant search filter on the grouped employees
  const filteredByEmployee = useMemo(() => {
    const q = searchEmployee.trim().toLowerCase()
    if (!q) return byEmployee
    return byEmployee.filter((group) => {
      const matchName = (group.name || '').toLowerCase().includes(q)
      const matchCode = (group.code || '').toLowerCase().includes(q)
      return matchName || matchCode
    })
  }, [byEmployee, searchEmployee])

  const toggleEmployee = (key) =>
    setExpandedEmployees((current) => ({ ...current, [key]: !current[key] }))

  const toggleAllEmployees = () => {
    const allExpanded = filteredByEmployee.every((g) => expandedEmployees[g.key])
    const next = {}
    if (!allExpanded) {
      filteredByEmployee.forEach((g) => {
        next[g.key] = true
      })
    }
    setExpandedEmployees(next)
  }

  const adjustingYear = leaveYears.find(
    (year) => String(year.id) === String(adjusting?.leave_year_id || historyFor?.leave_year_id || yearId),
  )

  const onAdjusted = async (data) => {
    const { adjustment, warnings } = data || {}
    if (adjustment) {
      const moved = `${adjustment.field.replace('_', ' ').toLowerCase()} ${adjustment.value_before} → ${adjustment.value_after}`
      setFlash(`Balance adjusted: ${moved}.${warnings?.length ? ` ${warnings[0]}` : ''}`)
    }
    await loadBalances()
  }

  const activeYearObj = leaveYears.find((y) => String(y.id) === String(yearId))
  const activeEmps = useMemo(
    () => employees.filter((e) => e.is_active !== false),
    [employees],
  )
  const activeTypes = useMemo(
    () => leaveTypes.filter((t) => t.is_active),
    [leaveTypes],
  )

  const searchedAssignEmps = useMemo(() => {
    const q = assignEmployeeSearch.trim().toLowerCase()
    if (!q) return activeEmps
    return activeEmps.filter(
      (e) =>
        (e.full_name || '').toLowerCase().includes(q) ||
        (e.employee_code || '').toLowerCase().includes(q),
    )
  }, [activeEmps, assignEmployeeSearch])

  return (
    <div>
      {/* Top Header Section */}
      <div className="d-flex flex-wrap justify-content-between align-items-center gap-3 mb-4">
        <div>
          <div className="d-flex align-items-center gap-2">
            <h1 className="h3 mb-0">Leave Assignments &amp; Balances</h1>
            {activeYearObj && (
              <Badge bg={activeYearObj.is_active ? 'success' : 'secondary'} pill>
                {activeYearObj.name} {activeYearObj.is_active ? '(Active Year)' : ''}
              </Badge>
            )}
          </div>
          <div className="text-muted small mt-1">
            Allocate leave types to staff, manage balance entitlements, and make manual adjustments.
          </div>
        </div>

        <div className="d-flex gap-2">
          <Button variant="primary" onClick={openAssign} className="d-flex align-items-center gap-2 shadow-xs">
            <Icon name="plus" size={16} />
            <span>Assign Leave Types</span>
          </Button>
          <Button variant="outline-primary" onClick={openBulk} className="d-flex align-items-center gap-2">
            <Icon name="layers" size={16} />
            <span>Bulk Assign</span>
          </Button>
        </div>
      </div>

      {error && (
        <Alert variant="danger" dismissible onClose={() => setError('')} className="mb-3">
          {error}
        </Alert>
      )}

      {flash && (
        <Alert variant="success" dismissible onClose={() => setFlash('')} className="mb-3">
          {flash}
        </Alert>
      )}
      {notice && (
        <Alert variant="success" dismissible onClose={() => setNotice('')} className="mb-3">
          {notice}
        </Alert>
      )}

      {/* Filter and Instant Search Toolbar */}
      <Card className="border-0 shadow-sm mb-4 bg-white">
        <Card.Body className="p-3">
          <Row className="g-2 align-items-center">
            {/* Search Box */}
            <Col lg={3} sm={6}>
              <div className="input-group input-group-sm">
                <span className="input-group-text bg-white border-end-0 text-muted">
                  <Icon name="search" size={14} />
                </span>
                <Form.Control
                  type="text"
                  placeholder="Search employee name or code..."
                  value={searchEmployee}
                  onChange={(e) => setSearchEmployee(e.target.value)}
                  className="border-start-0"
                />
                {searchEmployee && (
                  <Button
                    variant="outline-secondary"
                    size="sm"
                    onClick={() => setSearchEmployee('')}
                  >
                    Clear
                  </Button>
                )}
              </div>
            </Col>

            {/* Year Selector */}
            <Col lg={2} sm={6}>
              <Form.Select
                size="sm"
                aria-label="Leave year"
                value={yearId}
                onChange={(event) => setYearId(event.target.value)}
              >
                <option value="">Select leave year...</option>
                <NoOptions when={leaveYears.length === 0} label="No leave years yet" />
                {leaveYears.map((year) => (
                  <option key={year.id} value={year.id}>
                    {year.name}
                    {year.is_active ? ' (active)' : ''}
                  </option>
                ))}
              </Form.Select>
            </Col>

            {/* Division Filter */}
            <Col lg={2} sm={6}>
              <Form.Select
                size="sm"
                aria-label="Filter by division"
                value={filterDivision}
                onChange={(event) => {
                  setFilterDivision(event.target.value)
                  setFilterDepartment('')
                }}
              >
                <option value="">All divisions</option>
                {divisions.map((division) => (
                  <option key={division.id} value={division.id}>
                    {division.name}
                  </option>
                ))}
              </Form.Select>
            </Col>

            {/* Department Filter */}
            <Col lg={2} sm={6}>
              <Form.Select
                size="sm"
                aria-label="Filter by department"
                value={filterDepartment}
                onChange={(event) => setFilterDepartment(event.target.value)}
              >
                <option value="">All departments</option>
                {departmentOptions(filterDivision).map((department) => (
                  <option key={department.id} value={department.id}>
                    {department.name}
                  </option>
                ))}
              </Form.Select>
            </Col>

            {/* Leave Type Filter */}
            <Col lg={2} sm={6}>
              <Form.Select
                size="sm"
                aria-label="Filter by leave type"
                value={filterLeaveType}
                onChange={(event) => setFilterLeaveType(event.target.value)}
              >
                <option value="">All leave types</option>
                {leaveTypes.map((leaveType) => (
                  <option key={leaveType.id} value={leaveType.id}>
                    {leaveType.code} — {leaveType.name}
                  </option>
                ))}
              </Form.Select>
            </Col>

            {/* Expand / Collapse All Toggle */}
            <Col lg={1} sm={6} className="text-end">
              <Button
                variant="outline-secondary"
                size="sm"
                className="w-100 text-nowrap"
                onClick={toggleAllEmployees}
                title="Expand or collapse all employee rows"
              >
                {filteredByEmployee.length > 0 &&
                filteredByEmployee.every((g) => expandedEmployees[g.key])
                  ? 'Collapse'
                  : 'Expand'}
              </Button>
            </Col>
          </Row>
        </Card.Body>
      </Card>

      {/* Main Balances Table Content */}
      {loading ? (
        <div className="text-center py-5">
          <Spinner animation="border" variant="primary" role="status" />
          <div className="text-muted small mt-2">Loading assignments &amp; balances…</div>
        </div>
      ) : !yearId ? (
        <Alert variant="warning" className="text-center py-4">
          No leave year selected. Create and activate one on the Leave years page.
        </Alert>
      ) : balances.length === 0 ? (
        <Alert variant="info" className="text-center py-4">
          <div className="mb-2">
            <Icon name="balance" size={32} className="text-muted" />
          </div>
          <h2 className="h6 fw-bold">No Balances Assigned Yet</h2>
          <p className="small text-muted mb-0">
            Use &ldquo;Assign Leave Types&rdquo; or &ldquo;Bulk Assign&rdquo; above to allocate leave quotas.
          </p>
        </Alert>
      ) : filteredByEmployee.length === 0 ? (
        <Alert variant="warning" className="text-center py-4">
          No employees matched your search &ldquo;{searchEmployee}&rdquo;.
        </Alert>
      ) : (
        <Card className="border-0 shadow-sm overflow-hidden mb-4">
          <div className="table-responsive">
            <Table hover className="align-middle mb-0 small">
              <thead className="table-light text-muted text-uppercase" style={{ fontSize: '11px' }}>
                <tr>
                  <th style={{ minWidth: '220px' }}>Employee</th>
                  <th style={{ minWidth: '130px' }}>Entitlements</th>
                  <th className="text-end">Allocated</th>
                  <th className="text-end">Carried</th>
                  <th className="text-end">Used</th>
                  <th className="text-end">Pending</th>
                  <th className="text-end">Available</th>
                  <th className="text-end" style={{ minWidth: '280px' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredByEmployee.flatMap((group) => {
                  const open = Boolean(expandedEmployees[group.key])
                  return [
                    <tr
                      key={group.key}
                      onClick={() => toggleEmployee(group.key)}
                      style={{ cursor: 'pointer' }}
                      className={open ? 'table-active' : ''}
                    >
                      <td>
                        <div className="d-flex align-items-center gap-2">
                          <span className="text-muted fw-bold font-monospace" style={{ width: '16px' }}>
                            {open ? '▾' : '▸'}
                          </span>
                          <div
                            className="rounded-circle d-flex align-items-center justify-content-center text-white fw-bold shadow-xs"
                            style={{
                              width: '30px',
                              height: '30px',
                              backgroundColor: '#f79020',
                              fontSize: '11px',
                              flexShrink: 0,
                            }}
                          >
                            {getInitials(group.name)}
                          </div>
                          <div>
                            <div className="fw-bold text-dark">{group.name}</div>
                            <span className="font-monospace text-muted small">
                              {group.code}
                            </span>
                          </div>
                        </div>
                      </td>
                      <td>
                        <Badge bg="light" text="dark" className="border font-monospace py-1 px-2">
                          {group.rows.length} leave types
                        </Badge>
                      </td>
                      <td className="text-end font-monospace text-muted">{days(group.allocated)}</td>
                      <td className="text-end font-monospace text-muted">{days(group.carried)}</td>
                      <td className="text-end font-monospace text-secondary fw-semibold">{days(group.used)}</td>
                      <td className="text-end font-monospace text-warning fw-semibold">{days(group.pending)}</td>
                      <td className="text-end font-monospace">
                        <strong className="text-success fs-6">{days(group.available)}</strong>{' '}
                        <span className="small text-muted">days</span>
                      </td>
                      <td className="text-end">
                        <span className="badge bg-light text-secondary border">
                          {open ? 'Hide details' : 'Click for details'}
                        </span>
                      </td>
                    </tr>,
                    ...(open
                      ? group.rows.map((balance) => (
                          <tr key={`${group.key}-${balance.id}`} className="table-light">
                            <td className="ps-4 text-muted small">↳</td>
                            <td>
                              <span className="fw-semibold text-dark">{balance.leave_type_code}</span>
                              <span className="text-muted"> — {balance.leave_type_name}</span>
                            </td>
                            <td className="text-end font-monospace">{days(balance.allocated)}</td>
                            <td className="text-end font-monospace text-muted">{days(balance.carried_forward)}</td>
                            <td className="text-end font-monospace text-secondary fw-semibold">{days(balance.used)}</td>
                            <td className="text-end font-monospace text-warning fw-semibold">{days(balance.pending)}</td>
                            <td className="text-end font-monospace">
                              <strong className="text-success">{days(balance.available)}</strong>{' '}
                              <span className="small text-muted">days</span>
                            </td>
                            <td className="text-end text-nowrap" onClick={(e) => e.stopPropagation()}>
                              <Button
                                size="sm"
                                variant="outline-secondary"
                                className="me-1 py-0 px-2"
                                style={{ fontSize: '11px' }}
                                onClick={() => openEdit(balance)}
                              >
                                Edit allocation
                              </Button>
                              <Button
                                size="sm"
                                variant="outline-primary"
                                className="me-1 py-0 px-2"
                                style={{ fontSize: '11px' }}
                                onClick={() => setAdjusting(balance)}
                              >
                                Adjust
                              </Button>
                              <Button
                                size="sm"
                                variant="outline-dark"
                                className="me-1 py-0 px-2"
                                style={{ fontSize: '11px' }}
                                onClick={() => setHistoryFor(balance)}
                              >
                                History
                              </Button>
                              <Button
                                size="sm"
                                variant="outline-danger"
                                className="py-0 px-2"
                                style={{ fontSize: '11px' }}
                                onClick={() => setRemoving(balance)}
                              >
                                Remove
                              </Button>
                            </td>
                          </tr>
                        ))
                      : []),
                  ]
                })}
              </tbody>
            </Table>
          </div>
        </Card>
      )}

      {/* --- ASSIGN LEAVE TYPES MODAL (Clean Two-Column Layout) --- */}
      <Modal show={showAssign} onHide={() => setShowAssign(false)} centered size="lg">
        <Form onSubmit={submitAssign}>
          <Modal.Header closeButton className="border-bottom">
            <div>
              <Modal.Title className="h5 mb-0 fw-bold">Assign Leave Types</Modal.Title>
              <div className="text-muted small mt-1">
                Select employees and leave types to assign quotas in bulk or individually.
              </div>
            </div>
          </Modal.Header>
          <Modal.Body className="p-3">
            <Row className="g-3">
              {/* Left Column: Employees Selection */}
              <Col md={6}>
                <div className="p-3 rounded border bg-light h-100">
                  <div className="d-flex justify-content-between align-items-center mb-2">
                    <Form.Label className="mb-0 fw-bold text-dark small text-uppercase">
                      1. Select Employees
                    </Form.Label>
                    <Badge bg="primary" pill>
                      {assignForm.employee_ids.length} / {activeEmps.length} selected
                    </Badge>
                  </div>

                  {/* Search inside employees */}
                  <div className="input-group input-group-sm mb-2">
                    <span className="input-group-text bg-white border-end-0 text-muted">
                      <Icon name="search" size={13} />
                    </span>
                    <Form.Control
                      type="text"
                      placeholder="Filter employees..."
                      value={assignEmployeeSearch}
                      onChange={(e) => setAssignEmployeeSearch(e.target.value)}
                      className="border-start-0"
                    />
                    {assignEmployeeSearch && (
                      <Button
                        size="sm"
                        variant="outline-secondary"
                        onClick={() => setAssignEmployeeSearch('')}
                      >
                        Clear
                      </Button>
                    )}
                  </div>

                  {/* Select All Checkbox */}
                  <div className="d-flex justify-content-between align-items-center pb-2 mb-2 border-bottom">
                    <Form.Check
                      type="checkbox"
                      id="assign-select-all-employees"
                      className="fw-semibold small"
                      label={`Select all active (${activeEmps.length})`}
                      checked={
                        activeEmps.length > 0 &&
                        assignForm.employee_ids.length === activeEmps.length
                      }
                      onChange={(event) =>
                        setAssignForm((form) => ({
                          ...form,
                          employee_ids: event.target.checked
                            ? activeEmps.map((e) => String(e.id))
                            : [],
                        }))
                      }
                    />
                    {assignForm.employee_ids.length > 0 && (
                      <Button
                        variant="link"
                        size="sm"
                        className="p-0 text-decoration-none small text-danger"
                        onClick={() =>
                          setAssignForm((form) => ({ ...form, employee_ids: [] }))
                        }
                      >
                        Clear
                      </Button>
                    )}
                  </div>

                  {/* Scrollable Checkbox List */}
                  <div
                    className="bg-white rounded border p-2"
                    style={{ height: '230px', overflowY: 'auto' }}
                  >
                    {searchedAssignEmps.length === 0 ? (
                      <div className="text-muted small p-3 text-center">
                        No employees match &ldquo;{assignEmployeeSearch}&rdquo;
                      </div>
                    ) : (
                      searchedAssignEmps.map((emp) => (
                        <Form.Check
                          key={emp.id}
                          type="checkbox"
                          id={`assign-emp-${emp.id}`}
                          className="py-1 border-bottom border-light"
                          label={
                            <span className="small">
                              <strong className="text-dark">{emp.full_name}</strong>{' '}
                              <span className="text-muted font-monospace">
                                ({emp.employee_code})
                              </span>
                            </span>
                          }
                          checked={assignForm.employee_ids.includes(String(emp.id))}
                          onChange={() => toggleAssignEmployee(String(emp.id))}
                        />
                      ))
                    )}
                  </div>
                </div>
              </Col>

              {/* Right Column: Leave Types Selection */}
              <Col md={6}>
                <div className="p-3 rounded border bg-light h-100">
                  <div className="d-flex justify-content-between align-items-center mb-2">
                    <Form.Label className="mb-0 fw-bold text-dark small text-uppercase">
                      2. Select Leave Types
                    </Form.Label>
                    <Badge bg="success" pill>
                      {assignForm.leave_type_ids.length} / {activeTypes.length} selected
                    </Badge>
                  </div>

                  {/* Select All Checkbox */}
                  <div className="d-flex justify-content-between align-items-center pb-2 mb-2 border-bottom" style={{ minHeight: '31px' }}>
                    <Form.Check
                      type="checkbox"
                      id="assign-select-all-types"
                      className="fw-semibold small"
                      label={`Select all active types (${activeTypes.length})`}
                      checked={
                        activeTypes.length > 0 &&
                        assignForm.leave_type_ids.length === activeTypes.length
                      }
                      onChange={(event) =>
                        setAssignForm((form) => ({
                          ...form,
                          leave_type_ids: event.target.checked
                            ? activeTypes.map((t) => String(t.id))
                            : [],
                        }))
                      }
                    />
                    {assignForm.leave_type_ids.length > 0 && (
                      <Button
                        variant="link"
                        size="sm"
                        className="p-0 text-decoration-none small text-danger"
                        onClick={() =>
                          setAssignForm((form) => ({ ...form, leave_type_ids: [] }))
                        }
                      >
                        Clear
                      </Button>
                    )}
                  </div>

                  {/* Scrollable Checkbox List for Leave Types */}
                  <div
                    className="bg-white rounded border p-2"
                    style={{ height: '265px', overflowY: 'auto' }}
                  >
                    {activeTypes.map((leaveType) => (
                      <Form.Check
                        key={leaveType.id}
                        type="checkbox"
                        id={`assign-type-${leaveType.id}`}
                        className="py-1 border-bottom border-light d-flex align-items-center justify-content-between"
                        label={
                          <div className="d-flex align-items-center gap-2">
                            <span className="badge bg-light text-secondary border font-monospace">
                              {leaveType.code}
                            </span>
                            <span className="small text-dark fw-semibold">
                              {leaveType.name}
                            </span>
                            <span className="badge bg-light text-muted border font-monospace" style={{ fontSize: '10px' }}>
                              quota {days(leaveType.default_quota)}
                            </span>
                          </div>
                        }
                        checked={assignForm.leave_type_ids.includes(String(leaveType.id))}
                        onChange={() => toggleAssignType(String(leaveType.id))}
                      />
                    ))}
                  </div>
                </div>
              </Col>
            </Row>

            {/* Bottom Row: Optional Custom Allocated Days */}
            <div className="mt-3 p-3 rounded border bg-light">
              <Form.Group controlId="assignDays">
                <Form.Label className="small fw-bold text-dark text-uppercase mb-1">
                  Custom Allocated Days (Optional)
                </Form.Label>
                <Form.Control
                  type="number"
                  step="0.5"
                  min="0"
                  size="sm"
                  value={assignForm.allocated_days}
                  onChange={(event) =>
                    setAssignForm({
                      ...assignForm,
                      allocated_days: event.target.value,
                    })
                  }
                  placeholder="Leave empty to use policy default quota for each leave type"
                />
                <Form.Text className="text-muted small">
                  If left blank, each employee receives the configured standard quota (e.g. 20.00 for AL, 10.00 for CL).
                </Form.Text>
              </Form.Group>
            </div>
          </Modal.Body>

          <Modal.Footer className="border-top py-2">
            <Button variant="secondary" size="sm" onClick={() => setShowAssign(false)}>
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              disabled={
                saving ||
                assignForm.employee_ids.length === 0 ||
                assignForm.leave_type_ids.length === 0
              }
            >
              {saving
                ? 'Assigning...'
                : `Save Assignments (${assignForm.employee_ids.length} employees × ${assignForm.leave_type_ids.length} types)`}
            </Button>
          </Modal.Footer>
        </Form>
      </Modal>

      {/* --- BULK ASSIGN MODAL (by Division / Department) --- */}
      <Modal show={showBulk} onHide={() => setShowBulk(false)} centered size="lg">
        <Form onSubmit={submitBulk}>
          <Modal.Header closeButton className="border-bottom">
            <Modal.Title className="h5 mb-0 fw-bold">Bulk Assign Leave Types</Modal.Title>
          </Modal.Header>
          <Modal.Body className="p-3">
            <Form.Group className="mb-3">
              <Form.Label className="d-block fw-bold small text-uppercase text-dark">
                Scope / Target
              </Form.Label>
              <Form.Check
                inline
                type="radio"
                name="bulkScope"
                label="A Division"
                checked={bulkForm.scope === 'division'}
                onChange={() => setBulkForm({ ...bulkForm, scope: 'division' })}
              />
              <Form.Check
                inline
                type="radio"
                name="bulkScope"
                label="A Department"
                checked={bulkForm.scope === 'department'}
                onChange={() => setBulkForm({ ...bulkForm, scope: 'department' })}
              />
              <Form.Check
                inline
                type="radio"
                name="bulkScope"
                label="All Employees"
                checked={bulkForm.scope === 'all'}
                onChange={() => setBulkForm({ ...bulkForm, scope: 'all' })}
              />
            </Form.Group>

            {bulkForm.scope === 'all' ? (
              <p className="text-muted small mb-3">
                Every active employee ({employees.filter((employee) => employee.is_active !== false).length})
                will receive these leave types.
              </p>
            ) : bulkForm.scope === 'division' ? (
              <Form.Group className="mb-3" controlId="bulkDivision">
                <Form.Label className="small fw-semibold">Division</Form.Label>
                <Form.Select
                  size="sm"
                  value={bulkForm.division_id}
                  onChange={(event) =>
                    setBulkForm({ ...bulkForm, division_id: event.target.value })
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
            ) : (
              <Form.Group className="mb-3" controlId="bulkDepartment">
                <Form.Label className="small fw-semibold">Department</Form.Label>
                <Form.Select
                  size="sm"
                  value={bulkForm.department_id}
                  onChange={(event) =>
                    setBulkForm({
                      ...bulkForm,
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

            <Form.Group className="mb-3">
              <Form.Label className="d-block fw-bold small text-uppercase text-dark">
                Leave Types
              </Form.Label>
              <Form.Check
                type="checkbox"
                id="bulk-select-all-types"
                className="fw-semibold small mb-2"
                label={`Select all types (${leaveTypes.length})`}
                checked={
                  leaveTypes.length > 0 &&
                  bulkForm.leave_type_ids.length === leaveTypes.length
                }
                onChange={(event) =>
                  setBulkForm({
                    ...bulkForm,
                    leave_type_ids: event.target.checked
                      ? leaveTypes.map((leaveType) => leaveType.id)
                      : [],
                  })
                }
              />
              <div
                className="border rounded p-2 bg-light"
                style={{ maxHeight: '180px', overflowY: 'auto' }}
              >
                {leaveTypes.map((leaveType) => (
                  <Form.Check
                    key={leaveType.id}
                    type="checkbox"
                    id={`bulk-type-${leaveType.id}`}
                    className="py-1"
                    label={`${leaveType.code} — ${leaveType.name} (quota ${days(leaveType.default_quota)})`}
                    checked={bulkForm.leave_type_ids.includes(leaveType.id)}
                    onChange={(event) =>
                      toggleBulkType(leaveType.id, event.target.checked)
                    }
                  />
                ))}
              </div>
            </Form.Group>

            <Form.Group controlId="bulkDays">
              <Form.Label className="small fw-semibold">Allocated days (optional)</Form.Label>
              <Form.Control
                type="number"
                step="0.5"
                min="0"
                size="sm"
                value={bulkForm.allocated_days}
                onChange={(event) =>
                  setBulkForm({ ...bulkForm, allocated_days: event.target.value })
                }
                placeholder="Leave empty to use each type's default quota"
              />
            </Form.Group>

            {bulkResult && (
              <Alert variant="info" className="mt-3 mb-0">
                <div>
                  Created: <strong>{bulkResult.created}</strong> · Updated:{' '}
                  <strong>{bulkResult.updated}</strong> · Skipped:{' '}
                  <strong>{bulkResult.skipped}</strong>
                </div>
                {bulkResult.skipped_details.length > 0 && (
                  <ListGroup variant="flush" className="mt-2">
                    {bulkResult.skipped_details.map((skip) => (
                      <ListGroup.Item
                        key={`${skip.employee_code}-${skip.leave_type_code}`}
                        className="px-0 py-1 bg-transparent small"
                      >
                        {skip.employee_code} / {skip.leave_type_code}: {skip.reason}
                      </ListGroup.Item>
                    ))}
                  </ListGroup>
                )}
              </Alert>
            )}
          </Modal.Body>
          <Modal.Footer className="border-top py-2">
            <Button variant="secondary" size="sm" onClick={() => setShowBulk(false)}>
              Close
            </Button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              disabled={saving || bulkForm.leave_type_ids.length === 0}
            >
              {saving ? 'Working...' : 'Run bulk assign'}
            </Button>
          </Modal.Footer>
        </Form>
      </Modal>

      {/* --- EDIT ALLOCATION MODAL --- */}
      <Modal show={showEdit} onHide={() => setShowEdit(false)} centered>
        <Form onSubmit={submitEdit}>
          <Modal.Header closeButton className="border-bottom">
            <Modal.Title className="h5 mb-0 fw-bold">Edit Allocation</Modal.Title>
          </Modal.Header>
          <Modal.Body className="p-3">
            <div className="p-2 mb-3 bg-light rounded border">
              <div className="fw-bold text-dark">{editing?.employee_name}</div>
              <span className="font-monospace text-muted small">
                {editing?.employee_code} · {editing?.leave_type_code} ({editing?.leave_type_name})
              </span>
            </div>
            <p className="text-muted small">
              Currently allocated: <strong>{days(editing?.allocated)}</strong> days | Available:{' '}
              <strong className="text-success">{days(editing?.available)}</strong> days.
            </p>
            <Form.Group controlId="editAllocatedDays">
              <Form.Label className="small fw-semibold">New Allocated Days</Form.Label>
              <Form.Control
                type="number"
                step="0.5"
                min="0"
                value={editDays}
                onChange={(event) => setEditDays(event.target.value)}
                placeholder={quotaOf(editing?.leave_type_id) ? `Default quota: ${days(quotaOf(editing?.leave_type_id))}` : ''}
                required
              />
            </Form.Group>
          </Modal.Body>
          <Modal.Footer className="border-top py-2">
            <Button variant="secondary" size="sm" onClick={() => setShowEdit(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" size="sm" disabled={saving}>
              {saving ? 'Saving...' : 'Save Allocation'}
            </Button>
          </Modal.Footer>
        </Form>
      </Modal>

      {/* --- REMOVE ASSIGNMENT MODAL --- */}
      <Modal show={Boolean(removing)} onHide={() => setRemoving(null)} centered>
        <Modal.Header closeButton className="border-bottom">
          <Modal.Title className="h5 mb-0 fw-bold text-danger">Remove Assignment</Modal.Title>
        </Modal.Header>
        <Modal.Body className="p-3">
          <p className="mb-2">
            Are you sure you want to remove the <strong>{removing?.leave_type_code} ({removing?.leave_type_name})</strong> assignment for <strong>{removing?.employee_name}</strong>?
          </p>
          {Number(removing?.used) > 0 ? (
            <Alert variant="warning" className="small mb-0">
              This employee has used <strong>{days(removing?.used)}</strong> days of this leave. Removing it will transfer those used days to Annual Leave (AL).
            </Alert>
          ) : (
            <p className="text-muted small mb-0">
              No days have been used, so this assignment will be removed cleanly with zero balance impact.
            </p>
          )}
        </Modal.Body>
        <Modal.Footer className="border-top py-2">
          <Button variant="secondary" size="sm" onClick={() => setRemoving(null)}>
            Cancel
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={confirmRemove}
            disabled={removingSaving}
          >
            {removingSaving ? 'Removing...' : 'Confirm Remove'}
          </Button>
        </Modal.Footer>
      </Modal>

      {/* Adjust Balance Modal */}
      {adjusting && (
        <AdjustBalanceModal
          balance={adjusting}
          show={Boolean(adjusting)}
          yearClosed={Boolean(adjustingYear?.is_closed)}
          onSaved={onAdjusted}
          onAdjusted={onAdjusted}
          onHide={() => setAdjusting(null)}
          onClose={() => setAdjusting(null)}
        />
      )}

      {/* Adjustment History Modal */}
      {historyFor && (
        <AdjustmentHistoryModal
          balance={historyFor}
          show={Boolean(historyFor)}
          onHide={() => setHistoryFor(null)}
          onClose={() => setHistoryFor(null)}
        />
      )}
    </div>
  )
}
