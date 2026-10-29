"""The employee's own list of signed-in devices (DECISIONS D-191).

Only the SHAPE of a session is exposed — a device name, when it started, when it
was last used and when it expires. The token hash never leaves the database, and
no IP address is stored or shown (D-163).
"""

import datetime
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_tokens import RefreshToken
from app.models.employee import Employee
from app.services.audit import record
from app.services.auth_service import revoke_family, utcnow
from app.services.security_rules import hash_token
from app.services.session_rules import is_active_session, sort_sessions, summarise_user_agent
from app.core.config import settings


async def family_for_cookie(session: AsyncSession, raw_cookie: str | None) -> uuid.UUID | None:
    """Which family does THIS browser's refresh cookie belong to?"""
    if not raw_cookie:
        return None
    return await session.scalar(
        select(RefreshToken.family_id).where(RefreshToken.token_hash == hash_token(raw_cookie))
    )


async def list_sessions(
    session: AsyncSession, employee: Employee, raw_cookie: str | None
) -> list[dict]:
    now = utcnow()
    rows = await session.scalars(
        select(RefreshToken)
        .where(RefreshToken.employee_id == employee.id, RefreshToken.revoked_at.is_(None))
        .order_by(RefreshToken.issued_at.desc())
    )
    current_family = await family_for_cookie(session, raw_cookie)

    sessions: list[dict] = []
    for row in rows.all():
        if not is_active_session(
            revoked_at=row.revoked_at,
            replaced_at=row.replaced_at,
            expires_at=row.expires_at,
            family_started_at=row.family_started_at,
            now=now,
            family_max_days=settings.refresh_family_max_days,
        ):
            continue
        sessions.append(
            {
                "id": str(row.family_id),
                "device": summarise_user_agent(row.user_agent),
                "current": current_family is not None and row.family_id == current_family,
                "created_at": row.family_started_at,
                "last_used_at": row.last_used_at or row.issued_at,
                "expires_at": row.family_started_at
                + datetime.timedelta(days=settings.refresh_family_max_days),
            }
        )
    return sort_sessions(sessions)


async def revoke_session(
    session: AsyncSession, employee: Employee, family_id: uuid.UUID
) -> int:
    """End ONE of the employee's own sessions.

    A family that does not belong to the caller answers 404, exactly like a
    missing one, so the API never reveals that somebody else's session exists
    (the same rule as DECISIONS D-89).
    """
    owned = await session.scalar(
        select(func.count())
        .select_from(RefreshToken)
        .where(
            RefreshToken.employee_id == employee.id,
            RefreshToken.family_id == family_id,
        )
    )
    if not owned:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="That session was not found."
        )

    revoked = await revoke_family(session, family_id)
    await record(
        session,
        employee.id,
        "employee",
        employee.id,
        "SESSION_REVOKED",
        new={"sessions_ended": revoked},
        reason="the employee ended one signed-in device",
    )
    await session.commit()
    return revoked
