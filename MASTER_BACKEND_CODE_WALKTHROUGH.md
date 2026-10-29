# MASTER BACKEND CODE WALKTHROUGH

A line-by-line tour of the FastAPI backend. Backend only: connection, auth, models, routers,
services, business rules, the outbox and the database triggers.

**How to read this.** Each block gives you the **file**, the **function or line range**, a **real
snippet** from that file, and a **worked example** with concrete values so you can predict what the
database and the response will look like. Line numbers are from this version of the code — if they
drift, search for the function name.

---

## 1. Database Connection, Session & Core Setup

### 1.1 The URL is normalised before anything else

**File:** `backend/app/core/config.py`

| What | Where |
| --- | --- |
| `_to_asyncpg_url(url)` — rewrites `postgresql://` / `postgres://` to `postgresql+asyncpg://`, turns `sslmode=require` into `ssl=require` (asyncpg does not understand libpq syntax), drops `sslmode=disable`, keeps every other query parameter | **line 30** |
| `class Settings(BaseSettings)` — reads the env file chosen by `LMS_ENV_FILE`, default `backend/.env` | **line 74** |
| `async_database_url` property — what the engine actually uses | **line 157-158** |

```python
# config.py:157
@property
def async_database_url(self) -> str:
    return _to_asyncpg_url(self.database_url)
```

### 1.2 Pooler detection (Supabase 5432 vs 6543)

**File:** `backend/app/db/urls.py`

```python
# urls.py:20
POOLER_PORTS = frozenset({6543})          # Supabase transaction pooler (pgbouncer)
```

* `is_pooled(url)` (**line 32**) returns `True` only when the **port** is 6543. The port decides, not
  the hostname — Supabase's *session* pooler also lives on `*.pooler.supabase.com` but keeps one server
  session per client, so prepared statements are safe there.
* `connect_args_for(url, force=False)` (**line 44**) returns `{"statement_cache_size": 0}` for the
  transaction pooler. A prepared statement cached on one server session can be "already taken" when
  pgbouncer hands the next query to a different one; turning the cache off removes that whole class of
  error.

### 1.3 The engine and the session factory

**File:** `backend/app/db/session.py`

```python
# session.py:12
engine = create_async_engine(
    settings.async_database_url,
    echo=False,
    pool_pre_ping=True,                       # line 17: a dropped cloud connection recovers itself
    connect_args=connect_args_for(             # line 20
        settings.async_database_url, force=settings.db_statement_cache_disabled
    ),
)

async_session_factory = async_sessionmaker(   # line 25
    bind=engine, class_=AsyncSession, expire_on_commit=False
)

async def get_session() -> AsyncGenerator[AsyncSession, None]:   # line 32
    async with async_session_factory() as session:
        yield session
```

Three things to notice:

1. **`expire_on_commit=False`** — after `commit()` the objects keep their loaded values instead of
   triggering a lazy re-SELECT (which would need the async context again).
2. **One session per request**, opened by the dependency and closed when the request ends.
3. **Nothing auto-commits.** If a function returns without `commit()`, the work is thrown away — that is
   what makes "refuse and nothing changed" so easy: raise `HTTPException` and the transaction is gone.

### 1.4 A route using it

```python
# routers/divisions.py (GET /divisions), roughly lines 20-28
async def list_divisions(
    session: AsyncSession = Depends(get_session),
    _user: Employee = Depends(get_current_user),
):
    rows = (await session.scalars(select(Division).order_by(Division.id))).all()
    return [DivisionRead.model_validate(row) for row in rows]
```

**Worked example.** `GET /divisions` with a valid token:

1. `get_current_user` runs first (its own dependency) and returns employee #7.
2. `get_session` opens connection #3 of the pool.
3. One `SELECT … FROM division ORDER BY id` is sent.
4. Rows `[1 Head Office, 2 Operations, 3 Corporate Services]` are mapped to `DivisionRead`.
5. Nothing was written, so no commit; the `async with` closes the session and returns the connection.

### 1.5 Transactions you will see in the services

