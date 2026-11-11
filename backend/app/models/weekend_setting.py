from pydantic import field_validator
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Index,
    Integer,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, SQLModel

from app.models.base import BaseModel


class WeekendSetting(BaseModel, SQLModel, table=True):
    __tablename__ = "weekend_setting"
    __table_args__ = (
        CheckConstraint(
            "cardinality(days_of_week) >= 1", name="ck_weekend_setting_not_empty"
        ),
        CheckConstraint(
            "days_of_week <@ ARRAY[0, 1, 2, 3, 4, 5, 6]",
            name="ck_weekend_setting_range",
        ),
        Index(
            "uq_weekend_setting_employee",
            "employee_id",
            unique=True,
            postgresql_where=text("employee_id IS NOT NULL"),
        ),
        Index(
            "uq_weekend_setting_single_global",
            text("(employee_id IS NULL)"),
            unique=True,
            postgresql_where=text("employee_id IS NULL"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    employee_id: int | None = Field(
        default=None, foreign_key="employee.id", sa_type=BigInteger, nullable=True
    )
    days_of_week: list[int] = Field(sa_column=Column(ARRAY(Integer), nullable=False))


def _clean_days(values: list[int]) -> list[int]:
    cleaned = sorted({int(value) for value in values})
    if not cleaned:
        raise ValueError("Pick at least one weekend day.")
    if any(value < 0 or value > 6 for value in cleaned):
        raise ValueError("Weekend days must be 0..6 (Sunday=0 ... Saturday=6).")
    return cleaned


class WeekendSettingWrite(SQLModel):
    days_of_week: list[int] = Field(min_length=1)

    @field_validator("days_of_week", mode="after")
    @classmethod
    def _normalise(cls, value: list[int]) -> list[int]:
        return _clean_days(value)


class WeekendSettingRead(SQLModel):
    id: int
    employee_id: int | None = None
    employee_name: str | None = None
    employee_code: str | None = None
    days_of_week: list[int]
