# Demo Guide — showing the Leave Management System on your laptop

This guide is for showing the app to your company on a screen share, with **no domain and no
deployment**. The app reads its settings from **`backend/.env`**, so it talks to whichever Supabase database
that file points at — there is no separate demo database. No real e-mail is sent (delivery
is switched off).

Total demo time: **10–12 minutes**.

---

## 1. One-time setup (about 15 minutes, do this the day before)

### 1.1 Use your Supabase project

`DATABASE_URL` in `backend/.env` decides which database the whole app uses — there is no separate demo
database (D-205). Two honest options:

* **Your existing project.** Simplest, but demo rows land in the same database you work in, and the
  append-only audit log keeps that activity for ever (see §5).
* **A fresh Supabase project that you delete afterwards.** The cleanest choice if you want the demo
  database to be throw-away: create it, copy its connection string into `backend/.env`, and follow the
  steps below.

### 1.2 Point the app at your database (once)

`backend/.env` is the **only** settings file — the API, alembic and the worker all read it. Put your
Supabase connection string in `DATABASE_URL` (a plain `postgresql://` paste is fine; the app rewrites it
for asyncpg itself), then generate the two secrets:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste one value into `JWT_SECRET` and a second one into `IP_HASH_KEY`. Leave the rest as it is:
`EMAIL_BACKEND=console` (delivery switched off — see below), `STORAGE_BACKEND=local`,
`COOKIE_SECURE=false`, `ACCESS_TOKEN_MINUTES=15`.

### 1.3 Create the tables

```bash
cd backend
./venv/bin/alembic upgrade head
```

### 1.4 Create one admin

```bash
python -m app.cli.seed_admin
```

It asks for a full name, an e-mail and a password (typed with `getpass`, never printed). This is
your **demo admin** — the account you will use for the admin half of the story. It creates
"Head Office" / "Administration" as the first division and department.

### 1.5 Optionally fill it with a fictional company

```bash
python -m app.cli.demo_data --i-understand-this-is-a-demo-database --allow-remote-demo-database --allow-real-database
```

It asks for the demo admin's e-mail and password (used only to sign in; never stored), then builds,
**through the app's own API**:

| What | Details |
| --- | --- |
| Divisions | Operations, Corporate Services (+ Head Office from step 1.4) |
| Departments | Field Operations, Technical Services, Human Resources, Finance (+ Administration) |
| Leave year | the current year, active |
| Leave types | Annual Leave (AL, 20 days, carry-forward capped at 5), Sick Leave (SL, 10), Half Day Leave (HL, 5) |
| Weekend | Friday + Saturday (only if none was configured) |
| Holidays | 8 examples (public and company) |
| Employees | `DEMO-001` … `DEMO-010`, Bengali names, designations and supervisors |
| Approvers | one approver for most, **two** for Nusrat Jahan and Sadia Rahman, the head approves for the team |
| Assignments | 22 balances (AL + SL for everyone, HL for the HR pair) |
| Requests | 3 Pending, 3 Approved (one half-day, one cross-month, one around a holiday), 1 Rejected with a comment, 1 Cancelled, 1 Pending **with a sample PDF attached** |
| Balance adjustment | one example (Mahmudul Hasan, AL +2 days, with a reason) |
| Credentials | `backend/demo_credentials.txt` — mode `600`, git-ignored |

Every date is chosen by asking the app's own `/calendar/preview`, so weekends and holidays are
always respected.

**Running the command twice is safe.** The second run reuses the password already recorded in
`backend/demo_credentials.txt` (it never silently invents a new one, which would lock the demo
employees out) and creates nothing that already exists — only one sign-in is made, and no
balance, request or approver list is touched. If you **delete** the file and run again, the
command notices and sets one fresh shared password for all demo employees through the admin's
password-reset API, then rewrites the file. If a sign-in is ever refused, the command stops
immediately instead of retrying, so repeated failures never lock an account.

**Two things to note:**

