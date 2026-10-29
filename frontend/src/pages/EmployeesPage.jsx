import { useCallback, useEffect, useState } from 'react'
import { Alert, Badge, Button, Col, Form, Modal, Row, Spinner, Table } from 'react-bootstrap'

import api, { errorMessage } from '../api/client'
import NoOptions from '../components/NoOptions.jsx'
import StatusBadge from '../components/StatusBadge'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

const ROLES = ['ADMIN', 'EMPLOYEE', 'APPROVER']

const EMPTY_FORM = {
  employee_code: '',
  full_name: '',
  email: '',
  phone: '',
  designation: '',
  joining_date: '',
  password: '',
  division_id: '',
  department_id: '',
  supervisor_id: '',
  roles: ['EMPLOYEE'],
}

function sortRoles(roles) {
  return ROLES.filter((role) => roles.includes(role))
}

function toggleRole(roles, role, checked) {
  return checked ? [...roles, role] : roles.filter((item) => item !== role)
}

function toForm(employee) {
  return {
    employee_code: employee.employee_code,
    full_name: employee.full_name,
    email: employee.email,
    phone: employee.phone ?? '',
    designation: employee.designation ?? '',
    joining_date: employee.joining_date,
    password: '',
    division_id: String(employee.division_id),
    department_id: String(employee.department_id),
    supervisor_id: employee.supervisor_id === null ? '' : String(employee.supervisor_id),
    roles: [...new Set([...(employee.roles ?? []), 'EMPLOYEE'])],
  }
}

function toPayload(form, isEdit) {
  const payload = {
    full_name: form.full_name,
    email: form.email,
    phone: form.phone === '' ? null : form.phone,
    designation: form.designation === '' ? null : form.designation,
    joining_date: form.joining_date,
    division_id: Number(form.division_id),
    department_id: Number(form.department_id),
    supervisor_id: form.supervisor_id === '' ? null : Number(form.supervisor_id),
    // EMPLOYEE is compulsory (D-152); ADMIN / APPROVER are extras.
    roles: sortRoles([...new Set([...form.roles, 'EMPLOYEE'])]),
  }
  if (!isEdit) {
    payload.employee_code = form.employee_code
    payload.password = form.password
  } else if (form.password !== '') {
    // Only send a password when the admin actually typed a new one.
    payload.password = form.password
  }
  return payload
}

