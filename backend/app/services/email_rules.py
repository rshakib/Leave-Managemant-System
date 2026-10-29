"""Pure email planning and delivery rules (FR-NOT-1, FR-NOT-2).

No database, no network: given an event and the facts, say exactly which emails
should exist. The worker later renders and sends them.

Recipient rule: an employee/approver is included only if they have an address and
are active; addresses are de-duplicated case-insensitively and never appear in
both `to` and `cc`. The person who performed the action is not Cc'd on their own
action (they already know) — except on a SUBMITTED email, where the employee is a
required Cc, and on the extra employee email sent when an admin cancels.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.services.day_calc import DayCalcError, DayType, calculate_chargeable_days

SUBMITTED = "SUBMITTED"
APPROVER_ACTED = "APPROVER_ACTED"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
CANCELLED = "CANCELLED"
CANCELLED_EMPLOYEE = "CANCELLED_EMPLOYEE"
REMINDER = "REMINDER"

EVENTS = (
    SUBMITTED,
    APPROVER_ACTED,
    APPROVED,
    REJECTED,
    CANCELLED,
    CANCELLED_EMPLOYEE,
    REMINDER,
)

REMINDER_AFTER_WORKING_DAYS = 2
BACKOFF_SECONDS = (60, 300, 1800, 7200, 43200)
MAX_HEADER_LENGTH = 200

_COMMON_FACTS = (
    "request_id",
    "employee_name",
    "leave_type_code",
    "leave_type_name",
    "start_date",
    "end_date",
    "day_type",
    "chargeable_days",
    "reason",
)


@dataclass(frozen=True)
class EmailSpec:
    event_type: str
    to_emails: tuple[str, ...]
    cc_emails: tuple[str, ...]
    dedupe_key: str
    payload: dict = field(default_factory=dict)


def _text(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def clean_addresses(values) -> list[str]:
    """Lowercase, trim, drop empties, de-duplicate while keeping order."""
    seen: list[str] = []
    for value in values:
        address = (value or "").strip().lower()
        if address and address not in seen:
            seen.append(address)
    return seen


def _payload(facts: dict, extra: dict | None = None) -> dict:
    payload = {key: facts.get(key) for key in _COMMON_FACTS}
    if extra:
        payload.update(extra)
    return payload


def _active_approver_emails(facts: dict) -> list[str]:
    return clean_addresses(
        approver.get("email")
        for approver in facts.get("approvers", [])
        if approver.get("is_active", True) and approver.get("email")
    )


def plan_emails(event, facts: dict) -> list[EmailSpec]:
    """Return the emails that `event` should produce."""
    event = _text(event)
    request_id = facts.get("request_id")
    employee_email = (facts.get("employee_email") or "").strip().lower()
    actor_email = (facts.get("actor_email") or "").strip().lower()
    approver_emails = _active_approver_emails(facts)
    admin_cc = clean_addresses(facts.get("notify_cc_admin_emails") or [])

    def spec(
        event_type: str,
        to,
        cc,
        key: str,
        payload: dict,
        drop_actor_cc: bool = False,
    ) -> EmailSpec:
        to_list = clean_addresses(to)
        cc_list = clean_addresses(cc)
        if drop_actor_cc:
            cc_list = [address for address in cc_list if address != actor_email]
        cc_list = [address for address in cc_list if address not in to_list]
        return EmailSpec(
            event_type=event_type,
            to_emails=tuple(to_list),
            cc_emails=tuple(cc_list),
            dedupe_key=key,
            payload=payload,
        )

    if event == SUBMITTED:
        return [
            spec(
                SUBMITTED,
                approver_emails,
                [employee_email],
                f"submitted:{request_id}",
                _payload(facts, {"approver_count": len(approver_emails)}),
            )
        ]

    if event == APPROVER_ACTED:
        still_pending = [
            approver.get("name")
            for approver in facts.get("approvers", [])
            if approver.get("is_active", True) and approver.get("status") == "PENDING"
        ]
        return [
            spec(
                APPROVER_ACTED,
                [employee_email],
                [],
                f"approver_acted:{request_id}:{facts.get('approval_id')}",
                _payload(
                    facts,
                    {
                        "actor_name": facts.get("actor_name"),
                        "pending_names": still_pending,
                    },
                ),
                drop_actor_cc=True,
            )
        ]

    if event == APPROVED:
        cc = list(approver_emails)
        if facts.get("notify_cc_admins_on_final"):
            cc += admin_cc
        return [
            spec(
                APPROVED,
                [employee_email],
                cc,
                f"approved:{request_id}",
                _payload(facts, {"balances": facts.get("balances", [])}),
                drop_actor_cc=True,
            )
        ]

    if event == REJECTED:
        return [
            spec(
                REJECTED,
                [employee_email],
                approver_emails,
                f"rejected:{request_id}",
                _payload(
                    facts,
                    {
                        "actor_name": facts.get("actor_name"),
                        "comment": facts.get("comment"),
                        "balances": facts.get("balances", []),
                    },
                ),
                drop_actor_cc=True,
            )
        ]

    if event == CANCELLED:
        specs = [
            spec(
                CANCELLED,
                approver_emails,
                [],
                f"cancelled:{request_id}",
                _payload(
                    facts,
                    {
                        "cancelled_by_name": facts.get("cancelled_by_name"),
                        "cancel_reason": facts.get("cancel_reason"),
                    },
                ),
                drop_actor_cc=True,
            )
        ]
        # An admin cancelling someone else's leave also tells the employee why.
        if facts.get("cancelled_by_admin") and employee_email:
            specs.append(
                spec(
                    CANCELLED_EMPLOYEE,
                    [employee_email],
                    [],
                    f"cancelled_employee:{request_id}",
                    _payload(
                        facts,
                        {
                            "cancelled_by_name": facts.get("cancelled_by_name"),
                            "cancel_reason": facts.get("cancel_reason"),
                            "balances": facts.get("balances", []),
                        },
                    ),
                )
            )
        return specs

    if event == REMINDER:
        return [
            spec(
                REMINDER,
                [facts.get("approver_email")],
                [],
                f"reminder:{facts.get('approver_id')}:{facts.get('local_date')}",
                {
                    "approver_name": facts.get("approver_name"),
                    "overdue": facts.get("overdue", []),
                    "local_date": facts.get("local_date"),
                },
            )
        ]

    raise ValueError(f"Unknown email event '{event}'.")


def working_days_waiting(
    submitted_date: date, today: date, weekend_days, holidays
) -> int:
    """Working days strictly AFTER `submitted_date`, up to and including `today`.

    Re-uses the pure day-calculation engine, in <=366-day chunks so the engine's
    range limit is never hit.
    """
    if today <= submitted_date:
        return 0

    total = 0
    cursor = submitted_date + timedelta(days=1)
    while cursor <= today:
        chunk_end = min(today, cursor + timedelta(days=365))
        try:
            result = calculate_chargeable_days(
                cursor, chunk_end, DayType.FULL_DAY, weekend_days, holidays
            )
        except DayCalcError:
            break
        total += int(result.chargeable_days)
        cursor = chunk_end + timedelta(days=1)
    return total


def is_overdue(
    submitted_date: date,
    today: date,
    weekend_days,
    holidays,
    threshold: int = REMINDER_AFTER_WORKING_DAYS,
) -> bool:
    return working_days_waiting(submitted_date, today, weekend_days, holidays) > threshold


def backoff_seconds(attempt_number: int) -> int:
    """60s, 5min, 30min, 2h, 12h — then stay at 12h."""
    if attempt_number < 1:
        attempt_number = 1
    index = min(attempt_number, len(BACKOFF_SECONDS)) - 1
    return BACKOFF_SECONDS[index]


def next_state_after_failure(attempts: int, max_attempts: int) -> str:
    return "RETRY" if attempts < max_attempts else "FAILED"


def sanitize_header(text: str | None, limit: int = MAX_HEADER_LENGTH) -> str:
    """Strip CR/LF and control characters so a header cannot be injected."""
    # Replace line breaks with a space FIRST, so removing them cannot glue two
    # words together; then drop any remaining control characters.
    flattened = (
        (text or "").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    )
    cleaned = "".join(
        character
        for character in flattened
        if character >= " " and character != "\x7f"
    )
    cleaned = " ".join(cleaned.split())
    return cleaned[:limit]
