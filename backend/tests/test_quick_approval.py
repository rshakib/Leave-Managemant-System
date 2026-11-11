import asyncio
import datetime
from decimal import Decimal
import secrets
import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.auth_tokens import ApprovalActionToken
from app.models.employee import Employee, Role
from app.models.leave_request import (
    ApprovalStatus,
    LeaveRequest,
    LeaveRequestApproval,
    RequestStatus,
)
from app.models.leave_type import LeaveType
from app.routers.approvals import (
    QuickApprovalDecideIn,
    quick_decide,
    quick_verify,
)
from app.services.approval_rules import Action
from app.services.security_rules import hash_token


def test_quick_verify_success():
    async def _run():
        raw_token = secrets.token_urlsafe(32)
        now_utc = datetime.datetime.now(datetime.timezone.utc)

        # Setup mock session and entities
        mock_token_record = ApprovalActionToken(
            id=10,
            approval_id=100,
            token_hash=hash_token(raw_token),
            action="APPROVE",
            expires_at=now_utc + datetime.timedelta(days=7),
            used_at=None,
        )
        mock_approval = LeaveRequestApproval(
            id=100,
            leave_request_id=50,
            approver_id=2,
            status=ApprovalStatus.PENDING,
        )
        mock_request = LeaveRequest(
            id=50,
            employee_id=1,
            leave_type_id=1,
            leave_year_id=1,
            start_date=datetime.date(2026, 11, 1),
            end_date=datetime.date(2026, 11, 2),
            day_type="FULL_DAY",
            chargeable_days=Decimal("2.00"),
            reason="Attending wedding",
            status=RequestStatus.PENDING,
        )
        mock_employee = Employee(id=1, full_name="Alice Smith", employee_code="EMP-1", email="alice@example.com")
        mock_approver = Employee(id=2, full_name="Bob Jones", employee_code="EMP-2", email="bob@example.com")
        mock_leave_type = LeaveType(id=1, name="Annual Leave", code="AL")

        class FakeSession:
            async def scalar(self, stmt):
                return mock_token_record

            async def get(self, model, ident):
                if model == LeaveRequestApproval:
                    return mock_approval
                if model == LeaveRequest:
                    return mock_request
                if model == Employee:
                    return mock_employee if ident == 1 else mock_approver
                if model == LeaveType:
                    return mock_leave_type
                return None

        fake_session = FakeSession()
        result = await quick_verify(token=raw_token, session=fake_session)

        assert result.request_id == 50
        assert result.employee_name == "Alice Smith"
        assert result.approver_name == "Bob Jones"
        assert result.chargeable_days == Decimal("2.00")
        assert result.suggested_action == "APPROVE"

    asyncio.run(_run())


def test_quick_verify_used_or_expired_token():
    async def _run():
        raw_token = secrets.token_urlsafe(32)
        now_utc = datetime.datetime.now(datetime.timezone.utc)

        # 1. Used token
        used_token_record = ApprovalActionToken(
            id=11,
            approval_id=101,
            token_hash=hash_token(raw_token),
            action="APPROVE",
            expires_at=now_utc + datetime.timedelta(days=7),
            used_at=now_utc - datetime.timedelta(hours=1),
        )

        mock_approval_used = LeaveRequestApproval(id=101, leave_request_id=50, approver_id=2, status=ApprovalStatus.PENDING)
        mock_request_pending = LeaveRequest(id=50, status=RequestStatus.PENDING)

        class FakeSessionUsed:
            async def scalar(self, stmt):
                return used_token_record

            async def get(self, model, ident):
                if model == LeaveRequestApproval:
                    return mock_approval_used
                if model == LeaveRequest:
                    return mock_request_pending
                return None

        with pytest.raises(HTTPException) as exc_info:
            await quick_verify(token=raw_token, session=FakeSessionUsed())
        assert exc_info.value.status_code == 410
        assert "already been used" in exc_info.value.detail

        # 2. Expired token
        expired_token_record = ApprovalActionToken(
            id=12,
            approval_id=102,
            token_hash=hash_token(raw_token),
            action="APPROVE",
            expires_at=now_utc - datetime.timedelta(minutes=10),
            used_at=None,
        )
        mock_approval_expired = LeaveRequestApproval(id=102, leave_request_id=50, approver_id=2, status=ApprovalStatus.PENDING)

        class FakeSessionExpired:
            async def scalar(self, stmt):
                return expired_token_record

            async def get(self, model, ident):
                if model == LeaveRequestApproval:
                    return mock_approval_expired
                if model == LeaveRequest:
                    return mock_request_pending
                return None

        with pytest.raises(HTTPException) as exc_info:
            await quick_verify(token=raw_token, session=FakeSessionExpired())
        assert exc_info.value.status_code == 410
        assert "expired" in exc_info.value.detail

    asyncio.run(_run())


def test_quick_decide_reject_requires_reason():
    async def _run():
        raw_token = secrets.token_urlsafe(32)
        now_utc = datetime.datetime.now(datetime.timezone.utc)

        mock_token_record = ApprovalActionToken(
            id=13,
            approval_id=103,
            token_hash=hash_token(raw_token),
            action="REJECT",
            expires_at=now_utc + datetime.timedelta(days=7),
            used_at=None,
        )
        mock_approval = LeaveRequestApproval(
            id=103,
            leave_request_id=51,
            approver_id=3,
            status=ApprovalStatus.PENDING,
        )
        mock_approver = Employee(id=3, full_name="Cara", email="cara@example.com")

        class FakeSession:
            async def scalar(self, stmt):
                return mock_token_record

            async def get(self, model, ident):
                if model == LeaveRequestApproval:
                    return mock_approval
                if model == Employee:
                    return mock_approver
                return None

        # Rejection with empty comment should raise 400
        with pytest.raises(HTTPException) as exc_info:
            await quick_decide(
                payload=QuickApprovalDecideIn(token=raw_token, action=Action.REJECT, comment=""),
                session=FakeSession(),
            )
        assert exc_info.value.status_code == 400
        assert "rejection reason must be" in exc_info.value.detail

    asyncio.run(_run())


def test_quick_decide_already_approved():
    async def _run():
        raw_token = secrets.token_urlsafe(32)
        now_utc = datetime.datetime.now(datetime.timezone.utc)

        mock_token_record = ApprovalActionToken(
            id=14,
            approval_id=104,
            token_hash=hash_token(raw_token),
            action="APPROVE",
            expires_at=now_utc + datetime.timedelta(days=7),
            used_at=now_utc - datetime.timedelta(minutes=5),  # already used
        )
        mock_approval = LeaveRequestApproval(
            id=104,
            leave_request_id=52,
            approver_id=2,
            status=ApprovalStatus.APPROVED,
        )
        mock_request = LeaveRequest(
            id=52,
            status=RequestStatus.APPROVED,
        )

        class FakeSession:
            async def scalar(self, stmt):
                return mock_token_record

            async def get(self, model, ident):
                if model == LeaveRequestApproval:
                    return mock_approval
                if model == LeaveRequest:
                    return mock_request
                return None

        result = await quick_decide(
            payload=QuickApprovalDecideIn(token=raw_token, action=Action.APPROVE),
            session=FakeSession(),
        )

        assert result.ok is True
        assert result.already_decided is True
        assert result.status == RequestStatus.APPROVED
        assert "already been approved" in result.message

    asyncio.run(_run())