export default function EmployeesPage() {
  const [employees, setEmployees] = useState([])
  const [divisions, setDivisions] = useState([])
  const [departments, setDepartments] = useState([])
  const [supervisors, setSupervisors] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState(null)

  const [filterDivision, setFilterDivision] = useState('')
  const [filterDepartment, setFilterDepartment] = useState('')
  const [filterActive, setFilterActive] = useState('')

  const [showCreate, setShowCreate] = useState(false)
  const [showEdit, setShowEdit] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [saving, setSaving] = useState(false)

  const loadLookups = useCallback(async () => {
    try {
      const [divisionsRes, departmentsRes] = await Promise.all([
        api.get('/divisions'),
        api.get('/departments'),
      ])
      setDivisions(divisionsRes.data)
      setDepartments(departmentsRes.data)
    } catch (err) {
      setError(errorMessage(err, 'Could not load divisions and departments.'))
    }
  }, [])

  const loadEmployees = useCallback(async () => {
    try {
      const params = {}
      if (filterDivision) params.division_id = filterDivision
      if (filterDepartment) params.department_id = filterDepartment
      if (filterActive !== '') params.is_active = filterActive
      const { data } = await api.get('/employees', { params })
      setEmployees(data)
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load employees.'))
    } finally {
      setLoading(false)
    }
  }, [filterDivision, filterDepartment, filterActive])

  const loadSupervisors = useCallback(async () => {
    try {
      const { data } = await api.get('/employees', { params: { is_active: true } })
      setSupervisors(data)
    } catch (err) {
      setError(errorMessage(err, 'Could not load the supervisor list.'))
    }
  }, [])

  useEffect(() => {
    loadLookups()
  }, [loadLookups])

  useEffect(() => {
    loadEmployees()
  }, [loadEmployees])

  // Live view: reload after any change, when the tab returns, or on the poll.
  useAutoRefresh(() => {
      loadLookups()
      loadEmployees()
      loadSupervisors()
    })

  const divisionName = (id) =>
    divisions.find((division) => division.id === id)?.name ?? `#${id}`
  const departmentName = (id) =>
    departments.find((department) => department.id === id)?.name ?? `#${id}`

  const openCreate = async () => {
    setForm({
      ...EMPTY_FORM,
      division_id: filterDivision,
      department_id: filterDepartment,
    })
    setError('')
    await loadSupervisors()
    setShowCreate(true)
  }

  const openEdit = async (employee) => {
    setEditing(employee)
    setForm(toForm(employee))
    setError('')
    await loadSupervisors()
    setShowEdit(true)
  }

  const save = async (event, isEdit) => {
    event.preventDefault()
    setSaving(true)
    try {
      if (isEdit) {
        await api.patch(`/employees/${editing.id}`, toPayload(form, true))
        setShowEdit(false)
      } else {
        await api.post('/employees', toPayload(form, false))
        setShowCreate(false)
      }
      await loadEmployees()
    } catch (err) {
      setError(
        errorMessage(
          err,
          isEdit ? 'Could not update the employee.' : 'Could not create the employee.',
        ),
      )
    } finally {
      setSaving(false)
    }
  }

  const toggleActive = async (employee) => {
    setError('')
    setBusyId(employee.id)
    try {
      await api.patch(`/employees/${employee.id}`, {
        is_active: !employee.is_active,
      })
      await loadEmployees()
    } catch (err) {
      setError(errorMessage(err, 'Could not change the employee status.'))
    } finally {
      setBusyId(null)
    }
  }

  // Departments shown in the form depend on the division chosen in the form.
  const formDepartments = departments.filter(
    (department) => String(department.division_id) === form.division_id,
  )

  // Departments shown in the filter bar depend on the filter's division.
  const filterDepartments = departments.filter(
    (department) => !filterDivision || String(department.division_id) === filterDivision,
  )

  const renderForm = (isEdit) => (
    <>
      <Row className="g-3">
        <Col md={6}>
          <Form.Group controlId="empCode">
            <Form.Label>SOLshare ID</Form.Label>
            <Form.Control
              value={form.employee_code}
              onChange={(event) =>
                setForm({ ...form, employee_code: event.target.value })
              }
              maxLength={50}
              disabled={isEdit}
              required
            />
          </Form.Group>
        </Col>
        <Col md={6}>
          <Form.Group controlId="empName">
            <Form.Label>Full name</Form.Label>
            <Form.Control
              value={form.full_name}
              onChange={(event) =>
                setForm({ ...form, full_name: event.target.value })
              }
              maxLength={150}
              required
            />
          </Form.Group>
        </Col>

        <Col md={6}>
          <Form.Group controlId="empEmail">
            <Form.Label>Email</Form.Label>
            <Form.Control
              type="email"
              value={form.email}
              onChange={(event) => setForm({ ...form, email: event.target.value })}
              maxLength={255}
              required
            />
          </Form.Group>
        </Col>
        <Col md={6}>
          <Form.Group controlId="empPhone">
            <Form.Label>Phone</Form.Label>
            <Form.Control
              value={form.phone}
              onChange={(event) => setForm({ ...form, phone: event.target.value })}
              maxLength={30}
            />
          </Form.Group>
        </Col>

        <Col md={6}>
          <Form.Group controlId="empDesignation">
            <Form.Label>Designation</Form.Label>
            <Form.Control
              value={form.designation}
              onChange={(event) =>
                setForm({ ...form, designation: event.target.value })
              }
              maxLength={100}
            />
          </Form.Group>
        </Col>
        <Col md={6}>
          <Form.Group controlId="empJoiningDate">
            <Form.Label>Joining date</Form.Label>
            <Form.Control
              type="date"
              value={form.joining_date}
              onChange={(event) =>
                setForm({ ...form, joining_date: event.target.value })
              }
              required
            />
          </Form.Group>
        </Col>

        <Col md={6}>
          <Form.Group controlId="empPassword">
            <Form.Label>
              {isEdit ? 'New password (leave empty to keep the current one)' : 'Password'}
            </Form.Label>
            <Form.Control
              type="password"
              value={form.password}
              onChange={(event) =>
                setForm({ ...form, password: event.target.value })
              }
              minLength={8}
              autoComplete="new-password"
              required={!isEdit}
            />
            <Form.Text className="text-muted">At least 8 characters.</Form.Text>
          </Form.Group>
        </Col>
        <Col md={6}>
          <Form.Group controlId="empSupervisor">
            <Form.Label>Supervisor</Form.Label>
            <Form.Select
              value={form.supervisor_id}
              onChange={(event) =>
                setForm({ ...form, supervisor_id: event.target.value })
              }
            >
              <option value="">No supervisor</option>
              <NoOptions when={supervisors.length === 0} label="No other active employees" />
              {supervisors
                .filter((person) => !isEdit || person.id !== editing?.id)
                .map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.full_name} ({person.employee_code})
                  </option>
                ))}
            </Form.Select>
          </Form.Group>
        </Col>

        <Col md={6}>
          <Form.Group controlId="empDivision">
            <Form.Label>Division</Form.Label>
            <Form.Select
              value={form.division_id}
              onChange={(event) =>
                setForm({
                  ...form,
                  division_id: event.target.value,
                  // The old department belongs to the old division, so clear it.
                  department_id: '',
                })
              }
              required
            >
              <option value="">Select a division...</option>
              {divisions.map((division) => (
                <option key={division.id} value={division.id}>
                  {division.name}
                  {division.is_active ? '' : ' (inactive)'}
                </option>
              ))}
            </Form.Select>
          </Form.Group>
        </Col>
        <Col md={6}>
          <Form.Group controlId="empDepartment">
            <Form.Label>Department</Form.Label>
            <Form.Select
              value={form.department_id}
              onChange={(event) =>
                setForm({ ...form, department_id: event.target.value })
              }
              disabled={!form.division_id}
              required
            >
              <option value="">
                {form.division_id ? 'Select a department...' : 'Choose a division first'}
              </option>
              {formDepartments.map((department) => (
                <option key={department.id} value={department.id}>
                  {department.name}
                  {department.is_active ? '' : ' (inactive)'}
                </option>
              ))}
            </Form.Select>
          </Form.Group>
        </Col>

        <Col md={12}>
          <Form.Group controlId="empRoles">
            <Form.Label className="d-block">Roles</Form.Label>
            {ROLES.map((role) => {
              const locked = role === 'EMPLOYEE'
              return (
                <Form.Check
                  key={role}
                  inline
                  type="checkbox"
                  label={locked ? 'EMPLOYEE (always)' : role}
                  checked={locked ? true : form.roles.includes(role)}
                  disabled={locked}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      roles: toggleRole(form.roles, role, event.target.checked),
                    })
                  }
                />
              )
            })}
            <Form.Text className="text-muted d-block">
              Every employee always has EMPLOYEE. ADMIN and APPROVER are extra
              permissions on top of it.
            </Form.Text>
          </Form.Group>
        </Col>
      </Row>
    </>
  )

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h1 className="h3 mb-0">Employees</h1>
        <Button onClick={openCreate}>Add employee</Button>
      </div>

      {error && (
        <Alert variant="danger" dismissible onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      <Row className="g-2 mb-3">
        <Col md={4}>
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
        <Col md={4}>
          <Form.Select
            aria-label="Filter by department"
            value={filterDepartment}
            onChange={(event) => setFilterDepartment(event.target.value)}
          >
            <option value="">All departments</option>
            {filterDepartments.map((department) => (
              <option key={department.id} value={department.id}>
                {department.name}
              </option>
            ))}
          </Form.Select>
        </Col>
        <Col md={4}>
          <Form.Select
            aria-label="Filter by status"
            value={filterActive}
            onChange={(event) => setFilterActive(event.target.value)}
          >
            <option value="">Any status</option>
            <option value="true">Active</option>
            <option value="false">Inactive</option>
          </Form.Select>
        </Col>
      </Row>

      {loading ? (
        <div className="text-center py-5">
          <Spinner animation="border" role="status" />
        </div>
      ) : employees.length === 0 ? (
        <div className="empty-state">
          No employees to show. Click "Add employee" to create one.
        </div>
      ) : (
        <Table striped bordered hover responsive>
          <thead>
            <tr>
              <th>SOLshare ID</th>
              <th>Full name</th>
              <th>Email</th>
              <th>Division</th>
              <th>Department</th>
              <th>Roles</th>
              <th>Status</th>
              <th className="text-end">Actions</th>
            </tr>
          </thead>
          <tbody>
            {employees.map((employee) => (
              <tr key={employee.id}>
                <td>{employee.employee_code}</td>
                <td>{employee.full_name}</td>
                <td>{employee.email}</td>
                <td>{divisionName(employee.division_id)}</td>
                <td>{departmentName(employee.department_id)}</td>
                <td>
                  {employee.roles.map((role) => (
                    <Badge key={role} bg="primary" className="me-1">
                      {role}
                    </Badge>
                  ))}
                </td>
                <td>
                  <StatusBadge active={employee.is_active} />
                </td>
                <td className="text-end">
                  <Button
                    size="sm"
                    variant="outline-secondary"
                    className="me-2"
                    onClick={() => openEdit(employee)}
                  >
                    Edit
                  </Button>
                  <Button
                    size="sm"
                    variant={employee.is_active ? 'outline-danger' : 'outline-success'}
                    disabled={busyId === employee.id}
                    onClick={() => toggleActive(employee)}
                  >
                    {employee.is_active ? 'Deactivate' : 'Activate'}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      <Modal show={showCreate} onHide={() => setShowCreate(false)} size="lg" centered>
        <Form onSubmit={(event) => save(event, false)}>
          <Modal.Header closeButton>
            <Modal.Title>Add employee</Modal.Title>
          </Modal.Header>
          <Modal.Body>{renderForm(false)}</Modal.Body>
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

      <Modal show={showEdit} onHide={() => setShowEdit(false)} size="lg" centered>
        <Form onSubmit={(event) => save(event, true)}>
          <Modal.Header closeButton>
            <Modal.Title>Edit employee</Modal.Title>
          </Modal.Header>
          <Modal.Body>{renderForm(true)}</Modal.Body>
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
    </>
  )
}
