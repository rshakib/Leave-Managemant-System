import { useCallback, useEffect, useState } from 'react'
import { Alert, Badge, Button, Col, Form, Modal, Row, Spinner, Table } from 'react-bootstrap'

import api, { errorMessage } from '../api/client'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

export default function ApproversPage() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const [divisions, setDivisions] = useState([])
  const [departments, setDepartments] = useState([])
  const [employees, setEmployees] = useState([])

  const [filterDivision, setFilterDivision] = useState('')
  const [filterDepartment, setFilterDepartment] = useState('')
  const [onlyMissing, setOnlyMissing] = useState(false)

  const [showEdit, setShowEdit] = useState(false)
  const [editing, setEditing] = useState(null)
  const [selected, setSelected] = useState([])
  const [search, setSearch] = useState('')
  const [saving, setSaving] = useState(false)

  const loadLookups = useCallback(async () => {
    try {
      const [divisionList, departmentList, employeeList] = await Promise.all([
        api.get('/divisions'),
        api.get('/departments'),
        api.get('/employees', { params: { is_active: true } }),
      ])
      setDivisions(divisionList.data)
      setDepartments(departmentList.data)
      setEmployees(employeeList.data)
    } catch (err) {
      setError(errorMessage(err, 'Could not load reference data.'))
    }
  }, [])

  const loadRows = useCallback(async () => {
    try {
      const params = {}
      if (filterDivision) params.division_id = filterDivision
      if (filterDepartment) params.department_id = filterDepartment
      if (onlyMissing) params.only_missing = true
      const { data } = await api.get('/approver-assignments', { params })
      setRows(data)
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load approver assignments.'))
    } finally {
      setLoading(false)
    }
  }, [filterDivision, filterDepartment, onlyMissing])

  useEffect(() => {
    loadLookups()
  }, [loadLookups])

  useEffect(() => {
    loadRows()
  }, [loadRows])

  // Live view: reload after any change, when the tab returns, or on the poll.
  useAutoRefresh(() => {
      loadRows()
    })

  const divisionName = (id) =>
    divisions.find((division) => division.id === id)?.name ?? `#${id}`
  const departmentName = (id) =>
    departments.find((department) => department.id === id)?.name ?? `#${id}`

  const openEdit = (row) => {
    setEditing(row)
    // Start strictly from the currently assigned approvers (D-214: no auto pre-selection)
    setSelected(row.approvers.map((approver) => approver.id))
    setSearch('')
    setError('')
    setNotice('')
    setShowEdit(true)
  }

  const toggle = (id, checked) => {
    setSelected((current) =>
      checked ? [...current, id] : current.filter((item) => item !== id),
    )
  }

  const save = async (event) => {
    event.preventDefault()
    setSaving(true)
    setError('')
    setNotice('')
    try {
      await api.put(`/employees/${editing.employee_id}/approvers`, {
        approver_ids: selected,
      })
      setShowEdit(false)
      setNotice('Approvers updated.')
      await loadRows()
    } catch (err) {
      setError(errorMessage(err, 'Could not save the approvers.'))
    } finally {
      setSaving(false)
    }
  }

  // Only employees who already hold the APPROVER role may approve (D-151).
  const roleHolders = employees
    .filter((employee) => (employee.roles ?? []).includes('APPROVER'))
    .filter((employee) => employee.id !== editing?.employee_id)

  const candidates = roleHolders
    .filter((employee) => {
      const query = search.trim().toLowerCase()
      if (!query) return true
      return (
        employee.full_name.toLowerCase().includes(query) ||
        employee.employee_code.toLowerCase().includes(query)
      )
    })

  const departmentOptions = departments.filter(
    (department) =>
      !filterDivision || String(department.division_id) === filterDivision,
  )

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h1 className="h3 mb-0">Approvers</h1>
      </div>

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

      <Row className="g-2 mb-3 align-items-center">
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
            {departmentOptions.map((department) => (
              <option key={department.id} value={department.id}>
                {department.name}
              </option>
            ))}
          </Form.Select>
        </Col>
        <Col md={6}>
          <Form.Check
            type="checkbox"
            label="Only employees without an approver"
            checked={onlyMissing}
            onChange={(event) => setOnlyMissing(event.target.checked)}
          />
        </Col>
      </Row>

      {loading ? (
        <div className="text-center py-5">
          <Spinner animation="border" role="status" />
        </div>
      ) : rows.length === 0 ? (
        <div className="empty-state">
          {onlyMissing
            ? 'Every active employee already has at least one approver.'
            : 'No active employees found.'}
        </div>
      ) : (
        <Table striped bordered hover responsive>
          <thead>
            <tr>
              <th>Employee</th>
              <th>Division</th>
              <th>Department</th>
              <th>Approvers</th>
              <th className="text-end">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.employee_id}>
                <td>
                  {row.employee_name} ({row.employee_code})
                </td>
                <td>{divisionName(row.division_id)}</td>
                <td>{departmentName(row.department_id)}</td>
                <td>
                  {row.approvers.length === 0 ? (
                    <Badge bg="warning" text="dark">
                      No approver
                    </Badge>
                  ) : (
                    row.approvers.map((approver) => (
                      <Badge
                        key={approver.id}
                        bg={approver.is_supervisor ? 'info' : 'primary'}
                        className="me-1"
                        title={
                          approver.is_supervisor ? 'Reporting supervisor' : 'Approver'
                        }
                      >
                        {approver.full_name}
                        {approver.is_supervisor ? ' (supervisor)' : ''}
                      </Badge>
                    ))
                  )}
                </td>
                <td className="text-end">
                  <Button
                    size="sm"
                    variant="outline-secondary"
                    onClick={() => openEdit(row)}
                  >
                    Edit approvers
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      <Modal show={showEdit} onHide={() => setShowEdit(false)} centered size="lg">
        <Form onSubmit={save}>
          <Modal.Header closeButton>
            <Modal.Title>
              Approvers for {editing?.employee_name} ({editing?.employee_code})
            </Modal.Title>
          </Modal.Header>
          <Modal.Body>
            {selected.length === 0 && (
              <Alert variant="warning">
                No approver selected. This employee will not be able to submit
                leave until at least one approver is set.
              </Alert>
            )}

            <Form.Group className="mb-3" controlId="approverSearch">
              <Form.Label>Search employees (approvers only)</Form.Label>
              <Form.Control
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="type a name or code"
              />
            </Form.Group>

            <div style={{ maxHeight: 320, overflowY: 'auto' }}>
              {roleHolders.length === 0 ? (
                <Alert variant="warning" className="mb-0">
                  Nobody has the <strong>APPROVER</strong> role yet. Give that role to
                  someone on the <strong>Employees</strong> page (Edit → Roles), then
                  come back here.
                </Alert>
              ) : candidates.length === 0 ? (
                <p className="text-muted mb-0">No matching employees.</p>
              ) : (
                candidates.map((employee) => (
                  <Form.Check
                    key={employee.id}
                    type="checkbox"
                    label={`${employee.full_name} (${employee.employee_code})`}
                    checked={selected.includes(employee.id)}
                    onChange={(event) =>
                      toggle(employee.id, event.target.checked)
                    }
                  />
                ))
              )}
            </div>
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
    </>
  )
}
