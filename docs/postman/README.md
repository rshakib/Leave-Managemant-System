# Postman collection — Leave Management System API

Two files:

| File | What it is |
| --- | --- |
| `lms.postman_collection.json` | every route of the API (75 requests in 8 folders) |
| `lms.postman_environment.json` | `baseUrl`, `token`, `email`, `password` for your machine |

## Import (2 minutes)

1. Postman → **Import** → drag both files in (or *File → Import*).
2. Top-right dropdown → choose the environment **“LMS — local”**.
3. Open the environment and fill in `email` and `password` of a **test** account
   (never your production admin password). `baseUrl` is `http://localhost:8000`.
4. Run **Auth → POST /auth/login**. It stores the access token in `{{token}}` for you, and
   Postman’s cookie jar keeps the httpOnly `refresh_token` cookie.

After that every other request works — they all send `Authorization: Bearer {{token}}`.

## Notes

* **The access token lasts 15 minutes.** When you start getting `401`, run
  **Auth → POST /auth/refresh** once; it returns a new token and rotates the cookie.
* **Path variables** (`:year_id`, `:employee_id`, …) default to `1`. Replace them with the ids
  you actually created — every create request returns its new `id` in the response.
* **`POST /leave-requests` is multipart** (it accepts a file); fill the form fields in Postman.
* **Folders** follow the app: Health, Auth, Admin, Organisation & people, Leave configuration,
  Calendar, Leave requests & approvals, Reports.
* A few bodies contain placeholders (for example `reports` filters) — edit them freely.
* Never commit real tokens or passwords: the environment file you fill in stays on your machine.
