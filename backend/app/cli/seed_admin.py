"""Create the first administrator.

Usage (from the backend/ directory, with the virtualenv activated):

    python -m app.cli.seed_admin
    python -m app.cli.seed_admin --force   # create another admin anyway

The password is read with getpass (never an argument, never printed).
"""

import argparse
import asyncio
import getpass
import sys
from datetime import date

from sqlalchemy import select

from app.core.security import MIN_PASSWORD_LENGTH, hash_password
from app.db.session import async_session_factory
from app.models.department import Department
from app.models.division import Division
from app.models.employee import Employee, EmployeeRole, Role

DEFAULT_DIVISION_NAME = "Head Office"
DEFAULT_DEPARTMENT_NAME = "Administration"


async def _has_active_admin(session) -> bool:
    admin = await session.scalar(
        select(Employee)
        .join(EmployeeRole, EmployeeRole.employee_id == Employee.id)
        .where(EmployeeRole.role == Role.ADMIN, Employee.is_active.is_(True))
        .limit(1)
    )
    return admin is not None


async def _ensure_org(session) -> tuple[int, int]:
    """Return (division_id, department_id), creating defaults when missing."""
    division = await session.scalar(select(Division).order_by(Division.id).limit(1))
    if division is None:
        division = Division(name=DEFAULT_DIVISION_NAME)
        session.add(division)
        await session.flush()

    department = await session.scalar(
        select(Department)
        .where(Department.division_id == division.id)
        .order_by(Department.id)
        .limit(1)
    )
    if department is None:
        department = Department(division_id=division.id, name=DEFAULT_DEPARTMENT_NAME)
        session.add(department)
        await session.flush()

    return division.id, department.id


async def _free_code(session, base: str = "ADMIN") -> str:
    code = base
    counter = 2
    while await session.scalar(
        select(Employee).where(Employee.employee_code == code)
    ):
        code = f"{base}-{counter}"
        counter += 1
    return code


async def _seed(force: bool) -> int:
    async with async_session_factory() as session:
        if not force and await _has_active_admin(session):
            print(
                "An active ADMIN already exists. "
                "Re-run with --force to create another."
            )
            return 1

    full_name = input("Full name: ").strip()
    email = input("Email: ").strip().lower()
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")

    if not full_name or not email:
        print("Full name and email are required.")
        return 1
    if password != confirm:
        print("Passwords do not match.")
        return 1
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        return 1

    async with async_session_factory() as session:
        if await session.scalar(select(Employee).where(Employee.email == email)):
            print(f"An employee with email '{email}' already exists.")
            return 1

        division_id, department_id = await _ensure_org(session)
        code = await _free_code(session)

        employee = Employee(
            employee_code=code,
            full_name=full_name,
            email=email,
            password_hash=hash_password(password),
            division_id=division_id,
            department_id=department_id,
            joining_date=date.today(),
        )
        session.add(employee)
        await session.flush()
        session.add(EmployeeRole(employee_id=employee.id, role=Role.ADMIN))
        session.add(EmployeeRole(employee_id=employee.id, role=Role.EMPLOYEE))
        await session.commit()

        print(f"Created admin '{email}' (employee code {code}) with roles ADMIN, EMPLOYEE.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the first administrator.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="create another admin even if an active admin already exists",
    )
    args = parser.parse_args()
    return asyncio.run(_seed(args.force))


if __name__ == "__main__":
    sys.exit(main())