| Pattern | Where | Why |
| --- | --- | --- |
| `await session.commit()` at the end of a write route | every router | one unit of work |
| `await session.rollback()` inside `except IntegrityError` | e.g. `routers/employees.py:434` | a unique violation must not poison the session |
| `await session.flush()` before reading a generated id | `routers/employees.py:194`, `auth_service.py:232` | `flush` sends the INSERT without committing, so `id` exists |
| `execution_options(populate_existing=True)` after `SELECT … FOR UPDATE` | `services/cancellations.py:86` | without it SQLAlchemy hands back the stale copy already in the identity map |

---

## 2. Authentication, Refresh Token Rotation & RBAC

### 2.1 Passwords: argon2 + a timing equaliser

**File:** `backend/app/core/security.py`

| Symbol | Line | Note |
| --- | --- | --- |
| `MIN_PASSWORD_LENGTH = 8` | 15 | absolute floor; the real policy is stricter |
| `hash_password()` | 22 | argon2id, one-way, deliberately slow |
| `verify_password()` | 27 | returns `False`, never raises |

```python
# auth_service.py:46  — this hash is never a real account
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")
```

Why it exists: an unknown e-mail and a wrong password must take the **same time**, otherwise an
attacker can discover which addresses exist by timing the response. `login()` verifies against
`_DUMMY_HASH` when the account is missing or inactive, and both cases return the **same** 401 text
(`auth_service.py:39`, `GENERIC_INVALID`). A password longer than 128 characters
(`MAX_PASSWORD_INPUT`, line 41) is rejected before hashing, so nobody can burn CPU by posting a 1 MB
password.

### 2.2 The access token (JWT) — `sub` only

```python
# core/security.py:35-47
def create_access_token(subject: int, expires_minutes: int | None = None) -> str:
    payload = {"sub": subject, "type": TOKEN_TYPE, "exp": ...}     # sub = employee id
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

# security.py:50-52
def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
```

**Deliberately absent:** roles, names, permissions. If roles were baked in, a demoted admin would keep
their powers until the token expired. Instead everyone is reloaded from the database per request
(`deps.py:64`).

### 2.3 The refresh token — opaque, hashed, in an httpOnly cookie

```python
# services/security_rules.py:23 / 28
def hash_token(token: str) -> str: ...      # SHA-256, used for storage and lookup
def new_token() -> str: ...                 # 32+ random bytes, url-safe
```

```python
# routers/auth.py:42-46  (the cookie)
max_age=settings.refresh_token_days * 24 * 60 * 60,
httponly=True,
secure=settings.cookie_secure,
samesite=settings.cookie_samesite,
path=COOKIE_PATH,          # "/auth" — the cookie is not sent to /leave-requests etc.
```

The database row (`models/auth_tokens.py:21`) stores: `employee_id`, `family_id`, `token_hash`
(unique), `issued_at`, `expires_at`, `family_started_at`, `last_used_at`, `revoked_at`,
`replaced_at`, `replaced_by_id`, `user_agent`. **No token, no IP.**

### 2.4 Rotation and reuse detection

**File:** `backend/app/services/security_rules.py:33` — `classify_refresh(row, now, grace_seconds, max_family_age_days)`

| Result constant | Line | Meaning | What `rotate()` does |
| --- | --- | --- | --- |
| `VALID` | 15 | live token | rotate |
| `EXPIRED` | 16 | past `expires_at` | 401 |
| `FAMILY_TOO_OLD` | 17 | family older than `REFRESH_FAMILY_MAX_DAYS` (30) | 401 |
| `REVOKED` | 18 | logged out / password changed / deactivated | 401 |
| `REUSED_WITHIN_GRACE` | 19 | old token replayed within 10 s (two tabs) | **409 `REFRESH_RACE`** (`auth_service.py:258`) |
| `REUSED_THEFT` | 20 | replayed after the grace window | **the whole family is revoked** (`auth_service.py:292`) + audit `REFRESH_REUSE_DETECTED` |

### 2.5 Every protected request: `get_current_user`

**File:** `backend/app/core/deps.py`, function at **line 38**

