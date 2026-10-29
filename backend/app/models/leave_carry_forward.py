import datetime
from decimal import Decimal

from sqlmodel import Field, SQLModel
from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Numeric, UniqueConstraint, text

from app.models.base import BaseModel

_DAYS = dict(nullable=False, server_default=text("0"))


class LeaveCarryForward(BaseModel, SQLModel, table=True):
    """The year-end rollover log (FR-LT-4, DECISIONS D-22/D-25).

    One row per (employee, leave type, from-year) that actually carried days
    forward. A leave type that does not allow carry-forward writes NO row.
    """

    __tablename__ = "leave_carry_forward"
    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            "leave_type_id",
            "from_leave_year_id",
            name="uq_leave_carry_forward",
        ),
        CheckConstraint("carried_days >= 0", name="ck_leave_carry_forward_carried"),
        CheckConstraint("forfeited_days >= 0", name="ck_leave_carry_forward_forfeited"),
        # The two halves must add up to exactly what was left at closing.
        CheckConstraint(
            "remaining_at_close = carried_days + forfeited_days",
            name="ck_leave_carry_forward_split",
        ),
        CheckConstraint(
            "from_leave_year_id <> to_leave_year_id",
            name="ck_leave_carry_forward_different_years",
        ),
    )

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    employee_id: int = Field(foreign_key="employee.id", sa_type=BigInteger, nullable=False)
    leave_type_id: int = Field(
        foreign_key="leave_type.id", sa_type=BigInteger, nullable=False
    )
    from_leave_year_id: int = Field(
        foreign_key="leave_year.id", sa_type=BigInteger, nullable=False
    )
    to_leave_year_id: int = Field(
        foreign_key="leave_year.id", sa_type=BigInteger, nullable=False
    )
    remaining_at_close: Decimal = Field(sa_column=Column(Numeric(5, 2), **_DAYS))
    carried_days: Decimal = Field(sa_column=Column(Numeric(5, 2), **_DAYS))
    forfeited_days: Decimal = Field(sa_column=Column(Numeric(5, 2), **_DAYS))
    processed_at: datetime.datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    processed_by: int | None = Field(
        default=None, foreign_key="employee.id", sa_type=BigInteger, nullable=True
    )


# --- Pydantic-only models --------------------------------------------------


class CarryForwardRead(SQLModel):
    id: int
    employee_id: int
    employee_code: str
    employee_name: str
    leave_type_id: int
    leave_type_code: str
    leave_type_name: str
    from_leave_year_id: int
    from_leave_year_name: str
    to_leave_year_id: int
    to_leave_year_name: str
    remaining_at_close: Decimal
    carried_days: Decimal
    forfeited_days: Decimal
    processed_at: datetime.datetime
    processed_by_name: str | None = None


class ClosingPreviewRow(SQLModel):
    employee_id: int
    employee_code: str
    employee_name: str
    leave_type_id: int
    leave_type_code: str
    leave_type_name: str
    remaining: Decimal
    carried: Decimal
    forfeited: Decimal
    has_next_year_assignment: bool


class ClosingTypeTotal(SQLModel):
    leave_type_id: int
    leave_type_code: str
    leave_type_name: str
    employees: int
    remaining: Decimal
    carried: Decimal
    forfeited: Decimal


class ClosingPreview(SQLModel):
    leave_year_id: int
    leave_year_name: str
    next_leave_year_id: int | None = None
    next_leave_year_name: str | None = None
    can_close: bool
    blockers: list[dict]
    warnings: list[str]
    totals_by_type: list[ClosingTypeTotal]
    rows: list[ClosingPreviewRow]
    row_offset: int = 0
    row_limit: int = 200
    total_rows: int
    fingerprint: dict


class ClosingRequest(SQLModel):
    confirm_name: str
    expected_fingerprint: dict


class ClosingResult(SQLModel):
    leave_year_id: int
    leave_year_name: str
    next_leave_year_id: int
    next_leave_year_name: str
    rows_carried: int
    rows_forfeited_only: int
    total_carried: Decimal
    total_forfeited: Decimal
    skipped_inactive: int
    balances_created: int
    balances_updated: int
    active_year_id: int | None = None
    active_year_name: str | None = None
    fingerprint: dict


class CarryForwardPage(SQLModel):
    rows: list[CarryForwardRead]
    total: int
    limit: int
    offset: int
