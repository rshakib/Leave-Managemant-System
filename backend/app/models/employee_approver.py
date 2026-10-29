from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from app.models.base import BaseModel


class EmployeeApprover(BaseModel, SQLModel, table=True):
    """Which employees may approve leave for a given employee (FR-APR-1).

    Rows are **soft-deactivated**, never deleted, so an approver that is removed
    and later added again reuses the same row (DECISIONS D-79).

    `employee_id <> approver_id` is enforced by the database as well as the API
    (DECISIONS D-30).
    """

    __tablename__ = "employee_approver"
    __table_args__ = (
        UniqueConstraint("employee_id", "approver_id", name="uq_employee_approver"),
        CheckConstraint(
            "employee_id <> approver_id", name="ck_employee_approver_not_self"
        ),
    )

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    employee_id: int = Field(foreign_key="employee.id", sa_type=BigInteger, nullable=False)
    approver_id: int = Field(foreign_key="employee.id", sa_type=BigInteger, nullable=False)
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
    )


# --- Pydantic-only models (never a database table) -------------------------


class ApproverRead(SQLModel):
    """One approver, as shown in the UI."""

    id: int
    employee_code: str
    full_name: str
    is_supervisor: bool = False


class ApproversUpdate(SQLModel):
    # The active set becomes EXACTLY this list (D-77). An empty list is allowed.
    approver_ids: list[int] = Field(default_factory=list)


class EmployeeApproversRead(SQLModel):
    """One employee row in the admin overview."""

    employee_id: int
    employee_code: str
    employee_name: str
    division_id: int
    department_id: int
    supervisor_id: int | None = None
    approvers: list[ApproverRead]
