from collections.abc import Iterable
from datetime import date
from enum import Enum

from pydantic import EmailStr, field_validator
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    PrimaryKeyConstraint,
    String,
    text,
)
from sqlmodel import Field, SQLModel

from app.core.security import MIN_PASSWORD_LENGTH
from app.models.base import BaseModel


class Role(str, Enum):
    ADMIN = "ADMIN"
    EMPLOYEE = "EMPLOYEE"
    APPROVER = "APPROVER"


class Employee(BaseModel, SQLModel, table=True):
    __tablename__ = "employee"

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    employee_code: str = Field(unique=True, nullable=False, max_length=50)
    full_name: str = Field(nullable=False, max_length=150)
    email: str = Field(unique=True, nullable=False, max_length=255)
    password_hash: str = Field(nullable=False, max_length=255, repr=False)
    phone: str | None = Field(default=None, max_length=30)
    designation: str | None = Field(default=None, max_length=100)
    division_id: int = Field(foreign_key="division.id", sa_type=BigInteger, nullable=False)
    department_id: int = Field(foreign_key="department.id", sa_type=BigInteger, nullable=False)
    supervisor_id: int | None = Field(
        default=None, foreign_key="employee.id", sa_type=BigInteger, nullable=True
    )
    joining_date: date = Field(nullable=False)
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
    )
    must_change_password: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )


class EmployeeRole(SQLModel, table=True):
    __tablename__ = "employee_role"
    __table_args__ = (
        PrimaryKeyConstraint("employee_id", "role", name="pk_employee_role"),
        CheckConstraint(
            "role IN ('ADMIN', 'EMPLOYEE', 'APPROVER')", name="ck_employee_role_role"
        ),
    )

    employee_id: int = Field(foreign_key="employee.id", sa_type=BigInteger, nullable=False)
    role: Role = Field(sa_column=Column(String(20), nullable=False))


def _lowercase_email(value: str) -> str:
    return value.lower()


class EmployeeBase(SQLModel):
    full_name: str = Field(min_length=1, max_length=150)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=30)
    designation: str | None = Field(default=None, max_length=100)
    division_id: int
    department_id: int
    supervisor_id: int | None = None
    joining_date: date
    is_active: bool = True

    @field_validator("email", mode="after")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        return _lowercase_email(value)


class EmployeeCreate(EmployeeBase):
    employee_code: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)
    roles: list[Role] = Field(default_factory=lambda: [Role.EMPLOYEE])
    must_change_password: bool = True


class EmployeeUpdate(SQLModel):
    employee_code: str | None = Field(default=None, min_length=1, max_length=50)
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    email: EmailStr | None = None
    password: str | None = Field(
        default=None, min_length=MIN_PASSWORD_LENGTH, max_length=128
    )
    phone: str | None = Field(default=None, max_length=30)
    designation: str | None = Field(default=None, max_length=100)
    division_id: int | None = None
    department_id: int | None = None
    supervisor_id: int | None = None
    joining_date: date | None = None
    is_active: bool | None = None
    roles: list[Role] | None = Field(default=None)
    must_change_password: bool | None = None

    @field_validator("email", mode="after")
    @classmethod
    def _normalise_email(cls, value: str | None) -> str | None:
        return None if value is None else _lowercase_email(value)


class EmployeeRead(EmployeeBase):
    email: str
    id: int
    employee_code: str
    roles: list[Role] = Field(default_factory=list)
    must_change_password: bool = False
    is_supervisor: bool = False


_ROLE_ORDER = {Role.ADMIN: 0, Role.EMPLOYEE: 1, Role.APPROVER: 2}


def unique_roles(values: Iterable[Role | str]) -> list[Role]:
    seen: list[Role] = []
    for value in values:
        role = Role(value)
        if role not in seen:
            seen.append(role)
    return sorted(seen, key=lambda role: _ROLE_ORDER[role])


def with_employee_role(values: Iterable[Role | str]) -> list[Role]:
    return unique_roles([Role.EMPLOYEE, *(values or [])])


def employee_to_read(
    employee: Employee,
    roles: Iterable[Role | str],
    is_supervisor: bool = False,
) -> EmployeeRead:
    return EmployeeRead.model_validate(employee).model_copy(
        update={"roles": unique_roles(roles), "is_supervisor": is_supervisor}
    )
