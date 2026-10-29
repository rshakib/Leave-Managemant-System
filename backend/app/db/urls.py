"""Where the database URL is understood (D-203).

Supabase hands out two different URLs, and asyncpg cares which one you use:

* **Session pooler / direct**, port **5432** — a normal connection, prepared
  statements are fine.
* **Transaction pooler** (pgbouncer), port **6543** — connections are shared
  between clients, so a prepared statement can be "already taken" on the server
  session it lands on, and asyncpg fails with a confusing error. The cure is
  `statement_cache_size=0` (never cache prepared statements, so every statement is
  parsed per use).

`connect_args_for()` returns the right arguments for whichever URL is configured,
so pasting either Supabase URL just works.
"""

from urllib.parse import urlsplit

# Ports that mean "behind pgbouncer, do not cache prepared statements".
POOLER_PORTS = frozenset({6543})


def _host_port(url: str) -> tuple[str, int | None]:
    try:
        parts = urlsplit(url or "")
        port = parts.port
    except ValueError:  # a broken/absent port must never crash the app
        return "", None
    return (parts.hostname or "").lower(), port


def is_pooled(url: str) -> bool:
    """True only for the TRANSACTION pooler, where prepared statements are unsafe.

    The port decides, not the hostname: Supabase's **session** pooler is also on
    `*.pooler.supabase.com`, but it keeps one server session per client, so
    prepared statements work there (port 5432) whereas they do not through the
    transaction pooler (port 6543).
    """
    _host, port = _host_port(url)
    return port in POOLER_PORTS


def connect_args_for(url: str, *, force: bool = False) -> dict:
    """The asyncpg arguments this URL needs (empty dict when none are needed).

    `force` lets an operator turn prepared statements off for an unusual pooler
    that does not use the standard port (DB_STATEMENT_CACHE_DISABLED=true).
    """
    if force or is_pooled(url):
        return {"statement_cache_size": 0}
    return {}
