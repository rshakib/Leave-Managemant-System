"""The Content-Security-Policy used by the frontend host (D-180).

Written once here, reused by deploy/Caddyfile, and asserted by a test so the two
can never drift apart.
"""

PLACEHOLDER_ORIGIN = "{$API_ORIGIN}"


class CspError(ValueError):
    """The API origin is not something we are willing to put in a header."""


def _check_origin(api_origin: str) -> str:
    origin = (api_origin or "").strip()
    if origin == PLACEHOLDER_ORIGIN:
        # Caddy substitutes this at start-up; the shape is validated at deploy time.
        return origin
    if not origin.startswith("https://"):
        raise CspError("the API origin must use https.")
    body = origin[len("https://"):]
    if not body or "/" in body or '"' in body or "'" in body or ";" in body or " " in body:
        raise CspError("the API origin must be a bare host with no path or quotes.")
    return origin


def build_csp(api_origin: str) -> str:
    """The exact policy string served with every frontend response."""
    origin = _check_origin(api_origin)
    directives = [
        "default-src 'self'",
        # No 'unsafe-inline' and no 'unsafe-eval': a script injected into the page
        # cannot run, which is the XSS defence-in-depth behind React's escaping.
        "script-src 'self'",
        # react-bootstrap writes inline style attributes, so styles need this one.
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
