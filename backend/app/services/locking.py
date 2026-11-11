"""Leave-year row locking helpers."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.leave_year import LeaveYear


def _ids(year_ids) -> list[int]:
    return sorted({int(year_id) for year_id in year_ids if year_id is not None})


async def lock_years_shared(
    session: AsyncSession, year_ids
) -> list[LeaveYear]:
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
    for year in years:
        if year.is_closed:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Leave year '{year.name}' is closed and cannot be changed.",
            )
