# Session & JWT — how login actually works

Written for someone new to this. Every claim points at the real file and line so you can open it
and follow along. Line numbers are from this version of the code.

Read it in order. If you only have two minutes, read **§1** and **§7 (the worked example)**.

---

## 1. The big picture in one minute

The app uses **two different tokens**, and that is the whole trick:

| | **Access token** (JWT) | **Refresh token** |
| --- | --- | --- |
| What it is | a signed piece of text that says "I am employee #7" | a long random string |
| Lives for | **15 minutes** (`ACCESS_TOKEN_MINUTES` in `.env`) | **7 days** (`REFRESH_TOKEN_DAYS`) |
| Where the browser keeps it | **only in JavaScript memory** | an **httpOnly cookie** the page cannot read |
| Sent how | `Authorization: Bearer <token>` header | automatically by the browser, only to `/auth/*` |
| Purpose | fast: the server can trust it without a database lookup of "who is this" | lets the browser get a **new** access token without asking for the password again |

So: the short token is what the API checks on every call; the long token is what keeps you logged in.
If the short one is stolen it dies in 15 minutes. The long one never leaves the cookie jar, so page
JavaScript cannot steal it.

```
browser                        API                         database
  │  POST /auth/login (email+password)                         │
  │──────────────────────────────▶│  check password (argon2)   │
  │                               │──────────────────────────▶ │
  │  {access_token} + Set-Cookie  │  write a refresh row       │
  │◀──────────────────────────────│                            │
  │                                                             │
  │  GET /leave-balances/me   Authorization: Bearer eyJ…        │
  │──────────────────────────────▶│  verify signature, load    │
  │                               │  employee #7 from DB ────▶ │
  │  200 OK                                                  ◀──│
```

---

## 2. The cast (words you will meet)

| Word | Plain meaning |
| --- | --- |
| **JWT** | "JSON Web Token" — three base64 chunks joined by dots: `header.payload.signature` |
| **payload** | the data inside: here only `sub` (employee id), `type`, `exp` (expiry) |
| **signature** | a hash of the payload made with `JWT_SECRET`; change one character and the server knows |
| **httpOnly cookie** | a cookie JavaScript is **not allowed** to read (`document.cookie` will not show it) |
| **SameSite** | a cookie rule: `lax` means "send it when the user comes back to my own site" |
| **family** | all the refresh tokens that came from **one login**. Rotating a token keeps the same family |
| **rotation** | every refresh kills the old token and issues a new one; a stolen old one becomes useless |
| **argon2** | the password hashing function; one-way, deliberately slow |
| **bearer** | "whoever shows this token is the owner" — which is why it must stay secret |

---

## 3. Login, step by step

**Endpoint:** `POST /auth/login` — form fields `username` (the email) and `password`.
Code: `backend/app/routers/auth.py:75` → `backend/app/services/auth_service.py:116`.

What happens inside, in order:

1. **Rate-limit check first.** Before touching the password, `login()` counts recent failures
   (`auth_service.py:135-159`). Reasons are in §9.
2. **Normalise** the email (trimmed, lower-case) — `auth_service.py:53`.
3. **Find the employee.** `auth_service.py:160`.
4. **Verify the password against argon2.** `backend/app/core/security.py:27` (`verify_password`).
5. **If the account is unknown or inactive, still do a fake verify** against `_DUMMY_HASH`
   (`auth_service.py:46`). Without this, "unknown email" would answer in 1 ms and "wrong password" in
   80 ms, and an attacker could tell which emails exist. Both cases answer the **same** 401 message
   (`auth_service.py:39`).
6. **Write a `login_attempt` row** — email, a **hashed** IP, success/failure (`auth_service.py:110`).
   The raw IP is never stored.
7. **Create the access token** — `security.py:35`:
   ```python
   payload = {"sub": employee.id, "type": "access", "exp": now + minutes}
   jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)   # security.py:47
   ```
