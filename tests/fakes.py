from collections.abc import Iterable
from typing import Any

from google.cloud.bigquery import SchemaField
from google.cloud.bigquery.table import Row
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult
from pydantic import Field

from retail_agent.domain.policy import Brands
from retail_agent.domain.profile import Profile
from retail_agent.warehouse.query_executor import Fetched
from retail_agent.warehouse.sql_guard import AllowedQuery

BEN = Profile("ben", "Ben Ortiz", "Brand manager", Brands(frozenset({"Diesel"})))


class FakeExecutor:
    """Answers with what the test scripted and records what it was asked."""

    def __init__(
        self,
        estimate: int | Exception = 1_000,
        fetch: Fetched | Exception | None = None,
    ) -> None:
        self._estimate = estimate
        self._fetched = fetch or Fetched(("id", "country"), ((1, "Japan"),), 2_048)
        self.estimates: list[AllowedQuery] = []
        self.fetches: list[tuple[AllowedQuery, int]] = []

    async def estimate_bytes(self, query: AllowedQuery) -> int:
        self.estimates.append(query)
        if isinstance(self._estimate, Exception):
            raise self._estimate
        return self._estimate

    async def fetch(self, query: AllowedQuery, max_rows: int) -> Fetched:
        self.fetches.append((query, max_rows))
        if isinstance(self._fetched, Exception):
            raise self._fetched
        return self._fetched


class StubRows:
    schema = (SchemaField("id", "INTEGER"), SchemaField("price", "NUMERIC"))
    job_id = "job-1"
    total_bytes_processed = 2_048

    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = [Row(row, {"id": 0, "price": 1}) for row in rows]

    def __iter__(self) -> Any:
        return iter(self._rows)


class StubJob:
    def __init__(self, total_bytes_processed: int | None, statement_type: str) -> None:
        self.total_bytes_processed = total_bytes_processed
        self.statement_type = statement_type


class StubClient:
    """Stands in for the Google client and records what it was sent."""

    def __init__(
        self,
        rows: list[tuple[object, ...]] | None = None,
        error: Exception | None = None,
        estimate: int | None = 2_048,
        statement_type: str = "SELECT",
    ) -> None:
        self._rows = rows or []
        self._error = error
        self._estimate = estimate
        self._statement_type = statement_type
        self.sent: list[tuple[str, bool]] = []
        self.config: Any = None
        self.options: dict[str, Any] = {}

    def query(self, sql: str, job_config: Any, **options: Any) -> StubJob:
        self._record(sql, job_config, options)
        return StubJob(self._estimate, self._statement_type)

    def query_and_wait(self, sql: str, job_config: Any, **options: Any) -> StubRows:
        self._record(sql, job_config, options)
        return StubRows(self._rows)

    def _record(self, sql: str, job_config: Any, options: dict[str, Any]) -> None:
        self.sent.append((sql, bool(job_config.dry_run)))
        self.config = job_config
        self.options = options
        if self._error:
            raise self._error


class ScriptedModel(GenericFakeChatModel):
    """Plays the scripted messages in order and records what it was shown."""

    seen: list[str] = Field(default_factory=list)

    def __init__(self, script: Iterable[AIMessage]) -> None:
        super().__init__(messages=iter(script))

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedModel":
        return self

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        self.seen.append("\n".join(str(message.content) for message in messages))
        return super()._generate(messages, *args, **kwargs)


class BrokenModel(ScriptedModel):
    def __init__(self) -> None:
        super().__init__([])

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        raise ConnectionError("the model is down")


def sql_call(sql: str, number: int = 0) -> AIMessage:
    return tool_call("run_sql", {"sql": sql}, number)


def tool_call(name: str, args: dict[str, Any], number: int = 0) -> AIMessage:
    return tool_calls((name, args, number))


def tool_calls(*calls: tuple[str, dict[str, Any], int]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"call-{number}"} for name, args, number in calls
        ],
    )


def brands(*names: str) -> Fetched:
    return Fetched(columns=("brand",), rows=tuple((name,) for name in names), bytes_processed=1_024)


class FakeTerminal:
    def __init__(self, messages: list[str], *, confirm: bool = False) -> None:
        self._messages = iter(messages)
        self._confirm = confirm
        self.shown: list[str] = []

    def read(self) -> str | None:
        return next(self._messages, None)

    def show(self, text: str) -> None:
        self.shown.append(text)

    def show_reply(self, markdown: str) -> None:
        self.shown.append(markdown)

    def confirm(self, question: str) -> bool:
        self.shown.append(question)
        return self._confirm
