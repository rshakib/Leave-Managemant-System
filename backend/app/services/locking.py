"""Row locks on leave years — the gate every balance writer must pass.

Why a leave year is the gate: a year is closed exactly once, and after that no
balance in it may change. If every writer takes a SHARED lock on the leave-year
row(s) it is about to touch, and the closing takes an EXCLUSIVE lock on the same
row, then either the writer wins (and the closing waits, then sees the new data)
or the closing wins (and the writer waits, then sees `is_closed = true` and
refuses). Both outcomes are consistent.

Lock ordering rule (so two transactions can never wait for each other):
    leave year ids are ALWAYS locked in ascending id order,
    and a closing never locks an employee row.
"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.leave_year import LeaveYear


def _ids(year_ids) -> list[int]:
    return sorted({int(year_id) for year_id in year_ids if year_id is not None})


async def lock_years_shared(
    session: AsyncSession, year_ids
) -> list[LeaveYear]:
    """FOR SHARE on the given leave years (ascending id). Several writers may hold this."""
    ids = _ids(year_ids)
    if not ids:
        return []
    rows = (
        await session.scalars(
            select(LeaveYear)
            .where(LeaveYear.id.in_(ids))
            .order_by(LeaveYear.id)
            .with_for_update(read=True)
        )
    ).all()
    return list(rows)


async def lock_years_exclusive(
    session: AsyncSession, year_ids
) -> list[LeaveYear]:
    """FOR UPDATE on the given leave years (ascending id). Only one closer at a time."""
    ids = _ids(year_ids)
    if not ids:
        return []
    rows = (
        await session.scalars(
            select(LeaveYear)
            .where(LeaveYear.id.in_(ids))
            .order_by(LeaveYear.id)
            .with_for_update()
        )
    ).all()
    return list(rows)


def assert_years_open(years) -> None:
    """Call this AFTER taking the lock — the year may have been closed while we waited."""
    for year in years:
        if year.is_closed:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Leave year '{year.name}' is closed and cannot be changed.",
            )
