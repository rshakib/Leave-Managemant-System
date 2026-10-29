# Decisions & Open Questions — Leave Management System

Every ambiguity or gap found in `leave_management_system_requirements(1).md`, with a suggested
resolution. Each item has a stable ID (D-01, D-02, …) so it can be referenced from code and PRs.

Format: **what's unclear → suggested resolution.**

- **D-01 — Filename mismatch.** The task referred to `leave_management_system_requirements.md`, but the
  file on disk is `leave_management_system_requirements(1).md`.
  → Treat `leave_management_system_requirements(1).md` as the source of truth; optionally rename it to
  drop the `(1)`.

- **D-02 — `carried_forward` vs `carried_in`.** FR-LT-3 and the NFRs say `carried_forward`, but the
  `leave_balance` table in the data model says `carried_in` (and the rollover log says `carried_days`).
  → Standardize on **`carried_forward`** everywhere (database column, API, and UI); treat the schema's
  `carried_in` as a typo.

- **D-03 — `accrual_mode` missing from the schema.** FR-LT-1 requires an accrual mode
  (`fixed` at start of year, future-ready for `monthly`), but the `leave_type` table has no such column.
  → Add an `accrual_mode` enum (`fixed` | `monthly`) defaulting to `fixed`; implement only `fixed` in v1.

- **D-04 — `day_type` naming mismatch.** The prose uses `full_day` and `half_day — first_half / second_half`,
  while the schema uses the enum `FULL_DAY` / `FIRST_HALF` / `SECOND_HALF`.
  → Use the three-value enum in code; treat "half day" as the UI grouping of the two half variants.

- **D-05 — Cross-year requests vs a single `leave_year_id`.** Cross-year requests are allowed (confirmed
  decision), but `leave_request` stores one `leave_year_id` and balances are per year.
  → Store the year of `start_date` as the request's primary year; split the chargeable days across each
  year in the range and reserve/deduct per year. Add a small join table
  `leave_request_allocation(leave_request_id, leave_year_id, days)` to keep the split traceable.

- **D-06 — Pro-rata for mid-year joiners (still open).** The requirements leave this undecided.
  → v1: the admin enters `allocated_days` manually (matches `employee_leave_type`). Optionally show a
  suggested pro-rata figure as a hint. Automatic pro-rating is deferred.

- **D-07 — Holiday "date range" vs a single `date` column.** FR-CAL-3 mentions date *or date range*, but
  the `holiday` table has a single `date`.
  → Store one `holiday` row per date; the CSV import expands ranges into individual rows.

- **D-08 — The global weekend row isn't truly unique.** `weekend_setting.employee_id` is nullable
  (`NULL` = global) and `UNIQUE(employee_id)` allows multiple `NULL`s in PostgreSQL, so several "global"
  rows are possible.
  → Add a partial unique index on non-null `employee_id`, and keep exactly one global row (enforced in
  app/seed); or move the global weekend to a separate settings table.

- **D-09 — Overlap rule scope (FR-LR-2.5).** It doesn't say which statuses count or whether overlap is by
  calendar or chargeable days.
  → Compare inclusive **calendar** date ranges against only `PENDING`/`APPROVED` requests (ignore
  `REJECTED`/`CANCELLED`). Same-date halves: allow `FIRST_HALF` + `SECOND_HALF` together; otherwise block.

- **D-10 — "Require attachment after N consecutive days".** Unclear whether N counts calendar or working days.
  → Interpret as chargeable (working) days greater than N; enforce at submission.

- **D-11 — Attachment storage.** `attachment_url` implies external storage; the requirements don't say where.
  → Save uploads to local `backend/media/` in development and store the path in `attachment_url`, behind a
  storage interface so S3 can be swapped in later.

- **D-12 — Authentication mechanism.** NFR-1 allows "password hashing … or SSO-ready JWT session".
  → v1: email/username + password (argon2) issuing a JWT access token plus a refresh token; keep the user
  lookup pluggable for future SSO. For the SPA, keep the access token in memory and the refresh token in an
  httpOnly cookie.

- **D-13 — `employee.roles` as an array vs a join table.** The schema shows `roles` as a set/array.
  → Use a normalized `employee_role` join table (indexable, easy to query), and expose `roles: string[]`
  in the API to mirror the spec.

- **D-14 — How many active leave years?** The requirements don't say.
  → Allow exactly one `is_active = true` at a time; `is_closed` is set by the year-end closing action.

- **D-15 — Year-end closing with outstanding `PENDING` requests.** Not addressed.
  → Refuse to close a year that still has pending requests; the admin must approve, reject, or cancel them first.

- **D-16 — Deactivating an employee who is mid-approval or has pending requests.** Not addressed.
  → Block deactivation while the employee is an approver on pending requests or has pending requests;
  require reassignment/cancellation first. On deactivate: revoke login, block new submissions, keep history.

- **D-17 — "CC: HR/Admin optional" recipients (FR-NOT-1).** Who exactly, and always?
  → Add notification settings: a list of HR/admin emails plus a `cc_admins_on_final` boolean, default off.

- **D-18 — Reminder job "> 2 working days" (FR-NOT-1).** "Working day" is undefined and no scheduler is named.
  → A daily scheduled job; a "working day" is not a weekend (per that approver's calendar) and not a holiday;
  remind approvers whose approval is still pending past the threshold.

- **D-19 — Email delivery mechanism (FR-NOT-2).** "Queue with retry" but no technology named.
  → A durable database `email_outbox` table plus a background worker with retry and attempt logging; use a
  console/file email backend in development. Upgrade to Redis + Celery/ARQ only if volume grows.

- **D-20 — Export format (NFR-4, "CSV/Excel").** Two formats named.
  → Implement CSV first (Python standard library); add `.xlsx` (openpyxl) later.

- **D-21 — Time zone unspecified.** Timestamps have no stated zone.
  → Store all timestamps as UTC (`timestamptz`); add an organisation `timezone` setting for display and for
  working-day calculations.

- **D-22 — `max_carry_forward_days` semantics.** It's a decimal but described as "numeric, 0 if disabled".
  → Keep `decimal(5,2)`; when `carry_forward_allowed` is false, force it to `0` and ignore it at rollover.

- **D-23 — Audit columns vs the `audit_log` table.** Both are required; scope is unclear.
  → Keep lightweight `created_at`/`updated_at`/`created_by` on tables for convenience, and additionally write
  full old/new JSON snapshots to `audit_log` for configuration edits, balance changes, and approval actions.

- **D-24 — `audit_log.entity_id` is `bigint` while other primary keys are `int`.** IDs could fail to line up.
  → Use `bigint` primary keys everywhere (or make `entity_id` a text column) so IDs match across tables.

- **D-25 — When is a `leave_balance` row created?** Not stated.
  → Create it when the leave type is assigned (`employee_leave_type` created); create the next year's row
  during year-end closing (with `carried_forward`).

- **D-26 — Half-day on a non-working day.** FR-CAL-4 implies but doesn't spell out the failure case.
  → A half-day counts `0.5` only if that single date is a working day; otherwise block submission.

- **D-27 — Out of scope for v1.** Monthly accrual, biometric/attendance integration, and overtime are not
  required. → Note them as deferred so they don't creep into the first build.

- **D-28 — Password reset / self-service.** Not specified.
  → v1: an admin creates employees and resets passwords; email-based reset is added later.

- **D-29 — `weekend_setting.effective_from` unused.** Only one weekend row per employee is defined.
  → v1 keeps a single current weekend per employee (no historical versioning); documented limitation.

- **D-30 — Self-approver prevention.** FR-APR-3 and the data model both forbid it.
  → Enforce `employee_id <> approver_id` with a database `CHECK` constraint **and** validate it at the API.

- **D-31 — Cancelling a cross-year approved request.** Not addressed.
  → Restore `used` proportionally to each year's balance (the inverse of the D-05 split).

- **D-32 — Bulk assignment overwrite behaviour.** Unclear whether bulk assignment replaces existing rows.
  → Bulk assignment by division/department **upserts** `allocated_days` and reports created/updated/skipped counts.

- **D-33 — One model or two (SQLModel), and when to drop to SQLAlchemy.** SQLModel lets one class be both the
  table and the API schema, but a `table=True` model shouldn't be returned straight from an endpoint (it
  carries database-only fields and relationships).
  → Keep one `table=True` model per entity, plus thin Pydantic-only read/create/update models where the shapes
  diverge. Use `__table_args__` / `sa_column` (raw SQLAlchemy) for `UniqueConstraint`, `CHECK`, PostgreSQL
  `ARRAY`/`JSONB`, and partial indexes. Alembic must import every table model via `models/__init__.py`.

- **D-34 — "Cannot deactivate a division/department that has active employees" (FR-ORG-3).** The
  `employee` table does not exist until Phase 3, so this rule cannot be enforced yet.
  → Deferred: the PATCH handlers carry a `TODO(Phase 3)` marker; the guard that blocks deactivation
  while active employees exist is added in Phase 3. Until then, deactivation is not blocked by
  employee counts.

- **D-35 — Deactivating a division that still has departments.** Not specified.
  → Deactivation does **not** cascade. Departments keep their own `is_active` flag and are left
  untouched. A deactivated division blocks *creating* new departments under it (HTTP 400), but existing
  departments stay readable. Bulk-deactivating a division's departments is a separate, later action.

- **D-36 — Moving a department to another division.** Not specified.
  → Not supported in v1: `division_id` is immutable through the API (it is absent from
  `DepartmentUpdate`). A department is created under one division and stays there.

- **D-37 — Case sensitivity of unique names.** The requirements say division names (and department
  names within a division) must be unique, but not whether that is case-sensitive.
  → v1 uses the database default: uniqueness is **case-sensitive** ("HR" and "hr" are different names).
  Case-insensitive matching (e.g. PostgreSQL `CITEXT`) can be added later if needed.

- **D-38 — `employee.password_hash` not created in Phase 3.** FR-EMP-1 lists the employee fields, but a
  password is an authentication concern and Phase 3 has no login.
  → Deferred: the `employee` table is created in Phase 3 **without** `password_hash`; it is added in
  Phase 4 together with authentication.

