from dataclasses import dataclass
from typing import Protocol

from retail_agent.sql_guard import AllowedQuery

type Cell = object
type Row = tuple[Cell, ...]


@dataclass(frozen=True)
class Fetched:
    columns: tuple[str, ...]
    rows: tuple[Row, ...]
    bytes_processed: int | None
    job_id: str | None = None


class QueryRejected(Exception):
    """The warehouse read the query and refused it. The text is the warehouse's own."""


class QueryExecutor(Protocol):
    """Runs guarded queries.

    Raises QueryRejected when the warehouse refuses the query itself and TimeoutError
    when `fetch` waits too long. Any other exception means the warehouse cannot be reached.
    """

    async def estimate_bytes(self, query: AllowedQuery) -> int: ...

    async def fetch(self, query: AllowedQuery, max_rows: int) -> Fetched: ...
