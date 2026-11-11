from sqlalchemy import BigInteger, Boolean, Column, text
from sqlmodel import Field, SQLModel

from app.models.base import BaseModel


class Division(BaseModel, SQLModel, table=True):
    __tablename__ = "division"

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    name: str = Field(unique=True, nullable=False, max_length=150)
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
    )


class DivisionCreate(SQLModel):
    name: str = Field(min_length=1, max_length=150)
    is_active: bool = True


class DivisionUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    is_active: bool | None = None


class DivisionRead(SQLModel):
    id: int
    name: str
    is_active: bool
