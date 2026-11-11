from urllib.parse import urlsplit

POOLER_PORTS = frozenset({6543})


def _host_port(url: str) -> tuple[str, int | None]:
    try:
        parts = urlsplit(url or "")
        port = parts.port
    except ValueError:
        return "", None
    return (parts.hostname or "").lower(), port


def is_pooled(url: str) -> bool:
    """Return True when the URL points to a transaction pooler (port 6543)."""
    _host, port = _host_port(url)
    return port in POOLER_PORTS


def connect_args_for(url: str, *, force: bool = False) -> dict:
    """Return asyncpg connection arguments (disable prepared statement cache for poolers)."""
    if force or is_pooled(url):
        return {"statement_cache_size": 0}
    return {}
