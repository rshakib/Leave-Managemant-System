"""Tests for the Content-Security-Policy builder."""

import pytest

from app.services.csp_rules import CspError, build_csp

ORIGIN = "https://api.example.com"

REQUIRED = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "upgrade-insecure-requests",
]


def test_every_required_directive_is_present():
    policy = build_csp(ORIGIN)
    for directive in REQUIRED:
        assert directive in policy


def test_connect_src_allows_self_and_the_api():
    assert f"connect-src 'self' {ORIGIN}" in build_csp(ORIGIN)


def test_script_src_has_no_unsafe_inline_or_eval():
    policy = build_csp(ORIGIN)
    script = [part for part in policy.split(";") if part.strip().startswith("script-src")][0]
    assert "unsafe-inline" not in script
    assert "unsafe-eval" not in script


def test_the_caddy_placeholder_is_allowed():
    assert "{$API_ORIGIN}" in build_csp("{$API_ORIGIN}")


@pytest.mark.parametrize(
    "origin",
    [
        "http://api.example.com",
        "api.example.com",
        "https://api.example.com/",
        "https://api.example.com/path",
        'https://api.example.com"; script-src *',
        "https://api.example.com; default-src *",
        "https://api example.com",
        "",
        None,
    ],
)
def test_a_dangerous_or_wrong_origin_is_rejected(origin):
    with pytest.raises(CspError):
        build_csp(origin)


def test_no_directive_can_be_injected_through_the_origin():
    policy = build_csp(ORIGIN)
    assert policy.count("script-src") == 1
    assert "unsafe-eval" not in policy
