from rich.console import Console

from retail_agent.bigquery_executor import BigQueryExecutor
from retail_agent.chat import Chat
from retail_agent.config import Settings
from retail_agent.policy import Policy
from retail_agent.profile import Profile
from retail_agent.profile_repository import ProfileRepository
from retail_agent.terminal import RichTerminal
from retail_agent.warehouse import Warehouse


class _PlaceholderAgent:
    def reply(self, message: str) -> str:
        return "The agent is not connected yet."


def build_profile_repository(settings: Settings) -> ProfileRepository:
    return ProfileRepository(settings.data_dir / "retail_agent.db")


def build_console() -> Console:
    return Console()


def build_chat(settings: Settings, profile: Profile) -> Chat:
    agent = _PlaceholderAgent()
    terminal = RichTerminal(build_console())
    return Chat(agent, terminal, profile)


def build_warehouse(settings: Settings, profile: Profile) -> Warehouse:
    executor = BigQueryExecutor(
        settings.google_cloud_project,
        max_bytes_billed=settings.query_max_bytes,
        timeout_s=settings.query_timeout_s,
    )
    return Warehouse(
        executor,
        Policy(scope=profile.scope, row_limit=settings.result_max_rows),
        max_bytes=settings.query_max_bytes,
        max_result_chars=settings.result_max_chars,
        secrets=(settings.google_cloud_project, settings.google_api_key.get_secret_value()),
    )