* The demo employees' addresses end in `@demo.example.com`, because the API's own e-mail
  validation refuses `.invalid` addresses. That domain is reserved for documentation and can never
  receive mail.
* Running the command again within 15 minutes can hit the login rate limit (the run signs in as
  every demo employee). Wait 15 minutes if you need to re-run it. (Running it twice is otherwise
  safe: the password is reused and nothing is created twice.)
* **E-mail sending is switched off on purpose** (`EMAIL_BACKEND=console`). Messages are still built
  from the database queue and shown in **System → Email log**; nothing is delivered anywhere.

### 1.6 Open the credentials file

`backend/demo_credentials.txt` lists, one line per employee: code, e-mail, role(s) and the shared
password. Keep it open in a text editor **off** the screen share — you will need to type these
passwords during the demo, and you do not want them on the recording.

---

## 2. Demo day — start-up, in this order

Open three terminals in the project root.

```bash
# 1) The API
cd backend
./venv/bin/uvicorn app.main:app --port 8000

# 2) The worker (drains the e-mail queue; delivery itself is switched OFF)
cd backend
./venv/bin/python -m app.worker

# 3) The web app
cd frontend
npm run dev
```

Then open **one** address: **http://localhost:5173**

> Use `localhost`, **not** `127.0.0.1`. They are different "sites" for the browser, so the
> httpOnly refresh cookie set by one is not sent to the other — you would appear logged in and then
> be logged out on the first reload. In production both the app and the API sit on one domain
> (`app.example.com` + `api.example.com`), which is the same site and works the same way.
>
> The API's address comes from `frontend/.env` (`VITE_API_URL=http://localhost:8000`).

> **E-mail sending is deliberately switched off for this demo** (`EMAIL_BACKEND=console`).
> Nothing is delivered anywhere — there is no mail sandbox to start. The queue still works end to
> end, so every message is rendered, recorded and visible in **System → Email log**, which is what
> the story uses. Switching real delivery on later is one setting (`EMAIL_BACKEND=smtp`) plus an
> SMTP account.

---

## 3. The story (10–12 minutes, exact clicks)

Two browser windows, each with **its own browser profile** (Chrome → profile icon → Add):

* **Profile “Employee”** — the left window. You log in and out of it several times.
* **Profile “Admin”** — the right window. Stays logged in as your demo admin.

Everything below is a real menu item and a real button; the sidebar groups are
*My leave*, *Approvals*, *Administration*, *System*.

### 0:00 — 1:00 · Warm-up

Both windows: open `http://localhost:5173`. Log in in the **Admin** window with your demo admin.
Point out the sidebar: it only shows what your role allows (the Admin window has
*Administration* and *System*; an employee does not). The footer says `Signed in as <code>`.

### 1:00 — 3:30 · An employee asks for leave

In the **Employee** window, log in as **Nusrat Jahan** (`demo.002@demo.example.com`).

1. You land on **Home** — greeting, stat tiles, the month calendar, balances, recent requests.
2. Sidebar → **My leave → Request leave**.
3. Leave type **Annual Leave**, pick dates with the calendar picker, day type **Full day**, write a
   reason.
4. Point at the right-hand panel: **Balance impact** (chargeable days, remaining balance) and the
   day-by-day preview where weekends and holidays are clearly not charged. Nothing was typed by
   hand — the server calculated it.
5. Press **Submit request**, then click **My leave → My requests**: the request is **Pending**, and
   the reserved days have already left her available balance.
6. Click **Logout** (top right).

### 3:30 — 5:30 · Approver 1 says yes — and it is still Pending

Still in the **Employee** window, log in as **Rafiqul Islam** (`demo.001@demo.example.com`), the
head of field operations.

1. The sidebar shows **Approvals** with a red badge — those are the requests waiting for him.
2. Open **Approvals**, find Nusrat's request, press **Approve**.
3. Show that it is **still Pending**. This is the key business rule: Nusrat has **two** approvers
   and **every** approver must agree. Say it in one sentence: *"all must approve, in parallel."*
