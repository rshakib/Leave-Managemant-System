import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from app.core.config import settings
from app.core.deps import get_current_user, load_roles
from app.db.session import get_session
from app.models.employee import Employee, EmployeeRead, employee_to_read
from app.services import auth_service
from app.services import sessions as sessions_service
from app.services.security_rules import client_ip

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_PATH = "/auth"


class ChangePasswordIn(SQLModel):
    # Optional ONLY for the forced first change (D-198). A normal password change
    # still requires it, and a value that IS sent is always verified.
    current_password: str | None = None
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
    """CSRF guard for the cookie-based endpoints.

    A browser always sends Origin on a cross-site POST, so an Origin that is not
    one of our own front-ends means somebody else's page is trying to use the
    cookie. A request WITHOUT an Origin is allowed on purpose: non-browser
    clients (curl, the test suite, mobile apps) send no Origin, and they carry no
    ambient cookie authority of their own.
    """
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
    """Exchange email + password for an access token and a refresh cookie."""
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
        # The front-end sends the user straight to "change password" when this is
        # true, instead of letting them into the app (D-190).
        "must_change_password": employee.must_change_password,
    }


@router.post("/refresh")
async def refresh(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Rotate the refresh cookie and hand out a new access token."""
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
    """One signed-in device. No token, no hash and no IP address is ever shown."""

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
    """Where is this account signed in? Taken from the token, so it can only
    ever return the caller's own sessions (the same rule as D-69/D-84)."""
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
    """End ONE of the caller's own sessions (for example a laptop left behind)."""
    await sessions_service.revoke_session(session, employee, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=EmployeeRead)
async def read_me(
    employee: Employee = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> EmployeeRead:
    return employee_to_read(employee, await load_roles(session, employee.id))
