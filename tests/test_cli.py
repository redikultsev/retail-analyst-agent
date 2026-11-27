import sqlite3
from decimal import Decimal

import pytest
from fakes import BrokenModel, FakeExecutor, ScriptedModel, brands
from langchain_core.messages import AIMessage
from typer.testing import CliRunner

from retail_agent.cli import app
from retail_agent.policy import Policy
from retail_agent.query_executor import Fetched, QueryRejected
from retail_agent.report_repository import ReportsUnavailable
from retail_agent.warehouse import Warehouse

runner = CliRunner()


@pytest.fixture
def warehouse(monkeypatch):
    def answer_with(executor):
        def build(settings, profile):
            return Warehouse(
                executor,
                Policy(scope=profile.scope),
                max_bytes=1_000_000,
                max_result_chars=20_000,
                secrets=(),
            )

        monkeypatch.setattr("retail_agent.cli.build_warehouse", build)

    answer_with(FakeExecutor(fetch=brands("Diesel", "Joe's Jeans", "Polo Ralph Lauren")))
    return answer_with


@pytest.fixture(autouse=True)
def model(monkeypatch):
    def build(**options):
        return ScriptedModel([AIMessage("Revenue is up.")])

    monkeypatch.setattr("retail_agent.di.ChatGoogleGenerativeAI", build)


def test_chat_names_missing_variables_and_exits_with_code_2():
    result = runner.invoke(app, ["chat", "--user", "alice"])

    assert result.exit_code == 2
    assert "GOOGLE_CLOUD_PROJECT" in result.output
    assert "GOOGLE_API_KEY" in result.output


def test_chat_answers_a_question_and_runs_until_exit(required_env, warehouse):
    result = runner.invoke(app, ["chat", "--user", "alice"], input="monthly revenue\nexit\n")

    assert result.exit_code == 0
    assert "Revenue is up." in result.output


def test_chat_requires_a_user(required_env):
    result = runner.invoke(app, ["chat"])

    assert result.exit_code == 2
    assert "--user" in result.output


def test_chat_says_who_is_signed_in_and_what_they_see(required_env, warehouse):
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


def test_chat_does_not_start_when_the_warehouse_is_not_ready(required_env, warehouse):
    warehouse(FakeExecutor(estimate=RuntimeError("no credentials found")))

    result = runner.invoke(app, ["chat", "--user", "ben"], input="exit\n")

    assert result.exit_code == 2
    assert "no credentials found" in result.output
    assert "Check GOOGLE_CLOUD_PROJECT" in result.output
    assert "Signed in" not in result.output


def test_brands_missing_from_the_data_are_reported_without_the_setup_hint(required_env, warehouse):
    warehouse(FakeExecutor(fetch=brands("Wacoal")))

    result = runner.invoke(app, ["chat", "--user", "ben"], input="exit\n")

    assert result.exit_code == 2
    assert "Diesel" in result.output
    assert "Check GOOGLE_CLOUD_PROJECT" not in result.output


def test_chat_warns_about_brands_missing_from_the_data_before_the_greeting(required_env, warehouse):
    warehouse(FakeExecutor(fetch=brands("Diesel")))

    result = runner.invoke(app, ["chat", "--user", "ben"], input="exit\n")

    assert result.exit_code == 0
    assert result.output.index("not found in the data") < result.output.index("Signed in")


def test_sql_prints_the_result_as_a_table(required_env, warehouse):
    warehouse(FakeExecutor(fetch=Fetched(("name", "revenue"), (("Jeans", Decimal("120.50")),), 1)))

    result = runner.invoke(app, ["sql", "SELECT name FROM products", "--user", "alice"])

    assert result.exit_code == 0
    for text in ("name", "revenue", "Jeans", "120.50"):
        assert text in result.output


def test_sql_prints_the_query_that_was_really_run(required_env, warehouse):
    warehouse(FakeExecutor())

    result = runner.invoke(app, ["sql", "SELECT name FROM products", "--user", "chloe"])

    assert "Polo Ralph Lauren" in result.output


def test_sql_prints_the_log_record(required_env, warehouse):
    result = runner.invoke(app, ["sql", "SELECT name FROM products", "--user", "alice"])

    assert "status=ok" in result.output
    assert "rows=3" in result.output


def test_sql_prints_why_a_query_was_refused(required_env, warehouse):
    result = runner.invoke(app, ["sql", "SELECT email FROM users", "--user", "alice"])

    assert result.exit_code == 1
    assert "status=denied" in result.output
    assert "pii_column" in result.output


def test_sql_hides_the_runtime_error_text_from_a_brand_manager(required_env, warehouse):
    warehouse(FakeExecutor(fetch=QueryRejected("LEAK:36/China")))

    result = runner.invoke(app, ["sql", "SELECT name FROM products", "--user", "ben"])

    assert "status=runtime_error" in result.output
    assert "LEAK" not in result.output
    assert "detail=[hidden" in result.output


def test_sql_shows_the_runtime_error_text_to_someone_who_sees_all_brands(required_env, warehouse):
    warehouse(FakeExecutor(fetch=QueryRejected("LEAK:36/China")))

    result = runner.invoke(app, ["sql", "SELECT name FROM products", "--user", "alice"])

    assert "detail=LEAK:36/China" in result.output


def test_sql_prints_square_brackets_as_they_are(required_env, warehouse):
    warehouse(FakeExecutor(fetch=Fetched(("name",), (("Acme [/]",),), 1)))

    result = runner.invoke(app, ["sql", "SELECT name FROM products", "--user", "alice"])

    assert "Acme [/]" in result.output


def test_sql_rejects_an_unknown_user(required_env, warehouse):
    result = runner.invoke(app, ["sql", "SELECT 1", "--user", "dave"])

    assert result.exit_code == 2
    assert "dave" in result.output


def test_chat_says_it_is_checking_access_before_the_greeting(required_env, warehouse):
    result = runner.invoke(app, ["chat", "--user", "ben"], input="exit\n")

    assert result.output.index("Checking access") < result.output.index("Signed in")


def test_chat_uses_the_models_named_in_the_settings(required_env, warehouse, monkeypatch):
    def build(model, **options):
        return ScriptedModel([AIMessage(f"answered by {model}")])

    monkeypatch.setattr("retail_agent.di.ChatGoogleGenerativeAI", build)
    monkeypatch.setenv("GEMINI_MODEL", "main-model")
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "spare-model")

    result = runner.invoke(app, ["chat", "--user", "alice"], input="monthly revenue\nexit\n")

    assert "answered by main-model" in result.output


def test_a_failed_answer_goes_to_the_log_file_and_not_to_the_screen(
    required_env, warehouse, monkeypatch, tmp_path
):
    monkeypatch.setattr("retail_agent.di.ChatGoogleGenerativeAI", lambda **options: BrokenModel())

    result = runner.invoke(app, ["chat", "--user", "alice"], input="monthly revenue\nexit\n")

    assert "I could not answer that" in result.output
    assert "Traceback" not in result.output
    assert "the model is down" in (tmp_path / "data" / "retail_agent.log").read_text()


def test_unusable_report_database_is_reported_without_a_traceback(
    required_env, warehouse, monkeypatch
):
    def broken(database):
        raise ReportsUnavailable(database, sqlite3.OperationalError("database is locked"))

    monkeypatch.setattr("retail_agent.di.ReportRepository", broken)

    result = runner.invoke(app, ["chat", "--user", "ben"], input="exit\n")

    assert result.exit_code == 2
    assert "report database" in result.output
    assert "Traceback" not in result.output
