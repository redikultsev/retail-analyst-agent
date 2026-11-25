"""Composition root: the only place that creates real objects and wires them together."""

from rich.console import Console

from retail_agent.chat import Chat
from retail_agent.config import Settings
from retail_agent.terminal import RichTerminal


class _PlaceholderAgent:
    def reply(self, message: str) -> str:
        return "The agent is not connected yet."


def build_chat(settings: Settings) -> Chat:
    agent = _PlaceholderAgent()
    terminal = RichTerminal(Console())
    return Chat(agent, terminal)
