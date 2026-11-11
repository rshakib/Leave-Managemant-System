"""Populate a demo database via the in-process ASGI API."""

from __future__ import annotations

import argparse
import asyncio
import datetime
import getpass
import os
import pathlib
import secrets
import subprocess
import sys
from zoneinfo import ZoneInfo

import httpx

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]
CREDENTIALS_FILE = BACKEND_DIR / "demo_credentials.txt"
DEMO_PREFIX = "DEMO-"
EMAIL_DOMAIN = "demo.example.com"
FLAG = "--i-understand-this-is-a-demo-database"
REMOTE_FLAG = "--allow-remote-demo-database"
REAL_DB_FLAG = "--allow-real-database"


class DemoError(RuntimeError):
    pass


def database_name(database_url: str) -> str:
    tail = (database_url or "").split("?", 1)[0].rstrip("/")
    if "/" not in tail:
        return ""
    return tail.rsplit("/", 1)[-1]


def guard_environment(acknowledged: bool) -> None:
    if not acknowledged:
        raise DemoError(
            f"refusing to run: pass {FLAG} to confirm this is a demo database."
        )


def guard_app_env(app_env: str) -> None:
    if str(app_env).lower() == "production":
        raise DemoError("refusing to run: APP_ENV is production.")


def guard_database_name(name: str, allow_remote: bool) -> None:
    if name.endswith("_demo_test"):
        return
    if allow_remote:
        return
    raise DemoError(
        f"refusing to run: the database is named '{name}', which does not end with "
        f"'_demo_test'. Pass {REMOTE_FLAG} if this really is your throw-away demo "
        "database (a Supabase database is always called 'postgres')."
    )


def guard_not_a_development_database(employees: list[dict], *, allow_real: bool = False) -> None:
    if allow_real:
        return
    outside = [e for e in employees if not str(e.get("employee_code", "")).startswith(DEMO_PREFIX)]
    if len(outside) > 1:
        raise DemoError(
            f"refusing to run: this database already holds {len(outside)} employees that "
            f"are not '{DEMO_PREFIX}' rows, so it looks like a real or a development "
            "database. Only a fresh demo database (admin + nothing else) is accepted."
        )


def demo_emails() -> dict[str, str]:
    return {code: f"{code.lower().replace('-', '.')}@{EMAIL_DOMAIN}" for code, *_ in PEOPLE}


def make_password() -> str:
    return f"Demo-{secrets.token_urlsafe(12)}-9Aa"


def sample_pdf(label: str) -> bytes:
    text = f"SAMPLE DOCUMENT - demo data only - {label}"
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 120]"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        b"4 0 obj<</Length 90>>stream\nBT /F1 12 Tf 20 70 Td ("
        + text.encode("ascii", "replace")
        + b") Tj ET\nendstream\nendobj\n"
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )


FILE_OK = "ok"
FILE_MISSING = "missing"
FILE_BROKEN = "broken"

REUSE_PASSWORD = "REUSE"
RESET_PASSWORDS = "RESET"
CREATE_PASSWORD = "CREATE"
STOP = "STOP"

CREDENTIALS_HEADER = "code,email,role,password"
SHARED_PREFIX = "# shared demo password"

CREDENTIALS_HELP = (
    "Delete backend/demo_credentials.txt and run the command again: it will set one "
    "fresh shared password for the existing demo employees through the admin's "
    "password-reset API and rewrite the file."
)


def parse_credentials_file(text: str | None, expected: dict[str, str]) -> tuple[str, str | None]:
    if text is None:
        return FILE_MISSING, None

    shared: str | None = None
    rows: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(SHARED_PREFIX):
            if shared is not None:
                return FILE_BROKEN, None
            shared = line.split(":", 1)[1].strip() if ":" in line else ""
        elif line and not line.startswith("#") and line != CREDENTIALS_HEADER:
            parts = line.split(",")
            if len(parts) == 4:
                rows[parts[0]] = (parts[1], parts[3])

    if not shared:
        return FILE_BROKEN, None
    if set(rows) != set(expected):
        return FILE_BROKEN, None
    for code, email in expected.items():
        recorded_email, recorded_password = rows[code]
        if recorded_email.strip().lower() != email.lower() or recorded_password != shared:
            return FILE_BROKEN, None
    return FILE_OK, shared


