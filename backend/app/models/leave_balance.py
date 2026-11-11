from decimal import Decimal

from pydantic import model_validator
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Numeric,
    UniqueConstraint,
    text,
)
from sqlmodel import Field, SQLModel

from app.models.base import BaseModel

_DAYS_COLUMN = dict(nullable=False, server_default=text("0"))


class EmployeeLeaveType(BaseModel, SQLModel, table=True):
    __tablename__ = "employee_leave_type"
    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            "leave_type_id",
            "leave_year_id",
            name="uq_employee_leave_type",
        ),
        CheckConstraint("allocated_days >= 0", name="ck_employee_leave_type_days"),
    )

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    employee_id: int = Field(foreign_key="employee.id", sa_type=BigInteger, nullable=False)
    leave_type_id: int = Field(
        foreign_key="leave_type.id", sa_type=BigInteger, nullable=False
    )
    leave_year_id: int = Field(
        foreign_key="leave_year.id", sa_type=BigInteger, nullable=False
    )
    allocated_days: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(5, 2), **_DAYS_COLUMN),
    )


class LeaveAssignmentTransfer(BaseModel, SQLModel, table=True):
    __tablename__ = "leave_assignment_transfer"
    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            "leave_type_id",
            "leave_year_id",
            name="uq_leave_assignment_transfer",
        ),
        CheckConstraint(
            "transferred_days > 0", name="ck_leave_assignment_transfer_days"
        ),
    )

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    employee_id: int = Field(
        foreign_key="employee.id", sa_type=BigInteger, nullable=False
    )
    leave_type_id: int = Field(
        foreign_key="leave_type.id", sa_type=BigInteger, nullable=False
    )
    leave_year_id: int = Field(
        foreign_key="leave_year.id", sa_type=BigInteger, nullable=False
    )
    transferred_days: Decimal = Field(
        sa_column=Column(Numeric(5, 2), nullable=False)
    )


class LeaveBalance(BaseModel, SQLModel, table=True):
    __tablename__ = "leave_balance"
    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            "leave_type_id",
            "leave_year_id",
            name="uq_leave_balance",
        ),
        CheckConstraint("allocated >= 0", name="ck_leave_balance_allocated"),
        CheckConstraint("carried_forward >= 0", name="ck_leave_balance_carried"),
        CheckConstraint("used >= 0", name="ck_leave_balance_used"),
        CheckConstraint("pending >= 0", name="ck_leave_balance_pending"),
        CheckConstraint(
            "allocated + carried_forward - used - pending >= 0",
            name="ck_leave_balance_available_not_negative",
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
    allocated: Decimal = Field(
        default=Decimal("0"), sa_column=Column(Numeric(5, 2), **_DAYS_COLUMN)
    )
    carried_forward: Decimal = Field(
        default=Decimal("0"), sa_column=Column(Numeric(5, 2), **_DAYS_COLUMN)
    )
    used: Decimal = Field(
        default=Decimal("0"), sa_column=Column(Numeric(5, 2), **_DAYS_COLUMN)
    )
    pending: Decimal = Field(
        default=Decimal("0"), sa_column=Column(Numeric(5, 2), **_DAYS_COLUMN)
    )

    @property
    def available(self) -> Decimal:
        return self.allocated + self.carried_forward - self.used - self.pending


_DAYS_FIELD = dict(ge=0, max_digits=5, decimal_places=2)


class LeaveAssignmentCreate(SQLModel):
    employee_id: int
    leave_type_id: int
    leave_year_id: int | None = None
    allocated_days: Decimal | None = Field(default=None, **_DAYS_FIELD)


class BulkAssignmentRequest(SQLModel):
    leave_type_ids: list[int] = Field(min_length=1)
    division_id: int | None = None
    department_id: int | None = None
    employee_ids: list[int] | None = None
    allocated_days: Decimal | None = Field(default=None, **_DAYS_FIELD)
    leave_year_id: int | None = None

    @model_validator(mode="after")
    def _exactly_one_scope(self) -> "BulkAssignmentRequest":
        scopes = [
            self.division_id is not None,
            self.department_id is not None,
            bool(self.employee_ids),
        ]
        if sum(scopes) != 1:
            raise ValueError(
                "Provide exactly one scope: division_id, department_id or employee_ids."
            )
        return self


class BulkSkip(SQLModel):
    employee_code: str
    leave_type_code: str
    reason: str


class BulkAssignmentResult(SQLModel):
    created: int
    updated: int
    skipped: int
    skipped_details: list[BulkSkip]


class LeaveBalanceRead(SQLModel):
    id: int
    employee_id: int
    employee_name: str
    employee_code: str
    leave_type_id: int
    leave_type_code: str
    leave_type_name: str
    leave_year_id: int
    leave_year_name: str
    allocated: Decimal
    carried_forward: Decimal
    used: Decimal
    pending: Decimal
    available: Decimal
