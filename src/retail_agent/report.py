from dataclasses import dataclass
from datetime import datetime


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
