"""Login, refresh-token rotation and rate limiting (Phase 16C, D-163…D-166).

Everything that touches `refresh_token` / `login_attempt` lives here so the
routers stay thin.
"""

import datetime
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models.audit_log import AuditLog
from app.models.auth_tokens import LoginAttempt, RefreshToken
from app.models.employee import Employee
from app.services.audit import record
from app.services.password_rules import current_password_required
from app.services.security_rules import (
    EXPIRED,
    FAMILY_TOO_OLD,
    REUSED_THEFT,
    REUSED_WITHIN_GRACE,
    REVOKED,
    VALID,
    LoginLimits,
    check_password_policy,
    classify_refresh,
    decide_login,
    hash_ip,
    hash_token,
    new_token,
)

COOKIE_NAME = "refresh_token"

GENERIC_INVALID = "Incorrect email or password."
GENERIC_LOCKED = "Too many failed sign-in attempts. Please try again later."
MAX_PASSWORD_INPUT = 128

# Verifying against this when the email does not exist (or the account is
# inactive) keeps the response time the same, so timing cannot reveal which case
# applied (D-165).
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def normalise_email(value: str | None) -> str:
    return (value or "").strip().lower()


def limits() -> LoginLimits:
    return LoginLimits(
        pair_failures=settings.login_pair_limit,
        pair_window_seconds=settings.login_pair_window_minutes * 60,
        ip_failures=settings.login_ip_limit,
        ip_window_seconds=settings.login_ip_window_minutes * 60,
        email_failures=settings.login_email_limit,
        email_window_seconds=settings.login_email_window_minutes * 60,
    )


def ip_key_for(ip: str | None) -> str:
    return hash_ip(ip or "", settings.ip_hash_key)


def invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=GENERIC_INVALID,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _since(last_success, now, window_seconds: int) -> datetime.datetime:
    floor = now - datetime.timedelta(seconds=window_seconds)
    if last_success is not None and last_success > floor:
        return last_success
    return floor


async def _last_success(session: AsyncSession, *conditions) -> datetime.datetime | None:
    return await session.scalar(
        select(func.max(LoginAttempt.created_at)).where(
            LoginAttempt.success.is_(True), *conditions
        )
    )


async def _failures(session: AsyncSession, since, *conditions) -> list:
    rows = (
        await session.execute(
            select(LoginAttempt.created_at)
            .where(
                LoginAttempt.success.is_(False),
                LoginAttempt.created_at >= since,
                *conditions,
            )
            .order_by(LoginAttempt.created_at)
        )
    ).scalars().all()
    return list(rows)


async def record_attempt(session: AsyncSession, email: str, ip_key: str, success: bool):
    session.add(
        LoginAttempt(email_normalized=email[:254], ip_hash=ip_key, success=success)
    )


async def login(
    session: AsyncSession,
    email: str,
    password: str,
    ip: str | None,
    user_agent: str | None,
    now: datetime.datetime | None = None,
) -> tuple[Employee, str, str]:
    """Return (employee, access_token, refresh_token)."""
    now = now or utcnow()
    email = normalise_email(email)
    ip_key = ip_key_for(ip)

    # A password longer than the policy maximum cannot be a real password: answer
    # with the same generic 401, without paying for an argon2 verification.
    if len(password or "") > MAX_PASSWORD_INPUT:
        await record_attempt(session, email, ip_key, success=False)
        await session.commit()
        raise invalid_credentials()

    limits_now = limits()
    pair_conditions = (
        LoginAttempt.email_normalized == email,
        LoginAttempt.ip_hash == ip_key,
    )
    ip_conditions = (LoginAttempt.ip_hash == ip_key,)
    email_conditions = (LoginAttempt.email_normalized == email,)

    pair = await _failures(
        session,
        _since(await _last_success(session, *pair_conditions), now, limits_now.pair_window_seconds),
        *pair_conditions,
    )
    by_ip = await _failures(
        session,
        _since(await _last_success(session, *ip_conditions), now, limits_now.ip_window_seconds),
        *ip_conditions,
    )
    by_email = await _failures(
        session,
        _since(await _last_success(session, *email_conditions), now, limits_now.email_window_seconds),
        *email_conditions,
    )

    decision = decide_login(now, pair, by_ip, by_email, limits_now)
    employee = await session.scalar(select(Employee).where(Employee.email == email))

    if not decision.allowed:
        # One audit row per BLOCK (the pair key has just reached its limit), and
        # only when the email exists — never create rows for strangers.
        if employee is not None and len(pair) >= limits_now.pair_failures:
            # ONCE per block: if a LOGIN_LOCKED row already exists inside this
            # window we are still in the same block, so do not write another.
            already = await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.action == "LOGIN_LOCKED",
                    AuditLog.entity_type == "employee",
                    AuditLog.entity_id == employee.id,
                    AuditLog.created_at >= pair[0],
                )
            )
            if not already:
                await record(
                    session,
                    None,
                    "employee",
                    employee.id,
                    "LOGIN_LOCKED",
                    reason="too many failed sign-in attempts",
                )
                await session.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=GENERIC_LOCKED,
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )

    usable = employee is not None and employee.is_active
    confirmed = verify_password(
        password or "", employee.password_hash if usable else _DUMMY_HASH
    )
    if not (usable and confirmed):
        await record_attempt(session, email, ip_key, success=False)
        await session.commit()
        raise invalid_credentials()

    # Seamlessly upgrade legacy Django pbkdf2 hash to Argon2
    if employee.password_hash.startswith("pbkdf2_sha256$"):
        employee.password_hash = hash_password(password)
        session.add(employee)

    await record_attempt(session, email, ip_key, success=True)
    await record(session, employee.id, "employee", employee.id, "LOGIN_SUCCESS")

    raw, _row = await issue_refresh(
        session, employee, family_id=uuid.uuid4(), user_agent=user_agent, now=now
    )
    await session.commit()
    return employee, create_access_token(employee.id), raw


