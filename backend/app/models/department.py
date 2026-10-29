from sqlalchemy import BigInteger, Boolean, Column, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from app.models.base import BaseModel


class Department(BaseModel, SQLModel, table=True):
    """A department inside a division. Named `department` in the database."""

    __tablename__ = "department"
    __table_args__ = (
        # Department names must be unique *within* their division (FR-ORG-2).
        UniqueConstraint("division_id", "name", name="uq_department_division_name"),
    )

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    division_id: int = Field(foreign_key="division.id", sa_type=BigInteger, nullable=False)
    name: str = Field(nullable=False, max_length=150)
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
    )


# --- Pydantic-only models (never a database table) -------------------------


class DepartmentCreate(SQLModel):
    division_id: int
    name: str = Field(min_length=1, max_length=150)
    is_active: bool = True


class DepartmentUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    is_active: bool | None = None


class DepartmentRead(SQLModel):
    id: int
    division_id: int
    name: str
    is_active: bool
