# IMPLEMENTATION REPORT — Leave Management System

**Audit basis (how this document was produced).** Every statement below was read out of the code, not
from memory or from a plan: the table list, columns, defaults, nullability, keys and constraints come
from `SQLModel.metadata` (the same metadata Alembic uses), the endpoint list from the FastAPI OpenAPI
schema, and the business rules from the source files named next to each claim. Where something is
missing, mocked or not wired up, it is marked **NOT IMPLEMENTED**, **PARTIAL** or **NOT VERIFIED**.

Numbers measured at the time of writing:

| Measure | Value |
| --- | --- |
| Database tables | **21** |
| Alembic migrations | **16** |
| HTTP endpoints | **78** |
| Backend test files | **20** unit files + 1 integration file (`test_golden_path.py`, marker-gated) |
| Backend tests | `pytest -q` → **490 passed, 1 deselected** |
| Frontend tests | `npm test` → **8 passed** (1 file) |
| Frontend lint / build | `npm run lint` → 0 warnings/errors · `npm run build` → ok |

---

## 1. Project Overview & Tech Stack

### 1.1 Backend

| Concern | What is actually used | Version |
| --- | --- | --- |
| Language / runtime | Python 3.12 in `backend/venv` | 3.12 |
| Web framework | FastAPI (auto-docs at `/docs` unless `ENABLE_DOCS=false`) | `fastapi==0.160.0` |
| ASGI server | Uvicorn | `uvicorn[standard]==0.54.0` |
| ORM | **SQLModel** (one class = table + Pydantic model), on top of SQLAlchemy | `sqlmodel==0.0.48`, `sqlalchemy[asyncio]==2.1.6` |
| Database | PostgreSQL (Supabase in the cloud, or local Docker) | 16 / 17 |
| DB driver | asyncpg | `asyncpg==0.32.0` |
| Migrations | Alembic (autogenerate from SQLModel metadata) | `alembic==1.20.1` |
| Settings | pydantic-settings, reading `.env` or `$LMS_ENV_FILE` | `pydantic-settings==2.16.1` |
| Email validation | email-validator (via `EmailStr`) | `email-validator==2.3.0` |
| Password hashing | **argon2-cffi** directly (passlib deliberately avoided) | `argon2-cffi==25.1.0` |
| Tokens | PyJWT (HS256) + opaque refresh tokens stored as SHA-256 hashes | `PyJWT==2.15.1` |
| Uploads | python-multipart | `python-multipart==0.0.32` |
| Email rendering | Jinja2 (`app/templates/email/*.txt|*.html`) | `jinja2==3.1.6` |

**Background work — no queue library.** There is **no Celery, Redis, RQ or APScheduler**. Emails and
reminders are a **database-backed outbox** (`email_outbox`) plus a worker process you start yourself
(`python -m app.worker`, with `--once` for one pass). The worker loop sleeps `IDLE_SECONDS` between
passes and runs the reminder tick every `REMINDER_EVERY_SECONDS = 15 * 60` (`app/worker.py:60`), and a
daily retention/cleanup tick behind a PostgreSQL advisory lock.

**Not in `requirements.txt` but present in the venv**: `boto3` and `moto` were installed while testing
the planned S3 storage rules. No S3 code exists in the app (see §6).

### 1.2 Frontend

| Concern | What is actually used | Version |
| --- | --- | --- |
| UI library | React, **plain JavaScript + JSX (no TypeScript, no `tsconfig`)** | `react@19.3.1` |
| Build tool | Vite | (`vite.config.js`) |
| Routing | React Router | `react-router-dom@7.18.4` |
| State management | **None beyond React itself** — `useState`/`useEffect` plus one `AuthContext`. No Redux, no TanStack Query, no SWR | — |
| UI components | Bootstrap 5 + React-Bootstrap | `bootstrap@5.3.8`, `react-bootstrap@2.10.10` |
| HTTP client | Axios (single instance in `src/api/client.js`) | `axios@1.20.0` |
| Lint | oxlint (2 rules deliberately disabled: `only-export-components`, `set-state-in-effect`) | `frontend/.oxlintrc.json` |
| Tests | Vitest, dev-only, one file (`src/api/refreshCoordinator.test.js`) | 8 tests |
| "Live" updates | A change signal (`notifyDataChanged`) + `BroadcastChannel` + focus refresh + a 15 s poll (`useAutoRefresh`). **Not** SSE/WebSockets | — |

### 1.3 Folder structure (every existing source file)

```
Leave Management System/
├── AGENTS.md  DECISIONS.md  DEMO_GUIDE.md  PLAN.md  README.md  TECH_STACK.md  TODO_BACKLOG.md
├── IMPLEMENTATION_REPORT.md            ← this file
├── docker-compose.yml                  (PostgreSQL; Mailpit under the optional `mail` profile)
├── .gitignore  .env.example
├── docs/postman/  lms.postman_collection.json, lms.postman_environment.json, README.md
├── .github/
│   ├── dependabot.yml
│   └── workflows/ci.yml
├── backend/
│   ├── alembic.ini  pytest.ini  requirements.txt  requirements-dev.txt
│   ├── .env  .env.example
│   ├── alembic/
│   │   ├── env.py  script.py.mako  README
│   │   └── versions/  (16 migrations)
│   │       69d0b70a50c9_empty_baseline, 9ee0f38d8146_create_division_and_department,
│   │       8630a284ed68_create_employee_and_employee_role, 83a61549e9e3_add_employee_password_hash,
│   │       8e050ee9b800_create_leave_year_and_leave_type, c4e60f6f17d8_create_employee_leave_type_and_leave_,
│   │       5ec98b92db3d_create_weekend_setting_and_holiday, 8b7c1970e916_create_employee_approver,
│   │       ead5bf61ec76_create_leave_request_tables, 92beb3d954d2_add_leave_request_cancellation,
│   │       263a99a2d884_create_email_outbox, 7e3d308d483e_leave_balance_adjustment_ledger,
│   │       befce6c4a656_leave_carry_forward_and_year_closing, 116e7a2af170_audit_log,
│   │       3cce06fc823b_refresh_tokens_and_login_attempts, fb11f62036f4_employee_must_change_password
│   ├── app/
│   │   ├── main.py         worker.py
│   │   ├── core/           config.py  deps.py  security.py  audit_registry.py
│   │   ├── db/             session.py
│   │   ├── models/         base.py  employee.py  division.py  department.py  employee_approver.py
│   │   │                   leave_year.py  leave_type.py  leave_balance.py  leave_request.py
│   │   │                   weekend_setting.py  holiday.py  calendar.py  email_outbox.py
│   │   │                   balance_adjustment.py  leave_carry_forward.py  audit_log.py  auth_tokens.py
│   │   ├── routers/        auth.py  divisions.py  departments.py  employees.py  approvers.py
│   │   │                   leave_years.py  leave_types.py  leave_assignments.py  leave_balances.py
│   │   │                   balance_adjustments.py  weekends.py  holidays.py  calendar.py
│   │   │                   leave_requests.py  approvals.py  year_closing.py  reports.py
│   │   │                   admin_audit_log.py  admin_emails.py  admin_security.py
│   │   ├── services/       day_calc.py  request_rules.py  cancel_rules.py  approval_rules.py
│   │   │                   adjustment_rules.py  closing_rules.py  email_rules.py  report_rules.py
│   │   │                   audit_rules.py  security_rules.py  session_rules.py  password_rules.py
│   │   │                   storage_rules.py  csp_rules.py  maintenance_rules.py
│   │   │                   leave_requests.py  approvals.py  cancellations.py  adjustments.py
│   │   │                   closing.py  locking.py  balances.py  approvers.py  calendar.py
│   │   │                   notifications.py  email_templates.py  mailer.py  reports.py
│   │   │                   audit.py  auth_service.py  sessions.py  maintenance.py  storage.py
│   │   ├── cli/            seed_admin.py  demo_data.py  cleanup.py  unlock_login.py
│   │   └── templates/email/  14 files (7 events × .txt/.html): submitted, approver_acted, approved,
│   │                         rejected, cancelled, cancelled_employee, reminder
│   └── tests/              20 unit test files + integration/{conftest.py, test_golden_path.py}
└── frontend/
    ├── index.html  package.json  vite.config.js  .oxlintrc.json  .env  .env.example  .gitignore
    ├── public/favicon.svg
    └── src/
        ├── main.jsx  App.jsx  index.css
        ├── api/       client.js  liveUpdates.js  refreshCoordinator.js  refreshCoordinator.test.js
        ├── auth/      AuthContext.jsx  ProtectedRoute.jsx
        ├── hooks/     useAutoRefresh.js
        ├── components/ Layout.jsx  Icon.jsx  DateField.jsx  MonthCalendar.jsx  DayPreview.jsx
        │               DecisionModal.jsx  AdjustBalanceModal.jsx  AdjustmentHistoryModal.jsx
        │               RequestStatusBadge.jsx  StatusBadge.jsx  NoOptions.jsx
        └── pages/     21 pages (listed in §5)
```

