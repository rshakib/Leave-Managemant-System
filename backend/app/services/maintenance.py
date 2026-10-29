"""Data retention (Phase 16D-1).

Prunes ONLY three things, in batches, so no long lock is ever taken:

* `login_attempt`                 — telemetry older than RETENTION_LOGIN_ATTEMPT_DAYS
* `refresh_token`                 — tokens that are unusable AND older than the cutoff
* `email_outbox` (+ its `email_attempt` rows) — ONLY emails that were SENT and are old

The audit log, the adjustment ledger, the carry-forward log and every business
table are NEVER pruned (see maintenance_rules.py).

A cleanup is a SYSTEM action with no human actor, so it writes no audit row —
consistent with D-148. It logs counts only (no personal data).
"""

import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session_factory
from app.services.maintenance_rules import retention_cutoffs

# A fixed key so every worker process agrees on the same advisory lock.
CLEANUP_LOCK_KEY = 4_242_016_001


def _batch_size() -> int:
    return max(1, int(getattr(settings, "cleanup_batch_size", 1000) or 1000))


async def _count(session: AsyncSession, sql: str, params: dict) -> int:
    return int(await session.scalar(text(sql), params) or 0)


async def _prune(session: AsyncSession, delete_sql: str, params: dict) -> int:
    """Delete in batches of N, committing after each batch."""
    total = 0
    while True:
        result = await session.execute(text(delete_sql), params)
        await session.commit()
        removed = result.rowcount or 0
        total += removed
        if removed < params["limit"]:
            return total


LOGIN_COUNT = (
    "SELECT count(*) FROM login_attempt WHERE created_at < :cutoff"
)
LOGIN_DELETE = """
    DELETE FROM login_attempt WHERE id IN (
        SELECT id FROM login_attempt WHERE created_at < :cutoff LIMIT :limit
    )
"""

TOKEN_COUNT = """
    SELECT count(*) FROM refresh_token
    WHERE COALESCE(replaced_at, revoked_at, expires_at) < :cutoff
"""
TOKEN_DELETE = """
    DELETE FROM refresh_token WHERE id IN (
        SELECT id FROM refresh_token
        WHERE COALESCE(replaced_at, revoked_at, expires_at) < :cutoff
        LIMIT :limit
    )
"""

OUTBOX_FILTER = "status = 'SENT' AND sent_at IS NOT NULL AND sent_at < :cutoff"
OUTBOX_COUNT = f"SELECT count(*) FROM email_outbox WHERE {OUTBOX_FILTER}"
# The attempts must go first: they point at the outbox row (FK). Both statements
# run inside the same transaction, so the child always disappears before its
# parent and no foreign key is ever violated.
ATTEMPT_DELETE = f"""
    DELETE FROM email_attempt WHERE outbox_id IN (
        SELECT id FROM email_outbox WHERE {OUTBOX_FILTER} LIMIT :limit
    )
"""
OUTBOX_DELETE = f"""
    DELETE FROM email_outbox WHERE id IN (
        SELECT id FROM email_outbox WHERE {OUTBOX_FILTER} LIMIT :limit
    )
"""


async def cleanup(dry_run: bool = True, now: datetime.datetime | None = None) -> dict:
    """Return {table: count}. Dry run counts, apply mode really deletes."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    cutoffs = retention_cutoffs(now, settings)
    limit = _batch_size()
    counts: dict[str, int] = {}

    async with async_session_factory() as session:
        login_params = {"cutoff": cutoffs["login_attempt"], "limit": limit}
        token_params = {"cutoff": cutoffs["refresh_token"], "limit": limit}
        email_params = {"cutoff": cutoffs["email_outbox"], "limit": limit}

        if dry_run:
            counts["login_attempt"] = await _count(session, LOGIN_COUNT, login_params)
            counts["refresh_token"] = await _count(session, TOKEN_COUNT, token_params)
            counts["email_outbox"] = await _count(session, OUTBOX_COUNT, email_params)
            counts["email_attempt"] = await _count(
                session,
                "SELECT count(*) FROM email_attempt WHERE outbox_id IN "
                f"(SELECT id FROM email_outbox WHERE {OUTBOX_FILTER})",
                email_params,
            )
            return counts

        counts["login_attempt"] = await _prune(session, LOGIN_DELETE, login_params)
        counts["refresh_token"] = await _prune(session, TOKEN_DELETE, token_params)

        removed_attempts = 0
        removed_outbox = 0
        while True:
            result = await session.execute(text(ATTEMPT_DELETE), email_params)
            attempts = result.rowcount or 0
            result = await session.execute(text(OUTBOX_DELETE), email_params)
            outbox = result.rowcount or 0
            await session.commit()
            removed_attempts += attempts
            removed_outbox += outbox
            if outbox < limit:
                break
        counts["email_attempt"] = removed_attempts
        counts["email_outbox"] = removed_outbox

    return counts


async def try_cleanup_lock() -> bool:
    """True when THIS process got the daily cleanup lock (advisory lock)."""
    async with async_session_factory() as session:
        got = bool(
            await session.scalar(
                text("SELECT pg_try_advisory_lock(:key)"),
                {"key": CLEANUP_LOCK_KEY},
            )
        )
        await session.commit()
        return got


async def release_cleanup_lock() -> None:
    async with async_session_factory() as session:
        await session.execute(
            text("SELECT pg_advisory_unlock(:key)"), {"key": CLEANUP_LOCK_KEY}
        )
        await session.commit()
