import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

import langfuse_lite  # pyright: ignore[reportMissingTypeStubs]
import pytest
from fakes import BEN, FakeExecutor, FakeTerminal, ScriptedModel, sql_call, tool_call
from langchain_core.messages import AIMessage

from retail_agent.adapters.langfuse_tracing import LangfuseTracer, NoTracer
from retail_agent.adapters.report_repository import ReportRepository
from retail_agent.agent.langchain_agent import LangChainAgent
from retail_agent.agent.report_tools import DELETE_REPORTS, report_tools
from retail_agent.agent.sql_tool import RUN_SQL, sql_tool
from retail_agent.app.chat import TRACING_OFF, Chat
from retail_agent.config import Settings
from retail_agent.di import build_tracer, local_langfuse_database
from retail_agent.domain.policy import Policy
from retail_agent.query.warehouse import Warehouse

API_KEY = "test-key"
PROJECT = "acme-analytics"


def settings_in(folder: Path, **extra: Any) -> Settings:
    values = {"google_cloud_project": PROJECT, "google_api_key": API_KEY, "data_dir": folder}
    return Settings.model_validate(values | extra)


def agent(model, tracer, reports) -> LangChainAgent:
    warehouse = Warehouse(
        FakeExecutor(),
        Policy(scope=BEN.scope),
        max_bytes=1_000_000,
        max_result_chars=20_000,
        secrets=(),
    )
    return LangChainAgent(
        model,
        ScriptedModel([]),
        [sql_tool(warehouse), *report_tools(reports, "ben", "talk-1")],
        "You are a retail analyst.",
        max_model_calls=10,
        max_tool_calls={RUN_SQL: 6, DELETE_REPORTS: 1},
        timeout_s=5.0,
        callbacks=tracer.callbacks(),
    )


class Recorded:
    """Reads the local Langfuse database back with its own command line."""

    def __init__(self, settings: Settings, tracer: LangfuseTracer) -> None:
        self.database = local_langfuse_database(settings)
        self.tracer = tracer

    def rows(self, query: str) -> list[dict[str, Any]]:
        command = [langfuse_lite.binary(), "sql", query, "--json", "--db", str(self.database)]
        return json.loads(
            subprocess.run(command, capture_output=True, text=True, check=True).stdout
        )

    def questions(self) -> list[dict[str, Any]]:
        return self.rows("SELECT * FROM observations WHERE name = 'question' ORDER BY start_time")

    def steps(self, question: dict[str, Any], kind: str) -> list[dict[str, Any]]:
        return self.rows(
            "SELECT name, level, output FROM observations "
            f"WHERE trace_id = '{question['trace_id']}' AND type = '{kind}' ORDER BY start_time"
        )


@pytest.fixture(scope="module")
def recorded(tmp_path_factory) -> Recorded:
    """One chat with three questions: a refused then a good query, a deletion, and a failure."""
    folder = tmp_path_factory.mktemp("data")
    settings = settings_in(folder)
    tracer = build_tracer(settings, "ben", "talk-1")
    assert isinstance(tracer, LangfuseTracer)
    reports = ReportRepository(folder / "retail_agent.db")
    saved = reports.add("ben", "talk-1", "Diesel returns", "body")
    model = ScriptedModel(
        [
            sql_call("SELECT email FROM users", 0),
            sql_call("SELECT id FROM users", 1),
            AIMessage(f"Write to anna@example.com. The key is {API_KEY} in {PROJECT}."),
            tool_call("delete_reports", {"ids": [saved.id]}),
            AIMessage("The report is gone."),
        ]
    )
    messages = ["my email is anna@example.com", "delete the report", "one more question"]
    terminal = FakeTerminal(messages, confirm=True)
    asyncio.run(Chat(agent(model, tracer, reports), terminal, BEN, tracer).run())
    return Recorded(settings, tracer)


def test_every_question_is_one_trace_with_the_person_and_the_conversation(recorded) -> None:
    questions = recorded.questions()

    assert len(questions) == 3
    assert {(q["user_id"], q["session_id"]) for q in questions} == {("ben", "talk-1")}
    assert len({q["trace_id"] for q in questions}) == 3


def test_queries_are_recorded_with_what_the_warehouse_answered(recorded) -> None:
    refused, good = recorded.steps(recorded.questions()[0], "TOOL")

    assert (refused["name"], good["name"]) == ("run_sql", "run_sql")
    assert "denied" in refused["output"]
    assert "rows" in good["output"]