- **D-39 — D-16 deactivation checks (pending requests / pending approvals).** Those checks need the
  leave-request and approval tables, which do not exist until Phase 10.
  → Deferred: the employee PATCH handler carries a `TODO(Phase 10)`. Until then, deactivation only
  enforces the supervisor rule (D-40).

- **D-40 — Deactivating an employee who supervises other active employees.** Not specified.
  → Blocked (HTTP 409). Active employees should not report to a deactivated supervisor, so the
  supervisor links must be reassigned first. Inactive employees are ignored when counting reports.

- **D-41 — Email uniqueness and letter case.** Requirements require a unique email but do not say whether
  `A@x.com` and `a@x.com` are the same address.
  → Emails are normalised to **lowercase** on input and stored lowercase, so uniqueness is
  case-insensitive ("A@x.com" and "a@x.com" collide with HTTP 409).

- **D-42 — Shape of the `employee_role` join table (D-13).** `roles` could be a PostgreSQL array, a
  native ENUM, or a text column with a constraint.
  → Use a join table with a **composite primary key `(employee_id, role)`** (the PK is what makes a role
  unique per employee) and store `role` as `VARCHAR(20)` guarded by a `CHECK` constraint rather than a
  native PostgreSQL ENUM, so migrations stay simple if roles are added later.

- **D-12 (amendment, Phase 4) — Refresh tokens and httpOnly cookies deferred.** The original D-12 described
  an access token **plus** a refresh token held in an httpOnly cookie.
  → Not built yet. Phase 4 ships a **single access token** only: no `/auth/refresh`, no `/auth/logout`, no
  cookies. Logout is the frontend deleting the token. Refresh tokens and the httpOnly cookie are deferred
  to **Phase 16**.

- **D-43 — argon2-cffi instead of passlib.** `passlib` is unmaintained and breaks on recent Python versions.
  → Use `argon2-cffi` directly (`backend/app/core/security.py`). `TECH_STACK.md` updated.

- **D-44 — What goes inside the JWT.** Putting roles (or names) in the token would keep working after a role
  change or a deactivation.
  → The payload carries **only** `sub` (employee id), `type` ("access") and `exp`. The employee row and their
  roles are loaded from the database on every request, so deactivation and role changes take effect
  immediately — at the cost of one extra query per request.

- **D-45 — Logout and token lifetime.** There is no server-side session store.
  → Tokens are stateless and cannot be revoked before they expire (default `ACCESS_TOKEN_MINUTES=480`, i.e.
  8 hours). Logout is a client-side action (delete the token). Short-lived tokens + a refresh flow are
  Phase 16 (see the D-12 amendment).

- **D-46 — RBAC rules for the Phase 2–3 endpoints.** Not previously specified.
  → **Admin only:** `POST`/`PATCH` on `/divisions`, `/departments`, `/employees`, and `GET /employees` (list
  and one). **Any logged-in user:** `GET /divisions`, `GET /departments`. `POST /auth/login` is public;
  `GET /auth/me` needs any valid token. Unauthenticated → 401; authenticated but wrong role → 403.

- **D-47 — Seeds created by `seed_admin`.** The command needs a division and department for the first
  employee, but none may exist yet.
  → If no division exists it creates **"Head Office"**; if that division has no department it creates
  **"Administration"**. The admin gets a generated employee code (`ADMIN`, then `ADMIN-2`, …) and roles
  `["ADMIN", "EMPLOYEE"]`. It refuses to run when an active ADMIN already exists unless `--force` is given.

- **D-48 — Frontend language: JavaScript (JSX), not TypeScript.** TECH_STACK originally chose TypeScript.
  → Superseded: the frontend is plain **JavaScript + JSX** (Vite `template react`). `TECH_STACK.md` updated.
  There is no `tsconfig` and no `.ts`/`.tsx` file. TypeScript can be revisited later if wanted.

- **D-49 — Data fetching: Axios + plain React hooks for now.** TECH_STACK listed TanStack Query for caching.
  → Deferred. Phase 5 uses a single Axios instance (`src/api/client.js`) plus `useState`/`useEffect` in each
  page. TanStack Query can be added later without changing the API layer.

- **D-50 — CORS is configured from `CORS_ORIGINS`.** The browser app runs on a different origin than the API,
  so the API must allow it. → `backend/.env` `CORS_ORIGINS` (comma-separated, default
  `http://localhost:5173,http://127.0.0.1:5173`). Explicit origins only, never `*`. Recorded here because
  the wildcard-origin question comes up whenever CORS errors are hit.

- **D-51 — Two strict oxlint rules are disabled (`only-export-components`, `set-state-in-effect`).**
  Phase 5 uses the standard "fetch on mount" pattern (`useEffect` + `useState`) and exports the
  `useAuth` hook from the same file as its provider — both are what the phase asked for.
  → The two rules are turned off in `frontend/.oxlintrc.json`: the first is a fast-refresh nicety,
  the second is a React-Compiler-era rule that discourages exactly the data-loading pattern we use
  while TanStack Query is deferred (D-49). `react/rules-of-hooks` stays an error.

- **D-52 — Only one active leave year, changed only via `POST /leave-years/{id}/activate`.** Activation
  deactivates any other active year and activates the target **in one transaction**.
  → There is no "deactivate" endpoint, and `PATCH` rejects `is_active`/`is_closed` (the update model uses
  `extra="forbid"`, so sending them returns a clear 422 rather than being silently ignored). This keeps
  "exactly one active year" (D-14) simple and avoids a state with zero active years. The partial unique
  index `uq_leave_year_single_active` is the database-level guarantee.

- **D-53 — New leave years are created inactive, and `is_closed` is never editable through the API.**
  → Creating a year just records its dates; you activate it explicitly. Closing a year belongs to the
  Phase 15 year-end process, which is the only thing allowed to set `is_closed`.

- **D-54 — Leave-year overlap check.** Not specified by the requirements.
  → Two years may not overlap. The check uses **inclusive** date ranges (`a.start <= b.end AND
  a.end >= b.start`) against every existing year regardless of status, and returns 409 naming the
  clashing year. Editing a year excludes itself from the check.

- **D-55 — Two kinds of "bad input" get different status codes.** Field-level problems (negative quota,
  negative carry-forward, overly long/short text, wrong types) → **422** from Pydantic. Domain rules
  (monthly accrual, overlapping years, duplicate code/name, editing a closed year, activating a closed
  year) → **400** or **409** raised by the router with a human-readable message.

- **D-56 — Deactivating a leave type is allowed in Phase 6; blocking comes in Phase 7.**
  → `TODO(Phase 7)` marks the spot. Reasoning: employee assignment/balances do not exist yet, so there is
  nothing to block on and the rule could not be tested; a deactivated type simply stops being assignable
  once Phase 7 adds that check. Deactivation never deletes history.

- **D-57 — `accrual_mode` is stored as `VARCHAR` but only `fixed` is accepted by the API.** The database
  `CHECK` still permits `'monthly'` so a later phase can enable monthly accrual without a migration; the
  API rejects it with 400 and a clear message (concretising D-03).

- **D-58 — Leave-type codes are trimmed and uppercased before the uniqueness check.** `" al "` and `"AL"`
  are the same code, so the second one returns 409. Names keep their given case (uniqueness is
  case-sensitive, per D-37).

- **D-59 — Departments and Employees admin screens are frontend-only (no backend change).** Added as a
  UI task on top of the Phase 2–3 APIs. → The departments edit modal shows the division **read-only**,
  because D-36 already makes `division_id` immutable through the API, so the UI must not imply it can
  be changed.

- **D-60 — The employee form's department dropdown is *dependent* on the division dropdown.** It lists
  only departments of the chosen division, stays disabled until a division is picked, and is **cleared**
  whenever the division changes. → Without this the form could hold a (division, department) pair that
  belongs to different divisions, which the API rejects with 400 (see `_validate_placement`). Clearing
  avoids sending a stale, now-invalid department.

- **D-61 — The employee form never displays or logs a password.** `password` is a write-only field: on
  create it is required (min 8), on edit it is optional and sent **only** when the admin typed something
  ("New password (leave empty to keep the current one)"). `employee_code` is read-only after creation
  because it identifies the employee. → `EmployeeRead` deliberately has no password field, so the browser
  never receives one to show in the first place.

- **D-62 — 422 validation errors are flattened for display.** FastAPI returns validation errors as a
  *list* of objects; `errorMessage()` in `src/api/client.js` turns them into
  `"field: message"` entries joined with `"; "` instead of rendering `[object Object]`. Single-string
  `detail` values (400/409) are shown as-is.

- **D-63 — Exactly one small shared component was extracted: `StatusBadge`.** It renders the
  Active/Inactive pill used by the Departments and Employees tables. → No larger abstraction (no generic
  table/modal/form wrapper) was introduced, to keep each page readable and independent.

- **D-64 — No DELETE endpoint for assignments or balances.** Removing an assignment would silently destroy
  the balance history that leave requests (Phase 10) and year-end closing (Phase 15) rely on.
  → Adjustments are made by re-allocating (`allocated_days`); an explicit admin "balance adjustment"
  action can be added in Phase 16 if needed. History is never deleted (FR-LT-3, D-23).

- **D-65 — `available` is computed, never stored.** `available = allocated + carried_forward - used - pending`
  (D-02/FR-LT-3). → The four stored numbers each have a `>= 0` CHECK, plus a CHECK on the formula itself
  (`ck_leave_balance_available_not_negative`), so a negative available balance is impossible **at the
  database level**, not just in the API.

- **D-66 — How the assignment UPSERT stays safe under concurrency.** The API reads the row, then inserts
  or updates it. The real guard is the `UNIQUE (employee_id, leave_type_id, leave_year_id)` constraint: if
  two requests race, both may see "no row" and both INSERT — only one wins, the loser gets a 409 telling it
  to retry, and the retry takes the UPDATE path. → A later simplification could use PostgreSQL
  `INSERT ... ON CONFLICT (…) DO UPDATE`, which never conflicts; the current version was kept because its
  behaviour (and the created/updated counts in the bulk endpoint) are easier to follow.

