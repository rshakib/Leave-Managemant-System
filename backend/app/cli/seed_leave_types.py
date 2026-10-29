"""Seed the usual company leave types with small, demo-friendly quotas.

    ./venv/bin/python -m app.cli.seed_leave_types

Idempotent by code: an existing type is left exactly as it is.
"""

import asyncio
import sys
from decimal import Decimal

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.leave_type import LeaveType

# code, name, quota, half day, carry forward, max carry, attachment after N days
TYPES = [
    ("AL", "Annual Leave", "10", True, True, "5", None),
    ("SL", "Sick Leave", "10", True, False, "0", 3),
    ("CL", "Casual Leave", "10", True, False, "0", None),
    ("CO", "Compensatory Off", "5", True, False, "0", None),
    ("PL", "Paternity Leave", "5", False, False, "0", None),
    ("BL", "Bereavement Leave", "3", False, False, "0", None),
    ("MRL", "Marriage Leave", "5", True, False, "0", None),
    ("HJ", "Hajj / Umrah Leave", "10", False, False, "0", None),
    ("ST", "Study / Exam Leave", "5", True, False, "0", None),
    ("LWP", "Leave Without Pay", "0", True, False, "0", None),
]


async def _seed() -> int:
    created = 0
    async with async_session_factory() as session:
        for code, name, quota, half_day, carry, max_carry, attach in TYPES:
            existing = await session.scalar(select(LeaveType).where(LeaveType.code == code))
            if existing is not None:
                print(f"  {code:4} already exists ({existing.default_quota} day(s)) — skipped")
                continue
            if await session.scalar(select(LeaveType).where(LeaveType.name == name)):
                print(f"  {name} already exists under another code — skipped")
                continue
            session.add(
                LeaveType(
                    code=code,
                    name=name,
                    default_quota=Decimal(quota),
                    accrual_mode="fixed",
                    allow_half_day=half_day,
                    carry_forward_allowed=carry,
                    max_carry_forward_days=Decimal(max_carry),
                    require_attachment_after_days=attach,
                    is_active=True,
                )
            )
            created += 1
            print(f"  + {code:4} {name:26} {quota:>3} day(s)"
                  f"{'  · carry ' + max_carry if carry else ''}"
                  f"{'  · attachment after ' + str(attach) + ' day(s)' if attach else ''}")

        await session.commit()

        rows = (await session.scalars(
            select(LeaveType).order_by(LeaveType.code)
        )).all()

    print(f"\ncreated {created} type(s). All leave types now:")
    for row in rows:
        print(f"  {row.code:4} {row.name:26} quota {str(row.default_quota):>5}"
              f"  half-day={'yes' if row.allow_half_day else 'no ':3}"
              f"  carry={'yes' if row.carry_forward_allowed else 'no'}")
    return 0


def main() -> int:
    return asyncio.run(_seed())


if __name__ == "__main__":
    sys.exit(main())
