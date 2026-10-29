"""Render an outbox payload into subject + plain text + HTML.

Jinja2 autoescape is ON for `.html` templates and OFF for `.txt`, so user input
(reason, names) is escaped exactly where it matters.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.services.email_rules import (
    APPROVED,
    APPROVER_ACTED,
    CANCELLED,
    CANCELLED_EMPLOYEE,
    REJECTED,
    REMINDER,
    SUBMITTED,
    sanitize_header,
)

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "email"

MAX_REASON = 300

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html", "xml")),
    trim_blocks=True,
    lstrip_blocks=True,
)

SUBJECTS = {
    SUBMITTED: "Leave request from {employee_name} ({leave_type_code})",
    APPROVER_ACTED: "{actor_name} approved a leave request ({employee_name})",
    APPROVED: "Leave request approved ({employee_name})",
    REJECTED: "Leave request rejected ({employee_name})",
    CANCELLED: "Leave request cancelled ({employee_name})",
    CANCELLED_EMPLOYEE: "Your leave request was cancelled by an administrator",
    REMINDER: "Reminder: {count} leave request(s) waiting for your decision",
}


def shorten(value, limit: int = MAX_REASON) -> str:
    text = (value or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _link(event_type: str, payload: dict, base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if event_type == REMINDER:
        return f"{base}/approvals"
    return f"{base}/leave-requests/{payload.get('request_id')}"


def _subject(event_type: str, context: dict) -> str:
    template = SUBJECTS[event_type]
    safe = {key: ("" if value is None else value) for key, value in context.items()}
    try:
        rendered = template.format(**safe)
    except KeyError:
        rendered = template
    return sanitize_header(rendered)


def render_preview(
    event_type: str, payload: dict | None, base_url: str
) -> tuple[str | None, str | None, str | None]:
    """Render for the administrator's preview screen — NEVER raises.

    An extra or unexpected row must not turn `GET /admin/emails/{id}` into a 500,
    so anything we cannot render comes back as (None, None, None).
    """
    try:
        return render_email(event_type, payload or {}, base_url)
    except Exception:  # noqa: BLE001 - a preview is never worth a 500
        return None, None, None


def render_email(
    event_type: str, payload: dict, base_url: str
) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body)."""
    if event_type not in SUBJECTS:
        raise ValueError(f"Unknown email event '{event_type}'.")

    context = dict(payload)
    context["reason_short"] = shorten(payload.get("reason"))
    context["link"] = _link(event_type, payload, base_url)
    context["base_url"] = base_url
    context["count"] = len(payload.get("overdue") or [])

    subject = _subject(event_type, context)
    name = event_type.lower()
    text = _env.get_template(f"{name}.txt").render(**context)
    html = _env.get_template(f"{name}.html").render(**context)
    return subject, text, html
