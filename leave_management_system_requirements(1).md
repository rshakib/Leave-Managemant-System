# Leave Management System — Requirements

## 1. Purpose

Web application to manage employee leave end-to-end: organisation setup, leave configuration, balance tracking, leave requests, multi-approver workflows, and email notifications.

## 2. Roles

| Role | Scope |
| ----- | ----- |
| **Admin (HR)** | Full configuration: divisions, departments, employees, leave types, assignments, approvers, weekends, holidays. Views all requests and balances; can override or adjust balances. |
| **Employee** | Submits and cancels own leave requests; views own balances and request history. |
| **Approver** | Employee designated to approve/reject leave requests for specific employees. |

A user may hold multiple roles (e.g. Employee + Approver).

## 3. Functional Requirements

### 3.1 Organisation Structure

* **FR-ORG-1** Admin can create, edit, deactivate, and list **Divisions** (name required, unique; status active/inactive).
* **FR-ORG-2** Admin can create, edit, deactivate, and list **Departments** under a Division (name required, unique within its division; status active/inactive). A division contains many departments; each department belongs to exactly one division.
* **FR-ORG-3** A division or department with active employees cannot be deleted, only deactivated.

### 3.2 Employees

* **FR-EMP-1** Admin can create, edit, deactivate, and list **Employees** with: employee code (unique), full name, email (unique), phone, joining date, employment status (active/inactive), division, department (must belong to the selected division), designation, and role(s).
* **FR-EMP-2** Each employee can have an optional **Reporting Supervisor** (another active employee; cannot be self or create a circular chain).
* **FR-EMP-3** Deactivating an employee revokes login and blocks new leave submissions while preserving historical data.

### 3.3 Leave Types & Assignment

* **FR-LT-1** Admin can create, edit, deactivate, and list **Leave Types** with: name (unique), code (unique, e.g. `AL`, `SL`, `CL`), default annual quota (days), accrual mode (`fixed` at start of year; future-ready for `monthly`), allow half-day (yes/no), require attachment after N consecutive days (optional), carry-forward allowed (yes/no), max carry-forward days (numeric, 0 if carry-forward disabled), and status.
* **FR-LT-2** Admin assigns eligible leave types to an employee (individually or in bulk by division/department) with an **allocated days** value for the active leave year (defaults to the leave type’s quota, overridable per employee).
* **FR-LT-3** For each assigned `(employee, leave_type, leave_year)` the system maintains a **Leave Balance**: `allocated`, `carried_forward`, `used`, `pending`, and `available = allocated + carried_forward − used − pending`.
* **FR-LT-4** At leave-year rollover, Admin can run a **Year-End Closing** action (or scheduled job) that, for each employee and each leave type with carry-forward enabled, transfers `min(remaining_available, max_carry_forward_days)` into the next leave year’s `carried_forward` balance and logs the transfer.

### 3.4 Approver Assignment

* **FR-APR-1** Admin can assign **one or more Approvers** to an employee.
* **FR-APR-2** By default, the employee’s Reporting Supervisor (if set) is pre-populated as an approver, and Admin may add/remove approvers.
* **FR-APR-3** **Approval rule (all-must-approve, parallel):** when a leave request is submitted, all assigned approvers are notified simultaneously.
  * The request becomes **Approved** only when **every** assigned approver approves it.
  * If **any** approver rejects it, the request immediately becomes **Rejected** and remaining pending approvals are closed.
  * An employee cannot be assigned as their own approver.

### 3.5 Weekend & Holiday Configuration

* **FR-CAL-1** Admin configures **Global Weekend Days** (e.g. Friday, Saturday).
* **FR-CAL-2** Admin can override weekend days for a specific employee (e.g. Sunday, Monday for roster staff). When calculating leave days for an employee, the employee-specific weekend applies if defined; otherwise the global weekend applies.
* **FR-CAL-3** Admin can create, edit, delete, and bulk-import (CSV) **Holidays** for a calendar/leave year with: date (or date range), title, type (`public`, `company`, `optional`), and applicability (`all` or scoped to specific divisions/departments).
* **FR-CAL-4** **Day calculation rule:** when an employee requests leave from `start_date` to `end_date`, chargeable leave days = total calendar days in range **minus** applicable weekend days **minus** applicable holidays. Half-day requests count as `0.5` if the single date is a working day. If chargeable days = `0`, submission is blocked.

### 3.6 Leave Request & Approval Workflow

* **FR-LR-1** Employee submits a leave request specifying: leave type, start date, end date, day type (`full_day` or `half_day — first_half / second_half`), reason, and optional attachment.
* **FR-LR-2** System validates before submission:
  1. `start_date <= end_date` (and `start_date == end_date` for half-day).
  2. Employee is assigned the selected leave type for the leave year.
  3. Chargeable days > 0.
  4. `chargeable_days <= available_balance` for that leave type.
  5. No overlap with an existing `Pending` or `Approved` request of the same employee.
  6. Employee has at least one active approver assigned.
