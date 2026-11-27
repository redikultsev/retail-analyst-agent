import logging
from typing import Protocol

from retail_agent.domain.policy import describe
from retail_agent.domain.profile import Profile
from retail_agent.domain.report import DeletionRequest, ReportSummary
from retail_agent.query.sanitize import one_line, safe_text

logger = logging.getLogger(__name__)

FAILED_REPLY = "I could not answer that. Please try again or rephrase the question."
NOTHING_DELETED = "Nothing was deleted."
UNFINISHED_REPLY = (
    "I could not finish the answer. Ask what reports you have to see the current list."
)
MAX_TITLE_CHARS = 80


class Agent(Protocol):
    async def reply(self, message: str) -> str | DeletionRequest: ...

    async def resume(self, agreed: bool) -> str:
        """Continue after a deletion request with the person's answer."""
        ...


class Terminal(Protocol):
    def read(self) -> str | None:
        """Return the next message, or None when the Executive leaves."""
        ...

    def show(self, text: str) -> None: ...

    def show_reply(self, markdown: str) -> None: ...

    def confirm(self, question: str) -> bool:
        """Ask a yes-or-no question. Only a clear yes counts as agreement."""
        ...


class Chat:
    def __init__(self, agent: Agent, terminal: Terminal, profile: Profile) -> None:
        self._agent = agent
        self._terminal = terminal
        self._profile = profile

    async def run(self) -> None:
        self._terminal.show(greeting(self._profile))
        while (message := self._terminal.read()) is not None:
            try:
                reply = await self._answer(message)
            except Exception:
                logger.exception("the agent failed on a message")
                self._terminal.show(FAILED_REPLY)
            else:
                self._terminal.show_reply(reply)

    async def _answer(self, message: str) -> str:
        outcome = await self._agent.reply(message)
        if isinstance(outcome, str):
            return outcome
        agreed = self._terminal.confirm(deletion_question(outcome))
        if not agreed:
            self._terminal.show(NOTHING_DELETED)
        try:
            return await self._agent.resume(agreed)
        except Exception:
            # The person answered, so the reports may already be deleted. Saying only
            # "I could not answer that" would be wrong here.
            logger.exception("the agent failed after a deletion request was answered")
            return UNFINISHED_REPLY


def greeting(profile: Profile) -> str:
    return (
        f"Retail Analyst Agent. Signed in as {profile.name}, {profile.role}. "
        f"Scope: {describe(profile.scope)}. Type 'exit' to quit."
    )


def deletion_question(request: DeletionRequest) -> str:
    reports = request.reports
    lines = [
        f"  {number}. {_title(report)} ({report.created})"
        for number, report in enumerate(reports, start=1)
    ]
    which = "this report" if len(reports) == 1 else f"these {len(reports)} reports"
    return "\n".join([*lines, f"Delete {which}?"])


def _title(report: ReportSummary) -> str:
    return one_line(safe_text(report.title))[:MAX_TITLE_CHARS]
