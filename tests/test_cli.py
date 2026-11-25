import pytest
from typer.testing import CliRunner

from retail_agent.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


def test_chat_names_missing_variables_and_exits_with_code_2():
    result = runner.invoke(app, ["chat"])

    assert result.exit_code == 2
    assert "GOOGLE_CLOUD_PROJECT" in result.output
    assert "GOOGLE_API_KEY" in result.output


def test_chat_session_runs_until_exit(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "acme-analytics")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    result = runner.invoke(app, ["chat"], input="monthly revenue\nexit\n")

    assert result.exit_code == 0
    assert "not connected yet" in result.output
