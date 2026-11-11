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
    PUBLIC = "PUBLIC"
    COMPANY = "COMPANY"
    OPTIONAL = "OPTIONAL"


class Holiday(BaseModel, SQLModel, table=True):
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


class HolidayCreate(SQLModel):
    leave_year_id: int
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
