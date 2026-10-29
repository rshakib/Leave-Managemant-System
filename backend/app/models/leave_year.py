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
    """A leave year, e.g. "2026". Named `leave_year` in the database."""

    __tablename__ = "leave_year"
    __table_args__ = (
        # At most ONE row may have is_active = true (DECISIONS D-52). A partial
        # unique index only indexes the rows where is_active is true, so having
        # two active years violates uniqueness while any number of inactive
        # years are fine.
        Index(
            "uq_leave_year_single_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        CheckConstraint("end_date >= start_date", name="ck_leave_year_date_order"),
        # Closing (Phase 15) records who closed it. Parentheses matter: without
        # them PostgreSQL parses the comparison chain differently.
        CheckConstraint(
            "(closed_at IS NULL) = (closed_by_id IS NULL)",
            name="ck_leave_year_closed_together",
        ),
        # A year cannot claim to be closed without a closing timestamp.
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


# --- Pydantic-only models (never a database table) -------------------------
# `is_active` and `is_closed` are deliberately absent from Create/Update:
# activation happens through POST /leave-years/{id}/activate and closing is a
# Phase 15 action (DECISIONS D-52, D-53).


class LeaveYearCreate(SQLModel):
    name: str = Field(min_length=1, max_length=20)
    start_date: date
    end_date: date


class LeaveYearUpdate(SQLModel):
    # extra="forbid" turns a stray "is_active"/"is_closed" into a clear 422
    # instead of silently ignoring it.
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
    # Filled in by the router (the model has no relationship for this).
    closed_by_name: str | None = None
