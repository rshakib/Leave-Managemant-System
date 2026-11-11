"""Seed demo employees into the local database (``python -m app.cli.seed_employees``)."""

import asyncio
import os
import pathlib
import secrets
import sys
from datetime import date

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import async_session_factory
from app.models.department import Department
from app.models.division import Division
from app.models.employee import Employee, EmployeeRole, Role

CREDENTIALS = "demo_credentials.txt"

PEOPLE = [
    ("DEMO-101", "Rashed Karim", "Software Engineer", "Technology", "Software & Platform", date(2023, 2, 1)),
    ("DEMO-102", "Ayesha Siddiqua", "Accounts Officer", "Corporate", "Finance & Accounts", date(2023, 7, 16)),
    ("DEMO-103", "Imran Chowdhury", "Relationship Manager", "SOLbazaar", "Customer Support", date(2022, 11, 1)),
    ("DEMO-104", "Farzana Rahman", "People Operations Officer", "Corporate", "Human Resources", date(2024, 1, 8)),
    ("DEMO-105", "Tanvir Hossain", "Advisory Associate", "SOLroof", "Engineering & Design", date(2024, 6, 3)),
    ("DEMO-106", "Nusrat Jahan", "Energy Trading Analyst", "SOLbazaar", "Energy Trading", date(2023, 3, 14)),
    ("DEMO-107", "Rafiqul Islam", "Charging Network Lead", "Mobility", "EV Charging", date(2022, 9, 5)),
    ("DEMO-108", "Sadia Rahman", "Hardware Engineer", "Technology", "IoT & Hardware", date(2024, 2, 19)),
    ("DEMO-109", "Mahmudul Hasan", "Project Coordinator", "SOLroof", "Rooftop Projects", date(2023, 10, 2)),
    ("DEMO-110", "Shirin Sultana", "Compliance Officer", "Corporate", "Admin & Compliance", date(2024, 4, 21)),
]


async def _seed(password: str) -> int:
    created = 0
    async with async_session_factory() as session:
        for code, name, designation, division_name, department_name, joined in PEOPLE:
            if await session.scalar(select(Employee).where(Employee.employee_code == code)):
                print(f"  {code} already exists — skipped")
                continue

            division = await session.scalar(select(Division).where(Division.name == division_name))
            if division is None:
                print(f"  ! division '{division_name}' is missing — run app.cli.seed_org first")
                continue
            department = await session.scalar(
                select(Department).where(
                    Department.division_id == division.id, Department.name == department_name
                )
            )
            if department is None:
                print(f"  ! department '{department_name}' is missing under '{division_name}'")
                continue

            employee = Employee(
                employee_code=code,
                full_name=name,
                email=f"{code.lower()}@demo.example.com",
                password_hash=hash_password(password),
                designation=designation,
                division_id=division.id,
                department_id=department.id,
                joining_date=joined,
                must_change_password=False,
            )
            session.add(employee)
            await session.flush()
            session.add(EmployeeRole(employee_id=employee.id, role=Role.EMPLOYEE))
            created += 1
            print(f"  + {code} {name:18} {designation:28} {division_name} / {department_name}")

        await session.commit()

        rows = (
            await session.execute(
                select(Employee.employee_code, Employee.full_name, Employee.email,
                       Division.name, Department.name)
                .join(Division, Division.id == Employee.division_id)
                .join(Department, Department.id == Employee.department_id)
                .order_by(Employee.employee_code)
            )
        ).all()

    print(f"\ncreated {created} employee(s). Everyone in the database now:")
    for code, name, email, division_name, department_name in rows:
        print(f"  {code:10} {name:20} {email:28} {division_name} / {department_name}")
    return 0


def main() -> int:
    import getpass

    password = None
    existing = pathlib.Path(CREDENTIALS)
    if existing.exists():
        for line in existing.read_text().splitlines():
            if line.startswith("# shared password:"):
                password = line.split(":", 1)[1].strip() or None
                break
    if password is None:
        password = f"Demo-{secrets.token_urlsafe(9)}-9Aa"
    handle = os.open(CREDENTIALS, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w") as file:
        file.write("# demo employees — never use these accounts anywhere real\n")
        file.write(f"# shared password: {password}\n\n")
        file.write("code,email,password\n")
        for code, *_ in PEOPLE:
            file.write(f"{code},{code.lower()}@demo.example.com,{password}\n")
    os.chmod(CREDENTIALS, 0o600)

    code = asyncio.run(_seed(password))
    print(f"\ncredentials written to {CREDENTIALS} (mode 600, git-ignored)")
    return code


if __name__ == "__main__":
    sys.exit(main())
