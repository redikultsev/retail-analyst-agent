from typing import Protocol

from retail_agent.policy import describe
from retail_agent.profile import Profile


class Agent(Protocol):
    def reply(self, message: str) -> str: ...


class Terminal(Protocol):
    def read(self) -> str | None:
        """Return the next message, or None when the Executive leaves."""
        ...

    def show(self, text: str) -> None: ...


class Chat:
    def __init__(self, agent: Agent, terminal: Terminal, profile: Profile) -> None:
        self._agent = agent
        self._terminal = terminal
        self._profile = profile

    def run(self) -> None:
        self._terminal.show(greeting(self._profile))
        while (message := self._terminal.read()) is not None:
            self._terminal.show(self._agent.reply(message))


def greeting(profile: Profile) -> str:
    return (
        f"Retail Analyst Agent. Signed in as {profile.name}, {profile.role}. "
        f"Scope: {describe(profile.scope)}. Type 'exit' to quit."
    )
