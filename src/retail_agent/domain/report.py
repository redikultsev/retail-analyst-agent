from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Report:
    id: int
    owner: str
    conversation_id: str
    title: str
    body: str
    created_at: datetime


@dataclass(frozen=True)
class ReportSummary:
    id: int
    title: str
    created: str


@dataclass(frozen=True)
class DeletionRequest:
    """The agent asks to delete these reports. Nothing is deleted until a person agrees."""

    reports: tuple[ReportSummary, ...]


class ReportLibrary(Protocol):
    """Saved reports. Every read and write is limited to one owner."""

    def add(self, owner: str, conversation_id: str, title: str, body: str) -> Report: ...

    def find(
        self,
        owner: str,
        *,
        mentioning: str | None = None,
        conversation_id: str | None = None,
        ids: Iterable[int] | None = None,
    ) -> list[Report]: ...

    def delete(self, owner: str, ids: Iterable[int]) -> int:
        """Mark the owner's reports as deleted and return how many were marked."""
        ...
