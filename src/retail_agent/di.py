"""Composition root: the only place that creates real objects and wires them together."""

from rich.console import Console

from retail_agent.chat import Chat
from retail_agent.config import Settings
from retail_agent.profile import Profile
from retail_agent.profile_repository import ProfileRepository
from retail_agent.terminal import RichTerminal


class _PlaceholderAgent:
    def reply(self, message: str) -> str:
        return "The agent is not connected yet."


def build_profile_repository(settings: Settings) -> ProfileRepository:
    return ProfileRepository(settings.data_dir / "retail_agent.db")


def build_chat(settings: Settings, profile: Profile) -> Chat:
    agent = _PlaceholderAgent()
    terminal = RichTerminal(Console())
    return Chat(agent, terminal, profile)