`backend/media/` (uploaded attachments) and `backend/outbox_dev/` (file-backend emails) are created at
runtime and are git-ignored; `backend/.pytest_cache/` is a tool artifact.

---

## 2. Database Models & Schema Audit

21 tables. "Audit columns" below means literally `created_at`, `updated_at`, `created_by` **as present
in the model**; the shared base class (`models/base.py`) supplies them, and the exceptions are the
interesting part.

| Table | Audit columns present |
| --- | --- |
| `audit_log` | `created_at` **only** (deliberately immutable) |
| `leave_balance_adjustment` | `created_at`, `created_by` (no `updated_at` — append-only) |
| `employee_role` | **none at all** (composite-PK join table) |
| all 18 others | `created_at`, `updated_at`, `created_by` |

Primary keys are `BIGINT` on every table except `employee_role` (composite) — see D-24.

### 2.1 `division`
| Column | Type | Null | Default | Key |
| --- | --- | --- | --- | --- |
| `id` | BIGINT | no | — | **PK** |
| `name` | VARCHAR(150) | no | — | **UNIQUE** (column-level, case-sensitive) |
| `is_active` | BOOLEAN | no | `true` | |
| `created_at` | DATETIME | no | — | |
| `updated_at` | DATETIME | no | — | |
| `created_by` | BIGINT | yes | — | |

No table-level constraints. **No DELETE endpoint exists** (see §4.1).

### 2.2 `department`
| Column | Type | Null | Default | Key |
| --- | --- | --- | --- | --- |
| `id` | BIGINT | no | — | **PK** |
| `division_id` | BIGINT | no | — | **FK** → `division.id` |
| `name` | VARCHAR(150) | no | — | |
| `is_active` | BOOLEAN | no | `true` | |
| `created_at` / `updated_at` | DATETIME | no | — | |
| `created_by` | BIGINT | yes | — | |

Constraints: `UNIQUE uq_department_division_name` on `(division_id, name)` — **exact column names not
printed by SQLAlchemy's metadata alone; the constraint name is verified from the model.**

### 2.3 `employee`
| Column | Type | Null | Default | Key |
| --- | --- | --- | --- | --- |
| `id` | BIGINT | no | — | **PK** |
| `employee_code` | VARCHAR(50) | no | — | **UNIQUE** |
| `full_name` | VARCHAR(150) | no | — | |
| `email` | VARCHAR(255) | no | — | **UNIQUE** (stored lower-cased by the API) |
| `password_hash` | VARCHAR(255) | no | — | (argon2; `repr=False`) |
| `phone` | VARCHAR(30) | yes | — | |
| `designation` | VARCHAR(100) | yes | — | |
| `division_id` | BIGINT | no | — | **FK** → `division.id` |
| `department_id` | BIGINT | no | — | **FK** → `department.id` |
| `supervisor_id` | BIGINT | yes | — | **FK** → `employee.id` (self-referencing) |
| `joining_date` | DATE | no | — | |
| `is_active` | BOOLEAN | no | `true` | |
| `must_change_password` | BOOLEAN | no | `false` | added by migration `fb11f62036f4` |
| `created_at` / `updated_at` | DATETIME | no | — | |
| `created_by` | BIGINT | yes | — | |

### 2.4 `employee_role`
| Column | Type | Null | Key |
| --- | --- | --- | --- |
| `employee_id` | BIGINT | no | **PK (composite)**, **FK** → `employee.id` |
| `role` | VARCHAR(20) | no | **PK (composite)** |

Constraints: `pk_employee_role` on `(employee_id, role)`; `CHECK ck_employee_role_role`
(`role IN ('ADMIN','EMPLOYEE','APPROVER')`). Stored as `VARCHAR` + CHECK rather than a PostgreSQL ENUM
(D-42). **No audit columns.**

### 2.5 `employee_approver`
| Column | Type | Null | Default | Key |
| --- | --- | --- | --- | --- |
| `id` | BIGINT | no | — | **PK** |
| `employee_id` | BIGINT | no | — | **FK** → `employee.id` |
| `approver_id` | BIGINT | no | — | **FK** → `employee.id` |
| `is_active` | BOOLEAN | no | `true` | |
| `created_at` / `updated_at` | DATETIME | no | — | |
| `created_by` | BIGINT | yes | — | |

Constraints: `UNIQUE uq_employee_approver` on `(employee_id, approver_id)`;
`CHECK ck_employee_approver_not_self` (`employee_id <> approver_id`). Rows are **soft-deactivated**
(`is_active=false`), never deleted (D-79).

### 2.6 `weekend_setting`
| Column | Type | Null | Default | Key |
| --- | --- | --- | --- | --- |
| `id` | BIGINT | no | — | **PK** |
| `employee_id` | BIGINT | yes | — | **FK** → `employee.id`; `NULL` = the global default |
| `days_of_week` | ARRAY (PostgreSQL integer[]) | no | — | |
| `created_at` / `updated_at` | DATETIME | no | — | |
| `created_by` | BIGINT | yes | — | |

Constraints: `CHECK ck_weekend_setting_not_empty` (`cardinality(days_of_week) >= 1`);
`CHECK ck_weekend_setting_range` (`days_of_week <@ ARRAY[0..6]`);
`INDEX uq_weekend_setting_employee` **unique** on `(employee_id)`;
`INDEX uq_weekend_setting_single_global` **unique**, defined in the migration as a **partial index**
(`WHERE employee_id IS NULL`) — SQLAlchemy prints it with no plain columns because it is partial (D-08).
The D-08/D-29 limitation stands: **one weekend per employee, no history** (`effective_from` is not
implemented).

### 2.7 `holiday`
| Column | Type | Null | Default | Key |
| --- | --- | --- | --- | --- |
| `id` | BIGINT | no | — | **PK** |
| `leave_year_id` | BIGINT | no | — | **FK** → `leave_year.id` |
| `date` | DATE | no | — | |
| `title` | VARCHAR(150) | no | — | |
| `type` | VARCHAR(20) | no | — | |
| `division_id` | BIGINT | yes | — | **FK** → `division.id` (`NULL` = all) |
| `department_id` | BIGINT | yes | — | **FK** → `department.id` (`NULL` = all) |
| `created_at` / `updated_at` | DATETIME | no | — | |
| `created_by` | BIGINT | yes | — | |

Constraints: `CHECK ck_holiday_type` (`PUBLIC|COMPANY|OPTIONAL`);
`INDEX uq_holiday_date_scope` **unique** — created in the migration as an expression index over the
scope columns, so metadata shows no plain column list. One row per date: a date range is expanded on
import (D-07).

### 2.8 `leave_year`
| Column | Type | Null | Default | Key |
| --- | --- | --- | --- | --- |
| `id` | BIGINT | no | — | **PK** |
| `name` | VARCHAR(20) | no | — | **UNIQUE** |
| `start_date` / `end_date` | DATE | no | — | |
| `is_active` | BOOLEAN | no | `false` | |
| `is_closed` | BOOLEAN | no | `false` | |
| `closed_at` | DATETIME | yes | — | |
| `closed_by_id` | BIGINT | yes | — | **FK** → `employee.id` |
| `created_at` / `updated_at` | DATETIME | no | — | |
| `created_by` | BIGINT | yes | — | |

Constraints: `CHECK ck_leave_year_date_order`; `CHECK ck_leave_year_closed_has_date`;
`CHECK ck_leave_year_closed_together` (`(closed_at IS NULL) = (closed_by_id IS NULL)`);
`INDEX uq_leave_year_single_active` **unique** on `is_active` — a partial unique index
(`WHERE is_active`), the database-level guarantee of "exactly one active year" (D-14/D-52).

### 2.9 `leave_type`
| Column | Type | Null | Default | Key |
| --- | --- | --- | --- | --- |
| `id` | BIGINT | no | — | **PK** |
| `code` | VARCHAR(20) | no | — | **UNIQUE** |
| `name` | VARCHAR(100) | no | — | **UNIQUE** |
| `default_quota` | NUMERIC(5,2) | no | — | |
| `accrual_mode` | VARCHAR(20) | no | `'fixed'` | |
| `allow_half_day` | BOOLEAN | no | `true` | |
| `require_attachment_after_days` | INTEGER | yes | — | |
| `carry_forward_allowed` | BOOLEAN | no | `false` | |
| `max_carry_forward_days` | NUMERIC(5,2) | no | `0` | |
| `is_active` | BOOLEAN | no | `true` | |
| `created_at` / `updated_at` | DATETIME | no | — | |
| `created_by` | BIGINT | yes | — | |

Constraints: `CHECK ck_leave_type_default_quota (>= 0)`;
`CHECK ck_leave_type_max_carry_forward (>= 0)`;
`CHECK ck_leave_type_accrual_mode (IN ('fixed','monthly'))` — the DB allows `monthly`, **the API
rejects it with 400** (D-57);
`CHECK ck_leave_type_attachment_days (IS NULL OR > 0)`.