8. **Create the refresh token** — `auth_service.py:214` (`issue_refresh`): a random string
   (`security_rules.py:28`) is **hashed** (`security_rules.py:23`) and only the hash is saved
   (`models/auth_tokens.py:40`). A new `family_id` is started (one login = one family).
9. **Set the cookie** — `routers/auth.py:42-46`:
   ```python
   max_age = settings.refresh_token_days * 86400
   httponly=True, secure=settings.cookie_secure,
   samesite=settings.cookie_samesite, path="/auth"
   ```
   `path="/auth"` matters: the cookie is only sent to auth endpoints, not to every request.
10. **Answer** `{"access_token": "...", "must_change_password": false}` (`routers/auth.py:88`).

> **Why the expiry is short.** A JWT cannot be revoked — the server just checks the signature. So the
> only defence is a short life. `ACCESS_TOKEN_MINUTES` defaults to 480 in code (`core/config.py:96`)
> but this project's `.env` sets **15**; with the refresh cookie the user never notices.

---

## 4. What the JWT contains — and what it deliberately does not

A decoded payload looks like this (fake values):

```json
{ "sub": 7, "type": "access", "exp": 1793300000 }
```

That is all. Roles are **not** inside, on purpose: if they were, an admin demoted (or an employee
deactivated) would keep their powers until the token expired. Instead every request loads the
employee **from the database** (`core/deps.py:64`), so a role change or a deactivation takes effect on
the very next call — the price is one extra small query per request.

---

## 5. Every request: who is calling?

Every protected route depends on one function: `get_current_user` in **`backend/app/core/deps.py:38`**.

It does this, in order:

| Step | What it checks | Line | Failure |
| --- | --- | --- | --- |
| 1 | read the `Authorization: Bearer …` header | `deps.py:20` | 401 `Not authenticated` |
| 2 | verify the signature and the expiry | `deps.py:49-54` | 401 `Token has expired` / `Invalid token` |
| 3 | `type` must be `"access"` (a refresh token is not accepted here) | `deps.py:56-57` | 401 |
| 4 | load the employee from the database | `deps.py:64` | 401 |
| 5 | the employee must still be **active** | `deps.py:65` | 401 `Invalid or inactive account` |
| 6 | **must-change-password gate**: while `must_change_password` is true, only `/auth/me`, `/auth/change-password`, `/auth/logout`, `/auth/logout-all`, `/auth/refresh` pass | `deps.py:71-80` | 403 `You must change your password…` |

Role checks are a second layer: `require_roles(Role.ADMIN)` (`deps.py:84`) builds a dependency that
answers **403** when the caller holds none of the listed roles. Which routes use it is listed in
`IMPLEMENTATION_REPORT.md` §3.

The browser side adds the header in one place — `frontend/src/api/client.js:94`:

```js
config.headers.Authorization = `Bearer ${accessToken}`
```

---

## 6. Refresh: staying logged in without the password

### The flow

1. A request comes back **401** (the access token expired).
2. `client.js:99-116` catches it, asks the **refresh coordinator** for a new token, then **retries the
   original request once** (the `_lmsRetried` flag stops an endless loop).
3. The coordinator (`frontend/src/api/refreshCoordinator.js:25`) makes sure only **one** refresh is in
   flight: two tabs, or three requests at once, all wait on the same promise
   (`refreshCoordinator.js:7`). Across tabs it uses the browser's **Web Locks** API
   (`refreshCoordinator.js:11-13`).
4. The API's `POST /auth/refresh` (`routers/auth.py:101`) reads the **cookie**, classifies it, and
   **rotates**: the old row gets `replaced_at`, a new row is inserted in the **same family**
   (`auth_service.py:265`).

### What the server decides (`services/security_rules.py:33`)