def test_model_calls_are_recorded(recorded) -> None:
    assert len(recorded.steps(recorded.questions()[0], "GENERATION")) == 3


def test_a_deletion_with_its_confirmation_is_one_trace(recorded) -> None:
    asked, deleted = recorded.steps(recorded.questions()[1], "TOOL")

    assert (asked["name"], deleted["name"]) == ("delete_reports", "delete_reports")
    assert asked["level"] == "DEFAULT"
    assert "deleted" in deleted["output"]


def test_a_failed_question_is_marked_as_an_error(recorded) -> None:
    answered, _, failed = recorded.questions()

    assert answered["level"] == "DEFAULT"
    assert (failed["level"], failed["output"]) == ("ERROR", None)
    assert failed["status_message"]


def test_personal_data_and_secrets_never_reach_the_database(recorded) -> None:
    stored = b"".join(file.read_bytes() for file in recorded.database.parent.glob("langfuse.db*"))

    assert "my email is [email hidden]" in recorded.questions()[0]["input"]
    for secret in (b"anna@example.com", API_KEY.encode(), PROJECT.encode()):
        assert secret not in stored


def test_the_local_langfuse_stops_when_the_chat_ends(recorded) -> None:
    local = recorded.tracer._local  # pyright: ignore[reportPrivateUsage]

    assert local is not None
    assert local.process.poll() is not None


async def test_chat_works_without_tracing_when_the_local_langfuse_does_not_start(
    tmp_path, monkeypatch, reports
) -> None:
    def broken(**options: Any) -> None:
        raise RuntimeError("langfuse-lite did not start")

    monkeypatch.setattr("retail_agent.adapters.langfuse_tracing.langfuse_lite.serve", broken)
    tracer = build_tracer(settings_in(tmp_path), "ben", "talk-1")
    terminal = FakeTerminal(["monthly revenue"])

    model = ScriptedModel([AIMessage("Revenue is up.")])
    await Chat(agent(model, tracer, reports), terminal, BEN, tracer).run()

    assert isinstance(tracer, NoTracer)
    assert terminal.shown[1:] == [TRACING_OFF, "Revenue is up."]


def test_with_langfuse_keys_no_local_langfuse_is_started(tmp_path, monkeypatch) -> None:
    def unexpected(**options: Any) -> None:
        raise AssertionError("the local Langfuse must not start")

    monkeypatch.setattr("retail_agent.adapters.langfuse_tracing.langfuse_lite.serve", unexpected)
    settings = settings_in(
        tmp_path,
        langfuse_public_key="pk-test",
        langfuse_secret_key="sk-test",
        langfuse_host="http://127.0.0.1:9",
    )

    tracer = build_tracer(settings, "ben", "talk-1")

    assert isinstance(tracer, LangfuseTracer)
    assert tracer.recording
    assert not local_langfuse_database(settings).exists()


async def test_secrets_inside_an_error_text_never_reach_the_database(tmp_path, reports) -> None:
    class LeakyModel(ScriptedModel):
        def __init__(self) -> None:
            super().__init__([])

        def _generate(self, messages: Any, *args: Any, **kwargs: Any) -> Any:
            raise ConnectionError(f"bad key {API_KEY} for {PROJECT}, mail anna@example.com")

    settings = settings_in(tmp_path)
    tracer = build_tracer(settings, "ben", "talk-1")
    failing = LangChainAgent(
        LeakyModel(),
        LeakyModel(),
        [],
        "You are a retail analyst.",
        max_model_calls=10,
        max_tool_calls={},
        timeout_s=5.0,
        callbacks=tracer.callbacks(),
    )

    await Chat(failing, FakeTerminal(["hello"]), BEN, tracer).run()

    stored = b"".join(file.read_bytes() for file in tmp_path.glob("langfuse.db*"))
    assert b"bad key" in stored
    for secret in (b"anna@example.com", API_KEY.encode(), PROJECT.encode()):
        assert secret not in stored


def test_chat_works_without_tracing_when_the_langfuse_client_cannot_be_created(
    tmp_path, monkeypatch
) -> None:
    def broken(**options: Any) -> None:
        raise ValueError("bad host")

    monkeypatch.setattr("retail_agent.di.Langfuse", broken)
    settings = settings_in(tmp_path, langfuse_public_key="pk-test", langfuse_secret_key="sk-test")

    assert isinstance(build_tracer(settings, "ben", "talk-1"), NoTracer)