- **D-67 — Bulk assignment is all-or-nothing for writes, but "skips" business-rule failures.** Everything
  runs in ONE transaction; a database-level conflict rolls the whole thing back with 409. Rows that fail a
  *business* rule (inactive employee, inactive leave type, allocation that would make the balance negative)
  are **skipped and reported** with a reason instead of failing the run (D-32).

- **D-68 — D-56 implemented, then deliberately softened.** The guard blocks deactivating a leave type that is
  still allocated (> 0 days) in a leave year that is **not closed** (409 with an actionable message).
  → The strict reading of D-56 ("any assignment blocks") was rejected because assignments are never deleted
  (D-64), which would make any leave type that was ever used permanently undeactivatable. Allocations in
  **closed** years are history and never block. The escape hatch is to set the allocation to 0 days, which
  the existing upsert endpoint already allows. Recorded as the "closest sensible version" of D-56.

- **D-69 — `/leave-balances/me` can only ever return the caller's own rows.** The query is hard-filtered by
  the current employee id; the optional `leave_year_id` changes the year only, never whose rows are
  returned.

- **D-70 — Missing active year: read returns empty, write returns 409.** `GET /leave-balances` (and `/me`)
  return `[]` when no year is active, so the UI can show a friendly empty state. The assignment endpoints
  return 409 with a clear message, because writing a balance genuinely requires a leave year.

- **D-71 — Only `PUBLIC` and `COMPANY` holidays are subtracted; `OPTIONAL` is informational.**
  The requirements list an `OPTIONAL` holiday type but never say whether it reduces leave.
  → `OPTIONAL` holidays are returned in the preview (so the UI can show them) but are **not** subtracted
  from chargeable days; only `PUBLIC` and `COMPANY` are. This keeps "optional" meaning "you may choose to
  take it", which is the usual reading.

- **D-72 — The day-calculation engine is a pure function in `services/day_calc.py`.** It takes a weekend
  set and a holiday set and returns the chargeable days plus a per-day list; it touches no database, no
  HTTP and no clock. → The same rules serve the calendar preview now and the Phase-10 submission
  validation later, and they are covered by unit tests that need no database. The per-day list is kept
  so the Phase-10 cross-year split (D-05) can reuse it.

- **D-73 — CSV holiday import is all-or-nothing.** Every row is validated first (date format, type,
  division/department names, duplicates, "date inside the leave year"); if **any** row fails, nothing is
  imported and the response lists the failing row numbers with messages.
  → A half-imported holiday list is worse than none, because the admin cannot tell what actually landed.
  The file must be UTF-8 (a BOM is tolerated) and is limited to 1 MB / 1000 rows.

- **D-74 — Weekend days are stored in a PostgreSQL `ARRAY`, de-duplicated in the API.** The DB CHECK can
  enforce "at least one day" and "values are 0..6", but a CHECK cannot look for duplicates inside an array
  (no sub-queries allowed). → `WeekendSettingWrite` de-duplicates and sorts, and the CHECK is the backstop.

- **D-75 — The FLAT `holiday.date` lookup ignores the leave year.** `services/calendar.py` finds holidays by
  **date range**, not by `leave_year_id`, so a request that spans two leave years still sees every holiday
  in its window (needed for D-05 cross-year requests).

- **D-76 — Missing global weekend → 409 on the calculation, 404 on the read.** `GET /weekends/global`
  returns 404 when nothing is configured (the UI treats that as "nothing ticked yet"), while the calendar
  preview service raises 409 "Global weekend is not configured" because a calculation genuinely cannot
  happen without it.

- **D-77 — `PUT /employees/{id}/approvers` replaces the whole active set.** The body is the complete list;
  it is idempotent (sending the same list twice changes nothing). An empty list is allowed — the employee
  then cannot submit leave (FR-LR-2.6, enforced in Phase 10).
  → A PUT is used instead of add/remove endpoints so the admin always sends the intended final state; that
  removes the "two admins each adding one, both thinking the other is replaced" class of bug.

- **D-78 (SUPERSEDED by D-151) — Approvers automatically receive the APPROVER role; roles are never removed automatically.**
  Being an approver is the meaningful fact; the role is bookkeeping the authorisation layer reads.
  → `set_approvers` and `ensure_supervisor_is_approver` add the `APPROVER` role when missing. Removing the
  role is a deliberate admin action, and it is blocked while the person still approves for someone (D-82).

- **D-79 — Approver rows are soft-deactivated, never deleted.** Removing an approver sets `is_active=false`;
  adding them again reactivates the SAME row (the unique constraint on `(employee_id, approver_id)` makes
  that possible and prevents duplicates). → History is preserved and ids stay stable for later approvals.

- **D-80 (amended by D-151) — The supervisor is only added as an approver when the supervisor actually CHANGES.** The rule
  runs on creation (when a supervisor is given) and on a PATCH whose `supervisor_id` differs from the
  current value. → A PATCH that does not touch the supervisor must not re-add a supervisor an admin
  deliberately removed. Nothing is ever auto-removed.

- **D-81 — Deactivating an employee who is an active approver for active employees is blocked (409).**
  → The message names how many employees are affected and tells the admin to reassign first. Being an
  employee who merely HAS approvers is fine — that never blocks deactivation.

- **D-82 — Removing the APPROVER role while the employee still approves for someone is blocked (409).**
  Otherwise the role and the approver rows would silently disagree. → Reassign the approvers first.

- **D-83 — `GET /approver-assignments` avoids the N+1 query problem.** It runs a fixed 3 queries
  (active employees, all their active approver rows, then the approver employees) and assembles the rows in
  Python. → Querying approvers per employee would be 1 + N queries; with a few hundred employees that is
  hundreds of round-trips per page load.

- **D-84 — `GET /approvers/me` takes no id.** The employee is taken from the token, so it is impossible to
  read somebody else's approvers through it. Admins use `/approver-assignments` instead.

- **D-85 — Past dates are allowed.** The requirements never say a request must be in the future.
  → `start_date` may be in the past (useful for back-dated leave an admin approves). Only the shape rules
  (order, half-day) apply. Could be tightened later with a configuration flag.

- **D-86 — Chargeable days are always computed by the server.** `POST /leave-requests` takes no day count
  from the client; it re-uses `evaluate()` (the same function behind `/leave-requests/check`), so the
  preview and the stored value can never disagree.

- **D-87 — Submissions are serialised per employee with `SELECT … FOR UPDATE`.** The service locks the
  employee row, then that employee's balance rows for the touched years in ascending `leave_year_id` order,
  then re-runs `evaluate()` under those locks.
  → Two simultaneous submissions by the same employee become one at a time, so the balance check and the
  `pending` increment cannot interleave. A fixed locking order stops two different requests deadlocking on
  the same two balance rows. The `ck_leave_balance_available_not_negative` CHECK is the last line of
  defence (a violation becomes 409).

