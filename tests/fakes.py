from typing import Any

from google.cloud.bigquery import SchemaField
from google.cloud.bigquery.table import Row

from retail_agent.query_executor import Fetched
from retail_agent.sql_guard import AllowedQuery


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
    def __init__(self, total_bytes_processed: int | None) -> None:
        self.total_bytes_processed = total_bytes_processed


class StubClient:
    """Stands in for the Google client and records what it was sent."""

    def __init__(
        self,
        rows: list[tuple[object, ...]] | None = None,
        error: Exception | None = None,
        estimate: int | None = 2_048,
    ) -> None:
        self._rows = rows or []
        self._error = error
        self._estimate = estimate
        self.sent: list[tuple[str, bool]] = []
        self.config: Any = None
        self.options: dict[str, Any] = {}

    def query(self, sql: str, job_config: Any, **options: Any) -> StubJob:
        self._record(sql, job_config, options)
        return StubJob(self._estimate)

    def query_and_wait(self, sql: str, job_config: Any, **options: Any) -> StubRows:
        self._record(sql, job_config, options)
        return StubRows(self._rows)

    def _record(self, sql: str, job_config: Any, options: dict[str, Any]) -> None:
        self.sent.append((sql, bool(job_config.dry_run)))
        self.config = job_config
        self.options = options
        if self._error:
            raise self._error


def brands(*names: str) -> Fetched:
    return Fetched(columns=("brand",), rows=tuple((name,) for name in names), bytes_processed=1_024)
