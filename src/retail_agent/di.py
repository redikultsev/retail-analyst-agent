from datetime import date

from langchain_google_genai import ChatGoogleGenerativeAI
from rich.console import Console

from retail_agent.bigquery_executor import BigQueryExecutor
from retail_agent.chat import Chat
from retail_agent.config import Settings
from retail_agent.langchain_agent import LangChainAgent
from retail_agent.policy import Policy
from retail_agent.profile import Profile
from retail_agent.profile_repository import ProfileRepository
from retail_agent.prompt import system_prompt
from retail_agent.terminal import RichTerminal
from retail_agent.warehouse import Warehouse

MODEL_RETRIES = 2
MODEL_TIMEOUT_S = 60


def build_profile_repository(settings: Settings) -> ProfileRepository:
    return ProfileRepository(settings.data_dir / "retail_agent.db")


def build_console() -> Console:
    return Console()


def build_chat(settings: Settings, profile: Profile, warehouse: Warehouse) -> Chat:
    agent = build_agent(settings, profile, warehouse)
    return Chat(agent, RichTerminal(build_console()), profile)


def build_agent(settings: Settings, profile: Profile, warehouse: Warehouse) -> LangChainAgent:
    return LangChainAgent(
        _build_model(settings, settings.gemini_model),
        _build_model(settings, settings.gemini_fallback_model),
        warehouse,
        system_prompt(profile, date.today()),
        max_model_calls=settings.agent_max_model_calls,
        max_queries=settings.agent_max_queries,
        timeout_s=settings.agent_timeout_s,
    )


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


def _build_model(settings: Settings, name: str) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=name,
        api_key=settings.google_api_key,
        max_retries=MODEL_RETRIES,
        timeout=MODEL_TIMEOUT_S,
    )
