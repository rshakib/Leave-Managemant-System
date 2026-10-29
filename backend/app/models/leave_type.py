from decimal import Decimal
from enum import Enum

from pydantic import field_validator
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Numeric,
    String,
    text,
)
from sqlmodel import Field, SQLModel

from app.models.base import BaseModel


class AccrualMode(str, Enum):
    """How a leave type is credited. Only FIXED is implemented in v1 (D-03)."""

    FIXED = "fixed"
    MONTHLY = "monthly"


def _normalise_code(value: str) -> str:
    """Leave-type codes are stored uppercase and trimmed (DECISIONS D-58)."""
    return value.strip().upper()


class LeaveType(BaseModel, SQLModel, table=True):
    """A kind of leave (Annual, Sick, ...). Named `leave_type` in the database."""

    __tablename__ = "leave_type"
    __table_args__ = (
        CheckConstraint("default_quota >= 0", name="ck_leave_type_default_quota"),
        CheckConstraint(
            "max_carry_forward_days >= 0", name="ck_leave_type_max_carry_forward"
        ),
        CheckConstraint(
            "accrual_mode IN ('fixed', 'monthly')", name="ck_leave_type_accrual_mode"
        ),
        CheckConstraint(
            "require_attachment_after_days IS NULL OR require_attachment_after_days > 0",
            name="ck_leave_type_attachment_days",
        ),
    )

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    code: str = Field(unique=True, nullable=False, max_length=20)
    name: str = Field(unique=True, nullable=False, max_length=100)
    default_quota: Decimal = Field(sa_type=Numeric(5, 2), nullable=False)
    # Stored as VARCHAR + CHECK rather than a native PostgreSQL ENUM (D-42).
    accrual_mode: AccrualMode = Field(
        sa_column=Column(String(20), nullable=False, server_default=text("'fixed'")),
    )
    allow_half_day: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
    )
    require_attachment_after_days: int | None = Field(default=None, nullable=True)
    carry_forward_allowed: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    max_carry_forward_days: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(5, 2), nullable=False, server_default=text("0")),
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
    )


# --- Pydantic-only models (never a database table) -------------------------

_QUOTA_FIELD = dict(ge=0, max_digits=5, decimal_places=2)


class LeaveTypeCreate(SQLModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=100)
    default_quota: Decimal = Field(**_QUOTA_FIELD)
    accrual_mode: AccrualMode = AccrualMode.FIXED
    allow_half_day: bool = True
    require_attachment_after_days: int | None = Field(default=None, gt=0)
    carry_forward_allowed: bool = False
    max_carry_forward_days: Decimal = Field(default=Decimal("0"), **_QUOTA_FIELD)
    is_active: bool = True

    @field_validator("code", mode="after")
    @classmethod
    def _upper_code(cls, value: str) -> str:
        return _normalise_code(value)


class LeaveTypeUpdate(SQLModel):
    code: str | None = Field(default=None, min_length=1, max_length=20)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    default_quota: Decimal | None = Field(default=None, **_QUOTA_FIELD)
    accrual_mode: AccrualMode | None = None
    allow_half_day: bool | None = None
    require_attachment_after_days: int | None = Field(default=None, gt=0)
    carry_forward_allowed: bool | None = None
    max_carry_forward_days: Decimal | None = Field(default=None, **_QUOTA_FIELD)
    is_active: bool | None = None

    @field_validator("code", mode="after")
    @classmethod
    def _upper_code(cls, value: str | None) -> str | None:
        return None if value is None else _normalise_code(value)


class LeaveTypeRead(SQLModel):
    id: int
    code: str
    name: str
    default_quota: Decimal
    accrual_mode: AccrualMode
    allow_half_day: bool
    require_attachment_after_days: int | None
    carry_forward_allowed: bool
    max_carry_forward_days: Decimal
    is_active: bool
