from dataclasses import dataclass
from typing import Literal, Protocol

from retail_agent.sql_guard import Allowed

type Cell = bool | int | float | str | list[Cell] | dict[str, Cell] | None
type Row = tuple[Cell, ...]

FailureKind = Literal["invalid_query", "too_expensive", "timeout", "unavailable", "misconfigured"]


@dataclass(frozen=True)
class Estimate:
    bytes_processed: int


@dataclass(frozen=True)
class Fetched:
    columns: tuple[str, ...]
    rows: tuple[Row, ...]
    bytes_processed: int | None
    cache_hit: bool = False
    job_id: str | None = None


@dataclass(frozen=True)
class Failed:
    kind: FailureKind
    detail: str
    job_id: str | None = None


class SqlExecutor(Protocol):
    def dry_run(self, query: Allowed) -> Estimate | Failed: ...

    def execute(self, query: Allowed, max_rows: int) -> Fetched | Failed: ...
