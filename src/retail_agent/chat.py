from typing import Protocol

GREETING = "Retail Analyst Agent. Type 'exit' to quit."


class Agent(Protocol):
    def reply(self, message: str) -> str: ...


class Terminal(Protocol):
    def read(self) -> str | None:
        """Return the next message, or None when the Executive leaves."""
        ...

    def show(self, text: str) -> None: ...


class Chat:
    def __init__(self, agent: Agent, terminal: Terminal) -> None:
        self._agent = agent
        self._terminal = terminal

    def run(self) -> None:
        self._terminal.show(GREETING)
        while (message := self._terminal.read()) is not None:
            self._terminal.show(self._agent.reply(message))
