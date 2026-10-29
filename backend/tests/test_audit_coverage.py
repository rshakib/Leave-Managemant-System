"""Coverage guard: every write route is either audited or exempt with a reason."""

from app.core.audit_registry import AUDIT_REGISTRY
from app.main import app

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _walk(routes):
    found = []
    for route in routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            found.extend(_walk(original.routes))
        else:
            found.append(route)
    return found


def write_routes() -> set[str]:
    return {
        f"{method} {route.path}"
        for route in _walk(app.routes)
        for method in (getattr(route, "methods", None) or set())
        if method in WRITE_METHODS
    }


def test_the_app_really_has_write_routes():
    """Guards the test itself: an empty walk would make everything below pass."""
    assert len(write_routes()) > 20


def test_every_write_route_is_covered():
    missing = sorted(write_routes() - set(AUDIT_REGISTRY))
    assert missing == [], (
        "These write routes are not in AUDIT_REGISTRY — audit them or add an "
        f"'exempt: <reason>' entry: {missing}"
    )


def test_the_registry_names_no_route_that_no_longer_exists():
    stale = sorted(set(AUDIT_REGISTRY) - write_routes())
    assert stale == [], f"AUDIT_REGISTRY names routes that no longer exist: {stale}"


def test_every_exempt_entry_gives_a_reason():
    for route, verdict in AUDIT_REGISTRY.items():
        if verdict == "audited":
            continue
        assert verdict.startswith("exempt:"), f"{route} has an unknown verdict."
        reason = verdict.split("exempt:", 1)[1].strip()
        assert len(reason) >= 10, f"{route} is exempt but gives no real reason."
