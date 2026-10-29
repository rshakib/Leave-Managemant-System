import datetime
import zoneinfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import require_roles
from app.db.session import get_session
from app.models.audit_log import AuditLog, AuditLogPage, AuditLogRead, audit_read_rows
from app.models.employee import Employee, Role
from app.services.audit_rules import ENTITY_TYPES

router = APIRouter(prefix="/admin/audit-log", tags=["audit-log"])

ADMIN_ONLY = [Depends(require_roles(Role.ADMIN))]

# NOTE: there is deliberately NO create/update/delete endpoint here. The only
# writer is `services/audit.record()`, and the database trigger refuses edits.
# This router is READ-ONLY by design (DECISIONS D-147).


def _day_bounds(
    date_from: datetime.date | None, date_to: datetime.date | None
) -> tuple[datetime.datetime | None, datetime.datetime | None]:
    """Interpret the filter dates in the ORGANISATION's timezone.

    "25 October" means the local day, not the UTC day, so we turn the dates into
    UTC instants at both ends (the end is exclusive).
    """
    tz = zoneinfo.ZoneInfo(settings.org_timezone)
    start = (
        datetime.datetime.combine(date_from, datetime.time.min, tzinfo=tz)
        if date_from
        else None
    )
    end = (
        datetime.datetime.combine(
            date_to + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz
        )
        if date_to
        else None
    )
    return start, end


@router.get("", response_model=AuditLogPage, dependencies=ADMIN_ONLY)
async def list_audit_log(
    entity_type: str | None = None,
    entity_id: int | None = None,
    actor_id: int | None = None,
    action: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> AuditLogPage:
    if entity_type is not None and entity_type not in ENTITY_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown entity_type '{entity_type}'.",
        )
    limit = min(max(1, limit), 100)
    offset = max(0, offset)
    start, end = _day_bounds(date_from, date_to)

    filters = []
    if entity_type is not None:
        filters.append(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        filters.append(AuditLog.entity_id == entity_id)
    if actor_id is not None:
        filters.append(AuditLog.actor_id == actor_id)
    if action:
        filters.append(AuditLog.action.ilike(f"%{action}%"))
    if start is not None:
        filters.append(AuditLog.created_at >= start)
    if end is not None:
        filters.append(AuditLog.created_at < end)

    # Query 1: this page of rows. Query 2: the total. Query 3: the actor names.
    rows = (
        await session.scalars(
            select(AuditLog)
            .where(*filters)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    total = (
        await session.scalar(select(func.count()).select_from(AuditLog).where(*filters))
        or 0
    )
    names = await _actor_names(session, [row.actor_id for row in rows])

    return AuditLogPage(
        rows=audit_read_rows(rows, names), total=total, limit=limit, offset=offset
    )


@router.get("/{entry_id}", response_model=AuditLogRead, dependencies=ADMIN_ONLY)
async def get_audit_entry(
    entry_id: int,
    session: AsyncSession = Depends(get_session),
) -> AuditLogRead:
    row = await session.get(AuditLog, entry_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Audit entry not found.")
    names = await _actor_names(session, [row.actor_id])
    return audit_read_rows([row], names)[0]


async def _actor_names(
    session: AsyncSession, actor_ids: list[int | None]
) -> dict[int, str]:
    wanted = {actor_id for actor_id in actor_ids if actor_id is not None}
    if not wanted:
        return {}
    return {
        employee.id: employee.full_name
        for employee in (
            await session.scalars(select(Employee).where(Employee.id.in_(wanted)))
        ).all()
    }
