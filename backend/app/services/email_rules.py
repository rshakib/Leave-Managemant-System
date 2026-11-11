"""Pure email notification planning and delivery rules."""

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.services.day_calc import DayCalcError, DayType, calculate_chargeable_days

SUBMITTED = "SUBMITTED"
APPROVER_ACTED = "APPROVER_ACTED"
APPROVED = "APPROVED"
APPROVED_SUPERVISOR = "APPROVED_SUPERVISOR"
REJECTED = "REJECTED"
CANCELLED = "CANCELLED"
CANCELLED_EMPLOYEE = "CANCELLED_EMPLOYEE"
REMINDER = "REMINDER"
PASSWORD_RESET = "PASSWORD_RESET"
CURTAILMENT_SUBMITTED = "CURTAILMENT_SUBMITTED"
CURTAILMENT_APPROVED = "CURTAILMENT_APPROVED"
CURTAILMENT_REJECTED = "CURTAILMENT_REJECTED"

EVENTS = (
    SUBMITTED,
    APPROVER_ACTED,
    APPROVED,
    APPROVED_SUPERVISOR,
    REJECTED,
    CANCELLED,
    CANCELLED_EMPLOYEE,
    REMINDER,
    PASSWORD_RESET,
    CURTAILMENT_SUBMITTED,
    CURTAILMENT_APPROVED,
    CURTAILMENT_REJECTED,
)

REMINDER_AFTER_WORKING_DAYS = 2
BACKOFF_SECONDS = (60, 300, 1800, 7200, 43200)
MAX_HEADER_LENGTH = 200