```python
# deps.py:38-82, condensed but faithful
async def get_current_user(request, token=Depends(oauth2_scheme), session=Depends(get_session)):
    try:
        payload = decode_access_token(token)                       # 50
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token has expired.")                  # 52
    except jwt.InvalidTokenError:
        raise _unauthorized("Invalid token.")                      # 54

    if payload.get("type") != TOKEN_TYPE:                          # 56
        raise _unauthorized("Invalid token.")

    employee_id = int(payload.get("sub"))                          # 60
    employee = await session.get(Employee, employee_id)            # 64
    if employee is None or not employee.is_active:                 # 65
        raise _unauthorized("Invalid or inactive account.")

    if not may_use_application(must_change_password=..., path=request.url.path):   # 70-73
        raise HTTPException(403, "You must change your password before using the application.")
    return employee
```

Status codes, exactly:

| Situation | Code | Body |
| --- | --- | --- |
| no header / bad signature / expired / wrong `type` / unknown or inactive employee | **401** | `Invalid token.` · `Token has expired.` · `Invalid or inactive account.` |
| logged in, but `must_change_password` is set and the path is not one of `/auth/me`, `/auth/change-password`, `/auth/logout`, `/auth/logout-all`, `/auth/refresh` | **403** | `You must change your password…` + header `X-Password-Change-Required: true` |
| role guard fails | **403** | `You do not have permission to perform this action.` (`deps.py:95`) |

Role guard:

```python
# deps.py:84
def require_roles(*allowed: Role | str):
    required = {Role(role) for role in allowed}
    async def dependency(employee=Depends(get_current_user), session=Depends(get_session)):
        roles = set(await load_roles(session, employee.id))        # deps.py:31
        if not roles & required:
            raise HTTPException(403, "You do not have permission to perform this action.")
        return employee
    return dependency
```

### 2.6 Worked example — one login, start to finish

Request:

```
POST /auth/login
Content-Type: application/x-www-form-urlencoded
username=nusrat@demo.example.com&password=Demo-abc123-9Aa
```

1. `routers/auth.py:75` → `auth_service.login()` (`auth_service.py:116`).
2. Rate limits counted first (`auth_service.py:135-159`) using `login_attempt` rows; nothing blocked.
3. Employee found (id 7), argon2 verify passes.
4. `login_attempt(id=…, email_normalized='nusrat@…', ip_hash='9f2c…', success=true)` inserted
   (`auth_service.py:110`).
5. JWT: `{"sub": 7, "type": "access", "exp": 1793300000}`.
6. `refresh_token` row: `family_id=8d1e…`, `token_hash=a1b2…` (hash only), `expires_at=+7d`.
7. Response `200`:
   ```json
   {"access_token": "eyJhbGciOiJIUzI1NiIs…", "token_type": "bearer", "must_change_password": false}
   ```
   and `Set-Cookie: refresh_token=…; HttpOnly; Path=/auth; SameSite=Lax; Max-Age=604800`.

### 2.7 Worked example — the refresh dance

At 09:16 the JWT is dead.

1. The browser sends `GET /leave-balances/me` → **401**.
2. `frontend/src/api/client.js:99-116` catches it, calls the coordinator
   (`api/refreshCoordinator.js:25`), which holds a single promise for all callers and uses
   `navigator.locks` (`refreshCoordinator.js:11`) so two tabs cannot refresh at once.
3. `POST /auth/refresh` (`routers/auth.py:101`) reads the cookie, `classify_refresh` says `VALID`,
   and rotation happens: old row `replaced_at = now`, new row in the **same family**.
4. The original GET is retried once with the new token → **200**. The user saw nothing.

---

## 3. Exhaustive Module Breakdown

### 3.1 `backend/app/main.py` — the app object

| Step | Line | What |
| --- | --- | --- |
| production guard | 41 | `_config_problems = validate_production_settings(settings)` — a bad production config refuses to start |
| app | 56 | `app = FastAPI(...)` (title, docs switch from `ENABLE_DOCS`) |
| CORS | 65-75 | explicit origins, `allow_credentials=True`, `expose_headers=["Retry-After", "Content-Disposition"]` |
| routers | 78+ | one `app.include_router(...)` per module — 78 endpoints in total |
| headers middleware | 94-102 | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on `/auth/*` and `/admin/*` |

There is **no lifespan hook**: the app holds no background loop. That is the worker's job, on purpose —
if the API dies, mail keeps flowing, and if the worker dies the API still serves.

### 3.2 `backend/app/worker.py` — the email worker

```python
# worker.py:58-60
IDLE_SECONDS = 5
REMINDER_EVERY_SECONDS = 15 * 60
```

