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
    """The roles an employee can hold (a user may hold several)."""

    ADMIN = "ADMIN"
    EMPLOYEE = "EMPLOYEE"
    APPROVER = "APPROVER"


class Employee(BaseModel, SQLModel, table=True):
    """An employee. Named `employee` in the database."""

    __tablename__ = "employee"

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    employee_code: str = Field(unique=True, nullable=False, max_length=50)
    full_name: str = Field(nullable=False, max_length=150)
    email: str = Field(unique=True, nullable=False, max_length=255)
    # repr=False keeps the hash out of logs and tracebacks.
    password_hash: str = Field(nullable=False, max_length=255, repr=False)
    phone: str | None = Field(default=None, max_length=30)
    designation: str | None = Field(default=None, max_length=100)
    division_id: int = Field(foreign_key="division.id", sa_type=BigInteger, nullable=False)
    department_id: int = Field(foreign_key="department.id", sa_type=BigInteger, nullable=False)
    # Self-referencing foreign key: an employee's supervisor is another employee.
    supervisor_id: int | None = Field(
        default=None, foreign_key="employee.id", sa_type=BigInteger, nullable=True
    )
    joining_date: date = Field(nullable=False)
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
    )
    # Set when SOMEBODY ELSE chose this password (an admin created the account or
    # reset it): the employee must pick their own before using the app (D-190).
    # The database default is false, so existing employees are never locked out.
    must_change_password: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )


class EmployeeRole(SQLModel, table=True):
    """Join table: which roles an employee holds (DECISIONS D-13).

    The composite primary key ``(employee_id, role)`` is what makes a role
    unique per employee.
    """

    __tablename__ = "employee_role"
    __table_args__ = (
        PrimaryKeyConstraint("employee_id", "role", name="pk_employee_role"),
        CheckConstraint(
            "role IN ('ADMIN', 'EMPLOYEE', 'APPROVER')", name="ck_employee_role_role"
        ),
    )

    employee_id: int = Field(foreign_key="employee.id", sa_type=BigInteger, nullable=False)
    role: Role = Field(sa_column=Column(String(20), nullable=False))


# --- Pydantic-only models (never a database table) -------------------------


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
    # The admin sets the initial password (DECISIONS D-28). Never echoed back.
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)
    # EMPLOYEE is added automatically, so an empty list simply means
    # "a plain employee" (DECISIONS D-152).
    roles: list[Role] = Field(default_factory=lambda: [Role.EMPLOYEE])
    # The admin typed this password and therefore knows it, so the employee must
    # choose their own at first sign-in (D-190). Pass false for a demo or service
    # account whose password is handed over another way.
    must_change_password: bool = True


class EmployeeUpdate(SQLModel):
    employee_code: str | None = Field(default=None, min_length=1, max_length=50)
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    email: EmailStr | None = None
    # An admin can reset a password (DECISIONS D-28).
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
    # Only meaningful together with `password`: true forces the employee to pick
    # their own password next time, false waives it (D-190).
    must_change_password: bool | None = None

    @field_validator("email", mode="after")
    @classmethod
    def _normalise_email(cls, value: str | None) -> str | None:
        return None if value is None else _lowercase_email(value)


class EmployeeRead(EmployeeBase):
    """Response shape — deliberately has no password_hash field."""

    # Output only: the stored value is returned as-is. Re-validating it here
    # would turn an odd-but-already-stored address (for example a reserved
    # ".invalid" domain) into a 500 on a simple read.
    email: str
    id: int
    employee_code: str
    roles: list[Role] = Field(default_factory=list)
    must_change_password: bool = False


# --- small shared helpers --------------------------------------------------

_ROLE_ORDER = {Role.ADMIN: 0, Role.EMPLOYEE: 1, Role.APPROVER: 2}


def unique_roles(values: Iterable[Role | str]) -> list[Role]:
    """Coerce to Role, drop duplicates, return in a stable order."""
    seen: list[Role] = []
    for value in values:
        role = Role(value)
        if role not in seen:
            seen.append(role)
    return sorted(seen, key=lambda role: _ROLE_ORDER[role])


def with_employee_role(values: Iterable[Role | str]) -> list[Role]:
    """Every employee ALWAYS holds EMPLOYEE; ADMIN/APPROVER are extras (D-152).

    Used by the write paths, so the role can never be dropped by a payload.
    """
    return unique_roles([Role.EMPLOYEE, *(values or [])])


def employee_to_read(employee: Employee, roles: Iterable[Role | str]) -> EmployeeRead:
    return EmployeeRead.model_validate(employee).model_copy(
        update={"roles": unique_roles(roles)}
    )