### 2.10 `employee_leave_type` (eligibility + allocation per year)
| Column | Type | Null | Default | Key |
| --- | --- | --- | --- | --- |
| `id` | BIGINT | no | — | **PK** |
| `employee_id` | BIGINT | no | — | **FK** → `employee.id` |
| `leave_type_id` | BIGINT | no | — | **FK** → `leave_type.id` |
| `leave_year_id` | BIGINT | no | — | **FK** → `leave_year.id` |
| `allocated_days` | NUMERIC(5,2) | no | `0` | |
| `created_at` / `updated_at` / `created_by` | — | — | — | |

Constraints: `UNIQUE uq_employee_leave_type` on `(employee_id, leave_type_id, leave_year_id)`;
`CHECK ck_employee_leave_type_days (allocated_days >= 0)`.

### 2.11 `leave_balance`
| Column | Type | Null | Default | Key |
| --- | --- | --- | --- | --- |
| `id` | BIGINT | no | — | **PK** |
| `employee_id` | BIGINT | no | — | **FK** → `employee.id` |
| `leave_type_id` | BIGINT | no | — | **FK** → `leave_type.id` |
| `leave_year_id` | BIGINT | no | — | **FK** → `leave_year.id` |
| `allocated` | NUMERIC(5,2) | no | `0` | |
| `carried_forward` | NUMERIC(5,2) | no | `0` | (the requirements' `carried_in` — D-02) |
| `used` | NUMERIC(5,2) | no | `0` | |
| `pending` | NUMERIC(5,2) | no | `0` | |
| `created_at` / `updated_at` / `created_by` | — | — | — | |

Constraints: `UNIQUE uq_leave_balance` on `(employee_id, leave_type_id, leave_year_id)`;
`CHECK ck_leave_balance_allocated (>= 0)`, `ck_leave_balance_carried (>= 0)`,
`ck_leave_balance_used (>= 0)`, `ck_leave_balance_pending (>= 0)`, and
**`ck_leave_balance_available_not_negative`** (`allocated + carried_forward - used - pending >= 0`).
**`available` is never stored** — it is computed (D-65), and this CHECK is the database-level guarantee
that a race can never overdraw a balance.

### 2.12 `leave_request`
| Column | Type | Null | Default | Key |
| --- | --- | --- | --- | --- |
| `id` | BIGINT | no | — | **PK** |
| `employee_id` | BIGINT | no | — | **FK** → `employee.id` |
| `leave_type_id` | BIGINT | no | — | **FK** → `leave_type.id` |
| `leave_year_id` | BIGINT | no | — | **FK** → `leave_year.id` (year of `start_date`) |
| `start_date` / `end_date` | DATE | no | — | |
| `day_type` | VARCHAR(20) | no | `'FULL_DAY'` | |
| `chargeable_days` | NUMERIC(5,2) | no | — | |
| `reason` | TEXT | no | — | |
| `attachment_url` | VARCHAR(255) | yes | — | (storage key/path) |
| `status` | VARCHAR(20) | no | `'PENDING'` | |
| `submitted_at` | DATETIME | no | — | |
| `final_decided_at` | DATETIME | yes | — | |
| `cancelled_at` | DATETIME | yes | — | |
| `cancelled_by_id` | BIGINT | yes | — | **FK** → `employee.id` |
| `cancel_reason` | TEXT | yes | — | |
| `created_at` / `updated_at` / `created_by` | — | — | — | |

Constraints: `CHECK ck_leave_request_dates (start_date <= end_date)`;
`CHECK ck_leave_request_day_type (IN ('FULL_DAY','FIRST_HALF','SECOND_HALF'))`;
`CHECK ck_leave_request_days (chargeable_days > 0)`;
`CHECK ck_leave_request_half_day_single (day_type = 'FULL_DAY' OR start_date = end_date)`;
`CHECK ck_leave_request_status (IN ('PENDING','APPROVED','REJECTED','CANCELLED'))`;
`CHECK ck_leave_request_cancelled_pair` (cancelled_at and cancelled_by_id are both set or both null);
indexes `ix_leave_request_employee_dates`, `ix_leave_request_employee_status`.

### 2.13 `leave_request_allocation` (the cross-year split, D-05)
| Column | Type | Null | Key |
| --- | --- | --- | --- |
| `id` | BIGINT | no | **PK** |
| `leave_request_id` | BIGINT | no | **FK** → `leave_request.id` |
| `leave_year_id` | BIGINT | no | **FK** → `leave_year.id` |
| `days` | NUMERIC(5,2) | no | |
| `created_at` / `updated_at` / `created_by` | — | — | |

Constraints: `UNIQUE uq_leave_request_allocation` on `(leave_request_id, leave_year_id)`;
`CHECK ck_leave_request_allocation_days (days > 0)`.

### 2.14 `leave_request_approval`
| Column | Type | Null | Default | Key |
| --- | --- | --- | --- | --- |
| `id` | BIGINT | no | — | **PK** |
| `leave_request_id` | BIGINT | no | — | **FK** → `leave_request.id` |
| `approver_id` | BIGINT | no | — | **FK** → `employee.id` |
| `status` | VARCHAR(20) | no | `'PENDING'` | |
| `comment` | TEXT | yes | — | |
| `acted_at` | DATETIME | yes | — | |
| `created_at` / `updated_at` / `created_by` | — | — | — | |

Constraints: `UNIQUE uq_leave_request_approval` on `(leave_request_id, approver_id)`;
`CHECK ck_leave_request_approval_status (IN ('PENDING','APPROVED','REJECTED','SKIPPED'))`;
index `ix_leave_request_approval_approver_status`.

### 2.15 `leave_carry_forward` (year-end log)
| Column | Type | Null | Default | Key |
| --- | --- | --- | --- | --- |
| `id` | BIGINT | no | — | **PK** |
| `employee_id` / `leave_type_id` | BIGINT | no | — | **FK** → `employee.id` / `leave_type.id` |
| `from_leave_year_id` / `to_leave_year_id` | BIGINT | no | — | **FK** → `leave_year.id` |
| `remaining_at_close` | NUMERIC(5,2) | no | `0` | |
| `carried_days` | NUMERIC(5,2) | no | `0` | |
| `forfeited_days` | NUMERIC(5,2) | no | `0` | |
| `processed_at` | DATETIME | no | — | |
| `processed_by` | BIGINT | yes | — | **FK** → `employee.id` |
| `created_at` / `updated_at` / `created_by` | — | — | — | |

Constraints: `UNIQUE uq_leave_carry_forward` on `(employee_id, leave_type_id, from_leave_year_id)`;
`CHECK ck_leave_carry_forward_split (remaining_at_close = carried_days + forfeited_days)`;
`CHECK ck_leave_carry_forward_different_years`; `CHECK ..._carried (>= 0)`, `..._forfeited (>= 0)`.

### 2.16 `leave_balance_adjustment` (append-only ledger)
| Column | Type | Null | Default | Key |
| --- | --- | --- | --- | --- |
| `id` | BIGINT | no | — | **PK** |
| `balance_id` | BIGINT | no | — | **FK** → `leave_balance.id` |
| `employee_id` / `leave_type_id` / `leave_year_id` | BIGINT | no | — | **FK**s |
| `field` | VARCHAR(20) | no | — | |
| `delta` | NUMERIC(5,2) | no | — | |
| `value_before` / `value_after` | NUMERIC(5,2) | no | — | |
| `reason` | TEXT | no | — | |
| `year_was_closed` | BOOLEAN | no | `false` | |
| `created_by` | BIGINT | no | — | **FK** → `employee.id` |
| `created_at` | DATETIME | no | — | (no `updated_at`: append-only) |

Constraints: `ck_adjustment_field (field IN ('ALLOCATED','CARRIED_FORWARD','USED'))` — **PENDING can
never be adjusted** (D-157); `ck_adjustment_delta_nonzero`; `ck_adjustment_after_non_negative`;
`ck_adjustment_chain (value_after - value_before = delta)`;
`ck_adjustment_reason_length (5..500)`.

### 2.17 `email_outbox` / 2.18 `email_attempt`
`email_outbox`: `id` **PK**; `event_type` VARCHAR(40) no; `to_emails` ARRAY no; `cc_emails` ARRAY no
default `'{}'`; `payload` JSONB no default `'{}'`; `related_request_id` BIGINT yes **FK** →
`leave_request.id`; `status` VARCHAR(20) default `'PENDING'`; `attempts` INT default 0; `max_attempts`
INT default 5; `next_attempt_at` DATETIME no; `claimed_at` DATETIME yes; `sent_at` DATETIME yes;
`last_error` VARCHAR(500) yes; `dedupe_key` VARCHAR(200) yes **UNIQUE**; + audit columns.
Constraints: `ck_email_outbox_status (PENDING|SENDING|SENT|FAILED)`, `ck_email_outbox_attempts (>= 0)`;
indexes `ix_email_outbox_due (status, next_attempt_at)`, `ix_email_outbox_request (related_request_id)`.

`email_attempt`: `id` **PK**; `outbox_id` **FK** → `email_outbox.id`; `attempted_at` DATETIME no;
`success` BOOLEAN no; `error` VARCHAR(500) yes; `backend` VARCHAR(30) no; + audit columns. No extra
constraints.

### 2.19 `audit_log` (append-only; **does not** inherit the shared base — D-143)
`id` **PK**; `actor_id` BIGINT yes **FK** → `employee.id`; `entity_type` VARCHAR(40) no; `entity_id`
BIGINT **yes (nullable — D-145)**; `action` VARCHAR(40) no; `old_value` JSONB yes; `new_value` JSONB
yes; `reason` VARCHAR(1000) yes; `created_at` DATETIME no. Indexes: `ix_audit_log_actor`,
`ix_audit_log_entity (entity_type, entity_id)`, `ix_audit_log_created`.
**A PostgreSQL trigger refuses UPDATE/DELETE/TRUNCATE** (added in migration `116e7a2af170`) — that is
the real guarantee; the API has no write endpoints for it at all.

### 2.20 `refresh_token` / 2.21 `login_attempt`
`refresh_token`: `id` **PK**; `employee_id` **FK**; `family_id` UUID no; `token_hash` VARCHAR(64) no
**UNIQUE**; `issued_at`, `expires_at`, `family_started_at` DATETIME no; `last_used_at`, `revoked_at`,
`replaced_at` DATETIME yes; `replaced_by_id` BIGINT yes **FK** → `refresh_token.id`; `user_agent`
VARCHAR(200) yes; + audit columns. Indexes `ix_refresh_token_employee_active`,
`ix_refresh_token_family`. **No token column, no IP column** (D-163).

`login_attempt`: `id` **PK**; `email_normalized` VARCHAR(254) no; `ip_hash` VARCHAR(64) no (**keyed
HMAC, never the raw address** — D-164); `success` BOOLEAN no default `false`; + audit columns. Three
indexes for the rate-limit queries.

> **Two PostgreSQL-side objects are not visible in SQLModel metadata and live only in migrations:**
> the **append-only trigger on `audit_log`** (`116e7a2af170`) and the **append-only trigger on
> `leave_balance_adjustment`** (`7e3d308d483e`), plus the **RLS enablement** applied in several
> migrations for Supabase. They are real database objects; the ORM simply does not model them.

---

## 3. Authentication, Roles & Permissions (RBAC)

### 3.1 How authentication works (all of it real, nothing mocked)
- **Login**: `POST /auth/login` (OAuth2 password form). `services/auth_service.login()` checks the
  rate limits first, verifies the argon2 hash, and — for an unknown e-mail or an inactive account —
  still runs an argon2 verification **against a pre-computed dummy hash** so the response time cannot
  reveal which case applied (D-165). Every attempt writes a `login_attempt` row.
- **Access token**: JWT, HS256, signed with `JWT_SECRET`. Payload is **only** `sub` (employee id),
  `type: "access"` and `exp` (D-44) — roles are *not* in the token, so a role change or a deactivation
  takes effect on the very next request.
- **Refresh token**: an **opaque random string**, stored **only as a SHA-256 hash**, delivered as an
  **httpOnly cookie** (`refresh_token`, `Path=/auth`, `SameSite` from settings, `Secure` from
  `COOKIE_SECURE`). Rotation happens on `POST /auth/refresh`, grouped into **families**; reuse of a
  rotated token within a 10 s grace window answers **409 `REFRESH_RACE`** (the benign two-tabs race),
  later reuse is treated as theft and revokes the whole family with a `REFRESH_REUSE_DETECTED` audit
  row (D-163).
- **Frontend token storage**: the access token lives **only in a module variable** in
  `src/api/client.js`; the old `localStorage` key is deleted at start-up; a reload restores the session
  through `restoreSession()` → `POST /auth/refresh` (single-flight, Web-Locks-serialised across tabs,
  D-169/D-170).
- **Sign-out**: `POST /auth/logout` revokes the cookie's family (always 204); `POST /auth/logout-all`
  revokes every family of the employee and writes `SESSIONS_REVOKED`; `DELETE /auth/sessions/{id}`
  revokes one device and writes `SESSION_REVOKED`. A `BroadcastChannel("lms-auth")` message signs the
  other tabs out locally (D-172).
- **Production hardening** (present, not a mock): a middleware adds `nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer` and `Cache-Control: no-store` for `/auth/*` and `/admin/*`;
  `validate_production_settings()` refuses to start the app with unsafe production settings; docs can
  be switched off with `ENABLE_DOCS=false`.

### 3.2 How the three roles are identified and enforced

Roles exist as a **join table** (`employee_role`) with the values `ADMIN`, `EMPLOYEE`, `APPROVER`
(D-13/D-42). Two behavioural rules are implemented in the API, **not** in the database:

- **`EMPLOYEE` is always held** — `models/employee.py::with_employee_role()` adds it on create and on
  every role update; an empty role list means "a plain employee" (D-152).
- **Only role-holders can be approvers** — `PUT /employees/{id}/approvers` rejects any candidate who
  does not already hold `APPROVER`, with a 400 naming the employee codes (D-151).

**Backend enforcement** is centralised in `core/deps.py`:

| Dependency | What it does |
| --- | --- |
| `get_current_user` | Decodes the Bearer token, checks `type == "access"`, loads the employee **from the database**, rejects a missing or inactive account (401), and — since D-190 — **blocks every route except `/auth/me`, `/auth/change-password`, `/auth/logout`, `/auth/logout-all`, `/auth/refresh` with 403 + `X-Password-Change-Required: true` while `must_change_password` is set** |
| `load_roles(session, employee_id)` | Reads the employee's roles from `employee_role` on every request |
| `require_roles(*roles)` | Builds a dependency that answers **403** when the caller holds none of the listed roles |

Where each guard is applied (verified from the routers):

| Area | Guard |
| --- | --- |
| `/divisions`, `/departments` | `GET` = any logged-in user; write = `ADMIN` only (D-46) |
| `/employees`, `/leave-years`, `/leave-types`, `/holidays`, `/weekends` writes | `ADMIN` only |
| `/leave-assignments`, `/reports`, `/admin/*`, `/leave-balances/{id}/adjust`, year closing | `ADMIN` only |
| `/approvals/inbox`, `/leave-requests/{id}/approve|reject` | must have an approval row on that request; a stranger gets **404**, the requester gets **403** (D-89/D-97) |
| `/leave-requests`, `/leave-balances/me`, `/approvers/me`, `/auth/sessions` | any logged-in user, **hard-filtered to the caller** |
| `GET /leave-requests` (admin list), `GET /leave-balances` (all) | `ADMIN` only |

**Frontend enforcement** is `auth/ProtectedRoute.jsx`: `<ProtectedRoute />` requires any logged-in user,
`<ProtectedRoute roles={['APPROVER']} />` and `roles={['ADMIN']}` gate whole route groups
(`App.jsx:33-63`), and `components/Layout.jsx` **filters the sidebar items** by the roles returned in
`/auth/me` — so an employee simply never sees an admin link. This is convenience only; the API is the
real gate.

---

## 4. Backend API Endpoints & Business Logic Audit

**All 78 routes**, grouped exactly as they are implemented. `body`/`out` are the schemas the app
publishes in `/openapi.json`; query/path parameters are listed as reported by FastAPI.

### 4.1 Organisation & Departments

| Method | Path | Request | Response | Params |
| --- | --- | --- | --- | --- |
| GET | `/divisions` | — | `DivisionPage` (`{items, total}`) | — |
| POST | `/divisions` | `DivisionCreate` (`name*`, `is_active`) | `DivisionRead` | — |
| GET | `/divisions/{division_id}` | — | `DivisionRead` | `division_id` |
| PATCH | `/divisions/{division_id}` | `DivisionUpdate` (`name`, `is_active`) | `DivisionRead` | `division_id` |
| GET | `/departments` | — | `[DepartmentRead]` | `division_id` |
| POST | `/departments` | `DepartmentCreate` (`division_id*`, `name*`, `is_active`) | `DepartmentRead` | — |
| GET | `/departments/{department_id}` | — | `DepartmentRead` | `department_id` |
| PATCH | `/departments/{department_id}` | `DepartmentUpdate` (`name`, **`is_active`**) — `division_id` is **not** accepted | `DepartmentRead` | `department_id` |

Business logic actually written:

- **Uniqueness.** `division.name` is a column-level `UNIQUE`; a duplicate answers **409** (comparison is
  **case-sensitive**, D-37). A department is unique per division through
  `UNIQUE uq_department_division_name (division_id, name)`; a duplicate answers **409**.
- **Deactivation vs deletion.** **There is no DELETE endpoint for divisions or departments** — the
  route list contains only GET/POST/PATCH. "Removing" one therefore means `PATCH {"is_active": false}`.
  Deactivation is **blocked while active employees exist**: `routers/divisions.py:107-110`
  ("Cannot deactivate division {id}: it still has {n} active employee(s).") and
  `routers/departments.py:135-138` for departments — both **409**.
- Deactivating a division does **not** cascade to its departments (D-35).
- `division_id` is immutable through the API: it is absent from `DepartmentUpdate`, so a department
  cannot be moved (D-36).

### 4.2 Employees & Approvers

| Method | Path | Request | Response | Params |
| --- | --- | --- | --- | --- |
| GET | `/employees` | — | `[EmployeeRead]` | `division_id`, `department_id`, `is_active` |
| POST | `/employees` | `EmployeeCreate` (`employee_code*`, `full_name*`, `email*`, `password*`, `phone`, `designation`, `division_id*`, `department_id*`, `supervisor_id`, `joining_date*`, `is_active`, `roles`, `must_change_password` default **true**) | `EmployeeRead` | — |
| GET | `/employees/{employee_id}` | — | `EmployeeRead` | `employee_id` |
| PATCH | `/employees/{employee_id}` | `EmployeeUpdate` (all fields optional incl. `password`, `roles`, `must_change_password`) | `EmployeeRead` | `employee_id` |
| PUT | `/employees/{employee_id}/approvers` | `{approver_ids: [int]}` (the **complete** list) | `[EmployeeRead]` | `employee_id` |
| GET | `/approver-assignments` | — | `[{employee, approvers}]` | `division_id`, `department_id`, `only_missing` |
| GET | `/approvers/me` | — | the caller's own approvers | — |

- **Create**: duplicate `employee_code` or `email` → **409**; the password goes through
  `check_password_policy()` → **400** with every problem; `with_employee_role()` guarantees `EMPLOYEE`
  (D-152); `supervisor_id` is validated; `must_change_password` defaults to **true** (D-190).
- **Supervisor rules** (`routers/employees.py::_validate_supervisor`, line 116): a missing supervisor →
  400; **self-supervision → 400** ("An employee cannot be their own supervisor."); an **inactive**
  supervisor → 400; and `_creates_cycle()` (line 97) walks **up** the supervisor chain and refuses a
  link that would close a loop (the A → B → A case the requirements ask for) → **400**.
- **Approvers**: `PUT /employees/{id}/approvers` replaces the whole active set (idempotent, D-77). Each
  candidate **must already hold the `APPROVER` role** — otherwise **400** naming the codes (D-151).
  Self-approval is impossible in two places: the API and `CHECK ck_employee_approver_not_self`.
  Rows are soft-deactivated (`is_active=false`), never deleted (D-79). `ensure_supervisor_is_approver()`
  adds the supervisor as an approver **only when the supervisor actually changes** and only if they
  already hold the role (FR-APR-2 + D-80/D-151).
- **Deactivation guards** (they import `pending_request_count` / `pending_approval_count` from
  `services/approvals.py`): an employee who is an **active approver for active employees** (D-81), who
  **still owes an approval** or who **has pending requests** (D-94) cannot be deactivated → **409** with
  a message saying how many are affected. Deactivation revokes their sessions in the same transaction.

### 4.3 Leave Years, Leave Types & Balances

| Method | Path | Request | Response | Params |
| --- | --- | --- | --- | --- |
| GET | `/leave-years` | — | `LeaveYearPage` | — |
| POST | `/leave-years` | `LeaveYearCreate` (`name*`, `start_date*`, `end_date*`) | `LeaveYearRead` | — |
| GET | `/leave-years/{year_id}` | — | `LeaveYearRead` | `year_id` |
| PATCH | `/leave-years/{year_id}` | `LeaveYearUpdate` (`name`, `start_date`, `end_date`) — **`is_active`/`is_closed` refused (422)** | `LeaveYearRead` | `year_id` |
| POST | `/leave-years/{year_id}/activate` | — | `LeaveYearRead` | `year_id` |
| GET | `/leave-years/{year_id}/carry-forwards` | — | `CarryForwardPage` | `employee_id`, `leave_type_id`, `limit`, `offset` |
| GET | `/leave-years/{year_id}/closing-preview` | — | `ClosingPreview` | `limit`, `offset` |
| POST | `/leave-years/{year_id}/close` | `{confirm_name*, expected_fingerprint*}` | `ClosingResult` | `year_id` |
| GET | `/leave-types` | — | `LeaveTypePage` | — |
| POST | `/leave-types` | `LeaveTypeCreate` | `LeaveTypeRead` | — |
| GET | `/leave-types/{type_id}` | — | `LeaveTypeRead` | `type_id` |
| PATCH | `/leave-types/{type_id}` | `LeaveTypeUpdate` | `LeaveTypeRead` | `type_id` |
| POST | `/leave-assignments` | `{employee_id*, leave_type_id*, leave_year_id, allocated_days}` | `LeaveBalanceRead` | — |
| POST | `/leave-assignments/bulk` | `{leave_type_ids*, division_id, department_id, employee_ids, allocated_days, leave_year_id}` | `BulkAssignmentResult` (created/updated/skipped + reasons) | — |
| GET | `/leave-balances` | — | `[LeaveBalanceRead]` | `employee_id`, `division_id`, `department_id`, `leave_type_id`, `leave_year_id` |
| GET | `/leave-balances/me` | — | own balances | `leave_year_id` |
| POST | `/leave-balances/{balance_id}/adjust` | `{field*, delta*, reason*}` | summary | `balance_id` |
| GET | `/leave-balance-adjustments` | — | `AdjustmentPage` | `employee_id`, `leave_type_id`, `leave_year_id`, `field`, `created_by`, `date_from`, `date_to`, `limit`, `offset` |
| GET | `/leave-balances/me/adjustments` | — | `AdjustmentPage` | `leave_year_id`, `limit`, `offset` |

- **Leave year**: exactly one active at a time, enforced by the **partial unique index**
  `uq_leave_year_single_active`; `POST .../activate` deactivates the others and activates the target,
  as **two statements** (clear, then set) because a single multi-row UPDATE cannot guarantee row order
  and would violate the index (D-136, amended after a real failure). New years are created **inactive**
  (D-53); `is_closed` is only ever set by the closing action; two overlapping years are refused with
  **409** naming the clash (D-54).
- **Leave types**: the code is trimmed and upper-cased **before** the uniqueness check, so `" al "` and
  `"AL"` collide (**409**, D-58); `accrual_mode="monthly"` is accepted by the database but **refused by
  the API with 400** (D-57); deactivating a type that is still allocated (**> 0 days**) in a
  **not-closed** year is refused (**409**, D-68) — allocations in closed years never block.
- **Assignment**: `POST /leave-assignments` upserts the `employee_leave_type` row and creates/updates
  the `leave_balance` for that year (D-25). It refuses an inactive employee or leave type, and an
  allocation that would make `available` negative — the message is built by `_negative_message()`
  (`routers/leave_assignments.py:59-63`) and returned as **409** (line 118). Concurrency is safe because
  the `UNIQUE (employee_id, leave_type_id, leave_year_id)` constraint decides the winner (D-66).
- **Bulk assignment** runs in **one transaction**; database conflicts roll everything back (**409**),
  while **business-rule failures are skipped and reported** with a reason instead of failing the run —
  verified in the code: `reason="leave type is inactive"` and `reason="employee is inactive"`
  (`routers/leave_assignments.py:228-241`) (D-32/D-67).
- **Balance rows** are created when a leave type is assigned (D-25) and by the year-end closing for the
  next year (D-135). `available` is **computed, never stored**:
  `available = allocated + carried_forward − used − pending` (FR-LT-3/D-65), with
  `CHECK ck_leave_balance_available_not_negative` as the database-level guarantee.
- **Adjustments** are the repair path (16B): only `ALLOCATED`, `CARRIED_FORWARD`, `USED`;
  **`PENDING` can never be adjusted** (D-157); a **reason (5–500 chars) is mandatory** and is visible to
  the employee (D-159); the write is an **append-only ledger row** (trigger-protected) plus one
  `ADJUST_BALANCE` audit row; a mistake is corrected with the opposite entry (D-155); closed years and
  inactive employees/types **are** adjustable with a warning that carry-forward is not recomputed
  (D-158); the balance row is re-read with `FOR UPDATE` so two simultaneous adjustments cannot lose an
  update.

### 4.4 Weekend & Holiday Configuration

| Method | Path | Request | Response | Params |
| --- | --- | --- | --- | --- |
| GET | `/weekends/global` | — | `WeekendSettingRead` (**404** when nothing is configured — D-76) | — |
| PUT | `/weekends/global` | `{days_of_week*: [0..6]}` | `WeekendSettingRead` | — |
| GET | `/weekends/employees` | — | `[WeekendSettingRead]` | — |
| PUT | `/weekends/employees/{employee_id}` | `{days_of_week*}` | `WeekendSettingRead` | `employee_id` |
| DELETE | `/weekends/employees/{employee_id}` | — | 204 | `employee_id` |
| GET | `/holidays` | — | `[HolidayRead]` | `leave_year_id`, `division_id`, `department_id`, `type` |
| POST | `/holidays` | `{leave_year_id*, date \| date_from+date_to, title*, type, division_id, department_id}` | `HolidayRead` | — |
| PATCH | `/holidays/{holiday_id}` | `{date, title, type, division_id, department_id}` | `HolidayRead` | `holiday_id` |
| DELETE | `/holidays/{holiday_id}` | — | 204 | `holiday_id` |
| POST | `/holidays/import` | multipart `{leave_year_id*, file*}` | `HolidayImportResult` | — |
| GET | `/calendar/preview` | — | `CalendarPreview` (per-day `kind` + chargeable days) | `start_date`, `end_date`, `day_type`, `employee_id` |

- The **global weekend** is the single row whose `employee_id IS NULL` (partial unique index); `PUT`
  creates it or updates it. An **employee override** is a separate row; `DELETE` removes the override,
  after which the employee falls back to the global setting (FR-CAL-2). Weekends are stored in a
  PostgreSQL `ARRAY`, de-duplicated in the API (D-74).
- **Holidays** are one row per date (a date range is expanded — D-07) and can be scoped to a division
  and/or department, with `NULL` meaning "everybody". The unique index `uq_holiday_date_scope` refuses a
  duplicate date in the same scope (**409**). **CSV import is all-or-nothing** — every row is validated
  first and a single bad row imports nothing, listing the failing row numbers (D-73); the limit is
  `MAX_IMPORT_ROWS = 1000`.
- **What happens when a holiday changes after a request exists: nothing is recalculated.** The DELETE
  handler documents it (`routers/holidays.py:247`: *"deleted holiday only affects requests that were
  never reserved against it"*). `leave_request.chargeable_days` and its `leave_request_allocation` rows
  are **stored values** and are not recomputed for PENDING/APPROVED requests. The same is true for
  changing a weekend setting. This is a real, documented characteristic — see §6.
- Holidays are found by **date range**, not by `leave_year_id`, so a request spanning two leave years
  still sees every holiday in its window (D-75). Only `PUBLIC` and `COMPANY` reduce the day count;
  `OPTIONAL` is shown but never charged (D-71/D-117).

### 4.5 Chargeable Day Calculation Engine

File: `backend/app/services/day_calc.py`. It is a **pure function** — no database, no HTTP, no clock
(D-72), which is why it is unit-tested without any infrastructure (`tests/test_day_calculation.py`).

```
calculate_chargeable_days(start, end, day_type, weekend_days, holidays) -> DayCalcResult
      chargeable_days: Decimal        # the number the balance moves by
      days:            [DayResult]    # every date in the range with its DayKind
```

The algorithm, in order:

1. **Week index convention** — `weekday_index(date)` (line 53) converts Python's Monday=0 into the
   project convention **0 = Sunday … 6 = Saturday** (`(value.weekday() + 1) % 7`).
2. **Per-day classification** — `_day_kind(date, weekend, holidays)` (line 73): the date is
   `DayKind.HOLIDAY` if it is in the applicable holiday set, else `DayKind.WEEKEND` if its weekday index
   is in the weekend set, else `DayKind.WORKING`. `_normalise_weekend()` (line 65) turns the stored
   array into a set, so duplicate or unordered values cannot change the result.
3. **Which weekend set applies** — the caller passes the employee's own override if one exists, else the
   global set (FR-CAL-2; `services/calendar.py` performs that lookup and raises **409** when neither is
   configured, because a calculation genuinely cannot happen — D-76).
4. **Which holidays apply** — `PUBLIC` and `COMPANY` only; `OPTIONAL` is returned in the preview but is
   **not** subtracted (D-71).
5. **Count** — every `WORKING` day counts `1`. A **half-day** (`FIRST_HALF` / `SECOND_HALF`) counts
   `0.5` **only when the single date is a working day**; a half-day on a weekend or holiday is blocked
   (D-26). A `FULL_DAY` request that contains no working day at all yields `chargeable_days = 0`, and
   submission is refused (FR-CAL-4).
6. **Why the per-day list is returned** — the preview endpoint returns it to the browser
   (`GET /calendar/preview` carries a `kind` per day: `WORKING`, `WEEKEND`, `HOLIDAY`), and the
   **cross-year split** reuses it: `request_rules.py::years_for_days()` (line 64) and
   `split_days_by_leave_year()` (line 79) put each day into its own leave year, and `split_total()`
   (line 110) adds them up. A request that starts in December and ends in January therefore produces
   **two** `leave_request_allocation` rows (D-05), and a cancellation can never restore a proportional
   guess because the exact rows exist (D-105).
7. **Overlap detection** is a separate pure helper: `request_rules.ranges_conflict(a, b)` (line 40).

### 4.6 Leave Request & Parallel Approval Workflow

| Method | Path | Request | Response | Params |
| --- | --- | --- | --- | --- |
| POST | `/leave-requests` | multipart: `leave_type_id*`, `start_date*`, `end_date*`, `day_type`, `reason*`, `attachment` | `LeaveRequestDetail` | — |
| GET | `/leave-requests/check` | — | `LeaveRequestCheck` (chargeable days + balance + per-day preview, **no write**) | `leave_type_id*`, `start_date*`, `end_date*`, `day_type`, `has_attachment` |
| GET | `/leave-requests/me` | — | own requests | `status`, `leave_year_id`, `limit`, `offset` |
| GET | `/leave-requests` | — | all requests (ADMIN) | `status`, `employee_id`, `division_id`, `leave_year_id`, `limit`, `offset` |
| GET | `/leave-requests/{request_id}` | — | `LeaveRequestDetail` (+ `can_cancel`, `touches_closed_year`) | `request_id` |
| GET | `/leave-requests/{request_id}/attachment` | — | the file stream | `request_id` |
| POST | `/leave-requests/{request_id}/approve` | `{comment}` | `DecisionResult` | `request_id` |
| POST | `/leave-requests/{request_id}/reject` | `{comment*}` | `DecisionResult` | `request_id` |
| POST | `/leave-requests/{request_id}/cancel` | `{comment}` | `DecisionResult` | `request_id` |
| GET | `/approvals/inbox` | — | the caller's pending approvals | `status`, `limit`, `offset` |
| GET | `/approvals/inbox/count` | — | `{pending}` (the sidebar badge) | — |

**Validations on submission** (FR-LR-2, each with its own message):

| Rule | Where |
| --- | --- |
| `start_date <= end_date`; a half-day is a single date | API **and** `CHECK ck_leave_request_dates` / `ck_leave_request_half_day_single` |
| The leave type must be **assigned** to the employee for that leave year | `services/leave_requests.py::submit()` → `evaluate()` |
| `chargeable_days > 0` | API + `CHECK ck_leave_request_days` |
| `chargeable_days <= available` | `evaluate()`; the database CHECK is the last line of defence |
| **Negative balance is never allowed** | API **and** `CHECK ck_leave_balance_available_not_negative`; extra days exist only if an admin creates them with an `ALLOCATED` adjustment |
| No overlap with a `PENDING` or `APPROVED` request (calendar-date comparison; `REJECTED`/`CANCELLED` do not block — D-09/D-109) | `request_rules.ranges_conflict()` |
| At least one active approver | `evaluate()` (FR-LR-2.6) |
| Attachment: allowed types + magic bytes, size `MAX_UPLOAD_BYTES` (default 5 MB → **413**), strangers get **404** | `services/storage.py` + the download handler (D-90) |
| Reason length 1..1000 | `MAX_REASON = 1000` (`routers/leave_requests.py:54, 250`) |
| Attachment *required* after N days when configured | `leave_type.require_attachment_after_days`, checked as **chargeable** days (D-10) |

**How `pending` and `used` move** (per leave year, through the allocation rows):

| Action | Balance effect | Where |
| --- | --- | --- |
| Submit | every touched year: `pending += days` (this is what reduces `available`) | `services/leave_requests.py::submit()` |
| Approve (not the last one) | **nothing moves** — the days stay reserved | `services/approvals.py::act()` |
| Approve (the last one) | `pending -= days`, `used += days`, `status = APPROVED`, `final_decided_at` set | `services/approvals.py:139-141` |
| Reject (any approver) | `pending -= days` (released), `status = REJECTED`, remaining `PENDING` approvals become `SKIPPED` | `services/approvals.py::act()` (line 155) |
| Cancel a `PENDING` request | `pending -= days` (`BalanceEffect.RELEASE`) | `services/cancellations.py` + `cancel_rules.decide_cancel()` |
| Cancel an `APPROVED` request | **there is no such path** — `RESTORE_USED` was deleted (D-153) | `cancel_rules.can_cancel()` returns False for every status except `PENDING` |

**Parallel approval, precisely.** When a request is submitted, the approvers are **snapshotted**: one
`leave_request_approval` row per current approver, all `PENDING` (D-88) — changing the approver list
afterwards does not alter an in-flight request.
- The request becomes `APPROVED` **only when every** approval row is `APPROVED` (all-must-approve,
  FR-APR-3).
- **Any single rejection** immediately sets the request to `REJECTED`, marks the remaining `PENDING`
  approvals `SKIPPED` (already-`APPROVED` rows stay `APPROVED`, so the history stays truthful — D-98),
  and releases the `pending` days.
- `services/approvals.py` documents and implements the locking: it takes the **request row** with
  `with_for_update()` **first** (lines 64-70), then the balance rows in ascending `leave_year_id`, so
  two simultaneous decisions cannot both change the balances; the global order
  **leave_year → employee → leave_balance** is stated at the top of the file (D-96).
- The requester deciding their own request gets **403** (they know it exists); a stranger with no
  approval row gets **404** (nothing is revealed) — D-97/D-89.

**Cancellation.** `cancel_rules.can_cancel(request_status, requester_id, actor_id, actor_is_admin)`
(line 108) is the single rule: `status == "PENDING" and (is_requester or is_admin)` (D-153/D-162). The
API's `can_cancel` flag on the detail response is computed with the same function, so the button can
never appear where the call would be refused.

**Concurrency control.** `submit()` locks (D-87): the **employee row** with `FOR UPDATE`, then the
balance rows of the touched years in ascending year order, then re-runs `evaluate()` under those locks;
`services/locking.py` provides `lock_years_shared` / `lock_years_exclusive` / `assert_years_open`, and
`close_year` takes `FOR UPDATE` on the year rows, while `approvals.act()` / `cancellations.cancel()`
deliberately take **no** year lock because a closed year can never hold a pending request (D-139).
`reconcile_balances(session, employee_id)` recomputes expected `pending`/`used` from the allocation rows
(plus `USED` adjustments, D-156) and is called by the test suite.

**Audit rows.** Every write route writes exactly one audit row per business action, **inside the
caller's transaction**, and the action rolls back if the row cannot be written (fail-closed, D-141);
`PATCH /employees/{id}` may legitimately write up to three rows (`UPDATE`, `ROLES_CHANGED`,
`PASSWORD_RESET` — D-142); secrets are redacted and a password reset stores **no values at all**
(D-150). The coverage test `tests/test_audit_coverage.py` fails if a write route is missing from
`core/audit_registry.py`, so this cannot silently rot.

### 4.7 Carry-Forward & Year-End Job

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| GET | `/leave-years/{year_id}/closing-preview` | — | `ClosingPreview` (what *would* happen + fingerprint + blockers + warnings) |
| POST | `/leave-years/{year_id}/close` | `{confirm_name*, expected_fingerprint*}` | `ClosingResult` |
| GET | `/leave-years/{year_id}/carry-forwards` | — | `CarryForwardPage` (the log) |

- **How it is triggered: manually only.** There is **no scheduler and no automatic closing**; an admin
  opens the wizard, reads the preview and confirms. Confirmation needs the year name typed **and** the
  fingerprint from the preview, or the call is refused with **409 "data changed, preview again"** — an
  optimistic concurrency check (D-133). There is **no undo** and **no early-close switch**.
- **The calculation** (`services/closing_rules.py::compute_carry`, lines 40-61):
  `left = available at close`; `carried = min(left, max_carry_forward_days)`; `forfeited = left - carried`
  — i.e. exactly the FR-LT-4 `min(unused, max_carry_days)` rule. A leave type with
  `carry_forward_allowed = false` is skipped and `max_carry_forward_days` is ignored (D-22).
- **Blockers** (`closing_rules.closing_blockers`, line 91 — all **409**): the year has not ended
  (`year_has_ended`, line 86); there is no **adjacent next** year (`find_next_year`); the next year is
  already closed; the **previous** adjacent year is still open (`find_previous_year` — days must move in
  order); or **pending requests exist**, counted through `leave_request_allocation` rather than
  `leave_request.leave_year_id`, so a cross-year request that still owes days to this year is caught
  (D-132). Warnings (employees with carried days but no next-year assignment) never block (D-137).
- **The log**: one `leave_carry_forward` row per (employee, leave type, from-year) with
  `remaining_at_close = carried_days + forfeited_days` (enforced by CHECK). **No row is written when
  nothing happens** — carry-forward disabled, or nothing left (D-134). The unique constraint makes a
  second closing of the same year impossible at the database level (D-140).
- **Inactive employees are skipped and counted** in the summary (D-138).
- The next year's `leave_balance` is created with `allocated = 0` and **without** an
  `employee_leave_type` row, and `carried_forward` is **added**, never overwritten (D-135).
- The closing writes **one summary** audit row (counts, totals, skipped employees) rather than copying
  the per-employee log (D-144).

### 4.8 Email Notifications & Reminders

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/admin/emails` | the queue with filters (`status`, `event_type`, `related_request_id`, paging) |
| GET | `/admin/emails/{email_id}` | one message + its `email_attempt` history **+ the rendered `subject`, `body_text` and `body_html`** (D-195) |
| POST | `/admin/emails/{email_id}/retry` | only a `FAILED` row can be requeued; attempts reset to 0, old attempts kept |
| POST | `/admin/emails/process-queue` | runs ONE pass of the worker now (`?reminders=true` also runs the reminder tick and drains it) and returns counts (D-195) |

**The seven events that trigger mail** — the constants exist in `services/email_rules.py:18-24` and are
mapped by `plan_emails(event, facts)` (line 91):

| Event constant | When it fires | Recipients (FR-NOT-1) |
| --- | --- | --- |
| `SUBMITTED` | a request is submitted | all assigned approvers, Cc the employee |
| `APPROVER_ACTED` | one approver acts while others are still pending | the employee |
| `APPROVED` | the last approval arrives | the employee (Cc approvers) |
| `REJECTED` | any approver rejects | the employee (Cc approvers) |
| `CANCELLED` | a pending request is cancelled | the approvers |
| `CANCELLED_EMPLOYEE` | an **admin** cancelled somebody else's request | the employee (the extra mail in D-115) |
| `REMINDER` | an approval is still pending beyond the threshold | the approver, one digest per local date |

- **Asynchronous and queued — real, not mocked.** `services/notifications.enqueue_events()` only
  **INSERTs** into `email_outbox`, inside the caller's transaction, with a `dedupe_key` and
  `ON CONFLICT DO NOTHING` (D-110/D-112): a business action can never be rolled back or blocked by a
  mail problem, and a retried request cannot produce a duplicate mail. Rendering and sending happen in
  the **worker** (`python -m app.worker`), which claims rows with
  `SELECT … FOR UPDATE SKIP LOCKED` (D-113), marks them `SENDING` + `claimed_at`, **commits**, and only
  then renders and sends outside the transaction. Rows stuck in `SENDING` for more than 10 minutes are
  returned to `PENDING`. Failures retry on **60 s, 5 min, 30 min, 2 h, 12 h**, up to `EMAIL_MAX_ATTEMPTS`
  (default 5), then `FAILED` (D-118). Every attempt is logged in `email_attempt` with its backend name.
- **Is SMTP real or mocked? Both exist; the choice is a setting.** `services/mailer.py` supports
  `EMAIL_BACKEND=console` (renders and records, **sends nothing**), `file` (writes a real `.eml` into
  `EMAIL_FILE_DIR`, random file name — D-119) and **`smtp` (a genuine `smtplib` call in a thread, 15 s
  timeout, STARTTLS, multipart)**. Nothing is stubbed: `smtp` really talks to the configured server.
  **The current demo configuration deliberately uses `console`** (D-189), so in that setup the honest
  description is: the whole queue works, the messages are rendered, recorded and marked `SENT`, and
  **nothing is delivered anywhere**.
- **Reminders**: the worker's 15-minute tick (`REMINDER_EVERY_SECONDS`) evaluates overdue approvals
  using the **organisation timezone** (`ORG_TIMEZONE`) and each approver's own weekend/holidays, and
  writes at most one digest per approver per local date (D-114).
- **System actions are not audited** (D-148): enqueueing, sending and retrying write no `audit_log`
  row; their history lives on the email row and in `email_attempt`.

---

## 5. Frontend Pages, Components & Features

21 pages, all routed in `src/App.jsx`. Everything below is a real screen wired to the API — there are
**no placeholder/stub pages** in the router (the one catch-all redirects to `/`).

### 5.1 Public / shell

| Route | Page | What actually works |
| --- | --- | --- |
| `/login` | `LoginPage.jsx` | e-mail + password login; shows a "session expired" notice; a **429 countdown** using `Retry-After`; sends the user to `/account` when the API says a password change is required, otherwise to `/` |
| any (shell) | `components/Layout.jsx` | sidebar grouped *My leave / Approvals / Administration / System* filtered by role; approvals badge from `/approvals/inbox/count`; user menu → `/account`; Logout. While `must_change_password` is set everything except `/account` redirects there and a warning banner is shown |
| — | `auth/AuthContext.jsx`, `auth/ProtectedRoute.jsx` | restore-on-reload through the refresh cookie, in-memory access token, single-flight refresh, cross-tab logout via `BroadcastChannel` |
| — | `api/client.js`, `api/liveUpdates.js`, `api/refreshCoordinator.js`, `hooks/useAutoRefresh.js` | axios instance with `withCredentials`, one retry after a silent refresh, change signal + focus refresh + 15 s poll |

### 5.2 Employee screens

| Route | Page | What works |
| --- | --- | --- |
| `/` (index) | `HomePage.jsx` | greeting, stat tiles, **month calendar** (month + year selectable), balance summary, recent requests, my approvers, and — for admins — a pending list |
| `/my-balances` | `MyBalancesPage.jsx` | per-leave-type cards, a combined bar, a breakdown table with a **Total** row, `carried_forward` line, and an adjustments section |
| `/leave-requests/new` | `LeaveRequestFormPage.jsx` | the real submit form: leave type, dates via a **popup calendar** (`DateField`), day type, reason, **file upload**, and a sticky right-hand panel showing **balance impact** and the **day-by-day preview** from `/leave-requests/check`; an empty-state checklist when the employee has no assignment or no approver |
| `/my-requests` | `MyLeaveRequestsPage.jsx` | own request list with status badges |
| `/leave-requests/:id` | `LeaveRequestDetailPage.jsx` | full detail, approvals timeline, attachment download, **Cancel request** (only when the server's `can_cancel` is true), closed-year notice, and for admins a history panel |
| `/calendar-preview` | `CalendarPreviewPage.jsx` | pick a range and see weekends/holidays and the chargeable day count *before* submitting |

### 5.3 Approver screens

| Route | Page | What works |
| --- | --- | --- |
| `/approvals` | `ApprovalsInboxPage.jsx` | the inbox of requests waiting for **this** approver, with **Approve** / **Reject** buttons opening `components/DecisionModal.jsx` (a rejection comment is required) |

### 5.4 Admin screens

| Route | Page | What works |
| --- | --- | --- |
| `/divisions` | `DivisionsPage.jsx` | list, create, edit, activate/deactivate (no delete — the API has none) |
| `/departments` | `DepartmentsPage.jsx` | list per division, create, edit; the division is shown **read-only** in the edit modal (it is immutable) |
| `/employees` | `EmployeesPage.jsx` | list/filter, create (password + roles, `EMPLOYEE` shown ticked and locked, `must_change_password`), edit, deactivate; the department dropdown depends on the chosen division |
| `/leave-types` | `LeaveTypesPage.jsx` | create/edit with quota, half-day, attachment-after-N-days, carry-forward + cap |
| `/leave-years` | `LeaveYearsPage.jsx` | create, edit, **activate**, and the **year-end closing wizard** (preview → typed confirmation) plus the carry-forward log |
| `/assignments` | `LeaveAssignmentsPage.jsx` | the entitlement/balance grid, single + **bulk** assignment, and the **Adjust** modal (`AdjustBalanceModal.jsx`, with a before/after preview) and **Adjustment history** (`AdjustmentHistoryModal.jsx`) |
| `/approvers` | `ApproversPage.jsx` | assign/unassign approvers per employee (only `APPROVER` role-holders are offered) |
| `/calendar-settings` | `CalendarSettingsPage.jsx` | the global weekend, per-employee overrides, and holiday management including the **CSV import** |
| `/admin/leave-requests` | `AdminLeaveRequestsPage.jsx` | every request with filters |
| `/reports` | `ReportsPage.jsx` | **Balances** and **History** tabs, filters held in the URL, and **Download CSV** (the file is fetched as a blob, so the browser saves it) |
| `/admin/emails` | `AdminEmailsPage.jsx` | the email queue, one message's detail + attempts, and the retry action |
| `/admin/audit-log` | `AdminAuditLogPage.jsx` | filterable audit trail + a detail view. Read-only — there is no create/update/delete UI because there is no such endpoint |

Shared components: `Icon`, `NoOptions`, `StatusBadge`, `RequestStatusBadge`, `DateField` (popup
calendar), `MonthCalendar`, `DayPreview`, `DecisionModal`, `AdjustBalanceModal`,
`AdjustmentHistoryModal`, `Layout`.

---

## 6. Known Placeholders, TODOs, or Unimplemented Parts

### 6.1 TODO markers that exist in the code right now

| File | Marker | Meaning |
| --- | --- | --- |
| `services/closing.py` | (resolved, D-196) the closing **deliberately sends no mail** — visible in the closing summary, the carry-forward log and *My balances* |
| `services/adjustments.py` | (resolved, D-196) an adjustment **deliberately sends no mail** — not one of the six FR-NOT-1 events |
| `routers/employees.py:308` | comment about "finishing the Phase-4 TODO (FR-EMP-3)" | historical note; the behaviour (deactivation revokes login) **is** implemented by `get_current_user` rejecting inactive accounts |
| `services/audit_rules.py:119` | docstring: returns a *placeholder* when the JSON would exceed `max_bytes` | intentional truncation marker, not missing work |
| `main.py:51`, `services/security_rules.py:241,302` | strings containing the word "placeholder" | these are the **warnings** for a weak `JWT_SECRET` / a placeholder `S3_SECRET_ACCESS_KEY` — validation that exists, not a gap |

The many `placeholder=` hits in the frontend are HTML `placeholder` attributes on form inputs, not
TODOs. No `FIXME`, `NotImplementedError` or `raise NotImplemented` exists anywhere in `backend/app`.

### 6.2 NOT IMPLEMENTED (no code path at all)

| Item | Evidence |
| --- | --- |
| **S3 / object storage** | `services/storage_rules.py` (key format, allow-list, content types) and its tests exist, but `services/storage.py` is **local-disk only**; no `boto3` import exists in the app, and `boto3`/`moto` are not in `requirements.txt`. `STORAGE_BACKEND` is read, but only `local` is honoured |
| **Containers & deployment** | no `Dockerfile`, no `.dockerignore`, no nginx/Caddy config, no production `.env` template, no `deploy/` folder. `services/csp_rules.py` can *build* the Content-Security-Policy string, but **nothing serves it** |
| **Two-factor authentication** | `grep -rni "totp\|two_factor\|2fa" backend/app frontend/src` → **no matches** |
| **JWT secret rotation / `kid`** | `core/security.py` signs with a single `JWT_SECRET`; there is no key id, JWKS or previous-secret handling |
| **E-mail-based password reset** | not built; an admin resets a password instead (D-28) |
| **A second-admin approval for balance adjustments, and bulk adjustments** | not built (backlog) |
| **Audit-log export** | not built — the log is read on screen only |
| **`.xlsx` export** | not built — CSV only (D-20) |
| **Automatic/scheduled year-end closing** | not built by design — a human runs it (D-133) |
| **Monthly accrual** | the database allows `accrual_mode='monthly'`, the **API refuses it with 400** (D-57) |
| **`weekend_setting.effective_from`** | the column is not implemented at all; one weekend per employee, no history (D-29) |
| **Pro-rata allocation for mid-year joiners** | not built — the admin types the allocated days (D-06) |

### 6.3 PARTIAL, or behaviour that will surprise somebody

1. **Attachments are on local disk** (`backend/media/`), keys `attachments/YYYY/MM/<32 hex>.<ext>` for new
   uploads (D-179) with old flat keys still readable. Fine on one laptop; **not** survivable in a
   stateless deployment.
2. **The email worker is not started by anything.** In development, in the demo and in production you
   must run `python -m app.worker` yourself; without it the queue simply fills up with `PENDING` rows.
3. **A holiday or weekend change does not recalculate existing requests.** Stored `chargeable_days` and
   allocation rows stay as they were (documented in `routers/holidays.py:247`).
4. **An APPROVED request can never be cancelled** — not by the employee, not by an admin (D-153). The
   repair path is a manual `USED`/`ALLOCATED` adjustment, and if the request touched a closed year the
   next year's carry-forward is **not** recomputed automatically (D-158).
5. **Reports count whole requests**: the date filter uses **overlap**, but a request that overlaps the
   window contributes **all** its days to the totals (backlog).
6. **The audit log is tamper-evident, not tamper-proof**: a database owner could drop the trigger. It is
   append-only by trigger and by policy, not cryptographically (backlog).
7. **`GET /health` never touches the database** (pure liveness) while `GET /health/ready` reports
   `database` / `migrations` / `email`; a stale PENDING email is a **warning** and still returns `ok`
   (D-176). `/health/db` is kept for compatibility.
8. **Email delivery is switched off in the demo configuration on purpose** (`EMAIL_BACKEND=console`,
   D-189). This is a configuration choice, not a missing feature — but on a demo laptop **no mail
   leaves the machine**.
9. **The integration/golden-path test is deselected by default** (`pytest.ini` excludes the
   `integration` marker) and needs a throw-away database; the deployment checks (Docker build, Caddy
   validate) live in CI only.
10. **`must_change_password` is enforced for accounts an admin creates or resets**, while `seed_admin`
    and the demo accounts opt out (D-190) — deliberate, but it means an existing employee is never
    retroactively forced to change a password.

### 6.4 Nothing is mocked in the core logic

Authentication, RBAC, the day-calculation engine, balances, the approval workflow, the audit log and
the outbox are all **real implementations against a real PostgreSQL database**. The only intentional
"fakes" are (a) the `console`/`file` mail backends, (b) the deliberately fake demo dataset created by
`python -m app.cli.demo_data`, and (c) `_DUMMY_HASH` in `services/auth_service.py`, which exists purely
to equalise login timing against user enumeration (D-165) — it is a security measure, not a stub.