```python
# worker.py:68-90 — claiming a batch
stmt = (
    select(EmailOutbox)
    .where(EmailOutbox.status == "PENDING", EmailOutbox.next_attempt_at <= now)
    .with_for_update(skip_locked=True)     # line 80
    .limit(BATCH)
)
```

Why `SKIP LOCKED`: two workers never send the same row and neither waits for the other. The full pass
is `drain_once()` (**line 170**): claim → mark `SENDING` + `claimed_at` → **commit** → render and send
**outside** the transaction → `_mark_sent` (**106**) or `_mark_failed` (**120**) with the backoff
schedule. `recover_stuck()` (**177**) returns rows stuck in `SENDING` for >10 min to `PENDING`.
`reminder_tick()` (**213**) queues the pending-approval digests; `cleanup_tick()` (**350**) prunes old
telemetry behind `pg_try_advisory_lock`. `run(once)` is **line 373**.

### 3.3 `backend/app/models/` — schema highlights

Every table inherits `models/base.py` (`created_at`, `updated_at`, `created_by`) except the two
append-only tables.

| Model | Table | Keys / constraints worth knowing |
| --- | --- | --- |
| `division.py` | `division` | `name` unique |
| `department.py` | `department` | `UNIQUE (division_id, name)` → `uq_department_division_name` |
| `employee.py` | `employee` | `employee_code` unique, `email` unique, `supervisor_id → employee.id`, `must_change_password` default false |
| `employee_approver.py` | `employee_approver` | `UNIQUE (employee_id, approver_id)`, `CHECK employee_id <> approver_id` |
| `leave_balance.py` | `leave_balance` | `UNIQUE (employee_id, leave_type_id, leave_year_id)` + the five CHECKs, including **`ck_leave_balance_available_not_negative`** |
| `leave_request.py` | `leave_request` + `leave_request_approval` + `leave_request_allocation` | `CHECK chargeable_days > 0`, `CHECK day_type IN (FULL_DAY, FIRST_HALF, SECOND_HALF)`, `CHECK start_date <= end_date`, `CHECK day_type='FULL_DAY' OR start_date=end_date` |
| `email_outbox.py` | `email_outbox` | `dedupe_key` unique, `CHECK status IN (PENDING, SENDING, SENT, FAILED)` |
| `audit_log.py` | `audit_log` | **does not inherit the base** (no `updated_at`, no `created_by`); trigger blocks changes |

The balance guard as SQL:

```sql
CHECK (allocated + carried_forward - used - pending >= 0)   -- ck_leave_balance_available_not_negative
```

### 3.4 `backend/app/routers/` — representative endpoints

| Endpoint | Handler | What it does (short) |
| --- | --- | --- |
| `POST /divisions` | `routers/divisions.py:30` `create_division` | validate name, 409 on duplicate, insert, audit `CREATE` |
| `POST /employees` | `routers/employees.py:163` `create_employee` | duplicate code/email → 409; password policy → 400; `EMPLOYEE` role forced; supervisor validated; audit `CREATE` |
| `POST /leave-requests` | `routers/leave_requests.py` → `services/leave_requests.submit()` (**line 274**) | the whole submission workflow (see §4.2) |
| `POST /leave-requests/{id}/approve` | `routers/approvals.py:54` `approve_request` → `services/approvals.act()` (**46**) | one approver's decision (see §4.3) |
| `POST /admin/emails/process-queue` | `routers/admin_emails.py:94` `process_queue` | one worker pass on demand: `recover_stuck()` + `drain_once()` (+ `reminder_tick()` with `?reminders=true`) |

All of them follow the same three lines: dependency guard → service call → `return` a Pydantic model.
Business rules never live in the router; the router only translates HTTP to a service call.

---

## 4. Deep-Dive Business Logic Workflows

### 4.1 The day-calculation engine

**File:** `backend/app/services/day_calc.py` — a **pure** function (no DB, no HTTP, no clock)

