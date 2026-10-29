# Memory

## Project Overview

**Leave Management System** — a web application to manage employee leave end-to-end:
organisation setup, leave configuration, balance tracking, leave requests,
multi-approver workflows, and email notifications.

The full, authoritative requirements document is imported below.

## Requirements (full source)

@leave_management_system_requirements(1).md

## Project Docs

- Stack & reasons: @TECH_STACK.md
- Build plan (phases): @PLAN.md
- Decisions & open questions: @DECISIONS.md

## Tech Stack (confirmed)

- **Backend:** Python 3.12 + FastAPI + **SQLModel** (not raw SQLAlchemy) + Alembic + PostgreSQL 16.
- **Frontend:** React + Vite + TypeScript.
- **Layout:** a two-folder monorepo — `backend/` (Python, `venv`) and `frontend/` (`node_modules`).

## Confirmed Decisions (from "Open Questions")

These were answered directly in the requirements file and override the open questions:

- **Post-approval cancellation:** An employee can cancel only their own `Pending` requests. **SUPERSEDED by DECISIONS D-153:** an `Approved` request can never be cancelled — not even by an Admin. A wrong approval is repaired with a manual balance adjustment (Phase 16B).
- **Cross-year leave requests:** Allowed — a single request may span two leave years (do not block or split silently).
- **Negative balance / advance leave:** Blocked by default. Admin may manually update an employee's leave count to allow extra leave.
- **Employee balance visibility:** Yes — an employee can view their remaining leave balances.
- **Pro-rata allocation:** Still open — decide whether mid-year joiners get automatic pro-rated allocation or Admin enters allocated days manually.

## Standing Rules

- README/docs and this requirements file are the source of truth; if code and docs disagree, flag it.
- Follow `PLAN.md` phase by phase; do not start a phase whose dependencies are unfinished.
- Record new ambiguities and resolutions in `DECISIONS.md` using the `D-nn` id scheme.
