# Tech Stack — Leave Management System

Beginner-friendly choices. Each tool is explained in plain language, and the reasoning for the
picked option is given at the end.

## Backend

| Tool | What it is | Why it's here |
| ---- | ---------- | ------------- |
| **Python 3.12** | Programming language | One language for the whole server; huge ecosystem; readable for beginners. |
| **FastAPI** | Web framework | Builds the HTTP API. Auto-generates interactive docs at `/docs`, validates input for you, and is async by default. |
| **SQLModel** | ORM (database toolkit) | One class defines both the database table *and* the request/response shape. Built on SQLAlchemy (storage) + Pydantic (validation), so you learn one concept instead of two. |
| **SQLAlchemy 2.0 (async engine)** | Database layer under SQLModel | Supplies the async engine and `AsyncSession` that talk to PostgreSQL. You rarely touch it directly. |
| **Pydantic v2** | Data validation library | Validates request/response data. SQLModel reuses it, so plain (non-table) models double as Pydantic models. |
| **Alembic** | Database migration tool | Version-controlled schema changes: edit models → generate a migration → apply it. SQLModel has no migrator of its own, so Alembic reads the SQLModel/SQLAlchemy metadata. |
| **PostgreSQL** | The database | Supabase (PostgreSQL 17) in the cloud, or PostgreSQL 16 locally via Docker. Supports the arrays, JSONB, and partial indexes the requirements need. |
| **asyncpg** | Database driver | Fast async PostgreSQL driver used by SQLAlchemy. |
| **PyJWT + argon2-cffi** | Authentication libraries | Sign login tokens (JWT, HS256) and hash passwords with argon2. `passlib` was avoided because it is unmaintained (DECISIONS D-43). |
| **pytest + httpx + pytest-asyncio** | Testing tools | Test API endpoints and pure logic (especially the day-calculation engine). |

### SQLModel notes (vs writing raw SQLAlchemy)

- **Two model kinds.** `class Employee(SQLModel, table=True)` is a real database table. A plain
  `class EmployeeCreate(SQLModel)` is a Pydantic-only model used for request/response bodies. You
  often derive one from the other so fields aren't repeated.
- **Async still works.** SQLModel doesn't ship its own async session, but it pairs cleanly with
  SQLAlchemy's `AsyncSession` / `async_sessionmaker`.
- **Escaping to SQLAlchemy is expected.** Anything SQLModel doesn't cover directly — multi-column
  `UniqueConstraint`, `CHECK` constraints, PostgreSQL `ARRAY`/`JSONB`, partial indexes — is declared
  with `__table_args__` or `Field(sa_column=Column(...))`. That's plain SQLAlchemy *inside* the class.
- **Alembic autogenerate needs the models imported.** Import every `table=True` model (e.g. a
  `models/__init__.py` that re-exports them) before generating a migration, or Alembic will see no tables.
- **Trade-off to remember.** SQLModel is younger than SQLAlchemy and hides some advanced features
  behind the SQLAlchemy fallback above. For this CRUD-heavy app that's a good trade — less boilerplate,
  one model per concept — and the fallback is always available when needed.

## Frontend

| Tool | What it is | Why it's here |
| ---- | ---------- | ------------- |
| **React 19** | UI library | The SPA library. The component model is well documented and beginner-friendly. |
| **Vite** | Dev server & build tool | Instant page reload with almost no configuration. |
| **JavaScript + JSX** | The frontend language | Plain JavaScript, not TypeScript (DECISIONS D-48): fewer tools and less setup while learning React. |
| **React Router** | Routing library | Maps URLs to pages (login, dashboard, admin screens). |
| **Bootstrap 5 + React-Bootstrap** | UI component kit | Ready-made forms, tables, and modals, so you don't hand-style every screen. |
| **Axios** | HTTP client | Calls the API. Used with plain React hooks (`useState`/`useEffect`) for now (DECISIONS D-49). |
| **oxlint** | Linter | Ships with the Vite template; run with `npm run lint`. |

## Tooling

- **Docker Compose** — runs PostgreSQL (and later Redis) the same way on every machine.
- **Git + GitHub** — version control from day one.
- **ruff + black** (Python) and **ESLint + Prettier** (JS/TS) — automatic formatting/linting (optional).

## Deferred — add later, not now

- **TanStack Query** — data caching; Axios + plain hooks cover Phase 5 (DECISIONS D-49).
- **Vitest + React Testing Library** — frontend tests, once there are screens worth testing.
- **Refresh tokens + httpOnly cookies** — Phase 4 ships a single access token; refresh is Phase 16.
- **Redis + Celery/ARQ** — only if email volume outgrows the DB-backed outbox (see Phase 13).
- **S3-compatible storage** — only when moving attachments off the local disk.
- **SSO** — login is structured so SSO can replace password auth later.

## Why these and not the alternatives

- **FastAPI vs Django:** you chose FastAPI for its auto-generated docs and clean async API. The cost
  is that you assemble the ORM, migrations, and admin screens yourself — which is the learning.
- **SQLModel vs raw SQLAlchemy:** SQLModel removes the duplicated "DB model + schema model" pair, the
  exact boilerplate beginners trip over. Raw SQLAlchemy is more powerful and more mature; if you hit a
  wall, you drop down to SQLAlchemy for that one piece without changing the rest.
- **argon2-cffi vs passlib:** passlib is no longer maintained and fails on recent Python versions, so
  the password hashing uses argon2-cffi directly.
- **JavaScript vs TypeScript:** TypeScript catches type mistakes, but adds config and syntax to learn.
  For a first React project, plain JSX keeps the focus on components and data flow (DECISIONS D-48).
- **React SPA vs server-rendered pages:** a richer UI, but now there are two codebases, plus CORS and
  a build step to manage.
- **PostgreSQL from the start:** matches the requirements (arrays, JSONB, partial indexes) and avoids a
  painful switch later. The cost — running Postgres locally — is handled by Docker Compose.
