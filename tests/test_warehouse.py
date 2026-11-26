import logging
from decimal import Decimal

import pytest

from retail_agent.policy import AllBrands, Brands, Policy
from retail_agent.query_executor import Estimate, Failed, FailureKind, Fetched, Row
from retail_agent.sql_guard import Allowed, Rejected, check
from retail_agent.warehouse import Answered, Refused, Warehouse

PROJECT = "acme-project-123"
CEO = Policy(scope=AllBrands())
MANAGER = Policy(scope=Brands(frozenset({"Diesel"})), row_limit=3)
QUERY = "SELECT id, country FROM users"
ROW = (1, "Japan")


def fetched(*rows: Row) -> Fetched:
    return Fetched(columns=("id", "country"), rows=rows, bytes_processed=2_048)


class FakeExecutor:
    """Answers with what the test scripted and records what it was asked."""

    def __init__(
        self,
        dry_run: Estimate | Failed | Exception | None = None,
        execute: Fetched | Failed | Exception | None = None,
    ) -> None:
        self._dry_run = dry_run or Estimate(bytes_processed=1_000)
        self._execute = execute or fetched(ROW)
        self.dry_runs: list[Allowed] = []
        self.executions: list[tuple[Allowed, int]] = []

    def dry_run(self, query: Allowed) -> Estimate | Failed:
        self.dry_runs.append(query)
        if isinstance(self._dry_run, Exception):
            raise self._dry_run
        return self._dry_run

    def execute(self, query: Allowed, max_rows: int) -> Fetched | Failed:
        self.executions.append((query, max_rows))
        if isinstance(self._execute, Exception):
            raise self._execute
        return self._execute


def failing(phase: str, failure: Failed | Exception) -> FakeExecutor:
    return FakeExecutor(dry_run=failure) if phase == "dry_run" else FakeExecutor(execute=failure)


