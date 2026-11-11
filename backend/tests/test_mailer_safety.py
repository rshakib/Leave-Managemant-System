import logging
from app.core.config import settings
from app.services.mailer import Message, send, PROTECTED_RECIPIENT_EMAILS


def test_mailer_filters_boss_emails(monkeypatch, caplog):
    sent_messages = []

    def mock_send_console(email):
        sent_messages.append(email)

    monkeypatch.setattr("app.services.mailer._send_console", mock_send_console)
    monkeypatch.setattr(settings, "email_backend", "console")

    msg = Message(
        to=["raton.hosen@solshare.com", "other@example.com"],
        cc=["ishtiaque.ahmed@solshare.com", "admin@example.com"],
        subject="Test Safety Subject",
        text="Test body",
        html="<p>Test</p>",
    )

    with caplog.at_level(logging.WARNING):
        backend = send(msg)

    assert backend == "console"
    assert len(sent_messages) == 1
    sent_email = sent_messages[0]
    # Check that boss emails are strictly absent
    to_header = sent_email.get("To") or ""
    cc_header = sent_email.get("Cc") or ""
    assert "raton.hosen@solshare.com" not in to_header
    assert "ishtiaque.ahmed@solshare.com" not in cc_header
    assert "other@example.com" in to_header
    assert "admin@example.com" in cc_header


def test_mailer_suppresses_when_only_boss_emails_targeted(monkeypatch, caplog):
    called = []

    def mock_send_smtp(email):
        called.append(email)

    monkeypatch.setattr("app.services.mailer._send_smtp", mock_send_smtp)
    monkeypatch.setattr(settings, "email_backend", "smtp")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")

    msg = Message(
        to=["raton.hosen@solshare.com"],
        cc=["ishtiaque.ahmed@solshare.com"],
        subject="Only Bosses Targeted",
        text="Should be blocked",
        html="<p>Blocked</p>",
    )

    with caplog.at_level(logging.WARNING):
        backend = send(msg)

    # Must return blocked_safety and NEVER call smtp
    assert backend == "blocked_safety"
    assert len(called) == 0
    assert any("BOSS EMAIL SAFETY GUARD" in record.message for record in caplog.records)
