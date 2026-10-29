# TODO backlog

Every open marker found in the repository, grouped by the phase that will close it.
Last collected while building **Phase 16D-2 (Part A)** and the **demo kit**.

## Phase 16B follow-ups (deliberately not built)

- **No email** to the employee when their balance is adjusted — a deliberate product decision, not a
  gap (D-196); the adjustment, with its reason, is on their own *My balances* screen.
- **No second-admin approval** of an adjustment, and no bulk adjustments.
- **No report/export** of adjustments (the ledger is visible per balance and per employee only).
- **The cancel-with-closed-years flag** from the original plan is not built (D-160), and it is no
  longer needed: since **D-194** a request that touches a closed year is simply refused with 409 and
  `can_cancel` is false, so there is nothing to acknowledge in the UI.

## Phase 16C — what is left

- **B1 + B2 are done** (backend + frontend): refresh tokens with rotation and reuse detection, the
  httpOnly cookie, login rate limits and login auditing, the in-memory access token, the silent refresh
  coordinator (Vitest-tested), the AccountPage and `ACCESS_TOKEN_MINUTES=15`.
- **Not built on purpose**: 2FA, social login, email-based password reset, a frontend
  Content-Security-Policy at the host (16D-2), JWT-secret rotation. (`must_change_password` is built —
  D-190; the per-device session list is built — D-191.)
- **B2 also resolved**: the old `login_attempt` / expired `refresh_token` rows are pruned by the
  retention job (16D-1, D-173).

## Phase 16D-2 / 16D-3 — deployment (partly built)

| File | What is missing |
| ---- | --------------- |
| 16D-2 Part A (**done**) | `services/storage_rules.py` (D-179), `services/csp_rules.py` (D-180) and the extra `validate_production_settings` checks (S3 settings, `TRUSTED_PROXY_COUNT` must be exactly 1, `COOKIE_SAMESITE`, `STORAGE_BACKEND`). |
| 16D-2 Part B (**not built**) | `S3Storage` + boto3 behind `STORAGE_BACKEND` (threadpool, private bucket, no presigned URLs, `head_bucket` fail-fast), the router's `open_bytes` download change, `gunicorn` + `backend/Dockerfile` + `frontend/Dockerfile` + `.dockerignore`, the `deploy/` folder (compose, Caddyfile with HSTS + the CSP, `.env.production.example`, README), the deploy consistency test, and the `docker-build`/`caddy validate` CI jobs. |
| 16D-3 | The real deployment: real SMTP, TLS, the worker as its own process, the first smoke test. |
| `backend/app/services/closing.py` | (closed) Email about carried/forfeited days — deliberately not sent (D-196); the closing summary and the carry-forward log show it. |
| Not built | First-login password change (`must_change_password`), a per-device session list, 2FA. |
| DECISIONS D-149 | The audit log is intentionally never pruned — retention deliberately leaves it (and the ledger, and the carry-forward log) alone. |

## Year-end closing — what Phase 15 deliberately does not do

- **No undo of a closing.** Close a year and it stays closed; the only repair is a manual balance change
  (Phase 16B).
- **No balance-adjustment screen.** Needed to repair a wrong closing or a wrongly approved request (an
  approved request can no longer be cancelled — D-153). Phase 16B, on top of the audit log so every manual
  change is recorded.
- **No scheduled or automatic closing.** A human runs it, after reading the preview.
- **No "close early" switch** — a year can only be closed after its last day (D-15/D-133).
- **No partial closing** — one employee or one leave type at a time is not supported.

## Demo kit (Task 2)

- **2a and 2b are done**: `LMS_ENV_FILE` (D-181), `backend/.env.demo.example`, and
  `app/cli/demo_data.py` with its five guards (D-182, D-183) — verified end to end on a throw-away
  `lms_demo_test` database.
- **2c is done**: `DEMO_GUIDE.md` (setup, start-up, the 10–12 minute story, the honest Q&A, the reset
  and the pre-demo checklist).
- **Not built on purpose**: no demo data is seeded into the development database, and the demo never
  sends a real e-mail (Mailpit on the laptop, or the console backend).
