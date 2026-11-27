from rich.console import Console
from rich.table import Table
from rich.text import Text

from retail_agent.policy import AllBrands, Brands
from retail_agent.terminal import print_plain
from retail_agent.warehouse import Answered, QueryLog, Refused, shareable_detail


def print_outcome(console: Console, outcome: Answered | Refused, scope: AllBrands | Brands) -> None:
    log = outcome.log
    if log.executed_sql:
        print_plain(console, log.executed_sql, soft_wrap=True)
    if isinstance(outcome, Answered):
        table = Table()
        for name in outcome.columns:
            table.add_column(Text(name))
        for row in outcome.rows:
            table.add_row(*(Text(str(cell)) for cell in row))
        console.print(table)
    else:
        print_plain(console, outcome.message, soft_wrap=True)
    print_plain(console, _log_line(log, shareable_detail(log, scope)), soft_wrap=True)


def _log_line(log: QueryLog, detail: str | None) -> str:
    fields = {
        "status": log.status,
        "reject_code": log.reject_code,
        "rows": log.row_count,
        "truncated": log.truncated,
        "bytes": log.bytes_processed,
        "elapsed_ms": log.elapsed_ms,
        "job_id": log.job_id,
        "detail": detail,
    }
    return " ".join(f"{name}={value}" for name, value in fields.items() if value is not None)