* **FR-LR-3** On valid submission:
  * Request status is set to `Pending`.
  * Chargeable days are added to `pending` balance (reducing `available`).
  * One approval record per assigned approver is created with status `Pending`.
* **FR-LR-4** Each approver can **Approve** or **Reject** (rejection reason required) from the web app.
  * When all approvers have approved → request status = `Approved`; `pending` moves to `used`.
  * When any approver rejects → request status = `Rejected`; `pending` is released back to `available`.
* **FR-LR-5** Employee can **Cancel** own request while its status is `Pending` (releases `pending` balance). Cancelling an `Approved` request requires Admin action (restores `used` balance).

### 3.7 Email Notifications

* **FR-NOT-1** System sends transactional emails on the following events:

| Event | Recipients | Content Summary |
| ----- | ----- | ----- |
| Leave submitted | All assigned approvers (CC: employee) | Employee name, leave type, dates, chargeable days, reason, direct link to approve/reject. |
| Individual approver action (when others still pending) | Employee | Which approver approved, remaining pending approvers. |
| Request fully Approved | Employee (CC: all approvers, HR/Admin optional) | Final approval confirmation, updated remaining balance. |
| Request Rejected | Employee (CC: all approvers) | Rejecting approver name, rejection comment, restored balance. |
| Request Cancelled | All assigned approvers | Notification that the request was withdrawn. |
| Pending approval reminder | Approvers with pending action > 2 working days | Digest/reminder link. |

* **FR-NOT-2** Emails are dispatched asynchronously via a queue with retry on failure and logged for audit.

## 4. Non-Functional Requirements

* **NFR-1 Authentication & Security:** Role-based access control (RBAC) on all endpoints; password hashing (bcrypt/argon2) or SSO-ready JWT session; audit log for balance changes, configuration edits, and approval actions.
* **NFR-2 Concurrency & Integrity:** Balance updates and approval state transitions must run inside database transactions to prevent double-deduction or race conditions when multiple approvers act simultaneously.
* **NFR-3 Usability:** Responsive web UI; clear calendar preview showing weekends and holidays when selecting leave dates; real-time calculation of chargeable days and remaining balance before submit.
* **NFR-4 Reporting:** Admin can filter and export (CSV/Excel) leave balances and leave history by division, department, employee, leave type, status, and date range.

## 5. High-Level Data Model

### `division`

* `id` (PK)
* `name` (unique, not null)
* `is_active` (bool, default true)

### `department`

* `id` (PK)
* `division_id` (FK → `division.id`, not null)
* `name` (not null)
* `is_active` (bool, default true)
* *unique* `(division_id, name)`

### `employee`

* `id` (PK)
* `employee_code` (unique, not null)
* `full_name` (not null)
* `email` (unique, not null)
* `password_hash` (not null)
* `phone`
* `designation`
* `division_id` (FK → `division.id`, not null)
* `department_id` (FK → `department.id`, not null)
* `supervisor_id` (FK → `employee.id`, nullable)
* `joining_date` (date, not null)
* `roles` (set/array: `ADMIN`, `EMPLOYEE`, `APPROVER`)
* `is_active` (bool, default true)

### `employee_approver`

* `id` (PK)
* `employee_id` (FK → `employee.id`, not null)
* `approver_id` (FK → `employee.id`, not null)
* `is_active` (bool, default true)
* *unique* `(employee_id, approver_id)` — check `employee_id <> approver_id`

### `weekend_setting`

* `id` (PK)
* `employee_id` (FK → `employee.id`, nullable — `NULL` means global default)
* `days_of_week` (array of ints `0..6` where `0 = Sunday .. 6 = Saturday`, not null)
* `effective_from` (date, nullable)
* *unique* `(employee_id)`

### `leave_year`

* `id` (PK)
* `name` (e.g. `"2026"`, unique)
* `start_date` (date, not null)
* `end_date` (date, not null)
* `is_active` (bool)
* `is_closed` (bool, default false)

### `holiday`

* `id` (PK)
* `leave_year_id` (FK → `leave_year.id`, not null)
* `date` (date, not null)
* `title` (not null)
* `type` (`PUBLIC`, `COMPANY`, `OPTIONAL`)
* `division_id` (FK → `division.id`, nullable — `NULL` = all divisions)
* `department_id` (FK → `department.id`, nullable — `NULL` = all departments)

### `leave_type`

* `id` (PK)
* `code` (unique, not null)
* `name` (unique, not null)
* `default_quota` (decimal(5,2), not null)
* `allow_half_day` (bool, default true)
* `carry_forward_allowed` (bool, default false)
* `max_carry_forward_days` (decimal(5,2), default 0)
* `require_attachment_after_days` (int, nullable)
* `is_active` (bool, default true)