```python
# day_calc.py:53
def weekday_index(value: date) -> int:
    return (value.weekday() + 1) % 7          # python Mon=0 -> project 0=Sunday..6=Saturday

# day_calc.py:73
def _day_kind(value, weekend, holidays) -> DayKind:
    if value in holidays:  return DayKind.HOLIDAY
    if weekday_index(value) in weekend: return DayKind.WEEKEND
    return DayKind.WORKING

# day_calc.py:82
def calculate_chargeable_days(...) -> DayCalcResult:
    ...
    chargeable = Decimal("0.5") if kind is DayKind.WORKING else Decimal("0")   # 123 (half-day)
    ...
        chargeable += Decimal("1")                                             # 133 (full day)
    return DayCalcResult(chargeable_days=chargeable, days=days)                # 136
```

**Worked example A — full days across a weekend and a holiday.**
Weekend = Friday+Saturday (global). A PUBLIC holiday on Monday.

```
Request: Thursday 05 → Tuesday 10   (FULL_DAY)

Thu 05  WORKING   1
Fri 06  WEEKEND   0
Sat 07  WEEKEND   0
Sun 08  WORKING   1
Mon 09  HOLIDAY   0
Tue 10  WORKING   1
                     → chargeable_days = 3
```

**Worked example B — half day.**
`FIRST_HALF` on Thursday 05 (a working day) → `0.5`. The same request on Friday 06 (weekend) →
`chargeable = 0` for that day; the API then refuses submission, because
`CHECK chargeable_days > 0` and the explicit "zero chargeable days" rule both fire.

**Worked example C — a span across two leave years.**
`26 Dec 2026 → 04 Jan 2027` with weekends excluded produces five working days; the per-day list is
handed to `request_rules.years_for_days()` (**line 64**) and `split_days_by_leave_year()`
(**line 79**), which write **two** `leave_request_allocation` rows — 4 days in 2026, 1 in 2027. That is
why a later cancellation can restore the exact days instead of guessing a proportion
(`split_total`, line 110).

Overlap detection is another pure helper: `ranges_conflict(a, b)` at **`request_rules.py:40`** —
inclusive calendar ranges, and only `PENDING`/`APPROVED` requests are compared.

### 4.2 Submission and row locking

**Files:** `backend/app/services/leave_requests.py`, `backend/app/services/locking.py`

The lock order, written at the top of the approvals service and used identically here:

```
1. leave_year   (SHARED)      locking.py:26  lock_years_shared()
2. employee     (FOR UPDATE)  leave_requests.py:310
3. leave_balance rows, ascending leave_year_id  (:325)
```

```python
# leave_requests.py:306-326, condensed
assert_years_open(await lock_years_shared(session, year_ids))     # 306
await session.scalar(select(Employee.id).where(Employee.id == employee.id).with_for_update())  # 310
balances = (await session.scalars(
    select(LeaveBalance).where(...).order_by(LeaveBalance.leave_year_id).with_for_update()      # 325
)).all()
```

**Worked example.** Employee #7 (available 17 AL) submits 3 days.

| Step | Function | Result |
| --- | --- | --- |
| 1 | `evaluate()` (`leave_requests.py:68`) | chargeable 3, type assigned, no overlap, approvers exist |
| 2 | balance check (`:184-205`) | `available_before 17`, `available_after 14` ✓ |
| 3 | overlap check (`:232` `ranges_conflict`) | none |
| 4 | locks | employee row, then balance rows by year |
| 5 | `submit()` (`:274`) | `leave_request` PENDING + 1 `leave_request_allocation` (3) + N `leave_request_approval` PENDING |
| 6 | balance | `pending 0 → 3` (so `available 17 → 14`) |
| 7 | outbox | one `SUBMITTED` row, dedupe `submitted:123`, in the same transaction |
| 8 | commit | all of it, or nothing |

Refusals and their codes: not assigned → 400; overlap → 409 with the clashing request; over the
balance → 409; no approver → 400; `chargeable_days = 0` → 400; year closed → 409. The database CHECK
is the last line of defence if a race ever slips past the API.

### 4.3 Parallel approval

**File:** `backend/app/services/approvals.py`, `act()` at **line 46**

```python
# approvals.py:68-70 — the request row is locked FIRST
request = await session.scalar(select(LeaveRequest).where(LeaveRequest.id == request_id)
                               .with_for_update().execution_options(populate_existing=True))
...
# approvals.py:139-141 — the last approval arrived
balance.pending = Decimal(balance.pending) - Decimal(allocation.days)
balance.used    = Decimal(balance.used)    + Decimal(allocation.days)
...
# approvals.py:155 — any rejection
row.status = SKIPPED
```

