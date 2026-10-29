"""The LMS_ENV_FILE switch (Task 2a)."""

import importlib

import pytest

from app.core import config as config_module


@pytest.fixture
def restore_config(monkeypatch):
    """Reload again afterwards so other tests see the normal settings again.

    The variable is removed FIRST, otherwise the reload would hit the same
    "file does not exist" guard the test just provoked.
    """
    yield
    monkeypatch.delenv("LMS_ENV_FILE", raising=False)
    importlib.reload(config_module)


def test_the_default_file_is_dot_env(monkeypatch, restore_config):
    monkeypatch.delenv("LMS_ENV_FILE", raising=False)
    importlib.reload(config_module)
    assert config_module.env_file_name() == ".env"


def test_lms_env_file_selects_another_file(tmp_path, monkeypatch, restore_config):
    env = tmp_path / "demo.env"
    env.write_text(
        "DATABASE_URL=postgresql://u:p@localhost:5432/demo_case_test\n"
        "JWT_SECRET=test-only-not-a-real-secret-value\n"
        "PROJECT_NAME=Demo Project Marker\n"
        "ORG_TIMEZONE=Asia/Dhaka\n"
    )
    monkeypatch.setenv("LMS_ENV_FILE", str(env))
    importlib.reload(config_module)

    assert config_module.env_file_name() == str(env)
    assert config_module.settings.project_name == "Demo Project Marker"
    assert config_module.settings.org_timezone == "Asia/Dhaka"


def test_an_empty_variable_falls_back_to_dot_env(monkeypatch, restore_config):
    monkeypatch.setenv("LMS_ENV_FILE", "   ")
    importlib.reload(config_module)
    assert config_module.env_file_name() == ".env"


def test_a_missing_file_is_reported_clearly(tmp_path, monkeypatch, restore_config):
    monkeypatch.setenv("LMS_ENV_FILE", str(tmp_path / "nope.env"))
    with pytest.raises(RuntimeError) as error:
        importlib.reload(config_module)
    assert "does not exist" in str(error.value)
    assert "CHANGE_ME" not in str(error.value)


def test_switching_prints_nothing(tmp_path, monkeypatch, restore_config, capsys):
    env = tmp_path / "quiet.env"
    env.write_text(
        "DATABASE_URL=postgresql://u:p@localhost:5432/demo_case_test\n"
        "JWT_SECRET=test-only-not-a-real-secret-value\n"
    )
    monkeypatch.setenv("LMS_ENV_FILE", str(env))
    importlib.reload(config_module)
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""
    assert "test-only-not-a-real-secret-value" not in captured.out
