import { useCallback, useEffect, useState } from 'react'
import { Alert, Badge, Button, Form, Modal, Spinner, Table } from 'react-bootstrap'

import api, { errorMessage } from '../api/client'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

export default function DivisionsPage() {
  const [divisions, setDivisions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState(null)

  const [showCreate, setShowCreate] = useState(false)
  const [showEdit, setShowEdit] = useState(false)
  const [editing, setEditing] = useState(null)
  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(null)

  const load = useCallback(async () => {
    try {
      const { data } = await api.get('/divisions')
      setDivisions(data)
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load divisions.'))
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
    setName('')
    setError('')
    setShowCreate(true)
  }

  const openDelete = (division) => {
    setError('')
    setConfirmDelete(division)
  }

  const removeDivision = async () => {
    if (!confirmDelete) return
    setSaving(true)
    setError('')
    try {
      await api.delete(`/divisions/${confirmDelete.id}`)
      await load()
    } catch (err) {
      setError(errorMessage(err, 'Could not delete the division.'))
    } finally {
      setConfirmDelete(null)
      setSaving(false)
    }
  }

  const openEdit = (division) => {
    setEditing(division)
    setName(division.name)
    setError('')
    setShowEdit(true)
  }

  const createDivision = async (event) => {
    event.preventDefault()
    setSaving(true)
    try {
      await api.post('/divisions', { name })
      setShowCreate(false)
      await load()
    } catch (err) {
      setError(errorMessage(err, 'Could not create the division.'))
    } finally {
      setSaving(false)
    }
  }

  const renameDivision = async (event) => {
    event.preventDefault()
    setSaving(true)
    try {
      await api.patch(`/divisions/${editing.id}`, { name })
      setShowEdit(false)
      await load()
    } catch (err) {
      setError(errorMessage(err, 'Could not rename the division.'))
    } finally {
      setSaving(false)
    }
  }

  const toggleActive = async (division) => {
    setError('')
    setBusyId(division.id)
    try {
      await api.patch(`/divisions/${division.id}`, {
        is_active: !division.is_active,
      })
      await load()
    } catch (err) {
      setError(errorMessage(err, 'Could not change the division status.'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h1 className="h3 mb-0">Divisions</h1>
        <Button onClick={openCreate}>Add division</Button>
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
      ) : divisions.length === 0 ? (
        <div className="empty-state">
          No divisions yet. Click "Add division" to create the first one.
        </div>
      ) : (
        <Table striped bordered hover responsive>
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th className="text-end">Actions</th>
            </tr>
          </thead>
          <tbody>
            {divisions.map((division) => (
              <tr key={division.id}>
                <td>{division.name}</td>
                <td>
                  <Badge bg={division.is_active ? 'success' : 'secondary'}>
                    {division.is_active ? 'Active' : 'Inactive'}
                  </Badge>
                </td>
                <td className="text-end">
                  <Button
                    size="sm"
                    variant="outline-secondary"
                    className="me-2"
                    onClick={() => openEdit(division)}
                  >
                    Edit
                  </Button>
                  <Button
                    size="sm"
                    variant={
                      division.is_active ? 'outline-danger' : 'outline-success'
                    }
                    disabled={busyId === division.id}
                    onClick={() => toggleActive(division)}
                  >
                    {division.is_active ? 'Deactivate' : 'Activate'}
                  </Button>
                  <Button
                    size="sm"
                    variant="link"
                    className="text-danger p-0 ms-2"
                    disabled={busyId === division.id}
                    onClick={() => openDelete(division)}
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
        <Form onSubmit={createDivision}>
          <Modal.Header closeButton>
            <Modal.Title>Add division</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <Form.Group controlId="newDivisionName">
              <Form.Label>Name</Form.Label>
              <Form.Control
                value={name}
                onChange={(event) => setName(event.target.value)}
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
        <Form onSubmit={renameDivision}>
          <Modal.Header closeButton>
            <Modal.Title>Rename division</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <Form.Group controlId="editDivisionName">
              <Form.Label>Name</Form.Label>
              <Form.Control
                value={name}
                onChange={(event) => setName(event.target.value)}
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
          <Modal.Title>Delete division</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Alert variant="warning" className="mb-3">
            <strong>This cannot be undone.</strong> The record is removed for good.
          </Alert>
          <p className="mb-2">
            Delete <strong>{confirmDelete?.name}</strong>?
          </p>
          <p className="text-muted small mb-0">
            If any department, employee or holiday still uses it, the deletion is refused and you will be told what
            is in the way — deactivate it instead in that case.
          </p>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setConfirmDelete(null)} disabled={saving}>
            Cancel
          </Button>
          <Button variant="danger" onClick={removeDivision} disabled={saving}>
            {saving ? 'Deleting...' : 'Delete'}
          </Button>
        </Modal.Footer>
      </Modal>

    </>
  )
}
