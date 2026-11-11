from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlmodel import Field, SQLModel

from app.models.base import BaseModel


class CurtailmentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class LeaveCurtailment(BaseModel, SQLModel, table=True):
    __tablename__ = "leave_curtailment"
    __table_args__ = (
        CheckConstraint("curtailed_end_date <= original_end_date", name="ck_curtailment_dates"),
        CheckConstraint("days_to_refund > 0", name="ck_curtailment_refund_positive"),
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED')",
            name="ck_curtailment_status",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True, sa_type=BigInteger)
    leave_request_id: int = Field(
        foreign_key="leave_request.id", sa_type=BigInteger, nullable=False
    )
    employee_id: int = Field(
        foreign_key="employee.id", sa_type=BigInteger, nullable=False
    )
    original_end_date: date = Field(nullable=False)
    curtailed_end_date: date = Field(nullable=False)
    curtailed_day_type: Optional[str] = Field(
        default=None, sa_column=Column(String(20), nullable=True)
    )
    original_days: Decimal = Field(
        sa_column=Column(Numeric(5, 2), nullable=False)
    )
    new_days: Decimal = Field(
        sa_column=Column(Numeric(5, 2), nullable=False)
    )
    days_to_refund: Decimal = Field(
        sa_column=Column(Numeric(5, 2), nullable=False)
    )
    reason: str = Field(sa_column=Column(Text, nullable=False))
    status: CurtailmentStatus = Field(
        sa_column=Column(String(20), nullable=False, server_default=text("'PENDING'"))
    )
    submitted_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        )
    )
    decided_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    decided_by_id: Optional[int] = Field(
        default=None, foreign_key="employee.id", sa_type=BigInteger, nullable=True
    )
    decision_note: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )


class CurtailmentCreate(SQLModel):
    curtailed_end_date: date
    curtailed_day_type: Optional[str] = "FULL_DAY"
    reason: str


class CurtailmentPreview(SQLModel):
    leave_request_id: int
    original_end_date: date
    curtailed_end_date: date
    curtailed_day_type: Optional[str] = "FULL_DAY"
    original_days: Decimal
    new_days: Decimal
    days_to_refund: Decimal
    can_curtail: bool
    reason_required: bool = True
    error: Optional[str] = None


class CurtailmentDecision(SQLModel):
    note: Optional[str] = None


class CurtailmentRead(SQLModel):
    id: int
    leave_request_id: int
    employee_id: int
    employee_code: Optional[str] = None
    employee_name: Optional[str] = None
    leave_type_name: Optional[str] = None
    original_start_date: Optional[date] = None
    original_end_date: date
    curtailed_end_date: date
    curtailed_day_type: Optional[str] = None
    original_days: Decimal
    new_days: Decimal
    days_to_refund: Decimal
    reason: str
    status: CurtailmentStatus
    submitted_at: datetime
    decided_at: Optional[datetime] = None
    decided_by_id: Optional[int] = None
    decided_by_name: Optional[str] = None
    decision_note: Optional[str] = None

