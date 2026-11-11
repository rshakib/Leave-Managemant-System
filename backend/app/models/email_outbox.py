import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlmodel import Field, SQLModel

from app.models.base import BaseModel


class EmailStatus(str, Enum):
    PENDING = "PENDING"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class EmailOutbox(BaseModel, SQLModel, table=True):
    __tablename__ = "email_outbox"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'SENDING', 'SENT', 'FAILED')",
            name="ck_email_outbox_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_email_outbox_attempts"),
        Index("ix_email_outbox_due", "status", "next_attempt_at"),
        Index("ix_email_outbox_request", "related_request_id"),
    )

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    event_type: str = Field(nullable=False, max_length=40)
    to_emails: list[str] = Field(sa_column=Column(ARRAY(Text), nullable=False))
    cc_emails: list[str] = Field(
        sa_column=Column(
            ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
        )
    )
    payload: dict = Field(
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    )
    related_request_id: int | None = Field(
        default=None, foreign_key="leave_request.id", sa_type=BigInteger, nullable=True
    )
    status: EmailStatus = Field(
        sa_column=Column(String(20), nullable=False, server_default=text("'PENDING'"))
    )
    attempts: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default=text("0"))
    )
    max_attempts: int = Field(
        sa_column=Column(Integer, nullable=False, server_default=text("5"))
    )
    next_attempt_at: datetime.datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        )
    )
    claimed_at: datetime.datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    sent_at: datetime.datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_error: str | None = Field(default=None, max_length=500)
    dedupe_key: str | None = Field(default=None, max_length=200, unique=True)


class EmailAttempt(BaseModel, SQLModel, table=True):
    __tablename__ = "email_attempt"

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    outbox_id: int = Field(
        foreign_key="email_outbox.id", sa_type=BigInteger, nullable=False
    )
    attempted_at: datetime.datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        )
    )
    success: bool = Field(sa_column=Column(Boolean, nullable=False))
    error: str | None = Field(default=None, max_length=500)
    backend: str = Field(sa_column=Column(String(30), nullable=False))


class EmailAttemptRead(SQLModel):
    id: int
    attempted_at: datetime.datetime
    success: bool
    error: str | None = None
    backend: str


class EmailOutboxRead(SQLModel):
    id: int
    event_type: str
    to_emails: list[str]
    cc_emails: list[str]
    status: EmailStatus
    attempts: int
    max_attempts: int
    next_attempt_at: datetime.datetime
    claimed_at: datetime.datetime | None = None
    sent_at: datetime.datetime | None = None
    last_error: str | None = None
    related_request_id: int | None = None
    dedupe_key: str | None = None
    created_at: datetime.datetime


class EmailOutboxDetail(EmailOutboxRead):
    payload: dict = Field(default_factory=dict)
    attempt_history: list[EmailAttemptRead] = Field(default_factory=list)
    subject: str | None = None
    body_text: str | None = None
    body_html: str | None = None


class QueueRunResult(SQLModel):
    processed: int = 0
    sent: int = 0
    failed: int = 0
    still_pending: int = 0
    reminders_queued: int = 0
