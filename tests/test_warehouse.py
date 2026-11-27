import logging
from decimal import Decimal

import pytest
from fakes import FakeExecutor

from retail_agent.domain.policy import AllBrands, Brands, Policy
from retail_agent.query.query_executor import Fetched, QueryRejected, Row
from retail_agent.query.sql_guard import AllowedQuery, Rejected, check
from retail_agent.query.warehouse import Answered, Refused, Warehouse

PROJECT = "acme-project-123"
CEO = Policy(scope=AllBrands())
MANAGER = Policy(scope=Brands(frozenset({"Diesel"})), row_limit=3)
QUERY = "SELECT id, country FROM users"


def fetched(*rows: Row) -> Fetched:
    return Fetched(columns=("id", "country"), rows=rows, bytes_processed=2_048)


def failing(phase: str, failure: Exception) -> FakeExecutor:
    return FakeExecutor(estimate=failure) if phase == "estimate" else FakeExecutor(fetch=failure)


async def run(
    executor: FakeExecutor,
    sql: str = QUERY,
    policy: Policy = MANAGER,
    *,
    max_bytes: int = 1_000_000,
    max_result_chars: int = 20_000,
    secrets: tuple[str, ...] = (PROJECT,),
) -> Answered | Refused:
    warehouse = Warehouse(
        executor,
        policy,
        max_bytes=max_bytes,
        max_result_chars=max_result_chars,
        secrets=secrets,
    )
    return await warehouse.run(sql)


def answered(outcome: Answered | Refused) -> Answered:
    assert isinstance(outcome, Answered), outcome
    return outcome


def refused(outcome: Answered | Refused) -> Refused:
    assert isinstance(outcome, Refused), outcome
    return outcome


def size(rows: tuple[Row, ...]) -> int:
    return sum(len(str(cell)) for row in rows for cell in row)


# --- the guard decides first


@pytest.mark.parametrize(
    ("sql", "status", "code"),
    [
        ("SELECT email FROM users", "denied", "pii_column"),
        ("SELECT * FROM events", "denied", "table_not_allowed"),
        ("DROP TABLE users", "denied", "not_select"),
        ("SELECT SESSION_USER()", "denied", "function_not_allowed"),
        ("SELECT id FROM users; SELECT id FROM orders", "sql_error", "multiple_statements"),
        ("SELECT FROM", "sql_error", "sql_error"),
    ],
)
async def test_rejected_query_never_reaches_the_executor(sql: str, status: str, code: str) -> None:
    executor = FakeExecutor()
    verdict = check(sql, MANAGER)
    assert isinstance(verdict, Rejected)

    outcome = refused(await run(executor, sql))

    assert executor.estimates == []
    assert executor.fetches == []
    assert outcome.message == verdict.message
    assert outcome.log.status == status
    assert outcome.log.reject_code == code
    assert outcome.log.original_sql == sql
    assert outcome.log.executed_sql is None


async def test_executor_gets_the_guarded_sql_and_one_row_over_the_limit() -> None:
    executor = FakeExecutor()
    guarded = check(QUERY, MANAGER)
    assert isinstance(guarded, AllowedQuery)

    outcome = answered(await run(executor))

    assert "Diesel" in guarded.sql
    assert executor.estimates == [guarded]
    assert executor.fetches == [(guarded, MANAGER.row_limit + 1)]
    assert outcome.log.original_sql == QUERY
    assert outcome.log.executed_sql == guarded.sql


# --- results


async def test_answer_carries_columns_rows_and_a_log_record() -> None:
    result = Fetched(
        columns=("id", "country"),
        rows=((1, "Japan"), (2, "Brasil")),
        bytes_processed=2_048,
        job_id="job-1",
    )

    outcome = answered(await run(FakeExecutor(fetch=result)))

    assert outcome.columns == ("id", "country")
    assert outcome.rows == ((1, "Japan"), (2, "Brasil"))
    log = outcome.log
    assert log.status == "ok"
    assert log.row_count == 2
    assert log.truncated is None
    assert log.bytes_processed == 2_048
    assert log.job_id == "job-1"
    assert log.reject_code is None
    assert log.detail is None
    assert log.elapsed_ms >= 0


