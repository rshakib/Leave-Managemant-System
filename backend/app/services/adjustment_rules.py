"""Pure rules for a manual leave-balance adjustment (NFR-1).

An adjustment is a small, deliberate correction ("+5 days, because…") that an
administrator makes by hand. Only three of the four stored numbers can be
adjusted:

* ALLOCATED        — the entitlement for the year
* CARRIED_FORWARD  — days brought in from the previous year
* USED             — days already taken

PENDING is deliberately NOT adjustable: it belongs to the requests that are
waiting for approval, so the only honest way to change it is to approve, reject
or cancel a request. See DECISIONS D-155.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

ADJUSTABLE_FIELDS = ("ALLOCATED", "CARRIED_FORWARD", "USED")

HUNDREDTH = Decimal("0.01")
MAX_ABS_DELTA = Decimal("365")
MIN_REASON_LENGTH = 5
MAX_REASON_LENGTH = 500


class AdjustmentError(ValueError):
    """A refused adjustment, with the HTTP status the API should answer with."""

    def __init__(self, code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass(frozen=True)
class AdjustmentResult:
    field: str
    allocated: Decimal
    carried_forward: Decimal
    used: Decimal
    pending: Decimal
    value_before: Decimal
    value_after: Decimal
    available_before: Decimal
    available_after: Decimal


def _money(value) -> Decimal:
    return Decimal(str(value))


def available_of(allocated, carried_forward, used, pending) -> Decimal:
    """allocated + carried_forward - used - pending (the computed balance)."""
    return (
        _money(allocated)
        + _money(carried_forward)
        - _money(used)
        - _money(pending)
    )


def normalise_field(field) -> str:
    name = (field or "").strip().upper() if isinstance(field, str) else ""
    if name not in ADJUSTABLE_FIELDS:
        raise AdjustmentError(
            "field_not_allowed",
            f"'{field}' cannot be adjusted by hand. Only ALLOCATED, "
            "CARRIED_FORWARD and USED can — PENDING belongs to the requests "
            "waiting for approval.",
            422,
        )
    return name


def _delta(value) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise AdjustmentError("delta_invalid", "delta must be a number.", 422) from None
    if not number.is_finite():
        raise AdjustmentError("delta_invalid", "delta must be a finite number.", 422)
    if number == 0:
        raise AdjustmentError("delta_zero", "delta must not be zero.", 400)
    try:
        rounded = number.quantize(HUNDREDTH)
    except InvalidOperation:
        raise AdjustmentError("delta_invalid", "delta is out of range.", 400) from None
    if number != rounded:
        raise AdjustmentError(
            "delta_precision", "delta must have at most 2 decimal places.", 400
        )
    if abs(number) > MAX_ABS_DELTA:
        raise AdjustmentError(
            "delta_too_large",
            f"|delta| must be at most {MAX_ABS_DELTA} days.",
            400,
        )
    return number


def apply_adjustment(balance, field, delta) -> AdjustmentResult:
    """Apply `delta` to one field of `balance` (a row with the four numbers)."""
    name = normalise_field(field)
    change = _delta(delta)

    values = {
        column: _money(getattr(balance, column.lower()))
        for column in ADJUSTABLE_FIELDS
    }
    pending = _money(getattr(balance, "pending"))

    before = values[name]
    available_before = available_of(
        values["ALLOCATED"], values["CARRIED_FORWARD"], values["USED"], pending
    )

    after = before + change
    if after < 0:
        raise AdjustmentError(
            "field_negative",
            f"{name} would become {after}, which is not allowed (it is {before} now).",
            409,
        )

    values[name] = after
    available_after = available_of(
        values["ALLOCATED"], values["CARRIED_FORWARD"], values["USED"], pending
    )
    if available_after < 0:
        raise AdjustmentError(
            "available_negative",
            f"The available balance would become {available_after} "
            f"(it is {available_before} now): a balance may never go negative.",
            409,
        )

    return AdjustmentResult(
        field=name,
        allocated=values["ALLOCATED"],
        carried_forward=values["CARRIED_FORWARD"],
        used=values["USED"],
        pending=pending,
        value_before=before,
        value_after=after,
        available_before=available_before,
        available_after=available_after,
    )


def validate_reason(text) -> str:
    """Trim, then enforce 5..500 characters and no control characters."""
    cleaned = (text or "").strip() if isinstance(text, str) else ""
    if len(cleaned) < MIN_REASON_LENGTH:
        raise AdjustmentError(
            "reason_too_short",
            f"The reason must be at least {MIN_REASON_LENGTH} characters.",
            422,
        )
    if len(cleaned) > MAX_REASON_LENGTH:
        raise AdjustmentError(
            "reason_too_long",
            f"The reason must be at most {MAX_REASON_LENGTH} characters.",
            422,
        )
    for character in cleaned:
        if character == "\n":
            continue
        if ord(character) < 32 or ord(character) == 127:
            raise AdjustmentError(
                "reason_control_characters",
                "The reason must not contain control characters.",
                422,
            )
    return cleaned


def expected_used(approved_days_sum, used_adjustments_sum) -> Decimal:
    """used should equal approved request days PLUS 'used' adjustments."""
    return _money(approved_days_sum) + _money(used_adjustments_sum)


def expected_carried_forward(carry_log_sum, carried_adjustments_sum) -> Decimal:
    """carried_forward should equal the carry log PLUS carried adjustments."""
    return _money(carry_log_sum) + _money(carried_adjustments_sum)
