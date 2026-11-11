import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]

DEFAULT_ENV_FILE = ".env"


def env_file_name() -> str:
    """Resolve the active settings file name from LMS_ENV_FILE or default .env."""
    name = (os.environ.get("LMS_ENV_FILE") or "").strip()
    return name or DEFAULT_ENV_FILE


def _to_asyncpg_url(url: str) -> str:
    """Convert standard PostgreSQL URLs and sslmode query params for asyncpg."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix):]
            break
    else:
        return url

    parts = urlsplit(url)
    if not parts.query:
        return url

    params: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key != "sslmode":
            params.append((key, value))
        elif value != "disable":
            params.append(("ssl", "require" if value == "require" else value))

    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment)
    )


_selected_env_file = Path(env_file_name())
if not _selected_env_file.is_absolute():
    _selected_env_file = BACKEND_DIR / _selected_env_file
if os.environ.get("LMS_ENV_FILE") and not _selected_env_file.exists():
    raise RuntimeError(
        f"LMS_ENV_FILE points at '{_selected_env_file.name}', which does not exist. "
        "Copy backend/.env.demo.example to backend/.env.demo first."
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_selected_env_file),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project_name: str = "Leave Management System API"

    database_url: str
    db_statement_cache_disabled: bool = False

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 480

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    media_dir: str = str(BACKEND_DIR / "media")
    max_upload_bytes: int = 5 * 1024 * 1024

    email_backend: str = "console"
    email_from: str = "leave-management@example.invalid"
    email_file_dir: str = str(BACKEND_DIR / "outbox_dev")
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    frontend_base_url: str = "http://localhost:5173"
    notify_cc_admin_emails: str = ""
    notify_cc_admins_on_final: bool = False
    org_timezone: str = "UTC"
    reminder_after_working_days: int = 2
    enable_approval_reminders: bool = False
    email_max_attempts: int = 5
    embedded_email_worker: bool = True
    embedded_worker_interval_seconds: int = 5

    export_max_rows: int = 50000

    app_env: str = "development"
    refresh_token_days: int = 7
    refresh_family_max_days: int = 30
    refresh_reuse_grace_seconds: int = 10
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    trusted_proxy_count: int = 0
    ip_hash_key: str = ""
    login_pair_limit: int = 5
    login_pair_window_minutes: int = 15
    login_ip_limit: int = 30
    login_ip_window_minutes: int = 15
    login_email_limit: int = 20
    login_email_window_minutes: int = 60
    enable_docs: bool | None = None

    retention_login_attempt_days: int = 30
    retention_refresh_token_days: int = 30
    retention_sent_email_days: int = 90
    retention_stale_email_minutes: int = 60
    cleanup_batch_size: int = 1000

    @property
    def async_database_url(self) -> str:
        return _to_asyncpg_url(self.database_url)

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def media_path(self) -> Path:
        path = Path(self.media_dir)
        return path if path.is_absolute() else BACKEND_DIR / path

    @property
    def email_outbox_dir(self) -> Path:
        path = Path(self.email_file_dir)
        return path if path.is_absolute() else BACKEND_DIR / path

    @property
    def docs_enabled(self) -> bool:
        if self.enable_docs is not None:
            return self.enable_docs
        return str(self.app_env).lower() != "production"

    @property
    def notify_cc_admin_emails_list(self) -> list[str]:
        return [
            address.strip()
            for address in self.notify_cc_admin_emails.split(",")
            if address.strip()
        ]


settings = Settings()
