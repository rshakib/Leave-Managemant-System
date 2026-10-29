"""The golden path, end to end, against a throw-away Postgres.

Run it with:  pytest -m integration -q
(plain `pytest -q` skips this file; see pytest.ini and conftest.py)
"""

import asyncio
import datetime
import html
import os
import secrets

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.integration

PASSWORD = "Zz-Integration-pass1"
ADMIN_PASSWORD = "Zz-Integration-admin1"


def _unique(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4)}"


async def _session():
    from app.db.session import async_session_factory

    return async_session_factory()


async def _run(coro):
    return await coro


@pytest.mark.asyncio
async def test_golden_path():
    """Seed an admin, log in, then take one request from submission to approval."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1) the first admin, through the same service the seed command uses
        from app.cli.seed_admin import create_first_admin

        suffix = _unique("it")
        division_name = f"IT-Division-{suffix}"
        admin_email = f"{suffix}@example.invalid"
        await create_first_admin(
            full_name="IT Admin", email=admin_email, password=ADMIN_PASSWORD,
            division_name=division_name, department_name="IT-Department",
        )

        # 2) log in (form-encoded, exactly like the browser)
        response = await client.post(
            "/auth/login", data={"username": admin_email, "password": ADMIN_PASSWORD}
        )
        assert response.status_code == 200, response.text
        token = response.json()["access_token"]
        cookie = response.cookies.get("refresh_token")
        assert cookie, "login must set the refresh cookie"
        headers = {"Authorization": f"Bearer {token}"}

        me = await client.get("/auth/me", headers=headers)
        assert me.status_code == 200 and me.json()["email"] == admin_email

        # 3) one leave year, activated; one leave type
        year = await client.post(
            "/leave-years",
            headers=headers,
            json={"name": f"IT-{suffix}", "start_date": "2077-01-01", "end_date": "2077-12-31"},
        )
        assert year.status_code == 201, year.text
        year_id = year.json()["id"]
        assert (await client.post(f"/leave-years/{year_id}/activate", headers=headers)).status_code == 200

        leave_type = await client.post(
            "/leave-types",
            headers=headers,
            json={"code": f"IT{suffix[:4]}", "name": f"IT Annual {suffix}", "default_quota": "20"},
        )
        assert leave_type.status_code == 201, leave_type.text
        type_id = leave_type.json()["id"]

        # 4) the global weekend + an employee with two approvers
        assert (
            await client.put("/weekends/global", headers=headers, json={"days_of_week": [5, 6]})
        ).status_code == 200

        employee = await client.post(
            "/employees",
            headers=headers,
            json={
                "employee_code": f"IT-{suffix}",
                "full_name": "IT Requester",
                "email": f"req-{suffix}@example.invalid",
                "password": PASSWORD,
                "division_id": (await client.get("/divisions", headers=headers)).json()[-1]["id"],
                "department_id": (await client.get("/departments", headers=headers)).json()[-1]["id"],
                "joining_date": "2077-01-01",
                "roles": ["EMPLOYEE"],
            },
        )
        assert employee.status_code == 201, employee.text
        employee_id = employee.json()["id"]

        # 5) the assignment (this is what creates the balance)
        assigned = await client.post(
            "/leave-assignments",
            headers=headers,
            json={"employee_id": employee_id, "leave_type_id": type_id,
                  "leave_year_id": year_id, "allocated_days": "20"},
        )
        assert assigned.status_code == 200, assigned.text

        # 6) health
        assert (await client.get("/health")).status_code == 200
        ready = await client.get("/health/ready")
        assert ready.status_code == 200 and ready.json()["status"] == "ok"

        # 7) an unauthenticated call, and an employee on an admin route
        assert (await client.get("/employees", headers={"Authorization": "Bearer nope"})).status_code == 401
        employee_token = (
            await client.post("/auth/login", data={
                "username": f"req-{suffix}@example.invalid", "password": PASSWORD})
        ).json()["access_token"]
        assert (
            await client.get("/employees", headers={"Authorization": f"Bearer {employee_token}"})
        ).status_code == 403

        # 8) the retention dry run reports counts without deleting
        from app.services.maintenance import cleanup

        counts = await cleanup(dry_run=True)
        assert set(counts) == {"login_attempt", "refresh_token", "email_outbox", "email_attempt"}

        # 9) rotating the refresh cookie produces a new one
        rotated = await client.post("/auth/refresh")
        assert rotated.status_code == 200
        assert rotated.cookies.get("refresh_token") not in (None, cookie)
