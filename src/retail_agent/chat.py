import logging
from typing import Protocol

from retail_agent.policy import describe
from retail_agent.profile import Profile

logger = logging.getLogger(__name__)

FAILED_REPLY = "I could not answer that. Please try again or rephrase the question."


class Agent(Protocol):
    async def reply(self, message: str) -> str: ...


class Terminal(Protocol):
    def read(self) -> str | None:
        """Return the next message, or None when the Executive leaves."""
        ...

    def show(self, text: str) -> None: ...

    def show_reply(self, markdown: str) -> None: ...


class Chat:
    def __init__(self, agent: Agent, terminal: Terminal, profile: Profile) -> None:
        self._agent = agent
        self._terminal = terminal
        self._profile = profile

    async def run(self) -> None:
        self._terminal.show(greeting(self._profile))
        while (message := self._terminal.read()) is not None:
            try:
                reply = await self._agent.reply(message)
            except Exception:
                logger.exception("the agent failed on a message")
                self._terminal.show(FAILED_REPLY)
            else:
                self._terminal.show_reply(reply)


def greeting(profile: Profile) -> str:
    return (
        f"Retail Analyst Agent. Signed in as {profile.name}, {profile.role}. "
        f"Scope: {describe(profile.scope)}. Type 'exit' to quit."
    )
