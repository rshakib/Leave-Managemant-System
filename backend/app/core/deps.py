"""Shared FastAPI dependencies: current user and role guards."""

from collections.abc import Awaitable, Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TOKEN_TYPE, decode_access_token
from app.db.session import get_session
from app.models.employee import Employee, EmployeeRole, Role, unique_roles
from app.services.password_rules import (
    MUST_CHANGE_PASSWORD_HEADER,
    may_use_application,
)

# Tells /docs where to get a token; the "Authorize" button posts to this URL.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def load_roles(session: AsyncSession, employee_id: int) -> list[Role]:
    rows = await session.scalars(
        select(EmployeeRole).where(EmployeeRole.employee_id == employee_id)
    )
    return unique_roles(row.role for row in rows.all())


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> Employee:
    """Resolve the Bearer token to an active employee.

    Roles are deliberately NOT read from the token: the employee and their
    roles are loaded from the database on every request, so deactivating an
    employee or changing their roles takes effect immediately (DECISIONS D-44).
    """
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token has expired.") from None
    except jwt.InvalidTokenError:
        raise _unauthorized("Invalid token.") from None

    if payload.get("type") != TOKEN_TYPE:
        raise _unauthorized("Invalid token.")

    try:
        employee_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise _unauthorized("Invalid token.") from None

    employee = await session.get(Employee, employee_id)
    if employee is None or not employee.is_active:
        raise _unauthorized("Invalid or inactive account.")

    # An admin created or reset this password, so the employee must choose their
    # own before doing anything else. Only the calls needed for that are allowed
    # through (D-190). This is the ONE place that enforces it: every protected
    # route goes through this dependency.
    if not may_use_application(
        must_change_password=employee.must_change_password, path=request.url.path
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must change your password before using the application.",
            headers={MUST_CHANGE_PASSWORD_HEADER: "true"},
        )

    return employee


def require_roles(*allowed: Role | str) -> Callable[..., Awaitable[Employee]]:
    """Build a dependency that allows only the given roles through."""
    required = {Role(role) for role in allowed}

    async def dependency(
        employee: Employee = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
    ) -> Employee:
        roles = set(await load_roles(session, employee.id))
        if not roles & required:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return employee

    return dependency
