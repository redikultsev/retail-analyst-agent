import pytest
from typer.testing import CliRunner

from retail_agent.cli import app

runner = CliRunner()


def test_chat_names_missing_variables_and_exits_with_code_2():
    result = runner.invoke(app, ["chat", "--user", "alice"])

    assert result.exit_code == 2
    assert "GOOGLE_CLOUD_PROJECT" in result.output
    assert "GOOGLE_API_KEY" in result.output


def test_chat_session_runs_until_exit(required_env):
    result = runner.invoke(app, ["chat", "--user", "alice"], input="monthly revenue\nexit\n")

    assert result.exit_code == 0
    assert "not connected yet" in result.output


def test_chat_requires_a_user(required_env):
    result = runner.invoke(app, ["chat"])

    assert result.exit_code == 2
    assert "--user" in result.output


def test_chat_says_who_is_signed_in_and_what_they_see(required_env):
    result = runner.invoke(app, ["chat", "--user", "ben"], input="exit\n")

    assert result.exit_code == 0
    assert "Ben Ortiz" in result.output
    assert "Diesel" in result.output


def test_chat_rejects_an_unknown_user_and_lists_the_known_ones(required_env):
    result = runner.invoke(app, ["chat", "--user", "dave"])

    assert result.exit_code == 2
    assert "dave" in result.output
    assert "alice" in result.output


def test_users_lists_people_with_their_brands(required_env):
    result = runner.invoke(app, ["users"])

    assert result.exit_code == 0
    for text in ("alice", "Alice Carter", "all brands", "ben", "Joe's Jeans", "chloe"):
        assert text in result.output


def test_data_directory_comes_from_the_environment(required_env, monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "elsewhere"))

    runner.invoke(app, ["users"])

    assert (tmp_path / "elsewhere" / "retail_agent.db").exists()


@pytest.mark.parametrize("command", [["users"], ["chat", "--user", "alice"]])
def test_unusable_data_directory_is_reported_without_a_traceback(
    required_env, monkeypatch, tmp_path, command
):
    (tmp_path / "taken").write_text("not a folder")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "taken"))

    result = runner.invoke(app, command)

    assert result.exit_code == 2
    assert "profile database" in result.output