def read_credentials_file(expected: dict[str, str], path: pathlib.Path | None = None):
    file = path or CREDENTIALS_FILE
    try:
        text = file.read_text()
    except FileNotFoundError:
        return FILE_MISSING, None
    except OSError:
        return FILE_BROKEN, None
    return parse_credentials_file(text, expected)


def decide_credential_action(file_state: str, demo_employees_exist: bool,
                             can_reset: bool) -> str:
    if not demo_employees_exist:
        return CREATE_PASSWORD
    if file_state == FILE_OK:
        return REUSE_PASSWORD
    return RESET_PASSWORDS if can_reset else STOP


class RateLimited(DemoError):
    pass


class LoginRefused(DemoError):
    pass


class Session:
    def __init__(self, client: httpx.AsyncClient, label: str):
        self.client = client
        self.label = label
        self._tokens: dict[str, str] = {}

    def _headers(self, token: str | None) -> None:
        if token:
            self.client.headers["Authorization"] = f"Bearer {token}"
        else:
            self.client.headers.pop("Authorization", None)

    async def call(self, method: str, path: str, *, expect=(200, 201), **kwargs):
        actor = kwargs.pop("actor", None)
        response = await self.client.request(method, path, **kwargs)
        if response.status_code == 429:
            raise RateLimited(
                f"{method} {path} was rate limited (HTTP 429); "
                f"Retry-After={response.headers.get('Retry-After', 'unknown')} seconds."
            )
        if response.status_code == 401 and path.endswith("/auth/login"):
            raise LoginRefused(f"the sign-in for '{actor or self.label}' was refused (401)")
        if response.status_code not in expect:
            detail = ""
            try:
                detail = str(response.json().get("detail"))[:300]
            except Exception:
                detail = response.text[:200]
            raise DemoError(
                f"{self.label}: {method} {path} answered {response.status_code} - {detail}"
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def login(self, email: str, password: str, actor: str = "the administrator") -> str:
        data = await self.call(
            "POST", "/auth/login",
            expect=(200,),
            data={"username": email, "password": password},
            actor=f"{actor} ({email})",
        )
        token = data["access_token"]
        self._headers(token)
        return token

    async def as_employee(self, email: str, password: str) -> None:
        token = self._tokens.get(email)
        if token is None:
            token = await self.login(email, password, actor="a demo employee")
            self._tokens[email] = token
        self._headers(token)

    def as_admin(self, token: str) -> None:
        self._headers(token)


async def find(client: Session, path: str, **params):
    payload = await client.call("GET", path, expect=(200,), params=params or None)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "results", "rows", "data"):
            if isinstance(payload.get(key), list):
                return payload[key]
        for value in payload.values():
            if isinstance(value, list):
                return value
    return []


async def ensure_division(client: Session, name: str) -> dict:
    for row in await find(client, "/divisions"):
        if row["name"] == name:
            return row
    return await client.call("POST", "/divisions", json={"name": name, "is_active": True})


async def ensure_department(client: Session, division_id: int, name: str) -> dict:
    for row in await find(client, "/departments", division_id=division_id):
        if row["name"] == name:
            return row
    return await client.call(
        "POST", "/departments", json={"division_id": division_id, "name": name}
    )


async def ensure_leave_type(client: Session, **wanted) -> dict:
    for row in await find(client, "/leave-types"):
        if row["code"] == wanted["code"]:
            return row
    return await client.call("POST", "/leave-types", json=wanted)


WORKING_KINDS = {"WORKING", "WORKING_DAY", "WORKDAY", "CHARGEABLE"}
NON_WORKING_KINDS = {"WEEKEND", "HOLIDAY", "NON_WORKING", "OFF", "LEAVE"}


def _day_is_working(day: dict) -> bool | None:
    for key in ("is_working_day", "working", "is_chargeable", "chargeable", "counts"):
        value = day.get(key)
        if isinstance(value, bool):
            return value
    for key in ("kind", "day_kind", "type", "status"):
        value = str(day.get(key) or "").upper()
        if value in WORKING_KINDS:
            return True
        if value in NON_WORKING_KINDS:
            return False
    return None


