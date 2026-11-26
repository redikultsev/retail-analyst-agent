from decimal import Decimal
from typing import Any

import pytest
from google.api_core import exceptions as api
from google.auth import exceptions as auth
from google.cloud.bigquery import SchemaField
from google.cloud.bigquery.table import Row

from retail_agent.bigquery_executor import BigQueryExecutor, classify
from retail_agent.query_executor import Estimate, Failed, Fetched
from retail_agent.sql_guard import Allowed

QUERY = Allowed("SELECT id, price FROM items")


# --- BigQuery errors become failure kinds


def api_error(cls: type[api.GoogleAPICallError], reason: str) -> api.GoogleAPICallError:
    return cls("wrapper text", errors=[{"reason": reason, "message": f"cause: {reason}"}])


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (api_error(api.BadRequest, "invalidQuery"), "invalid_query"),
        (api_error(api.InternalServerError, "bytesBilledLimitExceeded"), "too_expensive"),
        (api_error(api.BadRequest, "resourcesExceeded"), "too_expensive"),
        (api_error(api.Forbidden, "responseTooLarge"), "too_expensive"),
        (api_error(api.GoogleAPICallError, "stopped"), "timeout"),
        (api_error(api.Forbidden, "accessDenied"), "misconfigured"),
        (api_error(api.NotFound, "notFound"), "misconfigured"),
        (api_error(api.Forbidden, "billingNotEnabled"), "misconfigured"),
        (api_error(api.Forbidden, "quotaExceeded"), "unavailable"),
        (api_error(api.Forbidden, "rateLimitExceeded"), "unavailable"),
        (api_error(api.InternalServerError, "backendError"), "unavailable"),
        (api_error(api.BadRequest, "badRequest"), "misconfigured"),
        (api_error(api.BadRequest, "somethingNew"), "invalid_query"),
        (api_error(api.Forbidden, "somethingNew"), "misconfigured"),
        (api_error(api.InternalServerError, "somethingNew"), "unavailable"),
    ],
)
def test_error_reason_decides_the_failure_kind(error: Exception, kind: str) -> None:
    failed = classify(error)

    assert failed.kind == kind
    assert failed.detail == error.errors[0]["message"]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (TimeoutError(), "timeout"),
        (api.DeadlineExceeded("too slow"), "timeout"),
        (api.RetryError("gave up", cause=None), "timeout"),
        (auth.DefaultCredentialsError("no credentials"), "misconfigured"),
        (auth.RefreshError("token expired"), "misconfigured"),
        (api.Forbidden("no reason given"), "misconfigured"),
        (api.ServiceUnavailable("down"), "unavailable"),
        (RuntimeError("anything else"), "unavailable"),
    ],
)
def test_error_without_a_reason_is_classified_by_its_type(error: Exception, kind: str) -> None:
    failed = classify(error)

    assert failed.kind == kind
    assert failed.detail == f"{type(error).__name__}: {error}".removesuffix(": ")


class OddError(Exception):
    def errors(self) -> list[str]:
        return ["not the BigQuery shape"]


def test_error_with_an_unrelated_errors_attribute_is_classified_by_type() -> None:
    assert classify(OddError("odd")) == Failed("unavailable", "OddError: odd")


def test_reason_in_an_unexpected_shape_does_not_break_classification() -> None:
    error = api.BadRequest("wrapper text", errors=["not a dict"])

    assert classify(error).kind == "invalid_query"


def test_unexpected_error_is_logged_with_its_type(caplog: pytest.LogCaptureFixture) -> None:
    failed = classify(TypeError("our own bug"))

    assert failed == Failed("unavailable", "TypeError: our own bug")
    assert "unexpected error" in caplog.text


# --- the executor


class StubRows:
    schema = (SchemaField("id", "INTEGER"), SchemaField("price", "NUMERIC"))

    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = [Row(row, {"id": 0, "price": 1}) for row in rows]

    def __iter__(self) -> Any:
        return iter(self._rows)


class StubJob:
    job_id = "job-1"
    total_bytes_processed = 2_048
    cache_hit = True

    def __init__(
        self,
        rows: list[tuple[object, ...]] | None = None,
        result_error: Exception | None = None,
        cancel_error: Exception | None = None,
    ) -> None:
        self._rows = rows or []
        self._result_error = result_error
        self._cancel_error = cancel_error
        self.max_results: int | None = None
        self.cancelled = False
        self.cancel_options: dict[str, Any] = {}

    def result(self, max_results: int | None = None, **_: Any) -> StubRows:
        self.max_results = max_results
        if self._result_error:
            raise self._result_error
        return StubRows(self._rows)

    def cancel(self, **options: Any) -> None:
        self.cancelled = True
        self.cancel_options = options
        if self._cancel_error:
            raise self._cancel_error


