"""Tests for the pure audit rules."""

import datetime
import uuid
from decimal import Decimal
from enum import Enum

import pytest

from app.services.audit_rules import (
    AuditValueError,
    changed_fields,
    limit_size,
    redact,
    to_jsonable,
    validate_entry,
)


class Colour(Enum):
    RED = "red"
    BLUE = "blue"


# --- to_jsonable -----------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("2.50"), "2.50"),
        (Decimal("0.5"), "0.5"),
        (Decimal("12345.67"), "12345.67"),
        (Decimal("1E+3"), "1000"),
    ],
)
def test_decimals_keep_their_exact_digits(value, expected):
    assert to_jsonable(value) == expected


def test_dates_and_enums_and_uuids():
    assert to_jsonable(datetime.date(2026, 10, 25)) == "2026-10-25"
    assert to_jsonable(
        datetime.datetime(2026, 10, 25, 20, 0, tzinfo=datetime.timezone.utc)
    ) == "2026-10-25T20:00:00+00:00"
    assert to_jsonable(Colour.RED) == "red"
    identifier = uuid.uuid4()
    assert to_jsonable(identifier) == str(identifier)


def test_sets_become_sorted_lists():
    assert to_jsonable({3, 1, 2}) == [1, 2, 3]
    assert to_jsonable({"b", "a"}) == ["a", "b"]


def test_nested_structures_are_converted_recursively():
    value = {
        "days": Decimal("2.00"),
        "when": datetime.date(1997, 12, 31),
        "rows": [{"n": Decimal("0.5")}, Colour.BLUE],
        "inner": {"deep": Decimal("1.10")},
    }
    assert to_jsonable(value) == {
        "days": "2.00",
        "when": "1997-12-31",
        "rows": [{"n": "0.5"}, "blue"],
        "inner": {"deep": "1.10"},
    }


def test_a_plain_value_passes_through():
    assert to_jsonable("text") == "text"
    assert to_jsonable(5) == 5
    assert to_jsonable(True) is True
    assert to_jsonable(None) is None


def test_an_unsupported_value_raises_a_clear_error():
    class Widget:
        pass

    with pytest.raises(AuditValueError) as error:
        to_jsonable(Widget())
    assert "Widget" in str(error.value)


def test_an_unsupported_value_inside_a_structure_raises():
    with pytest.raises(AuditValueError):
        to_jsonable({"ok": 1, "bad": object()})


# --- redact ----------------------------------------------------------------


def test_redaction_is_case_insensitive_and_covers_all_the_names():
    data = {
        "password": "hunter2",
        "Password": "hunter2",
        "passwordHash": "$argon2id$...",
        "PASSWORD_HASH": "$argon2id$...",
        "passwd": "x",
        "api_secret": "x",
        "access_token": "x",
        "Authorization": "Bearer x",
        "jwt_secret": "x",
        "api_key": "x",
    }
    cleaned = redact(data)
    assert all(value == "[REDACTED]" for value in cleaned.values())
    assert set(cleaned) == set(data)  # the keys stay


def test_a_harmless_key_containing_pass_is_not_redacted():
    cleaned = redact({"passenger": "Alice", "compassion": 1})
    assert cleaned == {"passenger": "Alice", "compassion": 1}


def test_redaction_works_at_every_nesting_level():
    data = {
        "employee": {"name": "Alice", "password": "hunter2"},
        "rows": [{"token": "abc", "keep": 1}],
        "deep": {"deeper": {"api_key": "abc"}},
    }
    cleaned = redact(data)
    assert cleaned["employee"]["name"] == "Alice"
    assert cleaned["employee"]["password"] == "[REDACTED]"
    assert cleaned["rows"][0] == {"token": "[REDACTED]", "keep": 1}
    assert cleaned["deep"]["deeper"]["api_key"] == "[REDACTED]"


def test_redaction_does_not_mutate_its_input():
    data = {"password": "hunter2", "rows": [{"token": "abc"}]}
    redact(data)
    assert data == {"password": "hunter2", "rows": [{"token": "abc"}]}


# --- changed_fields --------------------------------------------------------


def test_changed_fields_finds_added_removed_and_changed_keys():
    old = {"a": 1, "b": 2, "gone": 9}
    new = {"a": 1, "b": 3, "added": 4}
    assert changed_fields(old, new) == ["added", "b", "gone"]


def test_changed_fields_is_empty_when_nothing_changed():
    assert changed_fields({"a": 1}, {"a": 1}) == []


def test_changed_fields_handles_none():
    assert changed_fields(None, {"a": 1}) == ["a"]
    assert changed_fields({"a": 1}, None) == ["a"]
    assert changed_fields(None, None) == []


# --- limit_size ------------------------------------------------------------


def test_a_small_value_is_returned_unchanged():
    value = {"a": 1}
    assert limit_size(value, max_bytes=1000) == value


def test_a_value_exactly_at_the_limit_is_kept():
    value = {"key": "x" * 20}
    import json

    size = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    assert limit_size(value, max_bytes=size) == value


def test_a_big_value_becomes_a_placeholder():
    value = {"rows": ["x" * 100] * 100}
    result = limit_size(value, max_bytes=200)
    assert result["_truncated"] is True
    assert result["approx_bytes"] > 200


# --- validate_entry --------------------------------------------------------


@pytest.mark.parametrize(
    "entity_type",
    [
        "division", "department", "employee", "employee_approver", "leave_year",
        "leave_type", "leave_assignment", "leave_balance", "weekend_setting",
        "holiday", "leave_request", "report", "email",
    ],
)
def test_known_entity_types_are_accepted(entity_type):
    validate_entry(entity_type, "SUBMIT")


@pytest.mark.parametrize("action", ["SUBMIT", "PASSWORD_RESET", "REPORT_EXPORT", "CREATE"])
def test_good_actions_are_accepted(action):
    validate_entry("employee", action)


def test_an_unknown_entity_type_is_rejected():
    with pytest.raises(AuditValueError):
        validate_entry("widget", "SUBMIT")


@pytest.mark.parametrize("action", ["submit", "SuBMIT", "AB", "A B", "", "1_2_3", "X" * 45])
def test_bad_actions_are_rejected(action):
    with pytest.raises(AuditValueError):
        validate_entry("employee", action)


def test_day_bounds_single_date_and_range():
    from app.routers.admin_audit_log import _day_bounds

    d = datetime.date(2026, 10, 27)
    start, end = _day_bounds(d, d)
    assert start is not None and end is not None
    assert end - start == datetime.timedelta(days=1)

    d2 = datetime.date(2026, 10, 30)
    start_r, end_r = _day_bounds(d, d2)
    assert start_r is not None and end_r is not None
    assert end_r - start_r == datetime.timedelta(days=4)