async def test_zero_rows_is_an_answer_with_status_no_data() -> None:
    outcome = answered(await run(FakeExecutor(fetch=fetched())))

    assert outcome.rows == ()
    assert outcome.columns == ("id", "country")
    assert outcome.log.status == "no_data"


async def test_rows_over_the_limit_are_cut_and_marked() -> None:
    rows = tuple((n, "Japan") for n in range(MANAGER.row_limit + 1))

    outcome = answered(await run(FakeExecutor(fetch=fetched(*rows))))

    assert outcome.rows == rows[: MANAGER.row_limit]
    assert outcome.log.truncated == "rows"
    assert outcome.log.row_count == MANAGER.row_limit


async def test_exactly_the_limit_is_not_marked_as_cut() -> None:
    rows = tuple((n, "Japan") for n in range(MANAGER.row_limit))

    outcome = answered(await run(FakeExecutor(fetch=fetched(*rows))))

    assert outcome.rows == rows
    assert outcome.log.truncated is None


async def test_result_over_the_size_cap_loses_trailing_rows() -> None:
    rows = tuple((n, "x" * 100) for n in range(50))

    outcome = answered(
        await run(FakeExecutor(fetch=fetched(*rows)), policy=CEO, max_result_chars=1_000)
    )

    assert 0 < len(outcome.rows) < 50
    assert outcome.rows == rows[: len(outcome.rows)]
    assert size(outcome.rows) <= 1_000
    assert outcome.log.truncated == "size"
    assert outcome.log.row_count == len(outcome.rows)


async def test_single_row_over_the_size_cap_is_refused() -> None:
    executor = FakeExecutor(fetch=fetched((1, "x" * 5_000)))

    outcome = refused(await run(executor, max_result_chars=1_000))

    assert outcome.log.status == "too_large"
    assert "xxx" not in outcome.message


async def test_control_characters_are_stripped_from_text_cells() -> None:
    dirty = "a\x00b\x1b[31mc\nd\te"
    clean = "ab[31mc\nd\te"
    executor = FakeExecutor(fetch=fetched((dirty, [dirty, 1]), (None, {"note": dirty})))

    outcome = answered(await run(executor))

    assert outcome.rows == ((clean, [clean, 1]), (None, {"note": clean}))


async def test_invisible_and_direction_characters_are_stripped() -> None:
    executor = FakeExecutor(
        fetch=fetched(
            (1, "Ja\u202epan\u200b"),
        )
    )

    outcome = answered(await run(executor))

    assert outcome.rows == ((1, "Japan"),)


async def test_column_names_and_struct_keys_are_cleaned_too() -> None:
    result = Fetched(
        columns=("id\x1b[2J", "item"),
        rows=((1, {"na\x00me": "shirt"}),),
        bytes_processed=None,
    )

    outcome = answered(await run(FakeExecutor(fetch=result)))

    assert outcome.columns == ("id[2J", "item")
    assert outcome.rows == ((1, {"name": "shirt"}),)


async def test_cells_keep_the_values_the_executor_returned() -> None:
    row = (1, Decimal("9.99"), None)

    outcome = answered(await run(FakeExecutor(fetch=fetched(row))))

    assert outcome.rows == (row,)


# --- failures: only compile-time error text may reach the model


async def test_compile_error_from_the_dry_run_reaches_the_model_cleaned() -> None:
    detail = (
        "Unrecognized name: nope at [1:8]; see https://cloud.google.com/bigquery/docs "
        f"for projects/{PROJECT}/jobs/abc\nsecond line " + "x" * 500
    )
    executor = FakeExecutor(estimate=QueryRejected(detail))

    outcome = refused(await run(executor))

    assert executor.fetches == []
    assert outcome.log.status == "sql_error"
    assert "Unrecognized name: nope" in outcome.message
    assert "[1:8]" not in outcome.message
    assert "https://" not in outcome.message
    assert PROJECT not in outcome.message
    assert "\n" not in outcome.message
    assert len(outcome.message) <= 300


async def test_error_text_from_the_real_run_never_reaches_the_model() -> None:
    # BigQuery may evaluate the model's WHERE on rows outside the brand scope,
    # so a runtime error message can carry their values.
    executor = FakeExecutor(fetch=QueryRejected("LEAK:36/China"))

    outcome = refused(await run(executor))

    assert outcome.log.status == "runtime_error"
    assert "LEAK" not in outcome.message
    assert "China" not in outcome.message
    assert outcome.log.detail == "LEAK:36/China"
    assert outcome.log.executed_sql is not None


