import sqlite3
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from retail_agent.domain.report import Report

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    deleted_at TEXT
);
"""
COLUMNS = "id, conversation_id, title, body, created_at"


class ReportsUnavailable(Exception):
    def __init__(self, database: Path, cause: Exception) -> None:
        super().__init__(f"Cannot use the report database at {database}: {cause}.")


class ReportRepository:
    """The report library kept in the local SQLite database."""

    def __init__(self, database: Path) -> None:
        self._database = database
        try:
            database.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ReportsUnavailable(database, error) from error
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def add(self, owner: str, conversation_id: str, title: str, body: str) -> Report:
        created_at = datetime.now(UTC)
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO reports (owner, conversation_id, title, body, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (owner, conversation_id, title, body, created_at.isoformat()),
            )
        assert cursor.lastrowid is not None
        return Report(cursor.lastrowid, owner, conversation_id, title, body, created_at)

    def find(
        self,
        owner: str,
        *,
        mentioning: str | None = None,
        conversation_id: str | None = None,
        ids: Iterable[int] | None = None,
    ) -> list[Report]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {COLUMNS} FROM reports WHERE owner = ? AND deleted_at IS NULL ORDER BY id",
                (owner,),
            ).fetchall()
        reports = [
            Report(report_id, owner, conversation, title, body, datetime.fromisoformat(created))
            for report_id, conversation, title, body, created in rows
        ]
        if mentioning is not None:
            reports = [report for report in reports if _mentions(report, mentioning)]
        if conversation_id is not None:
            reports = [report for report in reports if report.conversation_id == conversation_id]
        if ids is not None:
            wanted = set(ids)
            reports = [report for report in reports if report.id in wanted]
        return reports

    def delete(self, owner: str, ids: Iterable[int]) -> int:
        deleted_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            cursor = connection.executemany(
                "UPDATE reports SET deleted_at = ? "
                "WHERE id = ? AND owner = ? AND deleted_at IS NULL",
                [(deleted_at, report_id, owner) for report_id in ids],
            )
        return cursor.rowcount

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(self._database)
            try:
                with connection:
                    yield connection
            finally:
                connection.close()
        except sqlite3.Error as error:
            raise ReportsUnavailable(self._database, error) from error


def _mentions(report: Report, text: str) -> bool:
    needle = text.casefold()
    return needle in report.title.casefold() or needle in report.body.casefold()
