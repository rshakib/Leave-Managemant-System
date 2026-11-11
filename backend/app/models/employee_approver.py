from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from app.models.base import BaseModel


class EmployeeApprover(BaseModel, SQLModel, table=True):
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


class ApproverRead(SQLModel):
    id: int
    employee_code: str
    full_name: str
    is_supervisor: bool = False


class ApproversUpdate(SQLModel):
    approver_ids: list[int] = Field(default_factory=list)


class EmployeeApproversRead(SQLModel):
    employee_id: int
    employee_code: str
    employee_name: str
    division_id: int
    department_id: int
    supervisor_id: int | None = None
    approvers: list[ApproverRead]