def parse_preview(payload) -> dict[str, bool]:
    days = None
    if isinstance(payload, dict):
        for key in ("days", "items", "dates", "calendar", "results"):
            if isinstance(payload.get(key), list):
                days = payload[key]
                break
        if days is None and all(isinstance(v, dict) for v in payload.values()):
            days = [dict(day, date=key) for key, day in payload.items()]
    elif isinstance(payload, list):
        days = payload
    if not days:
        raise DemoError("/calendar/preview returned no per-day list; cannot pick dates safely.")

    working: dict[str, bool] = {}
    for day in days:
        date = str(day.get("date") or day.get("day") or "")[:10]
        flag = _day_is_working(day)
        if date and flag is not None:
            working[date] = flag
    if not working:
        raise DemoError("/calendar/preview per-day entries carry no working/chargeable flag.")
    return working


async def preview_working_days(client: Session, start: datetime.date, end: datetime.date) -> dict:
    payload = await client.call(
        "GET", "/calendar/preview", expect=(200,),
        params={"start_date": start.isoformat(), "end_date": end.isoformat()},
    )
    return parse_preview(payload)


async def would_be_accepted(client: Session, leave_type_id: int, start, end, day_type) -> dict | None:
    response = await client.client.request(
        "GET", "/leave-requests/check",
        params={
            "leave_type_id": leave_type_id,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "day_type": day_type,
        },
    )
    return response.json() if response.status_code == 200 else None


async def find_window(client: Session, leave_type_id: int, working_days: int, *, day_type="FULL_DAY",
                      earliest: datetime.date | None = None, latest_span: int = 75):
    today = await today_in_org_timezone(client)
    cursor = earliest or (today + datetime.timedelta(days=3))
    for offset in range(latest_span):
        start = cursor + datetime.timedelta(days=offset)
        working = await preview_working_days(client, start, start + datetime.timedelta(days=30))
        days = sorted(day for day, works in working.items() if works)
        inside = [day for day in days if day >= start.isoformat()]
        if len(inside) < working_days:
            continue
        end = datetime.date.fromisoformat(inside[working_days - 1])
        if day_type != "FULL_DAY":
            start = datetime.date.fromisoformat(inside[0])
            end = start
        check = await would_be_accepted(client, leave_type_id, start, end, day_type)
        if check:
            return start, end
    raise DemoError("could not find a valid free date range for the demo requests.")


