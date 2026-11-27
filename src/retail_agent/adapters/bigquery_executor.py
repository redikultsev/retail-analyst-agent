# The Google client is only partly typed.
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false
import asyncio
from collections.abc import Generator
from contextlib import contextmanager
from functools import cached_property

from google.api_core import exceptions as api
from google.cloud import bigquery
from google.cloud.bigquery.retry import DEFAULT_RETRY

from retail_agent.query.query_executor import Fetched, QueryRejected
from retail_agent.query.sql_guard import AllowedQuery

SERVER_STOP_MARGIN_S = 5.0


class BigQueryExecutor:
    def __init__(self, project: str, *, max_bytes_billed: int, timeout_s: float) -> None:
        self._project = project
        self._max_bytes_billed = max_bytes_billed
        self._timeout_s = timeout_s
        # Without this limit the client keeps retrying a lost connection for ten minutes.
        self._retry = DEFAULT_RETRY.with_timeout(timeout_s)

    async def estimate_bytes(self, query: AllowedQuery) -> int:
        return await asyncio.to_thread(self._estimate_bytes, query.sql)

    async def fetch(self, query: AllowedQuery, max_rows: int) -> Fetched:
        return await asyncio.to_thread(self._fetch, query.sql, max_rows)

    @cached_property
    def _client(self) -> bigquery.Client:
        return bigquery.Client(project=self._project)

    def _estimate_bytes(self, sql: str) -> int:
        with _invalid_query_as_rejection():
            job = self._client.query(
                sql,
                job_config=bigquery.QueryJobConfig(dry_run=True),
                timeout=self._timeout_s,
                retry=self._retry,
                job_retry=None,
            )
        # A second read-only check that does not depend on our own SQL parser.
        if job.statement_type != "SELECT":
            raise QueryRejected("Only SELECT statements can run.")
        if job.total_bytes_processed is None:
            raise RuntimeError("BigQuery returned no estimate for the dry run")
        return job.total_bytes_processed

    def _fetch(self, sql: str, max_rows: int) -> Fetched:
        config = bigquery.QueryJobConfig(
            maximum_bytes_billed=self._max_bytes_billed,
            # The server stops the query after we stop waiting, so a slow query ends as our timeout.
            job_timeout_ms=int((self._timeout_s + SERVER_STOP_MARGIN_S) * 1000),
        )
        with _invalid_query_as_rejection():
            rows = self._client.query_and_wait(
                sql,
                job_config=config,
                max_results=max_rows,
                wait_timeout=self._timeout_s,
                api_timeout=self._timeout_s,
                retry=self._retry,
                job_retry=None,  # pyright: ignore[reportArgumentType]
            )
            return Fetched(
                columns=tuple(field.name for field in rows.schema),
                rows=tuple(tuple(row.values()) for row in rows),
                bytes_processed=rows.total_bytes_processed,
                job_id=rows.job_id,
            )


@contextmanager
def _invalid_query_as_rejection() -> Generator[None]:
    try:
        yield
    except api.BadRequest as error:
        cause = error.errors[0] if error.errors else None
        if not isinstance(cause, dict) or cause.get("reason") != "invalidQuery":
            raise
        raise QueryRejected(cause.get("message") or str(error)) from error
