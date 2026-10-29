import { useCallback, useEffect, useState } from 'react'
import { Alert, Badge, Button, Form, Modal, Spinner, Table } from 'react-bootstrap'

import api, { errorMessage } from '../api/client'
import { useAutoRefresh } from '../hooks/useAutoRefresh.js'

const EMPTY_FORM = {
  code: '',
  name: '',
  default_quota: '0',
  accrual_mode: 'fixed',
  allow_half_day: true,
  carry_forward_allowed: false,
  max_carry_forward_days: '0',
  is_active: true,
}

function toForm(leaveType) {
  return {
    code: leaveType.code,
    name: leaveType.name,
    default_quota: String(leaveType.default_quota),
    accrual_mode: leaveType.accrual_mode,
    allow_half_day: leaveType.allow_half_day,
    carry_forward_allowed: leaveType.carry_forward_allowed,
    max_carry_forward_days: String(leaveType.max_carry_forward_days),
    is_active: leaveType.is_active,
  }
}

function toPayload(form) {
  return {
    code: form.code,
    name: form.name,
    default_quota: form.default_quota,
    accrual_mode: form.accrual_mode,
    allow_half_day: form.allow_half_day,
    require_attachment_after_days: null,
    carry_forward_allowed: form.carry_forward_allowed,
    max_carry_forward_days: form.carry_forward_allowed
      ? form.max_carry_forward_days
      : '0',
    is_active: form.is_active,
  }
}

function YesNo({ value }) {
  return <Badge bg={value ? 'success' : 'secondary'}>{value ? 'Yes' : 'No'}</Badge>
}

export default function LeaveTypesPage() {
  const [leaveTypes, setLeaveTypes] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [showCreate, setShowCreate] = useState(false)
  const [showEdit, setShowEdit] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    try {
      const { data } = await api.get('/leave-types')
      setLeaveTypes(data)
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load leave types.'))
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

  const openEdit = (leaveType) => {
    setEditing(leaveType)
    setForm(toForm(leaveType))
    setError('')
    setShowEdit(true)
  }

  const createLeaveType = async (event) => {
    event.preventDefault()
    setSaving(true)
    try {
      await api.post('/leave-types', toPayload(form))
      setShowCreate(false)
      await load()
    } catch (err) {
      setError(errorMessage(err, 'Could not create the leave type.'))
    } finally {
      setSaving(false)
    }
  }

  const updateLeaveType = async (event) => {
    event.preventDefault()
    setSaving(true)
    try {
      await api.patch(`/leave-types/${editing.id}`, toPayload(form))
      setShowEdit(false)
      await load()
    } catch (err) {
      setError(errorMessage(err, 'Could not update the leave type.'))
    } finally {
      setSaving(false)
    }
  }

  const formBody = (
    <>
      <Form.Group className="mb-3" controlId="typeCode">
        <Form.Label>Code</Form.Label>
        <Form.Control
          value={form.code}
          onChange={(event) => setForm({ ...form, code: event.target.value })}
          placeholder="AL"
          maxLength={20}
          required
        />
        <Form.Text className="text-muted">Stored uppercase, e.g. AL, SL, CL.</Form.Text>
      </Form.Group>

      <Form.Group className="mb-3" controlId="typeName">
        <Form.Label>Name</Form.Label>
        <Form.Control
          value={form.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
          placeholder="Annual Leave"
          maxLength={100}
          required
        />
      </Form.Group>

      <Form.Group className="mb-3" controlId="typeQuota">
        <Form.Label>Default annual quota (days)</Form.Label>
        <Form.Control
          type="number"
          step="0.5"
          min="0"
          value={form.default_quota}
          onChange={(event) =>
            setForm({ ...form, default_quota: event.target.value })
          }
          required
        />
      </Form.Group>

      <Form.Group className="mb-3" controlId="typeAccrual">
        <Form.Label>Accrual mode</Form.Label>
        <Form.Select
          value={form.accrual_mode}
          onChange={(event) =>
            setForm({ ...form, accrual_mode: event.target.value })
          }
        >
          <option value="fixed">fixed</option>
          <option value="monthly" disabled>
            monthly (not supported yet)
          </option>
        </Form.Select>
      </Form.Group>

      <Form.Group className="mb-3" controlId="typeHalfDay">
        <Form.Check
          type="checkbox"
          label="Allow half-day"
          checked={form.allow_half_day}
          onChange={(event) =>
            setForm({ ...form, allow_half_day: event.target.checked })
          }
        />
      </Form.Group>

      <Form.Group className="mb-3" controlId="typeCarryForward">
        <Form.Check
          type="checkbox"
          label="Carry forward allowed"
          checked={form.carry_forward_allowed}
          onChange={(event) =>
            setForm({ ...form, carry_forward_allowed: event.target.checked })
          }
        />
      </Form.Group>

      {form.carry_forward_allowed && (
        <Form.Group className="mb-3" controlId="typeMaxCarry">
          <Form.Label>Max carry-forward days</Form.Label>
          <Form.Control
            type="number"
            step="0.5"
            min="0"
            value={form.max_carry_forward_days}
            onChange={(event) =>
              setForm({ ...form, max_carry_forward_days: event.target.value })
            }
            required
          />
        </Form.Group>
      )}

      <Form.Group controlId="typeActive">
        <Form.Check
          type="checkbox"
          label="Active"
          checked={form.is_active}
          onChange={(event) =>
            setForm({ ...form, is_active: event.target.checked })
          }
        />
      </Form.Group>
    </>
  )

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h1 className="h3 mb-0">Leave types</h1>
        <Button onClick={openCreate}>Add leave type</Button>
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
      ) : leaveTypes.length === 0 ? (
        <div className="empty-state">
          No leave types yet. Click "Add leave type" to create the first one.
        </div>
      ) : (
        <Table striped bordered hover responsive>
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
              <th>Quota</th>
              <th>Half-day</th>
              <th>Carry-forward</th>
              <th>Active</th>
              <th className="text-end">Actions</th>
            </tr>
          </thead>
          <tbody>
            {leaveTypes.map((leaveType) => (
              <tr key={leaveType.id}>
                <td>{leaveType.code}</td>
                <td>{leaveType.name}</td>
                <td>{Number(leaveType.default_quota)}</td>
                <td>
                  <YesNo value={leaveType.allow_half_day} />
                </td>
                <td>
                  {leaveType.carry_forward_allowed
                    ? `Yes (max ${Number(leaveType.max_carry_forward_days)})`
                    : 'No'}
                </td>
                <td>
                  <YesNo value={leaveType.is_active} />
                </td>
                <td className="text-end">
                  <Button
                    size="sm"
                    variant="outline-secondary"
                    onClick={() => openEdit(leaveType)}
                  >
                    Edit
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      <Modal show={showCreate} onHide={() => setShowCreate(false)} centered>
        <Form onSubmit={createLeaveType}>
          <Modal.Header closeButton>
            <Modal.Title>Add leave type</Modal.Title>
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
        <Form onSubmit={updateLeaveType}>
          <Modal.Header closeButton>
            <Modal.Title>Edit leave type</Modal.Title>
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
    </>
  )
}