- **Note (D-184)**: demo employee addresses end in `@demo.example.com`, because the API's own e-mail
  validation refuses `.invalid` addresses.
- **Note (D-186)**: a second `demo_data` run within 15 minutes can be refused by the login rate limit.

## E-mail sending — deliberately OFF (demo)

- **`EMAIL_BACKEND=console` in the demo configuration.** The whole chain works — the request/approval
  flow queues messages in the database, the worker renders them and marks them `SENT` — but nothing
  is delivered anywhere. The demo shows **System → Email log** instead of a mail sandbox (D-189).
- **To switch real delivery on later**: `EMAIL_BACKEND=smtp`, fill `SMTP_HOST`/`SMTP_PORT`/credentials,
  optionally `docker compose --profile mail up -d mailpit` for a local sandbox. No code change needed.
- **Not built** (deliberately, after the demo): a real SMTP provider in production, delivery
  monitoring/bounce handling, and the "adjusted balance" e-mail (16B follow-up).

## Authentication — the four deliberately unbuilt items

| Item | State | Proof |
| ---- | ----- | ----- |
| Two-factor authentication | **not built** | no `totp`/`two_factor`/`2fa` anywhere in `backend/app` or `frontend/src` |
| Forced password change on first login (`must_change_password`) | **BUILT** (D-190) | `employee.must_change_password`, set on admin create/reset, enforced in `get_current_user`, pure rules in `services/password_rules.py`; the demo accounts deliberately opt out |
| Per-device session list | **BUILT** (D-191…D-193) | `GET /auth/sessions` + `DELETE /auth/sessions/{id}`, Code on `My account` → "Where you are signed in"; pure rules in `services/session_rules.py` |
| JWT secret rotation / key id (`kid`) | **not built** | `core/security.py` signs with one `JWT_SECRET`; there is no `kid`, JWKS or previous-secret handling |

- **Closest existing thing to a session list**: `POST /auth/logout-all` revokes every refresh token of
  the signed-in employee (D-163), so a user can end all sessions even though they cannot see them.

## Integration test harness

- **`tests/integration/test_golden_path.py` cannot run: `pytest-asyncio` is not installed.** The file is
  decorated with `@pytest.mark.asyncio` (which pytest reports as an unknown mark) but its `async def`
  test is never awaited, so running `pytest -m integration` fails it with "async def functions are not
  natively supported". Found while running the new email integration tests (2026-10-26); it is invisible
  in `pytest -q` because the `integration` marker is deselected.
  → Fix by either adding `pytest-asyncio` to `backend/requirements-dev.txt` plus `asyncio_mode = auto`
  in `pytest.ini`, or by giving that file an owned event loop the way
  `tests/integration/test_admin_emails.py` now does (it uses a module-scoped loop and needs no plugin).

## Known limitations (accepted for now)

- **The audit log cannot prove *who* really acted** if someone has database owner rights: they can drop the
  trigger and rewrite rows. It is tamper-evident by policy and by trigger, not cryptographically
  tamper-proof.
- **No export of the audit log itself** — an admin reads it on screen only.
- **The access token lives in a module variable** (never `localStorage`); a reload restores the session
  through the httpOnly refresh cookie (D-169). Login is rate-limited by e-mail, IP and e-mail+IP, and
  every attempt is recorded (16C).
- **Attachments are stored on the local disk** (`backend/media/`, keys per D-179). The S3 backend is
  designed and its rules are tested, but the code itself is Phase 16D-2 Part B, so files would not
  survive a stateless deployment yet.
- **No automatic refresh-token revocation on a password change in another session** beyond
  `logout-all` and the documented family revocation (16C).
- **The email worker must run as its own process in production** (`python -m app.worker`); nothing starts
  it for you.
- **Reports count whole requests, not days inside a date range.** A 10-day request that overlaps a 7-day
  range contributes all 10 days to the totals; only the *filtering* uses overlap.
- **`.xlsx` export is not built** — CSV only (DECISIONS D-20).
