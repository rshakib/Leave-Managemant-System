"""Pure formatting, sanitization, and filter validation rules for reports."""

import csv
import datetime
import io
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

MAX_RANGE_DAYS = 1830
MAX_LIMIT = 100

SAFE_KINDS = ("balances", "history")


class ReportError(Exception):
    def __init__(self, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.http_status = http_status


def csv_safe(value):
    """Escape leading formula characters in text cells to prevent CSV injection."""
    if value is None:
        return ""
    if not isinstance(value, str):
        return value
    stripped = value.lstrip(" ")
    if stripped[:1] in DANGEROUS_PREFIXES:
        return "'" + value
    return value


def format_decimal(value) -> str:
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
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    local = value.astimezone(ZoneInfo(tz_name))
    return local.replace(microsecond=0).isoformat(sep=" ", timespec="seconds")


def csv_bytes(header: list[str], rows) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    if header:
        writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")
