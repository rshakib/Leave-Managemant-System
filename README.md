# Leave Management System

A web application to manage employee leave end-to-end: organisation setup, leave configuration,
balance tracking, leave requests, multi-approver workflows, and email notifications.

**Status — Phase 13:** the backend covers auth, organisation, employees, leave years/types,
balances, the calendar engine, approvers, leave requests, approvals, cancellation and an email
outbox with a worker. The React frontend has the matching screens (including an admin email log).

- Backend: Python + FastAPI (see `TECH_STACK.md`)
- Frontend: React + Vite + **JavaScript (JSX)**
- Database: PostgreSQL — Supabase in the cloud, or PostgreSQL 16 locally via Docker Compose
- Plan: `PLAN.md` · Decisions: `DECISIONS.md` · Todo backlog: `TODO_BACKLOG.md`
- Requirements: `leave_management_system_requirements(1).md`

## Prerequisites

- **Python 3.12+** (check: `python3 --version`)
- **Node.js 20.19+ or 22+** (check: `node --version`) and npm — with nvm, run `nvm use 22`
- **Docker** (only if you want a local database)

## 1. Database

The app reads `DATABASE_URL` from `backend/.env`. Pick one:

**Supabase (cloud)** — paste the connection string as-is into `backend/.env`:

```bash
cd backend && cp .env.example .env
# then edit backend/.env:  DATABASE_URL=postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres?sslmode=require
```

**Local PostgreSQL via Docker:**

```bash
cp .env.example .env          # repo root: POSTGRES_* values for docker-compose
docker compose up -d
docker compose ps             # wait for "healthy"
# then in backend/.env:  DATABASE_URL=postgresql://leave_user:leave_password@localhost:5432/leave_db
```

Stop the local database later with `docker compose down` (keeps data) or
`docker compose down -v` (also deletes the data volume).

## 2. Backend

```bash
cd backend
python3 -m venv venv               # one-time
source venv/bin/activate           # Windows: venv\Scripts\activate
pip install -r requirements.txt    # one-time
cp .env.example .env               # one-time, then set DATABASE_URL + JWT_SECRET

alembic upgrade head               # create/update the database tables
uvicorn app.main:app --reload --port 8000
```

Check it works:

```bash
curl http://127.0.0.1:8000/health      # {"status":"ok"}
curl http://127.0.0.1:8000/health/db   # {"database":"ok"}
```

Interactive API docs: <http://127.0.0.1:8000/docs>

## 3. Create your first admin

The app starts with an empty database, so there is nobody to log in as yet:

```bash
cd backend && source venv/bin/activate
python -m app.cli.seed_admin
```

It asks for a full name, email and password (twice). It creates "Head Office" / "Administration" if
no division/department exists, and refuses to run if an active admin already exists (use `--force`).

## 4. Frontend

```bash
cd frontend
npm install                        # one-time
cp .env.example .env               # one-time: sets VITE_API_URL=http://127.0.0.1:8000
npm run dev                        # start the dev server
```

Open <http://localhost:5173> and sign in with the admin you just created.

To confirm the production build works:

```bash
npm run build
npm run lint
```


## 5. Email worker

Emails are queued in the database (`email_outbox`) by the leave actions themselves, and a separate
worker process sends them. In development the default backend is `console` (no real mail):

```bash
cd backend && source venv/bin/activate
python -m app.worker            # keep running
python -m app.worker --once     # one pass, then exit (useful for testing)
```

Set `EMAIL_BACKEND=file` to write one `.eml` per message into `backend/outbox_dev/` (git-ignored)
instead of printing them.

## 6. Optional: local mail inbox (Mailpit)

To see real messages without any provider credentials:

```bash
docker compose --profile mail up -d mailpit
```

Then in `backend/.env`:

```bash
EMAIL_BACKEND=smtp
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_STARTTLS=false
```

Start the worker (`python -m app.worker`) and open <http://localhost:8025> to read the mail.
Every recipient in development must end in `@example.invalid`; nothing is sent to the internet.

