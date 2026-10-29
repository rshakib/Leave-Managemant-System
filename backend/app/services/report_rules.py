"""Pure helpers for reports and CSV export (NFR-4).

No database, no HTTP — just formatting and validation that both the JSON and the
CSV endpoints must agree on.
"""

import csv
import datetime
import io
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

# A text cell starting with any of these can be run as a formula by a
# spreadsheet program ("CSV injection"), so we prefix it with an apostrophe.
DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

MAX_RANGE_DAYS = 1830  # about five years
MAX_LIMIT = 100

# Fixed words only — never anything the user typed.
SAFE_KINDS = ("balances", "history")


class ReportError(Exception):
    def __init__(self, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.http_status = http_status


def csv_safe(value):
    """Neutralise a TEXT cell that a spreadsheet might treat as a formula.

    Non-strings (numbers, dates, decimals) and None are returned unchanged
    (None becomes an empty cell).
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        return value
    stripped = value.lstrip(" ")
    if stripped[:1] in DANGEROUS_PREFIXES:
        return "'" + value
    return value


def format_decimal(value) -> str:
    """Always two decimals, a dot, and never exponent notation."""
    if value is None:
        return ""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ""
    quantised = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{quantised:.2f}"


def validate_filters(
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int | None = None,
    offset: int | None = None,
    max_range_days: int = MAX_RANGE_DAYS,
) -> None:
    if date_from is not None and date_to is not None:
        if date_from > date_to:
            raise ReportError("date_from must not be after date_to.")
        if (date_to - date_from).days > max_range_days:
            raise ReportError(
                f"The date range is longer than {max_range_days} days; "
                "please narrow it."
            )
    if limit is not None:
        if limit < 1:
            raise ReportError("limit must be at least 1.")
        if limit > MAX_LIMIT:
            raise ReportError(f"limit may be at most {MAX_LIMIT}.")
    if offset is not None and offset < 0:
        raise ReportError("offset must not be negative.")


def export_filename(report_kind: str, today: datetime.date) -> str:
    if report_kind not in SAFE_KINDS:
        raise ReportError("Unknown report kind.")
    return f"leave-{report_kind}-{today.isoformat()}.csv"


def org_local_iso(value: datetime.datetime | None, tz_name: str) -> str:
    """UTC instant -> ISO text in the organisation's timezone, no microseconds."""
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    local = value.astimezone(ZoneInfo(tz_name))
    return local.replace(microsecond=0).isoformat(sep=" ", timespec="seconds")


def csv_bytes(header: list[str], rows) -> bytes:
    """Small helper: one CSV chunk as UTF-8 (no BOM — the caller adds it)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    if header:
        writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")