Rules:

* Approvers are **snapshotted** at submission (`leave_request_approval` rows). Changing the approver
  list later does not touch an in-flight request.
* **All must approve** → the request becomes `APPROVED` only when no approval row is left `PENDING`.
* **Any one rejects** → `REJECTED` immediately, the remaining `PENDING` rows become `SKIPPED`,
  already-`APPROVED` rows stay `APPROVED`, and `pending` is released.
* The requester deciding their own request gets **403** (they know it exists); a stranger gets **404**.

**Worked example.** Two approvers, 3 days.

| Action | request.status | approval rows | pending | used |
| --- | --- | --- | --- | --- |
| submit | PENDING | #1 PENDING, #2 PENDING | 3 | 0 |
| #1 approves | PENDING | #1 APPROVED, #2 PENDING | 3 | 0 |
| #2 approves | **APPROVED** | both APPROVED | **0** | **3** |

Alternative ending: #2 rejects instead → `REJECTED`, `#2 REJECTED`, `#1` untouched (already approved),
`pending 3 → 0`, `used` stays 0. `reconcile_balances()` (**line 221**) recomputes the expected
`pending`/`used` from the allocation rows and is called after every test scenario.

### 4.4 Cancellation and balance restoration

**File:** `backend/app/services/cancellations.py`, `cancel()` at **line 51**

```python
# cancellations.py:131-146 — the closed-year guard
years = (await session.scalars(
    select(LeaveYear).where(LeaveYear.id.in_(year_ids)).order_by(LeaveYear.id)
    .with_for_update(read=True)                     # SHARED — the closing takes EXCLUSIVE
)).all()
closed = [year.name for year in years if year.is_closed]
if closed:
    await session.rollback()
    blocker = closed_year_error(closed)              # 409, names the year(s)
    raise HTTPException(blocker.http_status, blocker.message)
```

```python
# cancellations.py:167-193 — one code path for both effects
field = "pending" if decision.balance_effect is BalanceEffect.RELEASE else "used"
current = Decimal(getattr(balance, field))
if current < days:            # never clamp silently
    rollback + 409
setattr(balance, field, current - days)
```

| Who | Status | Effect | Emails |
| --- | --- | --- | --- |
| requester or admin | `PENDING` | `pending -= days` (`RELEASE`) | `CANCELLED` to approvers |
| **admin only** | `APPROVED` | `used -= days` (`RESTORE_USED`) | `CANCELLED` + `CANCELLED_EMPLOYEE` |
| nobody | `REJECTED` / `CANCELLED` | — | 409 |
| nobody | anything in a **closed year** | — | 409 naming the year |

**Worked example.** Approved 3-day leave, `used 3`, `available 17`.