| Outcome | Meaning | Answer |
| --- | --- | --- |
| `VALID` | normal | rotate, return a new access token |
| `EXPIRED` | 7 days passed | **401** → the user logs in again |
| `REVOKED` | logged out / password changed | 401 |
| `FAMILY_TOO_OLD` | the family is older than 30 days (`REFRESH_FAMILY_MAX_DAYS`) | 401 |
| `REUSED_WITHIN_GRACE` | the old token was used again within **10 s** — the benign "two tabs at the same moment" race | **409 `REFRESH_RACE`**, and the frontend waits 1 s and retries once (`refreshCoordinator.js:20-38`) |
| `REUSED_THEFT` | the old token was used again **after** the grace window — somebody is replaying a stolen token | the **whole family is revoked** (`auth_service.py:292`) plus an audit row `REFRESH_REUSE_DETECTED` |

That last row is the nice part: a stolen refresh token makes the thief and the real user both get
logged out, which is loud and safe instead of silent and wrong.

---

## 7. A worked example (follow the clock)

You log in at **09:00**.

| Time | What the app does | Result |
| --- | --- | --- |
| 09:00 | `POST /auth/login` | gets a JWT valid until 09:15, cookie valid until +7 days |
| 09:05 | click "My balances" | header `Bearer …` → 200 |
| 09:16 | click "My requests" | **401** → the coordinator calls `/auth/refresh` → rotates → retries → **200**. You saw nothing |
| 09:30 | leave the tab, come back next day | JWT long expired → 401 → refresh → new token → the screen still works |
| +7 days | open the app | the cookie expired → refresh answers 401 → the login page says "session expired" |
| any time | press Logout | `/auth/logout` revokes the family, the cookie is deleted, other tabs sign out too |

Note what never happened: the password was typed once. That is the entire point of the pair.

---

## 8. Logout, and the device list

| Action | Endpoint | What it really does |
| --- | --- | --- |
| Logout | `POST /auth/logout` (`routers/auth.py:137`) | revokes the cookie's **family**; always 204, even for a bad cookie |
| Log out everywhere | `POST /auth/logout-all` (`routers/auth.py:150`) | revokes **every** family of that employee + one audit row `SESSIONS_REVOKED` |
| See my devices | `GET /auth/sessions` (`routers/auth.py:192`) | one row per live family: device name, signed-in at, last used, ends at |
| End one device | `DELETE /auth/sessions/{id}` (`routers/auth.py:206`) | revokes that family only; a family that is not yours answers **404** (no leak) |

The device list shows **no IP address and no token** — only a name derived from the User-Agent
(`services/session_rules.py:36`) and timestamps. "Is this session still alive?" is decided by the same
four conditions the refresh uses (`session_rules.py:58`), so the list can never show a session the API
would refuse.

Other tabs are signed out locally with `BroadcastChannel` (`frontend/src/auth/AuthContext.jsx:36-37`) —
no network involved.

---

## 9. Passwords and brute force

* **Hashing:** argon2 (`core/security.py:22`). `MIN_PASSWORD_LENGTH = 8` is the hard floor
  (`security.py:15`); the real rules (length, common passwords, not your own e-mail name) live in
  `services/security_rules.py:167` (`check_password_policy`).
* **Three rate limits** (`core/config.py:137-141`): 5 failures per e-mail+IP / 15 min, 30 per IP / 15 min,
  20 per e-mail / 60 min. Only **failures** count, and the decision is made by a pure function,
  `decide_login` (`security_rules.py:95`).
* A blocked login answers **429** with `Retry-After` seconds, and the login page counts down.
* A password longer than 128 characters is rejected immediately without hashing
  (`auth_service.py:41`) — that stops a "hash a 1 MB password" CPU attack.
