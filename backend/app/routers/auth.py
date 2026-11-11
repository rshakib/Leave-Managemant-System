import datetime
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel, select

from app.core.config import settings
from app.core.deps import get_current_user, load_roles
from app.core.security import hash_password
from app.db.session import get_session
from app.models.auth_tokens import PasswordResetToken
from app.models.email_outbox import EmailOutbox, EmailStatus
from app.models.employee import Employee, EmployeeRead, employee_to_read
from app.services import auth_service
from app.services import sessions as sessions_service
from app.services.audit import record
from app.services.email_rules import PASSWORD_RESET
from app.services.security_rules import check_password_policy, client_ip, hash_token

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_PATH = "/auth"


class ChangePasswordIn(SQLModel):
    current_password: str | None = None
    new_password: str


class ForgotPasswordIn(SQLModel):
    email: str


class ResetPasswordIn(SQLModel):
    token: str
    new_password: str


def _ip(request: Request) -> str:
    return client_ip(
        request.client.host if request.client else "",
        request.headers.get("x-forwarded-for"),
        settings.trusted_proxy_count,
    )


def _set_cookie(response: Response, raw: str) -> None:
    response.set_cookie(
        key=auth_service.COOKIE_NAME,
        value=raw,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path=COOKIE_PATH,
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(
        key=auth_service.COOKIE_NAME,
        path=COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )


def _origin_allowed(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True
    return origin in settings.cors_origins_list


@router.post("/login")
async def login(
    request: Request,
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    employee, access_token, raw_refresh = await auth_service.login(
        session,
        form.username,
        form.password,
        ip=_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    _set_cookie(response, raw_refresh)
    response.headers["Cache-Control"] = "no-store"
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "must_change_password": employee.must_change_password,
    }


@router.post("/refresh")
async def refresh(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    if not _origin_allowed(request):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Cross-origin token refresh is not allowed.",
        )

    raw = request.cookies.get(auth_service.COOKIE_NAME)
    try:
        _employee, access_token, raw_new = await auth_service.rotate(
            session, raw, request.headers.get("user-agent")
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            cleared = JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": exc.detail}
            )
            _clear_cookie(cleared)
            cleared.headers["Cache-Control"] = "no-store"
            return cleared
        raise

    response = JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"access_token": access_token, "token_type": "bearer"},
    )
    _set_cookie(response, raw_new)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await auth_service.logout(
        session, request.cookies.get(auth_service.COOKIE_NAME)
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_cookie(response)
    return response


@router.post("/logout-all")
async def logout_all(
    request: Request,
    employee: Employee = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    revoked = await auth_service.logout_all(session, employee)
    return {"revoked": revoked}


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordIn,
    request: Request,
    employee: Employee = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    raw_new = await auth_service.change_password(
        session,
        employee,
        current_password=payload.current_password,
        new_password=payload.new_password,
        ip=_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    response = JSONResponse(status_code=status.HTTP_200_OK, content={"ok": True})
    _set_cookie(response, raw_new)
    response.headers["Cache-Control"] = "no-store"
    return response


class SessionRead(SQLModel):
    id: str
    device: str
    current: bool
    created_at: datetime.datetime
    last_used_at: datetime.datetime
    expires_at: datetime.datetime


@router.get("/sessions", response_model=list[SessionRead])
async def list_my_sessions(
    request: Request,
    employee: Employee = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[SessionRead]:
    rows = await sessions_service.list_sessions(
        session, employee, request.cookies.get(auth_service.COOKIE_NAME)
    )
    return [SessionRead(**row) for row in rows]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def end_session(
    session_id: uuid.UUID,
    employee: Employee = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await sessions_service.revoke_session(session, employee, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=EmployeeRead)
async def read_me(
    employee: Employee = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> EmployeeRead:
    has_subordinates = await session.scalar(
        select(Employee.id).where(
            Employee.supervisor_id == employee.id,
            Employee.is_active.is_(True),
        ).limit(1)
    )
    is_sup = has_subordinates is not None
    return employee_to_read(employee, await load_roles(session, employee.id), is_supervisor=is_sup)


@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Trigger a password reset link email.

    Always returns 200 with the same message to prevent user enumeration.
    """
    email = payload.email.strip().lower()
    if email:
        employee = await session.scalar(
            select(Employee).where(func.lower(Employee.email) == email)
        )
        if employee is not None and employee.is_active:
            raw_token = secrets.token_urlsafe(32)
            token_hashed = hash_token(raw_token)
            now = datetime.datetime.now(datetime.timezone.utc)
            expires_at = now + datetime.timedelta(minutes=30)
            client_ip_hash = hash_token(_ip(request))

            reset_record = PasswordResetToken(
                employee_id=employee.id,
                token_hash=token_hashed,
                expires_at=expires_at,
                ip_hash=client_ip_hash,
            )
            session.add(reset_record)

            session.add(
                EmailOutbox(
                    event_type=PASSWORD_RESET,
                    to_emails=[employee.email],
                    payload={
                        "token": raw_token,
                        "employee_name": employee.full_name,
                    },
                    status=EmailStatus.PENDING,
                )
            )
            await session.commit()

    return {
        "ok": True,
        "message": "If this email is registered, a password reset link has been sent to your inbox.",
    }


@router.get("/verify-reset-token")
async def verify_reset_token(
    token: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Check if a password reset token is valid and unexpired."""
    token_hashed = hash_token(token)
    now = datetime.datetime.now(datetime.timezone.utc)
    record_obj = await session.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hashed,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
    )
    if record_obj is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This password reset link is invalid or has expired.",
        )
    employee = await session.get(Employee, record_obj.employee_id)
    if employee is None or not employee.is_active:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This account is no longer active.",
        )
    return {"valid": True, "email": employee.email}


@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordIn,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Consume a valid reset token and update the password."""
    token_hashed = hash_token(payload.token)
    now = datetime.datetime.now(datetime.timezone.utc)
    record_obj = await session.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hashed,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        ).with_for_update()
    )
    if record_obj is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This password reset link is invalid or has expired. Please request a new one.",
        )
    employee = await session.get(Employee, record_obj.employee_id)
    if employee is None or not employee.is_active:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This account is no longer active.",
        )

    problems = check_password_policy(payload.new_password, employee.email)
    if problems:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problems)

    employee.password_hash = hash_password(payload.new_password)
    employee.must_change_password = False
    record_obj.used_at = now

    await auth_service.revoke_all(session, employee.id)

    await record(
        session,
        employee.id,
        "employee",
        employee.id,
        "PASSWORD_RESET",
        reason="password reset via email reset link",
    )
    await session.commit()

    return {
        "ok": True,
        "message": "Password has been successfully reset. You can now sign in with your new password.",
    }
