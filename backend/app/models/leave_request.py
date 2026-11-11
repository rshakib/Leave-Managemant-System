import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlmodel import Field, SQLModel

from app.models.base import BaseModel
from app.models.calendar import PreviewDay
from app.models.leave_curtailment import CurtailmentRead
from app.services.day_calc import DayType


class RequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"


class LeaveRequest(BaseModel, SQLModel, table=True):
    __tablename__ = "leave_request"
    __table_args__ = (
        CheckConstraint("start_date <= end_date", name="ck_leave_request_dates"),
        CheckConstraint("chargeable_days > 0", name="ck_leave_request_days"),
        CheckConstraint(
            "day_type IN ('FULL_DAY', 'FIRST_HALF', 'SECOND_HALF')",
            name="ck_leave_request_day_type",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED')",
            name="ck_leave_request_status",
        ),
        CheckConstraint(
            "day_type = 'FULL_DAY' OR start_date = end_date",
            name="ck_leave_request_half_day_single",
        ),
        Index("ix_leave_request_employee_status", "employee_id", "status"),
        Index(
            "ix_leave_request_employee_dates",
            "employee_id",
            "start_date",
            "end_date",
        ),
        CheckConstraint(
            "(cancelled_at IS NULL AND cancelled_by_id IS NULL) OR "
            "(cancelled_at IS NOT NULL AND cancelled_by_id IS NOT NULL)",
            name="ck_leave_request_cancelled_pair",
        ),
    )

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    employee_id: int = Field(foreign_key="employee.id", sa_type=BigInteger, nullable=False)
    leave_type_id: int = Field(
        foreign_key="leave_type.id", sa_type=BigInteger, nullable=False
    )
    leave_year_id: int = Field(
        foreign_key="leave_year.id", sa_type=BigInteger, nullable=False
    )
    start_date: datetime.date = Field(nullable=False)
    end_date: datetime.date = Field(nullable=False)
    day_type: DayType = Field(
        sa_column=Column(String(20), nullable=False, server_default=text("'FULL_DAY'"))
    )
    chargeable_days: Decimal = Field(
        sa_column=Column(Numeric(5, 2), nullable=False)
    )
    reason: str = Field(sa_column=Column(Text, nullable=False))
    attachment_url: str | None = Field(default=None, max_length=255)
    status: RequestStatus = Field(
        sa_column=Column(String(20), nullable=False, server_default=text("'PENDING'"))
    )
    submitted_at: datetime.datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        )
    )
    final_decided_at: datetime.datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    cancelled_at: datetime.datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    cancelled_by_id: int | None = Field(
        default=None, foreign_key="employee.id", sa_type=BigInteger, nullable=True
    )
    cancel_reason: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )


class LeaveRequestAllocation(BaseModel, SQLModel, table=True):
    __tablename__ = "leave_request_allocation"
    __table_args__ = (
        UniqueConstraint(
            "leave_request_id", "leave_year_id", name="uq_leave_request_allocation"
        ),
        CheckConstraint("days > 0", name="ck_leave_request_allocation_days"),
    )

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    leave_request_id: int = Field(
        foreign_key="leave_request.id", sa_type=BigInteger, nullable=False
    )
    leave_year_id: int = Field(
        foreign_key="leave_year.id", sa_type=BigInteger, nullable=False
    )
    days: Decimal = Field(sa_column=Column(Numeric(5, 2), nullable=False))


class LeaveRequestApproval(BaseModel, SQLModel, table=True):
    __tablename__ = "leave_request_approval"
    __table_args__ = (
        UniqueConstraint(
            "leave_request_id", "approver_id", name="uq_leave_request_approval"
        ),
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED', 'SKIPPED')",
            name="ck_leave_request_approval_status",
        ),
        Index(
            "ix_leave_request_approval_approver_status", "approver_id", "status"
        ),
    )

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    leave_request_id: int = Field(
        foreign_key="leave_request.id", sa_type=BigInteger, nullable=False
    )
    approver_id: int = Field(
        foreign_key="employee.id", sa_type=BigInteger, nullable=False
    )
    status: ApprovalStatus = Field(
        sa_column=Column(String(20), nullable=False, server_default=text("'PENDING'"))
    )
    comment: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    acted_at: datetime.datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class AllocationRead(SQLModel):
    leave_year_id: int
    leave_year_name: str
    days: Decimal


class ApprovalRead(SQLModel):
    approver_id: int
    approver_code: str
    approver_name: str
    status: ApprovalStatus
    comment: str | None = None
    acted_at: datetime.datetime | None = None


class LeaveRequestSummary(SQLModel):
    id: int
    leave_type_id: int
    leave_type_code: str
    leave_type_name: str
    leave_year_id: int
    start_date: datetime.date
    end_date: datetime.date
    day_type: DayType
    chargeable_days: Decimal
    status: RequestStatus
    submitted_at: datetime.datetime
    has_attachment: bool


class LeaveRequestDetail(LeaveRequestSummary):
    employee_id: int
    employee_code: str
    employee_name: str
    reason: str
    final_decided_at: datetime.datetime | None = None
    my_pending_approval: bool = False
    can_cancel: bool = False
    cancelled_at: datetime.datetime | None = None
    cancelled_by_id: int | None = None
    cancelled_by_name: str | None = None
    cancel_reason: str | None = None
    allocations: list[AllocationRead] = Field(default_factory=list)
    approvals: list[ApprovalRead] = Field(default_factory=list)
    touches_closed_year: bool = False
    closed_year_names: list[str] = Field(default_factory=list)
    can_curtail: bool = False
    curtailments: list[CurtailmentRead] = Field(default_factory=list)


class CheckProblem(SQLModel):
    code: str
    message: str
    status: int


class YearSplitRead(SQLModel):
    leave_year_id: int
    leave_year_name: str
    days: Decimal


class YearBalanceRead(SQLModel):
    leave_year_id: int
    leave_year_name: str
    available_before: Decimal
    days: Decimal
    available_after: Decimal


class LeaveRequestCheck(SQLModel):
    employee_id: int
    leave_type_id: int
    start_date: datetime.date
    end_date: datetime.date
    day_type: DayType
    chargeable_days: Decimal
    weekend_days: list[int] = Field(default_factory=list)
    days: list[PreviewDay] = Field(default_factory=list)
    per_year: list[YearSplitRead] = Field(default_factory=list)
    balances: list[YearBalanceRead] = Field(default_factory=list)
    problems: list[CheckProblem] = Field(default_factory=list)
    can_submit: bool = False


class InboxItem(SQLModel):
    approval_id: int
    approval_status: ApprovalStatus
    request_id: int
    employee_id: int
    employee_code: str
    employee_name: str
    leave_type_code: str
    leave_type_name: str
    start_date: datetime.date
    end_date: datetime.date
    day_type: DayType
    chargeable_days: Decimal
    reason_preview: str
    submitted_at: datetime.datetime
    approved_count: int
    total_approvers: int
    summary: str


class InboxCount(SQLModel):
    pending: int
    early_returns: int = 0
    total: int = 0


class DecisionResult(SQLModel):
    request_id: int
    status: RequestStatus


class AdminRequestRow(LeaveRequestSummary):
    employee_id: int
    employee_code: str
    employee_name: str


class CancelIn(SQLModel):
    comment: str | None = Field(default=None, max_length=1000)
