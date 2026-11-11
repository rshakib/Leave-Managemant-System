import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlmodel import Field, SQLModel


class AdjustmentField(str, Enum):
    ALLOCATED = "ALLOCATED"
    CARRIED_FORWARD = "CARRIED_FORWARD"
    USED = "USED"


class LeaveBalanceAdjustment(SQLModel, table=True):
    __tablename__ = "leave_balance_adjustment"
    __table_args__ = (
        CheckConstraint(
            "field IN ('ALLOCATED', 'CARRIED_FORWARD', 'USED')",
            name="ck_adjustment_field",
        ),
        CheckConstraint("delta <> 0", name="ck_adjustment_delta_nonzero"),
        CheckConstraint("value_after >= 0", name="ck_adjustment_after_non_negative"),
        CheckConstraint(
            "value_after - value_before = delta", name="ck_adjustment_chain"
        ),
        CheckConstraint(
            "length(reason) >= 5 AND length(reason) <= 500",
            name="ck_adjustment_reason_length",
        ),
        Index("ix_adjustment_balance", "balance_id", text("created_at DESC")),
        Index("ix_adjustment_employee", "employee_id", text("created_at DESC")),
    )

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    balance_id: int = Field(
        foreign_key="leave_balance.id", sa_type=BigInteger, nullable=False
    )
    employee_id: int = Field(
        foreign_key="employee.id", sa_type=BigInteger, nullable=False
    )
    leave_type_id: int = Field(
        foreign_key="leave_type.id", sa_type=BigInteger, nullable=False
    )
    leave_year_id: int = Field(
        foreign_key="leave_year.id", sa_type=BigInteger, nullable=False
    )
    field: str = Field(sa_column=Column(String(20), nullable=False))
    delta: Decimal = Field(sa_column=Column(Numeric(5, 2), nullable=False))
    value_before: Decimal = Field(sa_column=Column(Numeric(5, 2), nullable=False))
    value_after: Decimal = Field(sa_column=Column(Numeric(5, 2), nullable=False))
    reason: str = Field(sa_column=Column(Text, nullable=False))
    year_was_closed: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    created_by: int = Field(
        foreign_key="employee.id", sa_type=BigInteger, nullable=False
    )
    created_at: datetime.datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        )
    )


class AdjustmentCreate(SQLModel):
    field: str
    delta: Decimal
    reason: str


class AdjustmentRead(SQLModel):
    id: int
    created_at: datetime.datetime
    balance_id: int
    employee_id: int
    employee_code: str
    employee_name: str
    leave_type_id: int
    leave_type_code: str
    leave_type_name: str
    leave_year_id: int
    leave_year_name: str
    field: str
    delta: Decimal
    value_before: Decimal
    value_after: Decimal
    reason: str
    year_was_closed: bool
    created_by: int
    actor_name: str | None = None


class AdjustmentPage(SQLModel):
    rows: list[AdjustmentRead]
    total: int
    limit: int
    offset: int