async def test_query_estimated_over_the_byte_budget_is_not_executed() -> None:
    executor = FakeExecutor(estimate=2_000_000)

    outcome = refused(await run(executor, max_bytes=1_000_000))

    assert executor.fetches == []
    assert outcome.log.status == "too_expensive"


async def test_slow_query_is_refused_as_a_timeout() -> None:
    outcome = refused(await run(FakeExecutor(fetch=TimeoutError())))

    assert outcome.log.status == "timeout"


async def test_slow_estimate_is_a_warehouse_problem_not_a_slow_query() -> None:
    outcome = refused(await run(FakeExecutor(estimate=TimeoutError())))

    assert outcome.log.status == "unavailable"


@pytest.mark.parametrize("phase", ["estimate", "fetch"])
async def test_any_other_error_is_a_refusal_with_its_own_text_in_the_log(
    phase: str, caplog: pytest.LogCaptureFixture
) -> None:
    executor = failing(phase, PermissionError(f"access denied in projects/{PROJECT}"))

    with caplog.at_level(logging.ERROR):
        outcome = refused(await run(executor))

    assert not caplog.records

    assert outcome.log.status == "unavailable"
    assert "access denied" not in outcome.message
    assert outcome.log.detail == "PermissionError: access denied in projects/[redacted]"


async def test_bug_in_our_own_code_is_refused_and_logged_with_its_traceback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def crash(_: str) -> str:
        raise TypeError("our own bug")

    monkeypatch.setattr("retail_agent.query.warehouse.safe_text", crash)

    with caplog.at_level(logging.ERROR):
        outcome = refused(await run(FakeExecutor()))

    assert outcome.log.status == "unavailable"
    assert outcome.log.detail == "TypeError: our own bug"
    assert caplog.records[0].exc_info


@pytest.mark.parametrize(
    "error",
    [RuntimeError("no project\n\nLocation: None"), QueryRejected("no project\n\nLocation: None")],
)
async def test_log_detail_is_always_one_line(error: Exception) -> None:
    outcome = refused(await run(FakeExecutor(estimate=error)))

    assert outcome.log.detail is not None
    assert outcome.log.detail.endswith("no project Location: None")


async def test_compile_error_without_usable_text_is_still_a_sql_error() -> None:
    executor = FakeExecutor(estimate=QueryRejected("https://cloud.google.com/bigquery"))

    outcome = refused(await run(executor))

    assert outcome.log.status == "sql_error"
    assert outcome.message


async def test_empty_secret_changes_nothing() -> None:
    executor = FakeExecutor(estimate=QueryRejected("Unrecognized name: nope"))

    outcome = refused(await run(executor, secrets=("",)))

    assert outcome.message == "Unrecognized name: nope"
    assert outcome.log.detail == "Unrecognized name: nope"


async def test_guard_crash_is_fixable_and_has_its_own_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def crash(*_: object) -> None:
        raise RuntimeError("guard bug")

    monkeypatch.setattr("retail_agent.query.sql_guard._parse", crash)

    outcome = refused(await run(FakeExecutor()))

    assert outcome.log.status == "sql_error"
    assert outcome.log.reject_code == "guard_error"


async def test_refusal_for_an_oversized_row_is_not_marked_as_truncated() -> None:
    rows = tuple((n, "x" * 5_000) for n in range(MANAGER.row_limit + 1))

    outcome = refused(await run(FakeExecutor(fetch=fetched(*rows)), max_result_chars=1_000))

    assert outcome.log.status == "too_large"
    assert outcome.log.truncated is None
    assert outcome.log.detail == "one row is longer than 1000 characters"


async def test_every_refusal_is_logged_with_its_cause(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        await run(FakeExecutor(estimate=RuntimeError("no credentials found")))

    assert "status=unavailable" in caplog.text
    assert "no credentials found" in caplog.text


async def test_log_file_never_gets_the_runtime_error_text_of_a_brand_manager(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        await run(FakeExecutor(fetch=QueryRejected("LEAK:36/China")))

    assert "status=runtime_error" in caplog.text
    assert "LEAK" not in caplog.text
