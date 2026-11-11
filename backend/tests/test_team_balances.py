import asyncio
import datetime
from decimal import Decimal
import pytest

from app.models.employee import Employee, EmployeeRead, EmployeeRole, Role, employee_to_read
from app.models.leave_balance import LeaveBalance
from app.models.leave_type import LeaveType
from app.models.leave_year import LeaveYear
from app.routers.leave_balances import team_leave_balances, team_leave_stats


def test_employee_read_includes_is_supervisor():
    emp = Employee(
        id=1,
        full_name="Alice",
        employee_code="EMP-1",
        email="alice@example.com",
        division_id=1,
        department_id=1,
        joining_date=datetime.date(2026, 1, 1),
        password_hash="fake",
    )
    read_false = employee_to_read(emp, [Role.EMPLOYEE], is_supervisor=False)
    assert read_false.is_supervisor is False

    read_true = employee_to_read(emp, [Role.EMPLOYEE, Role.APPROVER], is_supervisor=True)
    assert read_true.is_supervisor is True


def test_team_leave_balances_returns_subordinates():
    async def _run():
        supervisor = Employee(id=10, full_name="Supervisor Sam", email="sam@example.com")
        sub1 = Employee(id=20, full_name="Subordinate Bob", employee_code="EMP-20", supervisor_id=10)
        sub2 = Employee(id=21, full_name="Subordinate Carol", employee_code="EMP-21", supervisor_id=10)

        active_year = LeaveYear(id=1, name="2026-2027", is_active=True, is_closed=False)
        leave_type = LeaveType(id=5, name="Annual Leave", code="AL")

        bal1 = LeaveBalance(
            id=101,
            employee_id=20,
            leave_type_id=5,
            leave_year_id=1,
            allocated=Decimal("15.00"),
            carried_forward=Decimal("2.00"),
            used=Decimal("3.00"),
            pending=Decimal("1.00"),
        )

        class MockScalars:
            def __init__(self, data):
                self._data = data

            def all(self):
                return self._data

        class FakeSession:
            async def scalar(self, stmt):
                # find_active_leave_year
                return active_year

            async def scalars(self, stmt):
                query_str = str(stmt).lower()
                if "from employee_role" in query_str:
                    return MockScalars([EmployeeRole(employee_id=10, role=Role.EMPLOYEE)])
                if "from employee_approver" in query_str:
                    return MockScalars([])
                if "where employee.id in" in query_str:
                    return MockScalars([sub1, sub2])
                if "employee.supervisor_id =" in query_str:
                    return MockScalars([20, 21])
                if "from leave_type" in query_str:
                    return MockScalars([leave_type])
                if "from leave_year" in query_str:
                    return MockScalars([active_year])
                if "from leave_balance" in query_str:
                    return MockScalars([bal1])
                if "from employee" in query_str:
                    return MockScalars([sub1, sub2])
                return MockScalars([])

        results = await team_leave_balances(
            leave_year_id=None,
            employee=supervisor,
            session=FakeSession(),
        )

        assert len(results) == 1
        item = results[0]
        assert item.employee_id == 20
        assert item.employee_name == "Subordinate Bob"
        assert item.leave_type_code == "AL"
        assert item.allocated == Decimal("15.00")
        assert item.used == Decimal("3.00")
        assert item.pending == Decimal("1.00")
        # available = 15 + 2 - 3 - 1 = 13
        assert item.available == Decimal("13.00")

    asyncio.run(_run())


def test_team_leave_balances_empty_when_no_subordinates():
    async def _run():
        emp = Employee(id=99, full_name="Regular Staff", email="staff@example.com")
        active_year = LeaveYear(id=1, name="2026-2027", is_active=True, is_closed=False)

        class MockScalars:
            def __init__(self, data):
                self._data = data

            def all(self):
                return self._data

        class FakeSession:
            async def scalar(self, stmt):
                return active_year

            async def scalars(self, stmt):
                query_str = str(stmt).lower()
                if "from employee_role" in query_str:
                    return MockScalars([EmployeeRole(employee_id=99, role=Role.EMPLOYEE)])
                return MockScalars([])

        results = await team_leave_balances(
            leave_year_id=None,
            employee=emp,
            session=FakeSession(),
        )

        assert results == []

    asyncio.run(_run())


def test_team_leave_stats_empty_when_no_subordinates():
    async def _run():
        emp = Employee(id=99, full_name="Regular Staff", email="staff@example.com")

        class MockScalars:
            def __init__(self, data):
                self._data = data

            def all(self):
                return self._data

        class FakeSession:
            async def scalars(self, stmt):
                query_str = str(stmt).lower()
                if "from employee_role" in query_str:
                    return MockScalars([EmployeeRole(employee_id=99, role=Role.EMPLOYEE)])
                return MockScalars([])

        stats = await team_leave_stats(
            employee=emp,
            session=FakeSession(),
        )

        assert stats.subordinates_count == 0
        assert stats.on_leave_today_count == 0
        assert stats.on_leave_today == []
        assert stats.upcoming_leaves_count == 0
        assert stats.upcoming_leaves == []
        assert stats.pending_approvals_count == 0

    asyncio.run(_run())


def test_team_leave_balances_excludes_mere_approver_assignments():
    async def _run():
        approver = Employee(id=10, full_name="Approver Only", email="approver@example.com")
        active_year = LeaveYear(id=1, name="2026-2027", is_active=True, is_closed=False)

        class MockScalars:
            def __init__(self, data):
                self._data = data

            def all(self):
                return self._data

        class FakeSession:
            async def scalar(self, stmt):
                return active_year

            async def scalars(self, stmt):
                query_str = str(stmt).lower()
                # Supervisor query returns empty because approver does not supervise anyone
                if "employee.supervisor_id =" in query_str:
                    return MockScalars([])
                return MockScalars([])

        results = await team_leave_balances(
            leave_year_id=None,
            employee=approver,
            session=FakeSession(),
        )
        assert results == []

    asyncio.run(_run())