4. **Logout.**

### 5:30 — 7:00 · Approver 2 says yes — now it is Approved

Log in as **Farhana Akter** (`demo.004@demo.example.com`), HR officer.

1. **Approvals** → the same request → **Approve**.
2. Open the request: it is now **Approved**, and the approvals list shows both people with their
   decision times. The days moved from *pending* to *used*.

### 7:00 — 8:30 · The e-mails (recorded, not delivered)

In the **Admin** window, open **System → Email log**.

Show the messages for that sequence: the request was **submitted** (to both approvers), **one
approver approved** (to Nusrat, telling her who is still pending), and the request was **fully
approved** (to Nusrat, with her remaining balance). Each row carries its status.

Say: *"delivery is switched off in this demo, so nothing leaves this laptop — that is deliberate.
The messages are built from a queue inside the database, which means a mail problem can never lose
or block a leave decision, and switching real sending on is one setting plus an SMTP account."*

### 8:30 — 9:30 · A rejected request

Back in the **Employee** window, log in as **Tanvir Ahmed** (`demo.003@demo.example.com`).

1. **My leave → My requests** → the Sick Leave request is **Rejected**; open it and show the
   approver's **rejection comment**.
2. Point out that his balance is untouched — a rejection releases the reserved days.

### 9:30 — 11:00 · The admin side

In the **Admin** window:

1. **Administration → Assignments** — the grid of everybody's entitlements and balances.
   * Press **Adjust** on a row: field `ALLOCATED`, delta `+2`, a required **reason**; the preview
     shows the old and the new value before you commit. Press **Adjust** to confirm.
   * Press **Adjustment history** to show the ledger: each change has a reason, an author and a
     time, and nothing is ever edited — a mistake is corrected with the opposite entry.
   * (The demo already contains one such adjustment for Mahmudul Hasan.)
2. **Administration → Reports** — tab **Balances**, then **Download CSV**; open the file in a
   spreadsheet to show the Bengali names, the columns and the totals. Mention the
   **include reason** checkbox: reasons are private, so they are left out unless asked for.
3. **Administration → Leave years** — the active year → **Close year**. Show the **preview**: the
   carry-forward it *would* write for every employee and what is blocking it.
   **Do not press the final confirm button** — closing is irreversible and this demo database is
   your only copy.
4. **System → Audit log** — every important action, with who, what, when and the before/after
   values. Say: *"nobody can edit or delete this, not even a database administrator — a trigger
   refuses it, so it is evidence, not a screen."*
5. **System → Email log** — every message and its status (all `SENT`; the worker has drained the
   queue).

### 11:00 — 12:00 · Back to the employee

In the **Employee** window, log in again as **Nusrat Jahan**.

1. **My leave → My balances** — the total, broken down: allocated, carried forward, used, pending
   and available, per leave type, with the row for the request she just got approved.
2. Press **F5** (reload) — she is still logged in. That is the refresh cookie doing its job.
3. Optional, if someone asks "what if my dates clash?": **My leave → Calendar preview**, pick a
   range, and show which days would be charged.

**Close with one sentence:** *"Everything you just saw — the calculation, the all-must-approve
rule, the balance movement, the e-mails and the audit trail — happens inside database
transactions, so two approvers clicking at the same moment cannot double-charge anyone."*

---

## 4. Questions the company will ask (and honest answers)