- **D-88 — Approvers are snapshotted at submission time.** `leave_request_approval` rows are created from
  the approvers that exist *right now*. Changing an employee's approvers afterwards does not change an
  already-submitted request. → The in-flight question ("what happens to pending approvals when an approver
  is removed/deactivated") is left for Phase 11.

- **D-89 — 404, not 403, for someone else's request.** `GET /leave-requests/{id}` and its attachment are
  visible to the owner, an ADMIN, or an approver with a row on THAT request; everyone else gets 404, so the
  API does not leak that a request exists.

- **D-90 — Uploads are validated by extension AND magic bytes, and given a random name.** The stored
  filename is a UUID; the original filename is never part of a path (path traversal). The download header
  uses a generated name (`leave-request-<id>.<ext>`) rather than storing the user-supplied one — it is
  untrusted text and no column was specified for it. Allowed: pdf/png/jpg/jpeg; 5 MB cap → 413.

- **D-91 — If the database write fails after the file was saved, the file is deleted.** The router wraps
  `submit()` and calls `storage.delete()` on any exception, so a rejected request never leaves an orphan
  file in `backend/media/`.

- **D-92 — `/leave-requests/me` accepts `?status=` (via a query alias) and caps `limit` at 100.** Newest
  first (`submitted_at` desc, `id` desc as a tiebreaker).

- **D-93 — Removing an approver who still owes a decision is blocked (409).** If an approver has a
  PENDING approval on that employee's PENDING request, `PUT /employees/{id}/approvers` refuses the change and
  tells the admin to ask the employee to cancel the request or to wait for the decision.
  → Otherwise the request could never reach "every approver approved" (the removed row would sit PENDING
  forever). This closes the TODO(Phase 11) from D-84.

- **D-94 — Deactivating an employee with unfinished work is blocked (409).** Counted separately in the
  message: PENDING leave requests they submitted, and PENDING approvals they still have to decide.
  → A deactivated approver could not log in to decide, so their pending approvals would stall the request.
  This closes the D-16 / D-39 deferral from Phase 3.

- **D-95 — Removing the APPROVER role is also blocked while PENDING approvals exist.** This extends the
  existing D-82 guard (which only counted active approver assignments).
  → The role and the outstanding decisions must not disagree.

- **D-96 — Lock order: the request row first, then balance rows by `leave_year_id`.** `services/approvals.py`
  documents this at the top of the file and `submit()` uses the same order. → Two transactions always take
  locks in the same global order, so they cannot each hold what the other needs (no deadlock); and every
  approver of the SAME request serialises on the request lock, so two simultaneous decisions cannot both
  change the balances.

- **D-97 — The requester gets 403 (not a hidden 404) when they try to decide their own request.** They
  already know the request exists, so nothing is leaked. A stranger without an approval row still gets the
  same 404 as a missing request (no existence leak).

- **D-98 — On rejection, only PENDING approvals become SKIPPED; already-APPROVED rows stay APPROVED.**
  → The history stays truthful about who had agreed before the rejection arrived.

- **D-99 — `my_pending_approval` is computed on the server** (true only for an assigned approver whose row
  is PENDING while the request is PENDING). The client never works it out from the role.

- **D-100 — `reconcile_balances()` is a read-only invariant check, not an endpoint.** It recomputes
  expected `pending`/`used` from the request allocations and compares them with `leave_balance`; the test
  suite calls it after every scenario. Exposing it as an API would need admin auth and a clear UI, which
  is not part of this phase.

- **D-101 — A cancellation is recorded, never deleted.** A cancelled request keeps its row, its allocations
  and its approvals; `cancelled_at`, `cancelled_by_id` and `cancel_reason` say who/when/why.
  → Auditing and history need the request to stay; "cancel" is a state, not a delete (D-64 style).

- **D-102 — `final_decided_at` is not touched by a cancellation.** It records when the APPROVAL decision
  was reached, which remains a true fact afterwards. The cancellation has its own timestamp.

- **D-103 — The database keeps `cancelled_at` and `cancelled_by_id` together.** A CHECK rejects a row with
  only one of them set, so a half-written cancellation is impossible.

- **D-104 (superseded by D-153) — An APPROVED request that touches a CLOSED leave year cannot be cancelled automatically.**
  The days would have to come out of a closed year whose carry-forward may already have been computed.
  → 409 with a clear message; nothing is changed. An administrator must adjust the balance manually
  (the balance-editing screen is not built yet).

- **D-105 (superseded by D-153) — Restoring an APPROVED request uses the exact allocation rows, not a proportional estimate.**
  (Amends D-31.) A cross-year request restored 3 + 1 days puts exactly 3 back into 2098 and 1 into 2099,
  because those are the rows the submission created. A proportional split could drift by rounding.

- **D-106 (superseded by D-153) — An administrator may cancel their own request.** The admin power is about the action (undoing an
  APPROVED request, giving a reason), not about whose request it is. Their reason is still required.

- **D-107 — `can_cancel` is computed on the server** by the same pure rules the API enforces
  (`PENDING` + requester/admin, or `APPROVED` + admin), so the button can never appear where the call would
  be refused.

- **D-108 — `GET /leave-requests` (ADMIN) is a minimal list.** It supports status/employee/division/leave-year
  filters and paging (max 100), and runs 3 fixed queries. Exports, date-range filters and reporting belong
  to Phase 14.

- **D-109 — A cancelled request no longer blocks overlap.** `evaluate()` only looks at PENDING and APPROVED
  requests, so the same dates can be requested again after cancelling — and `reconcile_balances()` ignores
  CANCELLED requests entirely (they contribute nothing to expected pending or used).

- **D-110 — Emails go through a transactional outbox, never a direct send.** `enqueue_events()` only
  INSERTs rows, inside the caller's transaction, before its single commit. Rendering and sending happen
  in the worker. → A leave action can never be rolled back (or blocked) by a mail problem, and a committed
  action always has its emails queued ("no email without the leave, no leave without the email").

- **D-111 — The outbox stores the FACTS, not the finished email.** `payload` (JSONB) holds names, dates,
  days and balances as they were at that moment. → Templates can be redesigned later without rewriting
  history, and the log shows exactly what was known when the mail was queued. The subject/body are built
  at send time.

- **D-112 — `dedupe_key` + `ON CONFLICT DO NOTHING` make enqueueing idempotent.** A retried request, a
  double submit or the 15-minute reminder tick can run any number of times and still produce one email.

- **D-113 — The worker claims rows with `SELECT … FOR UPDATE SKIP LOCKED`.** Each worker locks only the
  rows it is about to send and skips rows other workers hold, so two workers never send the same email and
  neither waits for the other. A row left in `SENDING` for more than 10 minutes (crash) is returned to
  `PENDING`.

- **D-114 — Reminders use the organisation's timezone and the approver's own calendar.** "Today" comes
  from `ORG_TIMEZONE` (a UTC server clock would fire reminders on the wrong local day), and the waiting
  count uses that approver's weekend (override or global) and the holidays that apply to them. One digest
  per approver per local date.

- **D-115 — An admin cancellation sends an extra email to the employee.** FR-NOT-1 only lists "cancelled →
  approvers"; when an administrator cancelled somebody else's leave, the employee is also told, with the
  admin's reason. The requester cancelling their own leave does not email themselves.

- **D-116 — The actor is never Cc'd on their own action.** The one exception is the extra employee email
  in D-115 (the admin cancelled their own request), and the required Cc on the SUBMITTED email.

- **D-117 — `OPTIONAL` holidays do not affect reminders either.** Consistent with D-71: only PUBLIC and
  COMPANY holidays shorten the working-day count.

- **D-118 — Retry schedule 60s, 5m, 30m, 2h, 12h, then FAILED.** `EMAIL_MAX_ATTEMPTS` (default 5) decides
  when to give up. A FAILED row can be retried by an admin: it goes back to PENDING with `attempts = 0`,
  and the old `email_attempt` rows stay so the history is not lost.

- **D-119 — File-backend names are random UUIDs.** `.eml` files are a development aid, written to
  `backend/outbox_dev/` (git-ignored); the name is never derived from user input.

- **D-120 — Production SMTP and outbox cleanup are deferred.** TODO(Phase 16): a real provider, delivery
  monitoring, and a job that prunes old SENT rows.

- **D-121 — The "reason" column is opt-in (`include_reason`, default false).** Reasons are free text that
  can hold private information (illness, family matters). Reports are for counting days, not for reading
  people's notes. → The column is absent from both JSON and CSV unless the admin ticks the box.

- **D-122 — `date_from`/`date_to` on the history report means OVERLAP, not containment.**
  `end_date >= date_from AND start_date <= date_to`. A request that touches the range by a single day is
  included. → Containment would silently hide leave that is half inside the window the admin is asking
  about, which is exactly the leave that matters for a period report. Recorded because the requirements
  never define it.

- **D-123 — Exports are capped by `EXPORT_MAX_ROWS` (default 50000), checked BEFORE streaming.** The
  count is run first; over the cap the API returns **400** telling the admin to narrow the filters, so a
  huge file is never half-downloaded. → A silent truncation would look like complete data.

- **D-124 — CSV starts with a UTF-8 BOM.** Without it Excel guesses the encoding and shows Bengali as
  mojibake. A CSV opens in Excel directly, so `.xlsx` stays deferred (D-20) until someone needs real
  formatting or multiple sheets.

- **D-125 — Reports are ADMIN only in v1.** FR/NFR-4 gives reporting to the admin role; there is no
  per-manager or per-division reporting yet, and no employee-facing report. → One clear rule (401 without
  a token, 403 as a non-admin) instead of a half-built permission model.

- **D-126 — `csv_safe()` only ever touches TEXT cells.** A value starting with `=`, `+`, `-`, `@`, a tab
  or a carriage return (after leading spaces) gets a leading apostrophe so a spreadsheet treats it as
  text, not a formula ("CSV injection"). Numbers, decimals, dates and `None` pass through untouched — so
  the number `-5` stays `-5` while the text `"-5"` is neutralised.

- **D-127 — One shared filter builder per report is the single source of truth.** The JSON endpoint and
  the CSV endpoint call the same functions, so a filter can never work in one and not the other. The JSON
  path runs exactly **3 queries** (rows, total count, summary) no matter how many rows come back; the
  CSV path runs 1 count query plus 1 query per 1000-row batch. The approvals text is aggregated in the
  database with `string_agg`, so it costs no extra query per row (no N+1).

- **D-128 — CSV timestamps use the organisation timezone (`ORG_TIMEZONE`, D-21); dates stay plain
  `YYYY-MM-DD`.** An instant like `2026-10-25T20:00Z` is shown as `2026-10-26 02:00:00+06:00` for an
  admin in Dhaka, because that is the day the event happened locally. A leave *date* is a calendar date
  and must not be shifted.

- **D-129 — A blank result still exports a header row.** An empty file with no header looks like a broken
  download; the header tells the admin the export ran and the filters matched nothing.

- **D-130 — Response models do not re-validate stored data.** `EmployeeRead.email` is a plain `str`, while
  the `Create`/`Update` models keep `EmailStr`. → Email validation belongs at the INPUT boundary.
  Re-validating on the way out turned an already-stored address on a reserved domain (found while testing
  with `@example.invalid`) into a **500** on a plain `PATCH /employees/{id}`. Reads must never fail
  because data that is already in the database no longer passes today's rule.

- **D-131 — The `leave_year` row is the gate for every balance writer (Phase 15 locking).** A writer takes
  `SELECT … FOR SHARE` on the leave-year rows it will touch, THEN re-checks `is_closed`; closing takes
  `SELECT … FOR UPDATE` on the same rows. Shared locks let ordinary work run in parallel; the exclusive lock
  only conflicts with a closing. Leaves are always locked in ascending id order and a closing never locks an
  employee row, so no lock cycle (deadlock) is possible.

- **D-132 — Pending requests are counted through `leave_request_allocation`, not `leave_request.leave_year_id`.**
  A cross-year request stores only its start year, but it holds days in both years. Counting through the
  allocation rows catches every request that still owes days to the year being closed (FR-LR-4 + D-05).

- **D-133 — Closing is irreversible and needs two confirmations.** There is no undo and no "close early"
  switch: a year can only be closed after its last day (D-15). The admin must type the year name exactly
  (400 if wrong) **and** the request must carry the fingerprint from the preview (409 "data changed, preview
  again") — an optimistic concurrency check, so a balance edited between preview and close cannot slip past
  unseen.

- **D-134 — No log row when nothing happens.** A leave type with carry-forward disabled writes NO row at all
  (D-22), and a row whose remaining days are 0 (or whose carried and forfeited days are both 0) writes
  nothing either — the log records transfers, not attendance.

- **D-135 — The next year's balance is created with `allocated = 0` and WITHOUT an `employee_leave_type`
  row, and `carried_forward` is ADDED, never overwritten.** The carried days are a balance fact, not an
  entitlement: an admin still decides the next year's allocation. Assigning that year later (Phase 7 upsert)
  only touches `allocated`, so the carried days survive — proven by a test.

- **D-136 (amended in 16A) — Closing moves the active flag in TWO statements, in this order.** Clear every
  `is_active` first, then set it on the next year. The original "one multi-row UPDATE" idea was wrong:
  PostgreSQL may touch the rows in any order, so the statement can briefly hold two active rows and violate
  the `uq_leave_year_single_active` index — the Phase 16A audit test activated a year before closing it and
  hit exactly that. Two statements leave a moment with **no** active year, which nothing forbids.

- **D-137 — Blockers decide the HTTP status.** Every blocker is a 409 (closed / not ended / no adjacent next
  year / next year closed / previous year open / pending requests); a wrong confirmation name is a 400.
  Warnings (employees with carried days but no next-year assignment) are returned but never block.

- **D-138 — Inactive employees are skipped and counted.** Their remaining days are not carried forward (they
  cannot take leave any more) and the summary reports how many were skipped, so nothing disappears silently.

- **D-139 — `approvals.act()` and `cancellations.cancel()` deliberately do NOT take the shared lock.** A
  closed year can never contain a PENDING request — closing is blocked while one exists (D-132) and new
  submissions into a closed year are refused (D-131) — and cancelling an APPROVED request that touches a
  closed year is already refused (D-104). A test asserts both refusals still hold after a closing.

- **D-140 — The log is the proof, and its constraints make a second run impossible.** One row per
  (employee, leave type, from-year) — unique — with `remaining_at_close = carried_days + forfeited_days`
  enforced by a CHECK, so "closing twice" cannot carry the same days twice even if an application bug tried.

- **D-141 — The audit trail FAILS CLOSED — the opposite of the email outbox.** `audit.record()` inserts
  inside the caller's transaction, never commits and never swallows an error, so if the audit row cannot be
  written the whole business action rolls back (HTTP 500, nothing changed). The reasoning is in
  `services/audit.py`: a leave decision without its email is a delayed notification, which is annoying but
  recoverable; a leave decision without its audit row is an **unaccountable** change. Emails are a
  notification (D-110); the audit row is part of the fact.

- **D-142 — One row per business ACTION, not per field.** `PATCH /employees/{id}` can legitimately be three
  actions at once, so it may write up to three rows: `UPDATE` (the changed profile fields, as a diff),
  `ROLES_CHANGED` (old and new role lists) and `PASSWORD_RESET`. Each row is readable on its own.

- **D-143 — `AuditLog` deliberately does NOT inherit `BaseModel`.** The shared base adds `updated_at` and
  `created_by`; an audit row is written once and never changes (a trigger enforces it), and `created_by`
  would just duplicate `actor_id`. The table therefore carries only `created_at`.

- **D-144 — The year-end closing writes ONE summary row.** Counts, totals, skipped employees and the new
  active year go in that single row; the per-employee detail already lives in `leave_carry_forward`, and
  copying it into the audit log would be a second, drift-prone copy.

- **D-145 — `entity_id` is nullable.** Some audited events are not about one row: a CSV holiday import, a
  bulk assignment, a report export. Their details live in the JSON values, so `entity_id` stays NULL rather
  than pointing at an arbitrary member of the set.

- **D-146 — Report exports are audited, and the row is committed BEFORE streaming starts.** Personal data
  is about to leave the system; if the client aborts the download halfway, the record that an export
  happened already exists. `reports.py` documents this at the top.

- **D-147 — The audit API is READ-ONLY and the table is append-only.** Only `GET /admin/audit-log` and
  `GET /admin/audit-log/{id}` exist — no create, update or delete endpoint — and a database trigger raises
  for `UPDATE`, `DELETE` and `TRUNCATE`. The trigger is the real guarantee (it also blocks a careless SQL
  session); the missing endpoints are the polite version of the same rule.

- **D-148 — System actions are NOT audited.** The email worker, the pending-approval reminder job and
  `POST /admin/emails/{id}/retry` change no business data and have no human actor; their history is already
  on the email row and in `email_attempt`. Recorded in `worker.py` and in `audit_registry.py`.

- **D-149 — What is not audited, and why.** Read-only calls (there is nothing to record), **failed**
  actions (they are rolled back, so nothing changed — a 409 leaves no row), signing in (Phase 16C), and
  any change made outside the API (for example directly in SQL, which the trigger cannot see). Retention is
  **manual**: nothing deletes old audit rows yet (Phase 16D).

- **D-150 — Secrets never reach the audit log, twice over.** `redact()` replaces the value of any key whose
  name contains password/passwd/secret/token/authorization/jwt/api_key/hash with `"[REDACTED]"` (the key
  stays, so the change is still visible), and a password reset is recorded as `PASSWORD_RESET` with **no
  old/new values at all** — even an argon2 hash is secret material.

- **D-151 — Only someone who ALREADY holds the APPROVER role may be assigned as an approver, and the role
  is never granted automatically.** This reverses D-78. `PUT /employees/{id}/approvers` now rejects any
  candidate without the role (400, naming the employee codes), the Approvers page only lists role holders,
  and the role is granted deliberately on the Employees page (Edit → Roles). Reasons: "approver" becomes a
  real permission instead of a side effect of being picked, the role and the approver rows can no longer
  drift apart, and an admin cannot accidentally create an approver. Consequence: an admin must grant the
  role first, then assign. **Supervisor rule (FR-APR-2, option A):** a supervisor is pre-populated as an
  approver only when the supervisor already holds APPROVER; otherwise nothing happens and the admin adds
  them after granting the role. Existing data was verified: the only approver row (Shakil → ADMIN) has a
  role holder.

- **D-152 — Every employee ALWAYS holds the EMPLOYEE role; ADMIN and APPROVER are extras.** `EMPLOYEE` is
  the base permission (submit and cancel your own leave, see your own balances), so it can never be removed:
  `with_employee_role()` adds it on create and on every role update, the Employees form shows it ticked and
  **locked**, and an empty role list simply means "a plain employee". Consequence: a person cannot be an
  admin or an approver *without* also being able to request their own leave — which is what the requirements
  mean by "a user may hold multiple roles". Enforced in the API (create + update); existing rows were
  verified (ADMIN has ADMIN+APPROVER+EMPLOYEE, Shakil has EMPLOYEE).

- **D-153 — A request can be cancelled ONLY while it is PENDING; an APPROVED request can never be
  cancelled, by anybody — not even an administrator.** This supersedes the "admin may cancel an approved
  request" part of FR-LR-5 and of D-101…D-107: `BalanceEffect.RESTORE_USED` is deleted, `can_cancel()` is
  false for every status except PENDING, and the detail page hides the Cancel button accordingly. Reason:
  approval is final; silently moving days out of `used` again was the only path that rewrote history.
  **This DIVERGES from the requirements file** (§3.6 FR-LR-5 and the "Post-approval cancellation" answer in
  §7), which allowed an admin to cancel an approved request — flagged here as the standing rules require.
  Consequence: a wrongly approved request can no longer be undone at all; the only repair is a manual
  balance adjustment (Phase 16B). The closed-year refusal in D-104 can never be reached from a
  cancellation any more, and the closed-year cancellation email path is unreachable too.

- **D-154 — "Live" screens without a new dependency: a change signal + focus refresh + a slow poll.**
  Every successful non-GET request calls `notifyDataChanged()`, which fires a window event **and** a
  `BroadcastChannel` message. `useAutoRefresh`, mounted on every data screen (and on the sidebar approvals
  badge), re-runs that screen's loader when: (a) anything in the app changes — same tab or another tab,
  (b) the tab becomes visible / regains focus, (c) every 15 s as a safety net. Polling pauses while the tab
  is hidden, and GETs never trigger the signal, so there is no refresh loop. Trade-off: a change made by
  **another user on another device** appears within ≤15 s (or instantly when you return to the tab), not
  sub-second. True push (SSE with Postgres `LISTEN/NOTIFY`, or WebSockets) is deliberately deferred: it
  needs one streaming connection per tab plus a dedicated DB connection, which is a lot of machinery for a
  leave app — the hooks are written so the transport can be swapped in one place later.

- **D-155 — An adjustment is an append-only LEDGER row, never an edit.** `leave_balance_adjustment` records
  the field, the delta, the value before/after, who and why; a database trigger refuses UPDATE/DELETE/
  TRUNCATE. A mistake is corrected by writing the **opposite** adjustment (a compensating entry), so history
  stays truthful (the same idea as `audit_log`, D-147). It does not inherit `BaseModel`: written once, no
  `updated_at`.

- **D-156 — The invariants now include adjustments.** `reconcile_balances()` expects
  `used = Σ approved request days + Σ USED adjustments`, and `reconcile_carry_forward()` expects
  `carried_forward = Σ carry-log days + Σ CARRIED_FORWARD adjustments`. Without this a legitimate manual
  correction would look like corruption.

- **D-157 — Only ALLOCATED, CARRIED_FORWARD and USED can be adjusted; PENDING never.** PENDING belongs to the
  requests waiting for approval — the honest way to change it is to approve, reject or cancel a request.
  Allowing it by hand would desynchronise the balance from the requests and break D-156.

- **D-158 — Closed years, inactive employees and inactive leave types ARE adjustable.** The whole point is
  repair. The year is still locked SHARED (a closing takes it EXCLUSIVELY), so the two can never interleave.
  But the adjustment does **not** recompute the next year's carry-forward — it returns a warning instead,
  and the admin makes a separate CARRIED_FORWARD adjustment on the next year (deliberate: no silent
  recomputation of a closed year).

- **D-159 — The reason is 5…500 characters, required, and visible to the employee.** Required because an
  unexplained change to someone's leave is worthless as a record; visible because the employee must be able
  to challenge it (data minimisation the other way round: less data would hide the *reason*, not personal
  data). The UI says "do not write private information". Control characters are refused so a reason cannot
  smuggle formatting or fake log lines.

- **D-160 — The cancel-with-closed-years flag from PLAN.md is NOT built, because it contradicts D-153.**
  PLAN.md's 16B assumed an APPROVED request could be cancelled (the pre-D-153 rule) and wanted an
  `acknowledge_closed_years` switch for closed years. Since **D-153** an APPROVED request can never be
  cancelled at all, so that path is unreachable and the flag would be dead code. What remains useful is
  visibility: `GET /leave-requests/{id}` now returns `touches_closed_year` + `closed_year_names`, and the
  screen warns that such a request can only be repaired with a manual balance adjustment. **Flagged** as a
  divergence from the current PLAN.md text (which is updated accordingly).

- **D-161 — "Edit allocation" and an ALLOCATED adjustment are two ways to the same field.** The upsert
  (`POST /leave-assignments`) is the everyday path: it also creates the assignment row, refuses inactive
  employees and is the only way to create a balance. The adjustment is the repair path: it works for closed
  years, inactive people and inactive types, keeps a ledger and a reason. Rule of thumb: assigning an
  entitlement → Assignments; fixing history or granting an exception → Adjust.

- **D-162 — What can be cancelled today, in one paragraph (D-153 + D-160 in plain words).** A **PENDING**
  request can be cancelled by the employee who asked for it, or by an ADMIN, from the request page and via
  `POST /leave-requests/{id}/cancel`; the reserved days go back to the available balance. An **APPROVED**
  request can never be cancelled — not by the employee, not by an admin, neither in the UI (the button is
  not rendered, because the API's `can_cancel` is false) nor through the API (409 "Only a pending request
  can be cancelled"). There is therefore no `acknowledge_closed_years` flag and no closed-year cancellation
  path (D-160). When an APPROVED request is genuinely wrong, an ADMIN repairs the consequence by hand on the
  **Assignments** page: a `USED` adjustment (`-N`) puts the wrongly-charged days back, an `ALLOCATED`
  adjustment changes the entitlement, and if the request touched a closed year a separate
  `CARRIED_FORWARD` adjustment on the next year moves the days on. Every one of those adjustments needs a
  reason, is written to the append-only ledger and is audited; the old request itself stays APPROVED as
  history.

- **D-163 — Refresh tokens are opaque, stored hashed, rotated, and grouped into families.** Every login opens
  a new `family_id`; each refresh marks the old row `replaced_at` and inserts a new one in the same family.
  Only the SHA-256 hash of the token is stored, never the token, and never an IP. **Reuse detection:** a
  rotated token presented again within `REFRESH_REUSE_GRACE_SECONDS` (10 s) is the benign two-tabs race →
  **409 `REFRESH_RACE`**, family untouched; after the grace window it is theft → **the whole family is
  revoked**, 401, and one `REFRESH_REUSE_DETECTED` audit row. Password reset, deactivation and `logout-all`
  revoke tokens in the same transaction as the change.

- **D-164 — `LoginAttempt` is telemetry, not evidence, so it inherits `BaseModel` and is pruneable.** It holds
  the normalised email, a **keyed HMAC of the IP** (never the raw address) and the outcome — no password
  material of any kind. A future cleanup job (16D) may delete old rows, which is why it is NOT append-only
  like `audit_log`/`leave_balance_adjustment`.

- **D-165 — Login answers identically for unknown email, wrong password and an inactive account.** One
  generic 401 text, and an **argon2 verification against a pre-computed dummy hash** when the account is
  missing/inactive, so response time does not reveal which case applied (measured: medians within ~2%).
  A password longer than 128 characters short-circuits to the same 401 without hashing.

- **D-166 — Fail fast in production.** `validate_production_settings()` runs at import; with
  `APP_ENV=production` and any unsafe setting the app **refuses to start** with a readable list (never a secret
  value). `/docs`, `/redoc` and `/openapi.json` are disabled when docs are off (default: on in development,
  off in production). A middleware adds `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` to
  every response and `Cache-Control: no-store` to `/auth/*` and `/admin/*`.

- **D-167 — `ACCESS_TOKEN_MINUTES` stays 480 until the frontend step (B2).** Today's frontend keeps the access
  token in `localStorage` and has no silent refresh, so a 15-minute token would log the user out every quarter
  of an hour. `.env.example` carries a note: it must become **15** once the frontend uses the httpOnly cookie
  and refreshes silently. Everything else in 16C-backend is live now.

- **D-168 — The frontend and the API must share a host in development.** `localhost` and `127.0.0.1` are
  different SITES, so a `SameSite=lax` cookie set by one is not sent to the other — that is why the login
  "worked" but the session did not survive. `VITE_API_URL` is now `http://localhost:8000`, and the client
  prints a development-only console warning when the page host differs from the API host. In production both
  must be on the same site (`app.example.com` + `api.example.com`).

- **D-169 — The access token lives only in a module variable.** No `localStorage` / `sessionStorage`; the old
  key is deleted at startup. A reload restores the session through `restoreSession()`, which is a
  SINGLE-FLIGHT refresh: React StrictMode's double effect in development therefore produces exactly one
  `POST /auth/refresh`.

- **D-170 — The refresh coordinator is a dependency-injected factory** (`createRefreshCoordinator`), so its
  single-flight, lock and `REFRESH_RACE` retry behaviour is unit-tested with Vitest and no network. Web Locks
  (`navigator.locks.request`) serialise refreshes across TABS; when the API is unavailable the code falls
  back to running directly.

- **D-171 — CORS credentials require an explicit origin list.** `allow_credentials=True` with
  `allow_origins=settings.cors_origins_list` (never `*`, which no browser accepts together with credentials),
  explicit methods/headers, and `expose_headers=["Retry-After", "Content-Disposition"]` so the login countdown
  and the CSV filename are readable by the browser.

- **D-172 — Logging out in one tab logs out the others.** A `BroadcastChannel("lms-auth")` message clears the
  memory token in every tab of the same origin. The channel is closed on unmount.

- **D-173 — Retention touches exactly three tables, and they are all "operational".** `login_attempt`,
  unusable `refresh_token` rows and already-SENT `email_outbox` rows are pruned; the audit log, the adjustment
  ledger, the carry-forward log and every business table are kept forever. Reason: those three are telemetry
  and delivery bookkeeping, while the others are evidence (D-141, D-147, D-155).

- **D-174 — Cleanup is a DRY RUN unless you pass `--apply`, and it deletes in batches of 1000.** A batch is one
  `DELETE … WHERE id IN (SELECT … LIMIT 1000)` followed by a commit, so no long lock is ever taken and a big
  `login_attempt` table is pruned in several small transactions. `email_attempt` rows are deleted **before**
  their `email_outbox` parents inside the same transaction, so the foreign key is never violated. A second run
  deletes 0 (idempotent).

- **D-175 — The worker prunes once a day behind a PostgreSQL advisory lock.** `pg_try_advisory_lock(key)` is a
  lock the database hands out by name: the first worker gets `true`, everybody else gets `false`, and the lock
  vanishes when its session ends — no table needed to remember it. Cleanup is a SYSTEM action, so it writes
  **no** audit row (consistent with D-148) and logs counts only.

- **D-176 — `/health/ready` never leaks internals.** It reports only `database`, `migrations` or `email` as
  short reasons, never a version, revision id, host or error text. A stale PENDING email is a **warning**,
  and `status` stays `ok`: the API is healthy even when the worker is slow. `GET /health` stays a pure
  liveness check with no database call, and the old `/health/db` is kept so nothing that already uses it breaks.

- **D-177 — The golden path is a marker-selected test guarded by a database check.** `pytest.ini` excludes
  the `integration` marker, so `pytest -q` never touches a database; the runnable suite is pure. The
  integration `conftest.py` aborts the session unless the database is obviously throw-away (local host and a
  name ending in `_test`), because those tests run `alembic upgrade head`. Only the failed rule is printed,
  never the URL.

- **D-178 — CI is least-privilege and secret-free.** `permissions: contents: read`, no secrets at all (CI never
  gets Supabase or SMTP credentials), Postgres only as a throw-away service container, `alembic check` as the
  schema-drift gate, `pip-audit` / `npm audit` as **non-blocking** supply-chain signals, and a hygiene job that
  fails when a `.env`, `venv/`, `node_modules/` or a private key is tracked. Actions are pinned to major
  versions; pinning to full commit SHAs is a later hardening step.

- **D-179 — Attachment keys are dated and random: `attachments/YYYY/MM/<32 hex>.<ext>`.** The
  extension comes only from the fixed allow-list (pdf/png/jpg/jpeg), never from the user's file
  name, and the random part must be exactly 32 lowercase hex characters. `services/storage_rules.py`
  refuses anything else — no `..`, no leading `/` or `.`, no backslash, no NUL, no trailing
  whitespace, no uppercase hex, no extra path segments. **Old flat keys (`<hex>.pdf`) are still
  accepted** so files uploaded before this phase keep working; only new uploads use the dated form.

- **D-180 — The Content-Security-Policy is built in code and asserted against the deployed file.**
  `services/csp_rules.py::build_csp(api_origin)` produces the one policy string that `deploy/Caddyfile`
  will serve, and a test compares the two so they cannot drift. `script-src` deliberately has **no**
  `unsafe-inline` and **no** `unsafe-eval` (XSS defence in depth); `style-src` needs
  `'unsafe-inline'` only because react-bootstrap sets inline styles. The API origin must be `https`
  or the literal `{$API_ORIGIN}` placeholder, and may not contain a path, quote, semicolon or space,
  so a header cannot be injected.

- **D-181 — `LMS_ENV_FILE` chooses the settings file.** Default `backend/.env`; a relative name is
  resolved inside `backend/`, an absolute path is used as-is. The app, alembic, the worker and every
  `python -m app.cli.*` command honour it, because they all import `app/core/config.py`. It is what
  lets the whole backend run against a throw-away demo database without touching `.env`. A requested
  file that does not exist fails with a readable message instead of a confusing traceback.

- **D-182 — The demo command has five mandatory guards, checked in this order.** (1) the
  `--i-understand-this-is-a-demo-database` flag; (2) `APP_ENV` is not production; (3) `LMS_ENV_FILE`
  is set and is not `.env`/`.env.local`; (4) the database name ends with `_demo_test` **or**
  `--allow-remote-demo-database` is given; (5) the database holds at most ONE employee whose code
  does not start with `DEMO-` (the seeded admin). Guards 1–3 run **before** `app.core.config` is
  imported, so a missing switch means `backend/.env` is never opened at all. Guard 4 needs its escape
  hatch because a Supabase database is always named `postgres` — the suffix rule alone would make the
  kit unusable on the very database it is meant for. Every refusal prints the reason only, never a URL.

- **D-183 — Demo data is created through the application's own API, never with SQL.** `app/cli/demo_data.py`
  speaks to the app in-process (httpx + ASGI, no server needed), signing in as the existing admin and
  then as each demo employee through the real login endpoint. That is why audit rows, balances,
  approver rules, outbox rows and the reconcile invariants are produced exactly as in real use. It is
  idempotent (everything is looked up by code or name first), every date is chosen by asking
  `/calendar/preview` and `/leave-requests/check` rather than guessing working days, and it ends by
  draining the outbox once (`python -m app.worker --once`). All demo employees share ONE random
  password, written with the codes and e-mails to `backend/demo_credentials.txt` (mode `600`,
  git-ignored); only the path is printed. Roles are derived from the approver map
  (`roles_for()`), so a name that approves for somebody always holds `APPROVER` (D-151, D-152).

- **D-184 — Demo employee addresses use `@demo.example.com`, not `@example.invalid`.** The API's own
  `EmailStr` validation refuses reserved special-use names such as `.invalid`, so demo employees could
  not be created at all with the usual convention. `demo.example.com` is the reserved documentation
  domain: it can never receive mail, the demo sends to Mailpit on the laptop, and the value is a single
  constant (`EMAIL_DOMAIN`) at the top of the file. **This is a deliberate divergence** from the
  "test addresses end in @example.invalid" rule, forced by the product's own validation.

- **D-185 — The demo runs against a separate, throw-away database, and its reset is "recreate the
  project".** Audit rows and adjustment ledger rows are append-only by design (D-147, D-155), so a
  demo database cannot be tidied row by row: the documented clean reset is to create a fresh Supabase
  project and repeat the four setup commands. `DEMO_GUIDE.md` also tells the presenter never to press
  the final confirm in the year-end closing wizard (irreversible, and the demo database is the only
  copy) and never to show `demo_credentials.txt` on a shared screen.

- **D-186 — A second demo run within 15 minutes can be refused by the login rate limit.** The first
  run signs the admin and every demo employee in (11+ logins from one IP), so an immediate re-run may
  answer `401` on the admin sign-in. It is the rate limiter, not the data: everything that did re-run
  created nothing new (the counts were identical). Documented in `DEMO_GUIDE.md`; waiting 15 minutes
  solves it, and no code change is needed.

- **D-187 — The demo password is reused, reset through the admin API, or the run stops — it is never
  regenerated silently.** A second `demo_data` run used to call `make_password()` again while the demo
  employees still held the first password, so every one of their logins failed with **401** (the first
  failure was the first *demo-employee* login, not the admin's — the earlier report blamed the login rate
  limit and was wrong; a rate-limit block is a **429**, and only *failures* count towards it). Now a pure
  decision function chooses: `CREATE` when no demo employee exists yet, `REUSE` when
  `backend/demo_credentials.txt` is well-formed (the employees already have that password), `RESET` when
  employees exist but the file is missing/broken — one fresh shared password is then set for every
  `DEMO-` employee through the administrator's own password-reset API (`PATCH /employees/{id}`), so the
  change is audited like any other — and `STOP` when neither is possible. A file counts as well-formed
  only when it carries exactly one shared-password line, one line per demo employee, the right e-mail and
  the same password everywhere; anything else is treated as broken rather than guessed at. The command
  never retries a sign-in: the **first 401** stops it with a readable message, and a **429** stops it
  immediately, reporting the `Retry-After` seconds and pointing at
  `python -m app.cli.unlock_login --email …`.
- **D-188 — A repeat demo run performs no writes except the ones the API makes for a login.** Two more
  non-idempotent steps were found while proving D-187: `PUT /employees/{id}/approvers` was sent even when
  the list already matched (`APPROVERS_SET` audit row each time), and each employee was signed in merely
  to ask "does a request already exist?". The approver list is now compared with `/approver-assignments`
  first, and the existence check runs as the ADMIN via `GET /leave-requests?employee_id=…`. A second run
  therefore writes nothing but one admin login; `employees`, `requests`, `balances`, `emails`,
  `adjustments`, `holidays` and `divisions` are identical, and the only growth in `audit_log` is
  `LOGIN_SUCCESS` rows, which the product writes for every sign-in by design (16C) — not demo data.

- **D-189 — E-mail DELIVERY is deliberately switched off for the demo; the queue itself stays on.**
  `EMAIL_BACKEND=console` means the worker renders every message, records it and marks it `SENT`, but
  nothing is handed to an SMTP server — not even a local sandbox. The demo therefore shows
  **System → Email log** where `DEMO_GUIDE.md` used to send the presenter to Mailpit, and the Mailpit
  step is gone from the start-up list. Reasons: the product owner wants the rest of the app
  demonstrable now and delivery dealt with after the first feedback round, and a demo must not depend
  on a mail server being up. Nothing else changes — the transactional outbox, the retry schedule, the
  dedupe keys and the reminder job all still run (D-110…D-119). Switching real sending on later is one
  setting (`EMAIL_BACKEND=smtp` plus an SMTP account) with **no code change**. The four authentication
  items that are *not* built (2FA, `must_change_password`, a per-device session list, JWT-secret
  rotation) stay recorded in `TODO_BACKLOG.md` with the proof that they are absent.

- **D-190 — An administrator-chosen password must be replaced by the owner at first sign-in.**
  `employee.must_change_password` (default **false** in the database, so no existing account is ever
  locked out) is set when an admin **creates** an account (`EmployeeCreate.must_change_password`
  defaults to `true`) or **resets somebody else's** password, and is cleared by the employee's own
  `POST /auth/change-password`. Resetting your *own* password does not force a change (nobody else
  typed it). Enforcement lives in exactly ONE place — `core/deps.get_current_user` — so every
  protected route is covered; while the flag is set, only `GET /auth/me`,
  `POST /auth/change-password`, `POST /auth/logout`, `POST /auth/logout-all` and `POST /auth/refresh`
  pass, everything else is **403** with the header `X-Password-Change-Required: true`. The front-end
  lands on `/account` after login and shows a banner while the flag is set. The rules themselves are
  pure (`services/password_rules.py`): `requires_password_change()` and `may_use_application()`.
  **The demo accounts opt out** (`must_change_password: false` from `demo_data`), because their shared
  password is handed over in `demo_credentials.txt` — otherwise the 12-minute story would turn into
  five forced password changes. Not recorded in the audit values: the flag is not secret, and adding
  fields to the `PASSWORD_RESET` row would break D-150 (a reset stores no values at all); the
  `PASSWORD_RESET` / `PASSWORD_CHANGED` rows themselves already say who changed whose password when.

- **D-191 — One "session" is one refresh-token family, and the employee can see and end their own.**
  `GET /auth/sessions` lists the caller's live families (device, signed-in at, last used, ends at) and
  `DELETE /auth/sessions/{id}` ends one of them; `POST /auth/logout-all` (16C) stays for "everywhere".
  A family that is not the caller's answers **404**, exactly like a missing one, so the API never
  reveals that somebody else's session exists (the D-89 rule). The device carrying the request is
  marked `current` (found through the refresh cookie, which is sent to `/auth/*`), and the UI does not
  offer to end it from the list — that is what the Logout button is for. Nothing new is stored: the
  token **hash** never leaves the database and **no IP address** is stored or shown, per D-163. The
  list is built from the same four conditions `classify_refresh` uses (not revoked, not replaced, token
  not expired, family younger than `REFRESH_FAMILY_MAX_DAYS`), so it can never show a session the API
  would refuse. While `must_change_password` is set (D-190) the endpoints are blocked like every other
  route, and the front-end hides the card instead of showing a confusing 403.
- **D-192 — The device name is derived from the User-Agent by a pure function.** The raw string is
  stored as-is (it already was, capped at 200 characters) but never shown alone: `session_rules.py`
  turns it into "Chrome on Windows", "Safari on iPhone", "Edge on Windows"… and anything unrecognised
  becomes **"Unknown device"** rather than a guess. Order matters and is tested: Edge and Opera before
  Chrome (their string contains "Chrome"), Chrome before Safari (its string contains "Safari"), and
  iPhone/iPad before macOS (the iPad string contains "Mac OS X").
- **D-193 — Ending one session writes one audit row.** `SESSION_REVOKED` (entity `employee`, the new
  value carrying how many token rows were revoked) is written inside the caller's transaction and
  fails closed like every other action (D-141); `logout-all` keeps writing `SESSIONS_REVOKED` (16C), so
  "one device" and "every device" are distinguishable in the audit log. The route is registered as
  AUDITED in `core/audit_registry.py`, which the coverage test enforces.

- **D-194 — [SUPERSEDES D-153] An APPROVED request can be cancelled by an ADMINISTRATOR (and only by
  one).** This restores FR-LR-5 and the answer to Open Question #1 ("only pending status cancel can
  possible by the employee. If the leave is approved then only admin can cancel it"), which D-153 had
  overridden. The exact rules now: **PENDING** → the requester *or* an admin, releasing the reserved
  days (`pending -= days`); **APPROVED** → an **admin only**, restoring the charged days
  (`used -= days`, `BalanceEffect.RESTORE_USED`, the member D-153 had deleted), while the employee gets
  **403 "An approved request can only be cancelled by an administrator."**; **REJECTED/CANCELLED** →
  nobody (409). A request that touches a **closed leave year** is refused with **409** naming the
  year(s): `services/cancellations.cancel()` takes the SHARED year lock (the lock the closing takes
  EXCLUSIVELY), re-checks `is_closed`, then locks the balance rows in ascending `leave_year_id` after
  the request row — the documented global order (D-96/D-131). `used` is never allowed to drop below
  zero: an inconsistent balance is refused with 409 instead of being clamped, because
  `reconcile_balances()` expects `used = Σ approved allocation days + Σ USED adjustments` (D-156) and
  the invariant still holds after such a cancellation (verified live). The audit row records the old
  status (`old.status = APPROVED`), the new status, the actor and the admin's reason; the outbox gets
  `CANCELLED` to the approvers **and** `CANCELLED_EMPLOYEE` to the requester, because an administrator
  undid their leave (D-115). `can_cancel()` now answers the same rule for the UI and additionally
  returns **false** whenever the request touches a closed year, so the button can never appear where
  the API would answer 409. `final_decided_at` is still left untouched — the approval decision did
  happen. The four old D-104…D-107 notes about closing this path are thereby live again, and
  **D-162 (the one-paragraph summary) is superseded**: the repair path for a wrongly approved request
  is now the admin's cancellation, with a manual `USED` adjustment only for a request in a **closed**
  year.

- **D-195 — The email log can show the EXACT rendered message, and an admin can run the queue by hand.**
  `GET /admin/emails/{id}` now also returns `subject`, `body_text` and `body_html`, rendered on the spot
  from the row's **stored facts** by `email_templates.render_email()` with `FRONTEND_BASE_URL` — the same
  function the worker uses to send, so the preview cannot drift from the real message. Opening a preview
  sends nothing. Rendering goes through `render_preview()`, which **never raises**: a row with an unknown
  event type returns `null` for all three instead of turning the screen into a 500 (the UI then says so).
  A new admin-only `POST /admin/emails/process-queue` runs **one pass** of the worker
  (`worker.recover_stuck()` + `worker.drain_once()`, plus `worker.reminder_tick()` when
  `?reminders=true`, followed by a second drain) and reports `processed`, `sent`, `failed`,
  `still_pending` and `reminders_queued`. It is a **system action** (the same code the worker runs), so it
  writes **no audit row** and is registered as `exempt:` in `core/audit_registry.py` for the coverage test
  (D-148). The screen shows a **Process Queue Now** button with an optional
  "also send pending-approval reminders" checkbox, so a demo never has to wait for the background process
  or open a second terminal.
- **D-196 — The two `TODO(Phase 16D)` email markers are resolved as PRODUCT DECISIONS, not as work.** A
  balance adjustment and the year-end carry-forward are **not** among the six events FR-NOT-1 lists, so no
  email is sent for either; the comments in `services/adjustments.py` and `services/closing.py` now say
  that explicitly instead of reading like unfinished tasks, and no `TODO` marker remains in `backend/app`.
  Nothing is lost: the reason **and** the before/after of every adjustment are visible to the employee on
  **My balances** (`GET /leave-balances/me/adjustments`) and in the append-only ledger; the closing writes
  a summary plus one `leave_carry_forward` row per employee, readable at
  `GET /leave-years/{id}/carry-forwards`, and each employee sees their carried days on *My balances*.
  Adding a seventh event is a product decision to make later, deliberately, not an oversight.
- **D-197 — The integration guard reads `app.core.config` when `DATABASE_URL` is not exported.** The
  16D-1 guard inspected `os.environ["DATABASE_URL"]` only, so running the integration tests with
  `LMS_ENV_FILE=.env.demo` was refused with "the host is not local; the database name does not end with
  _test" — not because the database was unsafe, but because the variable simply was not set. It now falls
  back to the app's own settings, which **adds** a source of truth without weakening a single rule: a
  hosted host (anything containing "supabase") and a database name not ending in `_test` are still
  refused, and the message still prints only the rule, never the URL. `pytest -q` never reaches the guard
  because the `integration` marker is deselected.

- **D-198 — The forced first change asks only for the NEW password; a normal change still asks for the
  old one.** `password_rules.current_password_required(must_change_password=…)` encodes the rule:
  during the forced change the employee typed that very password a moment earlier to sign in, and the
  administrator is the one who chose it, so asking for it again proves nothing (`ChangePasswordIn.
  current_password` is therefore optional). Every other change still requires it, and a value that IS
  sent is **always verified** — the flag can never be used to bypass the old-password check (a wrong
  value answers the usual generic 401 and counts towards the login rate limit, exactly as before).
  Omitting it when it is required answers **400 "The current password is required."** instead of a
  confusing 401. The screen hides the field and explains why while the flag is set. Nothing else
  changes: the new password still has to pass the policy, must differ from the old one, revokes every
  other session of that employee, and clears the flag in the same transaction (D-163/D-190).

- **D-199 — A password change lands the user on Home, and the database is the single source of truth
  for the flag.** After a successful `POST /auth/change-password` the screen re-reads `/auth/me`
  (`refreshUser()`) and **then** navigates to `/` — in that order, because the shell redirects a
  still-flagged user back to `/account`, so navigating first would bounce them right back. The new
  password hash and `must_change_password = false` are written in the SAME transaction as the rest of
  the change (the old password is revoked everywhere, a new refresh cookie is issued, the
  `PASSWORD_CHANGED` audit row is written), so the next sign-in uses the new password and the forced
  screen **never returns** on its own — it comes back only if an **administrator** creates the account
  or resets that password (which is the point of D-190). Verified live: a fresh session after the
  forced change reports `must_change_password=false`, the old password answers 401 and the new one 200.

- **D-200 — "Live" now covers every data screen, including My account.** The device list added in D-191
  loaded once on mount, so signing a device out (here or in another tab) did not update it. `My account`
  now uses `useAutoRefresh` like the rest of the app, so the list re-reads after any successful write
  anywhere (same tab or another tab, via the change signal), when the tab regains focus, and on the
  15-second safety poll. The one guard: while `must_change_password` is set the callback does nothing,
  because `GET /auth/sessions` is blocked then and the card is hidden (D-190). This closes the last
  screen that was not live — an audit (`grep -l useAutoRefresh src/pages`) had shown only
  `AccountPage` and `LoginPage` without it, and the login page shows no data. The transport is unchanged
  and still deliberately a signal + focus refresh + poll (D-154): a change made by another user on
  another device appears within 15 seconds, or instantly when you return to the tab. True push (SSE with
  Postgres LISTEN/NOTIFY, or WebSockets) remains deferred — it needs one streaming connection per tab
  plus a dedicated database connection, which is a lot of machinery for a leave app.

- **D-201 — The password form is never pre-filled, and the forced screen has no "current password" field
  at all.** `My account` renders the current-password input **only** in the normal-change branch; while
  `must_change_password` is set the user sees an explanatory note plus "New password" and "Repeat the new
  password" (D-198). On top of that the form carries `autoComplete="off"` and an effect clears all three
  fields on mount and whenever the mode changes, so a value the browser's password manager filled in can
  neither appear nor be submitted by accident. The two new-password inputs keep
  `autoComplete="new-password"`, which is the hint browsers need to offer a *new* password instead of
  the saved one. Reported from a live UI check ("current password is auto-filled on the first forced
  change"); the field was already not rendered in that branch, so a stale bundle was the likely cause —
  these guards make it impossible either way.

- **D-202 — "Attempts" in the email log means FAILED tries, so the column was renamed.** The worker only
  increments `email_outbox.attempts` when a send **fails** (it is the retry counter, D-118); a successful
  send is recorded in `email_attempt` instead. A row that was sent first time therefore shows
  `0/5` forever, which read as "nothing happened" and caused a false bug report ("why don't the attempts
  increase?"). The list column is now **Failed tries** (with an explanatory tooltip) and the detail line
  reads "N send attempt(s), X failed of Y allowed", so the successful tries in the history table are the
  obvious place to look. No behaviour changed — only the labels.

- **D-203 — One database URL, whatever Supabase gives you.** `core/config._to_asyncpg_url()` (already
  used through `settings.async_database_url`) rewrites the `postgresql://` / `postgres://` scheme to
  `postgresql+asyncpg://` and translates `sslmode=…` (libpq syntax, which asyncpg rejects) into
  `ssl=…`, dropping `sslmode=disable`; every other query parameter is preserved. On top of that,
  `app/db/urls.py` decides the asyncpg arguments: the **transaction pooler (port 6543)** gets
  `statement_cache_size=0` because pgbouncer shares server sessions and a prepared statement can already
  be taken there, while the **direct/session-pooler** URL (5432) keeps prepared statements. The port
  decides, **not** the hostname — Supabase's session pooler is also on `*.pooler.supabase.com`, and
  treating it as transaction mode would have cost performance for nothing. `DB_STATEMENT_CACHE_DISABLED=true`
  is the escape hatch for a pooler on an unusual port. The same arguments are given to Alembic's own
  engine (`alembic/env.py`), and `pool_pre_ping=True` stays on so a dropped cloud connection recovers by
  itself. Verified against the live Supabase database: `SELECT 1` succeeds and `alembic current` works.
- **D-204 — `demo_data` no longer requires `.env.demo`; its guard is the DATA, not a filename.** The
  `.env.demo` rule was dropped (`guard_environment` now only requires the
  `--i-understand-this-is-a-demo-database` flag), because the project uses one configured database and a
  filename convention protected nothing on its own. What protects a real database is
  `guard_not_a_development_database`: a database that already holds more than ONE employee outside the
  `DEMO-` range is refused outright, the database name must still end in `_demo_test` (or
  `--allow-remote-demo-database` must be passed), and `APP_ENV=production` is refused. Net effect: running
  `python -m app.cli.demo_data` against the real Supabase database is refused as soon as it contains real
  employees, while a fresh throw-away project works with the flags. `seed_admin` never had such a guard
  and is unaffected. **The integration suite stays hard-guarded**: `pytest -m integration` refuses any
  host containing "supabase" and any database whose name does not end in `_test`, and `pytest -q` never
  opens a database at all (the marker is deselected), so the real data cannot be wiped by the test suite.

- **D-205 — There is ONE database, and demo data may live in it — deliberately.** `.env.demo*` is gone:
  `backend/.env` is the only settings file, so the API, alembic and the worker always talk to the single
  configured Supabase database (delivery of e-mail is still switched off with `EMAIL_BACKEND=console`).
  `seed_admin` is unchanged. `demo_data` no longer needs any environment switch (D-204) and now accepts a
  database that is already in use **only** with the explicit `--allow-real-database` flag, whose help
  text says what it costs: the audit log is append-only (D-147), so the demo activity stays in the real
  log for ever, and the fictional `DEMO-` employees sit beside the real ones. The safer path for a
  presentation is still a **fresh Supabase project** you delete afterwards — §1.1 of `DEMO_GUIDE.md`
  spells both options out. The integration suite is unaffected and still refuses a Supabase host.