async def issue_refresh(
    session: AsyncSession,
    employee: Employee,
    family_id: uuid.UUID,
    user_agent: str | None,
    now: datetime.datetime,
    family_started_at: datetime.datetime | None = None,
) -> tuple[str, RefreshToken]:
    raw = new_token()
    row = RefreshToken(
        employee_id=employee.id,
        family_id=family_id,
        token_hash=hash_token(raw),
        issued_at=now,
        expires_at=now + datetime.timedelta(days=settings.refresh_token_days),
        family_started_at=family_started_at or now,
        user_agent=(user_agent or "")[:200] or None,
    )
    session.add(row)
    await session.flush()
    return raw, row


async def revoke_family(session: AsyncSession, family_id, now=None) -> int:
    result = await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now or utcnow())
    )
    return result.rowcount or 0


async def revoke_all(session: AsyncSession, employee_id: int, now=None) -> int:
    result = await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.employee_id == employee_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now or utcnow())
    )
    return result.rowcount or 0


def race_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "REFRESH_RACE", "message": "Refresh raced; retry once."},
    )


async def rotate(
    session: AsyncSession,
    raw_cookie: str | None,
    user_agent: str | None,
    now: datetime.datetime | None = None,
) -> tuple[Employee, str, str]:
    """Rotate a refresh token. Returns (employee, access_token, new_cookie)."""
    now = now or utcnow()
    if not raw_cookie:
        raise invalid_credentials()

    row = await session.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_token(raw_cookie)
        )
    )
    if row is None:
        raise invalid_credentials()

    grace = settings.refresh_reuse_grace_seconds
    max_days = settings.refresh_family_max_days
    outcome = classify_refresh(row, now, grace, max_days)

    if outcome in (EXPIRED, REVOKED, FAMILY_TOO_OLD):
        raise invalid_credentials()
    if outcome == REUSED_WITHIN_GRACE:
        raise race_error()
    if outcome == REUSED_THEFT:
        await revoke_family(session, row.family_id, now)
        await record(
            session,
            None,
            "employee",
            row.employee_id,
            "REFRESH_REUSE_DETECTED",
            reason="a refresh token that had already been rotated was presented again",
        )
        await session.commit()
        raise invalid_credentials()

    # VALID: lock the row, then re-read it FRESH (another tab may have rotated it
    # while we waited for the lock).
    await session.execute(
        select(RefreshToken.id).where(RefreshToken.id == row.id).with_for_update()
    )
    fresh = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.id == row.id)
        .execution_options(populate_existing=True)
    )
    if fresh is None:
        raise invalid_credentials()

    again = classify_refresh(fresh, now, grace, max_days)
    if again == REUSED_WITHIN_GRACE:
        raise race_error()
    if again != VALID:
        raise invalid_credentials()

    employee = await session.get(Employee, fresh.employee_id)
    if employee is None or not employee.is_active:
        await revoke_family(session, fresh.family_id, now)
        await session.commit()
        raise invalid_credentials()

    raw_new, new_row = await issue_refresh(
        session,
        employee,
        family_id=fresh.family_id,
        user_agent=user_agent,
        now=now,
        family_started_at=fresh.family_started_at,
    )
    fresh.replaced_at = now
    fresh.replaced_by_id = new_row.id
    fresh.last_used_at = now
    await session.commit()
    return employee, create_access_token(employee.id), raw_new


async def change_password(
    session: AsyncSession,
    employee: Employee,
    current_password: str,
    new_password: str,
    ip: str | None,
    user_agent: str | None,
) -> str:
    """Change the password, revoke the other sessions, return a new cookie value."""
    now = utcnow()
    ip_key = ip_key_for(ip)

    # The forced first change does not need the old password (D-198); every other
    # change does. A value that IS sent must still be correct — never ignored.
    needs_old = current_password_required(
        must_change_password=employee.must_change_password
    )
    if needs_old and not current_password:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The current password is required.",
        )
    if (needs_old or current_password) and not verify_password(
        current_password or "", employee.password_hash
    ):
        await record_attempt(
            session, normalise_email(employee.email), ip_key, success=False
        )
        await session.commit()
        raise invalid_credentials()

    problems = check_password_policy(new_password or "", employee.email)
    if problems:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problems)
    if verify_password(new_password or "", employee.password_hash):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The new password must be different from the current one.",
        )

    employee.password_hash = hash_password(new_password)
    # The employee has now chosen their own password (D-190).
    employee.must_change_password = False
    await revoke_all(session, employee.id, now)
    raw, _row = await issue_refresh(
        session, employee, family_id=uuid.uuid4(), user_agent=user_agent, now=now
    )
    await record(
        session,
        employee.id,
        "employee",
        employee.id,
        "PASSWORD_CHANGED",
        reason="the employee changed their own password",
    )
    await session.commit()
    return raw


async def logout(session: AsyncSession, raw_cookie: str | None) -> None:
    if not raw_cookie:
        return
    row = await session.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_token(raw_cookie)
        )
    )
    if row is None:
        return
    await revoke_family(session, row.family_id)
    await session.commit()


async def logout_all(session: AsyncSession, employee: Employee) -> int:
    revoked = await revoke_all(session, employee.id)
    await record(
        session,
        employee.id,
        "employee",
        employee.id,
        "SESSIONS_REVOKED",
        reason="the employee signed out of every device",
    )
    await session.commit()
    return revoked