### `employee_leave_type` (eligibility & allocation per year)

* `id` (PK)
* `employee_id` (FK → `employee.id`, not null)
* `leave_type_id` (FK → `leave_type.id`, not null)
* `leave_year_id` (FK → `leave_year.id`, not null)
* `allocated_days` (decimal(5,2), not null)
* *unique* `(employee_id, leave_type_id, leave_year_id)`

### `leave_balance`

* `id` (PK)
* `employee_id` (FK → `employee.id`, not null)
* `leave_type_id` (FK → `leave_type.id`, not null)
* `leave_year_id` (FK → `leave_year.id`, not null)
* `allocated` (decimal(5,2), default 0)
* `carried_in` (decimal(5,2), default 0)
* `used` (decimal(5,2), default 0)
* `pending` (decimal(5,2), default 0)
* *(computed)* `available = allocated + carried_in - used - pending`
* *unique* `(employee_id, leave_type_id, leave_year_id)`

### `leave_carry_forward` (year-end rollover log)

* `id` (PK)
* `employee_id` (FK → `employee.id`, not null)
* `leave_type_id` (FK → `leave_type.id`, not null)
* `from_leave_year_id` (FK → `leave_year.id`, not null)
* `to_leave_year_id` (FK → `leave_year.id`, not null)
* `remaining_at_close` (decimal(5,2), not null)
* `carried_days` (decimal(5,2), not null)
* `forfeited_days` (decimal(5,2), not null)
* `processed_at` (timestamp, not null)
* `processed_by` (FK → `employee.id`, nullable)
* *unique* `(employee_id, leave_type_id, from_leave_year_id)`

### `leave_request`

* `id` (PK)
* `employee_id` (FK → `employee.id`, not null)
* `leave_type_id` (FK → `leave_type.id`, not null)
* `leave_year_id` (FK → `leave_year.id`, not null)
* `start_date` (date, not null)
* `end_date` (date, not null)
* `day_type` (`FULL_DAY`, `FIRST_HALF`, `SECOND_HALF`)
* `chargeable_days` (decimal(5,2), not null)
* `reason` (text, not null)
* `attachment_url` (nullable)
* `status` (`PENDING`, `APPROVED`, `REJECTED`, `CANCELLED`)
* `submitted_at` (timestamp, not null)
* `final_decided_at` (timestamp, nullable)

### `leave_request_approval`

* `id` (PK)
* `leave_request_id` (FK → `leave_request.id`, not null)
* `approver_id` (FK → `employee.id`, not null)
* `status` (`PENDING`, `APPROVED`, `REJECTED`, `SKIPPED`)
* `comment` (text, nullable)
* `acted_at` (timestamp, nullable)
* *unique* `(leave_request_id, approver_id)`

### `audit_log`

* `id` (PK)
* `actor_id` (FK → `employee.id`, nullable)
* `entity_type` (varchar)
* `entity_id` (bigint)
* `action` (varchar)
* `old_value` (jsonb)
* `new_value` (jsonb)
* `created_at` (timestamp, not null)

*All tables include standard audit columns (`created_at`, `updated_at`, `created_by`).*

## 6. Key Workflow Summary

```text
Employee submits request
        │
        ▼
Validate dates, holiday/weekend exclusion, balance, overlaps
        │
        ▼
Create leave_request (PENDING) + N leave_request_approval rows (PENDING)
Reserve chargeable_days in leave_balance.pending
Send email to all N approvers
        │
        ├──► Any approver REJECTS ──► Request = REJECTED
        │                             Remaining approvals = SKIPPED
        │                             Release pending balance
        │                             Email employee & approvers
        │
        └──► Approver APPROVES ────► All N approved?
                                        ├── No  ──► Stay PENDING (notify employee)
                                        └── Yes ──► Request = APPROVED
                                                    Move pending → used
                                                    Email employee & approvers
```

## 7. Open Questions (Confirm Before Build)

1. **Pro-rata allocation:** Should mid-year joiners automatically get pro-rated leave allocation, or does Admin enter the allocated days manually?
2. **Post-approval cancellation:** Can an employee request cancellation of an already-approved leave (requiring approver re-approval), or is cancellation strictly Admin-only after approval?
   only pending status cancel can possible by the employee. If the leave is approved then only admin can cancel it.
3. **Cross-year leave requests:** Should a single request spanning two leave years (e.g. 29 Dec – 3 Jan) be split automatically into two requests or blocked?
   allow
4. **Negative balance / advance leave:** Is negative balance ever allowed (with Admin override), or strictly blocked?
   block, if admin manually updates the leave count for a specific employee then he can take extra leaves.
5. **Can an employee view their remaining leave balances?**
   yes