## Project layout

```text
.
├── backend/                     # FastAPI app
│   ├── app/
│   │   ├── main.py              # app wiring, CORS, health checks
│   │   ├── core/                # settings, security (argon2 + JWT), dependencies
│   │   ├── db/session.py        # async engine + session dependency
│   │   ├── models/              # SQLModel tables + Pydantic schemas
│   │   ├── routers/             # auth, org, leave, approvals, admin emails
│   │   ├── services/            # rules + outbox + mailer
│   │   ├── templates/email/     # one .txt + .html per email event
│   │   ├── worker.py            # sends the outbox, queues reminders
│   │   └── cli/seed_admin.py    # create the first admin
│   ├── alembic/                 # migrations
│   ├── outbox_dev/              # .eml files from EMAIL_BACKEND=file
│   └── .env.example             # copy to backend/.env
├── frontend/                    # React + Vite + JavaScript (JSX)
│   ├── src/api/client.js        # Axios instance + interceptors
│   ├── src/auth/                # AuthContext + ProtectedRoute
│   ├── src/components/Layout.jsx
│   ├── src/pages/               # Login, Home, Divisions
│   └── .env.example             # copy to frontend/.env
├── docker-compose.yml           # local PostgreSQL 16 service
├── .env.example                 # copy to .env (used by docker-compose.yml)
├── PLAN.md                      # phase-by-phase build plan
├── TODO_BACKLOG.md              # every open marker, grouped by phase
├── DECISIONS.md                 # resolved gaps in the requirements
└── TECH_STACK.md                # tools and why
```


## Security model

**Two tokens.** Logging in returns a short-lived **access token** (15 minutes) and sets a long-lived
**refresh token** as an **httpOnly cookie** (`refresh_token`, `Path=/auth`, `SameSite=lax`, `Secure` in
production). The access token is kept **only in a JavaScript variable** — never in `localStorage` or
`sessionStorage` — so a reload simply refreshes silently, and a page script that injects code cannot read a
stored token afterwards.

**Silent refresh.** When a request comes back `401`, the API client asks a small coordinator for a refresh.
The coordinator is **single-flight**: every request that 401s at the same moment waits on the same
`POST /auth/refresh`, and the browser's **Web Locks** make two tabs take turns. The new token is stored in
memory and the original request is retried once. If the refresh is refused, the session ends and you land on
`/login` with “Your session has expired”. A *network* failure does not end the session.

**Rotation and reuse detection.** Every refresh replaces the cookie with a new one in the same *family*. If
an old cookie is presented again after a short grace window, that means a copy leaked: the whole family is
revoked, both sessions must sign in again, and a `REFRESH_REUSE_DETECTED` audit row is written.

**What the flags protect against.** `httpOnly` — page scripts cannot read the cookie (XSS cannot steal it).
`SameSite=lax` — another site's page cannot make your browser send it (CSRF). `Secure` — it only travels over
HTTPS. `allow_credentials` + an explicit origin list on the API — the browser only lets our own front-end use
the cookie, and the API also checks the `Origin` header on `/auth/refresh`.

**Same host in development.** `localhost` and `127.0.0.1` are *different sites*, so a `SameSite` cookie issued
to one is not sent by the other. Use **http://localhost:5173** with **http://localhost:8000** (that is what
`frontend/.env` and `backend/.env` are set to). In production the front-end and the API must be on the same
**site**, for example `app.example.com` and `api.example.com` (both `example.com`).

**Before running in production**, the app refuses to start unless these are set: `APP_ENV=production`, a real
`JWT_SECRET` (32+ random characters), `IP_HASH_KEY` (32+ random characters), `COOKIE_SECURE=true`,
`ENABLE_DOCS=false`, `CORS_ORIGINS` with only your https origins, `EMAIL_BACKEND=smtp`, an honest
`TRUSTED_PROXY_COUNT` (how many proxies really sit in front of the API) and `ACCESS_TOKEN_MINUTES` ≤ 60.

