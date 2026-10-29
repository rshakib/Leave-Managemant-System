"""Tests for the pure attachment-key rules."""

import datetime

import pytest

from app.services.storage_rules import (
    StorageKeyError,
    build_storage_key,
    content_type_for_extension,
    is_valid_storage_key,
)

NOW = datetime.datetime(2026, 10, 26, 12, 0)
HEX = "4f3a1c2b9d8e7f6a5b4c3d2e1f0a9b8c"


def test_a_new_key_uses_the_dated_format():
    key = build_storage_key(NOW, HEX, "pdf")
    assert key == f"attachments/2026/10/{HEX}.pdf"
    assert is_valid_storage_key(key) is True


@pytest.mark.parametrize("extension", ["pdf", "png", "jpg", "jpeg", "PDF", ".png"])
def test_every_allowed_extension(extension):
    assert build_storage_key(NOW, HEX, extension).endswith(
        f".{extension.lower().lstrip('.')}"
    )


@pytest.mark.parametrize("extension", ["exe", "gif", "svg", "pdf.exe", "", "../pdf"])
def test_a_disallowed_extension_is_refused(extension):
    with pytest.raises(StorageKeyError):
        build_storage_key(NOW, HEX, extension)


@pytest.mark.parametrize("bad", ["short", "XYZ", "4f3a1c2b9d8e7f6a5b4c3d2e1f0a9b8Z", ""])
def test_a_bad_random_part_is_refused(bad):
    with pytest.raises(StorageKeyError):
        build_storage_key(NOW, bad, "pdf")


def test_the_old_local_key_format_is_still_accepted():
    # Files uploaded before Phase 16D-2 live at the flat old path (D-179).
    assert is_valid_storage_key(f"{HEX}.pdf") is True


@pytest.mark.parametrize(
    "key",
    [
        "",
        "/attachments/2026/10/" + HEX + ".pdf",
        "attachments/2026/10/../../etc/passwd.pdf",
        "attachments/../" + HEX + ".pdf",
        "..\\attachments\\" + HEX + ".pdf",
        "attachments\\2026\\10\\" + HEX + ".pdf",
        "attachments/2026/10/" + HEX.upper() + ".pdf",
        "attachments/2026/10/" + HEX + ".exe",
        "attachments/2026/10/" + HEX + ".pdf\x00.png",
        "attachments/2026/10/" + HEX + ".pdf/extra",
        "attachments/2026/1/" + HEX + ".pdf",
        "attachments/26/10/" + HEX + ".pdf",
        "attachments/2026/10/" + HEX + "a.pdf",
        "attachments/2026/10/" + HEX + ".pdf ",
        ".hidden/" + HEX + ".pdf",
        "attachments/2026/10/" + HEX + ".pdf\n",
    ],
)
def test_bad_keys_are_refused(key):
    assert is_valid_storage_key(key) is False


def test_a_non_string_key_is_refused():
    assert is_valid_storage_key(None) is False
    assert is_valid_storage_key(123) is False


@pytest.mark.parametrize(
    ("extension", "content_type"),
    [("pdf", "application/pdf"), ("png", "image/png"),
     ("jpg", "image/jpeg"), ("jpeg", "image/jpeg")],
)
def test_content_types(extension, content_type):
    assert content_type_for_extension(extension) == content_type
    assert content_type_for_extension(extension.upper()) == content_type


def test_an_unknown_extension_has_no_content_type():
    with pytest.raises(StorageKeyError):
        content_type_for_extension("exe")
