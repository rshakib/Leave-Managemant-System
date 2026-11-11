"""Seed SOLshare divisions and departments (``python -m app.cli.seed_org``)."""

import asyncio
import sys

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.department import Department
from app.models.division import Division

STRUCTURE = {
    "SOLbazaar": ["Marketplace Operations", "Energy Trading", "Customer Support"],
    "Mobility": ["EV Charging", "Battery & Storage"],
    "SOLroof": ["Rooftop Projects", "Engineering & Design"],
    "Technology": ["Software & Platform", "IoT & Hardware"],
    "Corporate": ["Human Resources", "Finance & Accounts", "Admin & Compliance"],
}


async def _seed() -> int:
    created_divisions = created_departments = 0
    async with async_session_factory() as session:
        for division_name, department_names in STRUCTURE.items():
            division = await session.scalar(
                select(Division).where(Division.name == division_name)
            )
            if division is None:
                division = Division(name=division_name)
                session.add(division)
                await session.flush()
                created_divisions += 1

            for department_name in department_names:
                exists = await session.scalar(
                    select(Department).where(
                        Department.division_id == division.id,
                        Department.name == department_name,
                    )
                )
                if exists is None:
                    session.add(Department(division_id=division.id, name=department_name))
                    created_departments += 1

        await session.commit()

        rows = (
            await session.execute(
                select(Division.name, Department.name)
                .join(Department, Department.division_id == Division.id, isouter=True)
                .order_by(Division.name, Department.name)
            )
        ).all()

    print(f"created {created_divisions} division(s), {created_departments} department(s)")
    print("now in the database:")
    current = None
    for division_name, department_name in rows:
        if division_name != current:
            print(f"  {division_name}")
            current = division_name
        if department_name:
            print(f"    - {department_name}")
    return 0


def main() -> int:
    return asyncio.run(_seed())


if __name__ == "__main__":
    sys.exit(main())
