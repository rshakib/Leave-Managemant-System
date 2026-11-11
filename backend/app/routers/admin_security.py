import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Field, SQLModel

from app.core.deps import require_roles
from app.db.session import get_session
from app.models.auth_tokens import LoginAttempt
from app.models.employee import Role

router = APIRouter(prefix="/admin", tags=["admin-security"])

ADMIN_ONLY = [Depends(require_roles(Role.ADMIN))]


class LoginAttemptRead(SQLModel):
    id: int
    created_at: datetime.datetime
    email_normalized: str
    ip_hash: str
    success: bool


class LoginAttemptPage(SQLModel):
    rows: list[LoginAttemptRead]
    total: int
    limit: int
    offset: int


@router.get(
    "/login-attempts", response_model=LoginAttemptPage, dependencies=ADMIN_ONLY
)
async def list_login_attempts(
    email: str | None = None,
    success: bool | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> LoginAttemptPage:
    filters = []
    if email:
        filters.append(LoginAttempt.email_normalized.ilike(f"%{email.strip().lower()}%"))
    if success is not None:
        filters.append(LoginAttempt.success.is_(success))
    if date_from is not None:
        filters.append(
            LoginAttempt.created_at
            >= datetime.datetime.combine(date_from, datetime.time.min)
        )
    if date_to is not None:
        filters.append(
            LoginAttempt.created_at
            < datetime.datetime.combine(
                date_to + datetime.timedelta(days=1), datetime.time.min
            )
        )

    rows = (
        await session.scalars(
            select(LoginAttempt)
            .where(*filters)
            .order_by(LoginAttempt.created_at.desc(), LoginAttempt.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    total = (
        await session.scalar(
            select(func.count()).select_from(LoginAttempt).where(*filters)
        )
        or 0
    )
    return LoginAttemptPage(
        rows=[
            LoginAttemptRead(
                id=row.id,
                created_at=row.created_at,
                email_normalized=row.email_normalized,
                ip_hash=row.ip_hash[:8],
                success=row.success,
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