**Locked out?** `python -m app.cli.unlock_login --email someone@example.com` deletes that email's login
attempts and revokes its sessions — it prints only counts.

**Not covered yet:** two-factor authentication, a per-device session list, a first-login password change, a
Content-Security-Policy for the front-end, and rotation of `JWT_SECRET`.


## Running the tests

```
cd backend && source venv/bin/activate
pytest -q                 # unit tests only — no database, no network
```
The **integration** tests (below) are excluded by `pytest.ini`, so a plain `pytest -q` can never touch a
database. Run them explicitly:

```
pytest -m integration -q
```
Those tests **refuse to run** unless `DATABASE_URL` points at a throw-away database: the host must be
`localhost`/`127.0.0.1`/`postgres`, the database name must end with `_test`, and a hosted host is rejected.
Only the rule that failed is printed — never the URL. That guard exists because the suite runs
`alembic upgrade head`, which is destructive on the wrong database.

```
cd frontend
npm test        # Vitest (the refresh coordinator)
npm run lint
npm run build
```

## CI

`.github/workflows/ci.yml` runs on every push and pull request, with `permissions: contents: read` (least
privilege) and **no secrets**: CI never receives Supabase or SMTP credentials. Five jobs: **backend** (unit
tests + a non-blocking `pip-audit`), **migrations** (a `postgres:16` service container, `alembic upgrade
head`, then `alembic check` to fail on drift between the models and the migrations), **frontend**
(`npm ci`, lint, tests, build, non-blocking `npm audit`), **integration** (the golden path against a real
`lms_test` database) and **hygiene** (fails if a `.env`, a `venv/`, `node_modules/` or a private key is
tracked by git). `.github/dependabot.yml` opens weekly updates for pip, npm and the actions themselves.

## Maintenance and retention

Only three things ever expire:

| Table | Rule | Default |
| --- | --- | --- |
| `login_attempt` | older than the cutoff | 30 days |
| `refresh_token` | unusable (expired/revoked/replaced) and older than the cutoff | 30 days |
| `email_outbox` (+ its `email_attempt` rows) | **SENT** and older than the cutoff | 90 days |

The audit log, the adjustment ledger, the carry-forward log and every business table are kept **forever**.

```
cd backend && source venv/bin/activate
python -m app.cli.cleanup            # DRY RUN: prints counts, deletes nothing
python -m app.cli.cleanup --apply    # really deletes, in batches of 1000
```
Deleting happens in batches with a commit per batch, so no long lock is taken, and a second run deletes 0.
The worker also runs it once a day behind a **PostgreSQL advisory lock** (`pg_try_advisory_lock`), so two
workers can never prune at the same time. It is a system action: it writes no audit row and logs counts only.

## Health endpoints

* `GET /health` — **liveness**: the process answers. No database call.
* `GET /health/ready` — **readiness**: `SELECT 1`, the applied migration matches the code's head revision,
  and how old the oldest PENDING email is. `200 {"status":"ok","warnings":[...]}` or
  `503 {"status":"unavailable","reasons":[...]}`. It never exposes versions, revision ids, hosts or error
  text — only short reasons like `database` or `migrations`. A **stale pending email only warns**: the API is
  fine, the worker may just be slow.

## Troubleshooting

**`permission denied ... connect to the Docker daemon socket`** — your user isn't allowed to use
Docker yet. Add yourself to the `docker` group once:

```bash
sudo usermod -aG docker $USER
newgrp docker            # applies it to this shell (or log out and back in)
docker run hello-world   # should print "Hello from Docker!"
```

Note: membership in the `docker` group is effectively root-level access on this machine.

**Vite engine warning / build fails on an old Node** — this project needs Node 20.19+ (or 22+).
Check `node --version`; with nvm, run `nvm use 22` before `npm install`.

**CORS error in the browser console** — the API only allows the origins in `backend/.env`
`CORS_ORIGINS` (default `http://localhost:5173,http://127.0.0.1:5173`). Add your origin there and
restart the backend.
