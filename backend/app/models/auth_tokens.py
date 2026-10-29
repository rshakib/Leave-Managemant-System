import datetime
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlmodel import Field, SQLModel

from app.models.base import BaseModel


class RefreshToken(BaseModel, SQLModel, table=True):
    """One issued refresh token (DECISIONS D-163).

    Only the SHA-256 HASH of the token is stored, never the token itself, and
    never an IP address. The row is MUTABLE (revoked_at / replaced_at / last_used_at
    change), so it inherits BaseModel.
    """

    __tablename__ = "refresh_token"
    __table_args__ = (
        Index("ix_refresh_token_employee_active", "employee_id", "revoked_at"),
        Index("ix_refresh_token_family", "family_id"),
    )

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    employee_id: int = Field(
        foreign_key="employee.id", sa_type=BigInteger, nullable=False
    )
    family_id: uuid.UUID = Field(sa_column=Column(UUID(as_uuid=True), nullable=False))
    token_hash: str = Field(unique=True, nullable=False, max_length=64)
    issued_at: datetime.datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    )
    expires_at: datetime.datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    family_started_at: datetime.datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    last_used_at: datetime.datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    revoked_at: datetime.datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    replaced_at: datetime.datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    replaced_by_id: int | None = Field(
        default=None, sa_column=Column(BigInteger, ForeignKey("refresh_token.id"), nullable=True)
    )
    user_agent: str | None = Field(default=None, max_length=200)


class LoginAttempt(BaseModel, SQLModel, table=True):
    """One login try, for rate limiting and the admin view (DECISIONS D-164).

    Deliberately NOT append-only (it inherits BaseModel): it is telemetry, and a
    future cleanup job (16D) must be able to prune old rows. It holds no password
    material at all — only the normalised email, a keyed HMAC of the IP, and the
    outcome.
    """

    __tablename__ = "login_attempt"
    __table_args__ = (
        Index("ix_login_attempt_email", "email_normalized", "created_at"),
        Index("ix_login_attempt_ip", "ip_hash", "created_at"),
        Index("ix_login_attempt_email_ip", "email_normalized", "ip_hash", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    email_normalized: str = Field(nullable=False, max_length=254)
    ip_hash: str = Field(nullable=False, max_length=64)
    success: bool = Field(
        sa_column=Column(Boolean, nullable=False, server_default=text("false"))
    )


class PasswordResetToken(BaseModel, SQLModel, table=True):
    """A time-limited, single-use token for password resets.

    Stores only the SHA-256 hash of the token, never the plaintext token itself.
    """

    __tablename__ = "password_reset_token"
    __table_args__ = (
        Index("ix_password_reset_token_hash", "token_hash", unique=True),
        Index("ix_password_reset_token_employee", "employee_id", "expires_at"),
    )

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    employee_id: int = Field(
        foreign_key="employee.id", sa_type=BigInteger, nullable=False
    )
    token_hash: str = Field(nullable=False, max_length=64)
    expires_at: datetime.datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    used_at: datetime.datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    ip_hash: str | None = Field(default=None, max_length=64)
