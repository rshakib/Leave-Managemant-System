import datetime
from enum import Enum

from pydantic import model_validator
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    Index,
    String,
    text,
)
from sqlmodel import Field, SQLModel

from app.models.base import BaseModel


class HolidayType(str, Enum):
    """Whether a holiday is subtracted from leave (see DECISIONS D-71)."""

    PUBLIC = "PUBLIC"
    COMPANY = "COMPANY"
    OPTIONAL = "OPTIONAL"


class Holiday(BaseModel, SQLModel, table=True):
    """A holiday, one row per date (DECISIONS D-07).

    Scope: `division_id`/`department_id` NULL means "applies to everyone";
    a department also stores its division.

    Duplicate trap: `UNIQUE(date, division_id, department_id)` would NOT stop
    duplicates when the scope columns are NULL (two NULLs are never equal), so
    the index below compares `COALESCE(division_id, 0)` and
    `COALESCE(department_id, 0)` instead — an "expression index". `0` is safe
    as a stand-in for NULL because real ids start at 1.

    Note: the `date` column is annotated as `datetime.date` (not bare `date`)
    because a field may not share its name with its own type annotation.
    """

    __tablename__ = "holiday"
    __table_args__ = (
        CheckConstraint(
            "type IN ('PUBLIC', 'COMPANY', 'OPTIONAL')", name="ck_holiday_type"
        ),
        Index(
            "uq_holiday_date_scope",
            text("date"),
            text("COALESCE(division_id, 0)"),
            text("COALESCE(department_id, 0)"),
            unique=True,
        ),
    )

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    leave_year_id: int = Field(
        foreign_key="leave_year.id", sa_type=BigInteger, nullable=False
    )
    date: datetime.date = Field(sa_column=Column(Date, nullable=False))
    title: str = Field(nullable=False, max_length=150)
    type: HolidayType = Field(sa_column=Column(String(20), nullable=False))
    division_id: int | None = Field(
        default=None, foreign_key="division.id", sa_type=BigInteger, nullable=True
    )
    department_id: int | None = Field(
        default=None, foreign_key="department.id", sa_type=BigInteger, nullable=True
    )


# --- Pydantic-only models (never a database table) -------------------------


class HolidayCreate(SQLModel):
    leave_year_id: int
    # Either a single `date`, or `date_from` + `date_to` (the API expands a
    # range into one row per date).
    date: datetime.date | None = None
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    title: str = Field(min_length=1, max_length=150)
    type: HolidayType = HolidayType.PUBLIC
    division_id: int | None = None
    department_id: int | None = None

    @model_validator(mode="after")
    def _exactly_one_shape(self) -> "HolidayCreate":
        has_single = self.date is not None
        has_range = self.date_from is not None and self.date_to is not None
        if has_single == has_range:
            raise ValueError(
                "Provide either 'date', or both 'date_from' and 'date_to'."
            )
        if has_range and self.date_to < self.date_from:
            raise ValueError("date_to must not be before date_from.")
        return self

    @property
    def dates(self) -> list[datetime.date]:
        if self.date is not None:
            return [self.date]
        span = (self.date_to - self.date_from).days
        return [
            self.date_from + datetime.timedelta(days=offset)
            for offset in range(span + 1)
        ]


class HolidayUpdate(SQLModel):
    date: datetime.date | None = None
    title: str | None = Field(default=None, min_length=1, max_length=150)
    type: HolidayType | None = None
    division_id: int | None = None
    department_id: int | None = None


class HolidayRead(SQLModel):
    id: int
    leave_year_id: int
    date: datetime.date
    title: str
    type: HolidayType
    division_id: int | None = None
    department_id: int | None = None


class HolidayImportResult(SQLModel):
    created: int
