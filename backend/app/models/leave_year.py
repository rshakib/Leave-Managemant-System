from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    text,
)
from sqlmodel import Field, SQLModel

from app.models.base import BaseModel


class LeaveYear(BaseModel, SQLModel, table=True):
    __tablename__ = "leave_year"
    __table_args__ = (
        Index(
            "uq_leave_year_single_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        CheckConstraint("end_date >= start_date", name="ck_leave_year_date_order"),
        CheckConstraint(
            "(closed_at IS NULL) = (closed_by_id IS NULL)",
            name="ck_leave_year_closed_together",
        ),
        CheckConstraint(
            "NOT is_closed OR closed_at IS NOT NULL",
            name="ck_leave_year_closed_has_date",
        ),
    )

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    name: str = Field(unique=True, nullable=False, max_length=20)
    start_date: date = Field(nullable=False)
    end_date: date = Field(nullable=False)
    is_active: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    is_closed: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    closed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    closed_by_id: int | None = Field(
        default=None, foreign_key="employee.id", sa_type=BigInteger, nullable=True
    )


class LeaveYearCreate(SQLModel):
    name: str = Field(min_length=1, max_length=20)
    start_date: date
    end_date: date


class LeaveYearUpdate(SQLModel):
    model_config = {"extra": "forbid"}

    name: str | None = Field(default=None, min_length=1, max_length=20)
    start_date: date | None = None
    end_date: date | None = None


class LeaveYearRead(SQLModel):
    id: int
    name: str
    start_date: date
    end_date: date
    is_active: bool
    is_closed: bool
    closed_at: datetime | None = None
    closed_by_id: int | None = None
    closed_by_name: str | None = None