| Question | Answer |
| --- | --- |
| Can we use it tomorrow? | The core is built and tested: org set-up, employees, leave types, assignments, balances, requests, approvals, cancellation, e-mail, reports, audit log. What is **not** built is listed below. |
| Two-factor login / SSO / "log in with Microsoft"? | Not built. Today: e-mail + password (argon2), short-lived access token, refresh cookie. |
| Mobile app? | No. The web app is responsive, so a phone browser works. |
| Payroll or attendance integration? | Not built. CSV export is the bridge today. |
| How do holidays get in? | An admin enters them (there is a CSV import, the date range expands into single days). The demo has 8 examples; the real calendar has to be entered by HR, and **optional** holidays are shown but never charged. |
| Time zones? | One organisation time zone (`ORG_TIMEZONE`). E-mail reminders follow it, and it is the one the demo uses. |
| Do the e-mails really go out? | Not in this demo — sending is switched off on purpose (`EMAIL_BACKEND=console`), so nothing leaves the laptop. The messages are still generated from the database queue and shown in **System → Email log**. Production needs an SMTP account. |
| An approver approved by mistake — can we undo it? | Not by cancelling: an **approved** request can never be cancelled, by anyone. An admin corrects the balance with a documented adjustment, and the old request stays as history (that is deliberate). |
| Can someone take more leave than they have? | No — the database itself refuses a negative available balance. An admin can grant extra days with an adjustment, which is recorded. |
| What about a new joiner mid-year? | The admin types the allocated days; automatic pro-rating is not built. |
| How many leave years at once? | Exactly one active year. Year-end closing is irreversible and only runs for a year that has ended with no pending requests. |
| Can an approved leave be undone? | Yes, by an administrator only: open the request and press **Cancel approved request** — the day(s) go back into the employee's available balance and the employee is e-mailed. The employee cannot cancel it themselves, and if the leave falls in a **closed** leave year it cannot be cancelled at all (the balance of a closed year must not move). |
| Can someone see where their account is signed in? | Yes — **My account → Where you are signed in** lists each browser ("Chrome on Windows", "Safari on iPhone"), when it started and when it was last used, and can sign one device out on its own. "Sign out of all devices" is right below it. |
| Do employees keep the password the admin typed for them? | No. The first time they sign in they must set their own password before they can use anything else (the demo accounts are exempt, because their password is handed over on paper). |
| Attachments? | PDF/PNG/JPG up to 5 MB, checked by extension **and** content. In the demo they are saved on this laptop. |

---

## 5. Resetting demo rows (read before you seed)

There is **no separate demo database** any more: demo rows go into the same Supabase project you use.
That has one consequence worth knowing before you run the seeder:

* **The audit log is append-only.** The activity a demo run writes stays for ever — a database trigger
  refuses `UPDATE`, `DELETE` and `TRUNCATE` (D-147), so nothing can tidy it up afterwards.
* The same is true of the adjustment ledger and the carry-forward log.

So seed demo rows only into a project you are happy to keep, or into a **fresh Supabase project** you
can delete afterwards. `python -m app.cli.demo_data` refuses a database that already holds real
employees unless you pass `--allow-real-database`, and that flag exists precisely to make you decide.

If you want a clean slate later, the only clean way is a new Supabase project: point `DATABASE_URL` at
it, run `alembic upgrade head`, then `seed_admin`, then `demo_data`.

## 6. Five-minute pre-demo checklist

- [ ] **E-mail sending is switched off** (`EMAIL_BACKEND=console` in `backend/.env`) — deliberate. Start the worker (§2) or press **Process Queue Now**, otherwise the rows stay Pending.
- [ ] The API was **restarted** after the last change to `backend/.env` (settings are read once at start-up).
- [ ] The worker is running (`./venv/bin/python -m app.worker`, §2) — it drains the e-mail queue; without it the messages stay Pending in the Email log.
- [ ] `npm run dev` is running and **http://localhost:5173** (not `127.0.0.1`) shows the login page.
- [ ] Two browser windows with **two different profiles** are open, both logged out.
- [ ] Five minutes before: log in once as your demo admin and once as `DEMO-002` to warm the
      session, then log out again.
- [ ] `backend/demo_credentials.txt` is open in a text editor that is **not** on the shared screen.
- [ ] Notifications muted (Slack/Teams, mail clients) so nothing pops up mid-story.
- [ ] You know the one irreversible button you must **not** press: the final confirm in
      **Leave years → Close year**.

---

*Related: `README.md` (how the system is built), `PLAN.md` (what is built in which phase),
`DECISIONS.md` (why each choice was made).*