_COMMON_FACTS = (
    "request_id",
    "employee_code",
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


PROTECTED_RECIPIENT_EMAILS: frozenset[str] = frozenset({
    "raton.hosen@solshare.com",
    "ishtiaque.ahmed@solshare.com",
})


def _text(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def clean_addresses(values) -> list[str]:
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
    return [
        addr
        for addr in clean_addresses(
            approver.get("email")
            for approver in facts.get("approvers", [])
            if approver.get("is_active", True) and approver.get("email")
        )
        if addr not in PROTECTED_RECIPIENT_EMAILS
    ]


def plan_emails(event, facts: dict) -> list[EmailSpec]:
    event = _text(event)
    request_id = facts.get("request_id")
    employee_email = (facts.get("employee_email") or "").strip().lower()
    if employee_email in PROTECTED_RECIPIENT_EMAILS:
        employee_email = ""
    actor_email = (facts.get("actor_email") or "").strip().lower()
    approver_emails = _active_approver_emails(facts)
    admin_cc = [
        addr
        for addr in clean_addresses(facts.get("notify_cc_admin_emails") or [])
        if addr not in PROTECTED_RECIPIENT_EMAILS
    ]

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
        approvers_list = facts.get("approvers")
        if approvers_list:
            specs = []
            for approver in approvers_list:
                email = (approver.get("email") or "").strip().lower()
                if not email or not approver.get("is_active", True) or email in PROTECTED_RECIPIENT_EMAILS:
                    continue
                approver_id = approver.get("id") or approver.get("approver_id") or email
                payload = _payload(facts, {
                    "approver_count": len(approver_emails),
                    "approver_name": approver.get("name"),
                    "token": approver.get("token"),
                })
                specs.append(
                    spec(
                        SUBMITTED,
                        [email],
                        [],
                        f"submitted:{request_id}:{approver_id}",
                        payload,
                    )
                )
            return specs
        return [
            spec(
                SUBMITTED,
                approver_emails,
                [],
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

        supervisor_email = (facts.get("supervisor_email") or "").strip().lower()
        has_supervisor_email = (
            supervisor_email
            and supervisor_email not in PROTECTED_RECIPIENT_EMAILS
            and supervisor_email != employee_email
        )

        if has_supervisor_email:
            cc = [addr for addr in cc if addr != supervisor_email]

        specs = [
            spec(
                APPROVED,
                [employee_email],
                cc,
                f"approved:{request_id}",
                _payload(facts, {"balances": facts.get("balances", [])}),
                drop_actor_cc=True,
            )
        ]

        if has_supervisor_email:
            specs.append(
                spec(
                    APPROVED_SUPERVISOR,
                    [supervisor_email],
                    [],
                    f"approved_supervisor:{request_id}",
                    _payload(
                        facts,
                        {
                            "balances": facts.get("balances", []),
                            "supervisor_name": facts.get("supervisor_name"),
                        },
                    ),
                )
            )

        return specs

    if event == APPROVED_SUPERVISOR:
        supervisor_email = (facts.get("supervisor_email") or "").strip().lower()
        if (
            supervisor_email
            and supervisor_email not in PROTECTED_RECIPIENT_EMAILS
            and supervisor_email != employee_email
        ):
            return [
                spec(
                    APPROVED_SUPERVISOR,
                    [supervisor_email],
                    [],
                    f"approved_supervisor:{request_id}",
                    _payload(
                        facts,
                        {
                            "balances": facts.get("balances", []),
                            "supervisor_name": facts.get("supervisor_name"),
                        },
                    ),
                )
            ]
        return []

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

    if event == CURTAILMENT_SUBMITTED:
        approvers_list = facts.get("approvers") or []
        specs = []
        for approver in approvers_list:
            email = (approver.get("email") or "").strip().lower()
            if not email or not approver.get("is_active", True) or email in PROTECTED_RECIPIENT_EMAILS:
                continue
            approver_id = approver.get("id") or approver.get("approver_id") or email
            payload = _payload(facts, {
                "approver_name": approver.get("name"),
                "curtailment_id": facts.get("curtailment_id"),
                "original_end_date": facts.get("original_end_date"),
                "curtailed_end_date": facts.get("curtailed_end_date"),
                "curtailed_day_type": facts.get("curtailed_day_type"),
                "days_to_refund": str(facts.get("days_to_refund", "0")),
                "new_days": str(facts.get("new_days", "0")),
                "original_days": str(facts.get("original_days", "0")),
                "curtailment_reason": facts.get("curtailment_reason") or facts.get("reason"),
            })
            specs.append(
                spec(
                    CURTAILMENT_SUBMITTED,
                    [email],
                    [],
                    f"curtailment_submitted:{facts.get('curtailment_id')}:{approver_id}",
                    payload,
                )
            )
        return specs

    if event == CURTAILMENT_APPROVED:
        return [
            spec(
                CURTAILMENT_APPROVED,
                [employee_email],
                approver_emails,
                f"curtailment_approved:{facts.get('curtailment_id')}",
                _payload(
                    facts,
                    {
                        "curtailment_id": facts.get("curtailment_id"),
                        "actor_name": facts.get("actor_name"),
                        "original_end_date": facts.get("original_end_date"),
                        "curtailed_end_date": facts.get("curtailed_end_date"),
                        "curtailed_day_type": facts.get("curtailed_day_type"),
                        "days_to_refund": str(facts.get("days_to_refund", "0")),
                        "new_days": str(facts.get("new_days", "0")),
                        "original_days": str(facts.get("original_days", "0")),
                        "decision_note": facts.get("decision_note"),
                        "balances": facts.get("balances", []),
                    },
                ),
                drop_actor_cc=True,
            )
        ]

    if event == CURTAILMENT_REJECTED:
        return [
            spec(
                CURTAILMENT_REJECTED,
                [employee_email],
                approver_emails,
                f"curtailment_rejected:{facts.get('curtailment_id')}",
                _payload(
                    facts,
                    {
                        "curtailment_id": facts.get("curtailment_id"),
                        "actor_name": facts.get("actor_name"),
                        "original_end_date": facts.get("original_end_date"),
                        "curtailed_end_date": facts.get("curtailed_end_date"),
                        "curtailed_day_type": facts.get("curtailed_day_type"),
                        "decision_note": facts.get("decision_note"),
                    },
                ),
                drop_actor_cc=True,
            )
        ]

    raise ValueError(f"Unknown email event '{event}'.")


def working_days_waiting(
    submitted_date: date, today: date, weekend_days, holidays
) -> int:
    """Count working days strictly after `submitted_date` up to `today`."""
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
    if attempt_number < 1:
        attempt_number = 1
    index = min(attempt_number, len(BACKOFF_SECONDS)) - 1
    return BACKOFF_SECONDS[index]


def next_state_after_failure(attempts: int, max_attempts: int) -> str:
    return "RETRY" if attempts < max_attempts else "FAILED"


def sanitize_header(text: str | None, limit: int = MAX_HEADER_LENGTH) -> str:
    """Strip line breaks and control characters from an email header value."""
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
