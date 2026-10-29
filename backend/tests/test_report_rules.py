"""Tests for the pure report helpers (CSV safety, formatting, validation)."""

import datetime
from decimal import Decimal

import pytest

from app.services.report_rules import (
    ReportError,
    csv_safe,
    export_filename,
    format_decimal,
    org_local_iso,
    validate_filters,
)


# --- CSV injection ---------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["=1+1", "+1", "-1", "@cmd", "\tcmd", "\rcmd", " =1+1", "  @x"],
)
def test_dangerous_prefixes_are_neutralised(value):
    safe = csv_safe(value)
    assert safe.startswith("'")
    assert safe.endswith(value)


def test_a_number_is_never_touched():
    assert csv_safe(-5) == -5
    assert csv_safe(Decimal("-5.00")) == Decimal("-5.00")


def test_a_normal_sentence_containing_equals_is_untouched():
    assert csv_safe("total = 3 days") == "total = 3 days"


def test_bengali_text_is_unchanged():
    text = "জাহিদ হাসান"
    assert csv_safe(text) == text


def test_none_becomes_an_empty_cell():
    assert csv_safe(None) == ""


# --- decimal formatting ----------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0.00"),
        (0.5, "0.50"),
        (12, "12.00"),
        ("3.1", "3.10"),
        (Decimal("2"), "2.00"),
        (Decimal("1E+3"), "1000.00"),
        (Decimal("12345678901234567890.5"), "12345678901234567890.50"),
    ],
)
def test_format_decimal(value, expected):
    assert format_decimal(value) == expected


def test_format_decimal_of_none_is_empty():
    assert format_decimal(None) == ""


# --- filter validation -----------------------------------------------------


def test_date_from_after_date_to_is_refused():
    with pytest.raises(ReportError):
        validate_filters(date_from=datetime.date(2026, 2, 1), date_to=datetime.date(2026, 1, 1))


def test_a_range_of_at_most_1830_days_is_allowed():
    validate_filters(
        date_from=datetime.date(2020, 1, 1), date_to=datetime.date(2025, 1, 4)
    )  # 1830 days
    with pytest.raises(ReportError):
        validate_filters(
            date_from=datetime.date(2020, 1, 1), date_to=datetime.date(2025, 1, 5)
        )


def test_limit_and_offset_limits():
    validate_filters(limit=1)
    validate_filters(limit=100)
    with pytest.raises(ReportError):
        validate_filters(limit=0)
    with pytest.raises(ReportError):
        validate_filters(limit=101)
    with pytest.raises(ReportError):
        validate_filters(offset=-1)


def test_only_one_date_is_allowed():
    validate_filters(date_from=datetime.date(2026, 1, 1))
    validate_filters(date_to=datetime.date(2026, 1, 1))


# --- filenames -------------------------------------------------------------


def test_export_filename_is_built_from_fixed_words_and_the_date():
    name = export_filename("balances", datetime.date(2026, 10, 25))
    assert name == "leave-balances-2026-10-25.csv"
    assert all(character.isalnum() or character in "-._" for character in name)
    assert export_filename("history", datetime.date(2026, 10, 25)) == (
        "leave-history-2026-10-25.csv"
    )


def test_unknown_report_kind_is_refused():
    with pytest.raises(ReportError):
        export_filename("../etc/passwd", datetime.date(2026, 10, 25))


# --- timezone --------------------------------------------------------------


def test_utc_is_converted_to_the_organisation_timezone():
    value = datetime.datetime(2026, 10, 25, 20, 0, tzinfo=datetime.timezone.utc)
    assert org_local_iso(value, "Asia/Dhaka") == "2026-10-26 02:00:00+06:00"


def test_conversion_across_midnight_changes_the_date():
    value = datetime.datetime(2026, 10, 25, 23, 30, tzinfo=datetime.timezone.utc)
    assert org_local_iso(value, "Asia/Dhaka").startswith("2026-10-26")


def test_utc_stays_the_same_in_utc():
    value = datetime.datetime(2026, 10, 25, 12, 0, 5, 123456, tzinfo=datetime.timezone.utc)
    assert org_local_iso(value, "UTC") == "2026-10-25 12:00:05+00:00"


def test_none_timestamp_is_empty():
    assert org_local_iso(None, "UTC") == ""
