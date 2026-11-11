"""Content-Security-Policy header builder shared with the Caddy configuration."""

PLACEHOLDER_ORIGIN = "{$API_ORIGIN}"


class CspError(ValueError):
    pass


def _check_origin(api_origin: str) -> str:
    origin = (api_origin or "").strip()
    if origin == PLACEHOLDER_ORIGIN:
        return origin
    if not origin.startswith("https://"):
        raise CspError("the API origin must use https.")
    body = origin[len("https://"):]
    if not body or "/" in body or '"' in body or "'" in body or ";" in body or " " in body:
        raise CspError("the API origin must be a bare host with no path or quotes.")
    return origin


def build_csp(api_origin: str) -> str:
    origin = _check_origin(api_origin)
    directives = [
        "default-src 'self'",
        "script-src 'self'",
        # Needed for react-bootstrap inline style attributes.
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self'",
        f"connect-src 'self' {origin}",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "upgrade-insecure-requests",
    ]
    return "; ".join(directives)
