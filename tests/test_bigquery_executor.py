from collections.abc import Callable
from decimal import Decimal

import pytest
from fakes import StubClient
from google.api_core import exceptions as api
from google.auth import exceptions as auth

from retail_agent.bigquery_executor import BigQueryExecutor
from retail_agent.query_executor import Fetched, QueryRejected
from retail_agent.sql_guard import AllowedQuery

QUERY = AllowedQuery("SELECT id, price FROM items")
TIMEOUT_S = 30

type Connect = Callable[[StubClient], BigQueryExecutor]


def api_error(cls: type[api.GoogleAPICallError], reason: str) -> api.GoogleAPICallError:
    return cls("wrapper text", errors=[{"reason": reason, "message": f"cause: {reason}"}])


def new_executor() -> BigQueryExecutor:
    return BigQueryExecutor("acme-project", max_bytes_billed=1_000_000, timeout_s=TIMEOUT_S)


@pytest.fixture
def connect(monkeypatch: pytest.MonkeyPatch) -> Connect:
    def executor_for(client: StubClient) -> BigQueryExecutor:
        monkeypatch.setattr(
            "retail_agent.bigquery_executor.bigquery.Client", lambda project: client
        )
        return new_executor()

    return executor_for


async def call(executor: BigQueryExecutor, phase: str) -> object:
    if phase == "estimate":
        return await executor.estimate_bytes(QUERY)
    return await executor.fetch(QUERY, max_rows=3)


PHASES = pytest.mark.parametrize("phase", ["estimate", "fetch"])


async def test_estimate_returns_the_bytes_without_running_the_query(connect: Connect) -> None:
    client = StubClient(estimate=2_048)

    assert await connect(client).estimate_bytes(QUERY) == 2_048
    assert client.sent == [(QUERY.sql, True)]


async def test_estimate_without_a_number_is_an_error(connect: Connect) -> None:
    with pytest.raises(RuntimeError, match="no estimate"):
        await connect(StubClient(estimate=None)).estimate_bytes(QUERY)


@pytest.mark.parametrize("statement_type", ["DELETE", "CREATE_TABLE_AS_SELECT", "SCRIPT"])
async def test_estimate_rejects_anything_bigquery_does_not_call_a_select(
    connect: Connect, statement_type: str
) -> None:
    client = StubClient(statement_type=statement_type)

    with pytest.raises(QueryRejected, match="Only SELECT"):
        await connect(client).estimate_bytes(QUERY)


async def test_fetch_returns_columns_rows_bytes_and_the_job_id(connect: Connect) -> None:
    client = StubClient(rows=[(1, Decimal("9.99")), (2, None)])

    fetched = await connect(client).fetch(QUERY, max_rows=3)

    assert fetched == Fetched(
        columns=("id", "price"),
        rows=((1, Decimal("9.99")), (2, None)),
        bytes_processed=2_048,
        job_id="job-1",
    )
    assert client.sent == [(QUERY.sql, False)]


async def test_fetch_asks_for_no_more_rows_than_allowed(connect: Connect) -> None:
    client = StubClient()

    await connect(client).fetch(QUERY, max_rows=3)

    assert client.options["max_results"] == 3


@PHASES
async def test_query_bigquery_calls_invalid_is_rejected_with_its_text(
    connect: Connect, phase: str
) -> None:
    client = StubClient(error=api_error(api.BadRequest, "invalidQuery"))

    with pytest.raises(QueryRejected) as raised:
        await call(connect(client), phase)

    assert str(raised.value) == "cause: invalidQuery"


async def test_rejection_without_a_message_keeps_the_whole_error_text(connect: Connect) -> None:
    error = api.BadRequest("wrapper text", errors=[{"reason": "invalidQuery"}])

    with pytest.raises(QueryRejected, match="wrapper text"):
        await connect(StubClient(error=error)).estimate_bytes(QUERY)


@PHASES
@pytest.mark.parametrize(
    "error",
    [
        api_error(api.Forbidden, "accessDenied"),
        api_error(api.BadRequest, "badRequest"),
        api_error(api.BadRequest, "bytesBilledLimitExceeded"),
        api.BadRequest("no reason given"),
        api.BadRequest("odd shape", errors=["not a dict"]),
        api.ServiceUnavailable("down"),
        auth.RefreshError("token expired"),
        TimeoutError("too slow"),
    ],
)
async def test_any_other_error_passes_through_unchanged(
    connect: Connect, phase: str, error: Exception
) -> None:
    with pytest.raises(type(error), match=str(error)):
        await call(connect(StubClient(error=error)), phase)


@PHASES
async def test_calls_are_bounded_in_time_and_never_repeat_the_query(
    connect: Connect, phase: str
) -> None:
    client = StubClient()

    await call(connect(client), phase)

    time_limit = "timeout" if phase == "estimate" else "wait_timeout"
    assert client.options[time_limit] == TIMEOUT_S
    assert client.options["retry"].timeout == TIMEOUT_S
    assert client.options["job_retry"] is None


async def test_server_keeps_the_query_longer_than_we_wait_for_it(connect: Connect) -> None:
    client = StubClient()

    await connect(client).fetch(QUERY, max_rows=3)

    assert int(client.config.job_timeout_ms) > TIMEOUT_S * 1000


async def test_bytes_billed_are_capped(connect: Connect) -> None:
    client = StubClient()

    await connect(client).fetch(QUERY, max_rows=3)

    assert client.config.maximum_bytes_billed == 1_000_000


async def test_missing_credentials_fail_the_first_query_not_the_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_credentials(project: str) -> StubClient:
        raise auth.DefaultCredentialsError("credentials were not found")

    monkeypatch.setattr("retail_agent.bigquery_executor.bigquery.Client", no_credentials)
    executor = new_executor()

    with pytest.raises(auth.DefaultCredentialsError):
        await executor.estimate_bytes(QUERY)


async def test_client_is_created_once(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[str] = []

    def create(project: str) -> StubClient:
        created.append(project)
        return StubClient()

    monkeypatch.setattr("retail_agent.bigquery_executor.bigquery.Client", create)
    executor = new_executor()

    await executor.estimate_bytes(QUERY)
    await executor.fetch(QUERY, max_rows=3)

    assert created == ["acme-project"]
