import asyncio
import datetime
import logging

from fastapi import Depends, FastAPI, HTTPException
from contextlib import asynccontextmanager

from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.routers.events import router as events_router
from app.services import events
from app.services.security_rules import PLACEHOLDER_SECRETS, validate_production_settings
from app.routers import (
    admin_audit_log,
    admin_security,
    balance_adjustments,
    admin_emails,
    year_closing,
    reports,
    approvals,
    approvers,
    auth,
    calendar,
    curtailments,
    departments,
    divisions,
    employees,
    holidays,
    leave_assignments,
    leave_balances,
    leave_requests,
    leave_types,
    leave_years,
    weekends,
)

logger = logging.getLogger(__name__)

# --- fail-fast configuration (NFR-1, D-166) -----------------------------
# In production the app REFUSES to start with an unsafe configuration instead of
# running insecurely. The list never contains a secret value.
_config_problems = validate_production_settings(settings)
if str(settings.app_env).lower() == "production" and _config_problems:
    raise RuntimeError(
        "Refusing to start: APP_ENV=production but the configuration is unsafe:\n  - "
        + "\n  - ".join(_config_problems)
    )
if str(settings.app_env).lower() != "production":
    _secret = (settings.jwt_secret or "").strip()
    if len(_secret) < 32 or _secret.lower() in PLACEHOLDER_SECRETS:
        logging.getLogger("security").warning(
            "JWT_SECRET is short or a placeholder — fine for development, never "
            "for production."
        )

_docs = settings.docs_enabled
@asynccontextmanager
async def lifespan(_app):
    from sqlalchemy import text
    from app.db.session import engine

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        pass

    worker_task = None
    if settings.embedded_email_worker and settings.app_env.lower() != "test":
        from app.worker import drain_once, reminder_tick

        async def _embedded_worker_loop():
            logger.info(
                "Embedded email worker started (interval: %ss)",
                settings.embedded_worker_interval_seconds,
            )
            last_reminder = datetime.datetime.now(datetime.timezone.utc)
            while True:
                try:
                    await drain_once()
                    now = datetime.datetime.now(datetime.timezone.utc)
                    if (now - last_reminder).total_seconds() >= 900:
                        await reminder_tick()
                        last_reminder = now
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.warning("Embedded email worker error: %s", exc)

                try:
                    await asyncio.sleep(settings.embedded_worker_interval_seconds)
                except asyncio.CancelledError:
                    break
            logger.info("Embedded email worker stopped")

        worker_task = asyncio.create_task(_embedded_worker_loop())

    yield

    if worker_task is not None:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    await engine.dispose()


app = FastAPI(
    title=settings.project_name,
    lifespan=lifespan,
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)

# Allow the browser app (Vite dev server) to call this API. Explicit origins
# only — a wildcard "*" is never used.
app.add_middleware(
    CORSMiddleware,
    # Explicit origins only — never "*" (a wildcard cannot be combined with
    # credentials anyway, and it would let any site use the cookie).
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    # The browser may READ these headers: Retry-After (the login countdown) and
    # Content-Disposition (the CSV download filename).
    expose_headers=["Retry-After", "Content-Disposition"],
)

app.include_router(auth.router)
app.include_router(events_router)
app.include_router(divisions.router)
app.include_router(departments.router)
app.include_router(employees.router)
app.include_router(leave_years.router)
app.include_router(leave_types.router)
app.include_router(leave_assignments.router)
app.include_router(leave_balances.router)
app.include_router(weekends.router)
app.include_router(holidays.router)
app.include_router(calendar.router)
app.include_router(approvers.router)
app.include_router(leave_requests.router)
app.include_router(curtailments.router)
app.include_router(approvals.router)
app.include_router(admin_emails.router)
@app.middleware("http")
async def security_headers(request, call_next):
    """Defence in depth: cheap headers on EVERY response, errors included."""
    response = await call_next(request)

    # Any successful write tells the open browser tabs to refetch (SSE).
    if request.method != "GET" and response.status_code < 400:
        events.publish()
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    path = request.url.path
    if path.startswith("/auth") or path.startswith("/admin"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(admin_audit_log.router)
app.include_router(admin_security.router)
app.include_router(balance_adjustments.router)
app.include_router(reports.router)
app.include_router(year_closing.router)


from app.services.report_rules import ReportError


@app.exception_handler(ReportError)
async def _report_error_handler(request, exc: ReportError):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=exc.http_status, content={"detail": exc.message})



from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from app.models.email_outbox import EmailOutbox, EmailStatus
from app.services.maintenance_rules import readiness_state


def _head_revision() -> str | None:
    """The revision the CODE expects (read from alembic/versions)."""
    config = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    return ScriptDirectory.from_config(config).get_current_head()


@app.get("/health/ready")
async def health_ready(session: AsyncSession = Depends(get_session)):
    """Readiness: database reachable, migrations current, email not stuck.

    It never exposes versions, revisions, hostnames or error text — only short
    reasons such as "database" or "migrations".
    """
    db_ok = True
    current = None
    oldest_age = None
    try:
        await session.execute(text("SELECT 1"))
        current = await session.scalar(text("SELECT version_num FROM alembic_version"))
        oldest = await session.scalar(
            select(func.min(EmailOutbox.created_at)).where(
                EmailOutbox.status == EmailStatus.PENDING
            )
        )
        if oldest is not None:
            oldest_age = (
                datetime.datetime.now(datetime.timezone.utc) - oldest
            ).total_seconds()
    except Exception:
        db_ok = False

    state = readiness_state(
        db_ok,
        current,
        _head_revision() if db_ok else None,
        oldest_age,
        settings.retention_stale_email_minutes * 60,
    )
    if state.ok:
        return {"status": "ok", "warnings": state.warnings}
    return JSONResponse(
        status_code=503, content={"status": "unavailable", "reasons": state.reasons}
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/db")
async def health_db(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    """Check the database is reachable by running SELECT 1."""
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        # Log only the exception type so the connection URL is never written out.
        logger.warning("Database health check failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="database unavailable") from None
    return {"database": "ok"}