class StubClient:
    def __init__(self, job: StubJob | None = None, error: Exception | None = None) -> None:
        self.job = job or StubJob()
        self._error = error
        self.sent: list[tuple[str, bool]] = []
        self.options: dict[str, Any] = {}

    def query(self, sql: str, job_config: Any = None, **options: Any) -> StubJob:
        self.sent.append((sql, bool(job_config.dry_run)))
        self.options = options
        if self._error:
            raise self._error
        return self.job


def executor(client: StubClient) -> BigQueryExecutor:
    return BigQueryExecutor(client, max_bytes_billed=1_000_000, timeout_s=30)  # type: ignore[arg-type]


def test_dry_run_returns_the_estimate_without_running_the_query() -> None:
    client = StubClient()

    assert executor(client).dry_run(QUERY) == Estimate(bytes_processed=2_048)
    assert client.sent == [(QUERY.sql, True)]


def test_dry_run_reports_a_compile_error() -> None:
    client = StubClient(error=api_error(api.BadRequest, "invalidQuery"))

    assert executor(client).dry_run(QUERY) == Failed("invalid_query", "cause: invalidQuery")


def test_execute_returns_columns_and_rows() -> None:
    client = StubClient(StubJob(rows=[(1, Decimal("9.99")), (2, None)]))

    fetched = executor(client).execute(QUERY, max_rows=3)

    assert fetched == Fetched(
        columns=("id", "price"),
        rows=((1, Decimal("9.99")), (2, None)),
        bytes_processed=2_048,
        cache_hit=True,
        job_id="job-1",
    )
    assert client.sent == [(QUERY.sql, False)]
    assert client.job.max_results == 3


def test_execute_cancels_the_job_on_timeout() -> None:
    client = StubClient(StubJob(result_error=TimeoutError()))

    failed = executor(client).execute(QUERY, max_rows=3)

    assert isinstance(failed, Failed)
    assert failed.kind == "timeout"
    assert failed.job_id == "job-1"
    assert client.job.cancelled


@pytest.mark.parametrize("phase", ["dry_run", "execute"])
def test_sending_a_query_is_bounded_in_time(phase: str) -> None:
    client = StubClient()
    runner = executor(client)

    _ = runner.dry_run(QUERY) if phase == "dry_run" else runner.execute(QUERY, max_rows=3)

    assert client.options["timeout"] == 30
    assert client.options["retry"].timeout == 30
    assert client.options["job_retry"] is None


def test_cancel_is_bounded_in_time() -> None:
    client = StubClient(StubJob(result_error=TimeoutError()))

    executor(client).execute(QUERY, max_rows=3)

    assert client.job.cancel_options["retry"] is None
    assert client.job.cancel_options["timeout"] <= 5


def test_failed_cancel_does_not_hide_the_timeout() -> None:
    job = StubJob(result_error=TimeoutError(), cancel_error=RuntimeError("cancel failed"))

    failed = executor(StubClient(job)).execute(QUERY, max_rows=3)

    assert isinstance(failed, Failed)
    assert failed.kind == "timeout"


def test_failed_job_keeps_its_id_and_is_not_cancelled() -> None:
    job = StubJob(result_error=api_error(api.BadRequest, "invalidQuery"))

    failed = executor(StubClient(job)).execute(QUERY, max_rows=3)

    assert failed == Failed("invalid_query", "cause: invalidQuery", job_id="job-1")
    assert not job.cancelled


@pytest.mark.parametrize("phase", ["dry_run", "execute"])
def test_executor_never_raises(phase: str) -> None:
    runner = executor(StubClient(error=RuntimeError("network down")))

    failed = runner.dry_run(QUERY) if phase == "dry_run" else runner.execute(QUERY, max_rows=3)

    assert failed == Failed("unavailable", "RuntimeError: network down")


def test_dry_run_without_an_estimate_is_a_failure() -> None:
    job = StubJob()
    job.total_bytes_processed = None  # type: ignore[assignment]

    failed = executor(StubClient(job)).dry_run(QUERY)

    assert failed == Failed("unavailable", "dry run returned no estimate")


@pytest.mark.parametrize("phase", ["dry_run", "execute"])
def test_timeout_before_a_job_exists_is_a_connection_problem(phase: str) -> None:
    runner = executor(StubClient(error=TimeoutError()))

    failed = runner.dry_run(QUERY) if phase == "dry_run" else runner.execute(QUERY, max_rows=3)

    assert isinstance(failed, Failed)
    assert failed.kind == "unavailable"
