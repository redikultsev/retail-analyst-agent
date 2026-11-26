from pathlib import Path

import pytest

from retail_agent.config import ConfigError, load_settings


def load():
    return load_settings(env_file=None)


def test_loads_required_settings(required_env):
    settings = load()

    assert settings.google_cloud_project == "acme-analytics"
    assert settings.google_api_key.get_secret_value() == "test-key"


def test_secret_is_hidden_when_printed(required_env):
    assert "test-key" not in repr(load())


def test_reports_every_missing_variable():
    with pytest.raises(ConfigError) as raised:
        load()

    assert raised.value.missing == ["GOOGLE_CLOUD_PROJECT", "GOOGLE_API_KEY"]


def test_empty_value_counts_as_missing(required_env, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "")

    with pytest.raises(ConfigError) as raised:
        load()

    assert raised.value.missing == ["GOOGLE_API_KEY"]


def test_reads_values_from_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("GOOGLE_CLOUD_PROJECT=acme-analytics\nGOOGLE_API_KEY=file-key\n")

    settings = load_settings(env_file=str(env_file))

    assert settings.google_api_key.get_secret_value() == "file-key"


def test_langfuse_is_off_without_keys(required_env):
    assert load().langfuse_enabled is False


def test_langfuse_is_on_with_both_keys(required_env, monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    assert load().langfuse_enabled is True


def test_data_directory_defaults_to_a_local_folder(required_env):
    assert load().data_dir == Path("data")


def test_data_directory_can_be_moved(required_env, monkeypatch):
    monkeypatch.setenv("DATA_DIR", "/var/lib/acme")

    assert load().data_dir == Path("/var/lib/acme")
