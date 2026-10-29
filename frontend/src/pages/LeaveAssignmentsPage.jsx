import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
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
import NoOptions from '../components/NoOptions.jsx'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

// Decimals arrive from the API as strings (e.g. "20.00"). Format for display
// only — never do floating-point maths on day/money values in the browser.
function days(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : '-'
}

const EMPTY_ASSIGN = { employee_id: '', leave_type_ids: [], allocated_days: '' }
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

  const [balances, setBalances] = useState([])
  const [expandedEmployees, setExpandedEmployees] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const [showAssign, setShowAssign] = useState(false)
  const [assignForm, setAssignForm] = useState(EMPTY_ASSIGN)
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
    const typeIds = assignForm.leave_type_ids
    if (!assignForm.employee_id || typeIds.length === 0) {
      setError('Pick an employee and at least one leave type.')
      return
    }

    setSaving(true)
    setError('')
    const done = []
    const failed = []
    try {
      for (const typeId of typeIds) {
        const payload = {
          employee_id: Number(assignForm.employee_id),
          leave_type_id: Number(typeId),
          leave_year_id: Number(yearId),
        }
        if (assignForm.allocated_days !== '') {
          payload.allocated_days = assignForm.allocated_days
        }
        try {
          await api.post('/leave-assignments', payload)
          done.push(typeId)
        } catch (err) {
          failed.push(`${typeId}: ${errorMessage(err, 'failed')}`)
        }
      }
      setShowAssign(false)
      setNotice(
        `${done.length} leave type(s) assigned.` +
          (failed.length ? ` Skipped ${failed.length}: ${failed.join('; ')}` : ''),
      )
      await loadBalances()
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
        allocated_days: editDays,
      })
      setShowEdit(false)
      setNotice('Allocation updated.')
      await loadBalances()
    } catch (err) {
      setError(errorMessage(err, 'Could not update the allocation.'))
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

  const byEmployee = (() => {
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
  })()

  const toggleEmployee = (key) =>
    setExpandedEmployees((current) => ({ ...current, [key]: !current[key] }))

  const adjustingYear = leaveYears.find(
    (year) => year.id === adjusting?.leave_year_id,
  )

  const onAdjusted = async (data) => {
    const { adjustment, warnings } = data
    const moved = `${adjustment.field.replace('_', ' ').toLowerCase()} ${adjustment.value_before} → ${adjustment.value_after}`
    setFlash(`Balance adjusted: ${moved}.${warnings?.length ? ` ${warnings[0]}` : ''}`)
    await loadBalances()
  }

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h1 className="h3 mb-0">Assignments &amp; balances</h1>
        <div>
          <Button className="me-2" onClick={openAssign}>
            Assign
          </Button>
          <Button variant="outline-primary" onClick={openBulk}>
            Bulk assign
          </Button>
        </div>
      </div>

      {error && (
        <Alert variant="danger" dismissible onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      {flash && (
        <Alert variant="success" dismissible onClose={() => setFlash('')}>
          {flash}
        </Alert>
      )}
      {notice && (
        <Alert variant="success" dismissible onClose={() => setNotice('')}>
          {notice}
        </Alert>
      )}

      <Row className="g-2 mb-3">
        <Col md={3}>
          <Form.Select
            aria-label="Leave year"
            value={yearId}
            onChange={(event) => setYearId(event.target.value)}
          >
            <option value="">Select a leave year...</option>
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
          <Form.Select
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
        <Col md={3}>
          <Form.Select
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
        <Col md={3}>
          <Form.Select
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
      </Row>

      {loading ? (
        <div className="text-center py-5">
          <Spinner animation="border" role="status" />
        </div>
      ) : !yearId ? (
        <div className="empty-state">
          No leave year selected. Create and activate one on the Leave years page.
        </div>
      ) : balances.length === 0 ? (
        <div className="empty-state">
          No balances for this year yet. Use "Assign" or "Bulk assign" to allocate leave.
        </div>
      ) : (
        <Table striped bordered hover responsive>
          <thead>
            <tr>
              <th>Employee</th>
              <th>Leave type</th>
              <th className="text-end">Allocated</th>
              <th className="text-end">Carried forward</th>
              <th className="text-end">Used</th>
              <th className="text-end">Pending</th>
              <th className="text-end">Available</th>
              <th className="text-end">Actions</th>
            </tr>
          </thead>
          <tbody>
            {byEmployee.flatMap((group) => {
              const open = Boolean(expandedEmployees[group.key])
              return [
                <tr
                  key={group.key}
                  onClick={() => toggleEmployee(group.key)}
                  style={{ cursor: 'pointer' }}
                  className={open ? 'table-active' : ''}
                >
                  <td className="fw-semibold">
                    {open ? '▾' : '▸'} {group.name} ({group.code})
                  </td>
                  <td className="text-muted">{group.rows.length} leave type(s)</td>
                  <td className="text-end">{days(group.allocated)}</td>
                  <td className="text-end">{days(group.carried)}</td>
                  <td className="text-end">{days(group.used)}</td>
                  <td className="text-end">{days(group.pending)}</td>
                  <td className="text-end fw-bold">{days(group.available)}</td>
                  <td className="text-end small text-muted">
                    {open ? 'Hide details' : 'Click for details'}
                  </td>
                </tr>,
                ...(open
                  ? group.rows.map((balance) => (
                      <tr key={`${group.key}-${balance.id}`} className="table-light">
                        <td className="ps-4 text-muted small">↳</td>
                        <td>
                          {balance.leave_type_code} — {balance.leave_type_name}
                        </td>
                        <td className="text-end">{days(balance.allocated)}</td>
                        <td className="text-end">{days(balance.carried_forward)}</td>
                        <td className="text-end">{days(balance.used)}</td>
                        <td className="text-end">{days(balance.pending)}</td>
                        <td className="text-end fw-bold">{days(balance.available)}</td>
                        <td className="text-end text-nowrap">
                          <Button
                            size="sm"
                            variant="outline-secondary"
                            className="me-2"
                            onClick={() => openEdit(balance)}
                          >
                            Edit allocation
                          </Button>
                          <Button
                            size="sm"
                            variant="outline-primary"
                            className="me-2"
                            onClick={() => setAdjusting(balance)}
                          >
                            Adjust
                          </Button>
                          <Button
                            size="sm"
                            variant="outline-dark"
                            className="me-2"
                            onClick={() => setHistoryFor(balance)}
                          >
                            History
                          </Button>
                          <Button
                            size="sm"
                            variant="outline-danger"
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
      )}

      <Modal show={showAssign} onHide={() => setShowAssign(false)} centered>
        <Form onSubmit={submitAssign}>
          <Modal.Header closeButton>
            <Modal.Title>Assign leave type</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <Form.Group className="mb-3" controlId="assignEmployee">
              <Form.Label>Employee</Form.Label>
              <Form.Select
                value={assignForm.employee_id}
                onChange={(event) =>
                  setAssignForm({ ...assignForm, employee_id: event.target.value })
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

            <Form.Group className="mb-3" controlId="assignType">
              <Form.Label>Leave types</Form.Label>
              <Form.Check
                type="checkbox"
                id="assign-select-all-types"
                className="fw-semibold mb-1"
                label="Select all types"
                checked={
                  leaveTypes.filter((leaveType) => leaveType.is_active).length > 0 &&
                  assignForm.leave_type_ids.length ===
                    leaveTypes.filter((leaveType) => leaveType.is_active).length
                }
                onChange={(event) =>
                  setAssignForm((form) => ({
                    ...form,
                    leave_type_ids: event.target.checked
                      ? leaveTypes
                          .filter((leaveType) => leaveType.is_active)
                          .map((leaveType) => String(leaveType.id))
                      : [],
                  }))
                }
              />
              <div className="border rounded p-2" style={{ maxHeight: 190, overflowY: 'auto' }}>
                {leaveTypes
                  .filter((leaveType) => leaveType.is_active)
                  .map((leaveType) => (
                    <Form.Check
                      key={leaveType.id}
                      type="checkbox"
                      id={`assign-type-${leaveType.id}`}
                      label={`${leaveType.code} — ${leaveType.name} (quota ${days(
                        leaveType.default_quota,
                      )})`}
                      checked={assignForm.leave_type_ids.includes(String(leaveType.id))}
                      onChange={() => toggleAssignType(String(leaveType.id))}
                    />
                  ))}
              </div>
              <Form.Text className="text-muted">
                Tick as many as you need. Leave the days empty and each type takes its own
                quota.
              </Form.Text>
            </Form.Group>

            <Form.Group controlId="assignDays">
              <Form.Label>Allocated days</Form.Label>
              <Form.Control
                type="number"
                step="0.5"
                min="0"
                value={assignForm.allocated_days}
                onChange={(event) =>
                  setAssignForm({
                    ...assignForm,
                    allocated_days: event.target.value,
                  })
                }
                placeholder="leave empty to use the quota"
              />
            </Form.Group>
          </Modal.Body>
          <Modal.Footer>
            <Button variant="secondary" onClick={() => setShowAssign(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? 'Saving...' : 'Save'}
            </Button>
          </Modal.Footer>
        </Form>
      </Modal>

      <Modal show={showBulk} onHide={() => setShowBulk(false)} centered size="lg">
        <Form onSubmit={submitBulk}>
          <Modal.Header closeButton>
            <Modal.Title>Bulk assign</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <Form.Group className="mb-3">
              <Form.Label className="d-block">Apply to</Form.Label>
              <Form.Check
                inline
                type="radio"
                name="bulkScope"
                label="A division"
                checked={bulkForm.scope === 'division'}
                onChange={() =>
                  setBulkForm({ ...bulkForm, scope: 'division' })
                }
              />
              <Form.Check
                inline
                type="radio"
                name="bulkScope"
                label="A department"
                checked={bulkForm.scope === 'department'}
                onChange={() =>
                  setBulkForm({ ...bulkForm, scope: 'department' })
                }
              />
              <Form.Check
                inline
                type="radio"
                name="bulkScope"
                label="All employees"
                checked={bulkForm.scope === 'all'}
                onChange={() => setBulkForm({ ...bulkForm, scope: 'all' })}
              />
            </Form.Group>

            {bulkForm.scope === 'all' ? (
              <p className="text-muted small mb-3">
                Every active employee (
                {employees.filter((employee) => employee.is_active !== false).length})
                gets these leave types.
              </p>
            ) : bulkForm.scope === 'division' ? (
              <Form.Group className="mb-3" controlId="bulkDivision">
                <Form.Label>Division</Form.Label>
                <Form.Select
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
                <Form.Label>Department</Form.Label>
                <Form.Select
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
              <Form.Label className="d-block">Leave types</Form.Label>
              <Form.Check
                type="checkbox"
                id="bulk-select-all-types"
                className="fw-semibold"
                label="Select all types"
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
              {leaveTypes.map((leaveType) => (
                <Form.Check
                  key={leaveType.id}
                  type="checkbox"
                  label={`${leaveType.code} — ${leaveType.name}`}
                  checked={bulkForm.leave_type_ids.includes(leaveType.id)}
                  onChange={(event) =>
                    toggleBulkType(leaveType.id, event.target.checked)
                  }
                />
              ))}
            </Form.Group>

            <Form.Group controlId="bulkDays">
              <Form.Label>Allocated days (optional)</Form.Label>
              <Form.Control
                type="number"
                step="0.5"
                min="0"
                value={bulkForm.allocated_days}
                onChange={(event) =>
                  setBulkForm({ ...bulkForm, allocated_days: event.target.value })
                }
                placeholder="leave empty to use each type's quota"
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
                        className="px-0 py-1 bg-transparent"
                      >
                        {skip.employee_code} / {skip.leave_type_code}: {skip.reason}
                      </ListGroup.Item>
                    ))}
                  </ListGroup>
                )}
              </Alert>
            )}
          </Modal.Body>
          <Modal.Footer>
            <Button variant="secondary" onClick={() => setShowBulk(false)}>
              Close
            </Button>
            <Button
              type="submit"
              disabled={saving || bulkForm.leave_type_ids.length === 0}
            >
              {saving ? 'Working...' : 'Run bulk assign'}
            </Button>
          </Modal.Footer>
        </Form>
      </Modal>

      <Modal show={showEdit} onHide={() => setShowEdit(false)} centered>
        <Form onSubmit={submitEdit}>
          <Modal.Header closeButton>
            <Modal.Title>Edit allocation</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <p className="mb-3">
              {editing?.employee_name} ({editing?.employee_code}) —{' '}
              {editing?.leave_type_code} {editing?.leave_type_name}
            </p>
            <p className="text-muted">
              Currently allocated {days(editing?.allocated)} day(s); available{' '}
              {days(editing?.available)} day(s). Used and pending are not changed here.
            </p>
            <Form.Group controlId="editAllocation">
              <Form.Label>Allocated days</Form.Label>
              <Form.Control
                type="number"
                step="0.5"
                min="0"
                value={editDays}
                onChange={(event) => setEditDays(event.target.value)}
                required
              />
            </Form.Group>
          </Modal.Body>
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
          <Modal show={Boolean(removing)} onHide={() => setRemoving(null)} centered>
        <Modal.Header closeButton>
          <Modal.Title>Remove leave assignment</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {removing && (
            <>
              <p>
                Are you sure you want to remove the <strong>{removing.leave_type_code} — {removing.leave_type_name}</strong> assignment for <strong>{removing.employee_name} ({removing.employee_code})</strong>?
              </p>
              {Number(removing.pending) > 0 && (
                <Alert variant="danger">
                  This employee has <strong>{days(removing.pending)} day(s)</strong> pending approval for this leave type. You must approve, reject, or cancel those requests before removing this assignment.
                </Alert>
              )}
              {Number(removing.used) > 0 && removing.leave_type_code === 'AL' && (
                <Alert variant="danger">
                  Cannot remove Annual Leave (AL) when days have already been used.
                </Alert>
              )}
              {Number(removing.used) > 0 && removing.leave_type_code !== 'AL' && (
                <Alert variant="warning">
                  <strong>Notice:</strong> This employee has already used <strong>{days(removing.used)} day(s)</strong> of {removing.leave_type_name}. Removing this assignment will deduct these <strong>{days(removing.used)} day(s)</strong> from their <strong>Annual Leave (AL)</strong>.
                  <div className="mt-2 small text-muted">
                    If this leave type is assigned again later, those {days(removing.used)} used day(s) will be refunded to Annual Leave and deducted from the new assignment.
                  </div>
                </Alert>
              )}
              {Number(removing.used) === 0 && Number(removing.pending) === 0 && (
                <p className="text-muted small mb-0">
                  No days were used or pending for this leave type. It will be completely removed.
                </p>
              )}
            </>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setRemoving(null)} disabled={removingSaving}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={confirmRemove}
            disabled={
              removingSaving ||
              !removing ||
              Number(removing.pending) > 0 ||
              (removing.leave_type_code === 'AL' && Number(removing.used) > 0)
            }
          >
            {removingSaving ? 'Removing…' : 'Confirm remove'}
          </Button>
        </Modal.Footer>
      </Modal>

      <AdjustBalanceModal
        balance={adjusting}
        show={adjusting !== null}
        yearClosed={Boolean(adjustingYear?.is_closed)}
        onHide={() => setAdjusting(null)}
        onSaved={onAdjusted}
      />

      <AdjustmentHistoryModal
        balance={historyFor}
        show={historyFor !== null}
        onHide={() => setHistoryFor(null)}
      />
    </>
  )
}