async def cross_month_window(client: Session, leave_type_id: int, needed: int = 2):
    today = await today_in_org_timezone(client)
    month_end = (today.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
    while month_end <= today + datetime.timedelta(days=2):
        month_end = (month_end + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)
    for back in range(4):
        start = month_end - datetime.timedelta(days=back)
        working = await preview_working_days(client, start, start + datetime.timedelta(days=20))
        days = sorted(day for day, works in working.items() if works and day >= start.isoformat())
        if len(days) < needed:
            continue
        end = datetime.date.fromisoformat(days[needed - 1])
        if end.month != start.month and await would_be_accepted(client, leave_type_id, start, end, "FULL_DAY"):
            return start, end
    return None, None


async def today_in_org_timezone(client: Session) -> datetime.date:
    from app.core.config import settings

    return datetime.datetime.now(ZoneInfo(settings.org_timezone)).date()


DIVISIONS = ["Operations", "Corporate Services"]
DEPARTMENTS = {
    "Operations": ["Field Operations", "Technical Services"],
    "Corporate Services": ["Human Resources", "Finance"],
}

PEOPLE = [
    ("DEMO-001", "Rafiqul Islam", "Head of Field Operations", "Operations", "Field Operations", 2019, ["APPROVER"]),
    ("DEMO-002", "Nusrat Jahan", "Senior Field Officer", "Operations", "Field Operations", 2020, ["APPROVER"]),
    ("DEMO-003", "Tanvir Ahmed", "Technical Lead", "Operations", "Technical Services", 2020, ["APPROVER"]),
    ("DEMO-004", "Farhana Akter", "HR Officer", "Corporate Services", "Human Resources", 2021, ["APPROVER"]),
    ("DEMO-005", "Mahmudul Hasan", "Accounts Officer", "Corporate Services", "Finance", 2021, []),
    ("DEMO-006", "Sadia Rahman", "Technical Officer", "Operations", "Technical Services", 2022, []),
    ("DEMO-007", "Imran Kabir", "Field Officer", "Operations", "Field Operations", 2022, []),
    ("DEMO-008", "Rehana Begum", "HR Assistant", "Corporate Services", "Human Resources", 2023, []),
    ("DEMO-009", "Arif Hossain", "Finance Assistant", "Corporate Services", "Finance", 2023, []),
    ("DEMO-010", "Shirin Sultana", "Team Leader", "Operations", "Field Operations", 2019, []),
]

SUPERVISORS = {
    "DEMO-002": "DEMO-001", "DEMO-003": "DEMO-001", "DEMO-004": "DEMO-001",
    "DEMO-005": "DEMO-004", "DEMO-006": "DEMO-003", "DEMO-007": "DEMO-002",
    "DEMO-008": "DEMO-004", "DEMO-009": "DEMO-005", "DEMO-010": "DEMO-001",
}

APPROVERS = {
    "DEMO-002": ["DEMO-001", "DEMO-004"],
    "DEMO-003": ["DEMO-001"],
    "DEMO-004": ["DEMO-001"],
    "DEMO-005": ["DEMO-004"],
    "DEMO-006": ["DEMO-003", "DEMO-001"],
    "DEMO-007": ["DEMO-002"],
    "DEMO-008": ["DEMO-004"],
    "DEMO-009": ["DEMO-005"],
    "DEMO-010": ["DEMO-001"],
}

HOLIDAYS = [
    ("-02-21", "Language Day", "PUBLIC"),
    ("-03-17", "Company Foundation Day", "COMPANY"),
    ("-04-14", "New Year (Bengali)", "PUBLIC"),
    ("-05-01", "Labour Day", "PUBLIC"),
    ("-08-15", "Independence Day", "PUBLIC"),
    ("-09-25", "Annual Retreat", "COMPANY"),
    ("-12-16", "Victory Day", "PUBLIC"),
    ("-12-25", "Year-End Holiday", "COMPANY"),
]


async def ensure_weekend(client: Session) -> bool:
    response = await client.client.get("/weekends/global")
    if response.status_code == 200:
        return False
    await client.call("PUT", "/weekends/global", json={"days_of_week": [5, 6]})
    return True


async def ensure_leave_year(client: Session, year: int) -> dict:
    years = await find(client, "/leave-years")
    existing = next((row for row in years if row["name"] == str(year)), None)
    if existing:
        return existing
    created = await client.call(
        "POST", "/leave-years",
        json={"name": str(year), "start_date": f"{year}-01-01", "end_date": f"{year}-12-31"},
    )
    if not any(row.get("is_active") for row in years):
        await client.call("POST", f"/leave-years/{created['id']}/activate", expect=(200, 204))
    return created


async def ensure_holidays(client: Session, year_id: int, year: int) -> int:
    existing = {row["date"] for row in await find(client, "/holidays", leave_year_id=year_id)}
    created = 0
    for suffix, title, kind in HOLIDAYS:
        date = f"{year}{suffix}"
        if date in existing:
            continue
        await client.call(
            "POST", "/holidays",
            json={"leave_year_id": year_id, "date": date, "title": title, "type": kind},
        )
        created += 1
    return created


def approver_codes() -> set[str]:
    return {code for codes in APPROVERS.values() for code in codes}


def roles_for(code: str) -> list[str]:
    extra = next((row[6] for row in PEOPLE if row[0] == code), [])
    return ["EMPLOYEE", *sorted(set(extra) | ({"APPROVER"} if code in approver_codes() else set()))]


def _approver_ids_of(row: dict) -> set:
    for key in ("approver_ids", "approvers"):
        value = row.get(key)
        if isinstance(value, list):
            return {item.get("id") if isinstance(item, dict) else item for item in value}
    return set()


async def ensure_employees(client: Session, password: str, divisions: dict, departments: dict) -> tuple[dict, int]:
    existing = {row["employee_code"]: row for row in await find(client, "/employees")}
    emails = {}
    for code, name, designation, division, department, joined, _extra in PEOPLE:
        emails[code] = f"{code.lower().replace('-', '.')}@{EMAIL_DOMAIN}"
        if code in existing:
            wanted = roles_for(code)
            if sorted(existing[code].get("roles") or []) != sorted(wanted):
                await client.call("PATCH", f"/employees/{existing[code]['id']}", json={"roles": wanted})
            continue
        await client.call(
            "POST", "/employees",
            json={
                "employee_code": code,
                "full_name": name,
                "email": emails[code],
                "password": password,
                "designation": designation,
                "division_id": divisions[division]["id"],
                "department_id": departments[department]["id"],
                "joining_date": f"{joined}-06-01",
                "roles": roles_for(code),
                "must_change_password": False,
            },
        )
    existing = {row["employee_code"]: row for row in await find(client, "/employees")}
    by_code = {code: existing.get(code) for code, *_ in PEOPLE}

    for code, supervisor in SUPERVISORS.items():
        employee = by_code.get(code)
        if not employee:
            continue
        detail = await client.call("GET", f"/employees/{employee['id']}", expect=(200,))
        wanted = by_code[supervisor]["id"]
        if detail.get("supervisor_id") != wanted:
            await client.call(
                "PATCH", f"/employees/{employee['id']}", json={"supervisor_id": wanted}
            )
    current = {row.get("employee_id") or row.get("id"): _approver_ids_of(row)
               for row in await find(client, "/approver-assignments")}
    unchanged = 0
    for code, approvers in APPROVERS.items():
        ids = [by_code[approver]["id"] for approver in approvers]
        employee_id = by_code[code]["id"]
        if current.get(employee_id) == set(ids):
            unchanged += 1
            continue
        await client.call("PUT", f"/employees/{employee_id}/approvers", json={"approver_ids": ids})
    return by_code, unchanged


async def ensure_assignments(client: Session, by_code: dict, types: dict, year_id: int) -> int:
    created = 0
    wanted = {"AL": "20", "SL": "10"}
    for code, *_ in PEOPLE:
        employee = by_code[code]
        rows = await find(client, "/leave-balances", employee_id=employee["id"], leave_year_id=year_id)
        have = {row["leave_type_id"] for row in rows}
        for type_code, days in wanted.items():
            if types[type_code]["id"] in have:
                continue
            await client.call(
                "POST", "/leave-assignments",
                json={
                    "employee_id": employee["id"],
                    "leave_type_id": types[type_code]["id"],
                    "leave_year_id": year_id,
                    "allocated_days": days,
                },
            )
            created += 1
        if code in ("DEMO-004", "DEMO-008") and types["HL"]["id"] not in have:
            await client.call(
                "POST", "/leave-assignments",
                json={
                    "employee_id": employee["id"],
                    "leave_type_id": types["HL"]["id"],
                    "leave_year_id": year_id,
                    "allocated_days": "5",
                },
            )
            created += 1
    return created


async def submit(client: Session, email: str, password: str, leave_type_id: int, start, end,
                 *, day_type="FULL_DAY", reason="demo request", attachment: bytes | None = None) -> dict:
    await client.as_employee(email, password)
    files = {"__demo": (None, "1")} if attachment is None else {
        "attachment": ("sample.pdf", attachment, "application/pdf")
    }
    payload = await client.call(
        "POST", "/leave-requests", expect=(200, 201),
        data={
            "leave_type_id": str(leave_type_id),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "day_type": day_type,
            "reason": reason,
        },
        files=files,
    )
    return payload


async def approve_all(client: Session, request_id: int, approver_emails: list[tuple[str, str]]) -> None:
    for email, password in approver_emails:
        await client.as_employee(email, password)
        await client.call("POST", f"/leave-requests/{request_id}/approve", expect=(200,), json={"comment": "approved (demo)"})


async def has_any_request(client: Session, admin_token: str, employee_id: int) -> bool:
    client.as_admin(admin_token)
    return bool(await find(client, "/leave-requests", employee_id=employee_id))


async def build_requests(client: Session, password: str, by_code: dict, types: dict,
                         credentials: dict[str, str], year_id: int, admin_token: str) -> dict:
    made = {
        "pending": 0, "approved": 0, "rejected": 0, "cancelled": 0, "with_attachment": 0,
        "holiday_aware": 0, "half_day": 0, "cross_month": 0,
    }
    emails = {code: data["email"] for code, data in credentials.items()}

    async def fresh(code: str):
        return await has_any_request(client, admin_token, by_code[code]["id"])

    for code, needed in (("DEMO-002", 3), ("DEMO-007", 2)):
        if await fresh(code):
            continue
        await client.as_employee(emails[code], password)
        start, end = await find_window(client, types["AL"]["id"], needed)
        await submit(client, emails[code], password, types["AL"]["id"], start, end,
                     reason="Family function (demo)")
        made["pending"] += 1

    if not await fresh("DEMO-005"):
        await client.as_employee(emails["DEMO-005"], password)
        start, _ = await find_window(client, types["AL"]["id"], 1, day_type="FIRST_HALF")
        request = await submit(client, emails["DEMO-005"], password, types["AL"]["id"], start, start,
                               day_type="FIRST_HALF", reason="Half day - personal work (demo)")
        await approve_all(client, request["id"], [(emails["DEMO-004"], password)])
        made["approved"] += 1
        made["half_day"] += 1

    if not await fresh("DEMO-006"):
        await client.as_employee(emails["DEMO-006"], password)
        start, end = await cross_month_window(client, types["AL"]["id"], 2)
        if start is not None:
            request = await submit(client, emails["DEMO-006"], password, types["AL"]["id"], start, end,
                                   reason="Year-end travel (demo)")
            await approve_all(client, request["id"], [(emails["DEMO-003"], password), (emails["DEMO-001"], password)])
            made["approved"] += 1
            made["cross_month"] += 1

    if not await fresh("DEMO-003"):
        await client.as_employee(emails["DEMO-003"], password)
        start, end = await find_window(client, types["SL"]["id"], 2)
        request = await submit(client, emails["DEMO-003"], password, types["SL"]["id"], start, end,
                               reason="Sick (demo)")
        await client.as_employee(emails["DEMO-001"], password)
        await client.call("POST", f"/leave-requests/{request['id']}/reject",
                          json={"comment": "Critical maintenance window that week (demo)"})
        made["rejected"] += 1

    if not await fresh("DEMO-009"):
        await client.as_employee(emails["DEMO-009"], password)
        start, end = await find_window(client, types["AL"]["id"], 1)
        request = await submit(client, emails["DEMO-009"], password, types["AL"]["id"], start, end,
                               reason="Plans changed (demo)")
        await client.call("POST", f"/leave-requests/{request['id']}/cancel",
                          json={"comment": "No longer needed (demo)"})
        made["cancelled"] += 1

    if not await fresh("DEMO-008"):
        await client.as_employee(emails["DEMO-008"], password)
        start, end = await find_window(client, types["AL"]["id"], 2)
        await submit(client, emails["DEMO-008"], password, types["AL"]["id"], start, end,
                     reason="Training abroad (demo) - sample document attached",
                     attachment=sample_pdf("training approval"))
        made["with_attachment"] += 1
        made["pending"] += 1

    if not await fresh("DEMO-010"):
        await client.as_employee(emails["DEMO-010"], password)
        holiday_dates = sorted(
            row["date"] for row in await find(client, "/holidays", leave_year_id=year_id)
        )
        today = await today_in_org_timezone(client)
        upcoming = [d for d in holiday_dates if d > today.isoformat()]
        if upcoming:
            anchor = datetime.date.fromisoformat(upcoming[0]) - datetime.timedelta(days=1)
            start, end = await find_window(client, types["AL"]["id"], 1, earliest=anchor)
            request = await submit(client, emails["DEMO-010"], password, types["AL"]["id"], start, end,
                                   reason="Extended weekend around the holiday (demo)")
            await approve_all(client, request["id"], [(emails["DEMO-001"], password)])
            made["approved"] += 1
            made["holiday_aware"] += 1
    return made


async def ensure_adjustment(client: Session, admin_token: str, by_code: dict, types: dict, year_id: int) -> int:
    client.as_admin(admin_token)
    employee = by_code["DEMO-005"]
    balances = await find(client, "/leave-balances", employee_id=employee["id"],
                          leave_type_id=types["AL"]["id"], leave_year_id=year_id)
    if not balances:
        return 0
    history = await find(client, "/leave-balance-adjustments", employee_id=employee["id"],
                         leave_type_id=types["AL"]["id"], leave_year_id=year_id)
    if history:
        return 0
    await client.call(
        "POST", f"/leave-balances/{balances[0]['id']}/adjust",
        json={"field": "ALLOCATED", "delta": "2",
              "reason": "Extra two days granted for the audit season (demo example)"},
    )
    return 1


def write_credentials(credentials: dict[str, dict], password: str) -> None:
    lines = [
        "# DEMO ONLY - never use these accounts anywhere real.",
        "# Generated by: python -m app.cli.demo_data",
        "# A later run REUSES this password; delete the file to force a fresh one.",
        "",
        f"# shared demo password (every demo employee): {password}",
        "",
        "code,email,role,password",
    ]
    for code, data in sorted(credentials.items()):
        lines.append(f"{code},{data['email']},{'/'.join(data['roles'])},{password}")
    handle = os.open(CREDENTIALS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w") as file:
        file.write("\n".join(lines) + "\n")
    os.chmod(CREDENTIALS_FILE, 0o600)


async def reset_demo_passwords(client: Session, employees: dict[str, dict], password: str) -> int:
    for employee in employees.values():
        await client.call(
            "PATCH", f"/employees/{employee['id']}", json={"password": password}
        )
    return len(employees)


def drain_outbox() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "app.worker", "--once"],
        cwd=BACKEND_DIR, env=dict(os.environ),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("Note: the email worker exited with a problem; the demo data is unaffected.")
    return result.returncode


async def run(allow_remote: bool, allow_real: bool = False) -> int:
    from app.core.config import settings
    from app.main import app

    name = database_name(settings.database_url)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://demo.local") as raw:
        client = Session(raw, "demo")
        admin_token = await client.login(
            settings_demo_email(), settings_demo_password()
        )
        client.as_admin(admin_token)
        employees = await find(client, "/employees")
        guard_not_a_development_database(employees, allow_real=allow_real)

        existing_demo = {
            str(employee["employee_code"]): employee
            for employee in employees
            if str(employee.get("employee_code", "")).startswith(DEMO_PREFIX)
        }
        known_emails = demo_emails()
        file_state, recorded = read_credentials_file(known_emails)
        action = decide_credential_action(file_state, bool(existing_demo), can_reset=True)
        if action == STOP:
            raise DemoError(CREDENTIALS_HELP)

        if action == REUSE_PASSWORD:
            password = recorded
            print("Password   : reusing the one recorded in demo_credentials.txt.")
        elif action == RESET_PASSWORDS:
            password = make_password()
            changed = await reset_demo_passwords(client, existing_demo, password)
            print(f"Password   : demo_credentials.txt was {file_state}; set one fresh shared "
                  f"password for {changed} existing demo employee(s) through the admin reset API.")
        else:
            password = make_password()
        year = (await today_in_org_timezone(client)).year

        divisions = {}
        for division_name in DIVISIONS:
            divisions[division_name] = await ensure_division(client, division_name)
        departments = {}
        for division_name, department_names in DEPARTMENTS.items():
            for department_name in department_names:
                departments[department_name] = await ensure_department(
                    client, divisions[division_name]["id"], department_name
                )

        leave_year = await ensure_leave_year(client, year)
        active_years = [row for row in await find(client, "/leave-years") if row.get("is_active")]
        if not active_years:
            await client.call("POST", f"/leave-years/{leave_year['id']}/activate", expect=(200, 204))

        types = {
            "AL": await ensure_leave_type(client, code="AL", name="Annual Leave", default_quota="20",
                                         carry_forward_allowed=True, max_carry_forward_days="5"),
            "SL": await ensure_leave_type(client, code="SL", name="Sick Leave", default_quota="10"),
            "HL": await ensure_leave_type(client, code="HL", name="Half Day Leave", default_quota="5",
                                          allow_half_day=True),
        }
        weekend_created = await ensure_weekend(client)
        holidays = await ensure_holidays(client, leave_year["id"], year)
        by_code, approvers_unchanged = await ensure_employees(client, password, divisions, departments)
        assignments = await ensure_assignments(client, by_code, types, leave_year["id"])

        credentials = {
            code: {
                "email": f"{code.lower().replace('-', '.')}@{EMAIL_DOMAIN}",
                "roles": roles_for(code),
            }
            for code, _name, _designation, _division, _department, _joined, _extra in PEOPLE
        }
        made = await build_requests(client, password, by_code, types, credentials,
                                    leave_year["id"], admin_token)
        adjustments = await ensure_adjustment(client, admin_token, by_code, types, leave_year["id"])

        write_credentials(credentials, password)
        worker = drain_outbox()

        print(f"demo database name      : {name}")
        print(f"weekend setting created : {'yes' if weekend_created else 'already existed (left alone)'}")
        print(f"holidays created        : {holidays}")
        print(f"assignments created     : {assignments}")
        print(f"approver lists unchanged: {approvers_unchanged}")
        print(f"requests created        : {made}")
        print(f"balance adjustments     : {adjustments}")
        print(f"email worker            : {'drained' if worker == 0 else 'see the note above'}")
        print(f"credentials written to  : {CREDENTIALS_FILE.name} (mode 600, git-ignored)")
        return 0


_DEMO_LOGIN: dict[str, str] = {}


def settings_demo_email() -> str:
    return _DEMO_LOGIN["email"]


def settings_demo_password() -> str:
    return _DEMO_LOGIN["password"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fill a throw-away demo database.")
    parser.add_argument(FLAG, dest="acknowledged", action="store_true")
    parser.add_argument(REMOTE_FLAG, dest="allow_remote", action="store_true",
                        help="accept a database name that does not end with _demo_test")
    parser.add_argument(REAL_DB_FLAG, dest="allow_real", action="store_true",
                        help="accept a database that is ALREADY IN USE (its append-only "
                             "audit log will carry these demo rows for ever)")
    args = parser.parse_args(argv)

    try:
        # Defer config import so the default .env isn't loaded without confirmation.
        guard_environment(args.acknowledged)
    except DemoError as error:
        print(f"Refused: {error}")
        return 2

    try:
        from app.core.config import settings
    except RuntimeError as error:
        print(f"Refused: {error}")
        return 2

    try:
        guard_app_env(settings.app_env)
        guard_database_name(database_name(settings.database_url), args.allow_remote)
    except DemoError as error:
        print(f"Refused: {error}")
        return 2

    print("This will create DEMO-only rows in the database named "
          f"'{database_name(settings.database_url)}'.")
    print("The existing admin's own account is used to sign in; the password is never stored.")
    _DEMO_LOGIN["email"] = input("Existing admin e-mail: ").strip()
    _DEMO_LOGIN["password"] = getpass.getpass("Existing admin password: ")

    try:
        return asyncio.run(run(args.allow_remote, args.allow_real))
    except RateLimited as error:
        print(f"Stopped: {error} Nothing was retried, because repeated attempts lock the "
              "account. Wait for the Retry-After time (15 minutes for the login limits) and "
              "run the command again. If an account still looks locked, run: "
              "python -m app.cli.unlock_login --email <address>")
        return 1
    except LoginRefused as error:
        print(f"Stopped: {error}. Nothing was retried, because repeated failed sign-ins "
              f"lock the account. {CREDENTIALS_HELP} If the refused account is your own "
              "administrator, check the e-mail and password you typed.")
        return 1
    except DemoError as error:
        print(f"Stopped: {error}")
        return 1
    except httpx.HTTPError:
        print("Stopped: could not talk to the application (is the database reachable?).")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
