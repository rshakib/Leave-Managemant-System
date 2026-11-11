import pytest
from unittest.mock import MagicMock
from sqlmodel import select
from app.models.employee import Employee
from app.models.employee_approver import EmployeeApprover
from app.services.approvers import ensure_supervisor_is_approver

@pytest.mark.anyio
async def test_ensure_supervisor_is_approver_is_noop():
    session = MagicMock()
    employee = Employee(id=10, full_name="Alice", supervisor_id=5)
    # ensure_supervisor_is_approver should be a no-op
    await ensure_supervisor_is_approver(session, employee)
    assert not session.add.called