* Unlocking an account: `backend/app/cli/unlock_login.py` (deletes that e-mail's attempt rows).
* **Forced first change:** an admin-chosen password sets `must_change_password`; the gate in
  `deps.py:71` blocks everything else until the employee picks their own
  (`services/password_rules.py`). Their own change needs only the new password (D-198).

---

## 10. Frontend: where the token lives

```js
// frontend/src/api/client.js:9
let accessToken = null            // module variable, not localStorage
```

* `client.js:25` deletes the old `lms_token` key that an earlier version kept in `localStorage`.
* **Reload** → memory is empty → `restoreSession()` (`client.js:86`) calls `/auth/refresh` (cookie is
  still there) → gets a new access token → then `AuthContext` loads `/auth/me`
  (`AuthContext.jsx:55-56`). One refresh only, even with React's double render in development.
* **Route protection** is `frontend/src/auth/ProtectedRoute.jsx`: not logged in → `/login` (line 21),
  wrong role → a "no access" screen (line 24). The sidebar also hides links by role, but that is only
  cosmetics — the API is the real gate.
* **After login** the app goes to `/` (Home), or to `/account` when a password change is required
  (`LoginPage.jsx:38`).

See it yourself: DevTools → **Network** → `login` → the response body contains `access_token`; the
cookie shows under **Application → Cookies** with `HttpOnly ✓`, `Path=/auth`, `SameSite=Lax`. Open
`/auth/refresh` and you will see the token rotate after 15 minutes.

---

## 11. When something looks broken

| Symptom | Real cause | Fix |
| --- | --- | --- |
| Logged in, then logged out on the next reload | the page and the API are on **different hosts** (`localhost` vs `127.0.0.1` are different sites → the `SameSite` cookie is not sent) | open `http://localhost:5173`, and keep `VITE_API_URL=http://localhost:8000` |
| Everything answers **403** with `X-Password-Change-Required` | the forced password change is pending | open **My account** and set a new password |
| **409 REFRESH_RACE** in the console | two tabs refreshed at the same instant | harmless; the client retries after 1 s |
| **429** on login | too many wrong passwords | wait for the countdown, or `python -m app.cli.unlock_login --email …` |
| **401** immediately after login | clock skew, or `JWT_SECRET` changed (every old token is invalid) | check the server clock; changing the secret logs everybody out |

---

## 12. File map (open these in order)

| File | Responsibility | Start at |
| --- | --- | --- |
| `backend/app/routers/auth.py` | the HTTP endpoints | line 42 (cookie), 75 (login), 101 (refresh) |
| `backend/app/services/auth_service.py` | the real logic: login, issue, rotate, logout | 116, 214, 265, 345 |
| `backend/app/core/security.py` | JWT build/decode, argon2 | 22, 35, 50 |
| `backend/app/core/deps.py` | who is calling; role + password-change gates | 38, 84 |
| `backend/app/services/security_rules.py` | pure rules: classify refresh, limits, policy | 33, 95, 167 |
| `backend/app/models/auth_tokens.py` | `refresh_token`, `login_attempt` tables | 21, 65 |
| `backend/app/services/sessions.py` | the device list and per-device revoke | 33, 69 |
| `backend/app/main.py` | CORS + security headers | 65, 94 |
| `frontend/src/api/client.js` | token in memory, header, 401 retry | 9, 86, 94, 99 |
| `frontend/src/api/refreshCoordinator.js` | one refresh at a time, races | 11, 25 |
| `frontend/src/auth/AuthContext.jsx` | restore, login, logout, cross-tab | 36, 55, 73, 88 |

---

## 13. One-paragraph summary to say out loud

"You type your password once. The server checks the argon2 hash, gives you a **15-minute signed
token** that proves who you are, and puts a **7-day secret in an httpOnly cookie** that JavaScript
cannot read. Every request carries the short token; the server verifies the signature and reloads your
account so a deactivation or a role change applies immediately. When the short token expires you get a
**401**, the page silently trades the cookie for a new pair (the old refresh token is destroyed and any
replay is treated as theft), and the request is retried — so you never see it. Logout kills that whole
chain, and 'sign out everywhere' kills every chain you have."
