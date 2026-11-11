"""Clear login lockouts for an email (``python -m app.cli.unlock_login --email ...``)."""

import argparse
import asyncio

from sqlalchemy import delete, select, update

from app.db.session import async_session_factory
from app.models.auth_tokens import LoginAttempt, RefreshToken
from app.models.employee import Employee


async def unlock(email: str) -> int:
    normalised = email.strip().lower()
    async with async_session_factory() as session:
        employee = await session.scalar(
            select(Employee).where(Employee.email == normalised)
        )
        if employee is None:
            print("No employee with that email — nothing to do.")
            return 1

        removed = (
            await session.execute(
                delete(LoginAttempt).where(
                    LoginAttempt.email_normalized == normalised
                )
            )
        ).rowcount or 0
        revoked = (
            await session.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.employee_id == employee.id,
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
            )
        ).rowcount or 0
        await session.commit()

    print(f"Deleted {removed} login attempt(s) for that email.")
    print(f"Revoked {revoked} refresh token(s) for employee {employee.employee_code}.")
    print("That email can sign in again now.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Clear a locked-out login.")
    parser.add_argument("--email", required=True, help="the employee's email")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(unlock(args.email)))


if __name__ == "__main__":
    main()
