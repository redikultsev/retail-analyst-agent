import logging
import time
from dataclasses import dataclass
from typing import Literal, cast

from retail_agent.policy import AllBrands, Brands, Policy
from retail_agent.query_executor import Cell, Fetched, QueryExecutor, QueryRejected, Row
from retail_agent.sanitize import error_text, one_line, redact, safe_text
from retail_agent.sql_guard import AllowedQuery, RejectCode, Rejected, check

logger = logging.getLogger(__name__)

RefusalStatus = Literal[
    "denied",
    "sql_error",
    "runtime_error",
    "too_expensive",
    "too_large",
    "timeout",
    "unavailable",
]
Status = Literal["ok", "no_data"] | RefusalStatus
TruncatedBy = Literal["rows", "size"]

REJECTS_THE_MODEL_CAN_FIX: frozenset[RejectCode] = frozenset(
    {"sql_error", "multiple_statements", "unsupported_construct", "guard_error"}
)

MESSAGES: dict[RefusalStatus, str] = {
    "denied": "This query is not allowed.",
    "sql_error": "The query is not valid BigQuery SQL. Check the names and syntax.",
    "runtime_error": (
        "The query failed while running. Typical causes: division by zero, a failed CAST "
        "or an invalid date. Use SAFE_CAST, SAFE_DIVIDE or NULLIF and try again."
    ),
    "too_expensive": "The query would read too much data. Filter by date or aggregate earlier.",
    "too_large": "The result is too large. Aggregate or select fewer columns.",
    "timeout": "The query took too long and was cancelled. Simplify it or narrow the period.",
    "unavailable": (
        "The data warehouse cannot be reached. Do not retry; "
        "tell the user that the connection or the setup has to be checked."
    ),
}


@dataclass
class QueryLog:
    original_sql: str
    status: Status
    elapsed_ms: int = 0
    executed_sql: str | None = None
    reject_code: RejectCode | None = None
    row_count: int | None = None
    truncated: TruncatedBy | None = None
    bytes_processed: int | None = None
    job_id: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class Answered:
    columns: tuple[str, ...]
    rows: tuple[Row, ...]
    log: QueryLog


@dataclass(frozen=True)
class Refused:
    message: str
    log: QueryLog


class _Refuse(Exception):
    def __init__(
        self, status: RefusalStatus, message: str | None = None, *, detail: str | None = None
    ) -> None:
        super().__init__(status)
        self.status: RefusalStatus = status
        self.message = message or MESSAGES[status]
        self.detail = detail


class Warehouse:
    def __init__(
        self,
        executor: QueryExecutor,
        policy: Policy,
        *,
        max_bytes: int,
        max_result_chars: int,
        secrets: tuple[str, ...],
    ) -> None:
        self._executor = executor
        self._policy = policy
        self._max_bytes = max_bytes
        self._max_result_chars = max_result_chars
        self._secrets = secrets

    @property
    def scope(self) -> AllBrands | Brands:
        return self._policy.scope

    async def run(self, sql: str) -> Answered | Refused:
        log = QueryLog(original_sql=sql, status="unavailable")
        started = time.monotonic()
        try:
            outcome = await self._answer(sql, log)
        except _Refuse as refuse:
            log.status = refuse.status
            log.detail = self._log_text(refuse.detail)
            outcome = Refused(refuse.message, log)
        except Exception as error:
            logger.exception("warehouse failed on a query")
            log.status = "unavailable"
            log.detail = self._log_text(_describe(error))
            outcome = Refused(MESSAGES["unavailable"], log)
        log.elapsed_ms = int((time.monotonic() - started) * 1000)
        return outcome

    async def _answer(self, sql: str, log: QueryLog) -> Answered:
        query = self._guard(sql, log)
        await self._check_cost(query, log)
        fetched = await self._fetch(query, log)
        columns = tuple(safe_text(name) for name in fetched.columns)
        rows = tuple(tuple(_safe_cell(cell) for cell in row) for row in fetched.rows)
        rows = self._truncate(rows, log)
        log.status = "ok" if rows else "no_data"
        log.row_count = len(rows)
        return Answered(columns, rows, log)

    def _guard(self, sql: str, log: QueryLog) -> AllowedQuery:
        verdict = check(sql, self._policy)
        if isinstance(verdict, Rejected):
            log.reject_code = verdict.code
            status = "sql_error" if verdict.code in REJECTS_THE_MODEL_CAN_FIX else "denied"
            raise _Refuse(status, verdict.message)
        log.executed_sql = verdict.sql
        return verdict

    async def _check_cost(self, query: AllowedQuery, log: QueryLog) -> None:
        try:
            estimate = await self._executor.estimate_bytes(query)
        except QueryRejected as rejected:
            text = str(rejected)
            raise _Refuse("sql_error", error_text(text, self._secrets), detail=text) from rejected
        except Exception as error:
            raise _Refuse("unavailable", detail=_describe(error)) from error
        if estimate > self._max_bytes:
            detail = f"estimated {estimate} bytes, budget {self._max_bytes}"
            raise _Refuse("too_expensive", detail=detail)

    async def _fetch(self, query: AllowedQuery, log: QueryLog) -> Fetched:
        try:
            fetched = await self._executor.fetch(query, self._policy.row_limit + 1)
        except QueryRejected as rejected:
            # BigQuery may evaluate the model's conditions on rows outside the brand scope,
            # so the text of a runtime error can carry their values. It stays in the log.
            raise _Refuse("runtime_error", detail=str(rejected)) from rejected
        except TimeoutError as error:
            raise _Refuse("timeout") from error
        except Exception as error:
            raise _Refuse("unavailable", detail=_describe(error)) from error
        log.bytes_processed = fetched.bytes_processed
        log.job_id = fetched.job_id
        return fetched

    def _log_text(self, detail: str | None) -> str | None:
        return one_line(redact(detail, self._secrets)) if detail else None

    def _truncate(self, rows: tuple[Row, ...], log: QueryLog) -> tuple[Row, ...]:
        within_limit = rows[: self._policy.row_limit]
        kept: list[Row] = []
        size = 0
        for row in within_limit:
            size += sum(len(str(cell)) for cell in row)
            if size > self._max_result_chars:
                break
            kept.append(row)
        if within_limit and not kept:
            detail = f"one row is longer than {self._max_result_chars} characters"
            raise _Refuse("too_large", detail=detail)
        if len(kept) < len(within_limit):
            log.truncated = "size"
        elif len(within_limit) < len(rows):
            log.truncated = "rows"
        return tuple(kept)


def _describe(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"


def _safe_cell(cell: Cell) -> Cell:
    if isinstance(cell, str):
        return safe_text(cell)
    if isinstance(cell, list):
        return [_safe_cell(item) for item in cast(list[object], cell)]
    if isinstance(cell, dict):
        items = cast(dict[object, object], cell).items()
        return {safe_text(str(key)): _safe_cell(value) for key, value in items}
    return cell
