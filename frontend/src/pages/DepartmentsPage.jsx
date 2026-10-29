import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Form, Modal, Spinner, Table } from 'react-bootstrap'

import api, { errorMessage } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

const EMPTY_FORM = { division_id: '', name: '' }

export default function DepartmentsPage() {
  const [departments, setDepartments] = useState([])
  const [divisions, setDivisions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState(null)
  const [divisionFilter, setDivisionFilter] = useState('')

  const [showCreate, setShowCreate] = useState(false)
  const [showEdit, setShowEdit] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(null)

  const loadDivisions = useCallback(async () => {
    try {
      const { data } = await api.get('/divisions')
      setDivisions(data)
    } catch (err) {
      setError(errorMessage(err, 'Could not load divisions.'))
    }
  }, [])

  // Re-runs whenever the filter changes, because `loadDepartments` is rebuilt
  // when `divisionFilter` changes.
  const loadDepartments = useCallback(async () => {
    try {
      const params = divisionFilter ? { division_id: divisionFilter } : undefined
      const { data } = await api.get('/departments', { params })
      setDepartments(data)
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load departments.'))
    } finally {
      setLoading(false)
    }
  }, [divisionFilter])

  useEffect(() => {
    loadDivisions()
  }, [loadDivisions])

  useEffect(() => {
    loadDepartments()
  }, [loadDepartments])

  // Live view: reload after any change, when the tab returns, or on the poll.
  useAutoRefresh(() => {
      loadDivisions()
      loadDepartments()
    })

  const divisionName = (divisionId) =>
    divisions.find((division) => division.id === divisionId)?.name ??
    `#${divisionId}`

  const activeDivisions = divisions.filter((division) => division.is_active)

  const openCreate = () => {
    setForm({ ...EMPTY_FORM, division_id: String(activeDivisions[0]?.id ?? '') })
    setError('')
    setShowCreate(true)
  }

  const openDelete = (department) => {
    setError('')
    setConfirmDelete(department)
  }

  const removeDepartment = async () => {
    if (!confirmDelete) return
    setSaving(true)
    setError('')
    try {
      await api.delete(`/departments/${confirmDelete.id}`)
      await load()
    } catch (err) {
      setError(errorMessage(err, 'Could not delete the department.'))
    } finally {
      setConfirmDelete(null)
      setSaving(false)
    }
  }

  const openEdit = (department) => {
    setEditing(department)
    setForm({ division_id: String(department.division_id), name: department.name })
    setError('')
    setShowEdit(true)
  }

  const createDepartment = async (event) => {
    event.preventDefault()
    setSaving(true)
    try {
      await api.post('/departments', {
        division_id: Number(form.division_id),
        name: form.name,
      })
      setShowCreate(false)
      await loadDepartments()
    } catch (err) {
      setError(errorMessage(err, 'Could not create the department.'))
    } finally {
      setSaving(false)
    }
  }

  const renameDepartment = async (event) => {
    event.preventDefault()
    setSaving(true)
    try {
      await api.patch(`/departments/${editing.id}`, { name: form.name })
      setShowEdit(false)
      await loadDepartments()
    } catch (err) {
      setError(errorMessage(err, 'Could not rename the department.'))
    } finally {
      setSaving(false)
    }
  }

  const toggleActive = async (department) => {
    setError('')
    setBusyId(department.id)
    try {
      await api.patch(`/departments/${department.id}`, {
        is_active: !department.is_active,
      })
      await loadDepartments()
    } catch (err) {
      setError(errorMessage(err, 'Could not change the department status.'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h1 className="h3 mb-0">Departments</h1>
        <Button onClick={openCreate}>Add department</Button>
      </div>

      {error && (
        <Alert variant="danger" dismissible onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      <Form.Group className="mb-3" controlId="filterDivision" style={{ maxWidth: 320 }}>
        <Form.Label>Filter by division</Form.Label>
        <Form.Select
          value={divisionFilter}
          onChange={(event) => setDivisionFilter(event.target.value)}
        >
          <option value="">All divisions</option>
          {divisions.map((division) => (
            <option key={division.id} value={division.id}>
              {division.name}
            </option>
          ))}
        </Form.Select>
      </Form.Group>

      {loading ? (
        <div className="text-center py-5">
          <Spinner animation="border" role="status" />
        </div>
      ) : departments.length === 0 ? (
        <div className="empty-state">
          No departments to show. Click "Add department" to create one.
        </div>
      ) : (
        <Table striped bordered hover responsive>
          <thead>
            <tr>
              <th>Name</th>
              <th>Division</th>
              <th>Status</th>
              <th className="text-end">Actions</th>
            </tr>
          </thead>
          <tbody>
            {departments.map((department) => (
              <tr key={department.id}>
                <td>{department.name}</td>
                <td>{divisionName(department.division_id)}</td>
                <td>
                  <StatusBadge active={department.is_active} />
                </td>
                <td className="text-end">
                  <Button
                    size="sm"
                    variant="outline-secondary"
                    className="me-2"
                    onClick={() => openEdit(department)}
                  >
                    Edit
                  </Button>
                  <Button
                    size="sm"
                    variant={
                      department.is_active ? 'outline-danger' : 'outline-success'
                    }
                    disabled={busyId === department.id}
                    onClick={() => toggleActive(department)}
                  >
                    {department.is_active ? 'Deactivate' : 'Activate'}
                  </Button>
                  <Button
                    size="sm"
                    variant="link"
                    className="text-danger p-0 ms-2"
                    disabled={busyId === department.id}
                    onClick={() => openDelete(department)}
                  >
                    Delete
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      <Modal show={showCreate} onHide={() => setShowCreate(false)} centered>
        <Form onSubmit={createDepartment}>
          <Modal.Header closeButton>
            <Modal.Title>Add department</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <Form.Group className="mb-3" controlId="newDeptDivision">
              <Form.Label>Division</Form.Label>
              <Form.Select
                value={form.division_id}
                onChange={(event) =>
                  setForm({ ...form, division_id: event.target.value })
                }
                required
              >
                <option value="">Select a division...</option>
                {activeDivisions.map((division) => (
                  <option key={division.id} value={division.id}>
                    {division.name}
                  </option>
                ))}
              </Form.Select>
              <Form.Text className="text-muted">
                Only active divisions can receive new departments.
              </Form.Text>
            </Form.Group>

            <Form.Group controlId="newDeptName">
              <Form.Label>Name</Form.Label>
              <Form.Control
                value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
                maxLength={150}
                required
              />
            </Form.Group>
          </Modal.Body>
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
        <Form onSubmit={renameDepartment}>
          <Modal.Header closeButton>
            <Modal.Title>Rename department</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <Form.Group className="mb-3" controlId="editDeptDivision">
              <Form.Label>Division</Form.Label>
              {/* D-36: a department cannot be moved to another division. */}
              <Form.Control value={divisionName(editing?.division_id)} readOnly />
              <Form.Text className="text-muted">
                A department cannot be moved to another division.
              </Form.Text>
            </Form.Group>

            <Form.Group controlId="editDeptName">
              <Form.Label>Name</Form.Label>
              <Form.Control
                value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
                maxLength={150}
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
      <Modal show={Boolean(confirmDelete)} onHide={() => setConfirmDelete(null)} centered>
        <Modal.Header closeButton>
          <Modal.Title>Delete department</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Alert variant="warning" className="mb-3">
            <strong>This cannot be undone.</strong> The record is removed for good.
          </Alert>
          <p className="mb-2">
            Delete <strong>{confirmDelete?.name}</strong>?
          </p>
          <p className="text-muted small mb-0">
            If any employee or holiday still uses it, the deletion is refused and you will be told what
            is in the way — deactivate it instead in that case.
          </p>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setConfirmDelete(null)} disabled={saving}>
            Cancel
          </Button>
          <Button variant="danger" onClick={removeDepartment} disabled={saving}>
            {saving ? 'Deleting...' : 'Delete'}
          </Button>
        </Modal.Footer>
      </Modal>

    </>
  )
}