1. Employee presses Cancel → the API answers **403** ("An approved request can only be cancelled by an
   administrator.").
2. Admin cancels with a reason → `status=CANCELLED`, `cancelled_by_id`, `cancel_reason`, `used 3 → 0`,
   `available 17 → 20`, audit `CANCEL` with `old.status=APPROVED`, `new.status=CANCELLED`, and two
   outbox rows. `reconcile_balances()` still passes.

### 4.5 Year-end closing and carry-forward

**Files:** `backend/app/services/closing_rules.py` (pure), `backend/app/services/closing.py` (DB)

```python
# closing_rules.py:59-60
carried = left if left <= cap else cap        # min(unused, max_carry_forward_days)
forfeited = left - carried
```

Blockers (`closing_blockers`, **line 91**) — each one is a 409 with its own message:

| Blocker | Check |
| --- | --- |
| the year has not ended | `year_has_ended()` (**86**) |
| no adjacent next year exists | `find_next_year()` (**64**) |
| the next year is already closed | plan |
| the previous year is still open | `find_previous_year()` (**75**) |
| pending requests still hold days in this year | counted through `leave_request_allocation` |

`preview()` is **line 247**, `close_year()` is **line 301**. Closing needs the year **name typed** and
the **fingerprint** from the preview (`_fingerprint_matches`, **237**) — if a balance changed in
between, the answer is 409 "data changed, preview again".

**Worked example.** AL: 2 days left, cap 5.

| Employee | left | cap | carried | forfeited |
| --- | --- | --- | --- | --- |
| #7 | 2 | 5 | **2** | 0 |
| #8 | 9 | 5 | **5** | 4 |
| #9 (inactive) | 3 | 5 | — | skipped, counted in the summary |

Each row writes one `leave_carry_forward` log line, and the next year's balance gets
`carried_forward += carried` (an `ALLOCATED` value is **not** touched). A type with carry-forward
disabled writes nothing at all.

### 4.6 Outbox pattern and email dispatch

**File:** `backend/app/services/notifications.py:16` (`enqueue_events`) — INSERT only, no network

```python
# notifications.py:41-43
pg_insert(EmailOutbox)
    .values(...)                                    # payload = the FACTS, not the finished text
    .on_conflict_do_nothing(index_elements=["dedupe_key"])
```

Dedupe keys are stable per event: `submitted:<id>`, `approver_acted:<id>:<approval_id>`,
`approved:<id>`, `rejected:<id>`, `cancelled:<id>`, `cancelled_employee:<id>`,
`reminder:<approver_id>:<local_date>`. Running the same action twice therefore produces one mail.

Rendering and sending happen later, in `services/mailer.py`:

```python
# mailer.py:113
def send(message: Message) -> str:     # returns the backend used
# mailer.py:86   _send_smtp()  — real smtplib, STARTTLS, 15 s timeout
# mailer.py:62   _send_console()  — renders + records, sends nothing
# mailer.py:74   _send_file()   — writes a .eml
```

**Worked example.** Submit → approve → cancel of the same request:

| Moment | Outbox rows added |
| --- | --- |
| submit | `submitted:123` → approvers |
| first of two approvals | `approver_acted:123:45` → employee |
| second approval | `approved:123` → employee |
| admin cancellation | `cancelled:123`, `cancelled_employee:123` |

With the worker running, each is claimed (`worker.py:80` `SKIP LOCKED`), rendered, sent, and marked
`SENT` with an `email_attempt` row per try. With `EMAIL_BACKEND=console` the messages are rendered and
recorded but never delivered — which is why "SENT" in the log means "handled", not "in the inbox".

---

## 5. Database Integrity & Append-Only Triggers

Two tables are **evidence** and must never change after the fact: the audit log and the balance
adjustment ledger. The API has no UPDATE/DELETE endpoints for them, and the database enforces the same
rule so a careless SQL session cannot cheat.

**`audit_log`** — migration `backend/alembic/versions/116e7a2af170_audit_log.py`

```sql
-- lines 29-31 define the names; lines 59-82 create the function and both triggers (condensed)
CREATE OR REPLACE FUNCTION audit_log_block_changes() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP;   -- line 61-62
END; $$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_block_changes();      -- 71-73

CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_block_changes(); -- 78-80
```

**`leave_balance_adjustment`** — migration `7e3d308d483e_leave_balance_adjustment_ledger.py`

```sql
RAISE EXCEPTION 'leave_balance_adjustment is append-only: % is not allowed', TG_OP;   -- 64-65
CREATE TRIGGER adjustment_no_update_delete BEFORE UPDATE OR DELETE ...  -- 73-75
CREATE TRIGGER adjustment_no_truncate    BEFORE TRUNCATE ...            -- 80-82
```

Why two triggers per table: `UPDATE`/`DELETE` fire per row, `TRUNCATE` fires once per statement — a
row-level trigger would never see `TRUNCATE`.

How to prove it yourself (throw-away database only):

```sql
UPDATE audit_log SET action = 'hacked' WHERE id = 1;   -- ERROR: audit_log is append-only
DELETE FROM audit_log;                                 -- ERROR
TRUNCATE audit_log;                                    -- ERROR
SELECT tgenabled FROM pg_trigger WHERE tgname = 'audit_log_no_update_delete';  -- 'O' (enabled)
```

The application side is `backend/app/services/audit.py::record()`: it inserts **inside the caller's
transaction**, never commits, and never swallows an error — so if the audit row cannot be written, the
business action rolls back too. That is the "fail closed" choice: an unrecorded leave decision is worse
than a failed request.

A mistake in the ledger is corrected by writing the **opposite** row, never by editing history — the
same idea as a bank statement.