def run(
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
    return warehouse.run(sql)


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
def test_rejected_query_never_reaches_the_executor(sql: str, status: str, code: str) -> None:
    executor = FakeExecutor()
    verdict = check(sql, MANAGER)
    assert isinstance(verdict, Rejected)

    outcome = refused(run(executor, sql))

    assert executor.dry_runs == []
    assert executor.executions == []
    assert outcome.message == verdict.message
    assert outcome.log.status == status
    assert outcome.log.reject_code == code
    assert outcome.log.original_sql == sql
    assert outcome.log.executed_sql is None


def test_executor_gets_the_guarded_sql_and_one_row_over_the_limit() -> None:
    executor = FakeExecutor()
    guarded = check(QUERY, MANAGER)
    assert isinstance(guarded, Allowed)

    outcome = answered(run(executor))

    assert "Diesel" in guarded.sql
    assert executor.dry_runs == [guarded]
    assert executor.executions == [(guarded, MANAGER.row_limit + 1)]
    assert outcome.log.original_sql == QUERY
    assert outcome.log.executed_sql == guarded.sql


# --- results


def test_answer_carries_columns_rows_and_a_log_record() -> None:
    result = Fetched(
        columns=("id", "country"),
        rows=((1, "Japan"), (2, "Brasil")),
        bytes_processed=2_048,
        cache_hit=True,
        job_id="job-1",
    )

    outcome = answered(run(FakeExecutor(execute=result)))

    assert outcome.columns == ("id", "country")
    assert outcome.rows == ((1, "Japan"), (2, "Brasil"))
    log = outcome.log
    assert log.status == "ok"
    assert log.row_count == 2
    assert log.truncated is None
    assert log.bytes_processed == 2_048
    assert log.cache_hit is True
    assert log.job_id == "job-1"
    assert log.reject_code is None
    assert log.detail is None
    assert log.elapsed_ms >= 0


def test_zero_rows_is_an_answer_with_status_no_data() -> None:
    outcome = answered(run(FakeExecutor(execute=fetched())))

    assert outcome.rows == ()
    assert outcome.columns == ("id", "country")
    assert outcome.log.status == "no_data"


def test_rows_over_the_limit_are_cut_and_marked() -> None:
    rows = tuple((n, "Japan") for n in range(MANAGER.row_limit + 1))

    outcome = answered(run(FakeExecutor(execute=fetched(*rows))))

    assert outcome.rows == rows[: MANAGER.row_limit]
    assert outcome.log.truncated == "rows"
    assert outcome.log.row_count == MANAGER.row_limit


def test_exactly_the_limit_is_not_marked_as_cut() -> None:
    rows = tuple((n, "Japan") for n in range(MANAGER.row_limit))

    outcome = answered(run(FakeExecutor(execute=fetched(*rows))))

    assert outcome.rows == rows
    assert outcome.log.truncated is None


def test_result_over_the_size_cap_loses_trailing_rows() -> None:
    rows = tuple((n, "x" * 100) for n in range(50))

    outcome = answered(
        run(FakeExecutor(execute=fetched(*rows)), policy=CEO, max_result_chars=1_000)
    )

    assert 0 < len(outcome.rows) < 50
    assert outcome.rows == rows[: len(outcome.rows)]
    assert size(outcome.rows) <= 1_000
    assert outcome.log.truncated == "size"
    assert outcome.log.row_count == len(outcome.rows)


def test_single_row_over_the_size_cap_is_refused() -> None:
    executor = FakeExecutor(execute=fetched((1, "x" * 5_000)))

    outcome = refused(run(executor, max_result_chars=1_000))

    assert outcome.log.status == "too_large"
    assert "xxx" not in outcome.message


def test_control_characters_are_stripped_from_text_cells() -> None:
    dirty = "a\x00b\x1b[31mc\nd\te"
    clean = "ab[31mc\nd\te"
    executor = FakeExecutor(execute=fetched((dirty, [dirty, 1]), (None, {"note": dirty})))

    outcome = answered(run(executor))

    assert outcome.rows == ((clean, [clean, 1]), (None, {"note": clean}))


def test_invisible_and_direction_characters_are_stripped() -> None:
    executor = FakeExecutor(
        execute=fetched(
            (1, "Ja\u202epan\u200b"),
        )
    )

    outcome = answered(run(executor))

    assert outcome.rows == ((1, "Japan"),)


def test_column_names_and_struct_keys_are_cleaned_too() -> None:
    result = Fetched(
        columns=("id\x1b[2J", "item"),
        rows=((1, {"na\x00me": "shirt"}),),
        bytes_processed=None,
    )

    outcome = answered(run(FakeExecutor(execute=result)))

    assert outcome.columns == ("id[2J", "item")
    assert outcome.rows == ((1, {"name": "shirt"}),)


def test_cells_keep_the_values_the_executor_returned() -> None:
    row = (1, Decimal("9.99"), None)

    outcome = answered(run(FakeExecutor(execute=fetched(row))))

    assert outcome.rows == (row,)


# --- failures: only compile-time error text may reach the model


def test_compile_error_from_the_dry_run_reaches_the_model_cleaned() -> None:
    detail = (
        "Unrecognized name: nope at [1:8]; see https://cloud.google.com/bigquery/docs "
        f"for projects/{PROJECT}/jobs/abc\nsecond line " + "x" * 500
    )
    executor = FakeExecutor(dry_run=Failed("invalid_query", detail))

    outcome = refused(run(executor))

    assert executor.executions == []
    assert outcome.log.status == "sql_error"
    assert "Unrecognized name: nope" in outcome.message
    assert "[1:8]" not in outcome.message
    assert "https://" not in outcome.message
    assert PROJECT not in outcome.message
    assert "\n" not in outcome.message
    assert len(outcome.message) <= 300


def test_error_text_from_the_real_run_never_reaches_the_model() -> None:
    # BigQuery may evaluate the model's WHERE on rows outside the brand scope,
    # so a runtime error message can carry their values.
    executor = FakeExecutor(execute=Failed("invalid_query", "LEAK:36/China"))

    outcome = refused(run(executor))

    assert outcome.log.status == "runtime_error"
    assert "LEAK" not in outcome.message
    assert "China" not in outcome.message
    assert outcome.log.detail == "LEAK:36/China"
    assert outcome.log.executed_sql is not None


def test_query_estimated_over_the_byte_budget_is_not_executed() -> None:
    executor = FakeExecutor(dry_run=Estimate(bytes_processed=2_000_000))

    outcome = refused(run(executor, max_bytes=1_000_000))

    assert executor.executions == []
    assert outcome.log.status == "too_expensive"


@pytest.mark.parametrize("phase", ["dry_run", "execute"])
@pytest.mark.parametrize("kind", ["too_expensive", "timeout", "unavailable", "misconfigured"])
def test_other_failures_get_a_fixed_message_and_a_redacted_log(
    phase: str, kind: FailureKind
) -> None:
    executor = failing(phase, Failed(kind, f"raw cause in projects/{PROJECT}/jobs/abc"))

    outcome = refused(run(executor))

    assert outcome.log.status == kind
    assert outcome.message
    assert "raw cause" not in outcome.message
    assert outcome.log.detail is not None
    assert "raw cause" in outcome.log.detail
    assert PROJECT not in outcome.log.detail


@pytest.mark.parametrize("phase", ["dry_run", "execute"])
def test_executor_that_raises_becomes_a_refusal(
    phase: str, caplog: pytest.LogCaptureFixture
) -> None:
    executor = failing(phase, RuntimeError(f"boom {PROJECT}"))

    with caplog.at_level(logging.ERROR):
        outcome = refused(run(executor))

    assert outcome.log.status == "unavailable"
    assert "boom" not in outcome.message
    assert outcome.log.detail == "RuntimeError: boom [redacted]"
    assert caplog.records


def test_compile_error_without_usable_text_is_still_a_sql_error() -> None:
    executor = FakeExecutor(dry_run=Failed("invalid_query", "https://cloud.google.com/bigquery"))

    outcome = refused(run(executor))

    assert outcome.log.status == "sql_error"
    assert outcome.message


def test_empty_secret_changes_nothing() -> None:
    executor = FakeExecutor(dry_run=Failed("invalid_query", "Unrecognized name: nope"))

    outcome = refused(run(executor, secrets=("",)))

    assert outcome.message == "Unrecognized name: nope"
    assert outcome.log.detail == "Unrecognized name: nope"


def test_failed_run_keeps_its_job_id() -> None:
    executor = FakeExecutor(execute=Failed("timeout", "deadline exceeded", job_id="job-9"))

    outcome = refused(run(executor))

    assert outcome.log.job_id == "job-9"


def test_guard_crash_is_fixable_and_has_its_own_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def crash(*_: object) -> None:
        raise RuntimeError("guard bug")

    monkeypatch.setattr("retail_agent.sql_guard._parse", crash)

    outcome = refused(run(FakeExecutor()))

    assert outcome.log.status == "sql_error"
    assert outcome.log.reject_code == "guard_error"


def test_refusal_for_an_oversized_row_is_not_marked_as_truncated() -> None:
    rows = tuple((n, "x" * 5_000) for n in range(MANAGER.row_limit + 1))

    outcome = refused(run(FakeExecutor(execute=fetched(*rows)), max_result_chars=1_000))

    assert outcome.log.status == "too_large"
    assert outcome.log.truncated is None
    assert outcome.log.detail == "one row is longer than 1000 characters"
