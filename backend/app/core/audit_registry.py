AUDITED = "audited"

AUDIT_REGISTRY: dict[str, str] = {
    "POST /divisions": AUDITED,
    "DELETE /divisions/{division_id}": AUDITED,
    "PATCH /divisions/{division_id}": AUDITED,
    "POST /departments": AUDITED,
    "DELETE /departments/{department_id}": AUDITED,
    "PATCH /departments/{department_id}": AUDITED,
    "POST /employees": AUDITED,
    "PATCH /employees/{employee_id}": AUDITED,
    "PUT /employees/{employee_id}/approvers": AUDITED,
    "POST /leave-years": AUDITED,
    "PATCH /leave-years/{year_id}": AUDITED,
    "POST /leave-years/{year_id}/activate": AUDITED,
    "POST /leave-years/{year_id}/close": AUDITED,
    "POST /leave-types": AUDITED,
    "PATCH /leave-types/{type_id}": AUDITED,
    "POST /leave-assignments": AUDITED,
    "DELETE /leave-assignments/{balance_id}": AUDITED,
    "POST /leave-balances/{balance_id}/adjust": AUDITED,
    "POST /leave-assignments/bulk": AUDITED,
    "PUT /weekends/global": AUDITED,
    "PUT /weekends/employees/{employee_id}": AUDITED,
    "DELETE /weekends/employees/{employee_id}": AUDITED,
    "POST /holidays": AUDITED,
    "PATCH /holidays/{holiday_id}": AUDITED,
    "DELETE /holidays/{holiday_id}": AUDITED,
    "POST /holidays/import": AUDITED,
    "POST /leave-requests": AUDITED,
    "POST /leave-requests/{request_id}/approve": AUDITED,
    "POST /leave-requests/{request_id}/reject": AUDITED,
    "POST /leave-requests/{request_id}/cancel": AUDITED,
    "POST /approvals/quick-decide": AUDITED,
    "POST /leave-requests/{request_id}/curtail": AUDITED,
    "POST /curtailments/{curtailment_id}/approve": AUDITED,
    "POST /curtailments/{curtailment_id}/reject": AUDITED,
    "DELETE /curtailments/{curtailment_id}": AUDITED,
    "POST /admin/emails/process-queue": (
        "exempt: runs the email worker once; a system action, not a data change (D-148)."
    ),
    "POST /auth/login": AUDITED,
    "POST /auth/refresh": AUDITED,
    "POST /auth/logout": (
        "exempt: ending one session touches no business data and leaves no row "
        "worth auditing (the refresh token is simply marked revoked)"
    ),
    "POST /auth/logout-all": AUDITED,
    "POST /auth/change-password": AUDITED,
    "POST /auth/forgot-password": (
        "exempt: public request to trigger reset link; logged and rate-limited via security rules."
    ),
    "POST /auth/reset-password": AUDITED,
    "DELETE /auth/sessions/{session_id}": AUDITED,
    "POST /admin/emails/{email_id}/retry": (
        "exempt: a delivery retry is a SYSTEM action, already recorded on the "
        "email row and in email_attempt (DECISIONS D-148)"
    ),
}
